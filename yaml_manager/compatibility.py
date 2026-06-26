"""Local Home Assistant compatibility and deprecation checks."""

from __future__ import annotations

from typing import Any

import yaml

try:
    from .validation import HomeAssistantLoader
except ImportError:  # pragma: no cover - direct execution in the app container
    from validation import HomeAssistantLoader


LEGACY_KEYS: dict[str, str] = {
    "data_template": "Templates werden in data: unterstuetzt; data_template ist nur noch historische Syntax.",
    "service_template": "Nutze action/service mit Template oder choose-Blöcken statt service_template.",
}
MIGRATION_KEYS: dict[tuple[str, str], str] = {
    ("automation", "action"): "Neue Automation-Beispiele verwenden haeufig actions:, action: bleibt aber weiterhin verbreitet.",
    ("automation", "trigger"): "Neue Automation-Beispiele verwenden haeufig triggers:, trigger: bleibt aber weiterhin verbreitet.",
    ("automation", "condition"): "Neue Automation-Beispiele verwenden haeufig conditions:, condition: bleibt aber weiterhin verbreitet.",
}
DEPRECATED_SERVICES: dict[str, str] = {
    "homeassistant.reload_core_config": "Dieser Dienst ist historisch. Pruefe, ob ein spezifischer Reload-Dienst passender ist.",
    "zwave.refresh_node": "Die klassische Z-Wave-Integration ist veraltet; pruefe Z-Wave JS.",
    "zwave.set_config_parameter": "Die klassische Z-Wave-Integration ist veraltet; pruefe Z-Wave JS.",
}


def _mapping_pair(node: yaml.Node | None, key: str) -> tuple[yaml.ScalarNode, yaml.Node] | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    for key_node, value_node in node.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            return key_node, value_node
    return None


def _finding(
    severity: str,
    code: str,
    title: str,
    message: str,
    path: str,
    line: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "severity": severity,
        "code": code,
        "title": title,
        "message": message,
        "files": [path],
    }
    if line:
        result["line"] = line
    return result


def _walk_keys(node: yaml.Node | None, path: str, findings: list[dict[str, Any]], domain: str = "") -> None:
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            key = key_node.value if isinstance(key_node, yaml.ScalarNode) else ""
            if key in LEGACY_KEYS:
                findings.append(
                    _finding(
                        "warning",
                        "compat-legacy-key",
                        f'Historischer Schluessel "{key}"',
                        LEGACY_KEYS[key],
                        path,
                        key_node.start_mark.line + 1,
                    )
                )
            migration_message = MIGRATION_KEYS.get((domain, key))
            if migration_message:
                findings.append(
                    _finding(
                        "tip",
                        "compat-modern-syntax",
                        f'Neue Syntaxvariante fuer "{key}" pruefen',
                        migration_message,
                        path,
                        key_node.start_mark.line + 1,
                    )
                )
            next_domain = key if key in {"automation", "script", "scene"} else domain
            _walk_keys(value_node, path, findings, next_domain)
    elif isinstance(node, yaml.SequenceNode):
        for child in node.value:
            _walk_keys(child, path, findings, domain)


def _walk_services(node: yaml.Node | None, path: str, findings: list[dict[str, Any]]) -> None:
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            key = key_node.value if isinstance(key_node, yaml.ScalarNode) else ""
            if key in {"service", "action"} and isinstance(value_node, yaml.ScalarNode):
                service_id = value_node.value.strip()
                if service_id in DEPRECATED_SERVICES:
                    findings.append(
                        _finding(
                            "warning",
                            "compat-deprecated-service",
                            f'Dienst "{service_id}" pruefen',
                            DEPRECATED_SERVICES[service_id],
                            path,
                            value_node.start_mark.line + 1,
                        )
                    )
                if key == "service":
                    findings.append(
                        _finding(
                            "tip",
                            "compat-service-action-alias",
                            "action: statt service: pruefen",
                            "Home-Assistant-Beispiele verwenden zunehmend action:. service: funktioniert, ist aber weniger einheitlich mit neuer Dokumentation.",
                            path,
                            key_node.start_mark.line + 1,
                        )
                    )
            _walk_services(value_node, path, findings)
    elif isinstance(node, yaml.SequenceNode):
        for child in node.value:
            _walk_services(child, path, findings)


def _version(backend: Any) -> dict[str, Any]:
    try:
        config = backend.home_assistant_request("config")
    except backend.ApiError as exc:
        return {"available": False, "message": exc.message}
    if not isinstance(config, dict):
        return {"available": False, "message": "Home Assistant meldete keine Konfigurationsdaten."}
    return {
        "available": True,
        "version": str(config.get("version", "")),
        "locationName": str(config.get("location_name", "")),
    }


def compatibility_findings(content: str, path: str = "") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        documents = list(yaml.compose_all(content, Loader=HomeAssistantLoader))
    except yaml.YAMLError:
        return findings
    source = path or "<editor>"
    for document in documents:
        _walk_keys(document, source, findings)
        _walk_services(document, source, findings)
    return findings


def compatibility_scan(backend: Any, files: dict[str, str] | None = None) -> dict[str, Any]:
    files = files if files is not None else backend.managed_yaml_files()
    findings: list[dict[str, Any]] = []
    for path, content in sorted(files.items()):
        findings.extend(compatibility_findings(content, path))
    order = {"error": 0, "warning": 1, "tip": 2}
    findings.sort(
        key=lambda item: (
            order.get(item.get("severity", ""), 3),
            item.get("files", [""])[0],
            item.get("line", 0),
            item.get("title", "").casefold(),
        )
    )
    counts = {
        severity: sum(item.get("severity") == severity for item in findings)
        for severity in ("error", "warning", "tip")
    }
    return {
        "homeAssistant": _version(backend),
        "findings": findings,
        "counts": counts,
        "summary": {
            "files": len(files),
            "warnings": counts["warning"],
            "tips": counts["tip"],
        },
    }
