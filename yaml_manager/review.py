"""Stateless review bundles for grouped YAML changes."""

from __future__ import annotations

import difflib
from http import HTTPStatus
from pathlib import Path
from typing import Any

try:
    from .dependencies import package_state_version
    from .errors import ApiError
    from .resources import _safe_config_path, editable_resource_paths
except ImportError:  # pragma: no cover - direct execution in the app container
    from dependencies import package_state_version
    from errors import ApiError
    from resources import _safe_config_path, editable_resource_paths


def _backup_relative(relative: str) -> str:
    if relative == "configuration.yaml":
        return "configuration/configuration.yaml"
    if relative.startswith("packages/"):
        return relative.removeprefix("packages/")
    return f"resources/{relative}"


def _canonical_path(backend: Any, raw_path: Any, existing_files: dict[str, str]) -> str:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ApiError(HTTPStatus.BAD_REQUEST, "Jede Änderung braucht einen Pfad.")
    normalized = raw_path.strip().replace("\\", "/").lstrip("/")
    if normalized == "configuration.yaml":
        return normalized
    if normalized.startswith("packages/"):
        relative, _absolute = backend.normalize_relative_path(normalized.removeprefix("packages/"))
        return f"packages/{relative}"
    if normalized in existing_files or normalized in editable_resource_paths(backend):
        _safe_config_path(backend, normalized)
        return normalized
    relative, _absolute = backend.normalize_relative_path(normalized)
    return f"packages/{relative}"


def _absolute_path(backend: Any, path: str) -> Path:
    if path == "configuration.yaml":
        return backend.configuration_file()
    if path.startswith("packages/"):
        return backend.normalize_relative_path(path.removeprefix("packages/"))[1]
    if path not in editable_resource_paths(backend):
        raise ApiError(HTTPStatus.FORBIDDEN, "Diese HA-Ressource ist nicht direkt verwaltet.")
    return _safe_config_path(backend, path)[1]


def _diff(old: str, new: str, path: str) -> tuple[str, int, int]:
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    diff = "\n".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
            n=4,
        )
    )
    additions = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
    return diff, additions, deletions


def _changes(backend: Any, body: dict[str, Any], existing_files: dict[str, str]) -> list[dict[str, Any]]:
    raw_changes = body.get("changes")
    if not isinstance(raw_changes, list) or not raw_changes:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ein Änderungspaket braucht mindestens eine Änderung.")
    if len(raw_changes) > 100:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Ein Änderungspaket darf maximal 100 Dateien enthalten.")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_changes:
        if not isinstance(raw, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Jede Änderung muss ein Objekt sein.")
        path = _canonical_path(backend, raw.get("path"), existing_files)
        if path in seen:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"{path} ist mehrfach im Änderungspaket enthalten.")
        seen.add(path)
        operation = raw.get("operation", "upsert")
        if operation not in {"upsert", "delete"}:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Unbekannte Änderungsart.")
        if operation == "delete" and not path.startswith("packages/"):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Löschen im Review-Modus ist nur für Package-Dateien erlaubt.")
        content = raw.get("content", "")
        if operation == "upsert":
            if not isinstance(content, str):
                raise ApiError(HTTPStatus.BAD_REQUEST, f"{path}: Inhalt fehlt.")
            if len(content.encode("utf-8")) > backend.MAX_FILE_SIZE:
                raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"{path}: Inhalt ist zu groß.")
        result.append(
            {
                "path": path,
                "operation": operation,
                "content": content if operation == "upsert" else "",
                "category": raw.get("category"),
                "tags": raw.get("tags"),
            }
        )
    return result


def _package_overlay(before_files: dict[str, str], after_files: dict[str, str]) -> dict[str, str | None]:
    overlay: dict[str, str | None] = {}
    before_packages = {
        path.removeprefix("packages/")
        for path in before_files
        if path.startswith("packages/")
    }
    after_packages = {
        path.removeprefix("packages/"): content
        for path, content in after_files.items()
        if path.startswith("packages/")
    }
    for relative in before_packages - set(after_packages):
        overlay[relative] = None
    overlay.update(after_packages)
    return overlay


