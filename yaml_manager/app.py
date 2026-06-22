"""HTTP backend for the Home Assistant YAML Script Manager."""

from __future__ import annotations

import argparse
import base64
import binascii
import difflib
import hashlib
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml


PORT = int(os.environ.get("PORT", "8099"))
PACKAGES_ROOT = Path(os.environ.get("PACKAGES_PATH", "/homeassistant/packages")).resolve()
DATA_ROOT = Path(os.environ.get("DATA_PATH", "/data")).resolve()
STATIC_ROOT = Path(__file__).parent / "static"
METADATA_FILE = DATA_ROOT / "metadata.json"
GIT_REMOTE_FILE = DATA_ROOT / "git_remote.json"
GIT_REMOTE_NAME = "yaml-manager"
GIT_ASKPASS = Path(__file__).parent / "git_askpass.py"
MAX_FILE_SIZE = 2 * 1024 * 1024
MAX_IMPORT_SIZE = 10 * 1024 * 1024
MAX_IMPORT_EXPANDED_SIZE = 50 * 1024 * 1024
MAX_IMPORT_FILES = 500
VALID_SUFFIXES = {".yaml", ".yml"}
DEFAULT_CATEGORY = "Ohne Kategorie"
PACKAGE_DIRECTORY_TAGS = {"!include_dir_named", "!include_dir_merge_named"}
DIRECTORY_INCLUDE_TAGS = {
    "!include_dir_list",
    "!include_dir_named",
    "!include_dir_merge_list",
    "!include_dir_merge_named",
}

metadata_lock = threading.RLock()
file_lock = threading.RLock()
git_lock = threading.RLock()


class ApiError(Exception):
    def __init__(self, status: int, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details or {}


class HomeAssistantLoader(yaml.SafeLoader):
    """Safe YAML loader that accepts Home Assistant's custom tags."""


def _construct_mapping(loader: HomeAssistantLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            if key in result:
                raise yaml.MarkedYAMLError(
                    context="Doppelter YAML-Schluessel",
                    context_mark=key_node.start_mark,
                    problem=str(key),
                    problem_mark=key_node.start_mark,
                )
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found unhashable key",
                key_node.start_mark,
            ) from exc
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


def _construct_unknown(loader: HomeAssistantLoader, _suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


HomeAssistantLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)
HomeAssistantLoader.add_multi_constructor("!", _construct_unknown)


def ensure_directories() -> None:
    PACKAGES_ROOT.mkdir(parents=True, exist_ok=True)
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    (DATA_ROOT / "backups").mkdir(exist_ok=True)
    (DATA_ROOT / "trash").mkdir(exist_ok=True)


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def load_metadata() -> dict[str, Any]:
    with metadata_lock:
        try:
            data = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            data = {}
        return {
            "categories": list(data.get("categories", [])),
            "files": dict(data.get("files", {})),
        }


def file_metadata(metadata: dict[str, Any], relative: str) -> dict[str, Any]:
    value = metadata.get("files", {}).get(relative, DEFAULT_CATEGORY)
    if isinstance(value, str):
        return {"category": value or DEFAULT_CATEGORY, "tags": []}
    if not isinstance(value, dict):
        return {"category": DEFAULT_CATEGORY, "tags": []}
    category = value.get("category", DEFAULT_CATEGORY)
    tags = value.get("tags", [])
    return {
        "category": category if isinstance(category, str) and category else DEFAULT_CATEGORY,
        "tags": sanitize_tags(tags),
    }


def sanitize_tags(tags: Any) -> list[str]:
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


def save_metadata(metadata: dict[str, Any]) -> None:
    with metadata_lock:
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="metadata-", suffix=".json", dir=DATA_ROOT)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(metadata, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, METADATA_FILE)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def normalize_relative_path(raw_path: str) -> tuple[str, Path]:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ein Dateipfad ist erforderlich.")
    normalized = raw_path.strip().replace("\\", "/").lstrip("/")
    relative = Path(normalized)
    if relative.suffix.lower() not in VALID_SUFFIXES:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Nur .yaml- und .yml-Dateien sind erlaubt.")
    if any(part in {"", ".", ".."} or part.startswith(".") for part in relative.parts):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der Dateipfad ist ungueltig.")
    packages_root = PACKAGES_ROOT.resolve()
    absolute = (packages_root / relative).resolve()
    try:
        absolute.relative_to(packages_root)
    except ValueError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der Dateipfad liegt ausserhalb von packages.") from exc
    return relative.as_posix(), absolute


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


class GitOperationError(Exception):
    pass


def git_root() -> Path:
    return PACKAGES_ROOT.parent.resolve()


def git_relative_path(path: Path) -> str:
    root = git_root()
    try:
        relative = path.resolve().relative_to(root)
    except ValueError as exc:
        raise GitOperationError("Der Git-Pfad liegt außerhalb der Home-Assistant-Konfiguration.") from exc
    if not relative.parts or ".git" in relative.parts:
        raise GitOperationError("Dieser Pfad darf nicht mit Git versioniert werden.")
    return relative.as_posix()


def run_git(
    arguments: list[str],
    allowed_codes: tuple[int, ...] = (0,),
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    root = git_root()
    command = ["git", "-c", f"safe.directory={root}", "-C", str(root), *arguments]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=45 if environment else 15,
            check=False,
            env=environment,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise GitOperationError("Git ist in der App nicht verfügbar.") from exc
    if result.returncode not in allowed_codes:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise GitOperationError(error or "Git-Befehl fehlgeschlagen.")
    return result


def git_has_head() -> bool:
    return run_git(["rev-parse", "--verify", "HEAD"], allowed_codes=(0, 128)).returncode == 0


def git_commit_staged(message: str, relative_paths: list[str]) -> dict[str, Any]:
    changed = run_git(
        ["diff", "--cached", "--quiet", "--", *relative_paths],
        allowed_codes=(0, 1),
    ).returncode == 1
    if not changed:
        return {"available": True, "committed": False, "message": "Keine Git-Änderungen vorhanden."}
    run_git(
        [
            "-c", "user.name=YAML Script Manager",
            "-c", "user.email=yaml-script-manager@local",
            "commit", "--no-gpg-sign", "--no-verify", "--only", "-m", message, "--", *relative_paths,
        ]
    )
    commit = run_git(["rev-parse", "HEAD"]).stdout.decode("ascii").strip()
    return {"available": True, "committed": True, "commit": commit, "message": message}


def ensure_git_repository() -> dict[str, Any]:
    root = git_root()
    root.mkdir(parents=True, exist_ok=True)
    created = not (root / ".git").exists()
    if created:
        run_git(["init"])
    if not git_has_head():
        baseline = [path for path in (root / "configuration.yaml", PACKAGES_ROOT) if path.exists()]
        if baseline:
            relative_paths = [git_relative_path(path) for path in baseline]
            run_git(["add", "-A", "-f", "--", *relative_paths])
            git_commit_staged("Ausgangsstand des YAML Script Managers", relative_paths)
        if not git_has_head():
            run_git(
                [
                    "-c", "user.name=YAML Script Manager",
                    "-c", "user.email=yaml-script-manager@local",
                    "commit", "--no-gpg-sign", "--no-verify", "--allow-empty", "-m",
                    "Leerer Ausgangsstand des YAML Script Managers",
                ]
            )
    return {"available": True, "initialized": created}


def git_commit_paths(paths: list[Path], message: str) -> dict[str, Any]:
    with git_lock:
        try:
            ensure_git_repository()
            relative_paths = sorted({git_relative_path(path) for path in paths})
            if not relative_paths:
                return {"available": True, "committed": False, "message": "Keine Git-Pfade angegeben."}
            run_git(["add", "-A", "-f", "--", *relative_paths])
            return git_commit_staged(message, relative_paths)
        except GitOperationError as exc:
            return {"available": False, "committed": False, "message": str(exc)}


def git_checkpoint(paths: list[Path]) -> dict[str, Any]:
    return git_commit_paths(paths, "Zwischenstand vor Änderung durch den YAML Script Manager")


def public_git_remote_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "configured": bool(config.get("url")),
        "url": config.get("url", ""),
        "provider": config.get("provider", ""),
        "branch": config.get("branch", "main"),
        "username": config.get("username", ""),
        "tokenConfigured": bool(config.get("token")),
        "lastSync": config.get("lastSync"),
    }


def load_git_remote_config() -> dict[str, Any]:
    try:
        value = json.loads(GIT_REMOTE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def validate_git_remote_url(raw_url: Any) -> tuple[str, str]:
    if not isinstance(raw_url, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Eine Git-Remote-URL ist erforderlich.")
    url = raw_url.strip()
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Nur HTTPS-URLs ohne eingebettete Zugangsdaten sind erlaubt.")
    host = (parsed.hostname or "").lower()
    if host == "github.com":
        provider = "github"
    elif host == "gitlab.com":
        provider = "gitlab"
    else:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Es sind ausschließlich github.com und gitlab.com erlaubt.")
    if not re.fullmatch(r"/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+/?", parsed.path):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Repository-URL ist ungültig.")
    return urllib.parse.urlunsplit(("https", host, parsed.path.rstrip("/"), "", "")), provider


def validate_git_branch(raw_branch: Any) -> str:
    if not isinstance(raw_branch, str) or not raw_branch.strip():
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ein Git-Branch ist erforderlich.")
    branch = raw_branch.strip()
    if len(branch) > 128 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", branch):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der Git-Branch ist ungültig.")
    if any(value in branch for value in ("..", "//", "@{")) or branch.endswith(("/", ".", ".lock")):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der Git-Branch ist ungültig.")
    return branch


def save_git_remote_file(config: dict[str, Any]) -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    atomic_write_path(GIT_REMOTE_FILE, encoded, 0o600)


def configure_git_remote(url: str) -> None:
    current = run_git(["remote", "get-url", GIT_REMOTE_NAME], allowed_codes=(0, 2))
    if current.returncode == 0:
        run_git(["remote", "set-url", GIT_REMOTE_NAME, url])
    else:
        run_git(["remote", "add", GIT_REMOTE_NAME, url])


def git_remote_environment(config: dict[str, Any]) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_ASKPASS": str(GIT_ASKPASS),
            "GIT_TERMINAL_PROMPT": "0",
            "YAML_MANAGER_GIT_USERNAME": str(config.get("username", "")),
            "YAML_MANAGER_GIT_TOKEN": str(config.get("token", "")),
        }
    )
    return environment


