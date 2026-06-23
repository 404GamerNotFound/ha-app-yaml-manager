"""User-configurable application settings."""

from __future__ import annotations

import json
import os
import tempfile
from http import HTTPStatus
from typing import Any

try:
    from .errors import ApiError
except ImportError:  # pragma: no cover - direct execution in the app container
    from errors import ApiError


DEFAULT_SETTINGS: dict[str, Any] = {
    "backupRetention": 30,
    "trashRetentionDays": 30,
    "trashMaxSizeMiB": 100,
    "maxImportFiles": 500,
    "maxImportSizeMiB": 10,
    "maxExpandedImportSizeMiB": 50,
    "showUnusedScripts": True,
    "defaultBranchPrefix": "feature/",
    "theme": "system",
    "afterSave": "stay",
}


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, minimum), maximum)


def sanitize_settings(raw: Any) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    prefix = source.get("defaultBranchPrefix", DEFAULT_SETTINGS["defaultBranchPrefix"])
    if not isinstance(prefix, str):
        prefix = DEFAULT_SETTINGS["defaultBranchPrefix"]
    prefix = prefix.strip().replace("\\", "/")[:48]
    if prefix and not all(char.isalnum() or char in "._/-" for char in prefix):
        prefix = DEFAULT_SETTINGS["defaultBranchPrefix"]

    theme = source.get("theme", DEFAULT_SETTINGS["theme"])
    if theme not in {"system", "light", "dark"}:
        theme = DEFAULT_SETTINGS["theme"]

    after_save = source.get("afterSave", DEFAULT_SETTINGS["afterSave"])
    if after_save not in {"stay", "dashboard"}:
        after_save = DEFAULT_SETTINGS["afterSave"]

    return {
        "backupRetention": _bounded_int(
            source.get("backupRetention"),
            DEFAULT_SETTINGS["backupRetention"],
            5,
            500,
        ),
        "maxImportFiles": _bounded_int(
            source.get("maxImportFiles"),
            DEFAULT_SETTINGS["maxImportFiles"],
            1,
            2000,
        ),
        "maxImportSizeMiB": _bounded_int(
            source.get("maxImportSizeMiB"),
            DEFAULT_SETTINGS["maxImportSizeMiB"],
            1,
            100,
        ),
        "maxExpandedImportSizeMiB": _bounded_int(
            source.get("maxExpandedImportSizeMiB"),
            DEFAULT_SETTINGS["maxExpandedImportSizeMiB"],
            1,
            500,
        ),
        "trashRetentionDays": _bounded_int(
            source.get("trashRetentionDays"),
            DEFAULT_SETTINGS["trashRetentionDays"],
            0,
            3650,
        ),
        "trashMaxSizeMiB": _bounded_int(
            source.get("trashMaxSizeMiB"),
            DEFAULT_SETTINGS["trashMaxSizeMiB"],
            0,
            10240,
        ),
        "showUnusedScripts": bool(source.get("showUnusedScripts", True)),
        "defaultBranchPrefix": prefix,
        "theme": theme,
        "afterSave": after_save,
    }


def load_settings(backend: Any) -> dict[str, Any]:
    try:
        raw = json.loads(backend.SETTINGS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        raw = {}
    return sanitize_settings({**DEFAULT_SETTINGS, **(raw if isinstance(raw, dict) else {})})


def save_settings(backend: Any, settings: dict[str, Any]) -> None:
    backend.DATA_ROOT.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix="settings-",
        suffix=".json",
        dir=backend.DATA_ROOT,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(settings, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, backend.SETTINGS_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def update_settings(backend: Any, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ein Einstellungsobjekt wird erwartet.")
    settings = sanitize_settings({**load_settings(backend), **raw})
    if settings["maxExpandedImportSizeMiB"] < settings["maxImportSizeMiB"]:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "Das entpackte Importlimit muss mindestens so groß wie das ZIP-Limit sein.",
        )
    save_settings(backend, settings)
    return settings
