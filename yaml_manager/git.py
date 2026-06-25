"""Local Git history and protected remote synchronization."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.parse
from http import HTTPStatus
from pathlib import Path
from typing import Any

try:
    from .errors import ApiError
except ImportError:  # pragma: no cover - direct execution in the app container
    from errors import ApiError


def bind(backend: Any) -> None:
    """Refresh runtime paths and callbacks exposed by the application facade."""

    names = (
        "DATA_ROOT",
        "GIT_ASKPASS",
        "GIT_REMOTE_FILE",
        "GIT_REMOTE_NAME",
        "MAX_FILE_SIZE",
        "PACKAGES_ROOT",
        "atomic_write_path",
        "check_home_assistant_configuration",
        "configuration_file",
        "create_backup",
        "file_lock",
        "file_version",
        "git_lock",
        "normalize_relative_path",
        "package_contents",
        "read_configuration",
        "read_file",
        "read_yaml_text",
        "security_push_warning",
        "validate_yaml",
    )
    globals().update({name: getattr(backend, name) for name in names})


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
        "autoPush": bool(config.get("autoPush", True)),
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


def current_git_branch() -> str:
    result = run_git(["symbolic-ref", "--quiet", "--short", "HEAD"], allowed_codes=(0, 1))
    return result.stdout.decode("utf-8", errors="replace").strip() if result.returncode == 0 else "detached"


def resolve_local_branch(raw_branch: Any) -> tuple[str, str]:
    branch = validate_git_branch(raw_branch)
    result = run_git(
        ["rev-parse", "--verify", f"refs/heads/{branch}"],
        allowed_codes=(0, 128),
    )
    if result.returncode != 0:
        raise ApiError(HTTPStatus.NOT_FOUND, f"Der lokale Branch {branch} wurde nicht gefunden.")
    return branch, result.stdout.decode("ascii").split()[0]


def git_branches() -> dict[str, Any]:
    with git_lock:
        try:
            ensure_git_repository()
            output = run_git(
                [
                    "for-each-ref",
                    "--sort=refname",
                    "--format=%(refname:short)%00%(objectname)%00%(upstream:short)%00%(HEAD)",
                    "refs/heads",
                ]
            ).stdout.decode("utf-8", errors="replace")
            branches: list[dict[str, Any]] = []
            for line in output.splitlines():
                fields = line.split("\0")
                if len(fields) != 4:
                    continue
                name, commit, upstream, head = fields
                branches.append(
                    {
                        "name": name,
                        "commit": commit,
                        "shortCommit": commit[:8],
                        "upstream": upstream,
                        "current": head == "*",
                    }
                )
            return {
                "available": True,
                "current": current_git_branch(),
                "branches": branches,
            }
        except GitOperationError as exc:
            return {"available": False, "current": "", "branches": [], "message": str(exc)}


def create_git_branch(raw_branch: Any) -> dict[str, Any]:
    branch = validate_git_branch(raw_branch)
    with file_lock, git_lock:
        try:
            ensure_git_repository()
            exists = run_git(
                ["rev-parse", "--verify", f"refs/heads/{branch}"],
                allowed_codes=(0, 128),
            ).returncode == 0
            if exists:
                raise ApiError(HTTPStatus.CONFLICT, f"Der Branch {branch} existiert bereits.")
            git_commit_paths(
                [configuration_file(), PACKAGES_ROOT],
                "Stand vor dem Erstellen eines Git-Branches",
            )
            run_git(["switch", "-c", branch])
        except GitOperationError as exc:
            raise ApiError(HTTPStatus.CONFLICT, str(exc)) from exc
    return {**git_branches(), "message": f"Branch {branch} wurde erstellt und ausgecheckt."}


def branch_changed_paths(reference: str) -> list[str]:
    output = run_git(["diff", "--name-only", "HEAD", reference]).stdout.decode(
        "utf-8", errors="replace"
    )
    return [path for path in output.splitlines() if path]


def validate_branch_yaml(reference: str, changed: list[str]) -> None:
    for relative in changed:
        if relative == "configuration.yaml" or relative.startswith("packages/"):
            if relative != "configuration.yaml" and Path(relative).suffix.lower() not in {".yaml", ".yml"}:
                continue
            validate_remote_yaml(reference, relative)


def backup_changed_yaml(changed: list[str]) -> None:
    for relative in changed:
        if relative == "configuration.yaml":
            path = configuration_file()
            backup_relative = "configuration/configuration.yaml"
        elif relative.startswith("packages/"):
            package_relative = relative.removeprefix("packages/")
            if Path(package_relative).suffix.lower() not in {".yaml", ".yml"}:
                continue
            _normalized, path = normalize_relative_path(package_relative)
            backup_relative = package_relative
        else:
            continue
        if path.is_file():
            create_backup(backup_relative, path)


def switch_git_branch(raw_branch: Any) -> dict[str, Any]:
    branch, commit = resolve_local_branch(raw_branch)
    current = current_git_branch()
    if branch == current:
        return {**git_branches(), "message": f"Branch {branch} ist bereits aktiv."}
    configuration_check: dict[str, Any] | None = None
    with file_lock, git_lock:
        try:
            git_commit_paths(
                [configuration_file(), PACKAGES_ROOT],
                "Stand vor dem Wechsel des Git-Branches",
            )
            changed = branch_changed_paths(commit)
            validate_branch_yaml(commit, changed)
            backup_changed_yaml(changed)
            run_git(["switch", branch])
            configuration_check = check_home_assistant_configuration()
        except GitOperationError as exc:
            raise ApiError(HTTPStatus.CONFLICT, str(exc)) from exc
    return {
        **git_branches(),
        "message": f"Branch {branch} wurde ausgecheckt.",
        "configurationCheck": configuration_check,
    }


def branch_merge_preview(raw_branch: Any) -> dict[str, Any]:
    branch, target = resolve_local_branch(raw_branch)
    current = current_git_branch()
    if branch == current:
        raise ApiError(HTTPStatus.CONFLICT, "Der aktive Branch kann nicht mit sich selbst verglichen werden.")
    head = run_git(["rev-parse", "HEAD"]).stdout.decode("ascii").strip()
    counts = run_git(["rev-list", "--left-right", "--count", f"HEAD...{target}"]).stdout.decode().split()
    ahead, behind = (int(value) for value in counts)
    changed = branch_changed_paths(target)
    stat = run_git(["diff", "--stat", "HEAD..." + target]).stdout.decode("utf-8", errors="replace")
    difference = run_git(
        ["diff", "--no-ext-diff", "--unified=3", "HEAD..." + target, "--", "configuration.yaml", "packages"]
    ).stdout.decode("utf-8", errors="replace")
    lines = difference.splitlines()
    token = hashlib.sha256(f"{head}\0{target}\0{branch}".encode("utf-8")).hexdigest()
    return {
        "branch": branch,
        "current": current,
        "head": head,
        "target": target,
        "stateVersion": token,
        "ahead": ahead,
        "behind": behind,
        "files": changed,
        "stat": stat,
        "diff": "\n".join(lines[:2000]),
        "truncated": len(lines) > 2000,
    }


def merge_git_branch(raw_branch: Any, state_version: Any) -> dict[str, Any]:
    configuration_check: dict[str, Any] | None = None
    with file_lock, git_lock:
        try:
            git_commit_paths(
                [configuration_file(), PACKAGES_ROOT],
                "Stand vor dem Zusammenführen eines Git-Branches",
            )
            preview = branch_merge_preview(raw_branch)
            if not isinstance(state_version, str) or state_version != preview["stateVersion"]:
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    "Die Branch-Stände haben sich seit dem Vergleich geändert. Bitte erneut vergleichen.",
                )
            if preview["behind"] == 0:
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    "Der ausgewählte Branch enthält keine neuen Commits für den aktiven Branch.",
                )
            validate_branch_yaml(preview["target"], preview["files"])
            backup_changed_yaml(preview["files"])
            merge = run_git(
                ["merge", "--no-commit", "--no-ff", preview["branch"]],
                allowed_codes=(0, 1),
            )
            if merge.returncode != 0:
                run_git(["merge", "--abort"], allowed_codes=(0, 1, 128))
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    "Der Branch konnte wegen Dateikonflikten nicht zusammengeführt werden.",
                )
            invalid: list[str] = []
            configuration = configuration_file()
            if configuration.is_file():
                validation = validate_yaml(read_yaml_text(configuration))
                if not validation["valid"]:
                    invalid.append("configuration.yaml")
            for path, content in package_contents().items():
                if not validate_yaml(content)["valid"]:
                    invalid.append(f"packages/{path}")
            if invalid:
                run_git(["merge", "--abort"], allowed_codes=(0, 1, 128))
                raise ApiError(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    "Der Merge würde ungültiges YAML erzeugen und wurde abgebrochen.",
                    {"files": invalid},
                )
            run_git(
                [
                    "-c", "user.name=YAML Script Manager",
                    "-c", "user.email=yaml-script-manager@local",
                    "commit", "--no-gpg-sign", "--no-verify", "-m",
                    f"Git-Branch zusammengeführt: {preview['branch']}",
                ]
            )
            configuration_check = check_home_assistant_configuration()
        except GitOperationError as exc:
            run_git(["merge", "--abort"], allowed_codes=(0, 1, 128))
            raise ApiError(HTTPStatus.CONFLICT, str(exc)) from exc
    return {
        **git_branches(),
        "message": f"Branch {preview['branch']} wurde zusammengeführt.",
        "configurationCheck": configuration_check,
    }


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
        return {**result, "available": True, "ahead": 0, "behind": 0, "diverged": False, "dirty": False}
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
                "diverged": bool(ahead and behind),
                "dirty": dirty,
                "currentBranch": current_branch,
            }
        except GitOperationError as exc:
            return {**result, "available": False, "message": str(exc), "ahead": 0, "behind": 0, "diverged": False, "dirty": False}


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
    auto_push = body.get("autoPush", existing.get("autoPush", True))
    if not isinstance(auto_push, bool):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Die Auto-Push-Einstellung ist ungültig.")
    config = {
        "url": url,
        "provider": provider,
        "branch": branch,
        "username": username,
        "token": token,
        "autoPush": auto_push,
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


def auto_push_after_change(git_result: dict[str, Any] | None = None) -> dict[str, Any]:
    config = load_git_remote_config()
    enabled = bool(config.get("url")) and bool(config.get("autoPush", True))
    if not enabled:
        return {
            "enabled": False,
            "success": True,
            "message": "Automatischer Git-Push ist nicht aktiviert.",
        }
    if git_result is not None and not git_result.get("committed"):
        return {
            "enabled": True,
            "success": True,
            "skipped": True,
            "message": "Keine neue Git-Änderung zum Pushen vorhanden.",
        }
    security = security_push_warning()
    if not security.get("ok", True):
        return {
            "enabled": True,
            "success": False,
            "blocked": True,
            "message": f"Datei gespeichert, automatischer Git-Push wegen {security['count']} Sicherheits-Hinweisen blockiert.",
            "security": security,
        }
    try:
        result = synchronize_git_remote("push")
        return {
            "enabled": True,
            "success": True,
            "message": "Lokaler Commit wurde automatisch zum Git-Remote gepusht.",
            "ahead": result.get("ahead", 0),
            "behind": result.get("behind", 0),
        }
    except ApiError as exc:
        return {
            "enabled": True,
            "success": False,
            "message": f"Datei gespeichert, automatischer Git-Push fehlgeschlagen: {exc.message}",
            **exc.details,
        }


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


def validate_remote_yaml(reference: str, relative: str) -> None:
    tree = run_git(["ls-tree", reference, "--", relative]).stdout.decode().strip()
    if relative == "configuration.yaml" and not tree:
        raise ApiError(HTTPStatus.CONFLICT, "Der Remote-Stand würde configuration.yaml löschen.")
    if not tree:
        return
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


def safe_remote_auxiliary_path(relative: str) -> bool:
    documentation_pattern = re.compile(
        r"(?:README|LICENSE|CHANGELOG)(?:\.[A-Za-z0-9_.-]+)?$",
        re.IGNORECASE,
    )
    return relative in {".gitignore", ".gitattributes"} or bool(documentation_pattern.fullmatch(relative))


def validate_remote_auxiliary_file(reference: str, relative: str) -> None:
    tree = run_git(["ls-tree", reference, "--", relative]).stdout.decode().strip()
    if not tree:
        return
    if tree.split(None, 1)[0] not in {"100644", "100755"}:
        raise ApiError(HTTPStatus.CONFLICT, f"{relative} ist im Remote kein regulärer Dateieintrag.")
    size = int(run_git(["cat-file", "-s", f"{reference}:{relative}"]).stdout.decode().strip())
    if size > MAX_FILE_SIZE:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"{relative} ist im Remote größer als 2 MiB.")


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
        elif safe_remote_auxiliary_path(relative):
            validate_remote_auxiliary_file(reference, relative)
            continue
        else:
            raise ApiError(HTTPStatus.CONFLICT, "Der Remote-Stand verändert Dateien außerhalb von configuration.yaml und packages.")
        validate_remote_yaml(reference, relative)
        if absolute.is_file():
            create_backup(backup_relative, absolute)
    return changed


def prepare_remote_history_merge(branch: str) -> list[str]:
    reference = f"refs/remotes/{GIT_REMOTE_NAME}/{branch}"
    output = run_git(["ls-tree", "-r", "--name-only", reference]).stdout.decode("utf-8", errors="replace")
    paths = [path for path in output.splitlines() if path]
    for relative in paths:
        if relative == "configuration.yaml":
            absolute = configuration_file()
            backup_relative = "configuration/configuration.yaml"
            validate_remote_yaml(reference, relative)
        elif relative.startswith("packages/"):
            package_relative = relative.removeprefix("packages/")
            _normalized, absolute = normalize_relative_path(package_relative)
            backup_relative = package_relative
            validate_remote_yaml(reference, relative)
        elif safe_remote_auxiliary_path(relative):
            validate_remote_auxiliary_file(reference, relative)
            continue
        else:
            raise ApiError(
                HTTPStatus.CONFLICT,
                f"Der Remote enthält den nicht verwalteten Pfad {relative}. Die Historien werden nicht automatisch verbunden.",
            )
        if absolute.is_file():
            create_backup(backup_relative, absolute)
    return paths


def synchronize_git_remote(action: str) -> dict[str, Any]:
    if action not in {"fetch", "pull", "push", "sync", "merge", "force-push"}:
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
            if action == "merge":
                if not remote_exists:
                    raise ApiError(HTTPStatus.CONFLICT, "Der Remote-Branch existiert noch nicht und muss nur regulär gepusht werden.")
                prepare_remote_history_merge(branch)
                merge = run_git(
                    [
                        "-c", "user.name=YAML Script Manager",
                        "-c", "user.email=yaml-script-manager@local",
                        "merge", "--allow-unrelated-histories", "--no-edit", "--no-gpg-sign", reference,
                    ],
                    allowed_codes=(0, 1),
                )
                if merge.returncode != 0:
                    run_git(["merge", "--abort"], allowed_codes=(0, 1, 128))
                    raise ApiError(
                        HTTPStatus.CONFLICT,
                        "Die Historien konnten wegen Dateikonflikten nicht automatisch verbunden werden. Verwende einen externen Git-Client oder ersetze den Remote bewusst mit dem lokalen Stand.",
                    )
                configuration_check = check_home_assistant_configuration()
                run_git_remote(
                    ["push", "--set-upstream", GIT_REMOTE_NAME, f"HEAD:refs/heads/{branch}"],
                    config,
                )
                run_git(["update-ref", reference, "HEAD"])
                ahead, behind = git_ahead_behind(branch)
            elif action == "force-push":
                if not remote_exists:
                    raise ApiError(HTTPStatus.CONFLICT, "Der Remote-Branch existiert noch nicht. Verwende einen regulären Push.")
                remote_commit = remote_check.stdout.decode("ascii", errors="ignore").split(None, 1)[0]
                run_git_remote(
                    [
                        "push",
                        f"--force-with-lease=refs/heads/{branch}:{remote_commit}",
                        "--set-upstream",
                        GIT_REMOTE_NAME,
                        f"HEAD:refs/heads/{branch}",
                    ],
                    config,
                )
                run_git(["update-ref", reference, "HEAD"])
                ahead, behind = git_ahead_behind(branch)
            if action in {"pull", "sync"} and remote_exists:
                if ahead and behind:
                    raise ApiError(
                        HTTPStatus.CONFLICT,
                        "Lokaler und Remote-Stand sind auseinander gelaufen.",
                        {
                            "ahead": ahead,
                            "behind": behind,
                            "resolutionOptions": ["merge", "force-push"],
                        },
                    )
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
                run_git(["update-ref", reference, "HEAD"])
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
