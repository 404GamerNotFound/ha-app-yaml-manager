import base64
import io
import json
import sqlite3
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
        app.SETTINGS_FILE = app.DATA_ROOT / "settings.json"
        app.ha_helper_cache = {"timestamp": 0.0, "data": None}
        app.ensure_directories()

    def tearDown(self):
        self.temporary.cleanup()

    def create_recorder_database(self):
        path = app.PACKAGES_ROOT.parent / "home-assistant_v2.db"
        with sqlite3.connect(path) as connection:
            connection.executescript(
                """
                CREATE TABLE states_meta (
                  metadata_id INTEGER PRIMARY KEY,
                  entity_id TEXT NOT NULL
                );
                CREATE TABLE state_attributes (
                  attributes_id INTEGER PRIMARY KEY,
                  shared_attrs TEXT
                );
                CREATE TABLE states (
                  state_id INTEGER PRIMARY KEY,
                  metadata_id INTEGER NOT NULL,
                  state TEXT,
                  last_changed_ts REAL,
                  attributes_id INTEGER
                );
                CREATE TABLE statistics_meta (
                  metadata_id INTEGER PRIMARY KEY,
                  statistic_id TEXT NOT NULL,
                  unit_of_measurement TEXT,
                  has_mean INTEGER,
                  has_sum INTEGER
                );
                CREATE TABLE statistics (
                  id INTEGER PRIMARY KEY,
                  metadata_id INTEGER NOT NULL,
                  start_ts REAL,
                  state REAL,
                  sum REAL
                );
                CREATE TABLE statistics_short_term (
                  id INTEGER PRIMARY KEY,
                  metadata_id INTEGER NOT NULL,
                  start_ts REAL,
                  state REAL,
                  sum REAL
                );
                """
            )
            connection.executemany(
                "INSERT INTO states_meta(metadata_id, entity_id) VALUES (?, ?)",
                [
                    (1, "light.used"),
                    (2, "sensor.noisy"),
                    (3, "sensor.db_only"),
                    (4, "sensor.dead"),
                ],
            )
            connection.executemany(
                "INSERT INTO state_attributes(attributes_id, shared_attrs) VALUES (?, ?)",
                [
                    (1, '{"friendly_name":"Used"}'),
                    (2, '{"payload":"' + ("x" * 250) + '"}'),
                ],
            )
            rows = [
                (1, 1, "on", 1_700_000_000, 1),
                (2, 3, "42", 1_700_000_200, 1),
                (3, 4, "unavailable", 1_700_000_300, 1),
            ]
            rows.extend(
                (100 + index, 2, str(index), 1_700_001_000 + index, 2)
                for index in range(12)
            )
            connection.executemany(
                "INSERT INTO states(state_id, metadata_id, state, last_changed_ts, attributes_id) VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            connection.executemany(
                "INSERT INTO statistics_meta(metadata_id, statistic_id, unit_of_measurement, has_mean, has_sum) VALUES (?, ?, ?, ?, ?)",
                [
                    (1, "sensor.energy", "kWh", 0, 1),
                    (2, "sensor.energy", "Wh", 0, 1),
                    (3, "sensor.no_class", None, 0, 0),
                ],
            )
            connection.executemany(
                "INSERT INTO statistics(metadata_id, start_ts, state, sum) VALUES (?, ?, ?, ?)",
                [
                    (1, 1_700_000_000, 1, 1),
                    (1, 1_700_003_600, 2, 2),
                    (1, 1_700_012_000, 150, 150),
                    (3, 1_700_000_000, 5, 5),
                ],
            )
            connection.executemany(
                "INSERT INTO statistics_short_term(metadata_id, start_ts, state, sum) VALUES (?, ?, ?, ?)",
                [
                    (1, 1_700_000_000, 1, 1),
                    (1, 1_700_000_300, 2, 2),
                    (1, 1_700_001_200, 3, 3),
                ],
            )
        return path

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

    def test_settings_are_sanitized_and_affect_dashboard_rules(self):
        settings = app.update_settings(
            {
                "backupRetention": 3,
                "maxImportFiles": 12,
                "maxImportSizeMiB": 4,
                "maxExpandedImportSizeMiB": 8,
                "showUnusedScripts": False,
                "defaultBranchPrefix": "feature/",
                "theme": "dark",
                "afterSave": "dashboard",
            }
        )
        app.write_file(
            "unused.yaml",
            "script:\n  unused:\n    sequence: []\n",
            None,
            "Tests",
            create=True,
        )

        dashboard = app.configuration_quality_dashboard()

        self.assertEqual(settings["backupRetention"], 5)
        self.assertEqual(settings["theme"], "dark")
        self.assertEqual(app.load_settings()["afterSave"], "dashboard")
        self.assertFalse(any(item["code"] == "possibly-unused-script" for item in dashboard["findings"]))

    def test_maintenance_run_records_history_delta_and_retention(self):
        settings = app.update_settings(
            {
                "maintenanceEnabled": True,
                "maintenanceIntervalHours": 2,
                "maintenanceHistoryRetention": 2,
                "maintenanceIncludeDatabase": False,
            }
        )
        app.write_file(
            "maintenance.yaml",
            "script:\n  maintenance_test:\n    sequence: []\n",
            None,
            "Tests",
            create=True,
        )

        first = app.run_maintenance("test")
        status = app.maintenance_status()

        self.assertEqual(settings["maintenanceIntervalHours"], 2)
        self.assertEqual(status["latest"]["id"], first["id"])
        self.assertFalse(status["due"])
        self.assertEqual(app.maintenance_history()["count"], 1)
        self.assertFalse(first["summary"]["databaseAvailable"])

        app.write_file(
            "maintenance_warning.yaml",
            "automation:\n"
            "  - alias: Wartungswarnung\n"
            "    trigger: []\n"
            "    action: []\n",
            None,
            "Tests",
            create=True,
        )
        second = app.run_maintenance("test")
        third = app.run_maintenance("test")
        history = app.maintenance_history()

        self.assertEqual(second["delta"]["previousRunId"], first["id"])
        self.assertTrue(any(item["code"] == "preflight-lint" for item in second["findings"]))
        self.assertEqual(history["count"], 2)
        self.assertEqual(history["entries"][0]["id"], third["id"])

    def test_trash_history_restore_and_purge_preserve_metadata(self):
        created = app.write_file(
            "trash/test.yaml",
            "script:\n  trash_test:\n    sequence: []\n",
            None,
            "Papierkorb",
            create=True,
            tags=["restore"],
        )
        app.delete_file(created["path"], created["version"])
        history = app.trash_history()

        self.assertEqual(history["count"], 1)
        self.assertEqual(history["entries"][0]["path"], created["path"])
        restored = app.restore_trash_file(history["entries"][0]["id"], created["path"])
        self.assertEqual(restored["category"], "Papierkorb")
        self.assertEqual(restored["tags"], ["restore"])
        self.assertTrue((app.PACKAGES_ROOT / created["path"]).is_file())
        self.assertEqual(app.trash_history()["count"], 0)

        app.delete_file(restored["path"], restored["version"])
        self.assertEqual(app.trash_history()["count"], 1)
        self.assertEqual(app.purge_trash()["count"], 0)

    def test_trash_retention_removes_expired_and_oldest_entries(self):
        app.update_settings({"trashRetentionDays": 1, "trashMaxSizeMiB": 1})
        created = app.write_file("old.yaml", "script: {}\n", None, "Tests", create=True)
        app.delete_file(created["path"], created["version"])
        old_directory = next((app.DATA_ROOT / "trash").iterdir())
        expired = app.DATA_ROOT / "trash" / "20000101-000000-000000"
        old_directory.rename(expired)

        self.assertEqual(app.trash_history()["count"], 0)

        app.update_settings({"trashRetentionDays": 0, "trashMaxSizeMiB": 1})
        first = app.write_file(
            "first.yaml",
            "script:\n  first:\n    alias: " + ("A" * 700_000) + "\n    sequence: []\n",
            None,
            "Tests",
            create=True,
        )
        app.delete_file(first["path"], first["version"])
        second = app.write_file(
            "second.yaml",
            "script:\n  second:\n    alias: " + ("B" * 700_000) + "\n    sequence: []\n",
            None,
            "Tests",
            create=True,
        )
        app.delete_file(second["path"], second["version"])

        remaining = app.trash_history()

        self.assertEqual(remaining["count"], 1)
        self.assertEqual(remaining["entries"][0]["path"], "second.yaml")

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

    def test_semantic_analysis_checks_live_home_assistant_helpers(self):
        helpers = {
            "available": True,
            "entities": [{"entity_id": "switch.flur", "name": "Flur", "state": "off"}],
            "services": ["light.turn_on"],
            "serviceDetails": {
                "light.turn_on": {
                    "fields": {"brightness": {"required": True}},
                    "target": {"entity": {"domain": "light"}},
                }
            },
            "devices": [{"id": "device_ok"}],
            "areas": [{"area_id": "kueche"}],
        }
        with patch.object(app, "cached_helper_data", return_value=helpers):
            result = app.analyze_yaml(
                "script:\n"
                "  test:\n"
                "    alias: Test\n"
                "    mode: single\n"
                "    sequence:\n"
                "      - action: light.turn_on\n"
                "        target:\n"
                "          entity_id: switch.flur\n"
                "      - action: switch.turn_on\n"
                "        target:\n"
                "          device_id: missing_device\n"
                "          area_id: missing_area\n",
                "semantic.yaml",
            )

        codes = {finding["code"] for finding in result["findings"]}

        self.assertIn("ha-target-domain", codes)
        self.assertIn("ha-required-field", codes)
        self.assertIn("ha-unknown-service", codes)
        self.assertIn("ha-unknown-device", codes)
        self.assertIn("ha-unknown-area", codes)

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

    def test_entity_refactor_updates_exact_entity_references(self):
        app.write_file(
            "refactor.yaml",
            "script:\n"
            "  refactor:\n"
            "    sequence:\n"
            "      - action: light.turn_on\n"
            "        target:\n"
            "          entity_id: light.alt\n"
            "      - action: light.turn_on\n"
            "        target:\n"
            "          entity_id: light.alt_extra\n",
            None,
            "Tests",
            create=True,
        )

        preview = app.entity_refactor_preview("light.alt", "light.neu")
        result = app.apply_entity_refactor("light.alt", "light.neu", preview["stateVersion"])
        content = app.read_file("refactor.yaml")["content"]

        self.assertEqual(preview["matches"], 1)
        self.assertEqual(result["matches"], 1)
        self.assertIn("entity_id: light.neu", content)
        self.assertIn("entity_id: light.alt_extra", content)

    def test_secrets_manager_masks_values_and_converts_plaintext(self):
        overview = app.upsert_secret({"name": "api_token", "value": "super-secret-value"})

        self.assertEqual(overview["items"][0]["name"], "api_token")
        self.assertEqual(overview["items"][0]["masked"], "••••••••")
        self.assertNotIn("super-secret-value", str(overview))

        app.write_file(
            "secret_convert.yaml",
            "rest_command:\n  webhook:\n    api_key: plaintext-token-123456\n",
            None,
            "Tests",
            create=True,
        )
        converted = app.convert_plaintext_secret(
            {
                "path": "packages/secret_convert.yaml",
                "line": 3,
                "key": "api_key",
                "name": "webhook_key",
                "value": "plaintext-token-123456",
            }
        )
        content = app.read_file("secret_convert.yaml")["content"]
        secrets = (app.PACKAGES_ROOT.parent / "secrets.yaml").read_text(encoding="utf-8")

        self.assertIn("api_key: !secret webhook_key", content)
        self.assertIn("webhook_key:", secrets)
        self.assertNotIn("plaintext-token-123456", str(converted))

    def test_preflight_collects_checks(self):
        app.write_file("preflight.yaml", "script:\n  preflight:\n    sequence: []\n", None, "Tests", create=True)

        result = app.preflight()
        check_ids = {item["id"] for item in result["checks"]}

        self.assertIn("yaml", check_ids)
        self.assertIn("security", check_ids)
        self.assertIn("entity-health", check_ids)
        self.assertIn("git", check_ids)
        self.assertIn("blockers", result)

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

    def test_security_scan_detects_missing_secret_and_plaintext_token(self):
        (app.PACKAGES_ROOT.parent / "secrets.yaml").write_text("known_secret: vorhanden\n", encoding="utf-8")
        app.write_file(
            "security.yaml",
            "rest_command:\n"
            "  webhook:\n"
            "    url: https://example.test/hook?token=abcdef0123456789\n"
            "script:\n"
            "  sicherheit:\n"
            "    sequence:\n"
            "      - action: notify.mobile_app\n"
            "        data:\n"
            "          password: !secret missing_password\n"
            "          api_key: abcdef0123456789abcdef0123456789\n",
            None,
            "Tests",
            create=True,
        )

        result = app.security_scan()
        warning = app.security_push_warning()
        codes = {finding["code"] for finding in result["findings"]}

        self.assertIn("missing-secret", codes)
        self.assertIn("plaintext-secret-url", codes)
        self.assertIn("plaintext-secret", codes)
        self.assertFalse(warning["ok"])
        self.assertGreaterEqual(warning["count"], 3)

    def test_render_template_posts_to_home_assistant_and_reports_entities(self):
        with patch.object(app, "home_assistant_request", return_value="23.5") as request:
            result = app.render_template({"template": "{{ states('sensor.temperatur') }} {{ states.light.kueche.state }}"})

        self.assertTrue(result["success"])
        self.assertEqual(result["result"], "23.5")
        self.assertEqual(result["entities"], ["light.kueche", "sensor.temperatur"])
        request.assert_called_once_with(
            "template",
            method="POST",
            payload={"template": "{{ states('sensor.temperatur') }} {{ states.light.kueche.state }}"},
        )

    def test_render_template_reports_unavailable_home_assistant(self):
        with patch.object(app, "home_assistant_request", side_effect=app.ApiError(503, "nicht verfügbar")):
            result = app.render_template({"template": "{{ states('sensor.temperatur') }}"})

        self.assertFalse(result["success"])
        self.assertFalse(result["available"])
        self.assertEqual(result["entities"], ["sensor.temperatur"])

    def test_trace_index_and_detail_use_home_assistant_trace_api(self):
        app.write_file(
            "trace.yaml",
            "script:\n  trace_test:\n    alias: Trace Test\n    sequence: []\n",
            None,
            "Tests",
            create=True,
        )

        def fake_request(path, method="GET", payload=None):
            if path == "trace/script/trace_test":
                return {
                    "stored_traces": {
                        "run-1": {
                            "timestamp": "2026-06-25T10:00:00+00:00",
                            "state": "stopped",
                            "last_step": "sequence/0",
                        }
                    }
                }
            if path == "trace/script/trace_test/run-1":
                return {"trace": {"last_step": "sequence/0"}}
            raise app.ApiError(404, "nicht gefunden")

        with patch.object(app, "home_assistant_request", side_effect=fake_request):
            index = app.trace_index()
            detail = app.trace_detail("script", "trace_test", "run-1")

        self.assertTrue(index["available"])
        self.assertEqual(index["summary"]["traces"], 1)
        self.assertEqual(index["entries"][0]["runId"], "run-1")
        self.assertEqual(detail["trace"], {"trace": {"last_step": "sequence/0"}})

    def test_flow_analysis_builds_script_branches(self):
        result = app.flow_analysis(
            {
                "path": "flow.yaml",
                "content": (
                    "script:\n"
                    "  flow_test:\n"
                    "    alias: Flow Test\n"
                    "    sequence:\n"
                    "      - choose:\n"
                    "          - conditions:\n"
                    "              - condition: state\n"
                    "                entity_id: binary_sensor.tuer\n"
                    "                state: 'on'\n"
                    "            sequence:\n"
                    "              - action: light.turn_on\n"
                    "                target:\n"
                    "                  entity_id: light.flur\n"
                    "        default:\n"
                    "          - delay: '00:00:05'\n"
                    "      - repeat:\n"
                    "          count: 2\n"
                    "          sequence:\n"
                    "            - action: light.toggle\n"
                    "              target:\n"
                    "                entity_id: light.flur\n"
                ),
            }
        )

        types = {node["type"] for flow in result["flows"] for node in flow["nodes"]}

        self.assertTrue(result["valid"])
        self.assertEqual(result["summary"]["flows"], 1)
        self.assertIn("choose", types)
        self.assertIn("repeat", types)
        self.assertIn("service", types)

    def test_save_impact_reports_removed_referenced_script(self):
        app.write_file(
            "target.yaml",
            "script:\n  target:\n    alias: Target\n    sequence: []\n",
            None,
            "Tests",
            create=True,
        )
        app.write_file(
            "caller.yaml",
            "script:\n  caller:\n    sequence:\n      - action: script.target\n",
            None,
            "Tests",
            create=True,
        )

        impact = app.save_impact({"path": "target.yaml", "content": "script: {}\n"})

        self.assertEqual(impact["risk"], "error")
        self.assertEqual(impact["summary"]["removedScripts"], 1)
        self.assertEqual(impact["summary"]["incomingReferences"], 1)
        self.assertEqual(impact["scripts"]["removed"], ["script.target"])

    def test_entity_health_reports_unknown_unavailable_disabled_and_unused(self):
        app.write_file(
            "health.yaml",
            "script:\n"
            "  health:\n"
            "    sequence:\n"
            "      - action: light.turn_on\n"
            "        target:\n"
            "          entity_id:\n"
            "            - light.missing\n"
            "            - light.bad\n"
            "            - light.disabled\n",
            None,
            "Tests",
            create=True,
        )
        helpers = {
            "available": True,
            "entities": [
                {"entity_id": "light.bad", "name": "Bad", "state": "unavailable"},
                {"entity_id": "light.unused", "name": "Unused", "state": "on"},
            ],
            "services": [],
            "serviceDetails": {},
            "devices": [],
            "areas": [],
            "entityRegistry": [{"entity_id": "light.disabled", "disabled_by": "user"}],
        }

        with patch.object(app, "cached_helper_data", return_value=helpers):
            result = app.entity_health()

        self.assertEqual(result["summary"]["unknown"], 1)
        self.assertEqual(result["summary"]["unavailable"], 1)
        self.assertEqual(result["summary"]["disabled"], 1)
        self.assertGreaterEqual(result["summary"]["unused"], 1)
        self.assertEqual(result["unknown"][0]["entityId"], "light.missing")

    def test_run_home_assistant_object_calls_script_and_automation_services(self):
        calls = []

        def fake_request(path, method="GET", payload=None):
            calls.append((path, method, payload))
            return {"ok": True}

        with patch.object(app, "home_assistant_request", side_effect=fake_request):
            script = app.run_home_assistant_object({"domain": "script", "entityId": "script.test"})
            automation = app.run_home_assistant_object({"domain": "automation", "entityId": "automation.test", "skipCondition": True})

        self.assertEqual(script["traceHint"], {"domain": "script", "itemId": "test"})
        self.assertEqual(automation["traceHint"], {"domain": "automation", "itemId": "test"})
        self.assertEqual(calls[0], ("services/script/turn_on", "POST", {"entity_id": "script.test"}))
        self.assertEqual(
            calls[1],
            ("services/automation/trigger", "POST", {"entity_id": "automation.test", "skip_condition": True}),
        )

    def test_home_assistant_request_reports_http_error_message(self):
        error = app.urllib.error.HTTPError(
            url="http://supervisor/core/api/services/script/turn_on",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=io.BytesIO(b'{"message":"Entity not found"}'),
        )

        with patch.dict(app.os.environ, {"SUPERVISOR_TOKEN": "token"}):
            with patch.object(app.urllib.request, "urlopen", side_effect=error):
                with self.assertRaises(app.ApiError) as raised:
                    app.home_assistant_request(
                        "services/script/turn_on",
                        method="POST",
                        payload={"entity_id": "script.missing"},
                    )

        self.assertEqual(raised.exception.status, 502)
        self.assertEqual(raised.exception.message, "Entity not found")
        self.assertEqual(raised.exception.details["homeAssistantStatus"], 400)

    def test_documentation_overview_contains_html_page_data(self):
        app.write_file(
            "docs.yaml",
            "script:\n"
            "  dokumentiert:\n"
            "    alias: Dokumentiert\n"
            "    sequence:\n"
            "      - action: light.turn_on\n"
            "        target:\n"
            "          entity_id: light.kueche\n",
            None,
            "Tests",
            create=True,
        )

        result = app.documentation_overview()

        self.assertIn("content", result)
        self.assertTrue(any(item["entityId"] == "light.kueche" for item in result["data"]["entities"]))
        self.assertTrue(any(item["entityId"] == "script.dokumentiert" for item in result["data"]["objects"]))
        self.assertIn("commits", result["data"])

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

    def test_file_save_automatically_pushes_to_configured_remote(self):
        remote = app.PACKAGES_ROOT.parent / "automatic-remote.git"
        app.run_git(["init", "--bare", str(remote)])
        created = app.write_file(
            "automatic.yaml",
            "script:\n  automatic:\n    alias: Vorher\n    sequence: []\n",
            None,
            "Tests",
            create=True,
        )
        app.save_git_remote_file(
            {
                "url": str(remote),
                "provider": "test",
                "branch": "main",
                "username": "test",
                "token": "",
                "autoPush": True,
            }
        )

        saved = app.write_file(
            created["path"],
            created["content"].replace("Vorher", "Nachher"),
            created["version"],
            "Tests",
            create=False,
        )

        self.assertTrue(saved["gitSync"]["enabled"])
        self.assertTrue(saved["gitSync"]["success"])
        remote_head = app.run_git(
            ["--git-dir", str(remote), "rev-parse", "refs/heads/main"]
        ).stdout.decode().strip()
        self.assertEqual(remote_head, app.run_git(["rev-parse", "HEAD"]).stdout.decode().strip())

    def test_automatic_push_is_blocked_by_security_warning(self):
        remote = app.PACKAGES_ROOT.parent / "blocked-remote.git"
        app.run_git(["init", "--bare", str(remote)])
        app.save_git_remote_file(
            {
                "url": str(remote),
                "provider": "test",
                "branch": "main",
                "username": "test",
                "token": "",
                "autoPush": True,
            }
        )

        saved = app.write_file(
            "blocked_secret.yaml",
            "rest_command:\n"
            "  webhook:\n"
            "    url: https://example.test/hook?token=abcdef0123456789\n",
            None,
            "Tests",
            create=True,
        )

        self.assertTrue(saved["gitSync"]["enabled"])
        self.assertFalse(saved["gitSync"]["success"])
        self.assertTrue(saved["gitSync"]["blocked"])
        self.assertGreaterEqual(saved["gitSync"]["security"]["count"], 1)

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

    def test_dashboard_findings_can_be_marked_irrelevant_and_restored(self):
        app.write_file(
            "scripts.yaml",
            "script:\n  unused:\n    sequence: []\n",
            None,
            "Tests",
            create=True,
        )
        dashboard = app.configuration_quality_dashboard()
        finding = next(item for item in dashboard["findings"] if item["code"] == "possibly-unused-script")

        result = app.update_dashboard_finding_state(
            {"key": finding["key"], "status": "irrelevant", "finding": finding}
        )
        hidden_dashboard = app.configuration_quality_dashboard()
        hidden = next(
            item for item in hidden_dashboard["suppressedFindings"] if item["key"] == finding["key"]
        )

        self.assertEqual(result["label"], "gegenstandslos")
        self.assertFalse(any(item["key"] == finding["key"] for item in hidden_dashboard["findings"]))
        self.assertEqual(hidden["suppressionStatus"], "irrelevant")
        self.assertEqual(hidden_dashboard["summary"]["irrelevantFindings"], 1)

        restored = app.restore_dashboard_finding_state({"key": finding["key"]})
        restored_dashboard = app.configuration_quality_dashboard()

        self.assertTrue(restored["restored"])
        self.assertTrue(any(item["key"] == finding["key"] for item in restored_dashboard["findings"]))

    def test_blueprint_import_and_instantiation_create_package(self):
        blueprint = app.import_blueprint(
            "blueprints/script/local/notify.yaml",
            "blueprint:\n"
            "  name: Notify Script\n"
            "  domain: script\n"
            "  input:\n"
            "    message:\n"
            "      name: Nachricht\n"
            "sequence:\n"
            "  - action: notify.mobile_app\n"
            "    data:\n"
            "      message: !input message\n",
        )

        listing = app.list_blueprints()
        result = app.instantiate_blueprint(
            blueprint["path"],
            "blueprint_notify.yaml",
            "notify_test",
            "Notify Test",
            inputs_text="message: Hallo\n",
        )

        self.assertEqual(listing["summary"]["script"], 1)
        self.assertEqual(result["path"], "blueprint_notify.yaml")
        self.assertIn("use_blueprint:", result["content"])
        self.assertIn("path: local/notify.yaml", result["content"])

    def test_documentation_generator_summarizes_packages_and_objects(self):
        app.write_file(
            "doc.yaml",
            "script:\n"
            "  doc_script:\n"
            "    alias: Doc Script\n"
            "    sequence:\n"
            "      - action: light.turn_on\n"
            "        target:\n"
            "          entity_id: light.flur\n",
            None,
            "Doku",
            create=True,
        )

        result = app.documentation_overview()
        saved = app.write_documentation()

        self.assertIn("# Home Assistant YAML Dokumentation", result["content"])
        self.assertIn("doc_script", result["content"])
        self.assertEqual(result["summary"]["files"], 1)
        self.assertTrue(Path(saved["path"]).is_file())

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

    def test_backup_center_manifests_pin_and_retention(self):
        app.update_settings({"backupRetention": 5, "backupRetentionDays": 0, "backupMaxSizeMiB": 0})
        created = app.write_file("manifest.yaml", "script:\n  manifest: {}\n", None, "Tests", create=True)
        updated = app.write_file(
            created["path"],
            "script:\n  manifest:\n    alias: Neu\n    sequence: []\n",
            created["version"],
            "Tests",
            create=False,
        )
        backup_id = app.backup_history("package", created["path"])["entries"][0]["id"]
        manifest = json.loads((app.DATA_ROOT / "backups" / backup_id / "manifest.json").read_text(encoding="utf-8"))

        pinned = app.set_backup_pin(backup_id, True)
        app.update_settings({"backupRetention": 5, "backupMaxSizeMiB": 1})
        overview = app.backup_overview()

        self.assertEqual(manifest["type"], "file")
        self.assertEqual(manifest["files"][0]["path"], created["path"])
        self.assertEqual(manifest["files"][0]["sha256"], created["version"])
        self.assertTrue(any(item["id"] == backup_id and item["pinned"] for item in pinned["backups"]))
        self.assertTrue((app.DATA_ROOT / "backups" / backup_id).is_dir())
        self.assertGreaterEqual(overview["summary"]["pinned"], 1)
        self.assertEqual(app.read_file(created["path"])["version"], updated["version"])

    def test_snapshot_preview_restore_and_integrity(self):
        configuration = app.PACKAGES_ROOT.parent / "configuration.yaml"
        configuration.write_text("homeassistant:\n  packages: !include_dir_named packages\n", encoding="utf-8")
        app.write_file(
            "snapshot.yaml",
            "script:\n  snapshot:\n    alias: Alt\n    sequence: []\n",
            None,
            "Tests",
            create=True,
        )
        with patch.object(app, "check_home_assistant_configuration", return_value={"valid": True}):
            snapshot = app.create_backup_snapshot({"secretsMode": "none"})
            snapshot_id = snapshot["snapshot"]["id"]
            changed = app.read_file("snapshot.yaml")
            app.write_file(
                "snapshot.yaml",
                changed["content"].replace("alias: Alt", "alias: Neu"),
                changed["version"],
                "Tests",
                create=False,
            )
            preview = app.snapshot_restore_preview(snapshot_id)
            restored = app.restore_snapshot(snapshot_id, preview["stateVersion"])

        self.assertTrue(preview["valid"])
        self.assertTrue(any(file["path"] == "packages/snapshot.yaml" for file in preview["files"]))
        self.assertIn("alias: Alt", app.read_file("snapshot.yaml")["content"])
        self.assertEqual(restored["restored"], 2)
        self.assertEqual(app.backup_integrity()["summary"]["errors"], 0)

    def test_recorder_database_backup_uses_sqlite_backup(self):
        self.create_recorder_database()

        result = app.create_database_backup()
        backup_id = result["databaseBackup"]["id"]
        backup_path = app.DATA_ROOT / "db-backups" / backup_id / "home-assistant_v2.db"

        with sqlite3.connect(backup_path) as connection:
            count = connection.execute("SELECT COUNT(*) FROM states").fetchone()[0]

        self.assertTrue(backup_path.is_file())
        self.assertGreater(count, 0)
        self.assertEqual(app.backup_overview()["summary"]["databaseBackups"], 1)
        self.assertEqual(app.backup_integrity()["summary"]["errors"], 0)

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

    def test_lint_rules_are_configurable_and_feed_preflight_dashboard(self):
        app.update_settings(
            {
                "lintRules": {
                    "requireAlias": True,
                    "requireScriptMode": True,
                    "requireAutomationId": True,
                    "allowedEntityDomains": ["light"],
                    "requiredTags": ["reviewed"],
                }
            }
        )
        app.write_file(
            "lint.yaml",
            "script:\n"
            "  lint_test:\n"
            "    sequence:\n"
            "      - action: switch.turn_on\n"
            "        target:\n"
            "          entity_id: switch.steckdose\n",
            None,
            "Tests",
            create=True,
        )

        lint = app.lint_scan()
        preflight = app.preflight()
        dashboard = app.configuration_quality_dashboard()
        codes = {finding["code"] for finding in lint["findings"]}

        self.assertIn("lint-missing-alias", codes)
        self.assertIn("lint-missing-script-mode", codes)
        self.assertIn("lint-entity-domain", codes)
        self.assertIn("lint-missing-required-tag", codes)
        self.assertIn("lint", {check["id"] for check in preflight["checks"]})
        self.assertTrue(any(finding["code"].startswith("lint-") for finding in dashboard["findings"]))

    def test_database_analysis_reports_recorder_health_entities_and_statistics(self):
        self.create_recorder_database()

        health = app.database_health()
        entities = app.database_entities()
        statistics = app.database_statistics()

        self.assertTrue(health["available"])
        self.assertEqual(health["quickCheck"], "ok")
        self.assertGreaterEqual(health["summary"]["tables"], 6)
        self.assertGreater(health["summary"]["rows"], 0)
        self.assertEqual(entities["noisy"][0]["entityId"], "sensor.noisy")
        self.assertTrue(
            any(item["entityId"] == "sensor.dead" for item in entities["badStateEntities"])
        )
        self.assertTrue(any(item["statisticId"] == "sensor.energy" for item in statistics["gaps"]))
        self.assertTrue(
            any(item["statistic_id"] == "sensor.energy" for item in statistics["unitChanges"])
        )
        self.assertTrue(
            any(item["statistic_id"] == "sensor.no_class" for item in statistics["stateClassWarnings"])
        )

    def test_database_yaml_compare_and_safe_sql_query(self):
        self.create_recorder_database()
        (app.PACKAGES_ROOT / "db.yaml").write_text(
            "script:\n"
            "  db_check:\n"
            "    sequence:\n"
            "      - action: light.turn_on\n"
            "        target:\n"
            "          entity_id: light.used\n"
            "      - action: light.turn_on\n"
            "        target:\n"
            "          entity_id: light.missing\n",
            encoding="utf-8",
        )

        compare = app.database_yaml_compare()
        missing = {item["entityId"] for item in compare["yamlMissingInDatabase"]}
        database_only = {item["entityId"] for item in compare["databaseOnly"]}
        query = app.database_query(
            {"sql": "SELECT entity_id FROM states_meta ORDER BY entity_id", "limit": 2}
        )

        self.assertIn("light.missing", missing)
        self.assertIn("sensor.db_only", database_only)
        self.assertEqual(query["rowCount"], 2)
        self.assertTrue(query["truncated"])
        with self.assertRaises(app.ApiError) as raised:
            app.database_query({"sql": "DELETE FROM states", "limit": 10})
        self.assertEqual(raised.exception.status, 400)

    def test_review_preview_and_apply_grouped_changes(self):
        created = app.write_file(
            "review.yaml",
            "script:\n  review:\n    alias: Alt\n    mode: single\n    sequence: []\n",
            None,
            "Tests",
            create=True,
        )
        body = {
            "changes": [
                {
                    "path": "packages/review.yaml",
                    "content": created["content"].replace("alias: Alt", "alias: Neu"),
                    "category": "Review",
                    "tags": ["checked"],
                }
            ]
        }
        preview = app.review_preview(body)

        result = app.apply_review({**body, "stateVersion": preview["stateVersion"]})

        saved = app.read_file("review.yaml")
        self.assertTrue(preview["ready"])
        self.assertIn("alias: Neu", saved["content"])
        self.assertEqual(saved["category"], "Review")
        self.assertEqual(saved["tags"], ["checked"])
        self.assertEqual(result["summary"]["updates"], 1)

    def test_typed_refactor_updates_scene_device_and_package_paths(self):
        created = app.write_file(
            "typed_refactor.yaml",
            "scene:\n"
            "  old_scene:\n"
            "    name: Old Scene\n"
            "    entities: {}\n"
            "script:\n"
            "  caller:\n"
            "    alias: Caller\n"
            "    mode: single\n"
            "    sequence:\n"
            "      - action: scene.old_scene\n"
            "      - device_id: device_old\n"
            "        domain: light\n",
            None,
            "Refactor",
            create=True,
            tags=["move"],
        )

        scene_preview = app.refactor_preview("scene", "scene.old_scene", "scene.new_scene")
        app.apply_refactor("scene", "scene.old_scene", "scene.new_scene", scene_preview["stateVersion"])
        device_preview = app.refactor_preview("device_id", "device_old", "device_new")
        app.apply_refactor("device_id", "device_old", "device_new", device_preview["stateVersion"])
        move_preview = app.refactor_preview("package", created["path"], "archiv/typed_refactor.yaml")
        move = app.apply_refactor("package", created["path"], "archiv/typed_refactor.yaml", move_preview["stateVersion"])

        content = app.read_file("archiv/typed_refactor.yaml")["content"]
        self.assertIn("new_scene:", content)
        self.assertIn("action: scene.new_scene", content)
        self.assertIn("device_id: device_new", content)
        self.assertEqual(app.read_file("archiv/typed_refactor.yaml")["category"], "Refactor")
        self.assertEqual(move["newValue"], "archiv/typed_refactor.yaml")

    def test_compatibility_scan_detects_legacy_keys_and_services(self):
        app.write_file(
            "compat.yaml",
            "script:\n"
            "  compat:\n"
            "    alias: Compat\n"
            "    mode: single\n"
            "    sequence:\n"
            "      - service: homeassistant.reload_core_config\n"
            "        data_template:\n"
            "          value: \"{{ 1 }}\"\n",
            None,
            "Tests",
            create=True,
        )

        result = app.compatibility_scan()
        codes = {finding["code"] for finding in result["findings"]}

        self.assertIn("compat-legacy-key", codes)
        self.assertIn("compat-deprecated-service", codes)
        self.assertIn("compat-service-action-alias", codes)

    def test_global_graph_connects_objects_entities_secrets_and_blueprints(self):
        app.write_file(
            "graph.yaml",
            "script:\n"
            "  graph_test:\n"
            "    alias: Graph Test\n"
            "    mode: single\n"
            "    use_blueprint:\n"
            "      path: local/test.yaml\n"
            "    sequence:\n"
            "      - action: light.turn_on\n"
            "        target:\n"
            "          entity_id: light.graph\n"
            "        data:\n"
            "          token: !secret graph_token\n",
            None,
            "Tests",
            create=True,
        )

        result = app.global_graph()
        node_types = {node["type"] for node in result["nodes"]}
        relations = {edge["relation"] for edge in result["edges"]}

        self.assertIn("object", node_types)
        self.assertIn("entity", node_types)
        self.assertIn("secret", node_types)
        self.assertIn("blueprint", node_types)
        self.assertIn("defines", relations)
        self.assertIn("entity", relations)
        self.assertIn("secret", relations)
        self.assertIn("blueprint", relations)


if __name__ == "__main__":
    unittest.main()
