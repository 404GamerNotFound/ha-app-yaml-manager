"""Scheduled and manual maintenance runs for the HA Maintenance Hub."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import Any

try:
    from .errors import ApiError
except ImportError:  # pragma: no cover - direct execution in the app container
    from errors import ApiError


STATUS_WEIGHT = {"ok": 0, "warning": 1, "error": 2}
_run_lock = threading.Lock()
_scheduler_started = False
_scheduler_guard = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _history_file(backend: Any) -> Any:
    return backend.DATA_ROOT / "maintenance-history.json"


def _status(*values: str) -> str:
    worst = max((STATUS_WEIGHT.get(value, 0) for value in values), default=0)
    for name, weight in STATUS_WEIGHT.items():
        if weight == worst:
            return name
    return "ok"


def _finding_key(finding: dict[str, Any]) -> str:
    code = str(finding.get("code") or "")
    title = str(finding.get("title") or "")
    message = str(finding.get("message") or "")
    return f"{code}|{title}|{message}"


def load_history(backend: Any) -> list[dict[str, Any]]:
    try:
        raw = json.loads(_history_file(backend).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    entries = raw.get("entries") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return []
    clean = [entry for entry in entries if isinstance(entry, dict)]
    clean.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
    return clean[:500]


def _save_history(backend: Any, entries: list[dict[str, Any]]) -> None:
    backend.DATA_ROOT.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix="maintenance-",
        suffix=".json",
        dir=backend.DATA_ROOT,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"entries": entries}, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, _history_file(backend))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def cleanup_history(backend: Any, entries: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    settings = backend.load_settings()
    retention = int(settings.get("maintenanceHistoryRetention", 30))
    history = load_history(backend) if entries is None else entries
    kept = history[:retention]
    if len(kept) != len(history) or entries is not None:
        _save_history(backend, kept)
    return kept


def _preflight_findings(preflight: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for check in preflight.get("checks", []):
        if not isinstance(check, dict) or check.get("status") == "ok":
            continue
        status = str(check.get("status") or "warning")
        findings.append(
            {
                "severity": "error" if status == "error" else "warning",
                "source": "preflight",
                "code": f"preflight-{check.get('id') or 'check'}",
                "title": str(check.get("title") or "Preflight"),
                "message": str(check.get("message") or ""),
            }
        )
    return findings


def _database_findings(health: dict[str, Any]) -> list[dict[str, Any]]:
    if not health:
        return []
    if not health.get("available"):
        return [
            {
                "severity": "warning",
                "source": "database",
                "code": "database-unavailable",
                "title": "Recorder-Datenbank nicht verfügbar",
                "message": str(health.get("message") or "Die lokale Recorder-Datenbank konnte nicht gelesen werden."),
            }
        ]
    findings: list[dict[str, Any]] = []
    quick_check = str(health.get("quickCheck") or "")
    if quick_check and quick_check != "ok":
        findings.append(
            {
                "severity": "error",
                "source": "database",
                "code": "database-quick-check",
                "title": "SQLite quick_check meldet Probleme",
                "message": quick_check,
            }
        )
    summary = health.get("summary") if isinstance(health.get("summary"), dict) else {}
    size = int(summary.get("size") or 0)
    wal_size = int(summary.get("walSize") or 0)
    if size > 0 and wal_size / max(size, 1) > 0.5:
        findings.append(
            {
                "severity": "warning",
                "source": "database",
                "code": "database-large-wal",
                "title": "Recorder-WAL ist auffällig groß",
                "message": f"{wal_size} Bytes WAL bei {size} Bytes Datenbankgröße.",
            }
        )
    if int(summary.get("rows") or 0) == 0:
        findings.append(
            {
                "severity": "warning",
                "source": "database",
                "code": "database-empty",
                "title": "Recorder enthält keine gelesenen Zeilen",
                "message": "Die Datenbank ist erreichbar, liefert aber keine verwertbaren Recorder-Zeilen.",
            }
        )
    return findings


def _system_findings(system: dict[str, Any]) -> list[dict[str, Any]]:
    storage = system.get("storage") if isinstance(system.get("storage"), dict) else {}
    trash = storage.get("trash") if isinstance(storage.get("trash"), dict) else {}
    if int(trash.get("entries") or 0) <= 0:
        return []
    return [
        {
            "severity": "warning",
            "source": "system",
            "code": "trash-has-entries",
            "title": "Papierkorb enthält Dateien",
            "message": f"{trash.get('entries')} Dateien belegen {trash.get('size', 0)} Bytes.",
        }
    ]


def _check_from_database(health: dict[str, Any]) -> dict[str, Any]:
    findings = _database_findings(health)
    status = "error" if any(item["severity"] == "error" for item in findings) else "warning" if findings else "ok"
    if not health:
        return {
            "id": "database",
            "title": "Recorder-Datenbank",
            "status": "ok",
            "message": "Datenbankprüfung ist deaktiviert.",
        }
    if not health.get("available"):
        return {
            "id": "database",
            "title": "Recorder-Datenbank",
            "status": status,
            "message": str(health.get("message") or "Nicht verfügbar."),
        }
    summary = health.get("summary") if isinstance(health.get("summary"), dict) else {}
    return {
        "id": "database",
        "title": "Recorder-Datenbank",
        "status": status,
        "message": f"quick_check: {health.get('quickCheck') or 'n/a'} · {summary.get('tables', 0)} Tabellen · {summary.get('rows', 0)} Zeilen",
    }


def _system_check(system: dict[str, Any]) -> dict[str, Any]:
    findings = _system_findings(system)
    storage = system.get("storage") if isinstance(system.get("storage"), dict) else {}
    backups = storage.get("backups") if isinstance(storage.get("backups"), dict) else {}
    db_backups = storage.get("databaseBackups") if isinstance(storage.get("databaseBackups"), dict) else {}
    trash = storage.get("trash") if isinstance(storage.get("trash"), dict) else {}
    return {
        "id": "system",
        "title": "Speicher und Laufzeit",
        "status": "warning" if findings else "ok",
        "message": f"{backups.get('directories', 0)} Backups · {db_backups.get('directories', 0)} DB-Backups · {trash.get('entries', 0)} Papierkorb-Dateien",
    }


def _run_delta(run: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if not previous:
        return {
            "previousRunId": None,
            "statusChanged": False,
            "blockers": 0,
            "warnings": 0,
            "newFindings": [],
            "resolvedFindings": [],
        }
    current_keys = {_finding_key(item) for item in run.get("findings", []) if isinstance(item, dict)}
    previous_keys = {_finding_key(item) for item in previous.get("findings", []) if isinstance(item, dict)}
    return {
        "previousRunId": previous.get("id"),
        "statusChanged": run.get("status") != previous.get("status"),
        "blockers": int(run.get("blockers") or 0) - int(previous.get("blockers") or 0),
        "warnings": int(run.get("warnings") or 0) - int(previous.get("warnings") or 0),
        "newFindings": sorted(current_keys - previous_keys)[:20],
        "resolvedFindings": sorted(previous_keys - current_keys)[:20],
    }


def _notification_message(run: dict[str, Any]) -> str:
    status = {"ok": "OK", "warning": "Warnung", "error": "Fehler"}.get(str(run.get("status")), "Status")
    return (
        f"Wartung: {status}\n"
        f"Blocker: {run.get('blockers', 0)}\n"
        f"Warnungen: {run.get('warnings', 0)}\n"
        f"Zeitpunkt: {run.get('createdAt', '')}"
    )


def _notify_home_assistant(backend: Any, run: dict[str, Any]) -> dict[str, Any]:
    try:
        backend.home_assistant_request(
            "services/persistent_notification/create",
            method="POST",
            payload={
                "title": "HA Maintenance Hub",
                "message": _notification_message(run),
                "notification_id": "ha_maintenance_hub_maintenance",
            },
        )
    except ApiError as exc:
        return {"sent": False, "message": exc.message}
    return {"sent": True, "message": "Home-Assistant-Benachrichtigung erstellt."}


def run_maintenance(backend: Any, triggered_by: Any = "manual") -> dict[str, Any]:
    if not _run_lock.acquire(blocking=False):
        raise ApiError(HTTPStatus.CONFLICT, "Ein Wartungslauf läuft bereits.")
    try:
        settings = backend.load_settings()
        history = load_history(backend)
        started = time.monotonic()
        created_at = _iso()
        trigger = str(triggered_by or "manual")[:32]
        preflight = backend.preflight()
        database = backend.database_health() if settings.get("maintenanceIncludeDatabase", True) else {}
        system = backend.system_health(include_git=True)
        findings = _preflight_findings(preflight) + _database_findings(database) + _system_findings(system)
        checks = [
            {
                "id": str(check.get("id") or ""),
                "title": str(check.get("title") or ""),
                "status": str(check.get("status") or "warning"),
                "message": str(check.get("message") or ""),
            }
            for check in preflight.get("checks", [])
            if isinstance(check, dict)
        ]
        checks.extend([_check_from_database(database), _system_check(system)])
        status = _status(str(preflight.get("status") or "ok"), *(str(check.get("status") or "ok") for check in checks))
        blocker_additions = sum(1 for item in findings if item.get("severity") == "error" and item.get("source") != "preflight")
        warning_additions = sum(1 for item in findings if item.get("severity") == "warning" and item.get("source") != "preflight")
        db_summary = database.get("summary") if isinstance(database.get("summary"), dict) else {}
        storage = system.get("storage") if isinstance(system.get("storage"), dict) else {}
        backup_storage = storage.get("backups") if isinstance(storage.get("backups"), dict) else {}
        db_backup_storage = storage.get("databaseBackups") if isinstance(storage.get("databaseBackups"), dict) else {}
        trash_storage = storage.get("trash") if isinstance(storage.get("trash"), dict) else {}
        run_id = (
            f"{created_at.replace('-', '').replace(':', '').replace('.', '').replace('Z', '')}"
            f"-{time.time_ns() % 1_000_000:06d}"
        )
        run: dict[str, Any] = {
            "id": run_id,
            "createdAt": created_at,
            "triggeredBy": trigger,
            "durationMs": int((time.monotonic() - started) * 1000),
            "status": status,
            "ready": bool(preflight.get("ready")) and status != "error",
            "blockers": int(preflight.get("blockers") or 0) + blocker_additions,
            "warnings": int(preflight.get("warnings") or 0) + warning_additions,
            "checks": checks,
            "findings": findings[:100],
            "summary": {
                "yamlErrors": preflight.get("summary", {}).get("yamlErrors", 0),
                "securityErrors": preflight.get("summary", {}).get("securityErrors", 0),
                "backupErrors": preflight.get("summary", {}).get("backupErrors", 0),
                "remoteConfigured": bool(preflight.get("summary", {}).get("remoteConfigured")),
                "databaseAvailable": bool(database.get("available")) if database else False,
                "databaseQuickCheck": database.get("quickCheck") if database else "",
                "databaseTables": db_summary.get("tables", 0),
                "databaseRows": db_summary.get("rows", 0),
                "databaseWalSize": db_summary.get("walSize", 0),
                "backupDirectories": backup_storage.get("directories", 0),
                "databaseBackupDirectories": db_backup_storage.get("directories", 0),
                "trashEntries": trash_storage.get("entries", 0),
                "trashSize": trash_storage.get("size", 0),
            },
            "details": {
                "preflight": preflight,
                "database": database,
                "system": system,
            },
        }
        run["delta"] = _run_delta(run, history[0] if history else None)
        if settings.get("maintenanceNotify") and status != "ok":
            run["notification"] = _notify_home_assistant(backend, run)
        updated = cleanup_history(backend, [run, *history])
        return {**run, "historyCount": len(updated)}
    finally:
        _run_lock.release()


def _next_run_at(latest: dict[str, Any] | None, interval_hours: int) -> str | None:
    if not latest:
        return None
    created = _parse_iso(latest.get("createdAt"))
    if not created:
        return None
    return _iso(created + timedelta(hours=interval_hours))


def maintenance_status(backend: Any) -> dict[str, Any]:
    settings = backend.load_settings()
    history = load_history(backend)
    latest = history[0] if history else None
    interval = int(settings.get("maintenanceIntervalHours", 24))
    next_run = _next_run_at(latest, interval)
    due_at = _parse_iso(next_run)
    due = bool(settings.get("maintenanceEnabled")) and (due_at is None or _now() >= due_at)
    if latest:
        message = (
            f"Letzter Lauf: {latest.get('status', 'unknown')} · "
            f"{latest.get('blockers', 0)} Blocker · {latest.get('warnings', 0)} Warnungen"
        )
    else:
        message = "Noch kein Wartungslauf gespeichert."
    return {
        "enabled": bool(settings.get("maintenanceEnabled")),
        "due": due,
        "nextRunAt": next_run,
        "latest": latest,
        "historyCount": len(history),
        "settings": {
            "enabled": bool(settings.get("maintenanceEnabled")),
            "intervalHours": interval,
            "historyRetention": int(settings.get("maintenanceHistoryRetention", 30)),
            "includeDatabase": bool(settings.get("maintenanceIncludeDatabase", True)),
            "notify": bool(settings.get("maintenanceNotify")),
        },
        "message": message,
    }


def maintenance_history(backend: Any) -> dict[str, Any]:
    entries = load_history(backend)
    return {"count": len(entries), "entries": entries}


def _scheduler_loop(backend: Any) -> None:
    time.sleep(60)
    while True:
        wait_seconds = 300
        try:
            status = maintenance_status(backend)
            settings = status.get("settings", {})
            if settings.get("enabled") and status.get("due"):
                run_maintenance(backend, "scheduled")
            wait_seconds = max(60, min(3600, int(settings.get("intervalHours", 24)) * 900))
        except Exception as exc:  # pragma: no cover - background guard
            print(f"Maintenance scheduler error: {exc!r}", flush=True)
        time.sleep(wait_seconds)


def start_scheduler(backend: Any) -> None:
    global _scheduler_started
    with _scheduler_guard:
        if _scheduler_started:
            return
        _scheduler_started = True
    thread = threading.Thread(
        target=_scheduler_loop,
        args=(backend,),
        name="ha-maintenance-scheduler",
        daemon=True,
    )
    thread.start()
