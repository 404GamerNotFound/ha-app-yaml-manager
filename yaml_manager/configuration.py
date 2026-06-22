"""configuration.yaml inspection, editing, and package migration."""

from __future__ import annotations

import json
import os
import re
import tempfile
from http import HTTPStatus
from pathlib import Path
from typing import Any

import yaml

try:
    from .errors import ApiError
    from .validation import HomeAssistantLoader
except ImportError:  # pragma: no cover - direct execution in the app container
    from errors import ApiError
    from validation import HomeAssistantLoader


def bind(backend: Any) -> None:
    """Refresh runtime paths and callbacks exposed by the application facade."""

    names = (
        "DIRECTORY_INCLUDE_TAGS",
        "MAX_FILE_SIZE",
        "PACKAGES_ROOT",
        "PACKAGE_DIRECTORY_TAGS",
        "VALID_SUFFIXES",
        "check_home_assistant_configuration",
        "create_backup",
        "file_lock",
        "file_version",
        "git_checkpoint",
        "git_commit_paths",
        "update_file_metadata",
        "validate_yaml",
    )
    globals().update({name: getattr(backend, name) for name in names})


def configuration_file() -> Path:
    override = os.environ.get("CONFIGURATION_PATH")
    if override:
        return Path(override).resolve()
    return PACKAGES_ROOT.resolve().parent / "configuration.yaml"


def mapping_value(node: yaml.Node | None, key: str) -> yaml.Node | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    for key_node, value_node in node.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            return value_node
    return None


def compose_yaml(path: Path) -> yaml.Node | None:
    if path.stat().st_size > MAX_FILE_SIZE:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Die Konfigurationsdatei ist groesser als 2 MiB.")
    return yaml.compose(path.read_text(encoding="utf-8"), Loader=HomeAssistantLoader)


def resolve_include(value: str, base_directory: Path) -> Path:
    return (base_directory / value.strip()).resolve()


def package_node_uses_directory(
    node: yaml.Node | None,
    base_directory: Path,
    expected_directory: Path,
    visited: set[Path],
) -> bool:
    if not isinstance(node, yaml.ScalarNode):
        return False
    target = resolve_include(node.value, base_directory)
    if node.tag in PACKAGE_DIRECTORY_TAGS:
        return target == expected_directory
    if node.tag != "!include" or target in visited or not target.is_file():
        return False
    visited.add(target)
    return package_node_uses_directory(compose_yaml(target), target.parent, expected_directory, visited)


def homeassistant_node_uses_packages(
    node: yaml.Node | None,
    base_directory: Path,
    expected_directory: Path,
    visited: set[Path],
) -> bool:
    packages_node = mapping_value(node, "packages")
    if packages_node is not None:
        return package_node_uses_directory(packages_node, base_directory, expected_directory, visited)

    if not isinstance(node, yaml.ScalarNode):
        return False
    target = resolve_include(node.value, base_directory)
    if node.tag == "!include" and target not in visited and target.is_file():
        visited.add(target)
        return homeassistant_node_uses_packages(
            compose_yaml(target), target.parent, expected_directory, visited
        )
    if node.tag in DIRECTORY_INCLUDE_TAGS and target.is_dir():
        for candidate in sorted(target.iterdir()):
            if candidate.suffix.lower() not in VALID_SUFFIXES or not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if resolved in visited:
                continue
            visited.add(resolved)
            if homeassistant_node_uses_packages(
                compose_yaml(resolved), resolved.parent, expected_directory, visited
            ):
                return True
    return False


def package_configuration_status() -> dict[str, Any]:
    path = configuration_file()
    expected_directory = PACKAGES_ROOT.resolve()
    expected = "homeassistant:\n  packages: !include_dir_named packages"
    result: dict[str, Any] = {
        "configured": False,
        "status": "missing",
        "configuration": str(path),
        "expected": expected,
    }
    if not path.is_file():
        result["status"] = "unavailable"
        result["message"] = "configuration.yaml wurde nicht gefunden."
        return result
    try:
        root = compose_yaml(path)
        homeassistant = mapping_value(root, "homeassistant")
        if homeassistant_node_uses_packages(homeassistant, path.parent, expected_directory, {path}):
            result.update(
                {
                    "configured": True,
                    "status": "configured",
                    "message": "Der Ordner /config/packages ist in configuration.yaml eingebunden.",
                }
            )
        else:
            result["message"] = "Der Ordner /config/packages ist nicht über homeassistant.packages eingebunden."
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ApiError) as exc:
        result["status"] = "invalid"
        result["message"] = f"configuration.yaml konnte nicht geprüft werden: {exc}"
    return result


