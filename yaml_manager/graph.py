"""Global object graph for managed Home Assistant YAML."""

from __future__ import annotations

from typing import Any

import yaml

try:
    from .validation import HomeAssistantLoader
except ImportError:  # pragma: no cover - direct execution in the app container
    from validation import HomeAssistantLoader


def _node_id(kind: str, key: str) -> str:
    return f"{kind}:{key}"


def _add_node(nodes: dict[str, dict[str, Any]], kind: str, key: str, label: str, **extra: Any) -> str:
    node_id = _node_id(kind, key)
    nodes.setdefault(node_id, {"id": node_id, "type": kind, "key": key, "label": label, **extra})
    return node_id


def _add_edge(
    edges: list[dict[str, Any]],
    seen: set[tuple[str, str, str, int]],
    source: str,
    target: str,
    relation: str,
    path: str = "",
    line: int = 0,
) -> None:
    identity = (source, target, relation, line)
    if identity in seen:
        return
    seen.add(identity)
    edge: dict[str, Any] = {"source": source, "target": target, "relation": relation}
    if path:
        edge["path"] = path
    if line:
        edge["line"] = line
    edges.append(edge)


def _blueprint_paths(node: yaml.Node | None) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    if isinstance(node, yaml.MappingNode):
        use_blueprint = None
        for key_node, value_node in node.value:
            if isinstance(key_node, yaml.ScalarNode) and key_node.value == "use_blueprint":
                use_blueprint = value_node
                break
        if isinstance(use_blueprint, yaml.MappingNode):
            for key_node, value_node in use_blueprint.value:
                if (
                    isinstance(key_node, yaml.ScalarNode)
                    and key_node.value == "path"
                    and isinstance(value_node, yaml.ScalarNode)
                ):
                    result.append((value_node.value, value_node.start_mark.line + 1))
        for _key_node, value_node in node.value:
            result.extend(_blueprint_paths(value_node))
    elif isinstance(node, yaml.SequenceNode):
        for child in node.value:
            result.extend(_blueprint_paths(child))
    return result


def global_graph(backend: Any) -> dict[str, Any]:
    files = backend.managed_yaml_files()
    objects = backend.home_assistant_objects()
    security = backend.security_scan()
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str, int]] = set()

    for path in sorted(files):
        label = path.removeprefix("packages/")
        _add_node(
            nodes,
            "file",
            path,
            label,
            path=path,
            editor="package" if path.startswith("packages/") else "configuration" if path == "configuration.yaml" else "resource",
        )

    object_nodes: dict[str, str] = {}
    entity_nodes: dict[str, str] = {}
    for item in objects.get("objects", []):
        object_node = _add_node(
            nodes,
            "object",
            item["key"],
            item.get("alias") or item.get("entityId") or item["key"],
            domain=item.get("domain"),
            entityId=item.get("entityId"),
            path=item.get("path"),
            line=item.get("line"),
            editor=item.get("editor"),
        )
        object_nodes[item["key"]] = object_node
        entity_nodes[item["entityId"]] = object_node
        file_node = _add_node(nodes, "file", item["path"], item["path"], path=item["path"])
        _add_edge(edges, seen_edges, file_node, object_node, "defines", item["path"], item.get("line", 0))

    for reference in objects.get("references", []):
        source = object_nodes.get(reference.get("sourceObject") or reference.get("source", ""))
        if not source:
            source = _add_node(nodes, "file", reference.get("path", ""), reference.get("path", ""))
        target_entity = reference.get("target", "")
        target = object_nodes.get(reference.get("targetObject", "")) or entity_nodes.get(target_entity)
        if not target:
            target = _add_node(
                nodes,
                "entity",
                target_entity,
                target_entity,
                domain=target_entity.split(".", 1)[0] if "." in target_entity else "",
            )
            entity_nodes[target_entity] = target
        _add_edge(
            edges,
            seen_edges,
            source,
            target,
            reference.get("type", "reference"),
            reference.get("path", ""),
            reference.get("line", 0),
        )

    for reference in security.get("references", []):
        file_node = _add_node(nodes, "file", reference.get("path", ""), reference.get("path", ""))
        secret_node = _add_node(nodes, "secret", reference.get("name", ""), f"!secret {reference.get('name', '')}")
        _add_edge(
            edges,
            seen_edges,
            file_node,
            secret_node,
            "secret",
            reference.get("path", ""),
            reference.get("line", 0),
        )

    for path, content in sorted(files.items()):
        try:
            documents = list(yaml.compose_all(content, Loader=HomeAssistantLoader))
        except yaml.YAMLError:
            continue
        file_node = _add_node(nodes, "file", path, path)
        for document in documents:
            for blueprint_path, line in _blueprint_paths(document):
                blueprint_node = _add_node(nodes, "blueprint", blueprint_path, blueprint_path)
                _add_edge(edges, seen_edges, file_node, blueprint_node, "blueprint", path, line)

    by_type: dict[str, int] = {}
    for node in nodes.values():
        by_type[node["type"]] = by_type.get(node["type"], 0) + 1
    by_relation: dict[str, int] = {}
    for edge in edges:
        by_relation[edge["relation"]] = by_relation.get(edge["relation"], 0) + 1
    return {
        "nodes": sorted(nodes.values(), key=lambda item: (item["type"], item["label"].casefold())),
        "edges": sorted(edges, key=lambda item: (item["relation"], item.get("path", ""), item.get("line", 0))),
        "invalidFiles": objects.get("invalidFiles", []),
        "summary": {
            "nodes": len(nodes),
            "edges": len(edges),
            "byType": by_type,
            "byRelation": by_relation,
        },
    }
