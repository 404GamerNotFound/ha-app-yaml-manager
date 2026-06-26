"""Entity-ID refactoring across managed Home Assistant YAML files."""

from __future__ import annotations

import re
from http import HTTPStatus
from pathlib import Path
from typing import Any

try:
    from .dependencies import package_state_version
    from .errors import ApiError
    from .resources import _safe_config_path
except ImportError:  # pragma: no cover - direct execution in the app container
    from dependencies import package_state_version
    from errors import ApiError
    from resources import _safe_config_path


ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


def _entity_pattern(entity_id: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(entity_id)}(?![A-Za-z0-9_])")


def _backup_relative(relative: str) -> str:
    if relative == "configuration.yaml":
        return "configuration/configuration.yaml"
    if relative.startswith("packages/"):
        return relative.removeprefix("packages/")
    return f"resources/{relative}"


def _plan(backend: Any, old_entity: Any, new_entity: Any) -> dict[str, Any]:
    if not isinstance(old_entity, str) or not ENTITY_ID.fullmatch(old_entity):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die bisherige Entity-ID ist ungültig.")
    if not isinstance(new_entity, str) or not ENTITY_ID.fullmatch(new_entity):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die neue Entity-ID ist ungültig.")
    if old_entity == new_entity:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Entity-ID wurde nicht geändert.")
    files = backend.managed_yaml_files()
    pattern = _entity_pattern(old_entity)
    changed: dict[str, str] = {}
    details: list[dict[str, Any]] = []
    total = 0
    for path, content in sorted(files.items()):
        matches = list(pattern.finditer(content))
        if not matches:
            continue
        updated = pattern.sub(new_entity, content)
        validation = backend.validate_yaml(updated)
        if not validation["valid"]:
            raise ApiError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                f"Das Refactoring würde ungültiges YAML in {path} erzeugen.",
                {**validation, "path": path},
            )
        lines = sorted({content.count("\n", 0, match.start()) + 1 for match in matches})
        total += len(matches)
        changed[path] = updated
        details.append({"path": path, "matches": len(matches), "lines": lines[:30]})
    return {
        "oldEntity": old_entity,
        "newEntity": new_entity,
        "matches": total,
        "files": details,
        "stateVersion": package_state_version(files),
        "contents": changed,
    }


def entity_refactor_preview(backend: Any, old_entity: Any, new_entity: Any) -> dict[str, Any]:
    plan = _plan(backend, old_entity, new_entity)
    return {key: value for key, value in plan.items() if key != "contents"}


def apply_entity_refactor(backend: Any, old_entity: Any, new_entity: Any, state_version: Any) -> dict[str, Any]:
    if not isinstance(state_version, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Vorschau-Version fehlt.")
    with backend.file_lock:
        plan = _plan(backend, old_entity, new_entity)
        if plan["stateVersion"] != state_version:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Eine verwaltete YAML-Datei wurde seit der Vorschau geändert.",
                {"currentStateVersion": plan["stateVersion"]},
            )
        changed = plan["contents"]
        if not changed:
            raise ApiError(HTTPStatus.CONFLICT, "Keine Referenz auf diese Entity-ID gefunden.")
        package_overlay = {
            path.removeprefix("packages/"): content
            for path, content in changed.items()
            if path.startswith("packages/")
        }
        if package_overlay:
            before = backend.package_conflict_analysis()
            after = backend.package_conflict_analysis(package_overlay)
            previous = {
                (item["code"], item["title"], tuple(item.get("files", [])))
                for item in before["findings"] if item["severity"] == "error"
            }
            created = [
                item for item in after["findings"]
                if item["severity"] == "error"
                and (item["code"], item["title"], tuple(item.get("files", []))) not in previous
            ]
            if created:
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    "Das Refactoring würde neue Package-Konflikte erzeugen.",
                    {"conflicts": created},
                )
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
                "Das Entity-Refactoring wurde nach einem Schreibfehler zurückgerollt.",
            ) from exc
        git_result = backend.git_commit_paths(
            paths,
            f"Entity-ID refaktoriert: {plan['oldEntity']} -> {plan['newEntity']}",
        )
    result = {key: value for key, value in plan.items() if key != "contents"}
    result.update(
        {
            "message": f"{plan['matches']} Entity-Referenzen in {len(plan['files'])} Dateien wurden aktualisiert.",
            "git": git_result,
            "gitSync": backend.auto_push_after_change(git_result),
            "configurationCheck": backend.check_home_assistant_configuration(),
        }
    )
    return result
