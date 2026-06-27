"""Home Assistant blueprint discovery, import, and package instantiation."""

from __future__ import annotations

import re
from http import HTTPStatus
from pathlib import Path
from typing import Any

import yaml

try:
    from .errors import ApiError
    from .validation import HomeAssistantLoader
except ImportError:  # pragma: no cover - direct execution in the app container
    from errors import ApiError
    from validation import HomeAssistantLoader


BLUEPRINT_DOMAINS = {"automation", "script", "scene"}


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9_]+", "_", value.casefold()).strip("_")
    return result or "blueprint"


def _config_root(backend: Any) -> Path:
    return backend.PACKAGES_ROOT.resolve().parent


def _blueprint_root(backend: Any) -> Path:
    return _config_root(backend) / "blueprints"


def normalize_blueprint_path(backend: Any, raw_path: Any) -> tuple[str, Path, str]:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ein Blueprint-Pfad ist erforderlich.")
    normalized = raw_path.strip().replace("\\", "/").lstrip("/")
    if not normalized.startswith("blueprints/"):
        normalized = f"blueprints/{normalized}"
    relative = Path(normalized)
    if relative.suffix.lower() not in backend.VALID_SUFFIXES:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Blueprints müssen YAML-Dateien sein.")
    if len(relative.parts) < 4 or relative.parts[0] != "blueprints":
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "Blueprint-Pfade verwenden blueprints/<domain>/<ordner>/<datei>.yaml.",
        )
    domain = relative.parts[1]
    if domain not in BLUEPRINT_DOMAINS:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Unbekannte Blueprint-Domain.")
    if any(part in {"", ".", ".."} or part.startswith(".") for part in relative.parts):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der Blueprint-Pfad ist ungültig.")
    root = _config_root(backend)
    absolute = (root / relative).resolve()
    try:
        absolute.relative_to(root)
    except ValueError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der Blueprint-Pfad liegt außerhalb der Konfiguration.") from exc
    return relative.as_posix(), absolute, domain


def _load_yaml_mapping(content: str) -> dict[str, Any]:
    try:
        document = yaml.load(content, Loader=HomeAssistantLoader)
    except yaml.YAMLError as exc:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc).split("\n", 1)[0]) from exc
    if not isinstance(document, dict):
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Blueprint-YAML muss ein Objekt enthalten.")
    return document


def _blueprint_meta(content: str, path: str = "") -> dict[str, Any]:
    document = _load_yaml_mapping(content)
    blueprint = document.get("blueprint")
    if not isinstance(blueprint, dict):
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Der Block blueprint: fehlt.")
    domain = str(blueprint.get("domain") or "").strip()
    if domain not in BLUEPRINT_DOMAINS:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Blueprint-Domain muss automation, script oder scene sein.")
    inputs = blueprint.get("input", {})
    if not isinstance(inputs, dict):
        inputs = {}
    items = []
    for name, details in sorted(inputs.items(), key=lambda item: str(item[0]).casefold()):
        label = str(name)
        description = ""
        default = ""
        if isinstance(details, dict):
            label = str(details.get("name") or name)
            description = str(details.get("description") or "")
            if "default" in details:
                default = details["default"]
        items.append(
            {
                "name": str(name),
                "label": label,
                "description": description,
                "default": default,
            }
        )
    name = str(blueprint.get("name") or Path(path).stem or "Blueprint")
    return {
        "name": name,
        "description": str(blueprint.get("description") or ""),
        "domain": domain,
        "inputs": items,
        "inputCount": len(items),
    }


def _public_blueprint(backend: Any, relative: str, absolute: Path) -> dict[str, Any]:
    content = backend.read_yaml_text(absolute)
    meta = _blueprint_meta(content, relative)
    domain_root = _blueprint_root(backend) / meta["domain"]
    try:
        use_path = absolute.relative_to(domain_root).as_posix()
    except ValueError:
        use_path = Path(relative).name
    return {
        **meta,
        "path": relative,
        "usePath": use_path,
        "size": absolute.stat().st_size,
        "modified": absolute.stat().st_mtime,
    }


def list_blueprints(backend: Any) -> dict[str, Any]:
    root = _blueprint_root(backend)
    blueprints: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    for domain in sorted(BLUEPRINT_DOMAINS):
        directory = root / domain
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in backend.VALID_SUFFIXES:
                continue
            if path.stat().st_size > backend.MAX_FILE_SIZE:
                invalid.append({"path": path.relative_to(_config_root(backend)).as_posix(), "message": "Datei ist zu groß."})
                continue
            relative = path.relative_to(_config_root(backend)).as_posix()
            try:
                blueprints.append(_public_blueprint(backend, relative, path))
            except (ApiError, OSError, UnicodeDecodeError) as exc:
                message = exc.message if isinstance(exc, ApiError) else str(exc)
                invalid.append({"path": relative, "message": message})
    summary = {domain: sum(item["domain"] == domain for item in blueprints) for domain in BLUEPRINT_DOMAINS}
    return {
        "blueprints": sorted(blueprints, key=lambda item: (item["domain"], item["name"].casefold())),
        "invalidFiles": invalid,
        "summary": {**summary, "total": len(blueprints), "invalid": len(invalid)},
    }


def read_blueprint(backend: Any, raw_path: Any) -> dict[str, Any]:
    relative, absolute, _domain = normalize_blueprint_path(backend, raw_path)
    if not absolute.is_file():
        raise ApiError(HTTPStatus.NOT_FOUND, "Der Blueprint wurde nicht gefunden.")
    content = absolute.read_bytes()
    if len(content) > backend.MAX_FILE_SIZE:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Der Blueprint ist zu groß.")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Der Blueprint ist nicht UTF-8-kodiert.") from exc
    return {
        **_public_blueprint(backend, relative, absolute),
        "content": text,
        "version": backend.file_version(content),
    }


