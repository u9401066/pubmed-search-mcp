"""Shared agent-oriented JSON helpers for MCP tool responses.

Design:
    This module centralizes structured response building for agents and MCP
    clients, including source counts, next-tool suggestions, and output-format
    negotiation between markdown, JSON, and TOON.

Maintenance:
    Keep schema-like payload shaping here so individual tools do not drift in
    their structured output contracts. When adding a new shared field, update
    these helpers first and let formatters consume the new contract.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal, TypedDict

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class SourceCountRow(TypedDict):
    """Normalized source count row for agent-facing JSON responses."""

    source: str
    returned: int
    total_available: int | None
    has_more: bool

ProvenanceKind = Literal["direct", "indirect", "derived", "mixed"]
OutputFormat = Literal["markdown", "json", "toon"]
StructuredOutputFormat = Literal["json", "toon"]


def normalize_output_format(value: str | None, default: OutputFormat = "markdown") -> OutputFormat:
    """Normalize output format to markdown/json/toon with a safe default."""
    if not isinstance(value, str):
        return default

    normalized = value.strip().lower()
    if normalized == "toon":
        return "toon"
    if normalized == "json":
        return "json"
    return default


def preferred_structured_output_format(
    value: OutputFormat | str | None,
    default: StructuredOutputFormat = "json",
) -> StructuredOutputFormat:
    """Resolve whether structured output should be emitted as JSON or TOON."""
    normalized = normalize_output_format(value, default=default)
    return "toon" if normalized == "toon" else "json"


def is_structured_output_format(value: OutputFormat | str | None) -> bool:
    """Return whether the requested format is one of the structured encodings."""
    return preferred_structured_output_format(value) in {"json", "toon"} and normalize_output_format(
        value,
        default="markdown",
    ) in {"json", "toon"}


def serialize_structured_payload(
    payload: Any,
    output_format: OutputFormat | StructuredOutputFormat | str = "json",
) -> str:
    """Serialize a structured payload as JSON or TOON."""
    normalized = preferred_structured_output_format(output_format)
    if normalized == "toon":
        try:
            import toons
        except ImportError as exc:  # pragma: no cover - guarded by runtime dependency
            raise RuntimeError("TOON output requested but the 'toons' package is not installed") from exc
        return toons.dumps(payload)

    return json.dumps(payload, ensure_ascii=False, indent=2)


def make_source_count_row(
    source: str,
    returned: int,
    total_available: int | None = None,
) -> SourceCountRow:
    """Build a standard source count row."""
    returned_count = int(returned or 0)
    total_count = int(total_available) if total_available is not None else None
    return {
        "source": source,
        "returned": returned_count,
        "total_available": total_count,
        "has_more": total_count is not None and total_count > returned_count,
    }


def sort_source_count_rows(rows: Sequence[SourceCountRow]) -> list[SourceCountRow]:
    """Sort source rows by signal strength for stable agent consumption."""
    return sorted(
        rows,
        key=lambda row: (
            int(row["total_available"] or row["returned"] or 0),
            int(row["returned"] or 0),
            str(row["source"]),
        ),
        reverse=True,
    )


def make_next_tool(tool: str, reason: str, command: str) -> dict[str, str]:
    """Build a standard tool-chaining suggestion."""
    return {
        "tool": tool,
        "reason": reason,
        "command": command,
        "example": command,
    }


def finalize_next_tools(
    suggestions: Sequence[Mapping[str, str]],
    *,
    max_items: int = 4,
) -> tuple[list[dict[str, str]], list[str]]:
    """Deduplicate next-tool suggestions and return both rich and flat command views."""
    seen_tools: set[str] = set()
    next_tools: list[dict[str, str]] = []

    for suggestion in suggestions:
        tool = str(suggestion.get("tool", "")).strip()
        command = str(suggestion.get("command") or suggestion.get("example") or "").strip()
        reason = str(suggestion.get("reason", "")).strip()
        if not tool or not command or tool in seen_tools:
            continue
        next_tools.append(make_next_tool(tool, reason, command))
        seen_tools.add(tool)
        if len(next_tools) >= max_items:
            break

    return next_tools, [suggestion["command"] for suggestion in next_tools]


def make_section_provenance(
    *,
    surfacing_source: str,
    canonical_host: str | None,
    provenance: ProvenanceKind,
    note: str,
    upstream_sources: Sequence[str] | None = None,
    fields: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build a standard section-level provenance descriptor."""
    entry: dict[str, Any] = {
        "surfacing_source": surfacing_source,
        "canonical_host": canonical_host,
        "provenance": provenance,
        "note": note,
    }
    if upstream_sources:
        entry["upstream_sources"] = list(dict.fromkeys(upstream_sources))
    if fields:
        entry["fields"] = list(fields)
    return entry