def read_configuration() -> dict[str, Any]:
    path = configuration_file()
    try:
        content = path.read_bytes()
    except FileNotFoundError as exc:
        raise ApiError(HTTPStatus.NOT_FOUND, "configuration.yaml wurde nicht gefunden.") from exc
    if len(content) > MAX_FILE_SIZE:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "configuration.yaml ist groesser als 2 MiB.")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "configuration.yaml ist nicht UTF-8-kodiert.") from exc
    return {
        "path": "/config/configuration.yaml",
        "content": text,
        "version": file_version(content),
        "modified": path.stat().st_mtime,
        "packages": package_configuration_status(),
    }


def atomic_write_path(path: Path, content: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_configuration(content: str, expected_version: str | None) -> dict[str, Any]:
    if not isinstance(expected_version, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Dateiversion fehlt. Bitte configuration.yaml neu laden.")
    validation = validate_yaml(content)
    if not validation["valid"]:
        raise ApiError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "configuration.yaml enthaelt einen Syntaxfehler.",
            validation,
        )
    path = configuration_file()
    encoded = content.encode("utf-8")
    with file_lock:
        try:
            current = path.read_bytes()
        except FileNotFoundError as exc:
            raise ApiError(HTTPStatus.NOT_FOUND, "configuration.yaml wurde nicht gefunden.") from exc
        if file_version(current) != expected_version:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "configuration.yaml wurde zwischenzeitlich geaendert. Bitte neu laden.",
                {"currentVersion": file_version(current)},
            )
        git_checkpoint([path])
        create_backup("configuration/configuration.yaml", path)
        atomic_write_path(path, encoded, path.stat().st_mode)
        git_result = git_commit_paths([path], "configuration.yaml gespeichert")
    result = read_configuration()
    result["configurationCheck"] = check_home_assistant_configuration()
    result["git"] = git_result
    return result


def mapping_pair(node: yaml.Node | None, key: str) -> tuple[yaml.Node, yaml.Node] | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    for key_node, value_node in node.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            return key_node, value_node
    return None


def insert_line_after_node(content: str, node: yaml.Node, line: str) -> str:
    position = node.end_mark.index
    if position > 0 and content[position - 1] == "\n":
        return content[:position] + line + "\n" + content[position:]
    position = content.find("\n", position)
    if position == -1:
        return content.rstrip() + "\n" + line + "\n"
    position += 1
    return content[:position] + line + "\n" + content[position:]


def package_mode(node: yaml.Node, base_directory: Path) -> str | None:
    if not isinstance(node, yaml.ScalarNode):
        return None
    target = resolve_include(node.value, base_directory)
    if target != PACKAGES_ROOT.resolve():
        return None
    if node.tag == "!include_dir_named":
        return "named"
    if node.tag == "!include_dir_merge_named":
        return "merge_named"
    return None


def add_packages_to_mapping(
    content: str,
    mapping: yaml.MappingNode,
    base_directory: Path,
    indentation: int,
) -> tuple[str, str]:
    existing = mapping_pair(mapping, "packages")
    if existing:
        mode = package_mode(existing[1], base_directory)
        if mode:
            return content, mode
        raise ApiError(
            HTTPStatus.CONFLICT,
            "Es existiert bereits eine andere homeassistant.packages-Konfiguration. Sie wurde nicht ueberschrieben.",
        )
    if mapping.flow_style:
        raise ApiError(
            HTTPStatus.CONFLICT,
            "Eine einzeilige homeassistant-Konfiguration kann nicht automatisch erweitert werden.",
        )
    if mapping.value:
        content = insert_line_after_node(
            content,
            mapping.value[-1][1],
            " " * indentation + "packages: !include_dir_named packages",
        )
    else:
        content = content.rstrip() + "\n" + " " * indentation + "packages: !include_dir_named packages\n"
    return content, "named"


