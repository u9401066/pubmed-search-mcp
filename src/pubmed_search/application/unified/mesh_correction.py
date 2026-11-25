"""Automatic MeSH correction of the PubMed exact-tier query in ``unified_search``.

Design:
    PubMed reports MeSH clauses it cannot resolve in the diagnostics of the
    exact-tier search itself, so correction costs nothing for valid queries.
    When the exact-tier PubMed attempt flags a MeSH clause,
    :class:`PubMedMeshCorrector` asks :class:`MeshCorrectionService` for a
    corrected query; the caller re-runs the exact tier with it and the
    re-run's records *are* the exact tier. Precision-first deepening,
    broadening and zero-result relaxation therefore all decide on the
    corrected query's results. The original attempt is kept as a
    ``superseded`` row so nothing is hidden.

    The corrector is the application side of a small hook: the deep-search
    broker (infrastructure) calls :meth:`propose`, runs the corrected query,
    reports it back through :meth:`record_rerun`, and passes lower-precision
    PubMed fill queries through :meth:`rewrite`. The traditional single-pass
    path in ``execution`` uses the same three calls.

Maintenance:
    Keep provider I/O out of this module: queries run through the broker or
    the execution module, NCBI evidence through the correction service.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from pubmed_search.domain.services.mesh_correction import apply_replacements, find_mesh_terms, flag_unresolved_terms
from pubmed_search.domain.value_objects.query_diagnostics import PubMedQueryDiagnostics

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pubmed_search.application.search.mesh_correction import MeshCorrectionResult, MeshCorrectionService

logger = logging.getLogger(__name__)

MESH_CORRECTED_SUFFIX = ":mesh_corrected"
MESH_CORRECTION_TIMEOUT_SECONDS = 45.0
MESH_CORRECTION_OPT_OUT = 'options="no_mesh_correction"'
EXECUTED_COUNT_METHOD = "PubMed totals of the executed exact-tier searches (request filters applied)"


def diagnostics_from_metadata(metadata: Mapping[str, Any] | None) -> PubMedQueryDiagnostics | None:
    """PubMed diagnostics carried by a source adapter result, if any."""
    if not isinstance(metadata, dict):
        return None
    provider = metadata.get("provider_metadata")
    raw = provider.get("query_diagnostics") if isinstance(provider, dict) else None
    return PubMedQueryDiagnostics.from_dict(raw) if isinstance(raw, dict) else None


def has_unresolved_mesh(query: str, diagnostics: PubMedQueryDiagnostics | None) -> bool:
    """Whether PubMed reported any MeSH-tagged clause of ``query`` as not found."""
    return diagnostics is not None and bool(flag_unresolved_terms(find_mesh_terms(query), diagnostics))


class PubMedMeshCorrector:
    """Decide, apply and disclose one automatic MeSH correction per search."""

    def __init__(self, service: MeshCorrectionService, *, timeout: float = MESH_CORRECTION_TIMEOUT_SECONDS) -> None:
        self._service = service
        self._timeout = timeout
        self._result: MeshCorrectionResult | None = None
        self._original_query: str | None = None
        self._applied = False
        self._rerun_status: str | None = None
        self._notes: list[str] = []

    @property
    def applied(self) -> bool:
        """Whether a corrected query replaced the caller's PubMed exact tier."""
        return self._applied

    @property
    def result(self) -> MeshCorrectionResult | None:
        return self._result

    @property
    def rerun_status(self) -> str | None:
        """Status of the corrected exact-tier re-run, ``None`` when none ran."""
        return self._rerun_status

    async def propose(self, query: str, metadata: Mapping[str, Any] | None, total: int | None) -> str | None:
        """Return the corrected query for a flagged exact-tier attempt, else ``None``.

        Only the first flagged PubMed exact attempt is corrected; the result
        of that correction is reused for any other attempt of the same query.
        """
        if self._result is not None:
            return self._result.corrected_query if query == self._original_query and self._result.changed else None
        diagnostics = diagnostics_from_metadata(metadata)
        if not has_unresolved_mesh(query, diagnostics):
            return None
        self._original_query = query
        try:
            self._result = await asyncio.wait_for(
                self._service.correct_query(query, diagnostics=diagnostics, observed_count=total, measure_after=False),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            self._notes.append(f"MeSH correction did not finish within {self._timeout:.0f} s; query unchanged.")
            self._result = self._service.unavailable_result(query, diagnostics=diagnostics, observed_count=total)
        except Exception as exc:
            logger.warning("MeSH correction failed (%s)", type(exc).__name__)
            self._notes.append(f"MeSH correction failed ({type(exc).__name__}); query unchanged.")
            self._result = self._service.unavailable_result(query, diagnostics=diagnostics, observed_count=total)
        return self._result.corrected_query if self._result.changed else None

    def record_rerun(self, *, status: str, total: int | None, metadata: Mapping[str, Any] | None) -> None:
        """Record the exact-tier re-run of the corrected query."""
        if self._result is None:
            return
        self._rerun_status = status
        if status == "error":
            self._notes.append("The corrected query failed at PubMed; the original exact-tier results were kept.")
            return
        self._applied = True
        self._result = replace(
            self._result,
            after_count=total,
            diagnostics_after=diagnostics_from_metadata(metadata),
            count_method=EXECUTED_COUNT_METHOD,
        )

    def rewrite(self, query: str) -> str:
        """Apply the accepted clause rewrites to another PubMed query (fill tiers, relaxation)."""
        if not self._applied or self._result is None:
            return query
        replacements_by_clause = {
            correction.original: correction.replacement for correction in self._result.corrections
        }
        replacements = [
            (term.start, term.end, replacements_by_clause[term.clause])
            for term in find_mesh_terms(query)
            if term.clause in replacements_by_clause
        ]
        return apply_replacements(query, replacements) if replacements else query

    def disclosure(self) -> dict[str, Any] | None:
        """Full ``mesh_correction`` object for JSON/TOON, artifacts and audit."""
        if self._result is None:
            return None
        payload = self._result.to_dict()
        payload.update(
            {
                "mode": "automatic",
                "applied": self._applied,
                "rerun_status": self._rerun_status,
                "opt_out": MESH_CORRECTION_OPT_OUT,
            }
        )
        payload["warnings"] = [*payload.get("warnings", []), *self._notes]
        return payload


_TIER_LABELS = {
    "exact": "exact MeSH term",
    "co_occurrence": "co-occurrence evidence",
    "text_words": "no MeSH heading found",
}


def compact_mesh_correction(disclosure: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Evidence-free projection for size-capped responses and artifact summaries."""
    if not disclosure:
        return None
    return {
        "status": disclosure.get("status"),
        "applied": disclosure.get("applied"),
        "original_query": disclosure.get("original_query"),
        "corrected_query": disclosure.get("corrected_query"),
        "hit_counts": disclosure.get("hit_counts"),
        "corrections": [
            {
                key: correction.get(key)
                for key in ("original", "replacement", "replacement_mesh", "tier", "confidence", "reason")
            }
            for correction in disclosure.get("corrections") or []
            if isinstance(correction, dict)
        ],
        "opt_out": disclosure.get("opt_out"),
    }


def describe_correction(correction: Mapping[str, Any]) -> str:
    """One plain-text clause: what was rewritten into what, with tier and confidence."""
    tier = str(correction.get("tier") or "")
    mesh = correction.get("replacement_mesh")
    if tier == "exact":
        target = f"{correction.get('replacement')}"
    elif tier == "co_occurrence":
        target = f'text words OR "{mesh}" (related heading)'
    else:
        target = "title/abstract text words"
    return (
        f"{correction.get('original')} not found in MeSH → {target} "
        f"({correction.get('confidence')} confidence, {_TIER_LABELS.get(tier, tier)})"
    )


def correction_summary(disclosure: Mapping[str, Any] | None) -> str | None:
    """Sentence used by the broadening summary and Markdown; ``None`` when nothing to say."""
    if not disclosure:
        return None
    counts = disclosure.get("hit_counts") or {}
    before, after = counts.get("before"), counts.get("after")
    hits = f"hits {before if before is not None else '?'} → {after if after is not None else '?'}"
    corrections = [item for item in disclosure.get("corrections") or [] if isinstance(item, dict)]
    if disclosure.get("applied"):
        described = "; ".join(describe_correction(item) for item in corrections)
        return f"PubMed MeSH correction: {described}; {hits}"
    reasons = "; ".join(str(item) for item in disclosure.get("warnings") or []) or str(disclosure.get("status"))
    return f"PubMed could not resolve a MeSH clause; no correction was applied ({reasons})"


__all__ = [
    "EXECUTED_COUNT_METHOD",
    "MESH_CORRECTED_SUFFIX",
    "MESH_CORRECTION_OPT_OUT",
    "PubMedMeshCorrector",
    "compact_mesh_correction",
    "correction_summary",
    "describe_correction",
    "diagnostics_from_metadata",
    "has_unresolved_mesh",
]
