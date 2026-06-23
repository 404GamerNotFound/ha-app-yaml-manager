"""Discovery and editing of Home Assistant automations, scripts, and scenes."""

from __future__ import annotations

import re
from http import HTTPStatus
from pathlib import Path
from typing import Any

import yaml

try:
    from .dependencies import _walk_references, package_state_version
    from .errors import ApiError
    from .validation import HomeAssistantLoader
except ImportError:  # pragma: no cover - direct execution in the app container
    from dependencies import _walk_references, package_state_version
    from errors import ApiError
    from validation import HomeAssistantLoader


OBJECT_DOMAINS = {"automation", "script", "scene"}
DIRECTORY_TAGS = {
    "!include_dir_list",
    "!include_dir_named",
    "!include_dir_merge_list",
    "!include_dir_merge_named",
}


def _mapping_pair(node: yaml.Node | None, key: str) -> tuple[yaml.Node, yaml.Node] | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    for key_node, value_node in node.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            return key_node, value_node
    return None


def _scalar_value(node: yaml.Node, key: str) -> str:
    pair = _mapping_pair(node, key)
    return pair[1].value if pair and isinstance(pair[1], yaml.ScalarNode) else ""


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9_]+", "_", value.casefold()).strip("_")
    return result or "unbenannt"


def _safe_config_path(backend: Any, raw_path: str) -> tuple[str, Path]:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ein Ressourcenpfad ist erforderlich.")
    normalized = raw_path.strip().replace("\\", "/").lstrip("/")
    relative = Path(normalized)
    if relative.suffix.lower() not in backend.VALID_SUFFIXES:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Nur YAML-Ressourcen sind erlaubt.")
    if any(part in {"", ".", ".."} or part.startswith(".") for part in relative.parts):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der Ressourcenpfad ist ungültig.")
    root = backend.PACKAGES_ROOT.resolve().parent
    unresolved = root / relative
    if unresolved.is_symlink():
        raise ApiError(HTTPStatus.BAD_REQUEST, "Symbolische Links werden nicht bearbeitet.")
    absolute = unresolved.resolve()
    try:
        absolute.relative_to(root)
    except ValueError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der Ressourcenpfad liegt außerhalb der Konfiguration.") from exc
    return relative.as_posix(), absolute


def _included_paths(backend: Any) -> dict[str, dict[str, str]]:
    configuration = backend.configuration_file()
    try:
        content = backend.read_yaml_text(configuration)
        root = yaml.compose(content, Loader=HomeAssistantLoader)
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}
    result: dict[str, dict[str, str]] = {}
    config_root = configuration.parent.resolve()
    for domain in sorted(OBJECT_DOMAINS):
        pair = _mapping_pair(root, domain)
        if not pair or not isinstance(pair[1], yaml.ScalarNode):
            continue
        include = pair[1]
        if include.tag != "!include" and include.tag not in DIRECTORY_TAGS:
            continue
        unresolved_target = configuration.parent / include.value
        if unresolved_target.is_symlink():
            continue
        target = unresolved_target.resolve()
        try:
            target.relative_to(config_root)
        except ValueError:
            continue
        candidates = [target]
        if include.tag in DIRECTORY_TAGS:
            candidates = sorted(target.rglob("*.yaml")) if target.is_dir() else []
        for path in candidates:
            if not path.is_file() or path.is_symlink() or path.stat().st_size > backend.MAX_FILE_SIZE:
                continue
            result[path.relative_to(config_root).as_posix()] = {
                "domain": domain,
                "tag": include.tag,
            }
    return result