def _plan(backend: Any, body: dict[str, Any]) -> dict[str, Any]:
    existing_files = backend.managed_yaml_files()
    changes = _changes(backend, body, existing_files)
    after_files = dict(existing_files)
    details: list[dict[str, Any]] = []
    validation_errors: list[dict[str, Any]] = []
    for change in changes:
        path = change["path"]
        old = existing_files.get(path, "")
        if change["operation"] == "delete":
            if path not in existing_files:
                raise ApiError(HTTPStatus.NOT_FOUND, f"{path} existiert nicht.")
            after_files.pop(path, None)
            diff, additions, deletions = _diff(old, "", path)
            validation = {"valid": True, "message": "Datei wird gelöscht."}
            action = "delete"
        else:
            content = change["content"]
            validation = backend.validate_yaml(content)
            if not validation["valid"]:
                validation_errors.append({"path": path, **validation})
            after_files[path] = content
            diff, additions, deletions = _diff(old, content, path)
            action = "update" if path in existing_files else "create"
        details.append(
            {
                "path": path,
                "operation": change["operation"],
                "action": action,
                "exists": path in existing_files,
                "additions": additions,
                "deletions": deletions,
                "diff": diff,
                "validation": validation,
            }
        )

    conflicts = backend.package_conflict_analysis(_package_overlay(existing_files, after_files))
    lint = backend.lint_scan(after_files)
    compatibility = backend.compatibility_scan(after_files)
    blockers = (
        len(validation_errors)
        + conflicts["counts"].get("error", 0)
        + lint["counts"].get("error", 0)
        + compatibility["counts"].get("error", 0)
    )
    warnings = (
        conflicts["counts"].get("warning", 0)
        + lint["counts"].get("warning", 0)
        + compatibility["counts"].get("warning", 0)
    )
    return {
        "changes": changes,
        "files": details,
        "stateVersion": package_state_version(existing_files),
        "ready": blockers == 0,
        "status": "error" if blockers else "warning" if warnings else "ok",
        "blockers": blockers,
        "warnings": warnings,
        "summary": {
            "changes": len(changes),
            "creates": sum(item["action"] == "create" for item in details),
            "updates": sum(item["action"] == "update" for item in details),
            "deletes": sum(item["action"] == "delete" for item in details),
            "additions": sum(item["additions"] for item in details),
            "deletions": sum(item["deletions"] for item in details),
        },
        "checks": {
            "validation": {"errors": validation_errors},
            "conflicts": conflicts,
            "lint": lint,
            "compatibility": compatibility,
        },
    }


def review_preview(backend: Any, body: dict[str, Any]) -> dict[str, Any]:
    plan = _plan(backend, body)
    return {key: value for key, value in plan.items() if key != "changes"}


def apply_review(backend: Any, body: dict[str, Any]) -> dict[str, Any]:
    expected_version = body.get("stateVersion")
    if not isinstance(expected_version, str) or not expected_version:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Review-Vorschau-Version fehlt.")
    with backend.file_lock:
        plan = _plan(backend, body)
        if plan["stateVersion"] != expected_version:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Eine verwaltete YAML-Datei wurde seit der Review-Vorschau geändert.",
                {"currentStateVersion": plan["stateVersion"]},
            )
        if not plan["ready"]:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Das Änderungspaket enthält noch Blocker.", plan["checks"])
        changes = plan["changes"]
        paths = [_absolute_path(backend, change["path"]) for change in changes]
        originals = {path: path.read_bytes() if path.exists() else None for path in paths}
        modes = {path: path.stat().st_mode if path.exists() else 0o644 for path in paths}
        backend.git_checkpoint(paths)
        for change, path in zip(changes, paths, strict=True):
            if originals[path] is not None:
                backend.create_backup(_backup_relative(change["path"]), path)
        try:
            for change, path in zip(changes, paths, strict=True):
                if change["operation"] == "delete":
                    path.unlink()
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                backend.atomic_write_path(path, change["content"].encode("utf-8"), modes[path])
        except OSError as exc:
            for path, original in originals.items():
                if original is None:
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
                else:
                    backend.atomic_write_path(path, original, modes[path])
            raise ApiError(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Das Änderungspaket wurde nach einem Schreibfehler zurückgerollt.",
            ) from exc
        git_result = backend.git_commit_paths(paths, f"Review-Paket angewendet: {len(changes)} Dateien")

    for change in changes:
        if not change["path"].startswith("packages/"):
            continue
        package_path = change["path"].removeprefix("packages/")
        if change["operation"] == "delete":
            with backend.metadata_lock:
                metadata = backend.load_metadata()
                metadata["files"].pop(package_path, None)
                backend.save_metadata(metadata)
            continue
        if change.get("category") is not None or change.get("tags") is not None:
            backend.update_file_metadata(
                package_path,
                str(change.get("category") or backend.DEFAULT_CATEGORY),
                change.get("tags"),
            )
    result = {key: value for key, value in plan.items() if key != "changes"}
    result.update(
        {
            "message": f"{len(changes)} Dateien wurden als Review-Paket angewendet.",
            "git": git_result,
            "gitSync": backend.auto_push_after_change(git_result),
            "configurationCheck": backend.check_home_assistant_configuration(),
        }
    )
    return result
