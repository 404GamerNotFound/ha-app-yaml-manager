"""Configurable Home Assistant YAML lint checks."""

from __future__ import annotations

import re
from typing import Any

import yaml

try:
    from .validation import HomeAssistantLoader
except ImportError:  # pragma: no cover - direct execution in the app container
    from validation import HomeAssistantLoader


DEFAULT_LINT_RULES: dict[str, Any] = {
    "requireAlias": True,
    "requireAutomationId": True,
    "requireScriptMode": True,
    "scriptIdPattern": r"^[a-z0-9_]+$",
    "entityIdPattern": r"^[a-z0-9_]+\.[a-z0-9_]+$",
    "allowedEntityDomains": [],
    "forbiddenPlaintext": [],
    "requiredTags": [],
}

ENTITY_PATTERN = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z0-9_]+\.[A-Za-z0-9_.-]+)(?![A-Za-z0-9_])")
SECRETISH_KEY_PATTERN = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|password|secret|token)\b"
)


def _list(value: Any, limit: int = 50) -> list[str]:
    if isinstance(value, str):
        source = value.split(",")
    elif isinstance(value, list):
        source = value
    else:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in source:
        text = str(item).strip()
        if not text:
            continue
        text = text[:80]
        folded = text.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def sanitize_lint_rules(raw: Any) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    rules = dict(DEFAULT_LINT_RULES)
    for key in ("requireAlias", "requireAutomationId", "requireScriptMode"):
        rules[key] = bool(source.get(key, rules[key]))
    for key in ("scriptIdPattern", "entityIdPattern"):
        value = source.get(key, rules[key])
        if not isinstance(value, str) or len(value) > 160:
            value = rules[key]
        try:
            re.compile(value)
        except re.error:
            value = rules[key]
        rules[key] = value
    rules["allowedEntityDomains"] = [
        item
        for item in _list(source.get("allowedEntityDomains"))
        if re.fullmatch(r"[a-z0-9_]+", item)
    ]
    rules["forbiddenPlaintext"] = _list(source.get("forbiddenPlaintext"), 30)
    rules["requiredTags"] = _list(source.get("requiredTags"), 20)
    return rules


def _mapping_pair(node: yaml.Node | None, key: str) -> tuple[yaml.ScalarNode, yaml.Node] | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    for key_node, value_node in node.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            return key_node, value_node
    return None


def _scalar(node: yaml.Node | None) -> str:
    return node.value if isinstance(node, yaml.ScalarNode) else ""


def _node_has_key(node: yaml.Node | None, key: str) -> bool:
    return _mapping_pair(node, key) is not None


def _line(node: yaml.Node | None) -> int | None:
    return node.start_mark.line + 1 if node is not None else None


def _finding(
    severity: str,
    code: str,
    title: str,
    message: str,
    path: str,
    line: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "severity": severity,
        "code": code,
        "title": title,
        "message": message,
        "files": [path],
    }
    if line:
        result["line"] = line
    return result


def _check_scripts(
    path: str,
    script_node: yaml.Node | None,
    rules: dict[str, Any],
    findings: list[dict[str, Any]],
) -> None:
    if not isinstance(script_node, yaml.MappingNode):
        return
    script_id_pattern = re.compile(rules["scriptIdPattern"])
    for key_node, definition in script_node.value:
        if not isinstance(key_node, yaml.ScalarNode):
            continue
        script_id = str(key_node.value)
        if not script_id_pattern.fullmatch(script_id):
            findings.append(
                _finding(
                    "warning",
                    "lint-script-id-pattern",
                    f'Script-ID "{script_id}" passt nicht zur Regel',
                    f"Erwartetes Muster: {rules['scriptIdPattern']}",
                    path,
                    _line(key_node),
                )
            )
        if not isinstance(definition, yaml.MappingNode):
            continue
        if rules["requireAlias"] and not _scalar(_mapping_pair(definition, "alias")[1] if _mapping_pair(definition, "alias") else None):
            findings.append(
                _finding(
                    "tip",
                    "lint-missing-alias",
                    f'Alias fuer Script "{script_id}" fehlt',
                    "Die aktive Lint-Regel verlangt einen sprechenden alias.",
                    path,
                    _line(key_node),
                )
            )
        if rules["requireScriptMode"] and not _node_has_key(definition, "mode"):
            findings.append(
                _finding(
                    "tip",
                    "lint-missing-script-mode",
                    f'Modus fuer Script "{script_id}" fehlt',
                    "Die aktive Lint-Regel verlangt ein explizites mode-Feld.",
                    path,
                    _line(key_node),
                )
            )


