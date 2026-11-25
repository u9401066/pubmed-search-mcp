"""Suggest-only MeSH corrections for pipeline PubMed steps.

Design:
    A saved pipeline is a reproducible strategy (PRISMA-S records its exact
    query and fingerprint), so the executor never rewrites it. When PubMed
    reports that a MeSH clause of a pipeline query matched nothing, the
    correction service computes what ``unified_search`` would have run
    instead; the result is recorded on the step, in the PRISMA-S search
    record and in the run response, together with how to adopt it (save a
    new pipeline version with the corrected query).

    Suggestion traffic is optional work: it runs only if its whole request
    budget fits in the run's remaining external-call quota (unused requests
    are returned) and within the remaining run deadline, and it never makes
    the run fail.

Maintenance:
    Keep this module free of provider I/O; NCBI calls go through the
    injected ``MeshCorrectionService``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from pubmed_search.domain.services.mesh_correction import find_mesh_terms, flag_unresolved_terms
from pubmed_search.domain.value_objects.query_diagnostics import PubMedQueryDiagnostics

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from pubmed_search.application.search.mesh_correction import MeshCorrectionService

logger = logging.getLogger(__name__)

PIPELINE_SUGGESTION_MAX_REQUESTS = 18
PIPELINE_SUGGESTION_TIMEOUT_SECONDS = 45.0
_MIN_SUGGESTION_SECONDS = 5.0
ADOPT_INSTRUCTION = (
    "Saved strategies are never rewritten automatically. To adopt this suggestion, save a new pipeline "
    "version whose PubMed query is corrected_query (save_pipeline with the edited config) and run it; the "
    "PRISMA-S record will then show the new strategy and its own fingerprint."
)


def diagnostics_from_provenance(provenance: Mapping[str, Any] | None) -> PubMedQueryDiagnostics | None:
    """Diagnostics carried by a bounded PubMed search result's provenance."""
    provider = provenance.get("provider_metadata") if isinstance(provenance, dict) else None
    raw = provider.get("query_diagnostics") if isinstance(provider, dict) else None
    return PubMedQueryDiagnostics.from_dict(raw) if isinstance(raw, dict) else None


def diagnostics_from_snapshot(snapshot: Mapping[str, Any] | None) -> PubMedQueryDiagnostics | None:
    """Diagnostics of an ``esearch_snapshot`` (exhaustive retrieval, block analysis)."""
    if not isinstance(snapshot, dict):
        return None
    errors = snapshot.get("provider_errors")
    warnings = snapshot.get("provider_warnings")
    translation = snapshot.get("query_translation")
    return PubMedQueryDiagnostics.from_dict(
        {
            "query_translation": translation,
            "warning_list": warnings if isinstance(warnings, dict) else {},
            "error_list": errors if isinstance(errors, dict) else {},
        }
    )


def unresolved_mesh_clauses(query: str, diagnostics: PubMedQueryDiagnostics | None) -> list[str]:
    """MeSH-tagged clauses of ``query`` that PubMed reported as not found."""
    if diagnostics is None:
        return []
    return list(dict.fromkeys(item.term.clause for item in flag_unresolved_terms(find_mesh_terms(query), diagnostics)))


def count_scope_for(logical_query: str, physical_query: str | None) -> Callable[[str], str] | None:
    """Map a query to the filtered string PubMed counted, when the filter suffix is recognizable."""
    if not physical_query or physical_query == logical_query:
        return None
    prefix = f"({logical_query})"
    if not physical_query.startswith(prefix):
        return None
    suffix = physical_query[len(prefix) :]
    return lambda query: f"({query}){suffix}"


def _base(query: str, clauses: list[str]) -> dict[str, Any]:
    return {
        "mode": "suggestion",
        "applied": False,
        "original_query": query,
        "corrected_query": query,
        "unresolved_clauses": clauses,
        "adopt": ADOPT_INSTRUCTION,
    }


async def suggest_mesh_correction(
    service: MeshCorrectionService | None,
    query: str,
    *,
    diagnostics: PubMedQueryDiagnostics | None,
    observed_count: int | None,
    physical_query: str | None,
    reserve: Callable[[int], Awaitable[bool]],
    release: Callable[[int], Awaitable[None]],
    remaining_seconds: float | None,
) -> dict[str, Any] | None:
    """Return a suggestion record when PubMed flagged a MeSH clause of ``query``, else ``None``."""
    clauses = unresolved_mesh_clauses(query, diagnostics)
    if not clauses:
        return None
    record = _base(query, clauses)
    if service is None:
        return {**record, "status": "unavailable", "warnings": ["MeSH correction is not configured on this server."]}
    timeout = PIPELINE_SUGGESTION_TIMEOUT_SECONDS if remaining_seconds is None else remaining_seconds - 1.0
    if timeout < _MIN_SUGGESTION_SECONDS:
        return {**record, "status": "skipped", "warnings": ["Not enough of the run deadline remained."]}
    timeout = min(timeout, PIPELINE_SUGGESTION_TIMEOUT_SECONDS)
    requests = PIPELINE_SUGGESTION_MAX_REQUESTS
    if not await reserve(requests):
        return {
            **record,
            "status": "skipped",
            "warnings": [f"The run's external-call quota could not cover {requests} suggestion requests."],
        }
    used = requests
    try:
        result = await asyncio.wait_for(
            service.correct_query(
                query,
                diagnostics=diagnostics,
                observed_count=observed_count,
                count_scope=count_scope_for(query, physical_query),
                max_ncbi_requests=requests,
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return {**record, "status": "skipped", "warnings": [f"Suggestion did not finish within {timeout:.0f} s."]}
    except Exception as exc:
        logger.warning("Pipeline MeSH suggestion failed (%s)", type(exc).__name__)
        return {**record, "status": "unavailable", "warnings": [f"Suggestion failed ({type(exc).__name__})."]}
    else:
        reserved = result.budget.get("reserved")
        used = reserved if isinstance(reserved, int) and 0 <= reserved <= requests else requests
        payload = result.to_dict()
        payload.pop("diagnostics_before", None)
        payload.pop("diagnostics_after", None)
        payload.pop("changed", None)
        return {**payload, **record, "corrected_query": result.corrected_query, "status": result.status}
    finally:
        if used < requests:
            await release(requests - used)


def suggestion_note(suggestion: Mapping[str, Any] | None) -> str | None:
    """One-line PRISMA-S note / run warning for a suggestion record."""
    if not suggestion:
        return None
    clauses = ", ".join(str(clause) for clause in suggestion.get("unresolved_clauses") or [])
    note = f"PubMed could not resolve {clauses} (it matched nothing)"
    corrected = suggestion.get("corrected_query")
    if suggestion.get("status") == "corrected" and corrected and corrected != suggestion.get("original_query"):
        counts = suggestion.get("hit_counts") or {}
        before, after = counts.get("before"), counts.get("after")
        note += (
            f"; suggested MeSH correction (not applied): {corrected} "
            f"(hits {before if before is not None else '?'} → {after if after is not None else '?'}); "
            "save a new pipeline version to adopt it"
        )
    else:
        warnings = "; ".join(str(item) for item in suggestion.get("warnings") or [])
        note += f"; no correction suggested{f' ({warnings})' if warnings else ''}"
    return note


__all__ = [
    "ADOPT_INSTRUCTION",
    "PIPELINE_SUGGESTION_MAX_REQUESTS",
    "count_scope_for",
    "diagnostics_from_provenance",
    "diagnostics_from_snapshot",
    "suggest_mesh_correction",
    "suggestion_note",
    "unresolved_mesh_clauses",
]
