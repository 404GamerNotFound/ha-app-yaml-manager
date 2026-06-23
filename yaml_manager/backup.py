"""File backup history, diffs, and conflict-safe restoration."""

from __future__ import annotations

import difflib
import re
import shutil
import time
from http import HTTPStatus
from pathlib import Path
from typing import Any

try:
    from .errors import ApiError
except ImportError:  # pragma: no cover - direct execution in the app container
    from errors import ApiError


def create_backup(backend: Any, relative: str, source: Path) -> None:
    prefix = time.strftime("%Y%m%d-%H%M%S")
    suffix = time.time_ns() % 1_000_000
    backups_root = backend.DATA_ROOT / "backups"
    for offset in range(1_000_000):
        stamp = f"{prefix}-{(suffix + offset) % 1_000_000:06d}"
        destination = backups_root / stamp / relative
        if not destination.exists():
            break
    else:  # pragma: no cover - impossible without exhausting every microsecond ID
        raise OSError("Für diese Sekunde ist keine freie Backup-ID verfügbar.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    backups = sorted(
        backups_root.iterdir(),
        key=lambda item: item.name,
        reverse=True,
    )
    for old in backups[backend.backup_retention_count():]:
        shutil.rmtree(old, ignore_errors=True)


def history_target(backend: Any, scope: str, raw_path: str = "") -> tuple[str, Path, Path]:
    if scope == "configuration":
        relative = Path("configuration/configuration.yaml")
        return relative.as_posix(), backend.configuration_file(), relative
    if scope == "package":
        relative, absolute = backend.normalize_relative_path(raw_path)
        return relative, absolute, Path(relative)
    raise ApiError(HTTPStatus.BAD_REQUEST, "Unbekannter Versionsbereich.")


def backup_file(backend: Any, backup_id: str, relative: Path) -> Path:
    if not re.fullmatch(r"\d{8}-\d{6}-\d{6}", backup_id or ""):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ungültige Backup-ID.")
    path = (backend.DATA_ROOT / "backups" / backup_id / relative).resolve()
    backups_root = (backend.DATA_ROOT / "backups").resolve()
    try:
        path.relative_to(backups_root)
    except ValueError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ungültiger Backup-Pfad.") from exc
    if not path.is_file():
        raise ApiError(HTTPStatus.NOT_FOUND, "Die Sicherung wurde nicht gefunden.")
    return path


def backup_history(backend: Any, scope: str, raw_path: str = "") -> dict[str, Any]:
    display_path, current_path, relative = history_target(backend, scope, raw_path)
    try:
        current = current_path.read_bytes()
    except FileNotFoundError as exc:
        raise ApiError(HTTPStatus.NOT_FOUND, "Die aktuelle Datei wurde nicht gefunden.") from exc
    entries: list[dict[str, Any]] = []
    backups_root = backend.DATA_ROOT / "backups"
    for directory in sorted(backups_root.iterdir(), key=lambda item: item.name, reverse=True):
        if not directory.is_dir() or not re.fullmatch(r"\d{8}-\d{6}-\d{6}", directory.name):
            continue
        candidate = directory / relative
        if not candidate.is_file():
            continue
        content = candidate.read_bytes()
        changes = list(
            difflib.ndiff(
                content.decode("utf-8", errors="replace").splitlines(),
                current.decode("utf-8", errors="replace").splitlines(),
            )
        )
        entries.append(
            {
                "id": directory.name,
                "created": time.strftime(
                    "%Y-%m-%dT%H:%M:%S",
                    time.strptime(directory.name[:15], "%Y%m%d-%H%M%S"),
                ),
                "size": len(content),
                "version": backend.file_version(content),
                "additions": sum(line.startswith("+ ") for line in changes),
                "deletions": sum(line.startswith("- ") for line in changes),
            }
        )
    return {
        "scope": scope,
        "path": (
            "/config/configuration.yaml"
            if scope == "configuration"
            else f"/config/packages/{display_path}"
        ),
        "currentVersion": backend.file_version(current),
        "entries": entries,
    }


def backup_diff(
    backend: Any,
    scope: str,
    raw_path: str,
    backup_id: str,
) -> dict[str, Any]:
    display_path, current_path, relative = history_target(backend, scope, raw_path)
    backup_path = backup_file(backend, backup_id, relative)
    try:
        before = backup_path.read_text(encoding="utf-8").splitlines()
        after = current_path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ApiError(
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            "Die Sicherung ist nicht UTF-8-kodiert.",
        ) from exc
    lines = list(
        difflib.unified_diff(
            before,
            after,
            fromfile=f"Backup {backup_id}",
            tofile="Aktuelle Fassung",
            lineterm="",
        )
    )
    return {
        "id": backup_id,
        "path": display_path,
        "diff": "\n".join(lines[:1200]),
        "truncated": len(lines) > 1200,
    }


def restore_backup(
    backend: Any,
    scope: str,
    raw_path: str,
    backup_id: str,
    expected_version: str | None,
) -> dict[str, Any]:
    if not isinstance(expected_version, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die aktuelle Dateiversion fehlt. Bitte neu laden.")
    display_path, current_path, relative = history_target(backend, scope, raw_path)
    restored = backup_file(backend, backup_id, relative).read_bytes()
    try:
        restored_text = restored.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiError(
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            "Die Sicherung ist nicht UTF-8-kodiert.",
        ) from exc
    validation = backend.validate_yaml(restored_text)
    if not validation["valid"]:
        raise ApiError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "Die Sicherung enthält ungültiges YAML.",
            validation,
        )

    with backend.file_lock:
        try:
            current = current_path.read_bytes()
        except FileNotFoundError as exc:
            raise ApiError(HTTPStatus.NOT_FOUND, "Die aktuelle Datei wurde nicht gefunden.") from exc
        if backend.file_version(current) != expected_version:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Die Datei wurde zwischenzeitlich geändert. Bitte neu laden.",
            )
        backend.git_checkpoint([current_path])
        create_backup(backend, display_path, current_path)
        backend.atomic_write_path(current_path, restored, current_path.stat().st_mode)
        git_result = backend.git_commit_paths(
            [current_path],
            f"Backup wiederhergestellt: {display_path}",
        )

    result = (
        backend.read_configuration()
        if scope == "configuration"
        else backend.read_file(display_path)
    )
    result["configurationCheck"] = backend.check_home_assistant_configuration()
    result["git"] = git_result
    result.update(
        {
            "message": f"Backup {backup_id} wurde wiederhergestellt.",
            "restoredBackup": backup_id,
        }
    )
    return result