def prepare_package_enable(content: str) -> tuple[dict[Path, tuple[bytes, bytes]], str]:
    validation = validate_yaml(content)
    if not validation["valid"]:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "configuration.yaml ist nicht gueltig.", validation)
    path = configuration_file()
    root = yaml.compose(content, Loader=HomeAssistantLoader)
    if not isinstance(root, yaml.MappingNode):
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "configuration.yaml muss ein YAML-Objekt enthalten.")
    pair = mapping_pair(root, "homeassistant")
    changes: dict[Path, tuple[bytes, bytes]] = {}

    if pair is None:
        updated = content.rstrip() + "\n\nhomeassistant:\n  packages: !include_dir_named packages\n"
        changes[path] = (path.read_bytes(), updated.encode("utf-8"))
        return changes, "named"

    key_node, homeassistant = pair
    if isinstance(homeassistant, yaml.MappingNode):
        updated, mode = add_packages_to_mapping(content, homeassistant, path.parent, 2)
        current = path.read_bytes()
        if updated.encode("utf-8") != current:
            changes[path] = (current, updated.encode("utf-8"))
        return changes, mode

    if isinstance(homeassistant, yaml.ScalarNode) and homeassistant.tag == "!include":
        included = resolve_include(homeassistant.value, path.parent)
        try:
            included_bytes = included.read_bytes()
            included_content = included_bytes.decode("utf-8")
            included_root = yaml.compose(included_content, Loader=HomeAssistantLoader)
        except FileNotFoundError as exc:
            raise ApiError(HTTPStatus.NOT_FOUND, f"Eingebundene Datei {homeassistant.value} wurde nicht gefunden.") from exc
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Die eingebundene homeassistant-Datei ist nicht gueltig.") from exc
        if not isinstance(included_root, yaml.MappingNode):
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Die eingebundene homeassistant-Datei muss ein YAML-Objekt enthalten.")
        updated, mode = add_packages_to_mapping(included_content, included_root, included.parent, 0)
        if updated != included_content:
            changes[included] = (included_bytes, updated.encode("utf-8"))
        if content.encode("utf-8") != path.read_bytes():
            changes[path] = (path.read_bytes(), content.encode("utf-8"))
        return changes, mode

    if isinstance(homeassistant, yaml.ScalarNode) and homeassistant.tag == "tag:yaml.org,2002:null":
        updated = insert_line_after_node(content, key_node, "  packages: !include_dir_named packages")
        changes[path] = (path.read_bytes(), updated.encode("utf-8"))
        return changes, "named"

    raise ApiError(
        HTTPStatus.CONFLICT,
        "Die vorhandene homeassistant-Konfiguration kann nicht automatisch erweitert werden.",
    )


def enable_packages(content: str, expected_version: str | None) -> dict[str, Any]:
    if not isinstance(expected_version, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Dateiversion fehlt. Bitte configuration.yaml neu laden.")
    main_path = configuration_file()
    with file_lock:
        current_main = main_path.read_bytes()
        if file_version(current_main) != expected_version:
            raise ApiError(HTTPStatus.CONFLICT, "configuration.yaml wurde zwischenzeitlich geaendert. Bitte neu laden.")
        changes, mode = prepare_package_enable(content)
        for path, (old, new) in changes.items():
            if path.read_bytes() != old:
                raise ApiError(HTTPStatus.CONFLICT, f"{path.name} wurde zwischenzeitlich geaendert. Bitte neu laden.")
            validation = validate_yaml(new.decode("utf-8"))
            if not validation["valid"]:
                raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, f"Die erzeugte Datei {path.name} ist nicht gueltig.", validation)
        git_checkpoint(list(changes))
        applied: list[Path] = []
        try:
            for path, (_old, new) in changes.items():
                create_backup(f"configuration/{path.name}", path)
                atomic_write_path(path, new, path.stat().st_mode)
                applied.append(path)
        except OSError as exc:
            for path in reversed(applied):
                old = changes[path][0]
                atomic_write_path(path, old, path.stat().st_mode)
            raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "Der Package-Import konnte nicht atomar gespeichert werden.") from exc
        git_result = git_commit_paths(list(changes), "Package-Einbindung aktualisiert")
    result = read_configuration()
    result.update(
        {
            "mode": mode,
            "message": "Package-Import wurde in der Home-Assistant-Konfiguration eingetragen.",
            "configurationCheck": check_home_assistant_configuration(),
            "git": git_result,
        }
    )
    return result


