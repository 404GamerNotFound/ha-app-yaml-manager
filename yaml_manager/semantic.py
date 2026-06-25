"""Live Home Assistant semantic checks for YAML documents."""

from __future__ import annotations

from typing import Any

import yaml

try:
    from .validation import HomeAssistantLoader
except ImportError:  # pragma: no cover - direct execution in the app container
    from validation import HomeAssistantLoader


ACTION_KEYS = {"action", "service"}
ENTITY_TARGET_KEYS = {"entity_id"}
KNOWN_ACTION_KEYS = {
    "action",
    "service",
    "target",
    "data",
    "data_template",
    "alias",
    "enabled",
    "continue_on_error",
    "response_variable",
}
GENERIC_SERVICE_DOMAINS = {
    "homeassistant",
    "notify",
    "persistent_notification",
    "logbook",
    "system_log",
    "recorder",
}


def _mapping_pair(node: yaml.Node | None, key: str) -> tuple[yaml.ScalarNode, yaml.Node] | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    for key_node, value_node in node.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            return key_node, value_node
    return None


def _scalar_text(node: yaml.Node | None) -> str:
    return node.value if isinstance(node, yaml.ScalarNode) else ""


def _split_scalar_list(value: str) -> list[str]:
    if "{{" in value or "{%" in value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _node_strings(node: yaml.Node | None) -> list[tuple[str, int]]:
    if isinstance(node, yaml.ScalarNode):
        return [(value, node.start_mark.line + 1) for value in _split_scalar_list(node.value)]
    if isinstance(node, yaml.SequenceNode):
        values: list[tuple[str, int]] = []
        for child in node.value:
            values.extend(_node_strings(child))
        return values
    return []


def _walk_mappings(node: yaml.Node | None) -> list[yaml.MappingNode]:
    result: list[yaml.MappingNode] = []
    if isinstance(node, yaml.MappingNode):
        result.append(node)
        for _key, value in node.value:
            result.extend(_walk_mappings(value))
    elif isinstance(node, yaml.SequenceNode):
        for child in node.value:
            result.extend(_walk_mappings(child))
    return result


def _walk_key_values(node: yaml.Node | None, keys: set[str]) -> list[tuple[str, int, str]]:
    result: list[tuple[str, int, str]] = []
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            if isinstance(key_node, yaml.ScalarNode) and key_node.value in keys:
                for value, line in _node_strings(value_node):
                    result.append((key_node.value, line, value))
            result.extend(_walk_key_values(value_node, keys))
    elif isinstance(node, yaml.SequenceNode):
        for child in node.value:
            result.extend(_walk_key_values(child, keys))
    return result


def _action_value(mapping: yaml.MappingNode) -> tuple[str, int] | None:
    for key in ACTION_KEYS:
        pair = _mapping_pair(mapping, key)
        if pair and isinstance(pair[1], yaml.ScalarNode):
            value = pair[1].value.strip()
            if value and "{{" not in value and "{%" not in value:
                return value, pair[1].start_mark.line + 1
    return None


def _target_values(mapping: yaml.MappingNode, key: str) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    target_pair = _mapping_pair(mapping, "target")
    if target_pair and isinstance(target_pair[1], yaml.MappingNode):
        child_pair = _mapping_pair(target_pair[1], key)
        if child_pair:
            result.extend(_node_strings(child_pair[1]))
    direct_pair = _mapping_pair(mapping, key)
    if direct_pair:
        result.extend(_node_strings(direct_pair[1]))
    return result


def _action_field_names(mapping: yaml.MappingNode) -> set[str]:
    fields: set[str] = set()
    for key_node, value_node in mapping.value:
        if not isinstance(key_node, yaml.ScalarNode):
            continue
        if key_node.value not in KNOWN_ACTION_KEYS:
            fields.add(key_node.value)
        if key_node.value in {"data", "data_template"} and isinstance(value_node, yaml.MappingNode):
            for child_key, _child_value in value_node.value:
                if isinstance(child_key, yaml.ScalarNode):
                    fields.add(child_key.value)
    return fields


def _required_service_fields(service: dict[str, Any]) -> list[str]:
    fields = service.get("fields", {})
    if not isinstance(fields, dict):
        return []
    return sorted(
        name
        for name, details in fields.items()
        if isinstance(details, dict) and details.get("required") is True
    )


def _domains_from_spec(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str)}
    return set()


def _allowed_entity_domains(service_id: str, details: dict[str, Any], known_domains: set[str]) -> set[str]:
    target = details.get("target", {}) if isinstance(details, dict) else {}
    entity = target.get("entity", {}) if isinstance(target, dict) else {}
    if isinstance(entity, dict):
        configured = _domains_from_spec(entity.get("domain"))
        if configured:
            return configured
    domain = service_id.split(".", 1)[0]
    if service_id == "script.turn_on":
        return {"script"}
    if service_id == "scene.turn_on":
        return {"scene"}
    if domain in GENERIC_SERVICE_DOMAINS:
        return set()
    if domain in known_domains:
        return {domain}
    return set()


def _service_details(helpers: dict[str, Any], service_id: str) -> dict[str, Any]:
    details = helpers.get("serviceDetails", {})
    value = details.get(service_id) if isinstance(details, dict) else {}
    return value if isinstance(value, dict) else {}


def _device_ids(helpers: dict[str, Any]) -> set[str]:
    return {
        str(item.get("id") or item.get("device_id"))
        for item in helpers.get("devices", [])
        if isinstance(item, dict) and (item.get("id") or item.get("device_id"))
    }