def run_git_remote(
    arguments: list[str],
    config: dict[str, Any],
    allowed_codes: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[bytes]:
    return run_git(arguments, allowed_codes=allowed_codes, environment=git_remote_environment(config))


def git_ahead_behind(branch: str) -> tuple[int, int]:
    reference = f"refs/remotes/{GIT_REMOTE_NAME}/{branch}"
    exists = run_git(["show-ref", "--verify", "--quiet", reference], allowed_codes=(0, 1)).returncode == 0
    if not exists:
        return 0, 0
    output = run_git(["rev-list", "--left-right", "--count", f"HEAD...{reference}"]).stdout.decode().strip()
    ahead, behind = (int(value) for value in output.split())
    return ahead, behind


def git_remote_status() -> dict[str, Any]:
    config = load_git_remote_config()
    result = public_git_remote_config(config)
    if not result["configured"]:
        return {**result, "available": True, "ahead": 0, "behind": 0, "dirty": False}
    with git_lock:
        try:
            ensure_git_repository()
            configure_git_remote(config["url"])
            ahead, behind = git_ahead_behind(config["branch"])
            dirty = bool(
                run_git(["status", "--porcelain", "--", "configuration.yaml", "packages"]).stdout.strip()
            )
            branch_result = run_git(["symbolic-ref", "--short", "HEAD"], allowed_codes=(0, 1))
            current_branch = branch_result.stdout.decode().strip() if branch_result.returncode == 0 else "detached"
            return {
                **result,
                "available": True,
                "ahead": ahead,
                "behind": behind,
                "dirty": dirty,
                "currentBranch": current_branch,
            }
        except GitOperationError as exc:
            return {**result, "available": False, "message": str(exc), "ahead": 0, "behind": 0, "dirty": False}


def update_git_remote(body: dict[str, Any]) -> dict[str, Any]:
    url, provider = validate_git_remote_url(body.get("url"))
    branch = validate_git_branch(body.get("branch", "main"))
    existing = load_git_remote_config()
    raw_token = body.get("token")
    token = existing.get("token", "") if raw_token in (None, "") else raw_token
    if body.get("clearToken"):
        token = ""
    if not isinstance(token, str) or len(token) > 512 or any(char in token for char in "\r\n\0"):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Das Git-Token ist ungültig.")
    username = body.get("username") or existing.get("username") or ("x-access-token" if provider == "github" else "oauth2")
    if not isinstance(username, str) or not re.fullmatch(r"[^\s:@/]{1,128}", username):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der Git-Benutzername ist ungültig.")
    config = {
        "url": url,
        "provider": provider,
        "branch": branch,
        "username": username,
        "token": token,
        "lastSync": existing.get("lastSync"),
    }
    with git_lock:
        try:
            ensure_git_repository()
            configure_git_remote(url)
        except GitOperationError as exc:
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, str(exc)) from exc
        save_git_remote_file(config)
    return git_remote_status()


def remove_git_remote() -> dict[str, Any]:
    with git_lock:
        try:
            if (git_root() / ".git").exists():
                run_git(["remote", "remove", GIT_REMOTE_NAME], allowed_codes=(0, 2))
        except GitOperationError as exc:
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, str(exc)) from exc
        try:
            GIT_REMOTE_FILE.unlink()
        except FileNotFoundError:
            pass
    return git_remote_status()


def prepare_remote_fast_forward(branch: str) -> list[str]:
    reference = f"refs/remotes/{GIT_REMOTE_NAME}/{branch}"
    changed = run_git(["diff", "--name-only", "HEAD", reference]).stdout.decode("utf-8", errors="replace").splitlines()
    for relative in changed:
        if relative == "configuration.yaml":
            absolute = configuration_file()
            backup_relative = "configuration/configuration.yaml"
        elif relative.startswith("packages/"):
            package_relative = relative.removeprefix("packages/")
            _normalized, absolute = normalize_relative_path(package_relative)
            backup_relative = package_relative
        else:
            raise ApiError(HTTPStatus.CONFLICT, "Der Remote-Stand verändert Dateien außerhalb von configuration.yaml und packages.")
        tree = run_git(["ls-tree", reference, "--", relative]).stdout.decode().strip()
        if relative == "configuration.yaml" and not tree:
            raise ApiError(HTTPStatus.CONFLICT, "Der Remote-Stand würde configuration.yaml löschen.")
        if tree:
            mode = tree.split(None, 1)[0]
            if mode not in {"100644", "100755"}:
                raise ApiError(HTTPStatus.CONFLICT, f"{relative} ist im Remote kein regulärer Dateieintrag.")
            content = run_git(["show", f"{reference}:{relative}"]).stdout
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, f"{relative} ist im Remote nicht UTF-8-kodiert.") from exc
            validation = validate_yaml(text)
            if not validation["valid"]:
                raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, f"{relative} ist im Remote kein gültiges YAML.", validation)
        if absolute.is_file():
            create_backup(backup_relative, absolute)
    return changed


