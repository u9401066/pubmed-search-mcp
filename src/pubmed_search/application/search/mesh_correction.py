"""Automatic, disclosed correction of MeSH terms PubMed cannot resolve.

When an agent writes a MeSH heading that does not exist
(``"Post-Anesthesia Care Units"[Mesh]``), PubMed reports it in ESearch's
WarningList/ErrorList and the clause matches nothing, which zeroes any AND
strategy. :class:`MeshCorrectionService` rewrites exactly those clauses and
reports every change with its evidence, in the same spirit as automatic
search broadening: automatic, never silent.

Correction tiers, tried in order for each unresolved heading:

``exact``
    The heading is a preferred or entry term of a MeSH record once case,
    hyphen spacing and simple plurals are folded (``"Emergence Deliriums"`` ->
    ``"Emergence Delirium"``; ``"Recovery Rooms"[mesh:noexp]`` -> ``"Recovery
    Room"[mesh:noexp]``; a supplementary concept moves to
    ``[Supplementary Concept]``). The clause is replaced in place; confidence
    ``high``.
``co_occurrence``
    No record has the words (MeSH has no "post-anesthesia care unit"). The
    words are searched as ``[tiab]`` in MEDLINE-indexed records, a bounded
    sample's MeSH headings nominate candidates (check tags and study-design
    headings excluded), and each nominee is scored exactly from two PubMed
    counts: recall = evidence records indexed with it / evidence total, and
    precision = evidence records indexed with it / all records indexed with
    it. Candidates are ranked by F1. The clause becomes ``(<text words> OR "<best
    heading>"[<original tag>])``: the agent's own words keep the concept and
    the related heading adds the records indexed under it. A related heading
    is never substituted for the concept on its own. Confidence ``medium`` or
    ``low``.
``text_words``
    No usable heading, or the evidence budget ran out: the clause becomes the
    agent's words as ``[tiab]`` text words. Confidence ``low``.

A clause that PubMed resolves is never changed. Inside a NOT operand only an
``exact`` correction that keeps every restriction is applied; any other fix is
returned in ``suggestions`` and left out of the query, because a related
heading or text words would change what the NOT excludes. Each correction lists the
NCBI warning that triggered it, the replacement, the evidence (exact match
or the evidence query, date, sample and candidate scores), and the query's
before/after hit counts from count-only ESearch requests. NCBI traffic is
capped per call (``MeshCorrectionPolicy.max_ncbi_requests``); anything
skipped for budget reasons is listed in the disclosure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar

from pubmed_search.domain.services.mesh_correction import (
    FlaggedTerm,
    ScoredDescriptor,
    TaggedMeshTerm,
    apply_replacements,
    cooccurrence_confidence,
    descriptor_clause,
    descriptor_shares,
    evidence_query,
    fetch_batches,
    find_mesh_terms,
    flag_unresolved_terms,
    joint_query,
    or_block,
    phrase_priority,
    qualifier_allowed,
    qualifier_spelling,
    rank_descriptors,
    score_descriptor,
    text_word_block,
    text_word_clauses,
    text_word_variants,
)
from pubmed_search.domain.services.mesh_phrase_matching import matches_for, resolve_matches

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from pubmed_search.domain.services.mesh_correction import Confidence, EvidenceSample
    from pubmed_search.domain.services.mesh_phrase_matching import MeshRecord, TermMatch
    from pubmed_search.domain.value_objects.query_diagnostics import PubMedQueryDiagnostics, QueryProbe

logger = logging.getLogger(__name__)

T = TypeVar("T")
SampleSort = Literal["relevance", "pub_date"]
CorrectionTier = Literal["exact", "co_occurrence", "text_words"]
QualifierCheck = Literal["allowed", "not_allowed", "unverified"]
CorrectionStatus = Literal["not_applicable", "valid", "corrected", "unavailable"]
Detection = Literal["none", "ncbi_diagnostics", "exact_lookup"]
CooccurrenceStatus = Literal[
    "completed", "no_records", "too_common", "no_candidates", "unscored", "failed", "skipped_budget"
]

BUDGET_ACCOUNTING = (
    "Upper bound of NCBI E-utility operations reserved before each call; cached responses issue none and "
    "transport retries of one operation are not counted."
)
SAMPLE_NOTE = (
    "The sample is the first records of the evidence query in the stated sort order, not a random sample; it "
    "only nominates headings. background_count and joint_count are PubMed counts of records indexed with the "
    "heading itself ([mh:noexp]) at retrieval time."
)
PROBE_COUNT_METHOD = "PubMed ESearch count (retmax=0)"
NOT_OPERAND_NOTE = (
    "Inside a NOT operand: only an equivalent heading that keeps every restriction is applied automatically. "
    "This rewrite would change what is excluded, so it is a suggestion only."
)
SCORING_NOTE = (
    "share = sampled records carrying the heading / sampled records with MeSH (nominates candidates); "
    "joint_count = evidence records indexed with the heading ([mh:noexp]); recall = joint_count / evidence_total; "
    "precision = joint_count / background_count; score = F1 of recall and precision (exact counts, not sample "
    "estimates). Check tags (Humans, Male, Adult, ...) and study-design headings (Retrospective Studies, ...) "
    "are excluded."
)


class MeshCorrectionGateway(Protocol):
    """NCBI operations the service needs; ``NCBIMeshEvidenceGateway`` implements them."""

    async def probe(self, query: str) -> QueryProbe: ...

    async def lookup_exact(self, phrases: Sequence[str]) -> Mapping[str, tuple[MeshRecord, ...]]: ...

    async def sample(self, query: str, *, limit: int, sort: str) -> EvidenceSample: ...

    async def fetch_mesh_headings(self, pmids: Sequence[str], *, batch_size: int) -> Mapping[str, tuple[str, ...]]: ...

    async def count(self, query: str) -> int: ...


@dataclass(frozen=True)
class MeshCorrectionPolicy:
    """Bounds and thresholds for one correction or suggestion call.

    The defaults allow one unresolved heading to complete every tier:
    probe 1 + exact lookup 2 + evidence search 1 + one MEDLINE batch +
    6 nominees x 2 counts (background, joint) + after-count 1 = 18 of 24
    requests.
    """

    max_ncbi_requests: int = 24
    max_terms: int = 3
    sample_size: int = 150
    sample_sort: SampleSort = "relevance"
    fetch_batch_size: int = 200
    scored_candidates: int = 6
    reported_candidates: int = 5
    min_share: float = 0.05
    min_records: int = 3
    min_score: float = 0.05
    medium_confidence_score: float = 0.25
    medium_confidence_records: int = 50
    max_phrase_evidence_total: int = 100_000

    def __post_init__(self) -> None:
        integers = {
            "max_ncbi_requests": (self.max_ncbi_requests, 1, 200),
            "max_terms": (self.max_terms, 1, 20),
            "sample_size": (self.sample_size, 10, 500),
            "fetch_batch_size": (self.fetch_batch_size, 1, 500),
            "scored_candidates": (self.scored_candidates, 0, 30),
            "reported_candidates": (self.reported_candidates, 1, 30),
            "min_records": (self.min_records, 1, 500),
            "medium_confidence_records": (self.medium_confidence_records, 1, 500),
            "max_phrase_evidence_total": (self.max_phrase_evidence_total, 1, 100_000_000),
        }
        for name, (value, low, high) in integers.items():
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f"{name} must be an integer between {low} and {high}")
        for name, ratio in (
            ("min_share", self.min_share),
            ("min_score", self.min_score),
            ("medium_confidence_score", self.medium_confidence_score),
        ):
            if not 0.0 <= ratio <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.sample_sort not in {"relevance", "pub_date"}:
            raise ValueError("sample_sort must be relevance or pub_date")


class RequestBudget:
    """Caps NCBI operations for one call and records what was skipped."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.reserved = 0
        self.skipped: list[str] = []

    def reserve(self, requests: int, purpose: str, *, keep: int = 0) -> bool:
        """Reserve ``requests`` while leaving ``keep`` for later mandatory steps."""
        if self.reserved + requests + keep > self.limit:
            self.skipped.append(purpose)
            return False
        self.reserved += requests
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_ncbi_requests": self.limit,
            "reserved": self.reserved,
            "truncated": bool(self.skipped),
            "skipped": list(self.skipped),
            "accounting": BUDGET_ACCOUNTING,
        }