def homeassistant_package_mode(
    node: yaml.Node | None,
    base_directory: Path,
    visited: set[Path],
) -> str | None:
    existing = mapping_pair(node, "packages")
    if existing:
        return package_mode(existing[1], base_directory)
    if not isinstance(node, yaml.ScalarNode) or node.tag != "!include":
        return None
    target = resolve_include(node.value, base_directory)
    if target in visited or not target.is_file():
        return None
    visited.add(target)
    return homeassistant_package_mode(compose_yaml(target), target.parent, visited)


def configuration_package_mode(content: str) -> str | None:
    root = yaml.compose(content, Loader=HomeAssistantLoader)
    pair = mapping_pair(root, "homeassistant")
    if not pair:
        return None
    path = configuration_file()
    return homeassistant_package_mode(pair[1], path.parent, {path})


def collect_include_nodes(node: yaml.Node | None, result: list[yaml.ScalarNode]) -> None:
    if isinstance(node, yaml.ScalarNode) and node.tag.startswith("!include"):
        result.append(node)
    elif isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            collect_include_nodes(key_node, result)
            collect_include_nodes(value_node, result)
    elif isinstance(node, yaml.SequenceNode):
        for child in node.value:
            collect_include_nodes(child, result)


def render_include_node(node: yaml.ScalarNode, value: str) -> str:
    if node.style == "'":
        rendered = "'" + value.replace("'", "''") + "'"
    elif node.style == '"' or re.search(r"[\s:#{}\[\],&*?]", value):
        rendered = json.dumps(value, ensure_ascii=False)
    else:
        rendered = value
    return f"{node.tag} {rendered}"


def rewrite_section_includes(
    content: str,
    section_start: int,
    section_end: int,
    value_node: yaml.Node,
    source_directory: Path,
    destination_directory: Path,
) -> str:
    block = content[section_start:section_end]
    include_nodes: list[yaml.ScalarNode] = []
    collect_include_nodes(value_node, include_nodes)
    edits: list[tuple[int, int, str]] = []
    for node in include_nodes:
        raw_path = node.value.strip()
        if not raw_path or Path(raw_path).is_absolute():
            continue
        target = (source_directory / raw_path).resolve()
        relative = os.path.relpath(target, destination_directory).replace(os.sep, "/")
        edits.append(
            (
                node.start_mark.index - section_start,
                node.end_mark.index - section_start,
                render_include_node(node, relative),
            )
        )
    for start, end, replacement in sorted(edits, reverse=True):
        block = block[:start] + replacement + block[end:]
    return block


