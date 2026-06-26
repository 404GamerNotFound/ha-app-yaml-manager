"""Masked secrets.yaml management and plaintext-to-secret conversion."""

from __future__ import annotations

import re
from http import HTTPStatus
from pathlib import Path
from typing import Any

import yaml

try:
    from .errors import ApiError
    from .resources import _safe_config_path
    from .validation import HomeAssistantLoader
except ImportError:  # pragma: no cover - direct execution in the app container
    from errors import ApiError
    from resources import _safe_config_path
    from validation import HomeAssistantLoader


SECRET_NAME = re.compile(r"^[A-Za-z0-9_]+$")
MASK = "••••••••"


def _path(backend: Any) -> Path:
    return backend.PACKAGES_ROOT.resolve().parent / "secrets.yaml"


def _load(backend: Any) -> dict[str, Any]:
    path = _path(backend)
    if not path.exists():
        return {}
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=HomeAssistantLoader)
    except yaml.YAMLError as exc:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "secrets.yaml ist ungültig.") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "secrets.yaml muss ein YAML-Objekt sein.")
    return {str(key): value for key, value in data.items()}


def _dump(data: dict[str, Any]) -> bytes:
    text = yaml.safe_dump(
        dict(sorted(data.items(), key=lambda item: item[0].casefold())),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    return text.encode("utf-8")


def _write(backend: Any, data: dict[str, Any], message: str) -> dict[str, Any]:
    path = _path(backend)
    path.parent.mkdir(parents=True, exist_ok=True)
    paths = [path]
    with backend.file_lock:
        if path.exists():
            backend.create_backup("secrets/secrets.yaml", path)
            mode = path.stat().st_mode
        else:
            mode = 0o600
        backend.git_checkpoint(paths)
        backend.atomic_write_path(path, _dump(data), mode)
        git_result = backend.git_commit_paths(paths, message)
    return {
        "git": git_result,
        "gitSync": backend.auto_push_after_change(git_result),
    }


def secrets_overview(backend: Any) -> dict[str, Any]:
    data = _load(backend)
    scan = backend.security_scan()
    referenced = {item["name"] for item in scan.get("references", []) if item.get("name")}
    return {
        "path": str(_path(backend)),
        "exists": _path(backend).exists(),
        "count": len(data),
        "items": [
            {
                "name": name,
                "masked": MASK,
                "referenced": name in referenced,
                "referenceCount": sum(item.get("name") == name for item in scan.get("references", [])),
            }
            for name in sorted(data, key=str.casefold)
        ],
        "findings": scan.get("findings", []),
        "summary": scan.get("summary", {}),
    }


def upsert_secret(backend: Any, body: dict[str, Any]) -> dict[str, Any]:
    name = body.get("name")
    value = body.get("value")
    if not isinstance(name, str) or not SECRET_NAME.fullmatch(name):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der Secret-Name ist ungültig.")
    if not isinstance(value, str) or not value:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ein Secret-Wert ist erforderlich.")
    data = _load(backend)
    existed = name in data
    data[name] = value
    result = _write(backend, data, f"Secret {'aktualisiert' if existed else 'angelegt'}: {name}")
    return {
        **secrets_overview(backend),
        **result,
        "message": f"Secret {name} wurde {'aktualisiert' if existed else 'angelegt'}.",
    }


def delete_secret(backend: Any, raw_name: Any) -> dict[str, Any]:
    if not isinstance(raw_name, str) or not SECRET_NAME.fullmatch(raw_name):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der Secret-Name ist ungültig.")
    data = _load(backend)
    if raw_name not in data:
        raise ApiError(HTTPStatus.NOT_FOUND, "Secret wurde nicht gefunden.")
    data.pop(raw_name)
    result = _write(backend, data, f"Secret entfernt: {raw_name}")
    return {**secrets_overview(backend), **result, "message": f"Secret {raw_name} wurde entfernt."}


def convert_plaintext_secret(backend: Any, body: dict[str, Any]) -> dict[str, Any]:
    raw_path = body.get("path")
    line = body.get("line")
    key = body.get("key")
    name = body.get("name")
    value = body.get("value")
    if not isinstance(raw_path, str) or not isinstance(line, int) or line < 1:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Pfad und Zeile sind erforderlich.")
    if not isinstance(key, str) or not key:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der YAML-Schlüssel ist erforderlich.")
    if not isinstance(name, str) or not SECRET_NAME.fullmatch(name):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der Secret-Name ist ungültig.")
    if not isinstance(value, str) or not value:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der Secret-Wert ist erforderlich.")
    relative, path = _safe_config_path(backend, raw_path)
    content = backend.read_yaml_text(path)
    lines = content.splitlines()
    if line > len(lines):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die angegebene Zeile existiert nicht.")
    pattern = re.compile(rf"^(\s*{re.escape(key)}\s*:\s*)(.*?)(\s*(?:#.*)?)$")
    match = pattern.match(lines[line - 1])
    if not match:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Die Zeile passt nicht zum angegebenen YAML-Schlüssel.")
    lines[line - 1] = f"{match.group(1)}!secret {name}{match.group(3)}"
    updated = "\n".join(lines) + ("\n" if content.endswith("\n") else "")
    validation = backend.validate_yaml(updated)
    if not validation["valid"]:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Die Umwandlung würde ungültiges YAML erzeugen.", validation)
    data = _load(backend)
    data[name] = value
    secrets_path = _path(backend)
    paths = [path, secrets_path]
    with backend.file_lock:
        originals = {candidate: candidate.read_bytes() for candidate in paths if candidate.exists()}
        modes = {path: path.stat().st_mode, secrets_path: secrets_path.stat().st_mode if secrets_path.exists() else 0o600}
        backend.git_checkpoint(paths)
        if path.exists():
            backend.create_backup(
                "configuration/configuration.yaml" if relative == "configuration.yaml"
                else relative.removeprefix("packages/") if relative.startswith("packages/")
                else f"resources/{relative}",
                path,
            )
        if secrets_path.exists():
            backend.create_backup("secrets/secrets.yaml", secrets_path)
        try:
            backend.atomic_write_path(path, updated.encode("utf-8"), modes[path])
            secrets_path.parent.mkdir(parents=True, exist_ok=True)
            backend.atomic_write_path(secrets_path, _dump(data), modes[secrets_path])
        except OSError as exc:
            for candidate, original in originals.items():
                backend.atomic_write_path(candidate, original, modes.get(candidate, 0o600))
            raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "Die Secret-Umwandlung wurde zurückgerollt.") from exc
        git_result = backend.git_commit_paths(paths, f"Klartextwert in !secret umgewandelt: {name}")
    return {
        **secrets_overview(backend),
        "message": f"{relative}:{line} verwendet jetzt !secret {name}.",
        "git": git_result,
        "gitSync": backend.auto_push_after_change(git_result),
        "configurationCheck": backend.check_home_assistant_configuration(),
    }
