"""Persistent category and tag metadata for managed package files."""

from __future__ import annotations

import json
import os
import re
import tempfile
from typing import Any


def sanitize_tags(tags: Any) -> list[str]:
    """Normalize user-supplied tags while preserving display casing."""

    if not isinstance(tags, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in tags:
        if not isinstance(value, str):
            continue
        tag = re.sub(r"\s+", " ", value).strip()[:40]
        folded = tag.casefold()
        if tag and folded not in seen:
            cleaned.append(tag)
            seen.add(folded)
        if len(cleaned) == 12:
            break
    return cleaned


def load_metadata(backend: Any) -> dict[str, Any]:
    with backend.metadata_lock:
        try:
            data = json.loads(backend.METADATA_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            data = {}
        return {
            "categories": list(data.get("categories", [])),
            "files": dict(data.get("files", {})),
        }


def file_metadata(backend: Any, metadata: dict[str, Any], relative: str) -> dict[str, Any]:
    value = metadata.get("files", {}).get(relative, backend.DEFAULT_CATEGORY)
    if isinstance(value, str):
        return {"category": value or backend.DEFAULT_CATEGORY, "tags": []}
    if not isinstance(value, dict):
        return {"category": backend.DEFAULT_CATEGORY, "tags": []}
    category = value.get("category", backend.DEFAULT_CATEGORY)
    tags = value.get("tags", [])
    return {
        "category": (
            category
            if isinstance(category, str) and category
            else backend.DEFAULT_CATEGORY
        ),
        "tags": sanitize_tags(tags),
    }


def save_metadata(backend: Any, metadata: dict[str, Any]) -> None:
    with backend.metadata_lock:
        backend.DATA_ROOT.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix="metadata-",
            suffix=".json",
            dir=backend.DATA_ROOT,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(metadata, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, backend.METADATA_FILE)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
