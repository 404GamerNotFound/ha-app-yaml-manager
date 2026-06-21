"""HTTP backend for the Home Assistant YAML Script Manager."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml


PORT = int(os.environ.get("PORT", "8099"))
PACKAGES_ROOT = Path(os.environ.get("PACKAGES_PATH", "/homeassistant/packages")).resolve()
DATA_ROOT = Path(os.environ.get("DATA_PATH", "/data")).resolve()
STATIC_ROOT = Path(__file__).parent / "static"
METADATA_FILE = DATA_ROOT / "metadata.json"
MAX_FILE_SIZE = 2 * 1024 * 1024
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


class ApiError(Exception):
    def __init__(self, status: int, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details or {}


class HomeAssistantLoader(yaml.SafeLoader):
    """Safe YAML loader that accepts Home Assistant's custom tags."""


def _construct_mapping(loader: HomeAssistantLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            if key in result:
                raise yaml.MarkedYAMLError(
                    context="Doppelter YAML-Schluessel",
                    context_mark=key_node.start_mark,
                    problem=str(key),
                    problem_mark=key_node.start_mark,
                )
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found unhashable key",
                key_node.start_mark,
            ) from exc
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


def _construct_unknown(loader: HomeAssistantLoader, _suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


HomeAssistantLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)
HomeAssistantLoader.add_multi_constructor("!", _construct_unknown)


def ensure_directories() -> None:
    PACKAGES_ROOT.mkdir(parents=True, exist_ok=True)
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    (DATA_ROOT / "backups").mkdir(exist_ok=True)
    (DATA_ROOT / "trash").mkdir(exist_ok=True)


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def load_metadata() -> dict[str, Any]:
    with metadata_lock:
        try:
            data = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            data = {}
        return {
            "categories": list(data.get("categories", [])),
            "files": dict(data.get("files", {})),
        }


def file_metadata(metadata: dict[str, Any], relative: str) -> dict[str, Any]:
    value = metadata.get("files", {}).get(relative, DEFAULT_CATEGORY)
    if isinstance(value, str):
        return {"category": value or DEFAULT_CATEGORY, "tags": []}
    if not isinstance(value, dict):
        return {"category": DEFAULT_CATEGORY, "tags": []}
    category = value.get("category", DEFAULT_CATEGORY)
    tags = value.get("tags", [])
    return {
        "category": category if isinstance(category, str) and category else DEFAULT_CATEGORY,
        "tags": sanitize_tags(tags),
    }


def sanitize_tags(tags: Any) -> list[str]:
    if not isinstance(tags, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in tags:
        if not isinstance(value, str):
            continue
        tag = re.sub(r"\s+", " ", value).strip()[:40]
        folded = tag.casefold()
        if tag and folded not in seen:
            cleaned.append(tag)
            seen.add(folded)
        if len(cleaned) == 12:
            break
    return cleaned


def save_metadata(metadata: dict[str, Any]) -> None:
    with metadata_lock:
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="metadata-", suffix=".json", dir=DATA_ROOT)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(metadata, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, METADATA_FILE)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


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


def configuration_file() -> Path:
    override = os.environ.get("CONFIGURATION_PATH")
    if override:
        return Path(override).resolve()
    return PACKAGES_ROOT.resolve().parent / "configuration.yaml"


def mapping_value(node: yaml.Node | None, key: str) -> yaml.Node | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    for key_node, value_node in node.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            return value_node
    return None


def compose_yaml(path: Path) -> yaml.Node | None:
    if path.stat().st_size > MAX_FILE_SIZE:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Die Konfigurationsdatei ist groesser als 2 MiB.")
    return yaml.compose(path.read_text(encoding="utf-8"), Loader=HomeAssistantLoader)


def resolve_include(value: str, base_directory: Path) -> Path:
    return (base_directory / value.strip()).resolve()


def package_node_uses_directory(
    node: yaml.Node | None,
    base_directory: Path,
    expected_directory: Path,
    visited: set[Path],
) -> bool:
    if not isinstance(node, yaml.ScalarNode):
        return False
    target = resolve_include(node.value, base_directory)
    if node.tag in PACKAGE_DIRECTORY_TAGS:
        return target == expected_directory
    if node.tag != "!include" or target in visited or not target.is_file():
        return False
    visited.add(target)
    return package_node_uses_directory(compose_yaml(target), target.parent, expected_directory, visited)


