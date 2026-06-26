"""Visual flow extraction for Home Assistant automations and scripts."""

from __future__ import annotations

from typing import Any

import yaml

try:
    from .errors import ApiError
    from .validation import HomeAssistantLoader
except ImportError:  # pragma: no cover - direct execution in the app container
    from errors import ApiError
    from validation import HomeAssistantLoader


def _pair(node: yaml.Node | None, key: str) -> tuple[yaml.ScalarNode, yaml.Node] | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    for key_node, value_node in node.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            return key_node, value_node
    return None


def _scalar(node: yaml.Node | None) -> str:
    return node.value if isinstance(node, yaml.ScalarNode) else ""


def _line(node: yaml.Node | None) -> int:
    return node.start_mark.line + 1 if node is not None else 0


def _sequence_items(node: yaml.Node | None) -> list[yaml.Node]:
    if isinstance(node, yaml.SequenceNode):
        return list(node.value)
    if isinstance(node, yaml.MappingNode):
        return [node]
    return []


def _mapping_label(node: yaml.MappingNode) -> tuple[str, str, str]:
    action = _scalar((_pair(node, "action") or _pair(node, "service") or (None, None))[1])
    if action:
        target = _target_detail(node)
        return "service", action, target
    condition = _scalar((_pair(node, "condition") or (None, None))[1])
    if condition:
        return "condition", f"Bedingung: {condition}", _condition_detail(node)
    if _pair(node, "choose"):
        return "choose", "Choose-Zweig", "Bedingte Verzweigung"
    if _pair(node, "repeat"):
        return "repeat", "Wiederholung", _repeat_detail((_pair(node, "repeat") or (None, None))[1])
    if _pair(node, "if"):
        return "branch", "If/Then", "Bedingter Ablauf"
    if _pair(node, "delay"):
        return "delay", "Verzögerung", _scalar((_pair(node, "delay") or (None, None))[1]) or "delay"
    if _pair(node, "wait_template"):
        return "wait", "Warten auf Template", _scalar((_pair(node, "wait_template") or (None, None))[1])
    if _pair(node, "wait_for_trigger"):
        return "wait", "Warten auf Trigger", "wait_for_trigger"
    if _pair(node, "event"):
        return "event", f"Event: {_scalar((_pair(node, 'event') or (None, None))[1])}", "event"
    if _pair(node, "variables"):
        return "variables", "Variablen", "variables"
    if _pair(node, "stop"):
        return "stop", "Stop", _scalar((_pair(node, "stop") or (None, None))[1])
    return "step", "YAML-Schritt", "Mapping"


def _target_detail(node: yaml.MappingNode) -> str:
    target = (_pair(node, "target") or (None, None))[1]
    if isinstance(target, yaml.MappingNode):
        entity = _scalar((_pair(target, "entity_id") or (None, None))[1])
        device = _scalar((_pair(target, "device_id") or (None, None))[1])
        area = _scalar((_pair(target, "area_id") or (None, None))[1])
        return entity or device or area
    entity = _scalar((_pair(node, "entity_id") or (None, None))[1])
    return entity


def _condition_detail(node: yaml.MappingNode) -> str:
    entity = _scalar((_pair(node, "entity_id") or (None, None))[1])
    state = _scalar((_pair(node, "state") or (None, None))[1])
    value = _scalar((_pair(node, "value_template") or (None, None))[1])
    return " · ".join(item for item in (entity, state, value) if item)[:180]


def _repeat_detail(node: yaml.Node | None) -> str:
    if not isinstance(node, yaml.MappingNode):
        return ""
    for key in ("count", "while", "until", "for_each"):
        value = _pair(node, key)
        if value:
            return key
    return "sequence"


def _append_node(
    flow: dict[str, Any],
    kind: str,
    label: str,
    detail: str,
    line: int,
    depth: int,
    parent: str | None = None,
) -> str:
    node_id = f"n{len(flow['nodes']) + 1}"
    flow["nodes"].append(
        {
            "id": node_id,
            "type": kind,
            "label": label,
            "detail": detail,
            "line": line,
            "depth": depth,
            "parent": parent,
        }
    )
    if parent:
        flow["edges"].append({"source": parent, "target": node_id})
    elif len(flow["nodes"]) > 1:
        previous = flow["nodes"][-2]["id"]
        flow["edges"].append({"source": previous, "target": node_id})
    return node_id


