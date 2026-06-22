import base64
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from yaml_manager import app


class FileApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        app.PACKAGES_ROOT = root / "packages"
        app.DATA_ROOT = root / "data"
        app.METADATA_FILE = app.DATA_ROOT / "metadata.json"
        app.GIT_REMOTE_FILE = app.DATA_ROOT / "git_remote.json"
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

    def test_script_dependencies_include_incoming_outgoing_and_definitions(self):
        app.write_file(
            "ziel.yaml",
            "script:\n  ziel:\n    alias: Ziel\n    sequence: []\n",
            None,
            "Tests",
            create=True,
        )
        app.write_file(
            "aufrufer.yaml",
            "script:\n"
            "  aufrufer:\n"
            "    alias: Aufrufer\n"
            "    sequence:\n"
            "      - action: script.ziel\n"
            "      - action: scene.turn_on\n"
            "        target:\n"
            "          entity_id: scene.abend\n"
            "      - condition: template\n"
            "        value_template: \"{{ is_state('light.flur', 'on') }}\"\n",
            None,
            "Tests",
            create=True,
        )

        result = app.script_dependency_analysis("ziel.yaml")

        self.assertEqual(result["summary"]["scripts"], 2)
        self.assertEqual(result["focus"]["scripts"][0]["entityId"], "script.ziel")
        self.assertEqual(result["focus"]["incoming"][0]["source"], "script.aufrufer")
        targets = {item["target"] for item in result["references"]}
        self.assertEqual(targets, {"script.ziel", "scene.abend", "light.flur"})

    def test_script_rename_updates_definition_and_recognized_references(self):
        app.write_file(
            "ziel.yaml",
            "script:\n  'alt':\n    alias: Alt\n    sequence: []\n",
            None,
            "Tests",
            create=True,
        )
        app.write_file(
            "aufrufer.yaml",
            "script:\n"
            "  aufrufer:\n"
            "    description: script.alt bleibt als Beschreibung erhalten\n"
            "    sequence:\n"
            "      - action: script.alt\n"
            "      - action: script.turn_on\n"
            "        target:\n"
            "          entity_id: script.alt\n"
            "      - condition: template\n"
            "        value_template: \"{{ is_state('script.alt', 'on') }}\"\n",
            None,
            "Tests",
            create=True,
        )
        preview = app.preview_script_rename("ziel.yaml", "alt", "neu")

        result = app.rename_script_with_references(
            "ziel.yaml",
            "alt",
            "neu",
            preview["stateVersion"],
        )

        self.assertEqual(result["newEntityId"], "script.neu")
        self.assertIn("'neu':", app.read_file("ziel.yaml")["content"])
        caller = app.read_file("aufrufer.yaml")["content"]
        self.assertEqual(caller.count("script.neu"), 3)
        self.assertIn("description: script.alt bleibt", caller)
        self.assertNotIn("script.alt", {item["target"] for item in result["dependencies"]["references"]})

    def test_script_rename_rejects_changed_package_state(self):
        created = app.write_file(
            "ziel.yaml",
            "script:\n  alt:\n    sequence: []\n",
            None,
            "Tests",
            create=True,
        )
        preview = app.preview_script_rename("ziel.yaml", "alt", "neu")
        app.write_file(
            "ziel.yaml",
            created["content"].replace("sequence: []", "alias: Extern\n    sequence: []"),
            created["version"],
            "Tests",
            create=False,
        )

        with self.assertRaises(app.ApiError) as raised:
            app.rename_script_with_references(
                "ziel.yaml",
                "alt",
                "neu",
                preview["stateVersion"],
            )

        self.assertEqual(raised.exception.status, 409)
        self.assertIn("alt:", app.read_file("ziel.yaml")["content"])

    def test_ha_objects_follow_includes_and_resolve_script_references(self):
        configuration = app.PACKAGES_ROOT.parent / "configuration.yaml"
        automations = app.PACKAGES_ROOT.parent / "automations.yaml"
        scripts = app.PACKAGES_ROOT.parent / "scripts.yaml"
        configuration.write_text(
            "automation: !include automations.yaml\nscript: !include scripts.yaml\n",
            encoding="utf-8",
        )
        automations.write_text(
            "- id: abend_automation\n"
            "  alias: Abendautomatik\n"
            "  actions:\n"
            "    - action: script.abend\n",
            encoding="utf-8",
        )
        scripts.write_text(
            "abend:\n  alias: Abend\n  sequence:\n    - action: light.turn_on\n      target:\n        entity_id: light.flur\n",
            encoding="utf-8",
        )
        app.write_file(
            "scene.yaml",
            "scene:\n  abend_scene:\n    name: Abendszene\n    entities:\n      light.wohnzimmer: 'on'\n",
            None,
            "Tests",
            create=True,
        )

        result = app.home_assistant_objects()

        self.assertEqual(result["summary"]["automation"], 1)
        self.assertEqual(result["summary"]["script"], 1)
        self.assertEqual(result["summary"]["scene"], 1)
        automation = next(item for item in result["objects"] if item["domain"] == "automation")
        script = next(item for item in result["objects"] if item["domain"] == "script")
        reference = next(item for item in result["references"] if item["target"] == "script.abend")
        self.assertEqual(automation["editor"], "resource")
        self.assertEqual(reference["targetObject"], script["key"])
        self.assertTrue(any(item["target"] == "light.wohnzimmer" for item in result["references"]))

    def test_external_ha_resource_can_be_edited_with_version_protection(self):
        configuration = app.PACKAGES_ROOT.parent / "configuration.yaml"
        automations = app.PACKAGES_ROOT.parent / "automations.yaml"
        configuration.write_text("automation: !include automations.yaml\n", encoding="utf-8")
        automations.write_text("- id: test\n  alias: Alt\n  actions: []\n", encoding="utf-8")
        opened = app.read_resource("automations.yaml")

        saved = app.write_resource(
            "automations.yaml",
            opened["content"].replace("alias: Alt", "alias: Neu"),
            opened["version"],
        )

        self.assertIn("alias: Neu", saved["content"])
        with self.assertRaises(app.ApiError) as raised:
            app.write_resource("automations.yaml", opened["content"], opened["version"])
        self.assertEqual(raised.exception.status, 409)

    def test_ha_objects_support_named_script_and_list_automation_directories(self):
        configuration = app.PACKAGES_ROOT.parent / "configuration.yaml"
        script_directory = app.PACKAGES_ROOT.parent / "included_scripts"
        automation_directory = app.PACKAGES_ROOT.parent / "included_automations"
        script_directory.mkdir()
        automation_directory.mkdir()
        configuration.write_text(
            "script: !include_dir_named included_scripts\n"
            "automation: !include_dir_list included_automations\n",
            encoding="utf-8",
        )
        (script_directory / "abend.yaml").write_text(
            "alias: Abend\nsequence: []\n",
            encoding="utf-8",
        )
        (automation_directory / "morgen.yaml").write_text(
            "id: morgen\nalias: Morgen\nactions:\n  - action: script.abend\n",
            encoding="utf-8",
        )

        result = app.home_assistant_objects()

        script = next(item for item in result["objects"] if item["domain"] == "script")
        automation = next(item for item in result["objects"] if item["domain"] == "automation")
        self.assertEqual(script["entityId"], "script.abend")
        self.assertEqual(automation["id"], "morgen")
        self.assertTrue(any(item.get("targetObject") == script["key"] for item in result["references"]))

    def test_multi_file_search_replace_updates_packages_and_ha_resources(self):
        configuration = app.PACKAGES_ROOT.parent / "configuration.yaml"
        automations = app.PACKAGES_ROOT.parent / "automations.yaml"
        configuration.write_text("automation: !include automations.yaml\n", encoding="utf-8")
        automations.write_text(
            "- id: test\n  alias: Test\n  actions:\n    - action: script.alt\n",
            encoding="utf-8",
        )
        app.write_file(
            "suche.yaml",
            "script:\n  aufruf:\n    sequence:\n      - action: script.alt\n",
            None,
            "Tests",
            create=True,
        )
        preview = app.search_replace_preview("script.alt", "script.neu")

        result = app.apply_search_replace(
            "script.alt",
            "script.neu",
            True,
            preview["stateVersion"],
        )

        self.assertEqual(result["matches"], 2)
        self.assertIn("script.neu", automations.read_text(encoding="utf-8"))
        self.assertIn("script.neu", app.read_file("suche.yaml")["content"])

    def test_multi_file_search_replace_rejects_stale_preview(self):
        created = app.write_file(
            "stale_search.yaml",
            "script:\n  alt:\n    alias: Alt\n    sequence: []\n",
            None,
            "Tests",
            create=True,
        )
        preview = app.search_replace_preview("alias: Alt", "alias: Neu")
        app.write_file(
            created["path"],
            created["content"].replace("sequence: []", "mode: single\n    sequence: []"),
            created["version"],
            "Tests",
            create=False,
        )

        with self.assertRaises(app.ApiError) as raised:
            app.apply_search_replace(
                "alias: Alt",
                "alias: Neu",
                True,
                preview["stateVersion"],
            )

        self.assertEqual(raised.exception.status, 409)

    def test_configuration_editor_reads_writes_and_backs_up(self):
        configuration = app.PACKAGES_ROOT.parent / "configuration.yaml"
        configuration.write_text("default_config:\n", encoding="utf-8")
        opened = app.read_configuration()

        saved = app.write_configuration(
            "default_config:\nlogger:\n  default: warning\n",
            opened["version"],
        )

        self.assertIn("logger:", saved["content"])
        self.assertNotEqual(saved["version"], opened["version"])
        backups = list((app.DATA_ROOT / "backups").rglob("configuration.yaml"))
        self.assertEqual(len(backups), 1)

    def test_enable_packages_preserves_homeassistant_configuration(self):
        configuration = app.PACKAGES_ROOT.parent / "configuration.yaml"
        configuration.write_text(
            "homeassistant:\n"
            "  name: Mein Zuhause\n"
            "  auth_providers:\n"
            "    - type: homeassistant\n"
            "default_config:\n",
            encoding="utf-8",
        )
        opened = app.read_configuration()

        result = app.enable_packages(opened["content"], opened["version"])

        self.assertIn("  packages: !include_dir_named packages", result["content"])
        self.assertIn("  auth_providers:", result["content"])
        self.assertIn("default_config:", result["content"])
        self.assertTrue(result["packages"]["configured"])

    def test_enable_packages_supports_included_homeassistant_file(self):
        configuration = app.PACKAGES_ROOT.parent / "configuration.yaml"
        included = app.PACKAGES_ROOT.parent / "homeassistant.yaml"
        configuration.write_text("homeassistant: !include homeassistant.yaml\ndefault_config:\n", encoding="utf-8")
        included.write_text("name: Mein Zuhause\n", encoding="utf-8")
        opened = app.read_configuration()

        app.enable_packages(opened["content"], opened["version"])

        self.assertIn("packages: !include_dir_named packages", included.read_text(encoding="utf-8"))
        self.assertTrue(app.package_configuration_status()["configured"])

    def test_enable_packages_refuses_incompatible_existing_definition(self):
        configuration = app.PACKAGES_ROOT.parent / "configuration.yaml"
        original = "homeassistant:\n  packages: !include anderes.yaml\n"
        configuration.write_text(original, encoding="utf-8")
        opened = app.read_configuration()

        with self.assertRaises(app.ApiError) as raised:
            app.enable_packages(opened["content"], opened["version"])

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(configuration.read_text(encoding="utf-8"), original)

    def test_migration_moves_components_and_rewrites_includes(self):
        configuration = app.PACKAGES_ROOT.parent / "configuration.yaml"
        configuration.write_text(
            "# Hauptkonfiguration\n"
            "homeassistant:\n"
            "  name: Mein Zuhause\n"
            "  auth_providers:\n"
            "    - type: homeassistant\n"
            "  packages: !include_dir_named packages\n"
            "default_config:\n"
            "automation: !include automations.yaml\n"
            "script:\n"
            "  test:\n"
            "    sequence: []\n",
            encoding="utf-8",
        )
        opened = app.read_configuration()
        preview = app.configuration_migration_preview(opened["content"], "configuration_import")

        self.assertEqual(preview["components"], ["default_config", "automation", "script"])
        self.assertFalse(preview["targetExists"])
        result = app.migrate_configuration(
            opened["content"],
            opened["version"],
            "configuration_import",
        )

        main = configuration.read_text(encoding="utf-8")
        package = (app.PACKAGES_ROOT / "configuration_import.yaml").read_text(encoding="utf-8")
        self.assertIn("auth_providers:", main)
        self.assertIn("packages: !include_dir_named packages", main)
        self.assertNotIn("default_config:", main)
        self.assertIn("default_config:", package)
        self.assertIn("automation: !include ../automations.yaml", package)
        self.assertIn("script:", package)
        self.assertEqual(result["components"], ["default_config", "automation", "script"])

    def test_migration_wraps_merge_named_package(self):
        configuration = app.PACKAGES_ROOT.parent / "configuration.yaml"
        configuration.write_text(
            "homeassistant:\n"
            "  packages: !include_dir_merge_named packages\n"
            "default_config:\n",
            encoding="utf-8",
        )
        opened = app.read_configuration()

        app.migrate_configuration(opened["content"], opened["version"], "configuration_import")

        package = (app.PACKAGES_ROOT / "configuration_import.yaml").read_text(encoding="utf-8")
        self.assertIn("configuration_import:\n  default_config:", package)

    def test_migration_does_not_overwrite_existing_package(self):
        configuration = app.PACKAGES_ROOT.parent / "configuration.yaml"
        original = "homeassistant:\n  packages: !include_dir_named packages\ndefault_config:\n"
        configuration.write_text(original, encoding="utf-8")
        target = app.PACKAGES_ROOT / "configuration_import.yaml"
        target.write_text("script: {}\n", encoding="utf-8")
        opened = app.read_configuration()

        with self.assertRaises(app.ApiError) as raised:
            app.migrate_configuration(opened["content"], opened["version"], "configuration_import")

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(configuration.read_text(encoding="utf-8"), original)

    def test_home_assistant_configuration_check_results(self):
        with patch.object(app, "home_assistant_request", return_value={"result": "valid", "errors": None}):
            valid = app.check_home_assistant_configuration()
        with patch.object(
            app,
            "home_assistant_request",
            return_value={"result": "invalid", "errors": "Invalid config at line 17"},
        ):
            invalid = app.check_home_assistant_configuration()
        with patch.object(
            app,
            "home_assistant_request",
            side_effect=app.ApiError(503, "API nicht verfügbar"),
        ):
            unavailable = app.check_home_assistant_configuration()

        self.assertTrue(valid["valid"])
        self.assertFalse(invalid["valid"])
        self.assertEqual(invalid["line"], 17)
        self.assertFalse(unavailable["available"])

    def test_package_save_runs_home_assistant_check_and_extracts_source(self):
        response = {
            "result": "invalid",
            "errors": 'Invalid config at "/config/packages/test.yaml", line 4',
        }
        with patch.object(app, "home_assistant_request", return_value=response):
            created = app.write_file("test.yaml", "script: {}\n", None, "Tests", create=True)

        check = created["configurationCheck"]
        self.assertFalse(check["valid"])
        self.assertEqual(check["source"], "/config/packages/test.yaml")
        self.assertEqual(check["line"], 4)

    def test_package_backup_history_diff_and_restore(self):
        created = app.write_file(
            "history.yaml",
            "script:\n  history:\n    alias: Eins\n    sequence: []\n",
            None,
            "Tests",
            create=True,
        )
        updated = app.write_file(
            created["path"],
            created["content"].replace("alias: Eins", "alias: Zwei"),
            created["version"],
            "Tests",
            create=False,
        )
        history = app.backup_history("package", created["path"])

        self.assertEqual(len(history["entries"]), 1)
        backup_id = history["entries"][0]["id"]
        difference = app.backup_diff("package", created["path"], backup_id)
        self.assertIn("alias: Eins", difference["diff"])
        self.assertIn("alias: Zwei", difference["diff"])

        restored = app.restore_backup(
            "package",
            created["path"],
            backup_id,
            updated["version"],
        )
        self.assertIn("alias: Eins", restored["content"])
        self.assertEqual(len(app.backup_history("package", created["path"])["entries"]), 2)

    def test_git_history_diff_and_restore_for_package(self):
        created = app.write_file(
            "git_test.yaml",
            "script:\n  git_test:\n    alias: Erste Version\n    sequence: []\n",
            None,
            "Tests",
            create=True,
        )
        updated = app.write_file(
            created["path"],
            created["content"].replace("Erste Version", "Zweite Version"),
            created["version"],
            "Tests",
            create=False,
        )

        self.assertTrue(created["git"]["committed"])
        self.assertTrue(updated["git"]["committed"])
        history = app.git_history("package", created["path"])
        self.assertTrue(history["available"])
        self.assertGreaterEqual(len(history["entries"]), 2)
        oldest = history["entries"][-1]["id"]
        difference = app.git_diff("package", created["path"], oldest)
        self.assertIn("Erste Version", difference["diff"])
        self.assertIn("Zweite Version", difference["diff"])

        restored = app.restore_git_version(
            "package",
            created["path"],
            oldest,
            updated["version"],
        )
        self.assertIn("Erste Version", restored["content"])
        self.assertTrue(restored["git"]["committed"])

    def test_git_restore_rejects_stale_current_version(self):
        created = app.write_file("git_stale.yaml", "script: {}\n", None, "Tests", create=True)
        commit = app.git_history("package", created["path"])["entries"][0]["id"]
        app.write_file(
            created["path"],
            "script:\n  geändert: {}\n",
            created["version"],
            "Tests",
            create=False,
        )

        with self.assertRaises(app.ApiError) as raised:
            app.restore_git_version("package", created["path"], commit, created["version"])

        self.assertEqual(raised.exception.status, 409)

    def test_git_commit_does_not_include_unrelated_staged_files(self):
        app.ensure_git_repository()
        unrelated = app.PACKAGES_ROOT.parent / "unrelated.txt"
        unrelated.write_text("vom Nutzer vorgemerkt\n", encoding="utf-8")
        app.run_git(["add", "unrelated.txt"])

        app.write_file("isoliert.yaml", "script: {}\n", None, "Tests", create=True)

        committed = app.run_git(["show", "--format=", "--name-only", "HEAD"]).stdout.decode()
        staged = app.run_git(["diff", "--cached", "--name-only"]).stdout.decode()
        self.assertIn("packages/isoliert.yaml", committed)
        self.assertNotIn("unrelated.txt", committed)
        self.assertIn("unrelated.txt", staged)

    def test_git_branch_create_switch_compare_and_merge(self):
        created = app.write_file(
            "branch.yaml",
            "script:\n  branch:\n    alias: Hauptstand\n    sequence: []\n",
            None,
            "Tests",
            create=True,
        )
        base = app.git_branches()["current"]
        app.create_git_branch("feature/test")
        updated = app.write_file(
            created["path"],
            created["content"].replace("Hauptstand", "Featurestand"),
            created["version"],
            "Tests",
            create=False,
        )

        switched = app.switch_git_branch(base)
        self.assertEqual(switched["current"], base)
        self.assertIn("Hauptstand", app.read_file(created["path"])["content"])

        preview = app.branch_merge_preview("feature/test")
        self.assertGreaterEqual(preview["behind"], 1)
        self.assertIn("Featurestand", preview["diff"])
        merged = app.merge_git_branch("feature/test", preview["stateVersion"])

        self.assertEqual(merged["current"], base)
        self.assertIn("Featurestand", app.read_file(updated["path"])["content"])

    def test_git_remote_configuration_redacts_token_and_uses_private_file(self):
        status = app.update_git_remote(
            {
                "url": "https://github.com/example/home-assistant-config.git",
                "branch": "main",
                "username": "example",
                "token": "secret-token",
            }
        )

        self.assertTrue(status["configured"])
        self.assertTrue(status["tokenConfigured"])
        self.assertNotIn("token", status)
        self.assertEqual(app.GIT_REMOTE_FILE.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("secret-token", app.run_git(["remote", "get-url", app.GIT_REMOTE_NAME]).stdout.decode())

    def test_git_remote_rejects_embedded_credentials_and_unknown_hosts(self):
        for url in (
            "https://token@github.com/example/config.git",
            "https://example.com/example/config.git",
        ):
            with self.subTest(url=url), self.assertRaises(app.ApiError):
                app.update_git_remote({"url": url, "branch": "main", "token": "secret"})

    def test_git_remote_pushes_to_configured_branch(self):
        remote = app.PACKAGES_ROOT.parent / "remote.git"
        app.run_git(["init", "--bare", str(remote)])
        app.write_file("remote.yaml", "script: {}\n", None, "Tests", create=True)
        app.save_git_remote_file(
            {
                "url": str(remote),
                "provider": "test",
                "branch": "main",
                "username": "test",
                "token": "",
            }
        )

        result = app.synchronize_git_remote("push")
        remote_head = app.run_git(
            ["--git-dir", str(remote), "rev-parse", "refs/heads/main"]
        ).stdout.decode().strip()

        self.assertEqual(result["action"], "push")
        self.assertEqual(remote_head, app.run_git(["rev-parse", "HEAD"]).stdout.decode().strip())

    def test_git_remote_can_merge_unrelated_initial_readme_history(self):
        root = app.PACKAGES_ROOT.parent
        remote = root / "remote.git"
        seed = root / "remote-seed"
        app.run_git(["init", "--bare", str(remote)])
        app.run_git(["init", str(seed)])
        (seed / "README.md").write_text("# Home Assistant\n", encoding="utf-8")
        app.run_git(["-C", str(seed), "add", "README.md"])
        app.run_git(
            [
                "-C", str(seed),
                "-c", "user.name=Remote User",
                "-c", "user.email=remote@example.test",
                "commit", "-m", "Initial README",
            ]
        )
        app.run_git(["-C", str(seed), "remote", "add", "origin", str(remote)])
        app.run_git(["-C", str(seed), "push", "origin", "HEAD:refs/heads/main"])

        app.write_file("local.yaml", "script: {}\n", None, "Tests", create=True)
        app.save_git_remote_file(
            {
                "url": str(remote),
                "provider": "test",
                "branch": "main",
                "username": "test",
                "token": "",
            }
        )

        with self.assertRaises(app.ApiError) as diverged:
            app.synchronize_git_remote("sync")
        self.assertEqual(diverged.exception.details["resolutionOptions"], ["merge", "force-push"])

        result = app.synchronize_git_remote("merge")
        remote_head = app.run_git(
            ["--git-dir", str(remote), "rev-parse", "refs/heads/main"]
        ).stdout.decode().strip()

        self.assertEqual(result["action"], "merge")
        self.assertTrue((root / "README.md").is_file())
        self.assertTrue((app.PACKAGES_ROOT / "local.yaml").is_file())
        self.assertEqual(remote_head, app.run_git(["rev-parse", "HEAD"]).stdout.decode().strip())

    def test_git_remote_can_replace_diverged_remote_with_force_lease(self):
        root = app.PACKAGES_ROOT.parent
        remote = root / "remote.git"
        seed = root / "remote-seed"
        app.run_git(["init", "--bare", str(remote)])
        app.run_git(["init", str(seed)])
        (seed / "README.md").write_text("# Remote\n", encoding="utf-8")
        app.run_git(["-C", str(seed), "add", "README.md"])
        app.run_git(
            [
                "-C", str(seed),
                "-c", "user.name=Remote User",
                "-c", "user.email=remote@example.test",
                "commit", "-m", "Remote README",
            ]
        )
        app.run_git(["-C", str(seed), "remote", "add", "origin", str(remote)])
        app.run_git(["-C", str(seed), "push", "origin", "HEAD:refs/heads/main"])
        app.write_file("local.yaml", "script: {}\n", None, "Tests", create=True)
        app.save_git_remote_file(
            {"url": str(remote), "provider": "test", "branch": "main", "username": "test", "token": ""}
        )
        with self.assertRaises(app.ApiError):
            app.synchronize_git_remote("sync")

        result = app.synchronize_git_remote("force-push")
        remote_tree = app.run_git(
            ["--git-dir", str(remote), "ls-tree", "-r", "--name-only", "refs/heads/main"]
        ).stdout.decode().splitlines()

        self.assertEqual(result["action"], "force-push")
        self.assertIn("packages/local.yaml", remote_tree)
        self.assertNotIn("README.md", remote_tree)

    def test_quality_dashboard_reports_possibly_unused_scripts(self):
        app.write_file(
            "scripts.yaml",
            "script:\n  used:\n    sequence: []\n  unused:\n    sequence: []\n",
            None,
            "Tests",
            create=True,
        )
        (app.PACKAGES_ROOT.parent / "automations.yaml").write_text(
            "- action: script.used\n",
            encoding="utf-8",
        )

        dashboard = app.configuration_quality_dashboard()
        unused_titles = [
            finding["title"]
            for finding in dashboard["findings"]
            if finding["code"] == "possibly-unused-script"
        ]

        self.assertEqual(dashboard["summary"]["scripts"], 2)
        self.assertTrue(any("unused" in title for title in unused_titles))
        self.assertFalse(any(title.startswith("Script „used“") for title in unused_titles))

    def test_package_export_import_roundtrip_preserves_metadata(self):
        created = app.write_file(
            "export/test.yaml",
            "script:\n  export_test:\n    sequence: []\n",
            None,
            "Export",
            create=True,
            tags=["demo", "zip"],
        )
        _filename, archive = app.export_packages("file", raw_path=created["path"])
        app.delete_file(created["path"], created["version"])
        encoded = base64.b64encode(archive).decode("ascii")

        preview = app.preview_package_import(encoded)
        self.assertTrue(preview["valid"])
        self.assertFalse(preview["files"][0]["exists"])
        result = app.apply_package_import(
            encoded,
            "overwrite",
            preview["archiveVersion"],
            preview["destinationVersion"],
        )

        restored = app.read_file(created["path"])
        self.assertIn(created["path"], result["imported"])
        self.assertEqual(restored["category"], "Export")
        self.assertEqual(restored["tags"], ["demo", "zip"])

    def test_import_preview_detects_unsafe_paths_and_package_name_conflicts(self):
        app.write_file("room/a.yaml", "script:\n  one: {}\n", None, "Tests", create=True)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("packages/other/a.yaml", "script:\n  two: {}\n")
            archive.writestr("packages/../escape.yaml", "script: {}\n")
        preview = app.preview_package_import(base64.b64encode(output.getvalue()).decode("ascii"))

        self.assertFalse(preview["valid"])
        self.assertTrue(any("escape.yaml" in error for error in preview["errors"]))
        self.assertIn(
            "duplicate-package-name",
            {finding["code"] for finding in preview["conflicts"]["findings"]},
        )

    def test_import_rejects_any_package_change_after_preview(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("packages/import.yaml", "script:\n  imported: {}\n")
        encoded = base64.b64encode(output.getvalue()).decode("ascii")
        preview = app.preview_package_import(encoded)
        app.write_file("other.yaml", "script: {}\n", None, "Tests", create=True)

        with self.assertRaises(app.ApiError) as raised:
            app.apply_package_import(
                encoded,
                "overwrite",
                preview["archiveVersion"],
                preview["destinationVersion"],
            )

        self.assertEqual(raised.exception.status, 409)

    def test_backup_restore_rejects_stale_current_version(self):
        created = app.write_file("stale.yaml", "script: {}\n", None, "Tests", create=True)
        updated = app.write_file(
            created["path"],
            "script:\n  neu: {}\n",
            created["version"],
            "Tests",
            create=False,
        )
        backup_id = app.backup_history("package", created["path"])["entries"][0]["id"]

        with self.assertRaises(app.ApiError) as raised:
            app.restore_backup("package", created["path"], backup_id, created["version"])

        self.assertEqual(raised.exception.status, 409)
        self.assertIn("neu", app.read_file(created["path"])["content"])
        self.assertNotEqual(updated["version"], created["version"])

    def test_configuration_restore_runs_home_assistant_check(self):
        configuration = app.PACKAGES_ROOT.parent / "configuration.yaml"
        configuration.write_text("default_config:\n", encoding="utf-8")
        opened = app.read_configuration()
        with patch.object(app, "check_home_assistant_configuration", return_value={"valid": True}):
            saved = app.write_configuration("default_config:\nlogger:\n", opened["version"])
            backup_id = app.backup_history("configuration")["entries"][0]["id"]
            restored = app.restore_backup(
                "configuration",
                "",
                backup_id,
                saved["version"],
            )

        self.assertEqual(restored["configurationCheck"], {"valid": True})
        self.assertNotIn("logger:", restored["content"])

    def test_package_conflicts_detect_names_entities_keys_and_unique_ids(self):
        configuration = app.PACKAGES_ROOT.parent / "configuration.yaml"
        configuration.write_text(
            "homeassistant:\n  packages: !include_dir_named packages\n",
            encoding="utf-8",
        )
        first = app.PACKAGES_ROOT / "raum_a" / "licht.yaml"
        second = app.PACKAGES_ROOT / "raum_b" / "licht.yaml"
        first.parent.mkdir(parents=True)
        second.parent.mkdir(parents=True)
        first.write_text(
            "script:\n  doppelt:\n    sequence: []\n"
            "input_boolean:\n  status:\n"
            "recorder:\n  purge_keep_days: 5\n"
            "template:\n  - sensor:\n      - name: Eins\n        unique_id: gleich\n",
            encoding="utf-8",
        )
        second.write_text(
            "script:\n  doppelt:\n    sequence: []\n"
            "input_boolean:\n  status:\n"
            "recorder:\n  purge_keep_days: 7\n"
            "template:\n  - sensor:\n      - name: Zwei\n        unique_id: gleich\n",
            encoding="utf-8",
        )

        result = app.package_conflict_analysis()
        codes = {finding["code"] for finding in result["findings"]}

        self.assertIn("duplicate-package-name", codes)
        self.assertIn("duplicate-entity-id", codes)
        self.assertIn("duplicate-integration-key", codes)
        self.assertIn("duplicate-unique-id", codes)

    def test_package_conflicts_allow_list_based_platform_merges(self):
        (app.PACKAGES_ROOT / "eins.yaml").write_text(
            "sensor:\n  - platform: rest\n    name: Eins\n",
            encoding="utf-8",
        )
        (app.PACKAGES_ROOT / "zwei.yaml").write_text(
            "sensor:\n  - platform: rest\n    name: Zwei\n",
            encoding="utf-8",
        )

        result = app.package_conflict_analysis()

        self.assertFalse(any(item["code"] == "duplicate-integration" for item in result["findings"]))


if __name__ == "__main__":
    unittest.main()
