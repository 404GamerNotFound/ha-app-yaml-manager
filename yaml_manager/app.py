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
    return {
        "path": relative,
        "content": text,
        "version": file_version(content),
        "category": metadata["files"].get(relative, DEFAULT_CATEGORY),
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


def update_category(relative: str, category: str) -> None:
    clean = category.strip() if isinstance(category, str) else DEFAULT_CATEGORY
    clean = clean[:80] or DEFAULT_CATEGORY
    with metadata_lock:
        metadata = load_metadata()
        metadata["files"][relative] = clean
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


def write_file(raw_path: str, content: str, expected_version: str | None, category: str, create: bool) -> dict[str, Any]:
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

    update_category(relative, category)
    return read_file(relative)


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
            files.append(
                {
                    "path": relative,
                    "name": path.stem,
                    "category": metadata["files"].get(relative, DEFAULT_CATEGORY),
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                }
            )
    used = {item["category"] for item in files}
    categories = sorted(
        {DEFAULT_CATEGORY, *metadata["categories"], *used},
        key=lambda value: (value == DEFAULT_CATEGORY, value.casefold()),
    )
    return {
        "files": files,
        "categories": categories,
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
    server_version = "YamlScriptManager/0.1"

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
                )
                self.send_json(HTTPStatus.CREATED, result)
            elif path == "/api/validate":
                self.send_json(HTTPStatus.OK, validate_yaml(body.get("content", "")))
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