def _walk_steps(flow: dict[str, Any], node: yaml.Node | None, depth: int = 0, parent: str | None = None) -> None:
    last_parent = parent
    for child in _sequence_items(node):
        if not isinstance(child, yaml.MappingNode):
            if isinstance(child, yaml.ScalarNode):
                last_parent = _append_node(flow, "step", child.value[:80], "", _line(child), depth, last_parent)
            continue
        kind, label, detail = _mapping_label(child)
        current = _append_node(flow, kind, label, detail, _line(child), depth, last_parent)
        last_parent = current
        if kind == "choose":
            choose_node = (_pair(child, "choose") or (None, None))[1]
            for index, choice in enumerate(_sequence_items(choose_node), start=1):
                branch = _append_node(flow, "branch", f"Choose {index}", "", _line(choice), depth + 1, current)
                if isinstance(choice, yaml.MappingNode):
                    conditions = (_pair(choice, "conditions") or (None, None))[1]
                    sequence = (_pair(choice, "sequence") or (None, None))[1]
                    if conditions:
                        _walk_steps(flow, conditions, depth + 2, branch)
                    _walk_steps(flow, sequence, depth + 2, branch)
            default = (_pair(child, "default") or (None, None))[1]
            if default:
                branch = _append_node(flow, "branch", "Default", "", _line(default), depth + 1, current)
                _walk_steps(flow, default, depth + 2, branch)
        elif kind == "repeat":
            repeat = (_pair(child, "repeat") or (None, None))[1]
            sequence = (_pair(repeat, "sequence")[1] if isinstance(repeat, yaml.MappingNode) and _pair(repeat, "sequence") else None)
            _walk_steps(flow, sequence, depth + 1, current)
        elif kind == "branch":
            then_node = (_pair(child, "then") or (None, None))[1]
            else_node = (_pair(child, "else") or (None, None))[1]
            _walk_steps(flow, then_node, depth + 1, _append_node(flow, "branch", "Then", "", _line(then_node), depth + 1, current))
            if else_node:
                _walk_steps(flow, else_node, depth + 1, _append_node(flow, "branch", "Else", "", _line(else_node), depth + 1, current))


def _script_flows(document: yaml.Node | None, path: str) -> list[dict[str, Any]]:
    script_node = (_pair(document, "script") or (None, None))[1]
    if not isinstance(script_node, yaml.MappingNode):
        return []
    flows: list[dict[str, Any]] = []
    for key_node, definition in script_node.value:
        if not isinstance(key_node, yaml.ScalarNode) or not isinstance(definition, yaml.MappingNode):
            continue
        alias = _scalar((_pair(definition, "alias") or (None, None))[1]) or key_node.value
        flow = {
            "id": f"script.{key_node.value}",
            "domain": "script",
            "alias": alias,
            "path": path,
            "line": _line(key_node),
            "nodes": [],
            "edges": [],
        }
        _append_node(flow, "start", f"Script: {alias}", f"script.{key_node.value}", _line(key_node), 0)
        sequence = (_pair(definition, "sequence") or (None, None))[1]
        _walk_steps(flow, sequence, 0, flow["nodes"][0]["id"])
        flows.append(flow)
    return flows


def _automation_flows(document: yaml.Node | None, path: str) -> list[dict[str, Any]]:
    automation_node = (_pair(document, "automation") or (None, None))[1]
    if automation_node is None:
        return []
    definitions = _sequence_items(automation_node) if isinstance(automation_node, yaml.SequenceNode) else _sequence_items(automation_node)
    flows: list[dict[str, Any]] = []
    for index, definition in enumerate(definitions, start=1):
        if not isinstance(definition, yaml.MappingNode):
            continue
        identifier = _scalar((_pair(definition, "id") or (None, None))[1]) or f"line_{_line(definition)}"
        alias = _scalar((_pair(definition, "alias") or (None, None))[1]) or identifier
        flow = {
            "id": f"automation.{identifier}",
            "domain": "automation",
            "alias": alias,
            "path": path,
            "line": _line(definition),
            "nodes": [],
            "edges": [],
        }
        root = _append_node(flow, "start", f"Automation: {alias}", identifier, _line(definition), 0)
        trigger = (_pair(definition, "triggers") or _pair(definition, "trigger") or (None, None))[1]
        if trigger:
            branch = _append_node(flow, "trigger", "Trigger", f"{len(_sequence_items(trigger)) or 1} Auslöser", _line(trigger), 0, root)
            _walk_steps(flow, trigger, 1, branch)
        conditions = (_pair(definition, "conditions") or _pair(definition, "condition") or (None, None))[1]
        if conditions:
            branch = _append_node(flow, "condition", "Bedingungen", f"{len(_sequence_items(conditions)) or 1} Bedingungen", _line(conditions), 0, flow["nodes"][-1]["id"])
            _walk_steps(flow, conditions, 1, branch)
        actions = (_pair(definition, "actions") or _pair(definition, "action") or (None, None))[1]
        if actions:
            branch = _append_node(flow, "actions", "Aktionen", f"{len(_sequence_items(actions)) or 1} Schritte", _line(actions), 0, flow["nodes"][-1]["id"])
            _walk_steps(flow, actions, 1, branch)
        flows.append(flow)
    return flows


def flow_analysis(_backend: Any, body: dict[str, Any]) -> dict[str, Any]:
    content = body.get("content")
    path = body.get("path") if isinstance(body.get("path"), str) else ""
    if not isinstance(content, str):
        raise ApiError(400, "YAML-Inhalt ist erforderlich.")
    try:
        documents = list(yaml.compose_all(content, Loader=HomeAssistantLoader))
    except yaml.YAMLError as exc:
        return {
            "valid": False,
            "message": str(exc).split("\n", 1)[0],
            "flows": [],
            "summary": {"flows": 0, "nodes": 0, "edges": 0},
        }
    flows: list[dict[str, Any]] = []
    for document in documents:
        flows.extend(_script_flows(document, path))
        flows.extend(_automation_flows(document, path))
    return {
        "valid": True,
        "flows": flows,
        "summary": {
            "flows": len(flows),
            "nodes": sum(len(flow["nodes"]) for flow in flows),
            "edges": sum(len(flow["edges"]) for flow in flows),
        },
    }
