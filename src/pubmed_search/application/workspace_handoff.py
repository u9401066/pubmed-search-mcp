"""Map durable research references to explicit follow-up calls without performing I/O."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from pubmed_search.application.pipeline.validator import PIPELINE_NAME_PATTERN
from pubmed_search.domain.value_objects import IdentifierValidationError, normalize_doi, normalize_pmcid, normalize_pmid

if TYPE_CHECKING:
    from collections.abc import Iterable


_SESSION_RESOURCE = re.compile(r"([A-Za-z0-9][A-Za-z0-9_.-]{0,79})/([A-Za-z0-9][A-Za-z0-9_.-]{0,511})")
_REVISION = re.compile(r"([A-Za-z0-9][A-Za-z0-9_.-]{0,199})@([1-9][0-9]{0,9})")


def _lookup(reference: str) -> tuple[str, dict[str, Any]] | None:
    kind, _, value = reference.partition(":")
    if kind == "pmid":
        return "fetch_article_details", {"pmids": normalize_pmid(value), "output_format": "json"}
    if kind in {"doi", "pmcid"}:
        identifier = normalize_doi(value) if kind == "doi" else normalize_pmcid(value)
        return "get_fulltext", {"source": {"kind": kind, "value": identifier}, "output_format": "json"}
    if kind == "artifact":
        uri = reference if reference.startswith("artifact://") else value
        if uri.startswith("artifact://") and _SESSION_RESOURCE.fullmatch(uri.removeprefix("artifact://")):
            return "read_session", {
                "request": {"action": "artifact", "locator": {"kind": "artifact_uri", "value": uri}}
            }
    if kind == "run" and (run := _SESSION_RESOURCE.fullmatch(value)):
        return "read_session", {"request": {"action": "search_run", "session_id": run[1], "run_id": run[2]}}
    if kind == "pipeline" and re.fullmatch(PIPELINE_NAME_PATTERN, value):
        return "load_pipeline", {"source": f"saved:{value}"}
    if kind == "chronicle" and (chronicle := _REVISION.fullmatch(value)) and int(chronicle[2]) <= 2_000_000_000:
        return "read_research_chronicle", {
            "request": {"action": "load", "chronicle_id": chronicle[1], "revision": int(chronicle[2])}
        }
    return None


def source_handoffs(source_refs: Iterable[str]) -> list[dict[str, Any]]:
    """Offer a call only for a recognized locator; preserve all original references on the record."""
    suggestions = []
    for reference in source_refs:
        try:
            lookup = _lookup(reference)
        except IdentifierValidationError:
            continue
        if lookup:
            tool, arguments = lookup
            suggestions.append({"source_ref": reference, "tool": tool, "arguments": arguments})
    return suggestions
