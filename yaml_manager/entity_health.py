"""Entity health analysis for YAML references and live Home Assistant states."""

from __future__ import annotations

from typing import Any


BAD_STATES = {"unavailable", "unknown"}


def _state_map(helpers: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["entity_id"]: item
        for item in helpers.get("entities", [])
        if isinstance(item, dict) and item.get("entity_id")
    }


def _disabled_entities(helpers: dict[str, Any]) -> set[str]:
    registry = helpers.get("entityRegistry", [])
    return {
        str(item.get("entity_id"))
        for item in registry
        if isinstance(item, dict) and item.get("entity_id") and item.get("disabled_by")
    }


def entity_health(backend: Any) -> dict[str, Any]:
    helpers = backend.cached_helper_data()
    objects = backend.home_assistant_objects()
    references = [
        reference for reference in objects.get("references", [])
        if reference.get("type") == "entity" and isinstance(reference.get("target"), str)
    ]
    usage: dict[str, list[dict[str, Any]]] = {}
    for reference in references:
        usage.setdefault(reference["target"], []).append(
            {
                "source": reference.get("sourceObject") or reference.get("source"),
                "path": reference.get("path"),
                "line": reference.get("line"),
            }
        )
    states = _state_map(helpers)
    disabled = _disabled_entities(helpers)
    referenced = set(usage)
    known = set(states)

    unknown_items = [
        {
            "entityId": entity_id,
            "uses": usage[entity_id],
            "count": len(usage[entity_id]),
        }
        for entity_id in sorted(referenced - known - disabled, key=str.casefold)
    ]
    unavailable_items = [
        {
            "entityId": entity_id,
            "state": states[entity_id].get("state", ""),
            "name": states[entity_id].get("name", entity_id),
            "uses": usage.get(entity_id, []),
            "count": len(usage.get(entity_id, [])),
        }
        for entity_id in sorted(referenced & known, key=str.casefold)
        if str(states[entity_id].get("state", "")).casefold() in BAD_STATES
    ]
    disabled_items = [
        {
            "entityId": entity_id,
            "uses": usage.get(entity_id, []),
            "count": len(usage.get(entity_id, [])),
        }
        for entity_id in sorted(referenced & disabled, key=str.casefold)
    ]
    unused_items = [
        {
            "entityId": entity_id,
            "state": states[entity_id].get("state", ""),
            "name": states[entity_id].get("name", entity_id),
        }
        for entity_id in sorted(known - referenced, key=str.casefold)[:300]
    ]
    return {
        "available": bool(helpers.get("available")),
        "message": helpers.get("message", ""),
        "summary": {
            "referenced": len(referenced),
            "known": len(known),
            "unknown": len(unknown_items),
            "unavailable": len(unavailable_items),
            "disabled": len(disabled_items),
            "unused": len(known - referenced),
        },
        "unknown": unknown_items[:200],
        "unavailable": unavailable_items[:200],
        "disabled": disabled_items[:200],
        "unused": unused_items,
        "references": references,
    }
