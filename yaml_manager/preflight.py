"""Preflight checks before publishing Home Assistant YAML changes."""

from __future__ import annotations

from typing import Any


def _status(ok: bool, warnings: int = 0) -> str:
    if not ok:
        return "error"
    return "warning" if warnings else "ok"


def preflight(backend: Any) -> dict[str, Any]:
    validation_errors = []
    for path, content in backend.managed_yaml_files().items():
        result = backend.validate_yaml(content)
        if not result["valid"]:
            validation_errors.append({"path": path, "message": result["message"], "line": result.get("line")})
    conflicts = backend.package_conflict_analysis()
    lint = backend.lint_scan()
    compatibility = backend.compatibility_scan()
    security = backend.security_scan()
    entity_health = backend.entity_health()
    docs = backend.documentation_status()
    remote = backend.git_remote_status()
    ha_check = backend.check_home_assistant_configuration()
    blockers = (
        len(validation_errors)
        + conflicts["counts"].get("error", 0)
        + lint["counts"].get("error", 0)
        + compatibility["counts"].get("error", 0)
        + security["counts"].get("error", 0)
        + (0 if ha_check.get("valid") is not False else 1)
    )
    warnings = (
        conflicts["counts"].get("warning", 0)
        + lint["counts"].get("warning", 0)
        + compatibility["counts"].get("warning", 0)
        + security["counts"].get("warning", 0)
        + entity_health["summary"].get("unknown", 0)
        + entity_health["summary"].get("unavailable", 0)
        + entity_health["summary"].get("disabled", 0)
        + (0 if docs.get("exists") else 1)
    )
    checks = [
        {
            "id": "yaml",
            "title": "YAML-Syntax",
            "status": _status(not validation_errors),
            "message": f"{len(validation_errors)} ungültige Dateien" if validation_errors else "Alle verwalteten YAML-Dateien sind syntaktisch gültig.",
            "details": validation_errors[:20],
        },
        {
            "id": "conflicts",
            "title": "Package-Konflikte",
            "status": _status(conflicts["counts"].get("error", 0) == 0, conflicts["counts"].get("warning", 0)),
            "message": f"{conflicts['counts'].get('error', 0)} Fehler · {conflicts['counts'].get('warning', 0)} Warnungen",
            "details": conflicts["findings"][:20],
        },
        {
            "id": "lint",
            "title": "Konfigurierbare Lint-Regeln",
            "status": _status(lint["counts"].get("error", 0) == 0, lint["counts"].get("warning", 0)),
            "message": f"{lint['counts'].get('error', 0)} Fehler · {lint['counts'].get('warning', 0)} Warnungen · {lint['counts'].get('tip', 0)} Tipps",
            "details": lint["findings"][:20],
        },
        {
            "id": "compatibility",
            "title": "HA-Kompatibilität",
            "status": _status(compatibility["counts"].get("error", 0) == 0, compatibility["counts"].get("warning", 0)),
            "message": f"{compatibility['counts'].get('error', 0)} Fehler · {compatibility['counts'].get('warning', 0)} Warnungen · {compatibility['counts'].get('tip', 0)} Tipps",
            "details": compatibility["findings"][:20],
        },
        {
            "id": "security",
            "title": "Security und Secrets",
            "status": _status(security["counts"].get("error", 0) == 0, security["counts"].get("warning", 0)),
            "message": f"{security['counts'].get('error', 0)} Fehler · {security['counts'].get('warning', 0)} Warnungen",
            "details": security["findings"][:20],
        },
        {
            "id": "entity-health",
            "title": "Entity-Health",
            "status": _status(True, entity_health["summary"].get("unknown", 0) + entity_health["summary"].get("unavailable", 0) + entity_health["summary"].get("disabled", 0)),
            "message": f"{entity_health['summary'].get('unknown', 0)} unbekannt · {entity_health['summary'].get('unavailable', 0)} unavailable · {entity_health['summary'].get('disabled', 0)} deaktiviert",
            "details": {
                "unknown": entity_health.get("unknown", [])[:10],
                "unavailable": entity_health.get("unavailable", [])[:10],
                "disabled": entity_health.get("disabled", [])[:10],
            },
        },
        {
            "id": "ha-check",
            "title": "Home-Assistant-Check",
            "status": "ok" if ha_check.get("valid") is True else "error" if ha_check.get("valid") is False else "warning",
            "message": ha_check.get("message", "Home-Assistant-API ist nicht verfügbar."),
            "details": ha_check,
        },
        {
            "id": "documentation",
            "title": "Dokumentation",
            "status": "ok" if docs.get("exists") else "warning",
            "message": docs.get("path", ""),
            "details": docs,
        },
        {
            "id": "git",
            "title": "Git Remote",
            "status": "ok" if remote.get("configured") else "warning",
            "message": remote.get("message") or ("Remote konfiguriert" if remote.get("configured") else "Kein Remote konfiguriert"),
            "details": remote,
        },
    ]
    return {
        "ready": blockers == 0,
        "status": "error" if blockers else "warning" if warnings else "ok",
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
        "summary": {
            "yamlErrors": len(validation_errors),
            "conflictErrors": conflicts["counts"].get("error", 0),
            "lintWarnings": lint["counts"].get("warning", 0),
            "compatibilityWarnings": compatibility["counts"].get("warning", 0),
            "securityErrors": security["counts"].get("error", 0),
            "warnings": warnings,
            "remoteConfigured": bool(remote.get("configured")),
        },
    }
