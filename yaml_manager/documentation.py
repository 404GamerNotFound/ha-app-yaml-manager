"""Markdown documentation generation for managed Home Assistant YAML."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any


def _cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    if not rows:
        return ["_Keine Einträge._", ""]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _header in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_cell(value) for value in row) + " |")
    lines.append("")
    return lines


def documentation_overview(backend: Any) -> dict[str, Any]:
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    files = backend.list_files()["files"]
    objects = backend.home_assistant_objects()
    references = objects["references"]
    entity_references = sorted(
        {reference["target"] for reference in references if reference.get("type") == "entity"},
        key=str.casefold,
    )
    object_references = [
        reference
        for reference in references
        if reference.get("type") in {"script", "scene"}
    ]
    commits = backend.recent_git_commits(10)
    conflicts = backend.package_conflict_analysis()
    entity_usage: dict[str, list[dict[str, Any]]] = {}
    for reference in references:
        if reference.get("type") != "entity":
            continue
        entity_usage.setdefault(reference["target"], []).append(
            {
                "source": reference.get("sourceObject") or reference.get("source"),
                "path": reference.get("path"),
                "line": reference.get("line"),
            }
        )
    graph_edges = [
        {
            "source": reference.get("sourceObject") or reference.get("source"),
            "target": reference.get("targetObject") or reference.get("target"),
            "targetLabel": reference.get("target"),
            "type": reference.get("type"),
            "resolved": reference.get("resolved"),
            "path": reference.get("path"),
            "line": reference.get("line"),
        }
        for reference in object_references
    ]

    lines: list[str] = [
        "# Home Assistant YAML Dokumentation",
        "",
        f"Generiert: {generated_at}",
        "",
        "## Übersicht",
        "",
        f"- Package-Dateien: {len(files)}",
        f"- Automationen: {objects['summary'].get('automation', 0)}",
        f"- Scripts: {objects['summary'].get('script', 0)}",
        f"- Szenen: {objects['summary'].get('scene', 0)}",
        f"- Erkannte Bezüge: {objects['summary'].get('references', 0)}",
        f"- Genutzte Entitäten: {len(entity_references)}",
        f"- Package-Konflikte: {conflicts['counts'].get('error', 0)} Fehler, {conflicts['counts'].get('warning', 0)} Warnungen",
        "",
        "## Package-Dateien",
        "",
    ]
    lines.extend(
        _table(
            ["Pfad", "Kategorie", "Tags", "Größe"],
            [
                [
                    item["path"],
                    item.get("category", ""),
                    ", ".join(item.get("tags", [])),
                    item.get("size", 0),
                ]
                for item in files
            ],
        )
    )

    lines.extend(["## Automationen, Scripts und Szenen", ""])
    lines.extend(
        _table(
            ["Typ", "Name", "Entity-ID", "Quelle", "Zeile"],
            [
                [
                    item["domain"],
                    item["alias"],
                    item["entityId"],
                    item["path"],
                    item["line"],
                ]
                for item in objects["objects"]
            ],
        )
    )

    lines.extend(["## Script- und Szenenbezüge", ""])
    lines.extend(
        _table(
            ["Quelle", "Ziel", "Datei", "Zeile", "Status"],
            [
                [
                    reference.get("sourceObject") or reference.get("source"),
                    reference["target"],
                    reference["path"],
                    reference.get("line", ""),
                    "aufgelöst" if reference.get("resolved") else "offen",
                ]
                for reference in object_references
            ],
        )
    )

    lines.extend(["## Genutzte Entitäten", ""])
    entity_rows = [[entity] for entity in entity_references]
    lines.extend(_table(["Entity-ID"], entity_rows))

    lines.extend(["## Auffälligkeiten", ""])
    lines.extend(
        _table(
            ["Schwere", "Titel", "Dateien"],
            [
                [
                    finding["severity"],
                    finding["title"],
                    ", ".join(finding.get("files", [])),
                ]
                for finding in conflicts["findings"][:50]
            ],
        )
    )

    lines.extend(["## Letzte Git-Änderungen", ""])
    lines.extend(
        _table(
            ["Commit", "Zeitpunkt", "Nachricht"],
            [
                [commit["shortId"], commit["created"], commit["subject"]]
                for commit in commits
            ],
        )
    )

    content = "\n".join(lines).rstrip() + "\n"
    return {
        "generatedAt": generated_at,
        "content": content,
        "data": {
            "files": files,
            "objects": objects["objects"],
            "references": references,
            "graph": graph_edges,
            "entities": [
                {
                    "entityId": entity,
                    "domain": entity.split(".", 1)[0] if "." in entity else "",
                    "count": len(entity_usage.get(entity, [])),
                    "uses": entity_usage.get(entity, []),
                }
                for entity in entity_references
            ],
            "findings": conflicts["findings"][:100],
            "commits": commits,
        },
        "summary": {
            "files": len(files),
            "automations": objects["summary"].get("automation", 0),
            "scripts": objects["summary"].get("script", 0),
            "scenes": objects["summary"].get("scene", 0),
            "references": objects["summary"].get("references", 0),
            "entities": len(entity_references),
            "conflicts": conflicts["counts"].get("error", 0),
            "warnings": conflicts["counts"].get("warning", 0),
            "commits": len(commits),
        },
    }


def documentation_status(backend: Any) -> dict[str, Any]:
    path = backend.DATA_ROOT / "documentation" / "packages.md"
    return {
        "exists": path.is_file(),
        "path": str(path),
        "modified": path.stat().st_mtime if path.is_file() else None,
        "size": path.stat().st_size if path.is_file() else 0,
    }


def write_documentation(backend: Any) -> dict[str, Any]:
    result = documentation_overview(backend)
    path = backend.DATA_ROOT / "documentation" / "packages.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    backend.atomic_write_path(path, result["content"].encode("utf-8"), 0o644)
    return {**result, "path": str(Path(path))}