def managed_yaml_files(backend: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    configuration = backend.configuration_file()
    try:
        if configuration.is_file() and configuration.stat().st_size <= backend.MAX_FILE_SIZE:
            result["configuration.yaml"] = backend.read_yaml_text(configuration)
    except (OSError, UnicodeDecodeError):
        pass
    for path, content in backend.package_contents().items():
        result[f"packages/{path}"] = content
    for relative in _included_paths(backend):
        try:
            _normalized, absolute = _safe_config_path(backend, relative)
            result[relative] = backend.read_yaml_text(absolute)
        except (ApiError, OSError, UnicodeDecodeError):
            continue
    return result


def editable_resource_paths(backend: Any) -> set[str]:
    return set(_included_paths(backend))


def _object_entry(
    domain: str,
    identifier: str,
    alias: str,
    path: str,
    line: int,
    node: yaml.Node,
    editor: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if domain == "script":
        entity_id = f"script.{identifier}"
    elif domain == "scene":
        entity_id = f"scene.{_slug(identifier or alias)}"
    else:
        entity_id = f"automation.{_slug(alias or identifier)}"
    key = f"{domain}:{path}:{line}"
    entry = {
        "key": key,
        "domain": domain,
        "id": identifier,
        "entityId": entity_id,
        "alias": alias or identifier or f"{domain} in Zeile {line}",
        "path": path,
        "line": line,
        "editor": editor,
    }
    references: list[dict[str, Any]] = []
    _walk_references(node, key, path, references)
    return entry, references


def _objects_from_domain_node(
    domain: str,
    node: yaml.Node,
    path: str,
    editor: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    objects: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    if domain == "script" and isinstance(node, yaml.MappingNode):
        for key_node, definition in node.value:
            if not isinstance(key_node, yaml.ScalarNode):
                continue
            alias = _scalar_value(definition, "alias") or key_node.value
            entry, found = _object_entry(
                domain,
                key_node.value,
                alias,
                path,
                key_node.start_mark.line + 1,
                definition,
                editor,
            )
            objects.append(entry)
            references.extend(found)
    elif domain in {"automation", "scene"} and isinstance(node, yaml.SequenceNode):
        for definition in node.value:
            if not isinstance(definition, yaml.MappingNode):
                continue
            identifier = _scalar_value(definition, "id")
            alias = _scalar_value(definition, "alias") or _scalar_value(definition, "name")
            entry, found = _object_entry(
                domain,
                identifier or f"line_{definition.start_mark.line + 1}",
                alias,
                path,
                definition.start_mark.line + 1,
                definition,
                editor,
            )
            objects.append(entry)
            references.extend(found)
    elif domain in {"automation", "scene"} and isinstance(node, yaml.MappingNode):
        for key_node, definition in node.value:
            if not isinstance(key_node, yaml.ScalarNode) or not isinstance(definition, yaml.MappingNode):
                continue
            identifier = _scalar_value(definition, "id") or key_node.value
            alias = _scalar_value(definition, "alias") or _scalar_value(definition, "name") or key_node.value
            entry, found = _object_entry(
                domain,
                identifier,
                alias,
                path,
                key_node.start_mark.line + 1,
                definition,
                editor,
            )
            objects.append(entry)
            references.extend(found)
    return objects, references


def _objects_from_included_node(
    domain: str,
    node: yaml.Node,
    path: str,
    editor: str,
    tag: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if tag == "!include_dir_named" and domain == "script" and isinstance(node, yaml.MappingNode):
        identifier = Path(path).stem
        alias = _scalar_value(node, "alias") or identifier
        entry, references = _object_entry(
            domain,
            identifier,
            alias,
            path,
            node.start_mark.line + 1,
            node,
            editor,
        )
        return [entry], references
    if tag == "!include_dir_list" and domain in {"automation", "scene"} and isinstance(node, yaml.MappingNode):
        identifier = _scalar_value(node, "id") or Path(path).stem
        alias = _scalar_value(node, "alias") or _scalar_value(node, "name")
        entry, references = _object_entry(
            domain,
            identifier,
            alias,
            path,
            node.start_mark.line + 1,
            node,
            editor,
        )
        return [entry], references
    return _objects_from_domain_node(domain, node, path, editor)


def home_assistant_objects(backend: Any) -> dict[str, Any]:
    objects: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    files = managed_yaml_files(backend)
    includes = _included_paths(backend)
    for path, content in sorted(files.items()):
        try:
            documents = list(yaml.compose_all(content, Loader=HomeAssistantLoader))
        except yaml.YAMLError as exc:
            invalid.append({"path": path, "message": str(exc).split("\n", 1)[0]})
            continue
        editor = "package" if path.startswith("packages/") else "configuration" if path == "configuration.yaml" else "resource"
        include = includes.get(path)
        for document in documents:
            if document is None:
                continue
            if include:
                found, found_references = _objects_from_included_node(
                    include["domain"], document, path, editor, include["tag"]
                )
                objects.extend(found)
                references.extend(found_references)
                continue
            if not isinstance(document, yaml.MappingNode):
                continue
            for domain in OBJECT_DOMAINS:
                pair = _mapping_pair(document, domain)
                if not pair or isinstance(pair[1], yaml.ScalarNode) and pair[1].tag.startswith("!"):
                    continue
                found, found_references = _objects_from_domain_node(
                    domain, pair[1], path, editor
                )
                objects.extend(found)
                references.extend(found_references)
    entity_definitions = {item["entityId"]: item for item in objects}
    object_by_key = {item["key"]: item for item in objects}
    for reference in references:
        target = entity_definitions.get(reference["target"])
        reference["resolved"] = bool(target) if reference["type"] in {"script", "scene"} else True
        if target:
            reference["targetObject"] = target["key"]
        source = object_by_key.get(reference["source"])
        if source:
            reference["sourceObject"] = source["key"]
    for item in objects:
        item["outgoing"] = sum(ref["source"] == item["key"] for ref in references)
        item["incoming"] = sum(ref.get("targetObject") == item["key"] for ref in references)
    counts = {domain: sum(item["domain"] == domain for item in objects) for domain in OBJECT_DOMAINS}
    return {
        "objects": sorted(objects, key=lambda item: (item["domain"], item["alias"].casefold())),
        "references": references,
        "invalidFiles": invalid,
        "summary": {**counts, "references": len(references), "files": len(files)},
    }


def read_resource(backend: Any, raw_path: str) -> dict[str, Any]:
    relative, absolute = _safe_config_path(backend, raw_path)
    if relative not in editable_resource_paths(backend):
        raise ApiError(HTTPStatus.FORBIDDEN, "Diese Datei ist keine verwaltete HA-Ressource.")
    try:
        content = absolute.read_bytes()
    except FileNotFoundError as exc:
        raise ApiError(HTTPStatus.NOT_FOUND, "Die Ressourcendatei wurde nicht gefunden.") from exc
    if len(content) > backend.MAX_FILE_SIZE:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Die Ressourcendatei ist zu groß.")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Die Ressourcendatei ist nicht UTF-8-kodiert.") from exc
    return {
        "path": relative,
        "content": text,
        "version": backend.file_version(content),
        "modified": absolute.stat().st_mtime,
    }


def write_resource(
    backend: Any,
    raw_path: str,
    content: str,
    expected_version: Any,
) -> dict[str, Any]:
    relative, absolute = _safe_config_path(backend, raw_path)
    if relative not in editable_resource_paths(backend):
        raise ApiError(HTTPStatus.FORBIDDEN, "Diese Datei ist keine verwaltete HA-Ressource.")
    if not isinstance(expected_version, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Dateiversion fehlt.")
    validation = backend.validate_yaml(content)
    if not validation["valid"]:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Die Ressource enthält ungültiges YAML.", validation)
    with backend.file_lock:
        try:
            current = absolute.read_bytes()
        except FileNotFoundError as exc:
            raise ApiError(HTTPStatus.NOT_FOUND, "Die Ressourcendatei wurde nicht gefunden.") from exc
        if backend.file_version(current) != expected_version:
            raise ApiError(HTTPStatus.CONFLICT, "Die Ressource wurde zwischenzeitlich geändert.")
        backend.git_checkpoint([absolute])
        backend.create_backup(f"resources/{relative}", absolute)
        backend.atomic_write_path(absolute, content.encode("utf-8"), absolute.stat().st_mode)
        git_result = backend.git_commit_paths([absolute], f"HA-Ressource gespeichert: {relative}")
    result = read_resource(backend, relative)
    result["git"] = git_result
    result["gitSync"] = backend.auto_push_after_change(git_result)
    result["configurationCheck"] = backend.check_home_assistant_configuration()
    return result


def search_replace_plan(
    backend: Any,
    search: Any,
    replacement: Any,
    case_sensitive: Any = True,
) -> dict[str, Any]:
    if not isinstance(search, str) or not search or len(search) > 200:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der Suchtext muss 1 bis 200 Zeichen enthalten.")
    if not isinstance(replacement, str) or len(replacement) > 10_000:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der Ersetzungstext ist ungültig.")
    files = managed_yaml_files(backend)
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(re.escape(search), flags)
    changed: dict[str, str] = {}
    details: list[dict[str, Any]] = []
    total = 0
    for path, content in sorted(files.items()):
        matches = list(pattern.finditer(content))
        if not matches:
            continue
        total += len(matches)
        if total > 5000:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Die Suche liefert mehr als 5000 Treffer.")
        updated = pattern.sub(lambda _match: replacement, content)
        validation = backend.validate_yaml(updated)
        if not validation["valid"]:
            raise ApiError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                f"Die Ersetzung würde ungültiges YAML in {path} erzeugen.",
                {**validation, "path": path},
            )
        lines = sorted({content.count("\n", 0, match.start()) + 1 for match in matches})
        changed[path] = updated
        details.append({"path": path, "matches": len(matches), "lines": lines[:30]})
    return {
        "search": search,
        "replacement": replacement,
        "caseSensitive": bool(case_sensitive),
        "stateVersion": package_state_version(files),
        "files": details,
        "matches": total,
        "contents": changed,
    }


def search_replace_preview(
    backend: Any,
    search: Any,
    replacement: Any,
    case_sensitive: Any = True,
) -> dict[str, Any]:
    plan = search_replace_plan(backend, search, replacement, case_sensitive)
    return {key: value for key, value in plan.items() if key != "contents"}


def apply_search_replace(
    backend: Any,
    search: Any,
    replacement: Any,
    case_sensitive: Any,
    state_version: Any,
) -> dict[str, Any]:
    if not isinstance(state_version, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Vorschau-Version fehlt.")
    with backend.file_lock:
        plan = search_replace_plan(backend, search, replacement, case_sensitive)
        if plan["stateVersion"] != state_version:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Eine verwaltete YAML-Datei wurde seit der Vorschau geändert.",
                {"currentStateVersion": plan["stateVersion"]},
            )
        changed = plan["contents"]
        if not changed:
            raise ApiError(HTTPStatus.CONFLICT, "Es wurden keine Treffer gefunden.")
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
                    "Die Ersetzung würde neue Package-Konflikte erzeugen.",
                    {"conflicts": created},
                )
        paths = [_safe_config_path(backend, path)[1] for path in changed]
        originals = {path: path.read_bytes() for path in paths}
        modes = {path: path.stat().st_mode for path in paths}
        backend.git_checkpoint(paths)
        for path in paths:
            relative = path.relative_to(backend.PACKAGES_ROOT.resolve().parent).as_posix()
            backup_relative = (
                "configuration/configuration.yaml"
                if relative == "configuration.yaml"
                else relative.removeprefix("packages/")
                if relative.startswith("packages/")
                else f"resources/{relative}"
            )
            backend.create_backup(backup_relative, path)
        try:
            for relative, content in changed.items():
                path = _safe_config_path(backend, relative)[1]
                backend.atomic_write_path(path, content.encode("utf-8"), modes[path])
        except OSError as exc:
            for path, content in originals.items():
                backend.atomic_write_path(path, content, modes[path])
            raise ApiError(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Die Ersetzung wurde nach einem Schreibfehler zurückgerollt.",
            ) from exc
        git_result = backend.git_commit_paths(
            paths,
            f"Multi-Datei-Ersetzung: {search[:60]}",
        )
    result = {key: value for key, value in plan.items() if key != "contents"}
    result.update(
        {
            "message": f"{plan['matches']} Treffer in {len(plan['files'])} Dateien wurden ersetzt.",
            "git": git_result,
            "gitSync": backend.auto_push_after_change(git_result),
            "configurationCheck": backend.check_home_assistant_configuration(),
        }
    )
    return result
