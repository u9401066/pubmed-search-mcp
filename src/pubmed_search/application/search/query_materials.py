"""Query materials: conservative local fallbacks and data-driven MeSH candidates."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from .mesh_correction import cooccurrence_candidate_entry

if TYPE_CHECKING:
    from .mesh_correction import MeshCorrectionService

logger = logging.getLogger(__name__)


def build_fallback_query_materials(
    topic: str,
    *,
    strategy: str,
    include_suggestions: bool,
    fallback_reason: str,
) -> dict[str, Any]:
    """Offer unverified candidates for a validated topic without rewriting Boolean syntax."""
    queries: list[dict[str, Any]] = []
    if include_suggestions:
        if re.search(r'[()[\]"]|\b(?:AND|OR|NOT)\b', topic, re.IGNORECASE):
            queries.append({"id": "q_original", "query": topic, "purpose": "Original query, unverified", "priority": 1})
        else:
            queries.extend(
                [
                    {
                        "id": "q1_title",
                        "query": f"({topic})[Title]",
                        "purpose": "Title terms, not exact title identity",
                        "priority": 1,
                    },
                    {
                        "id": "q2_tiab",
                        "query": f"({topic})[Title/Abstract]",
                        "purpose": "Title or abstract",
                        "priority": 2,
                    },
                ]
            )
            words = topic.lower().split()
            if len(words) > 1:
                queries.append(
                    {
                        "id": "q3_and",
                        "query": "(" + " AND ".join(words) + ")",
                        "purpose": "All keywords required",
                        "priority": 2,
                    }
                )
            queries.append(
                {
                    "id": "q4_mesh",
                    "query": f"({topic})[MeSH Terms]",
                    "purpose": "Unverified MeSH candidate",
                    "priority": 2,
                }
            )
    return {
        "status": "partial",
        "generation_mode": "basic_fallback",
        "fallback_reason": fallback_reason,
        "topic": topic,
        "strategy": strategy,
        "spelling": None,
        "mesh_terms": [],
        "queries_count": len(queries),
        "suggested_queries": queries,
        "instruction": "Review the query materials, then execute unified_search; local query analysis cannot verify NCBI translation",
        "warnings": [
            "MeSH lookup and PubMed translation analysis were not available; suggested queries are unverified."
        ],
        "note": "Using explicit fallback generator (MeSH lookup unavailable)",
    }


DEFAULT_COOCCURRENCE_PHRASES = 2


async def attach_cooccurrence_candidates(
    materials: dict[str, Any],
    service: MeshCorrectionService | None,
    *,
    max_phrases: int = DEFAULT_COOCCURRENCE_PHRASES,
) -> dict[str, Any]:
    """Add data-driven MeSH candidates for ``unmapped_phrases`` to ``mesh_candidates``.

    Only phrases left unmapped by a completed exact MeSH lookup are tried,
    multi-word phrases first, at most ``max_phrases`` (NCBI cost per phrase:
    one evidence search, one MEDLINE fetch and two counts for each of up to
    ``policy.scored_candidates`` nominated headings, capped by the service's
    phrase budget). Entries carry ``reason="co_occurrence"`` with share and
    evidence; they are never added to ``mesh_terms`` or ``suggested_queries``.
    ``coverage["mesh_cooccurrence"]`` reports what was attempted and skipped.
    """
    coverage = materials.get("coverage")
    if not isinstance(coverage, dict):
        coverage = materials["coverage"] = {}
    raw_phrases = materials.get("unmapped_phrases")
    phrases = [phrase for phrase in raw_phrases if isinstance(phrase, str)] if isinstance(raw_phrases, list) else []
    mesh_status = coverage.get("mesh", {}).get("status") if isinstance(coverage.get("mesh"), dict) else None
    state: dict[str, Any] = {"status": "not_needed", "attempted": 0, "completed": 0, "failed": 0}
    if not phrases:
        coverage["mesh_cooccurrence"] = state
        return materials
    if service is None:
        coverage["mesh_cooccurrence"] = {**state, "status": "disabled"}
        return materials
    if mesh_status != "completed":
        coverage["mesh_cooccurrence"] = {**state, "status": "skipped", "reason": "exact MeSH lookup did not complete"}
        return materials
    try:
        suggestions = await service.suggest_for_phrases(phrases, max_phrases=max_phrases)
    except Exception as exc:
        logger.warning("Co-occurrence MeSH candidates failed (%s)", type(exc).__name__)
        coverage["mesh_cooccurrence"] = {**state, "status": "failed", "attempted": 1, "failed": 1}
        materials.setdefault("warnings", []).append("Co-occurrence MeSH candidates were unavailable.")
        return materials

    candidates = materials.setdefault("mesh_candidates", [])
    completed = failed = 0
    phrase_status: dict[str, str] = {}
    for report in suggestions.reports:
        phrase_status[report.phrase] = report.status
        if report.status == "failed":
            failed += 1
        else:
            completed += 1
        if report.candidates:
            candidates.append(cooccurrence_candidate_entry(report))
    attempted = len(suggestions.reports)
    coverage["mesh_cooccurrence"] = {
        "status": "completed" if not failed else "partial" if completed else "failed",
        "attempted": attempted,
        "completed": completed,
        "failed": failed,
        "phrases": phrase_status,
        "phrases_not_considered": list(suggestions.phrases_not_considered),
        "max_phrases": max_phrases,
        "budget": dict(suggestions.budget),
    }
    if suggestions.budget.get("truncated"):
        materials.setdefault("warnings", []).append(
            "Co-occurrence MeSH evidence was truncated by its NCBI request budget; see coverage.mesh_cooccurrence."
        )
    return materials
