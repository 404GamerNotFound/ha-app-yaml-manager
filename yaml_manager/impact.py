"""Pre-save impact analysis for changed package YAML."""

from __future__ import annotations

import re
from typing import Any

import yaml

try:
    from .dependencies import analyze_dependencies
    from .validation import HomeAssistantLoader
except ImportError:  # pragma: no cover - direct execution in the app container
    from dependencies import analyze_dependencies
    from validation import HomeAssistantLoader


ENTITY_PATTERN = re.compile(r"(?<![A-Za-z0-9_])([a-z0-9_]+\.[a-z0-9_]+)(?![A-Za-z0-9_])")
SECRET_PATTERN = re.compile(r"!secret\s+([A-Za-z0-9_]+)")


def _entities(content: str) -> set[str]:
    return {match.group(1) for match in ENTITY_PATTERN.finditer(content)}


def _secrets(content: str) -> set[str]:
    return set(SECRET_PATTERN.findall(content))


def _blueprints(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        if isinstance(value.get("use_blueprint"), dict):
            path = value["use_blueprint"].get("path")
            if isinstance(path, str):
                result.add(path)
        for child in value.values():
            result.update(_blueprints(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_blueprints(child))
    return result


def _load_documents(content: str) -> list[Any]:
    try:
        return list(yaml.load_all(content, Loader=HomeAssistantLoader))
    except yaml.YAMLError:
        return []


def _script_entities(graph: dict[str, Any], path: str) -> set[str]:
    return {script["entityId"] for script in graph.get("scripts", []) if script.get("path") == path}


def _path_references(graph: dict[str, Any], path: str) -> set[str]:
    return {reference["target"] for reference in graph.get("references", []) if reference.get("path") == path}


def _incoming(graph: dict[str, Any], targets: set[str], path: str) -> list[dict[str, Any]]:
    return [
        reference for reference in graph.get("references", [])
        if reference.get("target") in targets and reference.get("path") != path
    ]


def save_impact(backend: Any, body: dict[str, Any]) -> dict[str, Any]:
    path = body.get("path")
    content = body.get("content")
    if not isinstance(path, str) or not isinstance(content, str):
        raise backend.ApiError(400, "Pfad und Inhalt sind erforderlich.")
    relative, absolute = backend.normalize_relative_path(path)
    old_content = backend.read_yaml_text(absolute) if absolute.is_file() else ""
    validation = backend.validate_yaml(content)
    before_files = backend.package_contents()
    after_files = dict(before_files)
    after_files[relative] = content
    before_graph = analyze_dependencies(before_files)
    after_graph = analyze_dependencies(after_files)

    old_entities = _entities(old_content)
    new_entities = _entities(content)
    old_refs = _path_references(before_graph, relative)
    new_refs = _path_references(after_graph, relative)
    old_scripts = _script_entities(before_graph, relative)
    new_scripts = _script_entities(after_graph, relative)
    removed_scripts = old_scripts - new_scripts
    added_scripts = new_scripts - old_scripts
    incoming = _incoming(before_graph, old_scripts, relative)
    helpers = backend.cached_helper_data()
    known_entities = {
        item.get("entity_id")
        for item in helpers.get("entities", [])
        if isinstance(item, dict) and item.get("entity_id")
    }
    unknown_new = sorted(entity for entity in new_entities if known_entities and entity not in known_entities)
    old_blueprints = set().union(*(_blueprints(document) for document in _load_documents(old_content)))
    new_blueprints = set().union(*(_blueprints(document) for document in _load_documents(content)))

    findings: list[dict[str, Any]] = []
    if not validation["valid"]:
        findings.append({"severity": "error", "title": "YAML ist ungültig", "message": validation["message"]})
    if removed_scripts and incoming:
        findings.append(
            {
                "severity": "error",
                "title": "Entfernte Scripts werden noch referenziert",
                "message": f"{len(incoming)} externe Bezüge zeigen auf entfernte Script-Entities.",
            }
        )
    if unknown_new:
        findings.append(
            {
                "severity": "warning",
                "title": "Neue unbekannte Entitäten",
                "message": ", ".join(unknown_new[:6]),
            }
        )
    if old_entities != new_entities or old_refs != new_refs:
        findings.append(
            {
                "severity": "tip",
                "title": "Referenzen ändern sich",
                "message": f"{len(new_entities - old_entities)} Entities hinzugefügt, {len(old_entities - new_entities)} entfernt.",
            }
        )
    risk = "error" if any(item["severity"] == "error" for item in findings) else "warning" if any(item["severity"] == "warning" for item in findings) else "info"
    return {
        "path": relative,
        "risk": risk,
        "validation": validation,
        "summary": {
            "addedEntities": len(new_entities - old_entities),
            "removedEntities": len(old_entities - new_entities),
            "addedReferences": len(new_refs - old_refs),
            "removedReferences": len(old_refs - new_refs),
            "addedScripts": len(added_scripts),
            "removedScripts": len(removed_scripts),
            "incomingReferences": len(incoming),
            "addedSecrets": len(_secrets(content) - _secrets(old_content)),
            "removedSecrets": len(_secrets(old_content) - _secrets(content)),
            "addedBlueprints": len(new_blueprints - old_blueprints),
            "removedBlueprints": len(old_blueprints - new_blueprints),
            "traceCandidates": len(new_scripts | old_scripts),
        },
        "entities": {
            "added": sorted(new_entities - old_entities),
            "removed": sorted(old_entities - new_entities),
            "unknown": unknown_new,
        },
        "scripts": {
            "added": sorted(added_scripts),
            "removed": sorted(removed_scripts),
            "incoming": incoming[:50],
        },
        "references": {
            "added": sorted(new_refs - old_refs),
            "removed": sorted(old_refs - new_refs),
        },
        "secrets": {
            "added": sorted(_secrets(content) - _secrets(old_content)),
            "removed": sorted(_secrets(old_content) - _secrets(content)),
        },
        "blueprints": {
            "added": sorted(new_blueprints - old_blueprints),
            "removed": sorted(old_blueprints - new_blueprints),
        },
        "traces": sorted(new_scripts | old_scripts),
        "findings": findings,
    }