def _check_sequence_objects(
    domain: str,
    path: str,
    node: yaml.Node | None,
    rules: dict[str, Any],
    findings: list[dict[str, Any]],
) -> None:
    if not isinstance(node, yaml.SequenceNode):
        return
    for index, definition in enumerate(node.value, start=1):
        if not isinstance(definition, yaml.MappingNode):
            continue
        alias = _scalar(_mapping_pair(definition, "alias")[1] if _mapping_pair(definition, "alias") else None)
        name = _scalar(_mapping_pair(definition, "name")[1] if _mapping_pair(definition, "name") else None)
        item_id = _scalar(_mapping_pair(definition, "id")[1] if _mapping_pair(definition, "id") else None)
        label = alias or name or item_id or f"{domain} #{index}"
        if rules["requireAlias"] and not (alias or name):
            findings.append(
                _finding(
                    "tip",
                    "lint-missing-alias",
                    f'Alias fuer {domain} "{label}" fehlt',
                    "Die aktive Lint-Regel verlangt einen sprechenden alias oder name.",
                    path,
                    _line(definition),
                )
            )
        if domain == "automation" and rules["requireAutomationId"] and not item_id:
            findings.append(
                _finding(
                    "warning",
                    "lint-missing-automation-id",
                    f'Automation "{label}" hat keine id',
                    "Die aktive Lint-Regel verlangt eine stabile Automation-ID.",
                    path,
                    _line(definition),
                )
            )


def _check_mapping_objects(
    domain: str,
    path: str,
    node: yaml.Node | None,
    rules: dict[str, Any],
    findings: list[dict[str, Any]],
) -> None:
    if not isinstance(node, yaml.MappingNode):
        return
    for key_node, definition in node.value:
        if not isinstance(key_node, yaml.ScalarNode) or not isinstance(definition, yaml.MappingNode):
            continue
        alias = _scalar(_mapping_pair(definition, "alias")[1] if _mapping_pair(definition, "alias") else None)
        name = _scalar(_mapping_pair(definition, "name")[1] if _mapping_pair(definition, "name") else None)
        if rules["requireAlias"] and not (alias or name):
            findings.append(
                _finding(
                    "tip",
                    "lint-missing-alias",
                    f'Alias fuer {domain} "{key_node.value}" fehlt',
                    "Die aktive Lint-Regel verlangt einen sprechenden alias oder name.",
                    path,
                    _line(key_node),
                )
            )


