"""Typed refactoring helpers beyond script and entity IDs."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any

import yaml

try:
    from .dependencies import package_state_version
    from .errors import ApiError
    from .resources import _safe_config_path
    from .validation import HomeAssistantLoader
except ImportError:  # pragma: no cover - direct execution in the app container
    from dependencies import package_state_version
    from errors import ApiError
    from resources import _safe_config_path
    from validation import HomeAssistantLoader


ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
OBJECT_ID = re.compile(r"^[a-z0-9_]+$")
DEVICE_AREA_ID = re.compile(r"^[A-Za-z0-9_-]{2,128}$")
HELPER_DOMAINS = {
    "counter",
    "input_boolean",
    "input_button",
    "input_datetime",
    "input_number",
    "input_select",
    "input_text",
    "timer",
}


@dataclass(frozen=True)
class Replacement:
    path: str
    start: int
    end: int
    value: str
    line: int


def _backup_relative(relative: str) -> str:
    if relative == "configuration.yaml":
        return "configuration/configuration.yaml"
    if relative.startswith("packages/"):
        return relative.removeprefix("packages/")
    return f"resources/{relative}"


def _token_pattern(value: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(value)}(?![A-Za-z0-9_])")


def _mapping_pair(node: yaml.Node | None, key: str) -> tuple[yaml.ScalarNode, yaml.Node] | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    for key_node, value_node in node.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            return key_node, value_node
    return None


def _top_level(node: yaml.Node | None, key: str) -> yaml.Node | None:
    pair = _mapping_pair(node, key)
    return pair[1] if pair else None


def _validate(kind: str, old_value: Any, new_value: Any) -> tuple[str, str]:
    if kind not in {"entity", "helper_entity", "scene", "automation", "device_id", "area_id", "package"}:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Unbekannter Refactoring-Typ.")
    if not isinstance(old_value, str) or not isinstance(new_value, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Alter und neuer Wert sind erforderlich.")
    old = old_value.strip()
    new = new_value.strip()
    if not old or not new or old == new:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Alter und neuer Wert müssen unterschiedlich sein.")
    if kind in {"entity", "helper_entity"}:
        if not ENTITY_ID.fullmatch(old) or not ENTITY_ID.fullmatch(new):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Entity-IDs sind ungültig.")
        if kind == "helper_entity" and (
            old.split(".", 1)[0] not in HELPER_DOMAINS or new.split(".", 1)[0] not in HELPER_DOMAINS
        ):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Helper-Refactoring ist nur für Helper-Domains erlaubt.")
    elif kind in {"scene", "automation"}:
        prefix = f"{kind}."
        old_id = old.removeprefix(prefix)
        new_id = new.removeprefix(prefix)
        if not OBJECT_ID.fullmatch(old_id) or not OBJECT_ID.fullmatch(new_id):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Objekt-IDs dürfen nur Kleinbuchstaben, Ziffern und Unterstriche enthalten.")
        old, new = f"{prefix}{old_id}", f"{prefix}{new_id}"
    elif kind in {"device_id", "area_id"}:
        if not DEVICE_AREA_ID.fullmatch(old) or not DEVICE_AREA_ID.fullmatch(new):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Device- oder Area-ID ist ungültig.")
    return old, new


def _add_replacement(
    replacements: list[Replacement],
    seen: set[tuple[str, int, int]],
    path: str,
    start: int,
    end: int,
    value: str,
    line: int,
) -> None:
    identity = (path, start, end)
    if identity in seen:
        return
    seen.add(identity)
    replacements.append(Replacement(path, start, end, value, line))


def _replace_tokens(path: str, content: str, old: str, new: str) -> list[Replacement]:
    pattern = _token_pattern(old)
    return [
        Replacement(path, match.start(), match.end(), new, content.count("\n", 0, match.start()) + 1)
        for match in pattern.finditer(content)
    ]


def _replace_keyed_scalars(path: str, content: str, keys: set[str], old: str, new: str) -> list[Replacement]:
    replacements: list[Replacement] = []
    seen: set[tuple[str, int, int]] = set()

    def visit(node: yaml.Node | None, parent_key: str = "") -> None:
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                key = key_node.value if isinstance(key_node, yaml.ScalarNode) else parent_key
                visit(value_node, str(key))
        elif isinstance(node, yaml.SequenceNode):
            for child in node.value:
                visit(child, parent_key)
        elif isinstance(node, yaml.ScalarNode) and parent_key in keys and old in node.value:
            raw = content[node.start_mark.index:node.end_mark.index]
            value = raw.replace(old, new)
            if value != raw:
                _add_replacement(
                    replacements,
                    seen,
                    path,
                    node.start_mark.index,
                    node.end_mark.index,
                    value,
                    node.start_mark.line + 1,
                )

    try:
        for document in yaml.compose_all(content, Loader=HomeAssistantLoader):
            visit(document)
    except yaml.YAMLError:
        return []
    return replacements


def _replace_object_definitions(path: str, content: str, kind: str, old: str, new: str) -> list[Replacement]:
    replacements = _replace_tokens(path, content, old, new)
    seen = {(item.path, item.start, item.end) for item in replacements}
    old_id = old.split(".", 1)[1]
    new_id = new.split(".", 1)[1]
    try:
        documents = list(yaml.compose_all(content, Loader=HomeAssistantLoader))
    except yaml.YAMLError:
        return replacements
    for document in documents:
        object_node = _top_level(document, kind)
        if isinstance(object_node, yaml.MappingNode):
            for key_node, definition in object_node.value:
                if isinstance(key_node, yaml.ScalarNode) and key_node.value == old_id:
                    raw = content[key_node.start_mark.index:key_node.end_mark.index]
                    _add_replacement(
                        replacements,
                        seen,
                        path,
                        key_node.start_mark.index,
                        key_node.end_mark.index,
                        raw.replace(old_id, new_id),
                        key_node.start_mark.line + 1,
                    )
                if isinstance(definition, yaml.MappingNode):
                    id_pair = _mapping_pair(definition, "id")
                    if id_pair and isinstance(id_pair[1], yaml.ScalarNode) and id_pair[1].value == old_id:
                        raw = content[id_pair[1].start_mark.index:id_pair[1].end_mark.index]
                        _add_replacement(
                            replacements,
                            seen,
                            path,
                            id_pair[1].start_mark.index,
                            id_pair[1].end_mark.index,
                            raw.replace(old_id, new_id),
                            id_pair[1].start_mark.line + 1,
                        )
        elif isinstance(object_node, yaml.SequenceNode):
            for definition in object_node.value:
                if not isinstance(definition, yaml.MappingNode):
                    continue
                id_pair = _mapping_pair(definition, "id")
                if id_pair and isinstance(id_pair[1], yaml.ScalarNode) and id_pair[1].value == old_id:
                    raw = content[id_pair[1].start_mark.index:id_pair[1].end_mark.index]
                    _add_replacement(
                        replacements,
                        seen,
                        path,
                        id_pair[1].start_mark.index,
                        id_pair[1].end_mark.index,
                        raw.replace(old_id, new_id),
                        id_pair[1].start_mark.line + 1,
                    )
    return replacements


def _apply_replacements(content: str, replacements: list[Replacement]) -> str:
    updated = content
    last_start = len(content) + 1
    for item in sorted(replacements, key=lambda value: value.start, reverse=True):
        if item.end > last_start:
            continue
        updated = updated[:item.start] + item.value + updated[item.end:]
        last_start = item.start
    return updated


def _content_plan(backend: Any, kind: str, old: str, new: str) -> dict[str, Any]:
    files = backend.managed_yaml_files()
    changed: dict[str, str] = {}
    details: list[dict[str, Any]] = []
    total = 0
    for path, content in sorted(files.items()):
        if kind in {"entity", "helper_entity"}:
            replacements = _replace_tokens(path, content, old, new)
        elif kind in {"scene", "automation"}:
            replacements = _replace_object_definitions(path, content, kind, old, new)
        else:
            replacements = _replace_keyed_scalars(path, content, {kind}, old, new)
        if not replacements:
            continue
        updated = _apply_replacements(content, replacements)
        validation = backend.validate_yaml(updated)
        if not validation["valid"]:
            raise ApiError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                f"Das Refactoring würde ungültiges YAML in {path} erzeugen.",
                {**validation, "path": path},
            )
        lines = sorted({item.line for item in replacements})[:30]
        total += len(replacements)
        changed[path] = updated
        details.append({"path": path, "matches": len(replacements), "lines": lines})
    return {
        "kind": kind,
        "oldValue": old,
        "newValue": new,
        "matches": total,
        "files": details,
        "stateVersion": package_state_version(files),
        "contents": changed,
    }


def _package_move_plan(backend: Any, old: str, new: str) -> dict[str, Any]:
    old_relative, old_path = backend.normalize_relative_path(old.removeprefix("packages/"))
    new_relative, new_path = backend.normalize_relative_path(new.removeprefix("packages/"))
    if old_relative == new_relative:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Alter und neuer Package-Pfad sind gleich.")
    if not old_path.is_file():
        raise ApiError(HTTPStatus.NOT_FOUND, "Die Package-Datei wurde nicht gefunden.")
    if new_path.exists():
        raise ApiError(HTTPStatus.CONFLICT, "Am neuen Package-Pfad existiert bereits eine Datei.")
    files = backend.managed_yaml_files()
    return {
        "kind": "package",
        "oldValue": old_relative,
        "newValue": new_relative,
        "matches": 1,
        "files": [{"path": old_relative, "newPath": new_relative, "matches": 1, "lines": []}],
        "stateVersion": package_state_version(files),
    }


def refactor_preview(backend: Any, kind: Any, old_value: Any, new_value: Any) -> dict[str, Any]:
    normalized_kind = str(kind or "").strip()
    old, new = _validate(normalized_kind, old_value, new_value)
    if normalized_kind == "package":
        return _package_move_plan(backend, old, new)
    plan = _content_plan(backend, normalized_kind, old, new)
    return {key: value for key, value in plan.items() if key != "contents"}


def _check_conflicts(backend: Any, changed: dict[str, str]) -> None:
    package_overlay = {
        path.removeprefix("packages/"): content
        for path, content in changed.items()
        if path.startswith("packages/")
    }
    if not package_overlay:
        return
    before = backend.package_conflict_analysis()
    after = backend.package_conflict_analysis(package_overlay)
    previous = {
        (item["code"], item["title"], tuple(item.get("files", [])))
        for item in before["findings"]
        if item["severity"] == "error"
    }
    created = [
        item
        for item in after["findings"]
        if item["severity"] == "error"
        and (item["code"], item["title"], tuple(item.get("files", []))) not in previous
    ]
    if created:
        raise ApiError(
            HTTPStatus.CONFLICT,
            "Das Refactoring würde neue Package-Konflikte erzeugen.",
            {"conflicts": created},
        )


def _apply_package_move(backend: Any, old: str, new: str, state_version: str) -> dict[str, Any]:
    with backend.file_lock:
        plan = _package_move_plan(backend, old, new)
        if plan["stateVersion"] != state_version:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Eine verwaltete YAML-Datei wurde seit der Vorschau geändert.",
                {"currentStateVersion": plan["stateVersion"]},
            )
        old_relative, old_path = backend.normalize_relative_path(plan["oldValue"])
        new_relative, new_path = backend.normalize_relative_path(plan["newValue"])
        backend.git_checkpoint([old_path, new_path])
        backend.create_backup(old_relative, old_path)
        new_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(old_path, new_path)
        git_result = backend.git_commit_paths(
            [old_path, new_path],
            f"Package verschoben: packages/{old_relative} -> packages/{new_relative}",
        )
    with backend.metadata_lock:
        metadata = backend.load_metadata()
        attributes = backend.file_metadata(metadata, old_relative)
        metadata["files"].pop(old_relative, None)
        metadata["files"][new_relative] = attributes
        backend.save_metadata(metadata)
    result = dict(plan)
    result.update(
        {
            "message": f"Package wurde nach {new_relative} verschoben.",
            "git": git_result,
            "gitSync": backend.auto_push_after_change(git_result),
        }
    )
    return result


def apply_refactor(backend: Any, kind: Any, old_value: Any, new_value: Any, state_version: Any) -> dict[str, Any]:
    if not isinstance(state_version, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Vorschau-Version fehlt.")
    normalized_kind = str(kind or "").strip()
    old, new = _validate(normalized_kind, old_value, new_value)
    if normalized_kind == "package":
        return _apply_package_move(backend, old, new, state_version)
    with backend.file_lock:
        plan = _content_plan(backend, normalized_kind, old, new)
        if plan["stateVersion"] != state_version:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Eine verwaltete YAML-Datei wurde seit der Vorschau geändert.",
                {"currentStateVersion": plan["stateVersion"]},
            )
        changed = plan["contents"]
        if not changed:
            raise ApiError(HTTPStatus.CONFLICT, "Keine passenden Referenzen gefunden.")
        _check_conflicts(backend, changed)
        paths = [_safe_config_path(backend, path)[1] for path in changed]
        originals = {path: path.read_bytes() for path in paths}
        modes = {path: path.stat().st_mode for path in paths}
        backend.git_checkpoint(paths)
        for path in paths:
            relative = path.relative_to(backend.PACKAGES_ROOT.resolve().parent).as_posix()
            backend.create_backup(_backup_relative(relative), path)
        try:
            for relative, content in changed.items():
                path = _safe_config_path(backend, relative)[1]
                backend.atomic_write_path(path, content.encode("utf-8"), modes[path])
        except OSError as exc:
            for path, content in originals.items():
                backend.atomic_write_path(path, content, modes[path])
            raise ApiError(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Das Refactoring wurde nach einem Schreibfehler zurückgerollt.",
            ) from exc
        git_result = backend.git_commit_paths(paths, f"Refactoring {normalized_kind}: {old} -> {new}")
    result = {key: value for key, value in plan.items() if key != "contents"}
    result.update(
        {
            "message": f"{plan['matches']} Treffer in {len(plan['files'])} Dateien wurden aktualisiert.",
            "git": git_result,
            "gitSync": backend.auto_push_after_change(git_result),
            "configurationCheck": backend.check_home_assistant_configuration(),
        }
    )
    return result
