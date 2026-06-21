import tempfile
import unittest
from pathlib import Path

from yaml_manager import app


class FileApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        app.PACKAGES_ROOT = root / "packages"
        app.DATA_ROOT = root / "data"
        app.METADATA_FILE = app.DATA_ROOT / "metadata.json"
        app.ensure_directories()

    def tearDown(self):
        self.temporary.cleanup()

    def test_create_update_list_and_delete(self):
        created = app.write_file(
            "licht/abend.yaml",
            "script:\n  abend:\n    sequence: []\n",
            None,
            "Licht",
            create=True,
        )
        self.assertEqual(created["category"], "Licht")
        self.assertEqual(app.list_files()["files"][0]["path"], "licht/abend.yaml")

        updated = app.write_file(
            created["path"],
            "script:\n  abend:\n    mode: single\n    sequence: []\n",
            created["version"],
            "Abend",
            create=False,
        )
        self.assertNotEqual(updated["version"], created["version"])
        self.assertTrue(any((app.DATA_ROOT / "backups").iterdir()))

        app.delete_file(updated["path"], updated["version"])
        self.assertFalse((app.PACKAGES_ROOT / updated["path"]).exists())
        self.assertTrue(any((app.DATA_ROOT / "trash").iterdir()))

    def test_rejects_stale_version(self):
        created = app.write_file("test.yaml", "script: {}\n", None, "Test", create=True)
        with self.assertRaises(app.ApiError) as missing:
            app.write_file("test.yaml", "script: {}\n", None, "Test", create=False)
        self.assertEqual(missing.exception.status, 400)

        (app.PACKAGES_ROOT / "test.yaml").write_text("script:\n  extern: {}\n", encoding="utf-8")
        with self.assertRaises(app.ApiError) as raised:
            app.write_file("test.yaml", "script:\n  lokal: {}\n", created["version"], "Test", create=False)
        self.assertEqual(raised.exception.status, 409)

    def test_rejects_paths_outside_packages(self):
        for invalid in ("../configuration.yaml", ".hidden/test.yaml", "test.txt"):
            with self.subTest(path=invalid), self.assertRaises(app.ApiError):
                app.normalize_relative_path(invalid)

    def test_validation_accepts_ha_tags_and_rejects_duplicate_keys(self):
        valid = app.validate_yaml("sensor: !include sensors.yaml\nsecret: !secret token\n")
        self.assertTrue(valid["valid"])

        invalid = app.validate_yaml("script:\n  test: {}\n  test: {}\n")
        self.assertFalse(invalid["valid"])
        self.assertEqual(invalid["line"], 3)

    def test_detects_packages_in_configuration(self):
        configuration = app.PACKAGES_ROOT.parent / "configuration.yaml"
        configuration.write_text(
            "homeassistant:\n  packages: !include_dir_named packages\n",
            encoding="utf-8",
        )

        status = app.package_configuration_status()

        self.assertTrue(status["configured"])
        self.assertEqual(status["status"], "configured")

    def test_rejects_different_package_directory(self):
        configuration = app.PACKAGES_ROOT.parent / "configuration.yaml"
        configuration.write_text(
            "homeassistant:\n  packages: !include_dir_merge_named andere_packages\n",
            encoding="utf-8",
        )

        status = app.package_configuration_status()

        self.assertFalse(status["configured"])
        self.assertEqual(status["status"], "missing")

    def test_detects_packages_in_included_homeassistant_file(self):
        configuration = app.PACKAGES_ROOT.parent / "configuration.yaml"
        included = app.PACKAGES_ROOT.parent / "homeassistant.yaml"
        configuration.write_text("homeassistant: !include homeassistant.yaml\n", encoding="utf-8")
        included.write_text("packages: !include_dir_named packages\n", encoding="utf-8")

        self.assertTrue(app.package_configuration_status()["configured"])

    def test_reports_invalid_configuration(self):
        configuration = app.PACKAGES_ROOT.parent / "configuration.yaml"
        configuration.write_text("homeassistant: [\n", encoding="utf-8")

        status = app.package_configuration_status()

        self.assertFalse(status["configured"])
        self.assertEqual(status["status"], "invalid")

    def test_tags_are_saved_normalized_and_listed(self):
        created = app.write_file(
            "licht.yaml",
            "script:\n  licht:\n    alias: Licht\n    mode: single\n    sequence: []\n",
            None,
            "Licht",
            create=True,
            tags=["Abend", " abend ", "Wohnzimmer"],
        )

        self.assertEqual(created["tags"], ["Abend", "Wohnzimmer"])
        updated = app.write_file(
            created["path"],
            created["content"].replace("alias: Licht", "alias: Licht neu"),
            created["version"],
            "Licht",
            create=False,
        )
        self.assertEqual(updated["tags"], ["Abend", "Wohnzimmer"])
        listing = app.list_files()
        self.assertEqual(listing["tags"], ["Abend", "Wohnzimmer"])
        self.assertEqual(listing["files"][0]["tags"], ["Abend", "Wohnzimmer"])

    def test_legacy_category_metadata_remains_compatible(self):
        created = app.write_file("legacy.yaml", "script: {}\n", None, "Alt", create=True)
        metadata = app.load_metadata()
        metadata["files"][created["path"]] = "Legacy-Kategorie"
        app.save_metadata(metadata)

        result = app.read_file(created["path"])

        self.assertEqual(result["category"], "Legacy-Kategorie")
        self.assertEqual(result["tags"], [])

    def test_rename_preserves_content_and_metadata(self):
        created = app.write_file(
            "alt.yaml",
            "script:\n  test:\n    sequence: []\n",
            None,
            "Tests",
            create=True,
            tags=["Wichtig"],
        )

        renamed = app.rename_file("alt.yaml", "archiv/neu.yaml", created["version"])

        self.assertFalse((app.PACKAGES_ROOT / "alt.yaml").exists())
        self.assertTrue((app.PACKAGES_ROOT / "archiv/neu.yaml").exists())
        self.assertEqual(renamed["category"], "Tests")
        self.assertEqual(renamed["tags"], ["Wichtig"])

    def test_analysis_detects_duplicate_keys_and_template_blocks(self):
        result = app.analyze_yaml(
            "template:\n  - sensor: []\ntemplate:\n  - binary_sensor: []\n",
            "templates.yaml",
        )

        self.assertFalse(result["validation"]["valid"])
        self.assertEqual(result["findings"][0]["code"], "duplicate-key")
        self.assertEqual(result["findings"][0]["line"], 3)

    def test_analysis_provides_script_and_entity_tips(self):
        result = app.analyze_yaml(
            "script:\n"
            "  Abend-Licht:\n"
            "    sequence:\n"
            "      - action: light.turn_on\n"
            "        target:\n"
            "          entity_id: light.wohnzimmer\n"
            "      - action: light.turn_off\n"
            "        target:\n"
            "          entity_id: light.wohnzimmer\n",
            "abend.yaml",
        )
        codes = {finding["code"] for finding in result["findings"]}

        self.assertTrue(result["validation"]["valid"])
        self.assertIn("script-id", codes)
        self.assertIn("missing-alias", codes)
        self.assertIn("missing-mode", codes)
        self.assertIn("duplicate-entity", codes)

    def test_analysis_detects_script_id_in_another_file(self):
        app.write_file(
            "eins.yaml",
            "script:\n  doppelt:\n    sequence: []\n",
            None,
            "Tests",
            create=True,
        )

        result = app.analyze_yaml(
            "script:\n  doppelt:\n    alias: Zwei\n    mode: single\n    sequence: []\n",
            "zwei.yaml",
        )

        self.assertIn("duplicate-script-id", {item["code"] for item in result["findings"]})


if __name__ == "__main__":
    unittest.main()