def synchronize_git_remote(action: str) -> dict[str, Any]:
    if action not in {"fetch", "pull", "push", "sync"}:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Unbekannte Git-Synchronisationsaktion.")
    config = load_git_remote_config()
    if not config.get("url"):
        raise ApiError(HTTPStatus.CONFLICT, "Es ist noch kein Git-Remote konfiguriert.")
    branch = config["branch"]
    configuration_check: dict[str, Any] | None = None
    with file_lock, git_lock:
        try:
            ensure_git_repository()
            configure_git_remote(config["url"])
            git_commit_paths(
                [configuration_file(), PACKAGES_ROOT],
                "Lokaler Stand vor Git-Remote-Synchronisation",
            )
            reference = f"refs/remotes/{GIT_REMOTE_NAME}/{branch}"
            remote_check = run_git_remote(
                ["ls-remote", "--exit-code", GIT_REMOTE_NAME, f"refs/heads/{branch}"],
                config,
                allowed_codes=(0, 2),
            )
            remote_exists = remote_check.returncode == 0
            if action == "pull" and not remote_exists:
                raise ApiError(HTTPStatus.CONFLICT, "Der konfigurierte Remote-Branch existiert noch nicht.")
            if remote_exists:
                run_git_remote(
                    ["fetch", "--prune", GIT_REMOTE_NAME, f"refs/heads/{branch}:{reference}"],
                    config,
                )
            ahead, behind = git_ahead_behind(branch)
            if action in {"pull", "sync"} and remote_exists:
                if ahead and behind:
                    raise ApiError(HTTPStatus.CONFLICT, "Lokaler und Remote-Stand sind auseinander gelaufen. Bitte extern zusammenführen.")
                if behind:
                    prepare_remote_fast_forward(branch)
                    run_git(["merge", "--ff-only", reference])
                    configuration_check = check_home_assistant_configuration()
                    ahead, behind = git_ahead_behind(branch)
            if action in {"push", "sync"}:
                if remote_exists and behind:
                    raise ApiError(HTTPStatus.CONFLICT, "Der Remote-Stand ist neuer. Bitte zuerst sicher synchronisieren.")
                run_git_remote(
                    ["push", "--set-upstream", GIT_REMOTE_NAME, f"HEAD:refs/heads/{branch}"],
                    config,
                )
            config["lastSync"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            save_git_remote_file(config)
        except GitOperationError as exc:
            raise ApiError(HTTPStatus.BAD_GATEWAY, str(exc)) from exc
    return {
        **git_remote_status(),
        "message": "Git-Remote-Synchronisation wurde abgeschlossen.",
        "action": action,
        "configurationCheck": configuration_check,
    }


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


def file_version(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def read_file(raw_path: str) -> dict[str, Any]:
    relative, absolute = normalize_relative_path(raw_path)
    try:
        content = absolute.read_bytes()
    except FileNotFoundError as exc:
        raise ApiError(HTTPStatus.NOT_FOUND, "Die Datei wurde nicht gefunden.") from exc
    if len(content) > MAX_FILE_SIZE:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Die Datei ist groesser als 2 MiB.")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Die Datei ist nicht UTF-8-kodiert.") from exc
    metadata = load_metadata()
    attributes = file_metadata(metadata, relative)
    return {
        "path": relative,
        "content": text,
        "version": file_version(content),
        "category": attributes["category"],
        "tags": attributes["tags"],
        "modified": absolute.stat().st_mtime,
    }


def validate_yaml(content: str) -> dict[str, Any]:
    if not isinstance(content, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der YAML-Inhalt fehlt.")
    if len(content.encode("utf-8")) > MAX_FILE_SIZE:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Der Inhalt ist groesser als 2 MiB.")
    try:
        documents = list(yaml.load_all(content, Loader=HomeAssistantLoader))
        return {"valid": True, "documents": len(documents), "message": "YAML ist syntaktisch gueltig."}
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
        problem = getattr(exc, "problem", None) or str(exc).split("\n", 1)[0]
        result: dict[str, Any] = {"valid": False, "message": str(problem)}
        if mark is not None:
            result.update({"line": mark.line + 1, "column": mark.column + 1})
        return result


def duplicate_key_findings(node: yaml.Node | None) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def visit(current: yaml.Node | None) -> None:
        if isinstance(current, yaml.MappingNode):
            seen: dict[tuple[str, str], yaml.Node] = {}
            for key_node, value_node in current.value:
                if isinstance(key_node, yaml.ScalarNode):
                    identity = (key_node.tag, key_node.value)
                    if identity in seen:
                        findings.append(
                            {
                                "severity": "error",
                                "code": "duplicate-key",
                                "title": f'Doppelter Schlüssel „{key_node.value}“',
                                "message": "Der Schlüssel ist im selben YAML-Block mehrfach vorhanden und überschreibt eine Definition.",
                                "line": key_node.start_mark.line + 1,
                            }
                        )
                    else:
                        seen[identity] = key_node
                visit(value_node)
        elif isinstance(current, yaml.SequenceNode):
            for child in current.value:
                visit(child)

    visit(node)
    return findings


def script_definitions(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        return {}
    scripts = document.get("script")
    return scripts if isinstance(scripts, dict) else {}


def collect_entity_references(value: Any, references: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "entity_id":
                candidates = child if isinstance(child, list) else [child]
                for candidate in candidates:
                    if isinstance(candidate, str) and "{{" not in candidate:
                        references.extend(
                            item.strip() for item in candidate.split(",") if item.strip()
                        )
            collect_entity_references(child, references)
    elif isinstance(value, list):
        for child in value:
            collect_entity_references(child, references)


def other_script_locations(current_path: str) -> dict[str, list[str]]:
    locations: dict[str, list[str]] = {}
    packages_root = PACKAGES_ROOT.resolve()
    if not packages_root.exists():
        return locations
    for path in sorted(packages_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in VALID_SUFFIXES:
            continue
        try:
            relative = path.relative_to(packages_root).as_posix()
            if relative == current_path or path.stat().st_size > MAX_FILE_SIZE:
                continue
            text = path.read_text(encoding="utf-8")
            documents = yaml.load_all(text, Loader=HomeAssistantLoader)
            for document in documents:
                for script_id in script_definitions(document):
                    locations.setdefault(str(script_id), []).append(relative)
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            continue
    return locations


def analyze_yaml(content: str, current_path: str = "") -> dict[str, Any]:
    validation = validate_yaml(content)
    findings: list[dict[str, Any]] = []

    try:
        nodes = list(yaml.compose_all(content, Loader=HomeAssistantLoader))
        for node in nodes:
            findings.extend(duplicate_key_findings(node))
    except yaml.YAMLError:
        nodes = []

    if not validation["valid"]:
        if not findings:
            findings.append(
                {
                    "severity": "error",
                    "code": "yaml-syntax",
                    "title": "YAML-Syntaxfehler",
                    "message": validation["message"],
                    "line": validation.get("line"),
                }
            )
        return analysis_result(validation, findings)

    if content.count("{{") != content.count("}}") or content.count("{%") != content.count("%}"):
        findings.append(
            {
                "severity": "warning",
                "code": "template-balance",
                "title": "Template-Klammern prüfen",
                "message": "Die Anzahl der öffnenden und schließenden Jinja-Klammern ist unterschiedlich.",
            }
        )

    documents = list(yaml.load_all(content, Loader=HomeAssistantLoader))
    if len(documents) > 1:
        findings.append(
            {
                "severity": "tip",
                "code": "multiple-documents",
                "title": "Mehrere YAML-Dokumente",
                "message": "Die Datei enthält mehrere mit --- getrennte Dokumente. Home Assistant erwartet in Packages üblicherweise ein Dokument.",
            }
        )

    scripts: dict[str, Any] = {}
    for document in documents:
        scripts.update(script_definitions(document))

    if not scripts:
        findings.append(
            {
                "severity": "tip",
                "code": "no-script-section",
                "title": "Keine script-Sektion gefunden",
                "message": "Für ein Package mit Skripten wird normalerweise ein oberster Schlüssel script: verwendet.",
            }
        )

    external = other_script_locations(current_path) if scripts else {}
    for script_id, definition in scripts.items():
        script_name = str(script_id)
        if not re.fullmatch(r"[a-z0-9_]+", script_name):
            findings.append(
                {
                    "severity": "warning",
                    "code": "script-id",
                    "title": f'Ungünstige Script-ID „{script_name}“',
                    "message": "Script-IDs sollten nur Kleinbuchstaben, Ziffern und Unterstriche enthalten.",
                }
            )
        if script_name in external:
            findings.append(
                {
                    "severity": "error",
                    "code": "duplicate-script-id",
                    "title": f'Script-ID „{script_name}“ mehrfach definiert',
                    "message": f'Weitere Definition in: {", ".join(external[script_name][:3])}',
                }
            )
        if not isinstance(definition, dict):
            findings.append(
                {
                    "severity": "error",
                    "code": "script-structure",
                    "title": f'Unvollständiges Skript „{script_name}“',
                    "message": "Die Script-Definition muss ein YAML-Objekt sein.",
                }
            )
            continue
        if "sequence" not in definition:
            findings.append(
                {
                    "severity": "error",
                    "code": "missing-sequence",
                    "title": f'Sequenz fehlt in „{script_name}“',
                    "message": "Jedes Skript benötigt eine sequence: mit den auszuführenden Aktionen.",
                }
            )
        elif definition.get("sequence") == []:
            findings.append(
                {
                    "severity": "warning",
                    "code": "empty-sequence",
                    "title": f'Leere Sequenz in „{script_name}“',
                    "message": "Das Skript enthält aktuell keine ausführbare Aktion.",
                }
            )
        if not definition.get("alias"):
            findings.append(
                {
                    "severity": "tip",
                    "code": "missing-alias",
                    "title": f'Alias für „{script_name}“ ergänzen',
                    "message": "Ein sprechender Alias verbessert die Anzeige in Home Assistant.",
                }
            )
        if "mode" not in definition:
            findings.append(
                {
                    "severity": "tip",
                    "code": "missing-mode",
                    "title": f'Modus für „{script_name}“ festlegen',
                    "message": "Mit mode: single, restart, queued oder parallel wird das Verhalten bei erneutem Start eindeutig.",
                }
            )

    references: list[str] = []
    for document in documents:
        collect_entity_references(document, references)
    reference_counts = Counter(references)
    duplicates = sorted(
        (entity for entity, count in reference_counts.items() if count > 1), key=str.casefold
    )
    for entity in duplicates[:10]:
        count = reference_counts[entity]
        findings.append(
            {
                "severity": "warning",
                "code": "duplicate-entity",
                "title": f'Entität „{entity}“ {count}-mal verwendet',
                "message": "Prüfe, ob die mehrfache Belegung beabsichtigt ist.",
            }
        )

    return analysis_result(validation, findings)


def analysis_result(validation: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
    order = {"error": 0, "warning": 1, "tip": 2}
    findings.sort(key=lambda item: (order.get(item["severity"], 3), item.get("line", 0)))
    counts = {
        severity: sum(item["severity"] == severity for item in findings)
        for severity in ("error", "warning", "tip")
    }
    score = max(0, 100 - counts["error"] * 30 - counts["warning"] * 10 - counts["tip"] * 3)
    return {"validation": validation, "findings": findings, "counts": counts, "score": score}


def update_file_metadata(relative: str, category: str, tags: Any = None) -> None:
    clean = category.strip() if isinstance(category, str) else DEFAULT_CATEGORY
    clean = clean[:80] or DEFAULT_CATEGORY
    with metadata_lock:
        metadata = load_metadata()
        existing = file_metadata(metadata, relative)
        clean_tags = existing["tags"] if tags is None else sanitize_tags(tags)
        metadata["files"][relative] = {"category": clean, "tags": clean_tags}
        if clean != DEFAULT_CATEGORY and clean not in metadata["categories"]:
            metadata["categories"].append(clean)
            metadata["categories"].sort(key=str.casefold)
        save_metadata(metadata)


def create_backup(relative: str, source: Path) -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000:06d}"
    destination = DATA_ROOT / "backups" / stamp / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    backups = sorted((DATA_ROOT / "backups").iterdir(), key=lambda item: item.name, reverse=True)
    for old in backups[30:]:
        shutil.rmtree(old, ignore_errors=True)


def history_target(scope: str, raw_path: str = "") -> tuple[str, Path, Path]:
    if scope == "configuration":
        return "configuration/configuration.yaml", configuration_file(), Path("configuration/configuration.yaml")
    if scope == "package":
        relative, absolute = normalize_relative_path(raw_path)
        return relative, absolute, Path(relative)
    raise ApiError(HTTPStatus.BAD_REQUEST, "Unbekannter Versionsbereich.")


def backup_file(backup_id: str, relative: Path) -> Path:
    if not re.fullmatch(r"\d{8}-\d{6}-\d{6}", backup_id or ""):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ungültige Backup-ID.")
    path = (DATA_ROOT / "backups" / backup_id / relative).resolve()
    backups_root = (DATA_ROOT / "backups").resolve()
    try:
        path.relative_to(backups_root)
    except ValueError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ungültiger Backup-Pfad.") from exc
    if not path.is_file():
        raise ApiError(HTTPStatus.NOT_FOUND, "Die Sicherung wurde nicht gefunden.")
    return path


def backup_history(scope: str, raw_path: str = "") -> dict[str, Any]:
    display_path, current_path, relative = history_target(scope, raw_path)
    try:
        current = current_path.read_bytes()
    except FileNotFoundError as exc:
        raise ApiError(HTTPStatus.NOT_FOUND, "Die aktuelle Datei wurde nicht gefunden.") from exc
    entries: list[dict[str, Any]] = []
    backups_root = DATA_ROOT / "backups"
    for directory in sorted(backups_root.iterdir(), key=lambda item: item.name, reverse=True):
        if not directory.is_dir() or not re.fullmatch(r"\d{8}-\d{6}-\d{6}", directory.name):
            continue
        candidate = directory / relative
        if not candidate.is_file():
            continue
        content = candidate.read_bytes()
        old_lines = content.decode("utf-8", errors="replace").splitlines()
        current_lines = current.decode("utf-8", errors="replace").splitlines()
        changes = list(difflib.ndiff(old_lines, current_lines))
        entries.append(
            {
                "id": directory.name,
                "created": time.strftime(
                    "%Y-%m-%dT%H:%M:%S",
                    time.strptime(directory.name[:15], "%Y%m%d-%H%M%S"),
                ),
                "size": len(content),
                "version": file_version(content),
                "additions": sum(line.startswith("+ ") for line in changes),
                "deletions": sum(line.startswith("- ") for line in changes),
            }
        )
    return {
        "scope": scope,
        "path": "/config/configuration.yaml" if scope == "configuration" else f"/config/packages/{display_path}",
        "currentVersion": file_version(current),
        "entries": entries,
    }


def backup_diff(scope: str, raw_path: str, backup_id: str) -> dict[str, Any]:
    display_path, current_path, relative = history_target(scope, raw_path)
    backup_path = backup_file(backup_id, relative)
    try:
        before = backup_path.read_text(encoding="utf-8").splitlines()
        after = current_path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Die Sicherung ist nicht UTF-8-kodiert.") from exc
    lines = list(
        difflib.unified_diff(
            before,
            after,
            fromfile=f"Backup {backup_id}",
            tofile="Aktuelle Fassung",
            lineterm="",
        )
    )
    truncated = len(lines) > 1200
    return {
        "id": backup_id,
        "path": display_path,
        "diff": "\n".join(lines[:1200]),
        "truncated": truncated,
    }


def restore_backup(
    scope: str,
    raw_path: str,
    backup_id: str,
    expected_version: str | None,
) -> dict[str, Any]:
    if not isinstance(expected_version, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die aktuelle Dateiversion fehlt. Bitte neu laden.")
    display_path, current_path, relative = history_target(scope, raw_path)
    backup_path = backup_file(backup_id, relative)
    restored = backup_path.read_bytes()
    try:
        restored_text = restored.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Die Sicherung ist nicht UTF-8-kodiert.") from exc
    validation = validate_yaml(restored_text)
    if not validation["valid"]:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Die Sicherung enthält ungültiges YAML.", validation)

    with file_lock:
        try:
            current = current_path.read_bytes()
        except FileNotFoundError as exc:
            raise ApiError(HTTPStatus.NOT_FOUND, "Die aktuelle Datei wurde nicht gefunden.") from exc
        if file_version(current) != expected_version:
            raise ApiError(HTTPStatus.CONFLICT, "Die Datei wurde zwischenzeitlich geändert. Bitte neu laden.")
        git_checkpoint([current_path])
        create_backup(display_path, current_path)
        atomic_write_path(current_path, restored, current_path.stat().st_mode)
        git_result = git_commit_paths([current_path], f"Backup wiederhergestellt: {display_path}")

    result = read_configuration() if scope == "configuration" else read_file(display_path)
    result["configurationCheck"] = check_home_assistant_configuration()
    result["git"] = git_result
    result.update({"message": f"Backup {backup_id} wurde wiederhergestellt.", "restoredBackup": backup_id})
    return result


def git_history_target(scope: str, raw_path: str = "") -> tuple[str, Path, str]:
    if scope == "configuration":
        return "/config/configuration.yaml", configuration_file(), "configuration.yaml"
    if scope == "package":
        relative, absolute = normalize_relative_path(raw_path)
        return f"/config/packages/{relative}", absolute, f"packages/{relative}"
    raise ApiError(HTTPStatus.BAD_REQUEST, "Unbekannter Git-Versionsbereich.")


def resolve_git_commit(raw_commit: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", raw_commit or ""):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ungültige Git-Commit-ID.")
    try:
        result = run_git(["rev-parse", "--verify", f"{raw_commit}^{{commit}}"])
    except GitOperationError as exc:
        raise ApiError(HTTPStatus.NOT_FOUND, "Der Git-Commit wurde nicht gefunden.") from exc
    return result.stdout.decode("ascii").strip()


def git_file_at_commit(commit: str, relative: str) -> bytes:
    try:
        return run_git(["show", f"{commit}:{relative}"]).stdout
    except GitOperationError as exc:
        raise ApiError(HTTPStatus.NOT_FOUND, "Die Datei ist in diesem Git-Commit nicht vorhanden.") from exc


def git_history(scope: str, raw_path: str = "") -> dict[str, Any]:
    display_path, current_path, relative = git_history_target(scope, raw_path)
    try:
        current = current_path.read_bytes()
    except FileNotFoundError as exc:
        raise ApiError(HTTPStatus.NOT_FOUND, "Die aktuelle Datei wurde nicht gefunden.") from exc
    with git_lock:
        try:
            repository = ensure_git_repository()
            git_commit_paths(
                [current_path],
                f"Aktueller Stand vor Öffnen der Git-Historie: {relative}",
            )
            if not git_has_head():
                entries: list[dict[str, Any]] = []
            else:
                output = run_git(
                    ["log", "-n", "100", "--format=%H%x1f%aI%x1f%an%x1f%s%x1e", "--", relative]
                ).stdout.decode("utf-8", errors="replace")
                entries = []
                for record in output.split("\x1e"):
                    fields = record.strip().split("\x1f", 3)
                    if len(fields) != 4:
                        continue
                    commit, created, author, subject = fields
                    entries.append(
                        {
                            "id": commit,
                            "shortId": commit[:8],
                            "created": created,
                            "author": author,
                            "subject": subject,
                        }
                    )
            return {
                "available": True,
                "initialized": repository["initialized"],
                "scope": scope,
                "path": display_path,
                "currentVersion": file_version(current),
                "entries": entries,
            }
        except GitOperationError as exc:
            return {
                "available": False,
                "scope": scope,
                "path": display_path,
                "currentVersion": file_version(current),
                "entries": [],
                "message": str(exc),
            }


def git_diff(scope: str, raw_path: str, raw_commit: str) -> dict[str, Any]:
    display_path, current_path, relative = git_history_target(scope, raw_path)
    with git_lock:
        try:
            ensure_git_repository()
        except GitOperationError as exc:
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, str(exc)) from exc
        commit = resolve_git_commit(raw_commit)
        before_bytes = git_file_at_commit(commit, relative)
    try:
        before = before_bytes.decode("utf-8").splitlines()
        after = current_path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Die Git-Version ist nicht UTF-8-kodiert.") from exc
    lines = list(
        difflib.unified_diff(
            before,
            after,
            fromfile=f"Git {commit[:8]}",
            tofile="Aktuelle Fassung",
            lineterm="",
        )
    )
    truncated = len(lines) > 1200
    return {
        "commit": commit,
        "path": display_path,
        "diff": "\n".join(lines[:1200]),
        "truncated": truncated,
    }


def restore_git_version(
    scope: str,
    raw_path: str,
    raw_commit: str,
    expected_version: str | None,
) -> dict[str, Any]:
    if not isinstance(expected_version, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die aktuelle Dateiversion fehlt. Bitte neu laden.")
    display_path, current_path, relative = git_history_target(scope, raw_path)
    with git_lock:
        try:
            ensure_git_repository()
        except GitOperationError as exc:
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, str(exc)) from exc
        commit = resolve_git_commit(raw_commit)
        restored = git_file_at_commit(commit, relative)
    if len(restored) > MAX_FILE_SIZE:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Die Git-Version ist größer als 2 MiB.")
    try:
        restored_text = restored.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Die Git-Version ist nicht UTF-8-kodiert.") from exc
    validation = validate_yaml(restored_text)
    if not validation["valid"]:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Die Git-Version enthält ungültiges YAML.", validation)

    with file_lock:
        try:
            current = current_path.read_bytes()
        except FileNotFoundError as exc:
            raise ApiError(HTTPStatus.NOT_FOUND, "Die aktuelle Datei wurde nicht gefunden.") from exc
        if file_version(current) != expected_version:
            raise ApiError(HTTPStatus.CONFLICT, "Die Datei wurde zwischenzeitlich geändert. Bitte neu laden.")
        git_checkpoint([current_path])
        backup_relative = "configuration/configuration.yaml" if scope == "configuration" else raw_path
        create_backup(backup_relative, current_path)
        atomic_write_path(current_path, restored, current_path.stat().st_mode)
        git_result = git_commit_paths(
            [current_path],
            f"Git-Version {commit[:8]} wiederhergestellt: {relative}",
        )

    result = read_configuration() if scope == "configuration" else read_file(raw_path)
    result["configurationCheck"] = check_home_assistant_configuration()
    result["git"] = git_result
    result.update(
        {
            "message": f"Git-Version {commit[:8]} wurde wiederhergestellt.",
            "restoredCommit": commit,
            "path": result.get("path", display_path),
        }
    )
    return result


def write_file(
    raw_path: str,
    content: str,
    expected_version: str | None,
    category: str,
    create: bool,
    tags: Any = None,
) -> dict[str, Any]:
    relative, absolute = normalize_relative_path(raw_path)
    if not create and not isinstance(expected_version, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Dateiversion fehlt. Bitte die Datei neu laden.")
    validation = validate_yaml(content)
    if not validation["valid"]:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "YAML enthaelt einen Syntaxfehler.", validation)

    encoded = content.encode("utf-8")
    with file_lock:
        exists = absolute.exists()
        if create and exists:
            raise ApiError(HTTPStatus.CONFLICT, "Eine Datei mit diesem Namen existiert bereits.")
        if not create and not exists:
            raise ApiError(HTTPStatus.NOT_FOUND, "Die Datei wurde nicht gefunden.")
        if exists:
            current = absolute.read_bytes()
            if expected_version is not None and file_version(current) != expected_version:
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    "Die Datei wurde zwischenzeitlich geaendert. Bitte neu laden.",
                    {"currentVersion": file_version(current)},
                )
            create_backup(relative, absolute)

        git_checkpoint([absolute])

        absolute.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{absolute.name}.", dir=absolute.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            if exists:
                os.chmod(temporary, absolute.stat().st_mode)
            else:
                os.chmod(temporary, 0o644)
            os.replace(temporary, absolute)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        action = "gespeichert" if exists else "erstellt"
        git_result = git_commit_paths([absolute], f"Package {action}: packages/{relative}")

    update_file_metadata(relative, category, tags)
    result = read_file(relative)
    result["configurationCheck"] = check_home_assistant_configuration()
    result["git"] = git_result
    return result


def rename_file(raw_path: str, new_raw_path: str, expected_version: str | None) -> dict[str, Any]:
    relative, source = normalize_relative_path(raw_path)
    new_relative, destination = normalize_relative_path(new_raw_path)
    if not isinstance(expected_version, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Dateiversion fehlt. Bitte die Datei neu laden.")
    if relative == new_relative:
        return read_file(relative)
    with file_lock:
        if not source.exists():
            raise ApiError(HTTPStatus.NOT_FOUND, "Die Datei wurde nicht gefunden.")
        if destination.exists():
            raise ApiError(HTTPStatus.CONFLICT, "Am neuen Pfad existiert bereits eine Datei.")
        current = source.read_bytes()
        if file_version(current) != expected_version:
            raise ApiError(HTTPStatus.CONFLICT, "Die Datei wurde zwischenzeitlich geaendert. Bitte neu laden.")
        git_checkpoint([source, destination])
        create_backup(relative, source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)
        git_result = git_commit_paths(
            [source, destination],
            f"Package umbenannt: packages/{relative} -> packages/{new_relative}",
        )

    with metadata_lock:
        metadata = load_metadata()
        attributes = file_metadata(metadata, relative)
        metadata["files"].pop(relative, None)
        metadata["files"][new_relative] = attributes
        save_metadata(metadata)
    result = read_file(new_relative)
    result["git"] = git_result
    return result


def delete_file(raw_path: str, expected_version: str | None) -> dict[str, Any]:
    relative, absolute = normalize_relative_path(raw_path)
    if not isinstance(expected_version, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Dateiversion fehlt. Bitte die Datei neu laden.")
    with file_lock:
        if not absolute.exists():
            raise ApiError(HTTPStatus.NOT_FOUND, "Die Datei wurde nicht gefunden.")
        current = absolute.read_bytes()
        if expected_version and file_version(current) != expected_version:
            raise ApiError(HTTPStatus.CONFLICT, "Die Datei wurde zwischenzeitlich geaendert. Bitte neu laden.")
        git_checkpoint([absolute])
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000:06d}"
        destination = DATA_ROOT / "trash" / stamp / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(absolute), destination)
        git_result = git_commit_paths([absolute], f"Package gelöscht: packages/{relative}")
    with metadata_lock:
        metadata = load_metadata()
        metadata["files"].pop(relative, None)
        save_metadata(metadata)
    return git_result


def list_files() -> dict[str, Any]:
    metadata = load_metadata()
    files: list[dict[str, Any]] = []
    packages_root = PACKAGES_ROOT.resolve()
    if packages_root.exists():
        for path in sorted(packages_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in VALID_SUFFIXES:
                continue
            try:
                path.resolve().relative_to(packages_root)
            except ValueError:
                continue
            relative = path.relative_to(packages_root).as_posix()
            if any(part.startswith(".") for part in Path(relative).parts):
                continue
            stat = path.stat()
            attributes = file_metadata(metadata, relative)
            files.append(
                {
                    "path": relative,
                    "name": path.stem,
                    "category": attributes["category"],
                    "tags": attributes["tags"],
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                }
            )
    used = {item["category"] for item in files}
    tags = sorted({tag for item in files for tag in item["tags"]}, key=str.casefold)
    categories = sorted(
        {DEFAULT_CATEGORY, *metadata["categories"], *used},
        key=lambda value: (value == DEFAULT_CATEGORY, value.casefold()),
    )
    return {
        "files": files,
        "categories": categories,
        "tags": tags,
        "root": str(PACKAGES_ROOT),
        "configuration": package_configuration_status(),
    }


ENTITY_KEY_DOMAINS = {
    "counter",
    "group",
    "input_boolean",
    "input_button",
    "input_datetime",
    "input_number",
    "input_select",
    "input_text",
    "script",
    "shell_command",
    "timer",
}


def node_kind(node: yaml.Node) -> str:
    if isinstance(node, yaml.ScalarNode) and node.tag.startswith("!"):
        return "include"
    if isinstance(node, yaml.MappingNode):
        return "mapping"
    if isinstance(node, yaml.SequenceNode):
        return "list"
    return "scalar"


def collect_node_identifiers(
    node: yaml.Node,
    domain: str,
    source: str,
    unique_ids: dict[tuple[str, str], list[dict[str, Any]]],
    automation_ids: dict[str, list[dict[str, Any]]],
) -> None:
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            if isinstance(key_node, yaml.ScalarNode) and isinstance(value_node, yaml.ScalarNode):
                location = {"file": source, "line": value_node.start_mark.line + 1}
                if key_node.value == "unique_id" and value_node.value:
                    unique_ids.setdefault((domain, value_node.value), []).append(location)
                if domain == "automation" and key_node.value == "id" and value_node.value:
                    automation_ids.setdefault(value_node.value, []).append(location)
            collect_node_identifiers(value_node, domain, source, unique_ids, automation_ids)
    elif isinstance(node, yaml.SequenceNode):
        for child in node.value:
            collect_node_identifiers(child, domain, source, unique_ids, automation_ids)


def add_integration_records(
    mapping: yaml.Node,
    source: str,
    records: dict[str, list[dict[str, Any]]],
    unique_ids: dict[tuple[str, str], list[dict[str, Any]]],
    automation_ids: dict[str, list[dict[str, Any]]],
) -> bool:
    if not isinstance(mapping, yaml.MappingNode):
        return False
    for key_node, value_node in mapping.value:
        if not isinstance(key_node, yaml.ScalarNode):
            continue
        domain = key_node.value.split(" ", 1)[0]
        if domain == "homeassistant" and source == "/config/configuration.yaml":
            continue
        children: dict[str, dict[str, Any]] = {}
        if isinstance(value_node, yaml.MappingNode):
            for child_key, child_value in value_node.value:
                if isinstance(child_key, yaml.ScalarNode):
                    children[child_key.value] = {
                        "kind": node_kind(child_value),
                        "line": child_key.start_mark.line + 1,
                    }
        records.setdefault(domain, []).append(
            {
                "file": source,
                "kind": node_kind(value_node),
                "children": children,
                "line": key_node.start_mark.line + 1,
            }
        )
        collect_node_identifiers(value_node, domain, source, unique_ids, automation_ids)
    return True


def package_conflict_analysis(overlay: dict[str, str] | None = None) -> dict[str, Any]:
    packages_root = PACKAGES_ROOT.resolve()
    findings: list[dict[str, Any]] = []
    records: dict[str, list[dict[str, Any]]] = {}
    unique_ids: dict[tuple[str, str], list[dict[str, Any]]] = {}
    automation_ids: dict[str, list[dict[str, Any]]] = {}
    package_names: dict[str, list[str]] = {}
    mode = "named"
    try:
        configured_mode = configuration_package_mode(read_configuration()["content"])
        if configured_mode:
            mode = configured_mode
    except (ApiError, OSError, yaml.YAMLError):
        pass

    sources: dict[str, str] = {}
    if packages_root.exists():
        for path in sorted(packages_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in VALID_SUFFIXES:
                continue
            relative = path.relative_to(packages_root).as_posix()
            try:
                sources[relative] = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                sources[relative] = ""
                findings.append(
                    {
                        "severity": "error",
                        "code": "invalid-package-yaml",
                        "title": f"{relative} kann nicht analysiert werden",
                        "message": str(exc).split("\n", 1)[0],
                        "files": [relative],
                    }
                )
    if overlay:
        sources.update(overlay)

    for relative, source_content in sorted(sources.items()):
        source_path = Path(relative)
        package_names.setdefault(source_path.stem.casefold(), []).append(relative)
        if source_path.suffix.lower() == ".yml":
            findings.append(
                {
                    "severity": "warning",
                    "code": "unsupported-package-extension",
                    "title": f"{relative} wird nicht automatisch importiert",
                    "message": "Home Assistants Verzeichnis-Includes laden automatisch nur Dateien mit der Endung .yaml.",
                    "files": [relative],
                }
            )
        try:
            documents = list(yaml.compose_all(source_content, Loader=HomeAssistantLoader))
        except yaml.YAMLError as exc:
            findings.append(
                {
                    "severity": "error",
                    "code": "invalid-package-yaml",
                    "title": f"{relative} kann nicht analysiert werden",
                    "message": str(exc).split("\n", 1)[0],
                    "files": [relative],
                }
            )
            continue
        for document in documents:
            mappings: list[tuple[yaml.Node, str]] = []
            if mode == "merge_named" and isinstance(document, yaml.MappingNode):
                mappings.extend((value, f"{relative}#{key.value}") for key, value in document.value if isinstance(key, yaml.ScalarNode))
            else:
                mappings.append((document, relative))
            for mapping, source in mappings:
                if not add_integration_records(mapping, source, records, unique_ids, automation_ids):
                    findings.append(
                        {
                            "severity": "error",
                            "code": "invalid-package-root",
                            "title": f"Ungültige Package-Struktur in {relative}",
                            "message": "Der Package-Inhalt muss ein YAML-Objekt mit Integrationsschlüsseln sein.",
                            "files": [relative],
                        }
                    )

    try:
        configuration = configuration_file()
        main_node = yaml.compose(configuration.read_text(encoding="utf-8"), Loader=HomeAssistantLoader)
        add_integration_records(
            main_node,
            "/config/configuration.yaml",
            records,
            unique_ids,
            automation_ids,
        )
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        pass

    for name, files in package_names.items():
        if len(files) > 1:
            findings.append(
                {
                    "severity": "error",
                    "code": "duplicate-package-name",
                    "title": f'Package-Dateiname „{name}“ ist mehrfach vorhanden',
                    "message": "Bei !include_dir_named müssen Dateinamen auch über Unterordner hinweg eindeutig sein.",
                    "files": files,
                }
            )

    for domain, domain_records in records.items():
        relevant = [record for record in domain_records if record["kind"] != "include"]
        if len(relevant) < 2 or all(record["kind"] == "list" for record in relevant):
            continue
        if all(record["kind"] == "mapping" for record in relevant):
            child_records: dict[str, list[dict[str, Any]]] = {}
            for record in relevant:
                for key, details in record["children"].items():
                    child_records.setdefault(key, []).append({**details, "file": record["file"]})
            for key, duplicates in child_records.items():
                if len(duplicates) < 2 or all(item["kind"] == "list" for item in duplicates):
                    continue
                entity_domain = domain in ENTITY_KEY_DOMAINS
                findings.append(
                    {
                        "severity": "error",
                        "code": "duplicate-entity-id" if entity_domain else "duplicate-integration-key",
                        "title": (
                            f'Doppelte Entity-ID „{domain}.{key}“'
                            if entity_domain
                            else f'Doppelter Schlüssel „{domain}.{key}“'
                        ),
                        "message": "Dieser Schlüssel kann nach den Package-Merge-Regeln nur einmal definiert werden.",
                        "files": [item["file"] for item in duplicates],
                    }
                )
            continue
        findings.append(
            {
                "severity": "error",
                "code": "duplicate-integration",
                "title": f'Integration „{domain}“ ist nicht eindeutig zusammenführbar',
                "message": "Mehrere skalare oder unterschiedlich strukturierte Definitionen können nicht sicher gemergt werden.",
                "files": [record["file"] for record in relevant],
            }
        )

    for (domain, unique_id), locations in unique_ids.items():
        if len(locations) > 1:
            findings.append(
                {
                    "severity": "warning",
                    "code": "duplicate-unique-id",
                    "title": f'Doppelte unique_id „{unique_id}“ in {domain}',
                    "message": "Doppelte Unique-IDs können die Registrierung von Entitäten verhindern.",
                    "files": [location["file"] for location in locations],
                }
            )
    for automation_id, locations in automation_ids.items():
        if len(locations) > 1:
            findings.append(
                {
                    "severity": "error",
                    "code": "duplicate-automation-id",
                    "title": f'Doppelte Automation-ID „{automation_id}“',
                    "message": "Automation-IDs müssen über alle geladenen YAML-Dateien eindeutig sein.",
                    "files": [location["file"] for location in locations],
                }
            )

    findings.sort(key=lambda item: (item["severity"] != "error", item["title"].casefold()))
    counts = {
        "error": sum(item["severity"] == "error" for item in findings),
        "warning": sum(item["severity"] == "warning" for item in findings),
    }
    return {"mode": mode, "findings": findings, "counts": counts, "fileCount": len(sources)}


def collect_script_references(value: Any, references: set[str]) -> None:
    if isinstance(value, dict):
        for child in value.values():
            collect_script_references(child, references)
    elif isinstance(value, list):
        for child in value:
            collect_script_references(child, references)
    elif isinstance(value, str):
        references.update(re.findall(r"\bscript\.([A-Za-z0-9_]+)\b", value))


def recent_git_commits(limit: int = 5) -> list[dict[str, str]]:
    with git_lock:
        try:
            ensure_git_repository()
            output = run_git(
                ["log", "-n", str(limit), "--format=%H%x1f%aI%x1f%s%x1e"]
            ).stdout.decode("utf-8", errors="replace")
        except GitOperationError:
            return []
    commits: list[dict[str, str]] = []
    for record in output.split("\x1e"):
        fields = record.strip().split("\x1f", 2)
        if len(fields) == 3:
            commit, created, subject = fields
            commits.append({"id": commit, "shortId": commit[:8], "created": created, "subject": subject})
    return commits


def configuration_quality_dashboard() -> dict[str, Any]:
    conflicts = package_conflict_analysis()
    definitions: dict[str, list[str]] = {}
    references: set[str] = set()
    config_root = git_root()
    yaml_paths: list[Path] = []
    if config_root.exists():
        for path in config_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in VALID_SUFFIXES:
                continue
            try:
                relative = path.relative_to(config_root)
            except ValueError:
                continue
            if any(part.startswith(".") for part in relative.parts) or path.stat().st_size > MAX_FILE_SIZE:
                continue
            yaml_paths.append(path)

    for path in sorted(yaml_paths):
        try:
            documents = list(yaml.load_all(path.read_text(encoding="utf-8"), Loader=HomeAssistantLoader))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            continue
        relative = path.relative_to(config_root).as_posix()
        for document in documents:
            if isinstance(document, dict) and isinstance(document.get("script"), dict):
                for script_id in document["script"]:
                    definitions.setdefault(str(script_id), []).append(relative)
            collect_script_references(document, references)

    unused = sorted(set(definitions) - references, key=str.casefold)
    unused_findings = [
        {
            "severity": "warning",
            "code": "possibly-unused-script",
            "title": f'Script „{script_id}“ möglicherweise ungenutzt',
            "message": "Keine YAML-Referenz gefunden; Aufrufe aus Dashboards oder externen Integrationen sind weiterhin möglich.",
            "files": definitions[script_id],
        }
        for script_id in unused
    ]
    findings = [*conflicts["findings"], *unused_findings]
    errors = conflicts["counts"]["error"]
    warnings = conflicts["counts"]["warning"] + len(unused_findings)
    score = max(0, 100 - errors * 10 - warnings * 2)
    backups_root = DATA_ROOT / "backups"
    backup_count = sum(path.is_dir() for path in backups_root.iterdir()) if backups_root.exists() else 0
    remote = git_remote_status()
    return {
        "score": score,
        "summary": {
            "files": conflicts["fileCount"],
            "scripts": len(definitions),
            "unusedScripts": len(unused),
            "errors": errors,
            "warnings": warnings,
            "backups": backup_count,
        },
        "findings": findings[:200],
        "findingsTruncated": len(findings) > 200,
        "git": {
            "remote": remote,
            "recentCommits": recent_git_commits(),
        },
    }


def export_packages(scope: str, raw_path: str = "", category: str = "") -> tuple[str, bytes]:
    metadata = load_metadata()
    selected: list[tuple[str, Path]] = []
    for item in list_files()["files"]:
        include = scope == "all"
        if scope == "file":
            include = item["path"] == raw_path
        elif scope == "category":
            include = item["category"] == category
        elif scope not in {"all", "file", "category"}:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Unbekannter Exportbereich.")
        if include:
            relative, absolute = normalize_relative_path(item["path"])
            selected.append((relative, absolute))
    if not selected:
        raise ApiError(HTTPStatus.NOT_FOUND, "Für diesen Export wurden keine Package-Dateien gefunden.")
    if len(selected) > MAX_IMPORT_FILES:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Der Export enthält mehr als 500 Dateien.")
    if sum(path.stat().st_size for _relative, path in selected) > MAX_IMPORT_EXPANDED_SIZE:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Der Export ist größer als 50 MiB.")

    manifest = {
        "format": 1,
        "exportedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": {
            relative: file_metadata(metadata, relative)
            for relative, _absolute in selected
        },
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        for relative, absolute in selected:
            archive.writestr(f"packages/{relative}", absolute.read_bytes())
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return f"yaml-packages-{stamp}.zip", output.getvalue()


def decode_import_archive(encoded: Any) -> tuple[dict[str, str], dict[str, Any], list[str], str]:
    if not isinstance(encoded, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ein ZIP-Archiv ist erforderlich.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Das ZIP-Archiv ist nicht gültig kodiert.") from exc
    if len(raw) > MAX_IMPORT_SIZE:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Das ZIP-Archiv ist größer als 10 MiB.")
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Die Datei ist kein gültiges ZIP-Archiv.")

    files: dict[str, str] = {}
    manifest: dict[str, Any] = {}
    errors: list[str] = []
    expanded_size = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if len(members) > MAX_IMPORT_FILES + 1:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Das ZIP-Archiv enthält zu viele Dateien.")
        for member in members:
            expanded_size += member.file_size
            if expanded_size > MAX_IMPORT_EXPANDED_SIZE:
                raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Der entpackte ZIP-Inhalt ist größer als 50 MiB.")
            if member.flag_bits & 0x1:
                errors.append(f"{member.filename}: verschlüsselte ZIP-Einträge werden nicht unterstützt.")
                continue
            archive_path = member.filename.replace("\\", "/")
            if archive_path == "manifest.json":
                try:
                    candidate = json.loads(archive.read(member).decode("utf-8"))
                    manifest = candidate if isinstance(candidate, dict) else {}
                except (UnicodeDecodeError, json.JSONDecodeError):
                    errors.append("manifest.json ist ungültig.")
                continue
            relative_name = archive_path.removeprefix("packages/")
            try:
                relative, _absolute = normalize_relative_path(relative_name)
            except ApiError as exc:
                errors.append(f"{archive_path}: {exc.message}")
                continue
            if relative in files:
                errors.append(f"{relative}: im Archiv mehrfach vorhanden.")
                continue
            try:
                content = archive.read(member).decode("utf-8")
            except UnicodeDecodeError:
                errors.append(f"{relative}: Datei ist nicht UTF-8-kodiert.")
                continue
            validation = validate_yaml(content)
            if not validation["valid"]:
                errors.append(f"{relative}: {validation['message']}")
                continue
            files[relative] = content
    if not files and not errors:
        errors.append("Das Archiv enthält keine YAML-Package-Dateien.")
    return files, manifest, errors, hashlib.sha256(raw).hexdigest()


def import_destination_version(files: dict[str, str]) -> str:
    versions: list[str] = []
    package_paths = {item["path"] for item in list_files()["files"]}
    for relative in sorted(package_paths | set(files)):
        _normalized, absolute = normalize_relative_path(relative)
        current = file_version(absolute.read_bytes()) if absolute.is_file() else "missing"
        versions.append(f"{relative}\0{current}")
    return hashlib.sha256("\n".join(versions).encode("utf-8")).hexdigest()


def preview_package_import(encoded: Any) -> dict[str, Any]:
    files, _manifest, errors, archive_version = decode_import_archive(encoded)
    entries = []
    for relative, content in sorted(files.items()):
        _normalized, absolute = normalize_relative_path(relative)
        entries.append(
            {
                "path": relative,
                "size": len(content.encode("utf-8")),
                "exists": absolute.exists(),
                "action": "overwrite" if absolute.exists() else "create",
            }
        )
    conflicts = package_conflict_analysis(files) if files else {
        "mode": "unknown", "findings": [], "counts": {"error": 0, "warning": 0}, "fileCount": 0,
    }
    return {
        "valid": not errors,
        "archiveVersion": archive_version,
        "destinationVersion": import_destination_version(files),
        "files": entries,
        "errors": errors,
        "existingCount": sum(item["exists"] for item in entries),
        "conflicts": conflicts,
    }


def apply_package_import(
    encoded: Any,
    strategy: str,
    expected_archive_version: Any,
    expected_destination_version: Any,
) -> dict[str, Any]:
    if strategy not in {"skip", "overwrite"}:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Unbekannte Importstrategie.")
    files, manifest, errors, archive_version = decode_import_archive(encoded)
    if errors:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "Das Archiv enthält ungültige Dateien.", {"details": errors})
    if archive_version != expected_archive_version:
        raise ApiError(HTTPStatus.CONFLICT, "Das ZIP-Archiv hat sich seit der Vorschau geändert.")
    if import_destination_version(files) != expected_destination_version:
        raise ApiError(HTTPStatus.CONFLICT, "Package-Dateien wurden seit der Importvorschau geändert.")

    selected: dict[str, str] = {}
    skipped: list[str] = []
    for relative, content in files.items():
        _normalized, absolute = normalize_relative_path(relative)
        if absolute.exists() and strategy == "skip":
            skipped.append(relative)
        else:
            selected[relative] = content
    if not selected:
        raise ApiError(HTTPStatus.CONFLICT, "Nach Anwendung der Importstrategie bleiben keine Dateien übrig.")

    paths = [normalize_relative_path(relative)[1] for relative in selected]
    originals: dict[Path, bytes | None] = {}
    with file_lock:
        git_checkpoint(paths)
        try:
            for relative, content in selected.items():
                _normalized, absolute = normalize_relative_path(relative)
                originals[absolute] = absolute.read_bytes() if absolute.exists() else None
                if absolute.exists():
                    create_backup(relative, absolute)
                atomic_write_path(
                    absolute,
                    content.encode("utf-8"),
                    absolute.stat().st_mode if absolute.exists() else 0o644,
                )
        except OSError as exc:
            for path, original in originals.items():
                if original is None:
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
                else:
                    atomic_write_path(path, original, path.stat().st_mode if path.exists() else 0o644)
            raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "Der Package-Import wurde zurückgerollt.") from exc
        git_result = git_commit_paths(paths, f"{len(selected)} Package-Dateien aus ZIP importiert")

    manifest_files = manifest.get("files", {}) if isinstance(manifest.get("files"), dict) else {}
    for relative in selected:
        attributes = manifest_files.get(relative, {})
        if isinstance(attributes, dict):
            update_file_metadata(
                relative,
                attributes.get("category", DEFAULT_CATEGORY),
                attributes.get("tags", []),
            )
    result = {
        "message": f"{len(selected)} Package-Dateien wurden importiert.",
        "imported": sorted(selected),
        "skipped": sorted(skipped),
        "git": git_result,
        "configurationCheck": check_home_assistant_configuration(),
        "conflicts": package_conflict_analysis(),
    }
    return result


def home_assistant_request(path: str, method: str = "GET") -> Any:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "Home-Assistant-API ist lokal nicht verfuegbar.")
    request = urllib.request.Request(
        f"http://supervisor/core/api/{path.lstrip('/')}",
        data=b"{}" if method == "POST" else None,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = response.read()
            return json.loads(payload) if payload else {}
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ApiError(HTTPStatus.BAD_GATEWAY, "Home Assistant konnte nicht erreicht werden.") from exc


def check_home_assistant_configuration() -> dict[str, Any]:
    try:
        response = home_assistant_request("config/core/check_config", method="POST")
    except ApiError as exc:
        return {
            "available": False,
            "valid": None,
            "status": "unavailable",
            "message": exc.message,
        }
    valid = response.get("result") == "valid"
    errors = response.get("errors")
    message = "Home-Assistant-Konfiguration ist gültig." if valid else str(errors or "Home Assistant meldet eine ungültige Konfiguration.")
    result: dict[str, Any] = {
        "available": True,
        "valid": valid,
        "status": "valid" if valid else "invalid",
        "message": message,
        "errors": errors,
    }
    if not valid:
        source_match = re.search(
            r"\[source\s+(?P<source>/config/[^:\]]+\.ya?ml):(?P<line>\d+)",
            message,
            re.IGNORECASE,
        ) or re.search(
            r"[\"'](?P<source>/config/[^\"']+\.ya?ml)[\"'].*?(?:line|Zeile)\s+(?P<line>\d+)",
            message,
            re.IGNORECASE | re.DOTALL,
        )
        if source_match:
            result["source"] = source_match.group("source")
            result["line"] = int(source_match.group("line"))
            return result
        line_match = re.search(r"(?:line|Zeile)\s+(\d+)", message, re.IGNORECASE)
        if line_match:
            result["line"] = int(line_match.group(1))
    return result


def helper_data() -> dict[str, Any]:
    states = home_assistant_request("states")
    services_data = home_assistant_request("services")
    entities = [
        {
            "entity_id": item.get("entity_id", ""),
            "name": item.get("attributes", {}).get("friendly_name", item.get("entity_id", "")),
            "state": item.get("state", ""),
        }
        for item in states
    ]
    services = [
        f"{domain.get('domain')}.{service}"
        for domain in services_data
        for service in domain.get("services", {})
    ]
    return {
        "entities": sorted(entities, key=lambda item: item["entity_id"]),
        "services": sorted(services),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "YamlScriptManager/0.7"

    def log_message(self, format_string: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format_string % args}", flush=True)

    def send_bytes(
        self,
        status: int,
        body: bytes,
        content_type: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, value: Any) -> None:
        self.send_bytes(status, json_bytes(value), "application/json; charset=utf-8")

    def read_json(self, max_size: int | None = None) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Ungueltige Anfragegroesse.") from exc
        if length > (max_size or MAX_FILE_SIZE + 16_384):
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Die Anfrage ist zu gross.")
        try:
            value = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Ungueltiges JSON.") from exc
        if not isinstance(value, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Ein JSON-Objekt wird erwartet.")
        return value

    def route(self) -> tuple[str, dict[str, list[str]]]:
        parsed = urllib.parse.urlsplit(self.path)
        return parsed.path.rstrip("/") or "/", urllib.parse.parse_qs(parsed.query)

    def do_GET(self) -> None:  # noqa: N802
        try:
            path, query = self.route()
            if path == "/health":
                self.send_json(HTTPStatus.OK, {"status": "ok"})
            elif path == "/api/files":
                self.send_json(HTTPStatus.OK, list_files())
            elif path == "/api/file":
                self.send_json(HTTPStatus.OK, read_file(query.get("path", [""])[0]))
            elif path == "/api/configuration":
                self.send_json(HTTPStatus.OK, read_configuration())
            elif path == "/api/backups":
                self.send_json(
                    HTTPStatus.OK,
                    backup_history(
                        query.get("scope", [""])[0],
                        query.get("path", [""])[0],
                    ),
                )
            elif path == "/api/backup/diff":
                self.send_json(
                    HTTPStatus.OK,
                    backup_diff(
                        query.get("scope", [""])[0],
                        query.get("path", [""])[0],
                        query.get("id", [""])[0],
                    ),
                )
            elif path == "/api/git/history":
                self.send_json(
                    HTTPStatus.OK,
                    git_history(
                        query.get("scope", [""])[0],
                        query.get("path", [""])[0],
                    ),
                )
            elif path == "/api/git/diff":
                self.send_json(
                    HTTPStatus.OK,
                    git_diff(
                        query.get("scope", [""])[0],
                        query.get("path", [""])[0],
                        query.get("commit", [""])[0],
                    ),
                )
            elif path == "/api/package-conflicts":
                self.send_json(HTTPStatus.OK, package_conflict_analysis())
            elif path == "/api/dashboard":
                self.send_json(HTTPStatus.OK, configuration_quality_dashboard())
            elif path == "/api/git/remote":
                self.send_json(HTTPStatus.OK, git_remote_status())
            elif path == "/api/export":
                filename, archive = export_packages(
                    query.get("scope", ["all"])[0],
                    query.get("path", [""])[0],
                    query.get("category", [""])[0],
                )
                self.send_bytes(
                    HTTPStatus.OK,
                    archive,
                    "application/zip",
                    {"Content-Disposition": f'attachment; filename="{filename}"'},
                )
            elif path == "/api/helpers":
                self.send_json(HTTPStatus.OK, helper_data())
            elif path.startswith("/static/"):
                self.serve_static(path.removeprefix("/static/"))
            elif path == "/":
                self.serve_index()
            else:
                raise ApiError(HTTPStatus.NOT_FOUND, "Unbekannter Endpunkt.")
        except ApiError as exc:
            self.send_json(exc.status, {"error": exc.message, **exc.details})
        except Exception as exc:  # pragma: no cover - final request boundary
            print(f"Unhandled error: {exc!r}", flush=True)
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Interner Serverfehler."})

    def do_POST(self) -> None:  # noqa: N802
        try:
            path, _ = self.route()
            body = self.read_json(MAX_IMPORT_SIZE * 2 if path.startswith("/api/import/") else None)
            if path == "/api/files":
                result = write_file(
                    body.get("path", ""),
                    body.get("content", ""),
                    None,
                    body.get("category", DEFAULT_CATEGORY),
                    create=True,
                    tags=body.get("tags"),
                )
                self.send_json(HTTPStatus.CREATED, result)
            elif path == "/api/rename":
                result = rename_file(
                    body.get("path", ""),
                    body.get("newPath", ""),
                    body.get("version"),
                )
                self.send_json(HTTPStatus.OK, result)
            elif path == "/api/validate":
                self.send_json(HTTPStatus.OK, validate_yaml(body.get("content", "")))
            elif path == "/api/analyze":
                self.send_json(
                    HTTPStatus.OK,
                    analyze_yaml(body.get("content", ""), body.get("path", "")),
                )
            elif path == "/api/configuration/enable-packages":
                self.send_json(
                    HTTPStatus.OK,
                    enable_packages(body.get("content", ""), body.get("version")),
                )
            elif path == "/api/configuration/migration-preview":
                self.send_json(
                    HTTPStatus.OK,
                    configuration_migration_preview(
                        body.get("content", ""),
                        body.get("packageName", "configuration_import"),
                    ),
                )
            elif path == "/api/configuration/migrate":
                self.send_json(
                    HTTPStatus.OK,
                    migrate_configuration(
                        body.get("content", ""),
                        body.get("version"),
                        body.get("packageName", "configuration_import"),
                    ),
                )
            elif path == "/api/configuration/check":
                self.send_json(HTTPStatus.OK, check_home_assistant_configuration())
            elif path == "/api/backup/restore":
                self.send_json(
                    HTTPStatus.OK,
                    restore_backup(
                        body.get("scope", ""),
                        body.get("path", ""),
                        body.get("id", ""),
                        body.get("version"),
                    ),
                )
            elif path == "/api/git/restore":
                self.send_json(
                    HTTPStatus.OK,
                    restore_git_version(
                        body.get("scope", ""),
                        body.get("path", ""),
                        body.get("commit", ""),
                        body.get("version"),
                    ),
                )
            elif path == "/api/git/remote/sync":
                self.send_json(
                    HTTPStatus.OK,
                    synchronize_git_remote(body.get("action", "sync")),
                )
            elif path == "/api/import/preview":
                self.send_json(HTTPStatus.OK, preview_package_import(body.get("archive")))
            elif path == "/api/import/apply":
                self.send_json(
                    HTTPStatus.OK,
                    apply_package_import(
                        body.get("archive"),
                        body.get("strategy", "skip"),
                        body.get("archiveVersion"),
                        body.get("destinationVersion"),
                    ),
                )
            elif path == "/api/reload":
                home_assistant_request("services/script/reload", method="POST")
                self.send_json(HTTPStatus.OK, {"message": "Skripte wurden neu geladen."})
            else:
                raise ApiError(HTTPStatus.NOT_FOUND, "Unbekannter Endpunkt.")
        except ApiError as exc:
            self.send_json(exc.status, {"error": exc.message, **exc.details})

    def do_PUT(self) -> None:  # noqa: N802
        try:
            path, _ = self.route()
            body = self.read_json()
            if path == "/api/file":
                result = write_file(
                    body.get("path", ""),
                    body.get("content", ""),
                    body.get("version"),
                    body.get("category", DEFAULT_CATEGORY),
                    create=False,
                    tags=body.get("tags"),
                )
            elif path == "/api/configuration":
                result = write_configuration(body.get("content", ""), body.get("version"))
            elif path == "/api/git/remote":
                result = update_git_remote(body)
            else:
                raise ApiError(HTTPStatus.NOT_FOUND, "Unbekannter Endpunkt.")
            self.send_json(HTTPStatus.OK, result)
        except ApiError as exc:
            self.send_json(exc.status, {"error": exc.message, **exc.details})

    def do_DELETE(self) -> None:  # noqa: N802
        try:
            path, _ = self.route()
            if path == "/api/git/remote":
                self.send_json(HTTPStatus.OK, remove_git_remote())
                return
            if path != "/api/file":
                raise ApiError(HTTPStatus.NOT_FOUND, "Unbekannter Endpunkt.")
            body = self.read_json()
            git_result = delete_file(body.get("path", ""), body.get("version"))
            self.send_json(
                HTTPStatus.OK,
                {"message": "Datei wurde in den Papierkorb verschoben.", "git": git_result},
            )
        except ApiError as exc:
            self.send_json(exc.status, {"error": exc.message, **exc.details})

    def serve_index(self) -> None:
        template = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        ingress = self.headers.get("X-Ingress-Path", "").rstrip("/")
        if not ingress.startswith("/") or not re.fullmatch(r"/[A-Za-z0-9_./-]*", ingress):
            ingress = ""
        html = template.replace("__BASE_PATH__", f"{ingress}/")
        self.send_bytes(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")

    def serve_static(self, raw_name: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", raw_name):
            raise ApiError(HTTPStatus.NOT_FOUND, "Datei nicht gefunden.")
        path = STATIC_ROOT / raw_name
        try:
            body = path.read_bytes()
        except FileNotFoundError as exc:
            raise ApiError(HTTPStatus.NOT_FOUND, "Datei nicht gefunden.") from exc
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_bytes(HTTPStatus.OK, body, f"{content_type}; charset=utf-8")


def main() -> None:
    global DATA_ROOT, GIT_REMOTE_FILE, METADATA_FILE, PACKAGES_ROOT, PORT
    parser = argparse.ArgumentParser(description="Home Assistant YAML Script Manager")
    parser.add_argument("--port", type=int)
    parser.add_argument("--packages-path", type=Path)
    parser.add_argument("--data-path", type=Path)
    args = parser.parse_args()
    if args.port is not None:
        PORT = args.port
    if args.packages_path is not None:
        PACKAGES_ROOT = args.packages_path.resolve()
    if args.data_path is not None:
        DATA_ROOT = args.data_path.resolve()
        METADATA_FILE = DATA_ROOT / "metadata.json"
        GIT_REMOTE_FILE = DATA_ROOT / "git_remote.json"
    ensure_directories()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"YAML Script Manager listening on port {PORT}; packages={PACKAGES_ROOT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