def homeassistant_node_uses_packages(
    node: yaml.Node | None,
    base_directory: Path,
    expected_directory: Path,
    visited: set[Path],
) -> bool:
    packages_node = mapping_value(node, "packages")
    if packages_node is not None:
        return package_node_uses_directory(packages_node, base_directory, expected_directory, visited)

    if not isinstance(node, yaml.ScalarNode):
        return False
    target = resolve_include(node.value, base_directory)
    if node.tag == "!include" and target not in visited and target.is_file():
        visited.add(target)
        return homeassistant_node_uses_packages(
            compose_yaml(target), target.parent, expected_directory, visited
        )
    if node.tag in DIRECTORY_INCLUDE_TAGS and target.is_dir():
        for candidate in sorted(target.iterdir()):
            if candidate.suffix.lower() not in VALID_SUFFIXES or not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if resolved in visited:
                continue
            visited.add(resolved)
            if homeassistant_node_uses_packages(
                compose_yaml(resolved), resolved.parent, expected_directory, visited
            ):
                return True
    return False


def package_configuration_status() -> dict[str, Any]:
    path = configuration_file()
    expected_directory = PACKAGES_ROOT.resolve()
    expected = "homeassistant:\n  packages: !include_dir_named packages"
    result: dict[str, Any] = {
        "configured": False,
        "status": "missing",
        "configuration": str(path),
        "expected": expected,
    }
    if not path.is_file():
        result["status"] = "unavailable"
        result["message"] = "configuration.yaml wurde nicht gefunden."
        return result
    try:
        root = compose_yaml(path)
        homeassistant = mapping_value(root, "homeassistant")
        if homeassistant_node_uses_packages(homeassistant, path.parent, expected_directory, {path}):
            result.update(
                {
                    "configured": True,
                    "status": "configured",
                    "message": "Der Ordner /config/packages ist in configuration.yaml eingebunden.",
                }
            )
        else:
            result["message"] = "Der Ordner /config/packages ist nicht über homeassistant.packages eingebunden."
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ApiError) as exc:
        result["status"] = "invalid"
        result["message"] = f"configuration.yaml konnte nicht geprüft werden: {exc}"
    return result


def file_version(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


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
    if not isinstance(content, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der YAML-Inhalt fehlt.")
    if len(content.encode("utf-8")) > MAX_FILE_SIZE:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Der Inhalt ist groesser als 2 MiB.")
    try:
        documents = list(yaml.load_all(content, Loader=HomeAssistantLoader))
        return {"valid": True, "documents": len(documents), "message": "YAML ist syntaktisch gueltig."}
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
        problem = getattr(exc, "problem", None) or str(exc).split("\n", 1)[0]
        result: dict[str, Any] = {"valid": False, "message": str(problem)}
        if mark is not None:
            result.update({"line": mark.line + 1, "column": mark.column + 1})
        return result


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
            text = path.read_text(encoding="utf-8")
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
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000:06d}"
    destination = DATA_ROOT / "backups" / stamp / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    backups = sorted((DATA_ROOT / "backups").iterdir(), key=lambda item: item.name, reverse=True)
    for old in backups[30:]:
        shutil.rmtree(old, ignore_errors=True)


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

    update_file_metadata(relative, category, tags)
    return read_file(relative)


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
        create_backup(relative, source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)

    with metadata_lock:
        metadata = load_metadata()
        attributes = file_metadata(metadata, relative)
        metadata["files"].pop(relative, None)
        metadata["files"][new_relative] = attributes
        save_metadata(metadata)
    return read_file(new_relative)


def delete_file(raw_path: str, expected_version: str | None) -> None:
    relative, absolute = normalize_relative_path(raw_path)
    if not isinstance(expected_version, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Dateiversion fehlt. Bitte die Datei neu laden.")
    with file_lock:
        if not absolute.exists():
            raise ApiError(HTTPStatus.NOT_FOUND, "Die Datei wurde nicht gefunden.")
        current = absolute.read_bytes()
        if expected_version and file_version(current) != expected_version:
            raise ApiError(HTTPStatus.CONFLICT, "Die Datei wurde zwischenzeitlich geaendert. Bitte neu laden.")
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000:06d}"
        destination = DATA_ROOT / "trash" / stamp / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(absolute), destination)
    with metadata_lock:
        metadata = load_metadata()
        metadata["files"].pop(relative, None)
        save_metadata(metadata)


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


