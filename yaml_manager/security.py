"""Secret and plaintext credential checks for managed YAML files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

try:
    from .validation import HomeAssistantLoader
except ImportError:  # pragma: no cover - direct execution in the app container
    from validation import HomeAssistantLoader


SECRET_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth_token",
    "bearer_token",
    "client_secret",
    "password",
    "refresh_token",
    "secret",
    "token",
    "webhook_id",
}
SECRET_KEY_PATTERN = re.compile(
    r"(?i)\b(?:access[_-]?token|api[_-]?key|auth[_-]?token|bearer[_-]?token|client[_-]?secret|password|refresh[_-]?token|secret|token|webhook[_-]?id)\b"
)
SECRET_VALUE_PATTERN = re.compile(r"(?i)(?:token|apikey|api_key|secret|password)[=:]\s*['\"]?[A-Za-z0-9_./+=:-]{16,}")
LONG_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_./+=:-]{32,}$")
URL_SECRET_PATTERN = re.compile(r"(?i)[?&](?:token|api_key|apikey|auth|key|secret)=[^&\s]{8,}")


def _line_for_offset(content: str, offset: int) -> int:
    return content.count("\n", 0, max(0, offset)) + 1


def _load_secrets(backend: Any) -> tuple[set[str], bool]:
    path = backend.PACKAGES_ROOT.resolve().parent / "secrets.yaml"
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return set(), False
    except OSError:
        return set(), True
    try:
        document = yaml.load(content, Loader=HomeAssistantLoader)
    except yaml.YAMLError:
        return set(), True
    if not isinstance(document, dict):
        return set(), True
    return {str(key) for key in document}, True


def _secret_references(content: str) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []

    def visit(node: yaml.Node | None, source_key: str = "") -> None:
        if isinstance(node, yaml.ScalarNode):
            if node.tag == "!secret":
                references.append(
                    {
                        "name": node.value,
                        "line": node.start_mark.line + 1,
                        "sourceKey": source_key,
                    }
                )
            return
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                key = key_node.value if isinstance(key_node, yaml.ScalarNode) else source_key
                visit(value_node, str(key))
        elif isinstance(node, yaml.SequenceNode):
            for child in node.value:
                visit(child, source_key)

    try:
        for document in yaml.compose_all(content, Loader=HomeAssistantLoader):
            visit(document)
    except yaml.YAMLError:
        return references
    return references


def _plaintext_findings(path: str, content: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for index, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "!secret" in stripped:
            continue
        if URL_SECRET_PATTERN.search(stripped):
            findings.append(
                {
                    "severity": "warning",
                    "code": "plaintext-secret-url",
                    "title": "Token in URL erkannt",
                    "message": "Ein URL-Parameter sieht nach einem Klartext-Token aus. Verwende nach Möglichkeit !secret.",
                    "files": [path],
                    "line": index,
                }
            )
            continue
        if SECRET_VALUE_PATTERN.search(stripped):
            findings.append(
                {
                    "severity": "warning",
                    "code": "plaintext-secret",
                    "title": "Möglicher Klartext-Secret-Wert",
                    "message": "Diese Zeile enthält einen secret-typischen Schlüssel mit langem Wert.",
                    "files": [path],
                    "line": index,
                }
            )
            continue
        key_match = re.match(r"^\s*([A-Za-z0-9_.-]+)\s*:\s*['\"]?([^'\"#\s][^#\s]*)", line)
        if not key_match:
            continue
        key, value = key_match.groups()
        if SECRET_KEY_PATTERN.search(key) and LONG_VALUE_PATTERN.fullmatch(value.strip()):
            findings.append(
                {
                    "severity": "warning",
                    "code": "plaintext-secret",
                    "title": f"„{key}“ wirkt wie ein Klartext-Secret",
                    "message": "Der Wert ist lang genug, um ein Token oder Passwort zu sein. Prüfe eine Auslagerung nach secrets.yaml.",
                    "files": [path],
                    "line": index,
                }
            )
    return findings


def _literal_secret_keys(content: str) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    for match in SECRET_KEY_PATTERN.finditer(content):
        result.append((match.group(0), _line_for_offset(content, match.start())))
    return result


def security_scan(backend: Any) -> dict[str, Any]:
    files = backend.managed_yaml_files()
    known_secrets, secrets_file_exists = _load_secrets(backend)
    findings: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []

    for path, content in sorted(files.items()):
        for reference in _secret_references(content):
            item = {"path": path, **reference, "exists": reference["name"] in known_secrets}
            references.append(item)
            if not secrets_file_exists:
                findings.append(
                    {
                        "severity": "error",
                        "code": "missing-secrets-file",
                        "title": "secrets.yaml fehlt",
                        "message": f"{path} verwendet !secret, aber secrets.yaml wurde nicht gefunden.",
                        "files": [path],
                        "line": reference["line"],
                    }
                )
            elif reference["name"] not in known_secrets:
                findings.append(
                    {
                        "severity": "error",
                        "code": "missing-secret",
                        "title": f'!secret „{reference["name"]}“ fehlt',
                        "message": "Dieser Secret-Name ist in secrets.yaml nicht definiert.",
                        "files": [path],
                        "line": reference["line"],
                    }
                )
        findings.extend(_plaintext_findings(path, content))

    secret_like_keys = {
        key.casefold()
        for _path, content in files.items()
        for key, _line in _literal_secret_keys(content)
    }
    unused = sorted(
        secret for secret in known_secrets
        if secret.casefold() not in {reference["name"].casefold() for reference in references}
        and secret.casefold() not in secret_like_keys
    )
    for secret in unused[:20]:
        findings.append(
            {
                "severity": "tip",
                "code": "possibly-unused-secret",
                "title": f'!secret „{secret}“ möglicherweise ungenutzt',
                "message": "Keine verwaltete YAML-Datei referenziert diesen Secret-Namen.",
                "files": ["secrets.yaml"],
            }
        )

    order = {"error": 0, "warning": 1, "tip": 2}
    findings.sort(key=lambda item: (order.get(item["severity"], 3), item.get("files", [""])[0], item.get("line", 0)))
    counts = {
        severity: sum(item["severity"] == severity for item in findings)
        for severity in ("error", "warning", "tip")
    }
    return {
        "available": True,
        "secretsFile": {
            "exists": secrets_file_exists,
            "path": str(backend.PACKAGES_ROOT.resolve().parent / "secrets.yaml"),
            "defined": len(known_secrets),
        },
        "references": references,
        "findings": findings,
        "counts": counts,
        "summary": {
            "files": len(files),
            "references": len(references),
            "missing": counts["error"],
            "plaintext": sum(item["code"].startswith("plaintext-secret") for item in findings),
            "unused": sum(item["code"] == "possibly-unused-secret" for item in findings),
        },
    }


def security_push_warning(backend: Any) -> dict[str, Any]:
    result = security_scan(backend)
    risky = [
        item for item in result["findings"]
        if item["severity"] in {"error", "warning"} and item["code"] != "possibly-unused-secret"
    ]
    return {
        "ok": not risky,
        "count": len(risky),
        "findings": risky[:10],
        "summary": result["summary"],
    }
