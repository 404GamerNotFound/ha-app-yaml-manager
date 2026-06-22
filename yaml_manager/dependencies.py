"""Build and refactor Home Assistant script dependency graphs."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

import yaml

try:
    from .validation import HomeAssistantLoader
except ImportError:  # pragma: no cover - direct execution in the app container
    from validation import HomeAssistantLoader


SCRIPT_ID_PATTERN = re.compile(r"[a-z0-9_]+")
ENTITY_ID_PATTERN = re.compile(r"(?<![A-Za-z0-9_])([a-z0-9_]+\.[a-z0-9_]+)(?![A-Za-z0-9_])")
STANDARD_ENTITY_SERVICES = {
    "script": {"reload", "turn_on", "turn_off", "toggle"},
    "scene": {"reload", "turn_on", "apply", "create", "delete"},
}


@dataclass(frozen=True)
class Replacement:
    path: str
    start: int
    end: int
    value: str


def _mapping_value(node: yaml.Node, key: str) -> yaml.Node | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    for key_node, value_node in node.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            return value_node
    return None


def _scalar_entities(node: yaml.ScalarNode, parent_key: str | None) -> list[str]:
    value = node.value
    if parent_key == "entity_id":
        return [match.group(1) for match in ENTITY_ID_PATTERN.finditer(value)]
    if parent_key in {"action", "service"}:
        result: list[str] = []
        for match in ENTITY_ID_PATTERN.finditer(value):
            entity_id = match.group(1)
            domain, object_id = entity_id.split(".", 1)
            if domain in STANDARD_ENTITY_SERVICES and object_id not in STANDARD_ENTITY_SERVICES[domain]:
                result.append(entity_id)
        return result
    if ("{{" in value or "{%" in value) and ("states" in value or "is_state" in value):
        return [match.group(1) for match in ENTITY_ID_PATTERN.finditer(value)]
    return []


def _walk_references(
    node: yaml.Node,
    source: str,
    path: str,
    result: list[dict[str, Any]],
    parent_key: str | None = None,
) -> None:
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            key = key_node.value if isinstance(key_node, yaml.ScalarNode) else None
            _walk_references(value_node, source, path, result, key)
    elif isinstance(node, yaml.SequenceNode):
        for child in node.value:
            _walk_references(child, source, path, result, parent_key)
    elif isinstance(node, yaml.ScalarNode):
        seen: set[str] = set()
        for entity_id in _scalar_entities(node, parent_key):
            if entity_id in seen:
                continue
            seen.add(entity_id)
            domain = entity_id.split(".", 1)[0]
            result.append(
                {
                    "source": source,
                    "target": entity_id,
                    "type": domain if domain in {"script", "scene"} else "entity",
                    "path": path,
                    "line": node.start_mark.line + 1,
                }
            )


def analyze_dependencies(files: dict[str, str]) -> dict[str, Any]:
    """Return definitions and references for every script in the package set."""

    scripts: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    for path, content in sorted(files.items()):
        try:
            documents = list(yaml.compose_all(content, Loader=HomeAssistantLoader))
        except yaml.YAMLError as exc:
            invalid.append({"path": path, "message": str(exc).split("\n", 1)[0]})
            continue
        for document in documents:
            script_node = _mapping_value(document, "script") if document is not None else None
            if not isinstance(script_node, yaml.MappingNode):
                continue
            for key_node, definition_node in script_node.value:
                if not isinstance(key_node, yaml.ScalarNode):
                    continue
                script_id = key_node.value
                entity_id = f"script.{script_id}"
                alias_node = _mapping_value(definition_node, "alias")
                alias = alias_node.value if isinstance(alias_node, yaml.ScalarNode) else script_id
                scripts.append(
                    {
                        "id": script_id,
                        "entityId": entity_id,
                        "alias": alias,
                        "path": path,
                        "line": key_node.start_mark.line + 1,
                    }
                )
                _walk_references(definition_node, entity_id, path, references)

    definition_ids = {script["entityId"] for script in scripts}
    for reference in references:
        reference["resolved"] = reference["type"] != "script" or reference["target"] in definition_ids
    incoming: dict[str, int] = {}
    outgoing: dict[str, int] = {}
    for reference in references:
        outgoing[reference["source"]] = outgoing.get(reference["source"], 0) + 1
        incoming[reference["target"]] = incoming.get(reference["target"], 0) + 1
    for script in scripts:
        script["incoming"] = incoming.get(script["entityId"], 0)
        script["outgoing"] = outgoing.get(script["entityId"], 0)
    return {
        "scripts": scripts,
        "references": references,
        "invalidFiles": invalid,
        "summary": {
            "scripts": len(scripts),
            "references": len(references),
            "unresolvedScripts": sum(
                reference["type"] == "script" and not reference["resolved"]
                for reference in references
            ),
        },
    }


def focus_dependencies(graph: dict[str, Any], path: str) -> dict[str, Any]:
    script_ids = {
        script["entityId"] for script in graph["scripts"] if script["path"] == path
    }
    outgoing = [item for item in graph["references"] if item["source"] in script_ids]
    incoming = [item for item in graph["references"] if item["target"] in script_ids]
    return {
        **graph,
        "focus": {
            "path": path,
            "scripts": [item for item in graph["scripts"] if item["path"] == path],
            "outgoing": outgoing,
            "incoming": incoming,
        },
    }


def package_state_version(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for path, content in sorted(files.items()):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _replacement_value(raw: str, old_entity: str, new_entity: str) -> str:
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(old_entity)}(?![A-Za-z0-9_])"
    )
    return pattern.sub(new_entity, raw)


def plan_script_rename(
    files: dict[str, str],
    path: str,
    old_id: str,
    new_id: str,
) -> dict[str, Any]:
    """Prepare exact source replacements for a script ID and its references."""

    if not SCRIPT_ID_PATTERN.fullmatch(old_id) or not SCRIPT_ID_PATTERN.fullmatch(new_id):
        raise ValueError("Script-IDs dürfen nur Kleinbuchstaben, Ziffern und Unterstriche enthalten.")
    if old_id == new_id:
        raise ValueError("Die neue Script-ID entspricht der bisherigen ID.")

    graph = analyze_dependencies(files)
    definitions = [
        script for script in graph["scripts"]
        if script["path"] == path and script["id"] == old_id
    ]
    if len(definitions) != 1:
        raise ValueError("Die umzubenennende Script-Definition wurde nicht eindeutig gefunden.")
    if any(script["entityId"] == f"script.{new_id}" for script in graph["scripts"]):
        raise ValueError(f"Die Script-ID {new_id} ist bereits vorhanden.")

    old_entity = f"script.{old_id}"
    new_entity = f"script.{new_id}"
    replacements: list[Replacement] = []
    for file_path, content in sorted(files.items()):
        try:
            documents = list(yaml.compose_all(content, Loader=HomeAssistantLoader))
        except yaml.YAMLError:
            continue
        for document in documents:
            script_node = _mapping_value(document, "script") if document is not None else None
            if isinstance(script_node, yaml.MappingNode):
                for key_node, _definition in script_node.value:
                    if (
                        file_path == path
                        and isinstance(key_node, yaml.ScalarNode)
                        and key_node.value == old_id
                    ):
                        quoted = key_node.style in {"'", '"'}
                        value = f"{key_node.style}{new_id}{key_node.style}" if quoted else new_id
                        replacements.append(
                            Replacement(file_path, key_node.start_mark.index, key_node.end_mark.index, value)
                        )

            def visit(node: yaml.Node, parent_key: str | None = None) -> None:
                if isinstance(node, yaml.MappingNode):
                    for key_node, value_node in node.value:
                        key = key_node.value if isinstance(key_node, yaml.ScalarNode) else None
                        visit(value_node, key)
                elif isinstance(node, yaml.SequenceNode):
                    for child in node.value:
                        visit(child, parent_key)
                elif isinstance(node, yaml.ScalarNode):
                    if old_entity not in _scalar_entities(node, parent_key):
                        return
                    raw = content[node.start_mark.index:node.end_mark.index]
                    value = _replacement_value(raw, old_entity, new_entity)
                    if value != raw:
                        replacements.append(
                            Replacement(file_path, node.start_mark.index, node.end_mark.index, value)
                        )

            if document is not None:
                visit(document)

    changed: dict[str, str] = {}
    details: list[dict[str, Any]] = []
    by_path: dict[str, list[Replacement]] = {}
    for replacement in replacements:
        by_path.setdefault(replacement.path, []).append(replacement)
    for file_path, items in by_path.items():
        updated = files[file_path]
        for item in sorted(items, key=lambda value: value.start, reverse=True):
            updated = updated[:item.start] + item.value + updated[item.end:]
        changed[file_path] = updated
        details.append({"path": file_path, "changes": len(items)})
    return {
        "oldId": old_id,
        "newId": new_id,
        "oldEntityId": old_entity,
        "newEntityId": new_entity,
        "stateVersion": package_state_version(files),
        "files": sorted(details, key=lambda item: item["path"]),
        "changeCount": len(replacements),
        "contents": changed,
    }