@dataclass(frozen=True)
class CooccurrenceReport:
    """Data-driven MeSH candidates for one phrase, with the evidence behind them."""

    phrase: str
    status: CooccurrenceStatus
    evidence_query: str
    variants: tuple[str, ...]
    sample: EvidenceSample | None = None
    records_with_mesh: int = 0
    excluded: Mapping[str, int] = field(default_factory=dict)
    candidates: tuple[ScoredDescriptor, ...] = ()
    unscored: int = 0
    notes: tuple[str, ...] = ()

    @property
    def best(self) -> ScoredDescriptor | None:
        """Top-ranked candidate that has a score; unscored candidates are never chosen."""
        return next((item for item in self.candidates if item.score is not None), None)

    def evidence(self) -> dict[str, Any]:
        sample = self.sample
        return {
            "status": self.status,
            "query": self.evidence_query,
            "sort": sample.sort if sample else None,
            "retrieved_at": sample.retrieved_at if sample else None,
            "evidence_total": sample.total if sample else None,
            "sample_size": len(sample.pmids) if sample else 0,
            "records_with_mesh": self.records_with_mesh,
            "excluded_descriptors": dict(self.excluded),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "unscored_candidates": self.unscored,
            "scoring": SCORING_NOTE,
            "sampling": SAMPLE_NOTE,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class TermCorrection:
    """One rewritten clause and why.

    ``evidence_complete`` is False when the exact lookup or the co-occurrence
    evidence was skipped, failed or unscored, so "no heading" means "not
    established", not "MeSH has none".
    """

    original: str
    term: str
    occurrences: int
    reason: str
    tier: CorrectionTier
    replacement: str
    replacement_mesh: str | None
    confidence: Confidence
    evidence: Mapping[str, Any]
    notes: tuple[str, ...] = ()
    evidence_complete: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "term": self.term,
            "occurrences": self.occurrences,
            "reason": self.reason,
            "tier": self.tier,
            "replacement": self.replacement,
            "replacement_mesh": self.replacement_mesh,
            "confidence": self.confidence,
            "evidence_complete": self.evidence_complete,
            "evidence": dict(self.evidence),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class MeshCorrectionResult:
    """Outcome of :meth:`MeshCorrectionService.correct_query`; ``to_dict`` is the disclosure.

    ``corrections`` were applied to ``corrected_query``; ``suggestions`` were
    not (clauses inside a NOT operand whose only fix would change what is
    excluded).
    """

    original_query: str
    corrected_query: str
    status: CorrectionStatus
    detection: Detection
    corrections: tuple[TermCorrection, ...] = ()
    valid_terms: tuple[str, ...] = ()
    before_count: int | None = None
    after_count: int | None = None
    diagnostics_before: PubMedQueryDiagnostics | None = None
    diagnostics_after: PubMedQueryDiagnostics | None = None
    budget: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    count_method: str = PROBE_COUNT_METHOD
    suggestions: tuple[TermCorrection, ...] = ()

    @property
    def changed(self) -> bool:
        return self.corrected_query != self.original_query

    @property
    def improves_recall(self) -> bool:
        """True when both counts are known and the corrected query finds more records."""
        return self.before_count is not None and self.after_count is not None and self.after_count > self.before_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "changed": self.changed,
            "original_query": self.original_query,
            "corrected_query": self.corrected_query,
            "detection": self.detection,
            "hit_counts": {
                "before": self.before_count,
                "after": self.after_count,
                "method": self.count_method,
            },
            "corrections": [correction.to_dict() for correction in self.corrections],
            "suggestions": [suggestion.to_dict() for suggestion in self.suggestions],
            "valid_terms": list(self.valid_terms),
            "diagnostics_before": self.diagnostics_before.to_dict() if self.diagnostics_before else None,
            "diagnostics_after": self.diagnostics_after.to_dict() if self.diagnostics_after else None,
            "budget": dict(self.budget),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class PhraseSuggestions:
    """Co-occurrence candidates for unmapped topic phrases (``generate_search_queries``)."""

    reports: tuple[CooccurrenceReport, ...]
    phrases_considered: tuple[str, ...]
    phrases_not_considered: tuple[str, ...]
    budget: Mapping[str, Any]


class MeshCorrectionService:
    """Detect and correct MeSH-tagged clauses that PubMed cannot resolve.

    Phase-2 integration contract (``unified_search``, pipeline executor):

    - Call :meth:`correct_query` with the PubMed query that was (or is about
      to be) executed. Pass ``diagnostics`` and ``observed_count`` from the
      search page (``PubMedQueryDiagnostics.from_dict(page.metadata
      ["query_diagnostics"])`` and ``page.total``) to skip the first probe.
    - The call never raises for NCBI failures; it returns
      ``status="unavailable"`` (query unchanged) when validity cannot be
      determined, ``"not_applicable"`` when the query has no MeSH-tagged
      clause, ``"valid"`` when PubMed resolved every MeSH clause, and
      ``"corrected"`` when at least one clause was rewritten.
    - When ``result.changed``, re-run the search with
      ``result.corrected_query`` and attach ``result.to_dict()`` to the
      response (for example as ``mesh_correction``) so the agent sees the
      original term, NCBI's reason, the replacement, tier, evidence,
      confidence and before/after counts. ``result.improves_recall`` tells
      whether the rewrite found more records; callers may keep the original
      results when it is False, but must still disclose the attempt.
    - The query must already be PubMed syntax; filters compiled by
      ``search_page`` (dates, languages) can stay in the string.
    """

    def __init__(self, gateway: MeshCorrectionGateway, policy: MeshCorrectionPolicy | None = None) -> None:
        self._gateway = gateway
        self._policy = policy or MeshCorrectionPolicy()

    @property
    def policy(self) -> MeshCorrectionPolicy:
        return self._policy

    def unavailable_result(
        self,
        query: str,
        *,
        diagnostics: PubMedQueryDiagnostics | None = None,
        observed_count: int | None = None,
        warning: str | None = None,
    ) -> MeshCorrectionResult:
        """Disclosure for a correction attempt that could not complete; the query is unchanged."""
        terms = find_mesh_terms(query)
        flagged = {item.term.start for item in flag_unresolved_terms(terms, diagnostics)} if diagnostics else set()
        return MeshCorrectionResult(
            query,
            query,
            "unavailable",
            "ncbi_diagnostics" if diagnostics is not None else "none",
            valid_terms=tuple(dict.fromkeys(term.clause for term in terms if term.start not in flagged)),
            before_count=observed_count,
            diagnostics_before=diagnostics,
            warnings=(warning,) if warning else (),
        )

    async def correct_query(
        self,
        query: str,
        *,
        diagnostics: PubMedQueryDiagnostics | None = None,
        observed_count: int | None = None,
        measure_after: bool = True,
        count_scope: Callable[[str], str] | None = None,
        max_ncbi_requests: int | None = None,
    ) -> MeshCorrectionResult:
        """Return ``query`` with every unresolved MeSH clause corrected, plus the disclosure.

        Args:
            query: PubMed query string.
            diagnostics: ESearch diagnostics already obtained for ``query``;
                when omitted, one count-only probe obtains them.
            observed_count: Hit count already obtained for ``query``.
            measure_after: Count the corrected query with one ESearch. Callers
                that re-run the corrected query themselves pass ``False`` and
                fill ``after_count`` from that search.
            count_scope: Maps a query to the string actually counted, so
                probes include the caller's filters (for example
                ``lambda q: f"({q}) AND 2020:2025[dp]"``). Corrections are
                always computed on ``query`` itself.
            max_ncbi_requests: Lower per-call request cap (callers with their
                own quota); defaults to ``policy.max_ncbi_requests``.
        """
        scope = count_scope or (lambda text: text)
        terms = find_mesh_terms(query)
        if not terms:
            return MeshCorrectionResult(query, query, "not_applicable", "none", before_count=observed_count)

        limit = self._policy.max_ncbi_requests
        budget = RequestBudget(min(limit, max_ncbi_requests) if max_ncbi_requests is not None else limit)
        warnings: list[str] = []
        before_count = observed_count
        if diagnostics is None and budget.reserve(1, "diagnostics probe of the original query"):
            probe = await self._attempt(self._gateway.probe(scope(query)), "PubMed diagnostics probe", warnings)
            if probe is not None:
                diagnostics, before_count = probe.diagnostics, probe.count

        records_by_key: Mapping[str, tuple[MeshRecord, ...]] | None = None
        if diagnostics is not None:
            detection: Detection = "ncbi_diagnostics"
            flagged = flag_unresolved_terms(terms, diagnostics)
        else:
            detection = "exact_lookup"
            records_by_key = await self._lookup([term.descriptor for term in terms], budget, warnings, keep=0)
            if records_by_key is None:
                warnings.append("MeSH validity could not be determined; the query was left unchanged.")
                return MeshCorrectionResult(
                    query, query, "unavailable", detection, budget=budget.to_dict(), warnings=tuple(warnings)
                )
            flagged = [
                FlaggedTerm(term, "No MeSH record has this heading as a preferred or entry term (exact lookup).")
                for term in terms
                if not matches_for(term.descriptor, records_by_key.get(term.key, ()))
            ]

        flagged_clauses = {item.term.start for item in flagged}
        valid_terms = tuple(dict.fromkeys(term.clause for term in terms if term.start not in flagged_clauses))
        if not flagged:
            return MeshCorrectionResult(
                query,
                query,
                "valid",
                detection,
                valid_terms=valid_terms,
                before_count=before_count,
                diagnostics_before=diagnostics,
                budget=budget.to_dict(),
                warnings=tuple(warnings),
            )

        corrections, suggestions, replacements = await self._correct_flagged(flagged, records_by_key, budget, warnings)
        corrected = apply_replacements(query, replacements)

        from .query_validator import validate_query

        if not validate_query(corrected).is_valid:
            warnings.append("The rewritten query failed PubMed syntax validation; the query was left unchanged.")
            return MeshCorrectionResult(
                query,
                query,
                "unavailable",
                detection,
                valid_terms=valid_terms,
                before_count=before_count,
                diagnostics_before=diagnostics,
                budget=budget.to_dict(),
                warnings=tuple(warnings),
                suggestions=tuple(suggestions),
            )

        after_count: int | None = None
        diagnostics_after: PubMedQueryDiagnostics | None = None
        if measure_after and budget.reserve(1, "count of the corrected query"):
            after = await self._attempt(
                self._gateway.probe(scope(corrected)), "PubMed count of the corrected query", warnings
            )
            if after is not None:
                after_count, diagnostics_after = after.count, after.diagnostics
                for remaining in flag_unresolved_terms(find_mesh_terms(corrected), after.diagnostics):
                    warnings.append(f"PubMed still cannot resolve {remaining.term.clause}: {remaining.reason}")

        if corrected == query:
            warnings.append("No unresolved MeSH clause could be rewritten; the query was left unchanged.")
        return MeshCorrectionResult(
            original_query=query,
            corrected_query=corrected,
            status="corrected" if corrected != query else "unavailable",
            detection=detection,
            corrections=tuple(corrections),
            valid_terms=valid_terms,
            before_count=before_count,
            after_count=after_count,
            diagnostics_before=diagnostics,
            diagnostics_after=diagnostics_after,
            budget=budget.to_dict(),
            warnings=tuple(warnings),
            suggestions=tuple(suggestions),
        )

    async def suggest_for_phrases(
        self,
        phrases: Sequence[str],
        *,
        max_phrases: int = 2,
        max_ncbi_requests: int = 20,
    ) -> PhraseSuggestions:
        """Co-occurrence MeSH candidates for phrases no MeSH record names.

        Multi-word phrases are tried first (longest first), then single words,
        up to ``max_phrases``. A phrase used by more than
        ``policy.max_phrase_evidence_total`` records is reported as
        ``too_common`` without fetching headings. Results are candidates for
        review, never confirmed mappings.
        """
        considered = phrase_priority(phrases, max_phrases)
        budget = RequestBudget(max_ncbi_requests)
        reports = []
        for phrase in considered:
            reports.append(
                await self._cooccurrence(phrase, budget, keep=0, max_total=self._policy.max_phrase_evidence_total)
            )
        not_considered = tuple(phrase for phrase in dict.fromkeys(phrases) if phrase not in considered)
        return PhraseSuggestions(tuple(reports), tuple(considered), not_considered, budget.to_dict())

    async def _attempt(self, awaitable: Awaitable[T], purpose: str, warnings: list[str]) -> T | None:
        """Await one gateway call; failures become a warning, never an exception."""
        try:
            return await awaitable
        except Exception as exc:
            logger.warning("MeSH correction step failed (%s)", type(exc).__name__)
            warnings.append(f"{purpose} was unavailable ({type(exc).__name__}).")
            return None

    async def _lookup(
        self, descriptors: Sequence[str], budget: RequestBudget, warnings: list[str], *, keep: int
    ) -> Mapping[str, tuple[MeshRecord, ...]] | None:
        unique = list(dict.fromkeys(descriptors))
        if not budget.reserve(2, "exact MeSH lookup", keep=keep):
            return None
        return await self._attempt(self._gateway.lookup_exact(unique), "Exact MeSH lookup", warnings)

    async def _correct_flagged(
        self,
        flagged: Sequence[FlaggedTerm],
        records_by_key: Mapping[str, tuple[MeshRecord, ...]] | None,
        budget: RequestBudget,
        warnings: list[str],
    ) -> tuple[list[TermCorrection], list[TermCorrection], list[tuple[int, int, str]]]:
        """Applied corrections, NOT-operand suggestions, and the replacement spans of the applied ones.

        Clauses are grouped by text *and* polarity. Inside a NOT operand only
        an exact correction that keeps every restriction (qualifier, major
        topic, no-explode) is applied: anything else would change what the
        NOT excludes (a related heading or text words widen it), so it is
        reported as a suggestion. Included clauses are researched first.
        """
        researched: dict[str, str] = {}
        for item in sorted(flagged, key=lambda flagged_item: flagged_item.term.negated):
            if item.term.key and item.term.key not in researched and len(researched) < self._policy.max_terms:
                researched[item.term.key] = item.term.descriptor
        if len(researched) < len({item.term.key for item in flagged}):
            budget.skipped.append(f"headings beyond max_terms={self._policy.max_terms} were not researched")

        # Keep one request for the after-count while researching.
        lookup_checked = records_by_key is not None
        if records_by_key is None:
            looked_up = await self._lookup(list(researched.values()), budget, warnings, keep=1)
            lookup_checked = looked_up is not None
            records_by_key = looked_up or {}
        exact: dict[str, TermMatch] = {}
        ambiguous: dict[str, list[str]] = {}
        for key, descriptor in researched.items():
            matches = matches_for(descriptor, records_by_key.get(key, ()))
            chosen = resolve_matches(matches)
            if chosen is not None:
                exact[key] = chosen
            elif matches:
                ambiguous[key] = sorted({match.record.preferred for match in matches})

        reports: dict[str, CooccurrenceReport] = {}
        for key, descriptor in researched.items():
            if key not in exact:
                reports[key] = await self._cooccurrence(descriptor, budget, keep=1)

        grouped: dict[tuple[str, bool], list[FlaggedTerm]] = {}
        for item in flagged:
            grouped.setdefault((item.term.clause, item.term.negated), []).append(item)

        corrections: list[TermCorrection] = []
        suggestions: list[TermCorrection] = []
        replacements: list[tuple[int, int, str]] = []
        for (clause, negated), items in grouped.items():
            term, reason = items[0].term, items[0].reason
            if term.key in exact:
                correction = self._exact_correction(term, exact[term.key], reason)
                if correction is None:
                    warnings.append(f"{clause} was left unchanged: PubMed flagged an exact preferred heading.")
                    continue
            elif term.key in reports:
                correction = self._cooccurrence_correction(term, reports[term.key], reason, ambiguous.get(term.key, []))
            else:
                correction = self._text_word_correction(
                    term, reason, ("Not researched: more distinct headings than max_terms.",), {}, complete=False
                )
            if not correction.replacement:
                warnings.append(f"{clause} was left unchanged: it has no searchable words.")
                continue
            correction = replace(correction, occurrences=len(items))
            if not lookup_checked and correction.tier != "exact":
                correction = replace(
                    correction,
                    evidence_complete=False,
                    notes=(
                        *correction.notes,
                        "The exact MeSH lookup was unavailable, so an equivalent heading may exist.",
                    ),
                )
            if negated and (correction.tier != "exact" or correction.evidence.get("dropped_restrictions")):
                suggestions.append(replace(correction, notes=(*correction.notes, NOT_OPERAND_NOTE)))
                warnings.append(
                    f"{clause} is inside a NOT operand and PubMed cannot resolve it, so this exclusion currently "
                    f"removes nothing. Its {correction.tier.replace('_', ' ')} rewrite would change what is "
                    "excluded, so it was not applied; see suggestions."
                )
                continue
            corrections.append(correction)
            replacements.extend((item.term.start, item.term.end, correction.replacement) for item in items)
        return corrections, suggestions, replacements

    def _exact_correction(self, term: TaggedMeshTerm, match: TermMatch, reason: str) -> TermCorrection | None:
        record = match.record
        evidence: dict[str, Any] = {
            "method": "exact preferred/entry-term match (case, hyphen spacing and simple plurals folded)",
            "mesh_id": record.uid,
            "preferred": record.preferred,
            "record_type": record.record_type,
            "matched_on": match.matched_on,
            "matched_term": match.matched_term,
        }
        notes: list[str] = []
        confidence: Confidence = "high"
        if record.record_type != "descriptor":
            replacement = f'"{record.preferred}"[{record.search_field}]'
            dropped = [
                label
                for label, present in (
                    (f"qualifier /{term.qualifier}", bool(term.qualifier)),
                    ("major-topic restriction", term.major),
                    ("no-explode restriction", term.noexp),
                )
                if present
            ]
            notes.append(f"{record.record_type.replace('_', ' ')} records are searched with [{record.search_field}].")
            if dropped:
                notes.append(f"Dropped {', '.join(dropped)}, which do not apply to this record type.")
        else:
            # PubMed ignores case and spacing, not the characters themselves (a U+2011 hyphen differs).
            same_heading = " ".join(term.descriptor.casefold().split()) == " ".join(record.preferred.casefold().split())
            qualifier, qualifier_notes, qualifier_check = self._checked_qualifier(term, record, same_heading)
            if same_heading and qualifier == term.qualifier:
                return None  # PubMed flagged the clause, but no rewrite would change it
            notes.extend(qualifier_notes)
            if qualifier_check is not None:
                evidence["qualifier_check"] = qualifier_check
                if qualifier_check != "allowed":
                    confidence = "medium"
            dropped = [f"qualifier /{term.qualifier}"] if term.qualifier and qualifier is None else []
            replacement = term.render(record.preferred, keep_qualifier=qualifier is not None, qualifier=qualifier)
        if dropped:
            evidence["dropped_restrictions"] = dropped
        return TermCorrection(
            original=term.clause,
            term=term.descriptor,
            occurrences=1,
            reason=reason,
            tier="exact",
            replacement=replacement,
            replacement_mesh=record.preferred,
            confidence=confidence,
            evidence=evidence,
            notes=tuple(notes),
        )

    @staticmethod
    def _checked_qualifier(
        term: TaggedMeshTerm, record: MeshRecord, same_heading: bool
    ) -> tuple[str | None, list[str], QualifierCheck | None]:
        """Qualifier to keep on the corrected heading (None drops it), the notes, and how it was checked.

        Only a qualifier MeSH allows with the heading keeps "high" confidence;
        an unlisted allowed set is "unverified". When the clause already names
        the heading exactly, PubMed's flag is evidence against an unverified
        qualifier, so it is removed.
        """
        if not term.qualifier:
            return None, [], None
        spelled = qualifier_spelling(term.qualifier)
        allowed = qualifier_allowed(term.qualifier, record.allowed_qualifiers)
        if allowed is False:
            note = f"Qualifier /{term.qualifier} is not an allowable qualifier of {record.preferred!r}; it was removed."
            return None, [note], "not_allowed"
        if allowed is None and same_heading and spelled == term.qualifier:
            return (
                None,
                [f"The heading exists but PubMed rejected qualifier /{term.qualifier}; it was removed."],
                ("unverified"),
            )
        notes = []
        if spelled != term.qualifier:
            notes.append(
                f"Qualifier abbreviation /{term.qualifier} was written out as /{spelled}; PubMed does not resolve "
                "abbreviations inside quotes."
            )
        if allowed is None:
            notes.append(
                f"Qualifier /{spelled} could not be checked: the MeSH record lists no allowable qualifiers, so "
                "PubMed may still reject it."
            )
            return spelled, notes, "unverified"
        return spelled, notes, "allowed"

    def _cooccurrence_correction(
        self, term: TaggedMeshTerm, report: CooccurrenceReport, reason: str, ambiguous: Sequence[str]
    ) -> TermCorrection:
        notes = list(report.notes)
        if ambiguous:
            notes.append(f"Several MeSH records claim this exact term ({', '.join(ambiguous)}); none was chosen.")
        best = report.best
        if best is None or best.score is None or best.score < self._policy.min_score:
            if best is not None:
                notes.append(
                    f"Best co-occurring heading {best.descriptor!r} scored below {self._policy.min_score}; "
                    "no heading was added."
                )
            complete = report.status in {"completed", "no_records", "no_candidates", "too_common"}
            if not complete or report.unscored:
                notes.append(
                    f"Co-occurrence evidence was not completed ({report.status}, {report.unscored} unscored "
                    "candidates); a related heading may exist."
                )
            return self._text_word_correction(
                term,
                reason,
                tuple(notes),
                report.evidence(),
                report.variants,
                complete=complete and not report.unscored,
            )
        heading = term.render(best.descriptor, keep_qualifier=False)
        if term.qualifier:
            notes.append(f"Qualifier /{term.qualifier} was not carried over to a related heading.")
        notes.append(
            f"{best.descriptor!r} is a related heading chosen from indexing data, not an equivalent; "
            "the original words are kept as text words."
        )
        return TermCorrection(
            original=term.clause,
            term=term.descriptor,
            occurrences=1,
            reason=reason,
            tier="co_occurrence",
            replacement=or_block(*text_word_clauses(report.variants), heading),
            replacement_mesh=best.descriptor,
            confidence=cooccurrence_confidence(
                best,
                records_with_mesh=report.records_with_mesh,
                medium_score=self._policy.medium_confidence_score,
                medium_records=self._policy.medium_confidence_records,
            ),
            evidence=report.evidence(),
            notes=tuple(notes),
        )

    def _text_word_correction(
        self,
        term: TaggedMeshTerm,
        reason: str,
        notes: Sequence[str],
        evidence: Mapping[str, Any],
        variants: Sequence[str] = (),
        *,
        complete: bool,
    ) -> TermCorrection:
        words = tuple(variants) or text_word_variants(term.descriptor)
        extra = ["No MeSH heading was added; the concept is kept as title/abstract text words."]
        if term.qualifier:
            extra.append(f"Qualifier /{term.qualifier} has no text-word equivalent and was dropped.")
        return TermCorrection(
            original=term.clause,
            term=term.descriptor,
            occurrences=1,
            reason=reason,
            tier="text_words",
            replacement=text_word_block(words),
            replacement_mesh=None,
            confidence="low",
            evidence=dict(evidence),
            notes=(*notes, *extra),
            evidence_complete=complete,
        )

    async def _cooccurrence(
        self, phrase: str, budget: RequestBudget, *, keep: int, max_total: int | None = None
    ) -> CooccurrenceReport:
        """Rank MeSH headings indexed on records that use ``phrase`` in title/abstract."""
        policy = self._policy
        variants = text_word_variants(phrase)
        if not variants:
            return CooccurrenceReport(
                phrase, "no_records", "", variants, notes=("The phrase has no searchable words.",)
            )
        query = evidence_query(variants)
        if not budget.reserve(1, f"evidence search for {phrase!r}", keep=keep):
            return CooccurrenceReport(phrase, "skipped_budget", query, variants)
        warnings: list[str] = []
        sample = await self._attempt(
            self._gateway.sample(query, limit=policy.sample_size, sort=policy.sample_sort), "Evidence search", warnings
        )
        if sample is None:
            return CooccurrenceReport(phrase, "failed", query, variants, notes=tuple(warnings))
        not_found = {item.casefold() for item in sample.diagnostics.quoted_phrases_not_found}
        live = tuple(variant for variant in variants if f'"{variant}"[tiab]'.casefold() not in not_found) or variants
        if sample.total == 0 or not sample.pmids:
            return CooccurrenceReport(phrase, "no_records", query, live, sample)
        if max_total is not None and sample.total > max_total:
            note = f"{sample.total} records use the phrase (limit {max_total}); too common for co-occurrence evidence."
            return CooccurrenceReport(phrase, "too_common", query, live, sample, notes=(note,))
        if not budget.reserve(
            fetch_batches(len(sample.pmids), policy.fetch_batch_size), f"MeSH headings for {phrase!r}", keep=keep
        ):
            return CooccurrenceReport(phrase, "skipped_budget", query, live, sample)
        headings = await self._attempt(
            self._gateway.fetch_mesh_headings(sample.pmids, batch_size=policy.fetch_batch_size),
            "MEDLINE MeSH headings",
            warnings,
        )
        if headings is None:
            return CooccurrenceReport(phrase, "failed", query, live, sample, notes=tuple(warnings))
        table = descriptor_shares(headings)
        eligible = [
            share for share in table.shares if share.share >= policy.min_share and share.records >= policy.min_records
        ][: policy.scored_candidates]
        scored: list[ScoredDescriptor] = []
        unscored = 0
        for share in eligible:
            background = joint = None
            if budget.reserve(2, f"background and joint counts for {share.descriptor!r}", keep=keep):
                background = await self._attempt(
                    self._gateway.count(descriptor_clause(share.descriptor)), "Descriptor background count", warnings
                )
                if background is not None:
                    joint = await self._attempt(
                        self._gateway.count(joint_query(query, share.descriptor)), "Descriptor joint count", warnings
                    )
            if background is None or joint is None:
                unscored += 1
                scored.append(ScoredDescriptor(share.descriptor, share.records, share.share))
            else:
                scored.append(
                    score_descriptor(share, evidence_total=sample.total, background_count=background, joint_count=joint)
                )
        ranked = tuple(rank_descriptors(scored)[: policy.reported_candidates])
        status: CooccurrenceStatus
        if not eligible:
            status = "no_candidates"
        elif unscored == len(eligible):
            status = "unscored"
        else:
            status = "completed"
        return CooccurrenceReport(
            phrase=phrase,
            status=status,
            evidence_query=query,
            variants=live,
            sample=sample,
            records_with_mesh=table.records_with_mesh,
            excluded=table.excluded,
            candidates=ranked,
            unscored=unscored,
            notes=tuple(warnings),
        )


def cooccurrence_candidate_entry(report: CooccurrenceReport) -> dict[str, Any]:
    """``generate_search_queries`` ``mesh_candidates`` entry for one phrase report."""
    return {
        "input": report.phrase,
        "reason": "co_occurrence",
        "note": (
            "No MeSH record has this phrase as a preferred or entry term. These headings are indexed most "
            "often on MEDLINE records that use the phrase in title/abstract; they are related concepts, not "
            "equivalents. Review before using them as [MeSH Terms]."
        ),
        "candidates": [
            {
                "preferred": candidate.descriptor,
                "search_clause": f'"{candidate.descriptor}"[MeSH Terms]',
                **{key: value for key, value in candidate.to_dict().items() if key != "descriptor"},
            }
            for candidate in report.candidates
        ],
        "evidence": report.evidence(),
    }


__all__ = [
    "CooccurrenceReport",
    "MeshCorrectionGateway",
    "MeshCorrectionPolicy",
    "MeshCorrectionResult",
    "MeshCorrectionService",
    "PROBE_COUNT_METHOD",
    "PhraseSuggestions",
    "RequestBudget",
    "TermCorrection",
    "cooccurrence_candidate_entry",
]
