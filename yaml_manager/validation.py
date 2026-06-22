"""Home Assistant aware YAML loading and validation."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

import yaml

try:
    from .errors import ApiError
except ImportError:  # pragma: no cover - direct execution in the app container
    from errors import ApiError


class HomeAssistantLoader(yaml.SafeLoader):
    """Safe YAML loader that accepts Home Assistant's custom tags."""


def _construct_mapping(
    loader: HomeAssistantLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
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


def _construct_unknown(
    loader: HomeAssistantLoader,
    _suffix: str,
    node: yaml.Node,
) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


HomeAssistantLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)
HomeAssistantLoader.add_multi_constructor("!", _construct_unknown)


def validate_yaml(content: str, max_file_size: int) -> dict[str, Any]:
    """Validate YAML while preserving Home Assistant tag compatibility."""

    if not isinstance(content, str):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Der YAML-Inhalt fehlt.")
    if len(content.encode("utf-8")) > max_file_size:
        raise ApiError(
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            "Der Inhalt ist groesser als 2 MiB.",
        )
    try:
        documents = list(yaml.load_all(content, Loader=HomeAssistantLoader))
        return {
            "valid": True,
            "documents": len(documents),
            "message": "YAML ist syntaktisch gueltig.",
        }
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
        problem = getattr(exc, "problem", None) or str(exc).split("\n", 1)[0]
        result: dict[str, Any] = {"valid": False, "message": str(problem)}
        if mark is not None:
            result.update({"line": mark.line + 1, "column": mark.column + 1})
        return result