def prepare_configuration_migration(
    content: str,
    package_name: str = "configuration_import",
    require_enabled: bool = False,
) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9_]+", package_name):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der Package-Name darf nur Kleinbuchstaben, Ziffern und Unterstriche enthalten.")
    validation = validate_yaml(content)
    if not validation["valid"]:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "configuration.yaml ist nicht gueltig.", validation)
    root = yaml.compose(content, Loader=HomeAssistantLoader)
    if not isinstance(root, yaml.MappingNode):
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "configuration.yaml muss ein YAML-Objekt enthalten.")

    mode = configuration_package_mode(content)
    if require_enabled and not mode:
        raise ApiError(HTTPStatus.CONFLICT, "Packages muessen vor der Migration eingebunden werden.")
    mode = mode or "named"
    target = PACKAGES_ROOT.resolve() / f"{package_name}.yaml"
    pairs = root.value
    components: list[str] = []
    moved_blocks: list[str] = []
    kept_blocks: list[str] = []
    first_start = pairs[0][0].start_mark.index if pairs else len(content)
    preamble = content[:first_start]

    for index, (key_node, value_node) in enumerate(pairs):
        if not isinstance(key_node, yaml.ScalarNode):
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Komplexe Top-Level-Schluessel koennen nicht migriert werden.")
        start = key_node.start_mark.index
        end = pairs[index + 1][0].start_mark.index if index + 1 < len(pairs) else len(content)
        block = content[start:end]
        if key_node.value == "homeassistant":
            kept_blocks.append(block)
            continue
        components.append(key_node.value)
        moved_blocks.append(
            rewrite_section_includes(
                content,
                start,
                end,
                value_node,
                configuration_file().parent,
                target.parent,
            )
        )

    if not components:
        raise ApiError(HTTPStatus.CONFLICT, "Es gibt keine auslagerbaren Top-Level-Bereiche.")

    package_body = "".join(moved_blocks).strip() + "\n"
    if mode == "merge_named":
        indented = "".join(f"  {line}\n" if line else "\n" for line in package_body.splitlines())
        package_body = f"{package_name}:\n{indented}"
    package_content = (
        "# Automatisch aus configuration.yaml ausgelagert.\n"
        "# Bearbeitung und Wiederherstellung sind über den YAML Script Manager möglich.\n\n"
        + package_body
    )
    remaining = (preamble + "".join(kept_blocks)).rstrip() + "\n"
    return {
        "packageName": package_name,
        "target": f"/config/packages/{package_name}.yaml",
        "targetPath": target,
        "targetExists": target.exists(),
        "mode": mode,
        "components": components,
        "componentCount": len(components),
        "configurationContent": remaining,
        "packageContent": package_content,
    }


def configuration_migration_preview(content: str, package_name: str) -> dict[str, Any]:
    prepared = prepare_configuration_migration(content, package_name)
    return {
        key: value
        for key, value in prepared.items()
        if key not in {"targetPath", "configurationContent", "packageContent"}
    }


def migrate_configuration(
    content: str,
    expected_version: str | None,
    package_name: str,
) -> dict[str, Any]:
    if not isinstance(expected_version, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Dateiversion fehlt. Bitte configuration.yaml neu laden.")
    prepared = prepare_configuration_migration(content, package_name, require_enabled=True)
    target: Path = prepared["targetPath"]
    if target.exists():
        raise ApiError(HTTPStatus.CONFLICT, f"{target.name} existiert bereits. Die Migration wurde nicht ausgefuehrt.")
    configuration = configuration_file()
    new_configuration = prepared["configurationContent"].encode("utf-8")
    new_package = prepared["packageContent"].encode("utf-8")

    if not validate_yaml(new_configuration.decode("utf-8"))["valid"]:
        raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "Die erzeugte configuration.yaml ist nicht gueltig.")
    if not validate_yaml(new_package.decode("utf-8"))["valid"]:
        raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "Das erzeugte Package ist nicht gueltig.")

    with file_lock:
        original = configuration.read_bytes()
        if file_version(original) != expected_version:
            raise ApiError(HTTPStatus.CONFLICT, "configuration.yaml wurde zwischenzeitlich geaendert. Bitte neu laden.")
        git_checkpoint([configuration, target])
        create_backup("configuration/configuration.yaml", configuration)
        try:
            atomic_write_path(configuration, new_configuration, configuration.stat().st_mode)
            atomic_write_path(target, new_package)
        except OSError as exc:
            atomic_write_path(configuration, original, configuration.stat().st_mode)
            if target.exists():
                target.unlink()
            raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "Die Migration konnte nicht atomar gespeichert werden.") from exc
        git_result = git_commit_paths(
            [configuration, target],
            f"Konfiguration nach packages/{target.name} migriert",
        )

    update_file_metadata(target.name, "Konfiguration", ["migration", "configuration"])
    result = read_configuration()
    result.update(
        {
            "message": f'{prepared["componentCount"]} Bereiche wurden nach {prepared["target"]} ausgelagert.',
            "package": prepared["target"],
            "components": prepared["components"],
            "configurationCheck": check_home_assistant_configuration(),
            "git": git_result,
        }
    )
    return result


