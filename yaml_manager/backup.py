"""File backup history, diffs, and conflict-safe restoration."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import shutil
import sqlite3
import time
import urllib.parse
import zipfile
from http import HTTPStatus
from pathlib import Path
from typing import Any

try:
    from .errors import ApiError
except ImportError:  # pragma: no cover - direct execution in the app container
    from errors import ApiError


BACKUP_ID_PATTERN = r"\d{8}-\d{6}-\d{6}"
MANIFEST_NAME = "manifest.json"
SNAPSHOT_NAME = "snapshot.zip"
RECORDER_DB_NAME = "home-assistant_v2.db"


def _stamp() -> tuple[str, int]:
    prefix = time.strftime("%Y%m%d-%H%M%S")
    suffix = time.time_ns() % 1_000_000
    return prefix, suffix


def _iso_from_stamp(stamp: str) -> str:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.strptime(stamp[:15], "%Y%m%d-%H%M%S"))
    except ValueError:
        return ""


def _backup_directories(backend: Any) -> list[Path]:
    backups_root = backend.DATA_ROOT / "backups"
    if not backups_root.exists():
        return []
    return [
        item for item in backups_root.iterdir()
        if item.is_dir() and re.fullmatch(BACKUP_ID_PATTERN, item.name)
    ]


def _database_backup_directories(backend: Any) -> list[Path]:
    root = backend.DATA_ROOT / "db-backups"
    if not root.exists():
        return []
    return [
        item for item in root.iterdir()
        if item.is_dir() and re.fullmatch(BACKUP_ID_PATTERN, item.name)
    ]


def _next_directory(root: Path) -> tuple[str, Path]:
    prefix, suffix = _stamp()
    for offset in range(1_000_000):
        stamp = f"{prefix}-{(suffix + offset) % 1_000_000:06d}"
        directory = root / stamp
        if not directory.exists():
            return stamp, directory
    else:  # pragma: no cover - impossible without exhausting every microsecond ID
        raise OSError("Für diese Sekunde ist keine freie Backup-ID verfügbar.")


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_size(path: Path) -> int:
    total = 0
    if path.exists():
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    pass
    return total


def _manifest_path(directory: Path) -> Path:
    return directory / MANIFEST_NAME


def _read_manifest(directory: Path) -> dict[str, Any]:
    try:
        value = json.loads(_manifest_path(directory).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_manifest(backend: Any, directory: Path, manifest: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    backend.atomic_write_path(_manifest_path(directory), encoded, 0o600)


def _git_commit(backend: Any) -> str:
    try:
        return backend.run_git(["rev-parse", "HEAD"]).stdout.decode("ascii", errors="replace").strip()
    except Exception:
        return ""


def _last_home_assistant_check(backend: Any) -> dict[str, Any]:
    value = getattr(backend, "last_configuration_check", None)
    return value if isinstance(value, dict) else {"available": False, "message": "Kein Home-Assistant-Check protokolliert."}


def _manifest_entry(path: str, content: bytes) -> dict[str, Any]:
    return {
        "path": path,
        "size": len(content),
        "sha256": _sha256_bytes(content),
    }


def _backup_entry(directory: Path) -> dict[str, Any]:
    manifest = _read_manifest(directory)
    size = int(manifest.get("size") or _directory_size(directory))
    backup_type = str(manifest.get("type") or ("snapshot" if (directory / SNAPSHOT_NAME).is_file() else "file"))
    return {
        "id": directory.name,
        "type": backup_type,
        "created": manifest.get("created") or _iso_from_stamp(directory.name),
        "pinned": bool(manifest.get("pinned")),
        "size": size,
        "files": len(manifest.get("files", [])) if isinstance(manifest.get("files"), list) else 0,
        "source": manifest.get("source", {}),
        "summary": manifest.get("summary", {}),
        "restoreStatus": manifest.get("restoreStatus", {"status": "never"}),
        "manifest": bool(manifest),
    }


def _database_backup_entry(directory: Path) -> dict[str, Any]:
    manifest = _read_manifest(directory)
    db_path = directory / RECORDER_DB_NAME
    return {
        "id": directory.name,
        "type": "database",
        "created": manifest.get("created") or _iso_from_stamp(directory.name),
        "pinned": bool(manifest.get("pinned")),
        "size": int(manifest.get("size") or (db_path.stat().st_size if db_path.exists() else 0)),
        "source": manifest.get("source", {}),
        "restoreStatus": manifest.get("restoreStatus", {"status": "not-supported"}),
        "manifest": bool(manifest),
    }


def _is_pinned(directory: Path) -> bool:
    return bool(_read_manifest(directory).get("pinned"))


def cleanup_backups(backend: Any) -> dict[str, int]:
    settings = backend.load_settings()
    retention_count = int(settings.get("backupRetention", backend.backup_retention_count()))
    retention_days = int(settings.get("backupRetentionDays", 0))
    max_size = int(settings.get("backupMaxSizeMiB", 0)) * 1024 * 1024
    now = time.time()
    removed = 0
    removed_size = 0

    def remove(directory: Path) -> None:
        nonlocal removed, removed_size
        size = _directory_size(directory)
        shutil.rmtree(directory, ignore_errors=True)
        removed += 1
        removed_size += size

    directories = sorted(_backup_directories(backend), key=lambda item: item.name)
    if retention_days > 0:
        threshold = now - retention_days * 24 * 60 * 60
        for directory in list(directories):
            if _is_pinned(directory):
                continue
            try:
                created = time.mktime(time.strptime(directory.name[:15], "%Y%m%d-%H%M%S"))
            except ValueError:
                created = directory.stat().st_mtime
            if created < threshold:
                remove(directory)
        directories = sorted([item for item in directories if item.exists()], key=lambda item: item.name)

    unpinned = [directory for directory in directories if not _is_pinned(directory)]
    while len(directories) > retention_count and unpinned:
        directory = unpinned.pop(0)
        remove(directory)
        directories = [item for item in directories if item.exists()]

    if max_size > 0:
        directories = sorted([item for item in _backup_directories(backend)], key=lambda item: item.name)
        total = sum(_directory_size(directory) for directory in directories)
        for directory in directories:
            if total <= max_size:
                break
            if _is_pinned(directory):
                continue
            size = _directory_size(directory)
            remove(directory)
            total -= size

    db_directories = sorted(_database_backup_directories(backend), key=lambda item: item.name)
    if retention_days > 0:
        threshold = now - retention_days * 24 * 60 * 60
        for directory in list(db_directories):
            if _is_pinned(directory):
                continue
            try:
                created = time.mktime(time.strptime(directory.name[:15], "%Y%m%d-%H%M%S"))
            except ValueError:
                created = directory.stat().st_mtime
            if created < threshold:
                remove(directory)
        db_directories = sorted([item for item in db_directories if item.exists()], key=lambda item: item.name)
    unpinned_db = [directory for directory in db_directories if not _is_pinned(directory)]
    while len(db_directories) > retention_count and unpinned_db:
        directory = unpinned_db.pop(0)
        remove(directory)
        db_directories = [item for item in db_directories if item.exists()]

    return {"removed": removed, "removedSize": removed_size}


def create_backup(backend: Any, relative: str, source: Path) -> None:
    backups_root = backend.DATA_ROOT / "backups"
    stamp, directory = _next_directory(backups_root)
    destination = directory / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    content = destination.read_bytes()
    manifest = {
        "schema": 1,
        "id": stamp,
        "type": "file",
        "created": _iso_from_stamp(stamp),
        "pinned": False,
        "size": _directory_size(directory),
        "source": {
            "relative": relative,
            "path": str(source),
        },
        "files": [_manifest_entry(relative, content)],
        "gitCommit": _git_commit(backend),
        "homeAssistantCheck": _last_home_assistant_check(backend),
        "restoreStatus": {"status": "never", "count": 0},
    }
    _write_manifest(backend, directory, manifest)
    cleanup_backups(backend)


def history_target(backend: Any, scope: str, raw_path: str = "") -> tuple[str, Path, Path]:
    if scope == "configuration":
        relative = Path("configuration/configuration.yaml")
        return relative.as_posix(), backend.configuration_file(), relative
    if scope == "package":
        relative, absolute = backend.normalize_relative_path(raw_path)
        return relative, absolute, Path(relative)
    raise ApiError(HTTPStatus.BAD_REQUEST, "Unbekannter Versionsbereich.")


def backup_file(backend: Any, backup_id: str, relative: Path) -> Path:
    if not re.fullmatch(BACKUP_ID_PATTERN, backup_id or ""):
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


def backup_directory(backend: Any, backup_id: str) -> Path:
    if not re.fullmatch(BACKUP_ID_PATTERN, backup_id or ""):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ungültige Backup-ID.")
    directory = (backend.DATA_ROOT / "backups" / backup_id).resolve()
    root = (backend.DATA_ROOT / "backups").resolve()
    try:
        directory.relative_to(root)
    except ValueError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ungültiger Backup-Pfad.") from exc
    if not directory.is_dir():
        raise ApiError(HTTPStatus.NOT_FOUND, "Das Backup wurde nicht gefunden.")
    return directory


def database_backup_directory(backend: Any, backup_id: str) -> Path:
    if not re.fullmatch(BACKUP_ID_PATTERN, backup_id or ""):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ungültige Datenbank-Backup-ID.")
    directory = (backend.DATA_ROOT / "db-backups" / backup_id).resolve()
    root = (backend.DATA_ROOT / "db-backups").resolve()
    try:
        directory.relative_to(root)
    except ValueError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ungültiger Datenbank-Backup-Pfad.") from exc
    if not directory.is_dir():
        raise ApiError(HTTPStatus.NOT_FOUND, "Das Datenbank-Backup wurde nicht gefunden.")
    return directory


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
                "created": _iso_from_stamp(directory.name),
                "size": len(content),
                "version": backend.file_version(content),
                "additions": sum(line.startswith("+ ") for line in changes),
                "deletions": sum(line.startswith("- ") for line in changes),
                "pinned": bool(_read_manifest(directory).get("pinned")),
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
        _record_restore(backend, backup_id, "restored", f"{display_path} wiederhergestellt")

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


def _record_restore(backend: Any, backup_id: str, status: str, message: str) -> None:
    try:
        directory = backup_directory(backend, backup_id)
    except ApiError:
        return
    manifest = _read_manifest(directory)
    if not manifest:
        return
    previous = manifest.get("restoreStatus") if isinstance(manifest.get("restoreStatus"), dict) else {}
    manifest["restoreStatus"] = {
        "status": status,
        "message": message,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "count": int(previous.get("count") or 0) + 1,
    }
    _write_manifest(backend, directory, manifest)


def set_backup_pin(backend: Any, raw_id: Any, pinned: Any) -> dict[str, Any]:
    backup_id = str(raw_id or "")
    directory = backup_directory(backend, backup_id)
    manifest = _read_manifest(directory) or {
        "schema": 1,
        "id": backup_id,
        "type": "snapshot" if (directory / SNAPSHOT_NAME).is_file() else "file",
        "created": _iso_from_stamp(backup_id),
        "size": _directory_size(directory),
        "files": [],
        "restoreStatus": {"status": "never", "count": 0},
    }
    manifest["pinned"] = bool(pinned)
    _write_manifest(backend, directory, manifest)
    return backup_overview(backend)


def _safe_zip_path(raw_name: str) -> str | None:
    name = raw_name.strip().replace("\\", "/").lstrip("/")
    if not name or any(part in {"", ".", ".."} or part.startswith(".") for part in Path(name).parts):
        return None
    allowed = (
        name == "configuration.yaml"
        or name.startswith("packages/")
        or name.startswith("blueprints/")
        or name in {"secrets.masked.yaml", "snapshot.manifest.json"}
    )
    return name if allowed else None


def _masked_secrets(content: str) -> str:
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in line:
            lines.append(line)
            continue
        key, _sep, _value = line.partition(":")
        lines.append(f"{key}: \"***\"")
    return "\n".join(lines) + ("\n" if content.endswith("\n") else "")


def _snapshot_sources(backend: Any, secrets_mode: str) -> dict[str, bytes]:
    root = backend.PACKAGES_ROOT.parent.resolve()
    sources: dict[str, bytes] = {}
    configuration = backend.configuration_file()
    if configuration.is_file():
        sources["configuration.yaml"] = configuration.read_bytes()
    packages_root = backend.PACKAGES_ROOT.resolve()
    if packages_root.exists():
        for path in sorted(packages_root.rglob("*")):
            if path.is_file() and path.suffix.lower() in backend.VALID_SUFFIXES:
                sources[f"packages/{path.relative_to(packages_root).as_posix()}"] = path.read_bytes()
    blueprints_root = root / "blueprints"
    if blueprints_root.exists():
        for path in sorted(blueprints_root.rglob("*")):
            if path.is_file() and path.suffix.lower() in backend.VALID_SUFFIXES:
                sources[f"blueprints/{path.relative_to(blueprints_root).as_posix()}"] = path.read_bytes()
    secrets = root / "secrets.yaml"
    if secrets_mode == "masked" and secrets.is_file():
        sources["secrets.masked.yaml"] = _masked_secrets(secrets.read_text(encoding="utf-8", errors="replace")).encode("utf-8")
    return sources


def create_snapshot(backend: Any, body: dict[str, Any] | None = None) -> dict[str, Any]:
    raw_mode = (body or {}).get("secretsMode", "masked")
    secrets_mode = raw_mode if raw_mode in {"none", "masked"} else "masked"
    backups_root = backend.DATA_ROOT / "backups"
    stamp, directory = _next_directory(backups_root)
    directory.mkdir(parents=True, exist_ok=True)
    zip_path = directory / SNAPSHOT_NAME
    sources = _snapshot_sources(backend, secrets_mode)
    files = [_manifest_entry(path, content) for path, content in sources.items()]
    manifest = {
        "schema": 1,
        "id": stamp,
        "type": "snapshot",
        "created": _iso_from_stamp(stamp),
        "pinned": bool((body or {}).get("pinned", False)),
        "source": {"root": str(backend.PACKAGES_ROOT.parent.resolve()), "secretsMode": secrets_mode},
        "summary": {
            "files": len(files),
            "packages": sum(item["path"].startswith("packages/") for item in files),
            "blueprints": sum(item["path"].startswith("blueprints/") for item in files),
            "configuration": any(item["path"] == "configuration.yaml" for item in files),
            "maskedSecrets": any(item["path"] == "secrets.masked.yaml" for item in files),
        },
        "files": files,
        "gitCommit": _git_commit(backend),
        "homeAssistantCheck": backend.check_home_assistant_configuration(),
        "restoreStatus": {"status": "never", "count": 0},
    }
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in sources.items():
            archive.writestr(path, content)
        archive.writestr("snapshot.manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    manifest["size"] = _directory_size(directory)
    manifest["archive"] = {"path": SNAPSHOT_NAME, "sha256": _sha256_file(zip_path), "size": zip_path.stat().st_size}
    _write_manifest(backend, directory, manifest)
    cleanup_backups(backend)
    return {
        "message": f"Snapshot {stamp} wurde erstellt.",
        "snapshot": _backup_entry(directory),
        "overview": backup_overview(backend),
    }


def _snapshot_zip(backend: Any, backup_id: str) -> Path:
    directory = backup_directory(backend, backup_id)
    manifest = _read_manifest(directory)
    if manifest.get("type") != "snapshot" and not (directory / SNAPSHOT_NAME).is_file():
        raise ApiError(HTTPStatus.BAD_REQUEST, "Dieses Backup ist kein Snapshot.")
    zip_path = directory / SNAPSHOT_NAME
    if not zip_path.is_file():
        raise ApiError(HTTPStatus.NOT_FOUND, "Das Snapshot-Archiv wurde nicht gefunden.")
    return zip_path


def _snapshot_targets(backend: Any, zip_path: Path) -> tuple[dict[Path, bytes], list[dict[str, Any]], list[dict[str, Any]]]:
    root = backend.PACKAGES_ROOT.parent.resolve()
    targets: dict[Path, bytes] = {}
    files: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = _safe_zip_path(info.filename)
            if not name or name in {"snapshot.manifest.json", "secrets.masked.yaml"}:
                continue
            content = archive.read(info)
            if name == "configuration.yaml":
                destination = backend.configuration_file()
            else:
                destination = (root / name).resolve()
                try:
                    destination.relative_to(root)
                except ValueError:
                    errors.append({"path": name, "message": "Ziel liegt außerhalb der HA-Konfiguration."})
                    continue
            if Path(name).suffix.lower() in backend.VALID_SUFFIXES:
                try:
                    text = content.decode("utf-8")
                except UnicodeDecodeError:
                    errors.append({"path": name, "message": "Datei ist nicht UTF-8-kodiert."})
                else:
                    validation = backend.validate_yaml(text)
                    if not validation["valid"]:
                        errors.append({"path": name, "message": validation["message"], "line": validation.get("line")})
            targets[destination] = content
            files.append({"path": name, "size": len(content), "exists": destination.exists()})
    return targets, files, errors


def _snapshot_state_version(targets: dict[Path, bytes], zip_path: Path) -> str:
    versions = [_sha256_file(zip_path)]
    for path in sorted(targets, key=lambda item: str(item)):
        if path.is_file():
            versions.append(f"{path}\0{_sha256_file(path)}")
        else:
            versions.append(f"{path}\0missing")
    return _sha256_bytes("\n".join(versions).encode("utf-8"))


def snapshot_restore_preview(backend: Any, raw_id: Any) -> dict[str, Any]:
    backup_id = str(raw_id or "")
    zip_path = _snapshot_zip(backend, backup_id)
    targets, files, errors = _snapshot_targets(backend, zip_path)
    overlay = {
        path.relative_to(backend.PACKAGES_ROOT.resolve()).as_posix(): content.decode("utf-8", errors="replace")
        for path, content in targets.items()
        if path.is_relative_to(backend.PACKAGES_ROOT.resolve())
    }
    conflicts = backend.package_conflict_analysis(overlay) if not errors else {"findings": [], "counts": {"error": 0, "warning": 0}}
    error_count = len(errors) + conflicts["counts"].get("error", 0)
    return {
        "id": backup_id,
        "valid": error_count == 0,
        "stateVersion": _snapshot_state_version(targets, zip_path),
        "files": files,
        "errors": errors,
        "conflicts": conflicts,
        "configurationCheck": backend.check_home_assistant_configuration(),
        "summary": {
            "files": len(files),
            "errors": error_count,
            "warnings": conflicts["counts"].get("warning", 0),
        },
    }


def restore_snapshot(backend: Any, raw_id: Any, state_version: Any) -> dict[str, Any]:
    backup_id = str(raw_id or "")
    preview = snapshot_restore_preview(backend, backup_id)
    if not preview["valid"]:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Der Snapshot ist nicht wiederherstellbar.", preview)
    if not isinstance(state_version, str) or state_version != preview["stateVersion"]:
        raise ApiError(HTTPStatus.CONFLICT, "Der Snapshot-Stand oder die Zielkonfiguration hat sich geändert. Bitte erneut prüfen.")
    zip_path = _snapshot_zip(backend, backup_id)
    targets, _files, _errors = _snapshot_targets(backend, zip_path)
    originals = {path: path.read_bytes() if path.is_file() else None for path in targets}
    modes = {path: path.stat().st_mode if path.exists() else 0o644 for path in targets}
    with backend.file_lock:
        backend.git_checkpoint(list(targets))
        for path in targets:
            if path.is_file():
                if path == backend.configuration_file():
                    relative = "configuration/configuration.yaml"
                elif path.is_relative_to(backend.PACKAGES_ROOT.resolve()):
                    relative = path.relative_to(backend.PACKAGES_ROOT.resolve()).as_posix()
                else:
                    relative = path.relative_to(backend.PACKAGES_ROOT.parent.resolve()).as_posix()
                create_backup(backend, relative, path)
        try:
            for path, content in targets.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                backend.atomic_write_path(path, content, modes[path])
        except OSError as exc:
            for path, original in originals.items():
                if original is None:
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
                else:
                    backend.atomic_write_path(path, original, modes[path])
            raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "Der Snapshot-Restore wurde nach einem Schreibfehler zurückgerollt.") from exc
        git_result = backend.git_commit_paths(list(targets), f"Snapshot wiederhergestellt: {backup_id}")
    configuration_check = backend.check_home_assistant_configuration()
    _record_restore(backend, backup_id, "restored", f"{len(targets)} Dateien aus Snapshot wiederhergestellt")
    return {
        "message": f"Snapshot {backup_id} wurde wiederhergestellt.",
        "restored": len(targets),
        "configurationCheck": configuration_check,
        "git": git_result,
        "overview": backup_overview(backend),
    }


def create_database_backup(backend: Any) -> dict[str, Any]:
    source = (backend.PACKAGES_ROOT.parent / RECORDER_DB_NAME).resolve()
    if not source.is_file():
        raise ApiError(HTTPStatus.NOT_FOUND, f"Recorder-Datenbank wurde nicht gefunden: {source}")
    root = backend.DATA_ROOT / "db-backups"
    stamp, directory = _next_directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / RECORDER_DB_NAME
    uri = f"file:{urllib.parse.quote(str(source))}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=1.0) as source_connection:
            with sqlite3.connect(destination) as target_connection:
                source_connection.backup(target_connection)
    except sqlite3.Error as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, f"Recorder-Datenbank konnte nicht gesichert werden: {exc}") from exc
    content_hash = _sha256_file(destination)
    manifest = {
        "schema": 1,
        "id": stamp,
        "type": "database",
        "created": _iso_from_stamp(stamp),
        "pinned": False,
        "source": {"path": str(source)},
        "size": destination.stat().st_size,
        "files": [{"path": RECORDER_DB_NAME, "size": destination.stat().st_size, "sha256": content_hash}],
        "restoreStatus": {"status": "not-supported", "count": 0},
    }
    _write_manifest(backend, directory, manifest)
    return {
        "message": f"Recorder-Datenbank-Backup {stamp} wurde erstellt.",
        "databaseBackup": _database_backup_entry(directory),
        "overview": backup_overview(backend),
    }


def _integrity_findings_for_directory(backend: Any, directory: Path, database: bool = False) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    manifest = _read_manifest(directory)
    if not manifest:
        findings.append({"severity": "warning", "code": "backup-missing-manifest", "title": f"{directory.name} hat kein Manifest", "message": "Ältere Backups bleiben nutzbar, liefern aber keine Hash-Prüfung."})
    if manifest.get("type") == "snapshot":
        zip_path = directory / SNAPSHOT_NAME
        if not zip_path.is_file():
            return [{"severity": "error", "code": "backup-missing-file", "title": f"{directory.name}: Snapshot-Archiv fehlt", "message": "snapshot.zip existiert nicht mehr."}]
        archive_manifest = manifest.get("archive") if isinstance(manifest.get("archive"), dict) else {}
        expected_hash = archive_manifest.get("sha256")
        if isinstance(expected_hash, str) and expected_hash and _sha256_file(zip_path) != expected_hash:
            findings.append({"severity": "error", "code": "backup-hash-mismatch", "title": f"{directory.name}: Snapshot-Archiv Hash passt nicht", "message": "Das Snapshot-Archiv wurde seit der Erstellung verändert."})
        try:
            with zipfile.ZipFile(zip_path) as archive:
                names = {info.filename for info in archive.infolist() if not info.is_dir()}
                files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
                for entry in files:
                    relative = str(entry.get("path", ""))
                    if relative not in names:
                        findings.append({"severity": "error", "code": "backup-missing-file", "title": f"{directory.name}: {relative} fehlt im Snapshot", "message": "Die im Manifest genannte Datei existiert nicht im ZIP."})
                        continue
                    content = archive.read(relative)
                    if isinstance(entry.get("size"), int) and len(content) != entry["size"]:
                        findings.append({"severity": "error", "code": "backup-size-mismatch", "title": f"{directory.name}: {relative} hat eine andere Größe", "message": "Die Größe im ZIP stimmt nicht mit dem Manifest überein."})
                    if isinstance(entry.get("sha256"), str) and entry["sha256"] and _sha256_bytes(content) != entry["sha256"]:
                        findings.append({"severity": "error", "code": "backup-hash-mismatch", "title": f"{directory.name}: {relative} Hash passt nicht", "message": "Die Snapshot-Datei wurde seit der Erstellung verändert."})
        except zipfile.BadZipFile:
            findings.append({"severity": "error", "code": "backup-invalid-archive", "title": f"{directory.name}: Snapshot ist kein gültiges ZIP", "message": "Das Archiv kann nicht gelesen werden."})
        return findings
    files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
    if not files:
        candidates = [
            item for item in directory.rglob("*")
            if item.is_file() and item.name != MANIFEST_NAME
        ]
        files = [{"path": item.relative_to(directory).as_posix(), "size": item.stat().st_size, "sha256": ""} for item in candidates]
    for entry in files:
        relative = str(entry.get("path", ""))
        path = directory / relative
        if not path.is_file():
            findings.append({"severity": "error", "code": "backup-missing-file", "title": f"{directory.name}: {relative} fehlt", "message": "Die im Manifest genannte Datei existiert nicht mehr."})
            continue
        expected_size = entry.get("size")
        if isinstance(expected_size, int) and path.stat().st_size != expected_size:
            findings.append({"severity": "error", "code": "backup-size-mismatch", "title": f"{directory.name}: {relative} hat eine andere Größe", "message": "Die Dateigröße stimmt nicht mit dem Manifest überein."})
        expected_hash = entry.get("sha256")
        if isinstance(expected_hash, str) and expected_hash:
            actual_hash = _sha256_file(path)
            if actual_hash != expected_hash:
                findings.append({"severity": "error", "code": "backup-hash-mismatch", "title": f"{directory.name}: {relative} Hash passt nicht", "message": "Die Sicherung wurde seit der Erstellung verändert."})
        if not database and Path(relative).suffix.lower() in backend.VALID_SUFFIXES:
            try:
                validation = backend.validate_yaml(path.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                findings.append({"severity": "error", "code": "backup-invalid-encoding", "title": f"{directory.name}: {relative} ist nicht UTF-8", "message": "Diese YAML-Sicherung kann nicht direkt wiederhergestellt werden."})
            else:
                if not validation["valid"]:
                    findings.append({"severity": "error", "code": "backup-invalid-yaml", "title": f"{directory.name}: {relative} enthält ungültiges YAML", "message": validation["message"]})
    return findings


def backup_integrity(backend: Any) -> dict[str, Any]:
    settings = backend.load_settings()
    findings: list[dict[str, Any]] = []
    directories = _backup_directories(backend)
    db_directories = _database_backup_directories(backend)
    for directory in directories:
        findings.extend(_integrity_findings_for_directory(backend, directory))
    for directory in db_directories:
        findings.extend(_integrity_findings_for_directory(backend, directory, database=True))
    max_size = int(settings.get("backupMaxSizeMiB", 0)) * 1024 * 1024
    backup_size = sum(_directory_size(directory) for directory in directories)
    if max_size > 0 and backup_size > max_size:
        findings.append({"severity": "warning", "code": "backup-size-limit", "title": "Backup-Verzeichnis überschreitet Größenlimit", "message": f"{backup_size} Bytes belegt, Limit {max_size} Bytes."})
    retention_days = int(settings.get("backupRetentionDays", 0))
    if retention_days > 0:
        threshold = time.time() - retention_days * 24 * 60 * 60
        for directory in directories:
            if _is_pinned(directory):
                continue
            try:
                created = time.mktime(time.strptime(directory.name[:15], "%Y%m%d-%H%M%S"))
            except ValueError:
                created = directory.stat().st_mtime
            if created < threshold:
                findings.append({"severity": "warning", "code": "backup-expired", "title": f"Backup {directory.name} ist älter als die Aufbewahrung", "message": "Dieses Backup wird bei der nächsten Bereinigung entfernt, sofern es nicht gepinnt wird."})
    return {
        "summary": {
            "backups": len(directories),
            "databaseBackups": len(db_directories),
            "size": backup_size,
            "errors": sum(item["severity"] == "error" for item in findings),
            "warnings": sum(item["severity"] == "warning" for item in findings),
        },
        "findings": findings[:300],
        "truncated": len(findings) > 300,
    }


def backup_overview(backend: Any) -> dict[str, Any]:
    cleanup = cleanup_backups(backend)
    entries = [_backup_entry(directory) for directory in sorted(_backup_directories(backend), key=lambda item: item.name, reverse=True)]
    database_entries = [
        _database_backup_entry(directory)
        for directory in sorted(_database_backup_directories(backend), key=lambda item: item.name, reverse=True)
    ]
    integrity = backup_integrity(backend)
    settings = backend.load_settings()
    return {
        "summary": {
            "backups": len(entries),
            "fileBackups": sum(item["type"] == "file" for item in entries),
            "snapshots": sum(item["type"] == "snapshot" for item in entries),
            "databaseBackups": len(database_entries),
            "pinned": sum(item["pinned"] for item in entries) + sum(item["pinned"] for item in database_entries),
            "size": sum(item["size"] for item in entries),
            "errors": integrity["summary"]["errors"],
            "warnings": integrity["summary"]["warnings"],
        },
        "retention": {
            "count": settings["backupRetention"],
            "days": settings.get("backupRetentionDays", 0),
            "maxSizeMiB": settings.get("backupMaxSizeMiB", 0),
        },
        "cleanup": cleanup,
        "backups": entries,
        "databaseBackups": database_entries,
        "integrity": integrity,
    }