class Handler(BaseHTTPRequestHandler):
    server_version = "YamlScriptManager/0.3"

    def log_message(self, format_string: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format_string % args}", flush=True)

    def send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, value: Any) -> None:
        self.send_bytes(status, json_bytes(value), "application/json; charset=utf-8")

    def read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Ungueltige Anfragegroesse.") from exc
        if length > MAX_FILE_SIZE + 16_384:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Die Anfrage ist zu gross.")
        try:
            value = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Ungueltiges JSON.") from exc
        if not isinstance(value, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Ein JSON-Objekt wird erwartet.")
        return value

    def route(self) -> tuple[str, dict[str, list[str]]]:
        parsed = urllib.parse.urlsplit(self.path)
        return parsed.path.rstrip("/") or "/", urllib.parse.parse_qs(parsed.query)

    def do_GET(self) -> None:  # noqa: N802
        try:
            path, query = self.route()
            if path == "/health":
                self.send_json(HTTPStatus.OK, {"status": "ok"})
            elif path == "/api/files":
                self.send_json(HTTPStatus.OK, list_files())
            elif path == "/api/file":
                self.send_json(HTTPStatus.OK, read_file(query.get("path", [""])[0]))
            elif path == "/api/helpers":
                self.send_json(HTTPStatus.OK, helper_data())
            elif path.startswith("/static/"):
                self.serve_static(path.removeprefix("/static/"))
            elif path == "/":
                self.serve_index()
            else:
                raise ApiError(HTTPStatus.NOT_FOUND, "Unbekannter Endpunkt.")
        except ApiError as exc:
            self.send_json(exc.status, {"error": exc.message, **exc.details})
        except Exception as exc:  # pragma: no cover - final request boundary
            print(f"Unhandled error: {exc!r}", flush=True)
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Interner Serverfehler."})

    def do_POST(self) -> None:  # noqa: N802
        try:
            path, _ = self.route()
            body = self.read_json()
            if path == "/api/files":
                result = write_file(
                    body.get("path", ""),
                    body.get("content", ""),
                    None,
                    body.get("category", DEFAULT_CATEGORY),
                    create=True,
                    tags=body.get("tags"),
                )
                self.send_json(HTTPStatus.CREATED, result)
            elif path == "/api/rename":
                result = rename_file(
                    body.get("path", ""),
                    body.get("newPath", ""),
                    body.get("version"),
                )
                self.send_json(HTTPStatus.OK, result)
            elif path == "/api/validate":
                self.send_json(HTTPStatus.OK, validate_yaml(body.get("content", "")))
            elif path == "/api/analyze":
                self.send_json(
                    HTTPStatus.OK,
                    analyze_yaml(body.get("content", ""), body.get("path", "")),
                )
            elif path == "/api/reload":
                home_assistant_request("services/script/reload", method="POST")
                self.send_json(HTTPStatus.OK, {"message": "Skripte wurden neu geladen."})
            else:
                raise ApiError(HTTPStatus.NOT_FOUND, "Unbekannter Endpunkt.")
        except ApiError as exc:
            self.send_json(exc.status, {"error": exc.message, **exc.details})

    def do_PUT(self) -> None:  # noqa: N802
        try:
            path, _ = self.route()
            if path != "/api/file":
                raise ApiError(HTTPStatus.NOT_FOUND, "Unbekannter Endpunkt.")
            body = self.read_json()
            result = write_file(
                body.get("path", ""),
                body.get("content", ""),
                body.get("version"),
                body.get("category", DEFAULT_CATEGORY),
                create=False,
                tags=body.get("tags"),
            )
            self.send_json(HTTPStatus.OK, result)
        except ApiError as exc:
            self.send_json(exc.status, {"error": exc.message, **exc.details})

    def do_DELETE(self) -> None:  # noqa: N802
        try:
            path, _ = self.route()
            if path != "/api/file":
                raise ApiError(HTTPStatus.NOT_FOUND, "Unbekannter Endpunkt.")
            body = self.read_json()
            delete_file(body.get("path", ""), body.get("version"))
            self.send_json(HTTPStatus.OK, {"message": "Datei wurde in den Papierkorb verschoben."})
        except ApiError as exc:
            self.send_json(exc.status, {"error": exc.message, **exc.details})

    def serve_index(self) -> None:
        template = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        ingress = self.headers.get("X-Ingress-Path", "").rstrip("/")
        if not ingress.startswith("/") or not re.fullmatch(r"/[A-Za-z0-9_./-]*", ingress):
            ingress = ""
        html = template.replace("__BASE_PATH__", f"{ingress}/")
        self.send_bytes(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")

    def serve_static(self, raw_name: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", raw_name):
            raise ApiError(HTTPStatus.NOT_FOUND, "Datei nicht gefunden.")
        path = STATIC_ROOT / raw_name
        try:
            body = path.read_bytes()
        except FileNotFoundError as exc:
            raise ApiError(HTTPStatus.NOT_FOUND, "Datei nicht gefunden.") from exc
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_bytes(HTTPStatus.OK, body, f"{content_type}; charset=utf-8")


def main() -> None:
    ensure_directories()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"YAML Script Manager listening on port {PORT}; packages={PACKAGES_ROOT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