def _area_ids(helpers: dict[str, Any]) -> set[str]:
    return {
        str(item.get("area_id") or item.get("id"))
        for item in helpers.get("areas", [])
        if isinstance(item, dict) and (item.get("area_id") or item.get("id"))
    }


def semantic_findings(content: str, helpers: dict[str, Any]) -> list[dict[str, Any]]:
    """Return HA-aware findings for one YAML document set."""

    if not helpers.get("available"):
        return []
    services = set(helpers.get("services", []))
    entities = {
        item.get("entity_id", "")
        for item in helpers.get("entities", [])
        if isinstance(item, dict) and item.get("entity_id")
    }
    entity_domains = {entity.split(".", 1)[0] for entity in entities if "." in entity}
    devices = _device_ids(helpers)
    areas = _area_ids(helpers)
    findings: list[dict[str, Any]] = []

    try:
        nodes = list(yaml.compose_all(content, Loader=HomeAssistantLoader))
    except yaml.YAMLError:
        return findings

    seen_entities: set[tuple[str, int]] = set()
    seen_devices: set[tuple[str, int]] = set()
    seen_areas: set[tuple[str, int]] = set()
    for node in nodes:
        for _key, line, entity_id in _walk_key_values(node, ENTITY_TARGET_KEYS):
            if entity_id and entities and entity_id not in entities and (entity_id, line) not in seen_entities:
                seen_entities.add((entity_id, line))
                findings.append(
                    {
                        "severity": "warning",
                        "code": "ha-unknown-entity",
                        "title": f'Entität „{entity_id}“ nicht gefunden',
                        "message": "Diese entity_id ist im aktuellen Home-Assistant-State-Register nicht sichtbar.",
                        "line": line,
                    }
                )
        for _key, line, device_id in _walk_key_values(node, {"device_id"}):
            if devices and device_id not in devices and (device_id, line) not in seen_devices:
                seen_devices.add((device_id, line))
                findings.append(
                    {
                        "severity": "warning",
                        "code": "ha-unknown-device",
                        "title": f'Gerät „{device_id}“ nicht gefunden',
                        "message": "Diese device_id ist im Home-Assistant-Geräteregister nicht bekannt.",
                        "line": line,
                    }
                )
        for _key, line, area_id in _walk_key_values(node, {"area_id"}):
            if areas and area_id not in areas and (area_id, line) not in seen_areas:
                seen_areas.add((area_id, line))
                findings.append(
                    {
                        "severity": "warning",
                        "code": "ha-unknown-area",
                        "title": f'Bereich „{area_id}“ nicht gefunden',
                        "message": "Diese area_id ist im Home-Assistant-Bereichsregister nicht bekannt.",
                        "line": line,
                    }
                )

        for mapping in _walk_mappings(node):
            action = _action_value(mapping)
            if not action:
                continue
            service_id, line = action
            if services and service_id not in services:
                findings.append(
                    {
                        "severity": "error",
                        "code": "ha-unknown-service",
                        "title": f'Dienst „{service_id}“ nicht gefunden',
                        "message": "Dieser Dienst wird von Home Assistant aktuell nicht gemeldet.",
                        "line": line,
                    }
                )
                continue
            details = _service_details(helpers, service_id)
            provided = _action_field_names(mapping)
            for field in _required_service_fields(details):
                if field not in provided:
                    findings.append(
                        {
                            "severity": "warning",
                            "code": "ha-required-field",
                            "title": f'Pflichtfeld „{field}“ fehlt',
                            "message": f"Der Dienst {service_id} meldet dieses Feld als erforderlich.",
                            "line": line,
                        }
                    )
            allowed_domains = _allowed_entity_domains(service_id, details, entity_domains)
            if not allowed_domains:
                continue
            for entity_id, entity_line in _target_values(mapping, "entity_id"):
                entity_domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
                if entity_domain and entity_domain not in allowed_domains:
                    findings.append(
                        {
                            "severity": "warning",
                            "code": "ha-target-domain",
                            "title": f'Entität „{entity_id}“ passt nicht zu {service_id}',
                            "message": "Die Domain der Zielentität passt nicht zur erwarteten Service-Domain.",
                            "line": entity_line,
                        }
                    )
    return findings


def semantic_overview(files: dict[str, str], helpers: dict[str, Any], limit: int = 30) -> dict[str, Any]:
    """Summarize semantic findings for a managed YAML file set."""

    if not helpers.get("available"):
        return {
            "available": False,
            "status": "unavailable",
            "message": helpers.get("message", "Home-Assistant-Hilfsdaten sind nicht verfügbar."),
            "findings": [],
            "counts": {"error": 0, "warning": 0},
        }
    findings: list[dict[str, Any]] = []
    for path, content in sorted(files.items()):
        for finding in semantic_findings(content, helpers):
            findings.append({**finding, "files": [path]})
    findings.sort(key=lambda item: (item["severity"] != "error", item.get("line", 0), item["title"]))
    errors = sum(item["severity"] == "error" for item in findings)
    warnings = sum(item["severity"] == "warning" for item in findings)
    return {
        "available": True,
        "status": "error" if errors else "warning" if warnings else "ok",
        "message": (
            f"{errors} Service-Fehler · {warnings} semantische Warnungen"
            if findings
            else "Keine semantischen HA-Auffälligkeiten gefunden."
        ),
        "findings": findings[:limit],
        "truncated": len(findings) > limit,
        "counts": {"error": errors, "warning": warnings},
    }
