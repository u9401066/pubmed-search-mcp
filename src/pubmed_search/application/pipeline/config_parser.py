"""Bounded YAML/JSON parsing for pipeline configuration documents.

Pipeline configuration is accepted from MCP arguments, saved files, and the
unified-search inline mode.  All three entry points must enforce the same
resource and syntax policy before schema validation.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

import yaml

from pubmed_search.shared.credential_sanitizer import contains_credential_material

MAX_PIPELINE_CONFIG_CHARS = 100_000
MAX_PIPELINE_CONFIG_DEPTH = 24
MAX_PIPELINE_CONFIG_NODES = 2_000


class _BoundedSafeLoader(yaml.SafeLoader):
    """SafeLoader that rejects aliases and stops oversized trees while composing."""

    def __init__(self, stream: Any) -> None:
        super().__init__(stream)
        self._pipeline_depth = 0
        self._pipeline_nodes = 0

    def compose_node(self, parent: Any, index: Any) -> yaml.Node | None:
        if self.check_event(yaml.AliasEvent):
            raise yaml.YAMLError("YAML aliases are not supported in pipeline configs")

        self._pipeline_depth += 1
        self._pipeline_nodes += 1
        try:
            if self._pipeline_depth > MAX_PIPELINE_CONFIG_DEPTH:
                raise yaml.YAMLError(f"Pipeline config exceeds the maximum depth of {MAX_PIPELINE_CONFIG_DEPTH}")
            if self._pipeline_nodes > MAX_PIPELINE_CONFIG_NODES:
                raise yaml.YAMLError(f"Pipeline config exceeds the maximum node count of {MAX_PIPELINE_CONFIG_NODES}")
            return super().compose_node(parent, index)
        finally:
            self._pipeline_depth -= 1


def _validate_tree_bounds(value: Any) -> None:
    """Apply identical post-parse bounds to JSON and YAML values."""

    nodes = 0
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > MAX_PIPELINE_CONFIG_NODES:
            msg = f"Pipeline config exceeds the maximum node count of {MAX_PIPELINE_CONFIG_NODES}"
            raise ValueError(msg)
        if depth > MAX_PIPELINE_CONFIG_DEPTH:
            msg = f"Pipeline config exceeds the maximum depth of {MAX_PIPELINE_CONFIG_DEPTH}"
            raise ValueError(msg)

        if isinstance(current, Mapping):
            for key, item in current.items():
                stack.append((key, depth + 1))
                stack.append((item, depth + 1))
        elif isinstance(current, Sequence) and not isinstance(current, str | bytes | bytearray):
            stack.extend((item, depth + 1) for item in current)


def _short_parser_error(exc: BaseException) -> str:
    """Return one bounded, path-free parser diagnostic."""

    first_line = str(exc).splitlines()[0].strip()
    return first_line[:240] or type(exc).__name__


def parse_pipeline_config_text(text: str) -> dict[str, Any]:
    """Parse one bounded pipeline YAML/JSON mapping.

    JSON objects use the standard JSON decoder first.  Other documents use a
    bounded ``SafeLoader``; unsafe Python tags and YAML aliases are rejected.
    The result must be a mapping because scalar/list documents are not pipeline
    configurations.
    """

    if not isinstance(text, str):
        msg = "Pipeline config must be text"
        raise TypeError(msg)
    if len(text) > MAX_PIPELINE_CONFIG_CHARS:
        msg = f"Pipeline config exceeds the maximum length of {MAX_PIPELINE_CONFIG_CHARS} characters"
        raise ValueError(msg)
    if not text.strip():
        msg = "Pipeline config cannot be empty"
        raise ValueError(msg)
    if contains_credential_material(text):
        msg = "Pipeline config contains credential material; use server environment configuration instead"
        raise ValueError(msg)

    parsed: Any = None
    stripped = text.lstrip()
    if stripped.startswith("{"):
        with suppress(json.JSONDecodeError, RecursionError):
            parsed = json.loads(text)

    if parsed is None:
        try:
            # This is a SafeLoader subclass that adds composition limits and
            # rejects aliases; FullLoader/UnsafeLoader constructors remain
            # unavailable by design.
            parsed = yaml.load(text, Loader=_BoundedSafeLoader)  # noqa: S506  # nosec B506
        except (RecursionError, yaml.YAMLError) as exc:
            detail = _short_parser_error(exc)
            msg = f"Invalid pipeline YAML/JSON: {detail}"
            raise ValueError(msg) from None

    _validate_tree_bounds(parsed)
    if not isinstance(parsed, dict):
        msg = f"Pipeline config must be a YAML or JSON mapping (dict), got {type(parsed).__name__}"
        raise ValueError(msg)  # noqa: TRY004 - valid text with the wrong document shape
    return cast("dict[str, Any]", parsed)


def parse_pipeline_config_file(path: str | Path) -> dict[str, Any]:
    """Read and parse a pipeline file without loading an oversized file."""

    resolved = Path(path)
    try:
        with resolved.open(encoding="utf-8") as handle:
            text = handle.read(MAX_PIPELINE_CONFIG_CHARS + 1)
    except UnicodeDecodeError as exc:
        msg = "Pipeline config file must be UTF-8 text"
        raise ValueError(msg) from exc
    return parse_pipeline_config_text(text)


__all__ = [
    "MAX_PIPELINE_CONFIG_CHARS",
    "MAX_PIPELINE_CONFIG_DEPTH",
    "MAX_PIPELINE_CONFIG_NODES",
    "parse_pipeline_config_file",
    "parse_pipeline_config_text",
]