def _check_entities(path: str, content: str, rules: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    entity_pattern = re.compile(rules["entityIdPattern"])
    allowed_domains = set(rules.get("allowedEntityDomains", []))
    seen: set[tuple[str, int, str]] = set()
    for match in ENTITY_PATTERN.finditer(content):
        entity_id = match.group(1)
        line = content.count("\n", 0, match.start()) + 1
        domain = entity_id.split(".", 1)[0]
        if not entity_pattern.fullmatch(entity_id) and (entity_id, line, "pattern") not in seen:
            seen.add((entity_id, line, "pattern"))
            findings.append(
                _finding(
                    "warning",
                    "lint-entity-id-pattern",
                    f'Entity-ID "{entity_id}" passt nicht zur Regel',
                    f"Erwartetes Muster: {rules['entityIdPattern']}",
                    path,
                    line,
                )
            )
        if allowed_domains and domain not in allowed_domains and (entity_id, line, "domain") not in seen:
            seen.add((entity_id, line, "domain"))
            findings.append(
                _finding(
                    "warning",
                    "lint-entity-domain",
                    f'Entity-Domain "{domain}" ist nicht erlaubt',
                    f"Erlaubt: {', '.join(sorted(allowed_domains))}",
                    path,
                    line,
                )
            )
    return findings


def _check_plaintext(path: str, content: str, rules: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    forbidden = [item.casefold() for item in rules.get("forbiddenPlaintext", [])]
    for index, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "!secret" in stripped:
            continue
        folded = stripped.casefold()
        if any(item in folded for item in forbidden):
            findings.append(
                _finding(
                    "warning",
                    "lint-forbidden-plaintext",
                    "Verbotener Klartext-Ausdruck gefunden",
                    "Diese Zeile trifft eine konfigurierbare Lint-Regel.",
                    path,
                    index,
                )
            )
            continue
        if SECRETISH_KEY_PATTERN.search(stripped) and ":" in stripped and "!secret" not in stripped:
            findings.append(
                _finding(
                    "tip",
                    "lint-secret-candidate",
                    "Secret-typischer Klartext-Schluessel",
                    "Pruefe, ob dieser Wert nach secrets.yaml ausgelagert werden soll.",
                    path,
                    index,
                )
            )
    return findings


def lint_content(
    backend: Any,
    path: str,
    content: str,
    rules: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    rules = sanitize_lint_rules(rules or backend.load_settings().get("lintRules"))
    findings: list[dict[str, Any]] = []
    try:
        documents = list(yaml.compose_all(content, Loader=HomeAssistantLoader))
    except yaml.YAMLError:
        return findings
    for document in documents:
        if not isinstance(document, yaml.MappingNode):
            continue
        script_pair = _mapping_pair(document, "script")
        if script_pair:
            _check_scripts(path, script_pair[1], rules, findings)
        for domain in ("automation", "scene"):
            pair = _mapping_pair(document, domain)
            if not pair:
                continue
            _check_sequence_objects(domain, path, pair[1], rules, findings)
            _check_mapping_objects(domain, path, pair[1], rules, findings)
    findings.extend(_check_entities(path, content, rules))
    findings.extend(_check_plaintext(path, content, rules))
    required_tags = set(rules.get("requiredTags", []))
    if required_tags and path.startswith("packages/"):
        present = set(tags or [])
        missing = sorted(required_tags - present, key=str.casefold)
        if missing:
            findings.append(
                _finding(
                    "tip",
                    "lint-missing-required-tag",
                    f"{path} hat nicht alle Pflicht-Tags",
                    f"Fehlt: {', '.join(missing)}",
                    path,
                )
            )
    return findings


def lint_scan(
    backend: Any,
    files: dict[str, str] | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rules = sanitize_lint_rules(rules or backend.load_settings().get("lintRules"))
    files = files if files is not None else backend.managed_yaml_files()
    metadata = backend.load_metadata()
    findings: list[dict[str, Any]] = []
    for path, content in sorted(files.items()):
        tags: list[str] = []
        if path.startswith("packages/"):
            package_path = path.removeprefix("packages/")
            tags = backend.file_metadata(metadata, package_path).get("tags", [])
        findings.extend(lint_content(backend, path, content, rules, tags))
    order = {"error": 0, "warning": 1, "tip": 2}
    findings.sort(
        key=lambda item: (
            order.get(item.get("severity", ""), 3),
            item.get("files", [""])[0],
            item.get("line", 0),
            item.get("title", "").casefold(),
        )
    )
    counts = {
        severity: sum(item.get("severity") == severity for item in findings)
        for severity in ("error", "warning", "tip")
    }
    return {
        "rules": rules,
        "findings": findings,
        "counts": counts,
        "summary": {
            "files": len(files),
            "warnings": counts["warning"],
            "tips": counts["tip"],
        },
    }