def _write_blueprint(backend: Any, relative: str, absolute: Path, content: str, message: str) -> dict[str, Any]:
    validation = backend.validate_yaml(content)
    if not validation["valid"]:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Blueprint-YAML ist ungültig.", validation)
    _blueprint_meta(content, relative)
    if absolute.exists():
        raise ApiError(HTTPStatus.CONFLICT, "An diesem Blueprint-Pfad existiert bereits eine Datei.")
    with backend.file_lock:
        backend.git_checkpoint([absolute])
        absolute.parent.mkdir(parents=True, exist_ok=True)
        backend.atomic_write_path(absolute, content.encode("utf-8"), 0o644)
        git_result = backend.git_commit_paths([absolute], message)
    result = read_blueprint(backend, relative)
    result["git"] = git_result
    result["gitSync"] = backend.auto_push_after_change(git_result)
    return result


def import_blueprint(backend: Any, raw_path: Any, content: Any) -> dict[str, Any]:
    if not isinstance(content, str) or not content.strip():
        raise ApiError(HTTPStatus.BAD_REQUEST, "Blueprint-YAML ist erforderlich.")
    relative, absolute, _domain = normalize_blueprint_path(backend, raw_path)
    return _write_blueprint(
        backend,
        relative,
        absolute,
        content.rstrip() + "\n",
        f"Blueprint importiert: {relative}",
    )


def _first_domain_body(document: dict[str, Any], domain: str) -> dict[str, Any]:
    candidate = document.get(domain)
    if domain == "script" and isinstance(candidate, dict) and candidate:
        first = next(iter(candidate.values()))
        return first if isinstance(first, dict) else {}
    if domain in {"automation", "scene"}:
        if isinstance(candidate, list) and candidate and isinstance(candidate[0], dict):
            return candidate[0]
        if isinstance(candidate, dict) and candidate:
            first = next(iter(candidate.values()))
            return first if isinstance(first, dict) else candidate
    return document if isinstance(document, dict) else {}


def create_blueprint_from_yaml(
    backend: Any,
    domain: Any,
    name: Any,
    content: Any,
    raw_path: Any = "",
) -> dict[str, Any]:
    if domain not in BLUEPRINT_DOMAINS:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Unbekannte Blueprint-Domain.")
    if not isinstance(name, str) or not name.strip():
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ein Blueprint-Name ist erforderlich.")
    if not isinstance(content, str) or not content.strip():
        raise ApiError(HTTPStatus.BAD_REQUEST, "YAML-Inhalt ist erforderlich.")
    document = _load_yaml_mapping(content)
    body = dict(_first_domain_body(document, domain))
    if not body:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Aus diesem YAML konnte kein Blueprint-Körper abgeleitet werden.")
    for removable in ("id", "alias", "name"):
        body.pop(removable, None)
    blueprint_document = {
        "blueprint": {
            "name": name.strip(),
            "description": "Aus HA Maintenance Hub erzeugt.",
            "domain": domain,
            "input": {},
        },
        **body,
    }
    output = yaml.safe_dump(blueprint_document, sort_keys=False, allow_unicode=True)
    path = raw_path if isinstance(raw_path, str) and raw_path.strip() else f"blueprints/{domain}/local/{_slug(name)}.yaml"
    relative, absolute, _domain = normalize_blueprint_path(backend, path)
    return _write_blueprint(
        backend,
        relative,
        absolute,
        output,
        f"Blueprint aus YAML erzeugt: {relative}",
    )


def _parse_inputs(raw_inputs: Any, raw_text: Any) -> dict[str, Any]:
    if isinstance(raw_inputs, dict):
        return raw_inputs
    if not isinstance(raw_text, str) or not raw_text.strip():
        return {}
    try:
        parsed = yaml.load(raw_text, Loader=HomeAssistantLoader)
    except yaml.YAMLError as exc:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Blueprint-Eingaben enthalten ungültiges YAML.") from exc
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Blueprint-Eingaben müssen ein YAML-Objekt sein.")
    return parsed


def instantiate_blueprint(
    backend: Any,
    raw_blueprint_path: Any,
    raw_package_path: Any,
    object_id: Any,
    alias: Any = "",
    inputs: Any = None,
    inputs_text: Any = "",
) -> dict[str, Any]:
    blueprint = read_blueprint(backend, raw_blueprint_path)
    domain = blueprint["domain"]
    if domain not in {"automation", "script"}:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Instanziierung wird für Automation- und Script-Blueprints unterstützt.")
    if not isinstance(object_id, str) or not re.fullmatch(r"[a-z0-9_]+", object_id.strip()):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Objekt-ID darf nur Kleinbuchstaben, Ziffern und Unterstriche enthalten.")
    instance_alias = alias.strip() if isinstance(alias, str) and alias.strip() else object_id.strip()
    use_blueprint = {"path": blueprint["usePath"]}
    parsed_inputs = _parse_inputs(inputs, inputs_text)
    if parsed_inputs:
        use_blueprint["input"] = parsed_inputs
    if domain == "script":
        document = {
            "script": {
                object_id.strip(): {
                    "alias": instance_alias,
                    "use_blueprint": use_blueprint,
                }
            }
        }
    else:
        document = {
            "automation": [
                {
                    "id": object_id.strip(),
                    "alias": instance_alias,
                    "use_blueprint": use_blueprint,
                }
            ]
        }
    content = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    result = backend.write_file(
        raw_package_path,
        content,
        None,
        "Blueprints",
        create=True,
        tags=["blueprint"],
    )
    result["blueprint"] = blueprint
    result["message"] = f"{domain.capitalize()} aus Blueprint erstellt: {result['path']}"
    return result
