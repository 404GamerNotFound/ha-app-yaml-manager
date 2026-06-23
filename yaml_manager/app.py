"""HTTP backend for the Home Assistant YAML Script Manager."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml

try:
    from .api import create_handler
    from . import backup as backup_service
    from . import configuration as configuration_service
    from . import git as git_service
    from . import metadata as metadata_service
    from . import resources as resource_service
    from . import settings as settings_service
    from .dependencies import (
        analyze_dependencies,
        focus_dependencies,
        package_state_version,
        plan_script_rename,
    )
    from .errors import ApiError
    from .file_cache import TextFileCache
    from .validation import HomeAssistantLoader, validate_yaml as validate_yaml_content
except ImportError:  # pragma: no cover - direct execution in the app container
    from api import create_handler
    import backup as backup_service
    import configuration as configuration_service
    import git as git_service
    import metadata as metadata_service
    import resources as resource_service
    import settings as settings_service
    from dependencies import (
        analyze_dependencies,
        focus_dependencies,
        package_state_version,
        plan_script_rename,
    )
    from errors import ApiError
    from file_cache import TextFileCache
    from validation import HomeAssistantLoader, validate_yaml as validate_yaml_content


PORT = int(os.environ.get("PORT", "8099"))
PACKAGES_ROOT = Path(os.environ.get("PACKAGES_PATH", "/homeassistant/packages")).resolve()
DATA_ROOT = Path(os.environ.get("DATA_PATH", "/data")).resolve()
STATIC_ROOT = Path(__file__).parent / "static"
METADATA_FILE = DATA_ROOT / "metadata.json"
GIT_REMOTE_FILE = DATA_ROOT / "git_remote.json"
SETTINGS_FILE = DATA_ROOT / "settings.json"
GIT_REMOTE_NAME = "yaml-manager"
GIT_ASKPASS = Path(__file__).parent / "git_askpass.py"
MAX_FILE_SIZE = 2 * 1024 * 1024
MAX_IMPORT_SIZE = 10 * 1024 * 1024
MAX_IMPORT_EXPANDED_SIZE = 50 * 1024 * 1024
MAX_IMPORT_FILES = 500
VALID_SUFFIXES = {".yaml", ".yml"}
DEFAULT_CATEGORY = "Ohne Kategorie"
PACKAGE_DIRECTORY_TAGS = {"!include_dir_named", "!include_dir_merge_named"}
DIRECTORY_INCLUDE_TAGS = {
    "!include_dir_list",
    "!include_dir_named",
    "!include_dir_merge_list",
    "!include_dir_merge_named",
}

metadata_lock = threading.RLock()
file_lock = threading.RLock()
git_lock = threading.RLock()
yaml_text_cache = TextFileCache()
last_configuration_check: dict[str, Any] | None = None


def ensure_directories() -> None:
    PACKAGES_ROOT.mkdir(parents=True, exist_ok=True)
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    (DATA_ROOT / "backups").mkdir(exist_ok=True)
    (DATA_ROOT / "trash").mkdir(exist_ok=True)


def load_settings() -> dict[str, Any]:
    return settings_service.load_settings(sys.modules[__name__])


def update_settings(body: dict[str, Any]) -> dict[str, Any]:
    return settings_service.update_settings(sys.modules[__name__], body)


def import_limits() -> dict[str, int]:
    settings = load_settings()
    return {
        "maxImportFiles": settings["maxImportFiles"],
        "maxImportSize": settings["maxImportSizeMiB"] * 1024 * 1024,
        "maxExpandedImportSize": settings["maxExpandedImportSizeMiB"] * 1024 * 1024,
    }


def import_request_size_limit() -> int:
    return import_limits()["maxImportSize"] * 2


def backup_retention_count() -> int:
    return load_settings()["backupRetention"]


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def load_metadata() -> dict[str, Any]:
    return metadata_service.load_metadata(sys.modules[__name__])


def file_metadata(metadata: dict[str, Any], relative: str) -> dict[str, Any]:
    return metadata_service.file_metadata(sys.modules[__name__], metadata, relative)


def sanitize_tags(tags: Any) -> list[str]:
    return metadata_service.sanitize_tags(tags)


def save_metadata(metadata: dict[str, Any]) -> None:
    metadata_service.save_metadata(sys.modules[__name__], metadata)


def normalize_relative_path(raw_path: str) -> tuple[str, Path]:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ein Dateipfad ist erforderlich.")
    normalized = raw_path.strip().replace("\\", "/").lstrip("/")
    relative = Path(normalized)
    if relative.suffix.lower() not in VALID_SUFFIXES:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Nur .yaml- und .yml-Dateien sind erlaubt.")
    if any(part in {"", ".", ".."} or part.startswith(".") for part in relative.parts):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der Dateipfad ist ungueltig.")
    packages_root = PACKAGES_ROOT.resolve()
    absolute = (packages_root / relative).resolve()
    try:
        absolute.relative_to(packages_root)
    except ValueError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der Dateipfad liegt ausserhalb von packages.") from exc
    return relative.as_posix(), absolute


def _configuration_call(name: str, *args: Any, **kwargs: Any) -> Any:
    configuration_service.bind(sys.modules[__name__])
    return getattr(configuration_service, name)(*args, **kwargs)


def configuration_file() -> Path:
    return _configuration_call("configuration_file")


def mapping_value(node: yaml.Node | None, key: str) -> yaml.Node | None:
    return _configuration_call("mapping_value", node, key)


def compose_yaml(path: Path) -> yaml.Node | None:
    return _configuration_call("compose_yaml", path)


def resolve_include(value: str, base_directory: Path) -> Path:
    return _configuration_call("resolve_include", value, base_directory)


def package_node_uses_directory(
    node: yaml.Node | None,
    base_directory: Path,
    expected_directory: Path,
    visited: set[Path],
) -> bool:
    return _configuration_call(
        "package_node_uses_directory", node, base_directory, expected_directory, visited
    )


def homeassistant_node_uses_packages(node: yaml.Node | None, base_directory: Path, expected_directory: Path, visited: set[Path]) -> bool:
    return _configuration_call("homeassistant_node_uses_packages", node, base_directory, expected_directory, visited)


def package_configuration_status() -> dict[str, Any]:
    return _configuration_call("package_configuration_status")


def read_configuration() -> dict[str, Any]:
    return _configuration_call("read_configuration")


def atomic_write_path(path: Path, content: bytes, mode: int = 0o644) -> None:
    _configuration_call("atomic_write_path", path, content, mode)


GitOperationError = git_service.GitOperationError


def _git_call(name: str, *args: Any, **kwargs: Any) -> Any:
    git_service.bind(sys.modules[__name__])
    return getattr(git_service, name)(*args, **kwargs)


def git_root() -> Path:
    return _git_call("git_root")


def git_relative_path(path: Path) -> str:
    return _git_call("git_relative_path", path)


def run_git(arguments: list[str], allowed_codes: tuple[int, ...] = (0,), environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    return _git_call("run_git", arguments, allowed_codes, environment)


def git_has_head() -> bool:
    return _git_call("git_has_head")


def git_commit_staged(message: str, relative_paths: list[str]) -> dict[str, Any]:
    return _git_call("git_commit_staged", message, relative_paths)


def ensure_git_repository() -> dict[str, Any]:
    return _git_call("ensure_git_repository")


def git_commit_paths(paths: list[Path], message: str) -> dict[str, Any]:
    return _git_call("git_commit_paths", paths, message)


def git_checkpoint(paths: list[Path]) -> dict[str, Any]:
    return _git_call("git_checkpoint", paths)


def public_git_remote_config(config: dict[str, Any]) -> dict[str, Any]:
    return _git_call("public_git_remote_config", config)


def load_git_remote_config() -> dict[str, Any]:
    return _git_call("load_git_remote_config")


def validate_git_remote_url(raw_url: Any) -> tuple[str, str]:
    return _git_call("validate_git_remote_url", raw_url)


def validate_git_branch(raw_branch: Any) -> str:
    return _git_call("validate_git_branch", raw_branch)


def git_branches() -> dict[str, Any]:
    return _git_call("git_branches")


def create_git_branch(raw_branch: Any) -> dict[str, Any]:
    return _git_call("create_git_branch", raw_branch)


def switch_git_branch(raw_branch: Any) -> dict[str, Any]:
    return _git_call("switch_git_branch", raw_branch)


def branch_merge_preview(raw_branch: Any) -> dict[str, Any]:
    return _git_call("branch_merge_preview", raw_branch)


def merge_git_branch(raw_branch: Any, state_version: Any) -> dict[str, Any]:
    return _git_call("merge_git_branch", raw_branch, state_version)


def save_git_remote_file(config: dict[str, Any]) -> None:
    _git_call("save_git_remote_file", config)


def configure_git_remote(url: str) -> None:
    _git_call("configure_git_remote", url)


def git_remote_environment(config: dict[str, Any]) -> dict[str, str]:
    return _git_call("git_remote_environment", config)


def run_git_remote(arguments: list[str], config: dict[str, Any], allowed_codes: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[bytes]:
    return _git_call("run_git_remote", arguments, config, allowed_codes)


def git_ahead_behind(branch: str) -> tuple[int, int]:
    return _git_call("git_ahead_behind", branch)


def git_remote_status() -> dict[str, Any]:
    return _git_call("git_remote_status")


def update_git_remote(body: dict[str, Any]) -> dict[str, Any]:
    return _git_call("update_git_remote", body)


def auto_push_after_change(git_result: dict[str, Any] | None = None) -> dict[str, Any]:
    return _git_call("auto_push_after_change", git_result)


def remove_git_remote() -> dict[str, Any]:
    return _git_call("remove_git_remote")


def validate_remote_yaml(reference: str, relative: str) -> None:
    _git_call("validate_remote_yaml", reference, relative)


def safe_remote_auxiliary_path(relative: str) -> bool:
    return _git_call("safe_remote_auxiliary_path", relative)


def validate_remote_auxiliary_file(reference: str, relative: str) -> None:
    _git_call("validate_remote_auxiliary_file", reference, relative)


def prepare_remote_fast_forward(branch: str) -> list[str]:
    return _git_call("prepare_remote_fast_forward", branch)


def prepare_remote_history_merge(branch: str) -> list[str]:
    return _git_call("prepare_remote_history_merge", branch)


def synchronize_git_remote(action: str) -> dict[str, Any]:
    return _git_call("synchronize_git_remote", action)


def write_configuration(content: str, expected_version: str | None) -> dict[str, Any]:
    return _configuration_call("write_configuration", content, expected_version)


def mapping_pair(node: yaml.Node | None, key: str) -> tuple[yaml.Node, yaml.Node] | None:
    return _configuration_call("mapping_pair", node, key)


def insert_line_after_node(content: str, node: yaml.Node, line: str) -> str:
    return _configuration_call("insert_line_after_node", content, node, line)


def package_mode(node: yaml.Node, base_directory: Path) -> str | None:
    return _configuration_call("package_mode", node, base_directory)


def add_packages_to_mapping(*args: Any, **kwargs: Any) -> str:
    return _configuration_call("add_packages_to_mapping", *args, **kwargs)


def prepare_package_enable(content: str) -> tuple[dict[Path, tuple[bytes, bytes]], str]:
    return _configuration_call("prepare_package_enable", content)


def enable_packages(content: str, expected_version: str | None) -> dict[str, Any]:
    return _configuration_call("enable_packages", content, expected_version)


def homeassistant_package_mode(*args: Any, **kwargs: Any) -> str | None:
    return _configuration_call("homeassistant_package_mode", *args, **kwargs)


def configuration_package_mode(content: str) -> str | None:
    return _configuration_call("configuration_package_mode", content)


def collect_include_nodes(node: yaml.Node | None, result: list[yaml.ScalarNode]) -> None:
    _configuration_call("collect_include_nodes", node, result)


def render_include_node(node: yaml.ScalarNode, value: str) -> str:
    return _configuration_call("render_include_node", node, value)


def rewrite_section_includes(*args: Any, **kwargs: Any) -> str:
    return _configuration_call("rewrite_section_includes", *args, **kwargs)


def prepare_configuration_migration(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _configuration_call("prepare_configuration_migration", *args, **kwargs)


def configuration_migration_preview(content: str, package_name: str) -> dict[str, Any]:
    return _configuration_call("configuration_migration_preview", content, package_name)


def migrate_configuration(content: str, expected_version: str | None, package_name: str) -> dict[str, Any]:
    return _configuration_call("migrate_configuration", content, expected_version, package_name)


def file_version(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def read_yaml_text(path: Path) -> str:
    """Read a small UTF-8 YAML file through the shared scan cache."""

    return yaml_text_cache.read_text(path, MAX_FILE_SIZE)


def read_file(raw_path: str) -> dict[str, Any]:
    relative, absolute = normalize_relative_path(raw_path)
    try:
        content = absolute.read_bytes()
    except FileNotFoundError as exc:
        raise ApiError(HTTPStatus.NOT_FOUND, "Die Datei wurde nicht gefunden.") from exc
    if len(content) > MAX_FILE_SIZE:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Die Datei ist groesser als 2 MiB.")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Die Datei ist nicht UTF-8-kodiert.") from exc
    metadata = load_metadata()
    attributes = file_metadata(metadata, relative)
    return {
        "path": relative,
        "content": text,
        "version": file_version(content),
        "category": attributes["category"],
        "tags": attributes["tags"],
        "modified": absolute.stat().st_mtime,
    }


def validate_yaml(content: str) -> dict[str, Any]:
    return validate_yaml_content(content, MAX_FILE_SIZE)


def duplicate_key_findings(node: yaml.Node | None) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def visit(current: yaml.Node | None) -> None:
        if isinstance(current, yaml.MappingNode):
            seen: dict[tuple[str, str], yaml.Node] = {}
            for key_node, value_node in current.value:
                if isinstance(key_node, yaml.ScalarNode):
                    identity = (key_node.tag, key_node.value)
                    if identity in seen:
                        findings.append(
                            {
                                "severity": "error",
                                "code": "duplicate-key",
                                "title": f'Doppelter Schlüssel „{key_node.value}“',
                                "message": "Der Schlüssel ist im selben YAML-Block mehrfach vorhanden und überschreibt eine Definition.",
                                "line": key_node.start_mark.line + 1,
                            }
                        )
                    else:
                        seen[identity] = key_node
                visit(value_node)
        elif isinstance(current, yaml.SequenceNode):
            for child in current.value:
                visit(child)

    visit(node)
    return findings


def script_definitions(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        return {}
    scripts = document.get("script")
    return scripts if isinstance(scripts, dict) else {}


def collect_entity_references(value: Any, references: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "entity_id":
                candidates = child if isinstance(child, list) else [child]
                for candidate in candidates:
                    if isinstance(candidate, str) and "{{" not in candidate:
                        references.extend(
                            item.strip() for item in candidate.split(",") if item.strip()
                        )
            collect_entity_references(child, references)
    elif isinstance(value, list):
        for child in value:
            collect_entity_references(child, references)


def other_script_locations(current_path: str) -> dict[str, list[str]]:
    locations: dict[str, list[str]] = {}
    packages_root = PACKAGES_ROOT.resolve()
    if not packages_root.exists():
        return locations
    for path in sorted(packages_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in VALID_SUFFIXES:
            continue
        try:
            relative = path.relative_to(packages_root).as_posix()
            if relative == current_path or path.stat().st_size > MAX_FILE_SIZE:
                continue
            text = read_yaml_text(path)
            documents = yaml.load_all(text, Loader=HomeAssistantLoader)
            for document in documents:
                for script_id in script_definitions(document):
                    locations.setdefault(str(script_id), []).append(relative)
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            continue
    return locations


def analyze_yaml(content: str, current_path: str = "") -> dict[str, Any]:
    validation = validate_yaml(content)
    findings: list[dict[str, Any]] = []

    try:
        nodes = list(yaml.compose_all(content, Loader=HomeAssistantLoader))
        for node in nodes:
            findings.extend(duplicate_key_findings(node))
    except yaml.YAMLError:
        nodes = []

    if not validation["valid"]:
        if not findings:
            findings.append(
                {
                    "severity": "error",
                    "code": "yaml-syntax",
                    "title": "YAML-Syntaxfehler",
                    "message": validation["message"],
                    "line": validation.get("line"),
                }
            )
        return analysis_result(validation, findings)

    if content.count("{{") != content.count("}}") or content.count("{%") != content.count("%}"):
        findings.append(
            {
                "severity": "warning",
                "code": "template-balance",
                "title": "Template-Klammern prüfen",
                "message": "Die Anzahl der öffnenden und schließenden Jinja-Klammern ist unterschiedlich.",
            }
        )

    documents = list(yaml.load_all(content, Loader=HomeAssistantLoader))
    if len(documents) > 1:
        findings.append(
            {
                "severity": "tip",
                "code": "multiple-documents",
                "title": "Mehrere YAML-Dokumente",
                "message": "Die Datei enthält mehrere mit --- getrennte Dokumente. Home Assistant erwartet in Packages üblicherweise ein Dokument.",
            }
        )

    scripts: dict[str, Any] = {}
    for document in documents:
        scripts.update(script_definitions(document))

    if not scripts:
        findings.append(
            {
                "severity": "tip",
                "code": "no-script-section",
                "title": "Keine script-Sektion gefunden",
                "message": "Für ein Package mit Skripten wird normalerweise ein oberster Schlüssel script: verwendet.",
            }
        )

    external = other_script_locations(current_path) if scripts else {}
    for script_id, definition in scripts.items():
        script_name = str(script_id)
        if not re.fullmatch(r"[a-z0-9_]+", script_name):
            findings.append(
                {
                    "severity": "warning",
                    "code": "script-id",
                    "title": f'Ungünstige Script-ID „{script_name}“',
                    "message": "Script-IDs sollten nur Kleinbuchstaben, Ziffern und Unterstriche enthalten.",
                }
            )
        if script_name in external:
            findings.append(
                {
                    "severity": "error",
                    "code": "duplicate-script-id",
                    "title": f'Script-ID „{script_name}“ mehrfach definiert',
                    "message": f'Weitere Definition in: {", ".join(external[script_name][:3])}',
                }
            )
        if not isinstance(definition, dict):
            findings.append(
                {
                    "severity": "error",
                    "code": "script-structure",
                    "title": f'Unvollständiges Skript „{script_name}“',
                    "message": "Die Script-Definition muss ein YAML-Objekt sein.",
                }
            )
            continue
        if "sequence" not in definition:
            findings.append(
                {
                    "severity": "error",
                    "code": "missing-sequence",
                    "title": f'Sequenz fehlt in „{script_name}“',
                    "message": "Jedes Skript benötigt eine sequence: mit den auszuführenden Aktionen.",
                }
            )
        elif definition.get("sequence") == []:
            findings.append(
                {
                    "severity": "warning",
                    "code": "empty-sequence",
                    "title": f'Leere Sequenz in „{script_name}“',
                    "message": "Das Skript enthält aktuell keine ausführbare Aktion.",
                }
            )
        if not definition.get("alias"):
            findings.append(
                {
                    "severity": "tip",
                    "code": "missing-alias",
                    "title": f'Alias für „{script_name}“ ergänzen',
                    "message": "Ein sprechender Alias verbessert die Anzeige in Home Assistant.",
                }
            )
        if "mode" not in definition:
            findings.append(
                {
                    "severity": "tip",
                    "code": "missing-mode",
                    "title": f'Modus für „{script_name}“ festlegen',
                    "message": "Mit mode: single, restart, queued oder parallel wird das Verhalten bei erneutem Start eindeutig.",
                }
            )

    references: list[str] = []
    for document in documents:
        collect_entity_references(document, references)
    reference_counts = Counter(references)
    duplicates = sorted(
        (entity for entity, count in reference_counts.items() if count > 1), key=str.casefold
    )
    for entity in duplicates[:10]:
        count = reference_counts[entity]
        findings.append(
            {
                "severity": "warning",
                "code": "duplicate-entity",
                "title": f'Entität „{entity}“ {count}-mal verwendet',
                "message": "Prüfe, ob die mehrfache Belegung beabsichtigt ist.",
            }
        )

    return analysis_result(validation, findings)


def analysis_result(validation: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
    order = {"error": 0, "warning": 1, "tip": 2}
    findings.sort(key=lambda item: (order.get(item["severity"], 3), item.get("line", 0)))
    counts = {
        severity: sum(item["severity"] == severity for item in findings)
        for severity in ("error", "warning", "tip")
    }
    score = max(0, 100 - counts["error"] * 30 - counts["warning"] * 10 - counts["tip"] * 3)
    return {"validation": validation, "findings": findings, "counts": counts, "score": score}


def update_file_metadata(relative: str, category: str, tags: Any = None) -> None:
    clean = category.strip() if isinstance(category, str) else DEFAULT_CATEGORY
    clean = clean[:80] or DEFAULT_CATEGORY
    with metadata_lock:
        metadata = load_metadata()
        existing = file_metadata(metadata, relative)
        clean_tags = existing["tags"] if tags is None else sanitize_tags(tags)
        metadata["files"][relative] = {"category": clean, "tags": clean_tags}
        if clean != DEFAULT_CATEGORY and clean not in metadata["categories"]:
            metadata["categories"].append(clean)
            metadata["categories"].sort(key=str.casefold)
        save_metadata(metadata)


def create_backup(relative: str, source: Path) -> None:
    backup_service.create_backup(sys.modules[__name__], relative, source)


def history_target(scope: str, raw_path: str = "") -> tuple[str, Path, Path]:
    return backup_service.history_target(sys.modules[__name__], scope, raw_path)


def backup_file(backup_id: str, relative: Path) -> Path:
    return backup_service.backup_file(sys.modules[__name__], backup_id, relative)


def backup_history(scope: str, raw_path: str = "") -> dict[str, Any]:
    return backup_service.backup_history(sys.modules[__name__], scope, raw_path)


def backup_diff(scope: str, raw_path: str, backup_id: str) -> dict[str, Any]:
    return backup_service.backup_diff(sys.modules[__name__], scope, raw_path, backup_id)


def restore_backup(
    scope: str,
    raw_path: str,
    backup_id: str,
    expected_version: str | None,
) -> dict[str, Any]:
    return backup_service.restore_backup(
        sys.modules[__name__], scope, raw_path, backup_id, expected_version
    )


def git_history_target(scope: str, raw_path: str = "") -> tuple[str, Path, str]:
    return _git_call("git_history_target", scope, raw_path)


def resolve_git_commit(raw_commit: str) -> str:
    return _git_call("resolve_git_commit", raw_commit)


def git_file_at_commit(commit: str, relative: str) -> bytes:
    return _git_call("git_file_at_commit", commit, relative)


def git_history(scope: str, raw_path: str = "") -> dict[str, Any]:
    return _git_call("git_history", scope, raw_path)


def git_diff(scope: str, raw_path: str, raw_commit: str) -> dict[str, Any]:
    return _git_call("git_diff", scope, raw_path, raw_commit)


def restore_git_version(
    scope: str,
    raw_path: str,
    raw_commit: str,
    expected_version: str | None,
) -> dict[str, Any]:
    return _git_call(
        "restore_git_version", scope, raw_path, raw_commit, expected_version
    )


def write_file(
    raw_path: str,
    content: str,
    expected_version: str | None,
    category: str,
    create: bool,
    tags: Any = None,
) -> dict[str, Any]:
    relative, absolute = normalize_relative_path(raw_path)
    if not create and not isinstance(expected_version, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Dateiversion fehlt. Bitte die Datei neu laden.")
    validation = validate_yaml(content)
    if not validation["valid"]:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "YAML enthaelt einen Syntaxfehler.", validation)

    encoded = content.encode("utf-8")
    with file_lock:
        exists = absolute.exists()
        if create and exists:
            raise ApiError(HTTPStatus.CONFLICT, "Eine Datei mit diesem Namen existiert bereits.")
        if not create and not exists:
            raise ApiError(HTTPStatus.NOT_FOUND, "Die Datei wurde nicht gefunden.")
        if exists:
            current = absolute.read_bytes()
            if expected_version is not None and file_version(current) != expected_version:
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    "Die Datei wurde zwischenzeitlich geaendert. Bitte neu laden.",
                    {"currentVersion": file_version(current)},
                )
            create_backup(relative, absolute)

        git_checkpoint([absolute])

        absolute.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{absolute.name}.", dir=absolute.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            if exists:
                os.chmod(temporary, absolute.stat().st_mode)
            else:
                os.chmod(temporary, 0o644)
            os.replace(temporary, absolute)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        action = "gespeichert" if exists else "erstellt"
        git_result = git_commit_paths([absolute], f"Package {action}: packages/{relative}")

    update_file_metadata(relative, category, tags)
    result = read_file(relative)
    result["configurationCheck"] = check_home_assistant_configuration()
    result["git"] = git_result
    result["gitSync"] = auto_push_after_change(git_result)
    return result


def rename_file(raw_path: str, new_raw_path: str, expected_version: str | None) -> dict[str, Any]:
    relative, source = normalize_relative_path(raw_path)
    new_relative, destination = normalize_relative_path(new_raw_path)
    if not isinstance(expected_version, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Dateiversion fehlt. Bitte die Datei neu laden.")
    if relative == new_relative:
        return read_file(relative)
    with file_lock:
        if not source.exists():
            raise ApiError(HTTPStatus.NOT_FOUND, "Die Datei wurde nicht gefunden.")
        if destination.exists():
            raise ApiError(HTTPStatus.CONFLICT, "Am neuen Pfad existiert bereits eine Datei.")
        current = source.read_bytes()
        if file_version(current) != expected_version:
            raise ApiError(HTTPStatus.CONFLICT, "Die Datei wurde zwischenzeitlich geaendert. Bitte neu laden.")
        git_checkpoint([source, destination])
        create_backup(relative, source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)
        git_result = git_commit_paths(
            [source, destination],
            f"Package umbenannt: packages/{relative} -> packages/{new_relative}",
        )

    with metadata_lock:
        metadata = load_metadata()
        attributes = file_metadata(metadata, relative)
        metadata["files"].pop(relative, None)
        metadata["files"][new_relative] = attributes
        save_metadata(metadata)
    result = read_file(new_relative)
    result["git"] = git_result
    result["gitSync"] = auto_push_after_change(git_result)
    return result


def delete_file(raw_path: str, expected_version: str | None) -> dict[str, Any]:
    relative, absolute = normalize_relative_path(raw_path)
    if not isinstance(expected_version, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Dateiversion fehlt. Bitte die Datei neu laden.")
    with file_lock:
        if not absolute.exists():
            raise ApiError(HTTPStatus.NOT_FOUND, "Die Datei wurde nicht gefunden.")
        current = absolute.read_bytes()
        if expected_version and file_version(current) != expected_version:
            raise ApiError(HTTPStatus.CONFLICT, "Die Datei wurde zwischenzeitlich geaendert. Bitte neu laden.")
        git_checkpoint([absolute])
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000:06d}"
        destination = DATA_ROOT / "trash" / stamp / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(absolute), destination)
        metadata = load_metadata()
        manifest = {
            "path": relative,
            "deletedAt": stamp,
            "metadata": file_metadata(metadata, relative),
        }
        (DATA_ROOT / "trash" / stamp / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        git_result = git_commit_paths([absolute], f"Package gelöscht: packages/{relative}")
    with metadata_lock:
        metadata = load_metadata()
        metadata["files"].pop(relative, None)
        save_metadata(metadata)
    git_result["autoSync"] = auto_push_after_change(git_result)
    return git_result


def _trash_directory(raw_id: Any) -> Path:
    if not isinstance(raw_id, str) or not re.fullmatch(r"\d{8}-\d{6}-\d{6}", raw_id):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ungültige Papierkorb-ID.")
    path = (DATA_ROOT / "trash" / raw_id).resolve()
    trash_root = (DATA_ROOT / "trash").resolve()
    try:
        path.relative_to(trash_root)
    except ValueError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ungültiger Papierkorb-Pfad.") from exc
    if not path.is_dir():
        raise ApiError(HTTPStatus.NOT_FOUND, "Der Papierkorb-Eintrag wurde nicht gefunden.")
    return path


def _trash_file(raw_id: Any, raw_path: Any) -> tuple[str, Path]:
    relative, _destination = normalize_relative_path(raw_path)
    directory = _trash_directory(raw_id)
    path = (directory / relative).resolve()
    try:
        path.relative_to(directory.resolve())
    except ValueError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ungültiger Papierkorb-Pfad.") from exc
    if not path.is_file():
        raise ApiError(HTTPStatus.NOT_FOUND, "Die gelöschte Datei wurde nicht gefunden.")
    return relative, path


def _trash_manifest(directory: Path) -> dict[str, Any]:
    try:
        value = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _cleanup_empty_trash_parents(path: Path, root: Path) -> None:
    current = path.parent
    while current != root and current.exists():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def trash_history() -> dict[str, Any]:
    trash_root = DATA_ROOT / "trash"
    entries: list[dict[str, Any]] = []
    if trash_root.exists():
        for directory in sorted(trash_root.iterdir(), key=lambda item: item.name, reverse=True):
            if not directory.is_dir() or not re.fullmatch(r"\d{8}-\d{6}-\d{6}", directory.name):
                continue
            manifest = _trash_manifest(directory)
            for candidate in sorted(directory.rglob("*")):
                if not candidate.is_file() or candidate.name == "manifest.json":
                    continue
                try:
                    relative = candidate.relative_to(directory).as_posix()
                except ValueError:
                    continue
                if Path(relative).suffix.lower() not in VALID_SUFFIXES:
                    continue
                content = candidate.read_bytes()
                entries.append(
                    {
                        "id": directory.name,
                        "path": relative,
                        "deleted": time.strftime(
                            "%Y-%m-%dT%H:%M:%S",
                            time.strptime(directory.name[:15], "%Y%m%d-%H%M%S"),
                        ),
                        "size": len(content),
                        "version": file_version(content),
                        "category": manifest.get("metadata", {}).get("category", DEFAULT_CATEGORY),
                        "tags": sanitize_tags(manifest.get("metadata", {}).get("tags", [])),
                        "exists": (PACKAGES_ROOT / relative).exists(),
                    }
                )
    return {"entries": entries, "count": len(entries)}


def restore_trash_file(
    raw_id: Any,
    raw_path: Any,
    overwrite: Any = False,
    expected_version: Any = None,
) -> dict[str, Any]:
    relative, source = _trash_file(raw_id, raw_path)
    restored = source.read_bytes()
    try:
        restored_text = restored.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Die gelöschte Datei ist nicht UTF-8-kodiert.") from exc
    validation = validate_yaml(restored_text)
    if not validation["valid"]:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Die gelöschte Datei enthält ungültiges YAML.", validation)
    _normalized, destination = normalize_relative_path(relative)
    directory = source.parents[len(Path(relative).parts) - 1]
    manifest = _trash_manifest(directory)

    with file_lock:
        exists = destination.exists()
        if exists:
            current = destination.read_bytes()
            current_version = file_version(current)
            if not overwrite:
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    "Am ursprünglichen Pfad existiert bereits eine Datei.",
                    {"currentVersion": current_version},
                )
            if not isinstance(expected_version, str) or current_version != expected_version:
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    "Die vorhandene Datei wurde zwischenzeitlich geändert. Bitte neu laden.",
                    {"currentVersion": current_version},
                )
        git_checkpoint([destination])
        if exists:
            create_backup(relative, destination)
        atomic_write_path(destination, restored, destination.stat().st_mode if exists else 0o644)
        source.unlink()
        _cleanup_empty_trash_parents(source, directory)
        if not any(path.is_file() and path.name != "manifest.json" for path in directory.rglob("*")):
            try:
                (directory / "manifest.json").unlink()
            except FileNotFoundError:
                pass
        try:
            directory.rmdir()
        except OSError:
            pass
        git_result = git_commit_paths([destination], f"Package aus Papierkorb wiederhergestellt: packages/{relative}")

    metadata = manifest.get("metadata")
    if isinstance(metadata, dict):
        update_file_metadata(
            relative,
            metadata.get("category", DEFAULT_CATEGORY),
            metadata.get("tags", []),
        )
    result = read_file(relative)
    result["message"] = f"{relative} wurde aus dem Papierkorb wiederhergestellt."
    result["git"] = git_result
    result["gitSync"] = auto_push_after_change(git_result)
    result["configurationCheck"] = check_home_assistant_configuration()
    return result


def purge_trash(raw_id: Any = "", raw_path: Any = "") -> dict[str, Any]:
    trash_root = DATA_ROOT / "trash"
    if raw_id and raw_path:
        _relative, path = _trash_file(raw_id, raw_path)
        directory = _trash_directory(raw_id)
        path.unlink()
        _cleanup_empty_trash_parents(path, directory)
        if not any(candidate.is_file() and candidate.name != "manifest.json" for candidate in directory.rglob("*")):
            try:
                (directory / "manifest.json").unlink()
            except FileNotFoundError:
                pass
        try:
            directory.rmdir()
        except OSError:
            pass
    elif raw_id:
        shutil.rmtree(_trash_directory(raw_id))
    else:
        for directory in (trash_root.iterdir() if trash_root.exists() else []):
            if directory.is_dir() and re.fullmatch(r"\d{8}-\d{6}-\d{6}", directory.name):
                shutil.rmtree(directory)
    return trash_history()


def list_files() -> dict[str, Any]:
    metadata = load_metadata()
    files: list[dict[str, Any]] = []
    packages_root = PACKAGES_ROOT.resolve()
    if packages_root.exists():
        for path in sorted(packages_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in VALID_SUFFIXES:
                continue
            try:
                path.resolve().relative_to(packages_root)
            except ValueError:
                continue
            relative = path.relative_to(packages_root).as_posix()
            if any(part.startswith(".") for part in Path(relative).parts):
                continue
            stat = path.stat()
            attributes = file_metadata(metadata, relative)
            files.append(
                {
                    "path": relative,
                    "name": path.stem,
                    "category": attributes["category"],
                    "tags": attributes["tags"],
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                }
            )
    used = {item["category"] for item in files}
    tags = sorted({tag for item in files for tag in item["tags"]}, key=str.casefold)
    categories = sorted(
        {DEFAULT_CATEGORY, *metadata["categories"], *used},
        key=lambda value: (value == DEFAULT_CATEGORY, value.casefold()),
    )
    return {
        "files": files,
        "categories": categories,
        "tags": tags,
        "root": str(PACKAGES_ROOT),
        "configuration": package_configuration_status(),
    }


def package_contents() -> dict[str, str]:
    """Read the current UTF-8 package set for cross-file analyses."""

    result: dict[str, str] = {}
    packages_root = PACKAGES_ROOT.resolve()
    if not packages_root.exists():
        return result
    for path in sorted(packages_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in VALID_SUFFIXES:
            continue
        if path.stat().st_size > MAX_FILE_SIZE:
            continue
        try:
            relative = path.relative_to(packages_root).as_posix()
            result[relative] = read_yaml_text(path)
        except (OSError, UnicodeDecodeError):
            continue
    return result


def home_assistant_objects() -> dict[str, Any]:
    return resource_service.home_assistant_objects(sys.modules[__name__])


def read_resource(raw_path: str) -> dict[str, Any]:
    return resource_service.read_resource(sys.modules[__name__], raw_path)


def write_resource(raw_path: str, content: str, expected_version: Any) -> dict[str, Any]:
    return resource_service.write_resource(
        sys.modules[__name__], raw_path, content, expected_version
    )


def search_replace_preview(
    search: Any,
    replacement: Any,
    case_sensitive: Any = True,
) -> dict[str, Any]:
    return resource_service.search_replace_preview(
        sys.modules[__name__], search, replacement, case_sensitive
    )


def apply_search_replace(
    search: Any,
    replacement: Any,
    case_sensitive: Any,
    state_version: Any,
) -> dict[str, Any]:
    return resource_service.apply_search_replace(
        sys.modules[__name__],
        search,
        replacement,
        case_sensitive,
        state_version,
    )


def script_dependency_analysis(raw_path: str = "") -> dict[str, Any]:
    relative = ""
    if raw_path:
        relative, absolute = normalize_relative_path(raw_path)
        if not absolute.is_file():
            raise ApiError(HTTPStatus.NOT_FOUND, "Die Datei wurde nicht gefunden.")
    graph = analyze_dependencies(package_contents())
    return focus_dependencies(graph, relative) if relative else graph


def preview_script_rename(raw_path: str, old_id: str, new_id: str) -> dict[str, Any]:
    relative, absolute = normalize_relative_path(raw_path)
    if not absolute.is_file():
        raise ApiError(HTTPStatus.NOT_FOUND, "Die Datei wurde nicht gefunden.")
    files = package_contents()
    try:
        plan = plan_script_rename(files, relative, old_id, new_id)
    except ValueError as exc:
        raise ApiError(HTTPStatus.CONFLICT, str(exc)) from exc
    return {key: value for key, value in plan.items() if key != "contents"}


def rename_script_with_references(
    raw_path: str,
    old_id: str,
    new_id: str,
    state_version: str,
) -> dict[str, Any]:
    """Rename a script and all recognized references as one transaction."""

    relative, absolute = normalize_relative_path(raw_path)
    if not isinstance(state_version, str) or not state_version:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Vorschau-Version fehlt.")
    with file_lock:
        files = package_contents()
        current_version = package_state_version(files)
        if current_version != state_version:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Eine Package-Datei wurde seit der Vorschau geändert. Bitte die Vorschau neu laden.",
                {"currentStateVersion": current_version},
            )
        try:
            plan = plan_script_rename(files, relative, old_id, new_id)
        except ValueError as exc:
            raise ApiError(HTTPStatus.CONFLICT, str(exc)) from exc
        changed = plan["contents"]
        if not changed:
            raise ApiError(HTTPStatus.CONFLICT, "Für die Umbenennung wurden keine Änderungen gefunden.")
        for path, content in changed.items():
            validation = validate_yaml(content)
            if not validation["valid"]:
                raise ApiError(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    f"Die Umbenennung würde ungültiges YAML in {path} erzeugen.",
                    validation,
                )
        existing_conflicts = package_conflict_analysis()
        conflicts = package_conflict_analysis(changed)
        existing_errors = {
            (item["code"], item["title"], tuple(item.get("files", [])))
            for item in existing_conflicts["findings"]
            if item["severity"] == "error"
        }
        new_errors = [
            item for item in conflicts["findings"]
            if item["severity"] == "error"
            and (item["code"], item["title"], tuple(item.get("files", []))) not in existing_errors
        ]
        if new_errors:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Die Umbenennung würde Package-Konflikte erzeugen.",
                {"conflicts": {**conflicts, "findings": new_errors}},
            )

        paths = [normalize_relative_path(path)[1] for path in changed]
        originals = {path: path.read_bytes() for path in paths}
        modes = {path: path.stat().st_mode for path in paths}
        git_checkpoint(paths)
        for path in paths:
            create_backup(path.relative_to(PACKAGES_ROOT.resolve()).as_posix(), path)
        try:
            for path, content in changed.items():
                destination = normalize_relative_path(path)[1]
                atomic_write_path(destination, content.encode("utf-8"), modes[destination])
        except OSError as exc:
            for path, content in originals.items():
                atomic_write_path(path, content, modes[path])
            raise ApiError(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Die Script-Umbenennung wurde nach einem Schreibfehler zurückgerollt.",
            ) from exc
        git_result = git_commit_paths(
            paths,
            f"Script umbenannt: script.{old_id} -> script.{new_id}",
        )

    result = {key: value for key, value in plan.items() if key != "contents"}
    result.update(
        {
            "message": f"script.{old_id} und alle erkannten Referenzen wurden umbenannt.",
            "file": read_file(relative),
            "dependencies": script_dependency_analysis(relative),
            "configurationCheck": check_home_assistant_configuration(),
            "git": git_result,
            "gitSync": auto_push_after_change(git_result),
        }
    )
    return result


ENTITY_KEY_DOMAINS = {
    "counter",
    "group",
    "input_boolean",
    "input_button",
    "input_datetime",
    "input_number",
    "input_select",
    "input_text",
    "script",
    "shell_command",
    "timer",
}


def node_kind(node: yaml.Node) -> str:
    if isinstance(node, yaml.ScalarNode) and node.tag.startswith("!"):
        return "include"
    if isinstance(node, yaml.MappingNode):
        return "mapping"
    if isinstance(node, yaml.SequenceNode):
        return "list"
    return "scalar"


def collect_node_identifiers(
    node: yaml.Node,
    domain: str,
    source: str,
    unique_ids: dict[tuple[str, str], list[dict[str, Any]]],
    automation_ids: dict[str, list[dict[str, Any]]],
) -> None:
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            if isinstance(key_node, yaml.ScalarNode) and isinstance(value_node, yaml.ScalarNode):
                location = {"file": source, "line": value_node.start_mark.line + 1}
                if key_node.value == "unique_id" and value_node.value:
                    unique_ids.setdefault((domain, value_node.value), []).append(location)
                if domain == "automation" and key_node.value == "id" and value_node.value:
                    automation_ids.setdefault(value_node.value, []).append(location)
            collect_node_identifiers(value_node, domain, source, unique_ids, automation_ids)
    elif isinstance(node, yaml.SequenceNode):
        for child in node.value:
            collect_node_identifiers(child, domain, source, unique_ids, automation_ids)


def add_integration_records(
    mapping: yaml.Node,
    source: str,
    records: dict[str, list[dict[str, Any]]],
    unique_ids: dict[tuple[str, str], list[dict[str, Any]]],
    automation_ids: dict[str, list[dict[str, Any]]],
) -> bool:
    if not isinstance(mapping, yaml.MappingNode):
        return False
    for key_node, value_node in mapping.value:
        if not isinstance(key_node, yaml.ScalarNode):
            continue
        domain = key_node.value.split(" ", 1)[0]
        if domain == "homeassistant" and source == "/config/configuration.yaml":
            continue
        children: dict[str, dict[str, Any]] = {}
        if isinstance(value_node, yaml.MappingNode):
            for child_key, child_value in value_node.value:
                if isinstance(child_key, yaml.ScalarNode):
                    children[child_key.value] = {
                        "kind": node_kind(child_value),
                        "line": child_key.start_mark.line + 1,
                    }
        records.setdefault(domain, []).append(
            {
                "file": source,
                "kind": node_kind(value_node),
                "children": children,
                "line": key_node.start_mark.line + 1,
            }
        )
        collect_node_identifiers(value_node, domain, source, unique_ids, automation_ids)
    return True


def package_conflict_analysis(overlay: dict[str, str] | None = None) -> dict[str, Any]:
    packages_root = PACKAGES_ROOT.resolve()
    findings: list[dict[str, Any]] = []
    records: dict[str, list[dict[str, Any]]] = {}
    unique_ids: dict[tuple[str, str], list[dict[str, Any]]] = {}
    automation_ids: dict[str, list[dict[str, Any]]] = {}
    package_names: dict[str, list[str]] = {}
    mode = "named"
    try:
        configured_mode = configuration_package_mode(read_configuration()["content"])
        if configured_mode:
            mode = configured_mode
    except (ApiError, OSError, yaml.YAMLError):
        pass

    sources: dict[str, str] = {}
    if packages_root.exists():
        for path in sorted(packages_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in VALID_SUFFIXES:
                continue
            relative = path.relative_to(packages_root).as_posix()
            try:
                sources[relative] = read_yaml_text(path)
            except (OSError, UnicodeDecodeError) as exc:
                sources[relative] = ""
                findings.append(
                    {
                        "severity": "error",
                        "code": "invalid-package-yaml",
                        "title": f"{relative} kann nicht analysiert werden",
                        "message": str(exc).split("\n", 1)[0],
                        "files": [relative],
                    }
                )
    if overlay:
        sources.update(overlay)

    for relative, source_content in sorted(sources.items()):
        source_path = Path(relative)
        package_names.setdefault(source_path.stem.casefold(), []).append(relative)
        if source_path.suffix.lower() == ".yml":
            findings.append(
                {
                    "severity": "warning",
                    "code": "unsupported-package-extension",
                    "title": f"{relative} wird nicht automatisch importiert",
                    "message": "Home Assistants Verzeichnis-Includes laden automatisch nur Dateien mit der Endung .yaml.",
                    "files": [relative],
                }
            )
        try:
            documents = list(yaml.compose_all(source_content, Loader=HomeAssistantLoader))
        except yaml.YAMLError as exc:
            findings.append(
                {
                    "severity": "error",
                    "code": "invalid-package-yaml",
                    "title": f"{relative} kann nicht analysiert werden",
                    "message": str(exc).split("\n", 1)[0],
                    "files": [relative],
                }
            )
            continue
        for document in documents:
            mappings: list[tuple[yaml.Node, str]] = []
            if mode == "merge_named" and isinstance(document, yaml.MappingNode):
                mappings.extend((value, f"{relative}#{key.value}") for key, value in document.value if isinstance(key, yaml.ScalarNode))
            else:
                mappings.append((document, relative))
            for mapping, source in mappings:
                if not add_integration_records(mapping, source, records, unique_ids, automation_ids):
                    findings.append(
                        {
                            "severity": "error",
                            "code": "invalid-package-root",
                            "title": f"Ungültige Package-Struktur in {relative}",
                            "message": "Der Package-Inhalt muss ein YAML-Objekt mit Integrationsschlüsseln sein.",
                            "files": [relative],
                        }
                    )

    try:
        configuration = configuration_file()
        main_node = yaml.compose(read_yaml_text(configuration), Loader=HomeAssistantLoader)
        add_integration_records(
            main_node,
            "/config/configuration.yaml",
            records,
            unique_ids,
            automation_ids,
        )
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        pass

    for name, files in package_names.items():
        if len(files) > 1:
            findings.append(
                {
                    "severity": "error",
                    "code": "duplicate-package-name",
                    "title": f'Package-Dateiname „{name}“ ist mehrfach vorhanden',
                    "message": "Bei !include_dir_named müssen Dateinamen auch über Unterordner hinweg eindeutig sein.",
                    "files": files,
                }
            )

    for domain, domain_records in records.items():
        relevant = [record for record in domain_records if record["kind"] != "include"]
        if len(relevant) < 2 or all(record["kind"] == "list" for record in relevant):
            continue
        if all(record["kind"] == "mapping" for record in relevant):
            child_records: dict[str, list[dict[str, Any]]] = {}
            for record in relevant:
                for key, details in record["children"].items():
                    child_records.setdefault(key, []).append({**details, "file": record["file"]})
            for key, duplicates in child_records.items():
                if len(duplicates) < 2 or all(item["kind"] == "list" for item in duplicates):
                    continue
                entity_domain = domain in ENTITY_KEY_DOMAINS
                findings.append(
                    {
                        "severity": "error",
                        "code": "duplicate-entity-id" if entity_domain else "duplicate-integration-key",
                        "title": (
                            f'Doppelte Entity-ID „{domain}.{key}“'
                            if entity_domain
                            else f'Doppelter Schlüssel „{domain}.{key}“'
                        ),
                        "message": "Dieser Schlüssel kann nach den Package-Merge-Regeln nur einmal definiert werden.",
                        "files": [item["file"] for item in duplicates],
                    }
                )
            continue
        findings.append(
            {
                "severity": "error",
                "code": "duplicate-integration",
                "title": f'Integration „{domain}“ ist nicht eindeutig zusammenführbar',
                "message": "Mehrere skalare oder unterschiedlich strukturierte Definitionen können nicht sicher gemergt werden.",
                "files": [record["file"] for record in relevant],
            }
        )

    for (domain, unique_id), locations in unique_ids.items():
        if len(locations) > 1:
            findings.append(
                {
                    "severity": "warning",
                    "code": "duplicate-unique-id",
                    "title": f'Doppelte unique_id „{unique_id}“ in {domain}',
                    "message": "Doppelte Unique-IDs können die Registrierung von Entitäten verhindern.",
                    "files": [location["file"] for location in locations],
                }
            )
    for automation_id, locations in automation_ids.items():
        if len(locations) > 1:
            findings.append(
                {
                    "severity": "error",
                    "code": "duplicate-automation-id",
                    "title": f'Doppelte Automation-ID „{automation_id}“',
                    "message": "Automation-IDs müssen über alle geladenen YAML-Dateien eindeutig sein.",
                    "files": [location["file"] for location in locations],
                }
            )

    findings.sort(key=lambda item: (item["severity"] != "error", item["title"].casefold()))
    counts = {
        "error": sum(item["severity"] == "error" for item in findings),
        "warning": sum(item["severity"] == "warning" for item in findings),
    }
    return {"mode": mode, "findings": findings, "counts": counts, "fileCount": len(sources)}


def collect_script_references(value: Any, references: set[str]) -> None:
    if isinstance(value, dict):
        for child in value.values():
            collect_script_references(child, references)
    elif isinstance(value, list):
        for child in value:
            collect_script_references(child, references)
    elif isinstance(value, str):
        references.update(re.findall(r"\bscript\.([A-Za-z0-9_]+)\b", value))


def recent_git_commits(limit: int = 5) -> list[dict[str, str]]:
    with git_lock:
        try:
            ensure_git_repository()
            output = run_git(
                ["log", "-n", str(limit), "--format=%H%x1f%aI%x1f%s%x1e"]
            ).stdout.decode("utf-8", errors="replace")
        except GitOperationError:
            return []
    commits: list[dict[str, str]] = []
    for record in output.split("\x1e"):
        fields = record.strip().split("\x1f", 2)
        if len(fields) == 3:
            commit, created, subject = fields
            commits.append({"id": commit, "shortId": commit[:8], "created": created, "subject": subject})
    return commits


def configuration_quality_dashboard() -> dict[str, Any]:
    settings = load_settings()
    conflicts = package_conflict_analysis()
    definitions: dict[str, list[str]] = {}
    references: set[str] = set()
    config_root = git_root()
    yaml_paths: list[Path] = []
    if config_root.exists():
        for path in config_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in VALID_SUFFIXES:
                continue
            try:
                relative = path.relative_to(config_root)
            except ValueError:
                continue
            if any(part.startswith(".") for part in relative.parts) or path.stat().st_size > MAX_FILE_SIZE:
                continue
            yaml_paths.append(path)

    for path in sorted(yaml_paths):
        try:
            documents = list(yaml.load_all(read_yaml_text(path), Loader=HomeAssistantLoader))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            continue
        relative = path.relative_to(config_root).as_posix()
        for document in documents:
            if isinstance(document, dict) and isinstance(document.get("script"), dict):
                for script_id in document["script"]:
                    definitions.setdefault(str(script_id), []).append(relative)
            collect_script_references(document, references)

    unused = sorted(set(definitions) - references, key=str.casefold) if settings["showUnusedScripts"] else []
    unused_findings = [
        {
            "severity": "warning",
            "code": "possibly-unused-script",
            "title": f'Script „{script_id}“ möglicherweise ungenutzt',
            "message": "Keine YAML-Referenz gefunden; Aufrufe aus Dashboards oder externen Integrationen sind weiterhin möglich.",
            "files": definitions[script_id],
        }
        for script_id in unused
    ]
    findings = [*conflicts["findings"], *unused_findings]
    errors = conflicts["counts"]["error"]
    warnings = conflicts["counts"]["warning"] + len(unused_findings)
    score = max(0, 100 - errors * 10 - warnings * 2)
    backups_root = DATA_ROOT / "backups"
    backup_count = sum(path.is_dir() for path in backups_root.iterdir()) if backups_root.exists() else 0
    remote = git_remote_status()
    return {
        "score": score,
        "summary": {
            "files": conflicts["fileCount"],
            "scripts": len(definitions),
            "unusedScripts": len(unused),
            "errors": errors,
            "warnings": warnings,
            "backups": backup_count,
        },
        "findings": findings[:200],
        "findingsTruncated": len(findings) > 200,
        "git": {
            "remote": remote,
            "recentCommits": recent_git_commits(),
        },
        "health": system_health(remote),
    }


def directory_usage(path: Path) -> dict[str, int]:
    files = 0
    size = 0
    if path.exists():
        for candidate in path.rglob("*"):
            if candidate.is_file():
                files += 1
                try:
                    size += candidate.stat().st_size
                except OSError:
                    pass
    return {"files": files, "size": size}


def system_health(remote: dict[str, Any] | None = None) -> dict[str, Any]:
    backups_root = DATA_ROOT / "backups"
    trash_root = DATA_ROOT / "trash"
    try:
        git_available = ensure_git_repository().get("available", False)
        git_message = "Git ist verfügbar."
    except GitOperationError as exc:
        git_available = False
        git_message = str(exc)
    remote_status = remote if remote is not None else git_remote_status()
    return {
        "settings": load_settings(),
        "paths": {
            "packages": str(PACKAGES_ROOT),
            "data": str(DATA_ROOT),
            "configuration": str(configuration_file()),
        },
        "git": {
            "available": git_available,
            "message": git_message,
            "remote": remote_status,
        },
        "homeAssistant": {
            "tokenConfigured": bool(os.environ.get("SUPERVISOR_TOKEN")),
            "lastCheck": last_configuration_check,
        },
        "storage": {
            "backups": {
                "directories": sum(path.is_dir() for path in backups_root.iterdir()) if backups_root.exists() else 0,
                **directory_usage(backups_root),
            },
            "trash": {
                "entries": trash_history()["count"],
                **directory_usage(trash_root),
            },
        },
    }


def export_packages(scope: str, raw_path: str = "", category: str = "") -> tuple[str, bytes]:
    metadata = load_metadata()
    selected: list[tuple[str, Path]] = []
    for item in list_files()["files"]:
        include = scope == "all"
        if scope == "file":
            include = item["path"] == raw_path
        elif scope == "category":
            include = item["category"] == category
        elif scope not in {"all", "file", "category"}:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Unbekannter Exportbereich.")
        if include:
            relative, absolute = normalize_relative_path(item["path"])
            selected.append((relative, absolute))
    if not selected:
        raise ApiError(HTTPStatus.NOT_FOUND, "Für diesen Export wurden keine Package-Dateien gefunden.")
    limits = import_limits()
    if len(selected) > limits["maxImportFiles"]:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Der Export enthält mehr als 500 Dateien.")
    if sum(path.stat().st_size for _relative, path in selected) > limits["maxExpandedImportSize"]:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Der Export ist größer als 50 MiB.")

    manifest = {
        "format": 1,
        "exportedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": {
            relative: file_metadata(metadata, relative)
            for relative, _absolute in selected
        },
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        for relative, absolute in selected:
            archive.writestr(f"packages/{relative}", absolute.read_bytes())
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return f"yaml-packages-{stamp}.zip", output.getvalue()


def decode_import_archive(encoded: Any) -> tuple[dict[str, str], dict[str, Any], list[str], str]:
    if not isinstance(encoded, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ein ZIP-Archiv ist erforderlich.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Das ZIP-Archiv ist nicht gültig kodiert.") from exc
    limits = import_limits()
    if len(raw) > limits["maxImportSize"]:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Das ZIP-Archiv ist größer als 10 MiB.")
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Die Datei ist kein gültiges ZIP-Archiv.")

    files: dict[str, str] = {}
    manifest: dict[str, Any] = {}
    errors: list[str] = []
    expanded_size = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if len(members) > limits["maxImportFiles"] + 1:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Das ZIP-Archiv enthält zu viele Dateien.")
        for member in members:
            expanded_size += member.file_size
            if expanded_size > limits["maxExpandedImportSize"]:
                raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Der entpackte ZIP-Inhalt ist größer als 50 MiB.")
            if member.flag_bits & 0x1:
                errors.append(f"{member.filename}: verschlüsselte ZIP-Einträge werden nicht unterstützt.")
                continue
            archive_path = member.filename.replace("\\", "/")
            if archive_path == "manifest.json":
                try:
                    candidate = json.loads(archive.read(member).decode("utf-8"))
                    manifest = candidate if isinstance(candidate, dict) else {}
                except (UnicodeDecodeError, json.JSONDecodeError):
                    errors.append("manifest.json ist ungültig.")
                continue
            relative_name = archive_path.removeprefix("packages/")
            try:
                relative, _absolute = normalize_relative_path(relative_name)
            except ApiError as exc:
                errors.append(f"{archive_path}: {exc.message}")
                continue
            if relative in files:
                errors.append(f"{relative}: im Archiv mehrfach vorhanden.")
                continue
            try:
                content = archive.read(member).decode("utf-8")
            except UnicodeDecodeError:
                errors.append(f"{relative}: Datei ist nicht UTF-8-kodiert.")
                continue
            validation = validate_yaml(content)
            if not validation["valid"]:
                errors.append(f"{relative}: {validation['message']}")
                continue
            files[relative] = content
    if not files and not errors:
        errors.append("Das Archiv enthält keine YAML-Package-Dateien.")
    return files, manifest, errors, hashlib.sha256(raw).hexdigest()


def import_destination_version(files: dict[str, str]) -> str:
    versions: list[str] = []
    package_paths = {item["path"] for item in list_files()["files"]}
    for relative in sorted(package_paths | set(files)):
        _normalized, absolute = normalize_relative_path(relative)
        current = file_version(absolute.read_bytes()) if absolute.is_file() else "missing"
        versions.append(f"{relative}\0{current}")
    return hashlib.sha256("\n".join(versions).encode("utf-8")).hexdigest()


def preview_package_import(encoded: Any) -> dict[str, Any]:
    files, _manifest, errors, archive_version = decode_import_archive(encoded)
    entries = []
    for relative, content in sorted(files.items()):
        _normalized, absolute = normalize_relative_path(relative)
        entries.append(
            {
                "path": relative,
                "size": len(content.encode("utf-8")),
                "exists": absolute.exists(),
                "action": "overwrite" if absolute.exists() else "create",
            }
        )
    conflicts = package_conflict_analysis(files) if files else {
        "mode": "unknown", "findings": [], "counts": {"error": 0, "warning": 0}, "fileCount": 0,
    }
    return {
        "valid": not errors,
        "archiveVersion": archive_version,
        "destinationVersion": import_destination_version(files),
        "files": entries,
        "errors": errors,
        "existingCount": sum(item["exists"] for item in entries),
        "conflicts": conflicts,
    }


def apply_package_import(
    encoded: Any,
    strategy: str,
    expected_archive_version: Any,
    expected_destination_version: Any,
) -> dict[str, Any]:
    if strategy not in {"skip", "overwrite"}:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Unbekannte Importstrategie.")
    files, manifest, errors, archive_version = decode_import_archive(encoded)
    if errors:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Das Archiv enthält ungültige Dateien.", {"details": errors})
    if archive_version != expected_archive_version:
        raise ApiError(HTTPStatus.CONFLICT, "Das ZIP-Archiv hat sich seit der Vorschau geändert.")
    if import_destination_version(files) != expected_destination_version:
        raise ApiError(HTTPStatus.CONFLICT, "Package-Dateien wurden seit der Importvorschau geändert.")

    selected: dict[str, str] = {}
    skipped: list[str] = []
    for relative, content in files.items():
        _normalized, absolute = normalize_relative_path(relative)
        if absolute.exists() and strategy == "skip":
            skipped.append(relative)
        else:
            selected[relative] = content
    if not selected:
        raise ApiError(HTTPStatus.CONFLICT, "Nach Anwendung der Importstrategie bleiben keine Dateien übrig.")

    paths = [normalize_relative_path(relative)[1] for relative in selected]
    originals: dict[Path, bytes | None] = {}
    with file_lock:
        git_checkpoint(paths)
        try:
            for relative, content in selected.items():
                _normalized, absolute = normalize_relative_path(relative)
                originals[absolute] = absolute.read_bytes() if absolute.exists() else None
                if absolute.exists():
                    create_backup(relative, absolute)
                atomic_write_path(
                    absolute,
                    content.encode("utf-8"),
                    absolute.stat().st_mode if absolute.exists() else 0o644,
                )
        except OSError as exc:
            for path, original in originals.items():
                if original is None:
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
                else:
                    atomic_write_path(path, original, path.stat().st_mode if path.exists() else 0o644)
            raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "Der Package-Import wurde zurückgerollt.") from exc
        git_result = git_commit_paths(paths, f"{len(selected)} Package-Dateien aus ZIP importiert")

    manifest_files = manifest.get("files", {}) if isinstance(manifest.get("files"), dict) else {}
    for relative in selected:
        attributes = manifest_files.get(relative, {})
        if isinstance(attributes, dict):
            update_file_metadata(
                relative,
                attributes.get("category", DEFAULT_CATEGORY),
                attributes.get("tags", []),
            )
    result = {
        "message": f"{len(selected)} Package-Dateien wurden importiert.",
        "imported": sorted(selected),
        "skipped": sorted(skipped),
        "git": git_result,
        "gitSync": auto_push_after_change(git_result),
        "configurationCheck": check_home_assistant_configuration(),
        "conflicts": package_conflict_analysis(),
    }
    return result


def home_assistant_request(path: str, method: str = "GET") -> Any:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "Home-Assistant-API ist lokal nicht verfuegbar.")
    request = urllib.request.Request(
        f"http://supervisor/core/api/{path.lstrip('/')}",
        data=b"{}" if method == "POST" else None,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = response.read()
            return json.loads(payload) if payload else {}
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ApiError(HTTPStatus.BAD_GATEWAY, "Home Assistant konnte nicht erreicht werden.") from exc


def check_home_assistant_configuration() -> dict[str, Any]:
    global last_configuration_check
    try:
        response = home_assistant_request("config/core/check_config", method="POST")
    except ApiError as exc:
        result = {
            "available": False,
            "valid": None,
            "status": "unavailable",
            "message": exc.message,
        }
        last_configuration_check = {**result, "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        return result
    valid = response.get("result") == "valid"
    errors = response.get("errors")
    message = "Home-Assistant-Konfiguration ist gültig." if valid else str(errors or "Home Assistant meldet eine ungültige Konfiguration.")
    result: dict[str, Any] = {
        "available": True,
        "valid": valid,
        "status": "valid" if valid else "invalid",
        "message": message,
        "errors": errors,
    }
    checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not valid:
        source_match = re.search(
            r"\[source\s+(?P<source>/config/[^:\]]+\.ya?ml):(?P<line>\d+)",
            message,
            re.IGNORECASE,
        ) or re.search(
            r"[\"'](?P<source>/config/[^\"']+\.ya?ml)[\"'].*?(?:line|Zeile)\s+(?P<line>\d+)",
            message,
            re.IGNORECASE | re.DOTALL,
        )
        if source_match:
            result["source"] = source_match.group("source")
            result["line"] = int(source_match.group("line"))
            last_configuration_check = {**result, "checkedAt": checked_at}
            return result
        line_match = re.search(r"(?:line|Zeile)\s+(\d+)", message, re.IGNORECASE)
        if line_match:
            result["line"] = int(line_match.group(1))
    last_configuration_check = {**result, "checkedAt": checked_at}
    return result


def helper_data() -> dict[str, Any]:
    states = home_assistant_request("states")
    services_data = home_assistant_request("services")
    entities = [
        {
            "entity_id": item.get("entity_id", ""),
            "name": item.get("attributes", {}).get("friendly_name", item.get("entity_id", "")),
            "state": item.get("state", ""),
        }
        for item in states
    ]
    services = [
        f"{domain.get('domain')}.{service}"
        for domain in services_data
        for service in domain.get("services", {})
    ]
    return {
        "entities": sorted(entities, key=lambda item: item["entity_id"]),
        "services": sorted(services),
    }


Handler = create_handler(sys.modules[__name__])


def main() -> None:
    global DATA_ROOT, GIT_REMOTE_FILE, METADATA_FILE, PACKAGES_ROOT, PORT, SETTINGS_FILE
    parser = argparse.ArgumentParser(description="Home Assistant YAML Script Manager")
    parser.add_argument("--port", type=int)
    parser.add_argument("--packages-path", type=Path)
    parser.add_argument("--data-path", type=Path)
    args = parser.parse_args()
    if args.port is not None:
        PORT = args.port
    if args.packages_path is not None:
        PACKAGES_ROOT = args.packages_path.resolve()
    if args.data_path is not None:
        DATA_ROOT = args.data_path.resolve()
        METADATA_FILE = DATA_ROOT / "metadata.json"
        GIT_REMOTE_FILE = DATA_ROOT / "git_remote.json"
        SETTINGS_FILE = DATA_ROOT / "settings.json"
    ensure_directories()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"YAML Script Manager listening on port {PORT}; packages={PACKAGES_ROOT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
