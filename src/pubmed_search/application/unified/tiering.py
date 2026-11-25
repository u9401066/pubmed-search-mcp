"""Precision-first deep-search tiering policy and broadening disclosure.

Design:
    The caller's query is authoritative. Deep search runs every ``exact``
    strategy (the caller's query for each planned source) with the full
    per-source budget. Only when the exact tier leaves the requested limit
    unfilled -- after identity deduplication and the exclude_seen /
    detected-preprint eligibility policy -- does it fetch more of the same
    exact query, and only then lower-precision tiers in decreasing-precision
    order, each contributing at most the remaining slots.

    Zero-result auto-relaxation is the last-resort member of the same policy.
    Both mechanisms tag records with :class:`RetrievalProvenance` and produce
    one ``search-broadening/v1`` disclosure, so agents can always tell whether
    broadening happened, why, and which records it added.

    A PubMed MeSH correction (``mechanisms`` entry ``"mesh_correction"``)
    happens before all of this: when PubMed reports that a MeSH clause of the
    caller's query matched nothing, the corrected query is re-run as the exact
    tier and every later decision uses its results. ``mechanisms`` therefore
    lists every automatic change to what was searched, and ``applied`` is
    true when any of them completed (a provider answered);
    ``broadened_records`` alone counts records from lower-precision tiers.

    A deepening, broadening or relaxation request that failed or timed out
    changed nothing about the result. It is counted in ``failed_attempts``
    and named in the summary as failed, never described as a broader query
    that found no new records: an empty answer and a missing answer are
    different coverage facts.

Maintenance:
    This module is pure policy: no I/O, no presentation strings beyond the
    disclosure summary. The infrastructure broker drives provider calls with
    :class:`DeepFillTracker`; the application executor builds the disclosure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pubmed_search.application.search.result_aggregator import ArticleIdentityIndex
from pubmed_search.application.search.semantic_enhancer import STRATEGY_TIER_RANKS
from pubmed_search.application.unified.mesh_correction import correction_summary
from pubmed_search.domain.entities.article import RetrievalProvenance
from pubmed_search.shared.article_identity import (
    normalize_article_doi,
    normalize_article_identifier,
    normalize_article_title,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from pubmed_search.domain.entities.article import UnifiedArticle

    from .helpers import DeepTierOutcome, RelaxationResult, SearchDepthMetrics, StrategyResult

    Eligibility = Callable[[UnifiedArticle], bool]

BROADENING_SCHEMA_VERSION = "search-broadening/v1"
BROADENING_POLICY = "precision_first"
DEEP_FILL_MAX_REQUEST = 100
"""Largest provider request a fill phase may issue (the public per-source maximum)."""

EXACT_TIER = "exact"
NARROW_TIER = "narrow"
RELAXED_TIER = "relaxed"
RELAXED_TIER_RANK = max(STRATEGY_TIER_RANKS.values()) + 1

PHASE_SUPERSEDED = "superseded"
"""Exact attempt replaced by its MeSH-corrected re-run; its records never entered the pool."""
PHASE_MESH_CORRECTION_FAILED = "mesh_correction_failed"
"""Failed re-run of a MeSH-corrected query; the original exact attempt was kept."""
UNADMITTED_PHASES = frozenset({PHASE_SUPERSEDED, PHASE_MESH_CORRECTION_FAILED})
MECHANISM_MESH_CORRECTION = "mesh_correction"

SKIP_LIMIT_FILLED = "limit_filled"
SKIP_BROADENING_DISABLED = "broadening_disabled"
SKIP_EXACT_TIER_FAILED = "exact_tier_failed"
SKIP_NARROWS_EXACT_QUERY = "narrows_exact_query"
SKIP_DUPLICATE_OF_EXACT_QUERY = "duplicate_of_exact_query"
SKIP_DEADLINE_EXHAUSTED = "deadline_exhausted"
BLOCKED_NO_BROADER_STRATEGY = "no_broader_strategy"
POLICY_SKIP_REASONS = frozenset(
    {SKIP_LIMIT_FILLED, SKIP_BROADENING_DISABLED, SKIP_NARROWS_EXACT_QUERY, SKIP_DUPLICATE_OF_EXACT_QUERY}
)
"""Skips that are intended by the precision-first policy (not coverage gaps)."""

_SOURCE_LABELS = {
    "pubmed": "PubMed",
    "europe_pmc": "Europe PMC",
    "openalex": "OpenAlex",
    "semantic_scholar": "Semantic Scholar",
    "core": "CORE",
    "scopus": "Scopus",
    "web_of_science": "Web of Science",
    "arxiv": "arXiv",
    "medrxiv": "medRxiv",
    "biorxiv": "bioRxiv",
}


def source_label(source: str) -> str:
    """Return a human-readable provider name for disclosure text."""
    return _SOURCE_LABELS.get(source, source)


def strategy_tier(strategy: Any) -> str:
    """Return a strategy's declared tier; unknown labels are treated as broad.

    A missing attribute means the strategy runs the given query as-is
    (``exact``). An unrecognized label must never be presented as an exact
    match, so it fails safe to the lowest-precision fill tier.
    """
    tier = getattr(strategy, "tier", EXACT_TIER)
    if tier == NARROW_TIER or tier in STRATEGY_TIER_RANKS:
        return str(tier)
    return "broad"


def strategy_tier_rank(strategy: Any) -> int | None:
    """Return the fill-execution rank, or ``None`` for never-executed narrowings."""
    return STRATEGY_TIER_RANKS.get(strategy_tier(strategy))


def precision_first_order(strategies: Sequence[Any]) -> list[Any]:
    """Order strategies by tier, then priority, then plan position (stable)."""
    never_run = max(STRATEGY_TIER_RANKS.values()) + 1
    indexed = list(enumerate(strategies))
    indexed.sort(
        key=lambda item: (
            rank if (rank := strategy_tier_rank(item[1])) is not None else never_run,
            -int(getattr(item[1], "priority", 0) or 0),
            item[0],
        )
    )
    return [strategy for _index, strategy in indexed]


def provenance_for(strategy: Any) -> RetrievalProvenance:
    """Build the record-level provenance for one fill-tier strategy."""
    tier = strategy_tier(strategy)
    rank = STRATEGY_TIER_RANKS.get(tier, RELAXED_TIER_RANK)
    return RetrievalProvenance(
        source=str(getattr(strategy, "source", "")),
        strategy=str(getattr(strategy, "name", "")),
        tier=tier,
        tier_rank=rank,
    )


def relaxation_provenance(action: str, *, source: str = "pubmed") -> RetrievalProvenance:
    """Build the record-level provenance for a zero-result relaxation step."""
    return RetrievalProvenance(
        source=source,
        strategy=f"auto_relax:{action}",
        tier=RELAXED_TIER,
        tier_rank=RELAXED_TIER_RANK,
    )


def tag_retrieval(articles: Iterable[UnifiedArticle], provenance: RetrievalProvenance) -> None:
    """Attach one provenance entry to every record (idempotent)."""
    for article in articles:
        if provenance not in article.retrieval:
            article.retrieval.append(provenance)


def order_by_retrieval_tier(articles: list[UnifiedArticle]) -> list[UnifiedArticle]:
    """Keep tiers ordered while preserving the ranking inside each tier.

    Python's sort is stable, so ranked order survives within a tier and a
    broadened record can never be placed above an exact-query record.
    """
    return sorted(articles, key=lambda article: article.retrieval_tier_rank)


def _identity_tokens(article: UnifiedArticle) -> frozenset[tuple[str, str]]:
    """Every identity signal of a record: identifiers, else its normalized title.

    This is a superset of the keys the aggregator merges on (it ignores the
    conflict rule and the minimum title length). Fill admission discards any
    candidate sharing one of these tokens with a held record, so a record it
    keeps can never be merged away by the aggregator.
    """
    tokens: set[tuple[str, str]] = set()
    doi = normalize_article_doi(article.doi)
    if doi:
        tokens.add(("doi", doi))
    pmid = str(article.pmid or "").strip()
    if pmid:
        tokens.add(("pmid", pmid))
    for attr, kind in (
        ("pmc", "pmc"),
        ("openalex_id", "openalex"),
        ("s2_id", "s2"),
        ("core_id", "core"),
        ("arxiv_id", "arxiv"),
    ):
        identifier = normalize_article_identifier(kind, getattr(article, attr, None))
        if identifier:
            tokens.add((kind, identifier))
    if not tokens:
        title = normalize_article_title(article.title)
        tokens.add(("title", title) if title else ("object", str(id(article))))
    return frozenset(tokens)


@dataclass
class FillAdmission:
    """Outcome of admitting one provider attempt into the fill pool.

    ``accepted`` are the records handed to the aggregator; an exact-tier
    attempt keeps ineligible records there because the final filters remove
    them. ``contributed`` counts only new *eligible* records -- the ones this
    attempt actually adds to what the caller receives.
    """

    accepted: list[UnifiedArticle] = field(default_factory=list)
    new_unique: int = 0
    duplicates: int = 0
    ineligible: int = 0
    surplus_discarded: int = 0

    @property
    def contributed(self) -> int:
        """New unique records that survive the eligibility policy."""
        return self.new_unique - self.ineligible - self.surplus_discarded


class DeepFillTracker:
    """Count eligible unique records against the requested limit.

    ``admit_exact`` keeps every record of an exact-tier attempt (the final
    filters remove ineligible ones) and counts unique records with the
    aggregator's own :class:`ArticleIdentityIndex` -- same keys, conflict
    rule and title threshold -- so a record bridging two earlier identities
    merges them, and records with conflicting identifiers stay distinct,
    exactly as they will in the aggregated result. A merged record counts as
    eligible only when every member is eligible.

    ``admit_fill`` keeps only new eligible records up to the remaining slots.
    It discards any candidate sharing an identity token with a held record
    (a superset of the aggregator's merge keys), so every kept fill record
    is a new identity for the aggregator as well, and discarded records never
    reach it.
    """

    def __init__(self, requested_limit: int, eligibility: Eligibility | None = None) -> None:
        if requested_limit < 1:
            msg = "requested_limit must be positive"
            raise ValueError(msg)
        self.requested_limit = requested_limit
        self._eligibility = eligibility
        self._index = ArticleIdentityIndex()
        self._pool_eligible: list[bool] = []
        self._tokens: set[tuple[str, str]] = set()
        self.unique_count = 0
        self.eligible_unique = 0

    @property
    def remaining(self) -> int:
        """Eligible slots still open before the requested limit is met."""
        return max(0, self.requested_limit - self.eligible_unique)

    @property
    def filled(self) -> bool:
        """Whether the eligible unique pool reached the requested limit."""
        return self.remaining == 0

    def fill_request_limit(self) -> int:
        """Provider limit large enough to fill the gap despite overlap.

        A broader query can re-return every record already held, so request
        ``remaining + held`` (at least the per-source budget), capped at the
        public per-source maximum.
        """
        return min(DEEP_FILL_MAX_REQUEST, max(self.requested_limit, self.remaining + self.unique_count))

    def _is_eligible(self, article: UnifiedArticle) -> bool:
        return True if self._eligibility is None else bool(self._eligibility(article))

    def _hold(self, article: UnifiedArticle, tokens: frozenset[tuple[str, str]], *, eligible: bool) -> bool:
        """Add one record to the pool; return whether it merged into a held record."""
        self._tokens.update(tokens)
        self._pool_eligible.append(eligible)
        return bool(self._index.add(article))

    def _recount(self) -> None:
        groups = list(self._index.groups().values())
        self.unique_count = len(groups)
        self.eligible_unique = sum(1 for members in groups if all(self._pool_eligible[i] for i in members))

    def admit_exact(self, articles: Sequence[UnifiedArticle], provenance: RetrievalProvenance) -> FillAdmission:
        """Admit an exact-tier attempt; every record is kept and tagged."""
        admission = FillAdmission(accepted=list(articles))
        for article in articles:
            eligible = self._is_eligible(article)
            if self._hold(article, _identity_tokens(article), eligible=eligible):
                admission.duplicates += 1
                continue
            admission.new_unique += 1
            if not eligible:
                admission.ineligible += 1
        self._recount()
        tag_retrieval(admission.accepted, provenance)
        return admission

    def admit_fill(self, articles: Sequence[UnifiedArticle], provenance: RetrievalProvenance) -> FillAdmission:
        """Admit a fill attempt; keep only new eligible records for open slots."""
        admission = FillAdmission()
        for article in articles:
            tokens = _identity_tokens(article)
            if tokens & self._tokens:
                admission.duplicates += 1
                continue
            admission.new_unique += 1
            if not self._is_eligible(article):
                admission.ineligible += 1
                continue
            if self.remaining == 0:
                admission.surplus_discarded += 1
                continue
            # It shares no identity token with anything held: a new identity.
            self._hold(article, tokens, eligible=True)
            self.unique_count += 1
            self.eligible_unique += 1
            admission.accepted.append(article)
        tag_retrieval(admission.accepted, provenance)
        return admission


# ============================================================================
# Broadening disclosure
# ============================================================================


FILL_PHASES = frozenset({"deepen", "broaden"})
"""Automatic fill phases whose provider requests may fail without changing the result."""


def _executed(rows: Iterable[StrategyResult], phase: str) -> list[StrategyResult]:
    return [row for row in rows if row.phase == phase and row.executed]


def _completed(rows: Iterable[StrategyResult], phase: str) -> list[StrategyResult]:
    """Executed attempts the provider answered (records or a confirmed empty result)."""
    return [row for row in _executed(rows, phase) if row.status != "error"]


def _failed(rows: Iterable[StrategyResult], phase: str) -> list[StrategyResult]:
    return [row for row in _executed(rows, phase) if row.status == "error"]


def _failure_verb(row: StrategyResult) -> str:
    errors = row.metadata.get("errors") if isinstance(row.metadata, dict) else None
    kinds = (
        {str(error.get("kind")) for error in errors if isinstance(error, dict)} if isinstance(errors, list) else set()
    )
    return "timed out" if kinds == {"timeout"} else "failed"


def _failed_phrase(action: str, rows: Sequence[StrategyResult]) -> str:
    """Name failed fill attempts; a failure is never presented as an empty result."""
    names = ", ".join(dict.fromkeys(row.strategy_name for row in rows))
    verbs = {_failure_verb(row) for row in rows}
    verb = "timed out" if verbs == {"timed out"} else "failed"
    details = ", ".join(dict.fromkeys(f"{source_label(row.source)} request {_failure_verb(row)}" for row in rows))
    return f" → {action} {names} {verb} ({details})"


def _exact_phrase(rows: Sequence[StrategyResult], count: int, limit: int) -> str:
    exact_rows = _executed(rows, "exact")
    if not exact_rows:
        return f"no exact-tier query ran ({count} of requested {limit})"
    if len(exact_rows) == 1:
        row = exact_rows[0]
        phrase = f"{row.strategy_name} returned {count} of requested {limit}"
        if row.status == "error":
            return phrase + f" ({source_label(row.source)} request failed)"
        if row.total_available is not None:
            phrase += f" ({source_label(row.source)} total {row.total_available})"
        return phrase
    details = "; ".join(
        f"{source_label(row.source)} {row.strategy_name} "
        + (
            "failed"
            if row.status == "error"
            else f"total {row.total_available if row.total_available is not None else 'unknown'}"
        )
        for row in exact_rows
    )
    return f"exact-tier queries returned {count} unique of requested {limit} ({details})"


def _not_needed_phrase(rows: Sequence[StrategyResult], outcome: DeepTierOutcome) -> str:
    limit = outcome.requested_limit
    exact_rows = _executed(rows, "exact")
    single = exact_rows[0] if len(exact_rows) == 1 else None
    if single is not None and single.total_available is not None and single.total_available >= limit:
        phrase = f"no broadening needed ({single.strategy_name} total {single.total_available} ≥ limit {limit}"
    else:
        phrase = f"no broadening needed (exact-tier queries returned {outcome.eligible_unique} eligible unique ≥ limit {limit}"
    if outcome.deepened_records:
        phrase += f"; fetched {outcome.deepened_records} more record(s) from the exact query after exclusions"
    return phrase + ")"


def _deep_summary(metrics: SearchDepthMetrics, outcome: DeepTierOutcome) -> str:
    rows = metrics.strategy_results
    if not outcome.broadening_needed:
        summary = _not_needed_phrase(rows, outcome)
        skipped = list(
            dict.fromkeys(row.strategy_name for row in rows if row.skip_reason == SKIP_LIMIT_FILLED and row.tier_rank)
        )
        if skipped:
            summary += f"; skipped lower-precision strategies: {', '.join(skipped)}"
        return summary

    summary = _exact_phrase(rows, outcome.exact_eligible_unique, outcome.requested_limit)
    if outcome.deepened_records:
        summary += f" → fetched {outcome.deepened_records} more record(s) from the exact query"
    failed_deepening = _failed(rows, "deepen")
    if failed_deepening:
        summary += _failed_phrase("fetching more records from", failed_deepening)
    broadened = list(dict.fromkeys(row.strategy_name for row in _completed(rows, "broaden")))
    failed_broadening = _failed(rows, "broaden")
    if broadened:
        if outcome.broadened_records:
            summary += (
                f" → broadened with {', '.join(broadened)}, adding {outcome.broadened_records} "
                "lower-precision record(s)"
            )
        else:
            summary += f" → broadened with {', '.join(broadened)}, but no new eligible records were found"
    if failed_broadening:
        summary += _failed_phrase("broadening with", failed_broadening)
        summary += ", so lower-precision coverage is incomplete"
    if broadened or failed_broadening:
        if outcome.broadening_blocked_reason == SKIP_DEADLINE_EXHAUSTED:
            summary += "; the remaining broadening was skipped because the deep-search deadline was exhausted"
    elif outcome.broadening_blocked_reason == SKIP_BROADENING_DISABLED:
        summary += '; broadening disabled by options="no_relax"'
    elif outcome.broadening_blocked_reason == SKIP_EXACT_TIER_FAILED:
        summary += "; broadening skipped because the exact-tier query failed (coverage is incomplete, not narrow)"
    elif outcome.broadening_blocked_reason == SKIP_DEADLINE_EXHAUSTED:
        summary += "; broadening skipped because the deep-search deadline was exhausted"
    elif outcome.broadening_blocked_reason == BLOCKED_NO_BROADER_STRATEGY:
        summary += "; no lower-precision strategy was planned"
    return summary


def _relaxation_rows(relaxation: RelaxationResult, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    successful = relaxation.successful_step
    for step in relaxation.steps_tried:
        is_success = successful is not None and step is successful
        rows.append(
            {
                "source": "pubmed",
                "strategy": f"auto_relax:{step.action}",
                "tier": RELAXED_TIER,
                "tier_rank": RELAXED_TIER_RANK,
                "phase": "relax",
                "status": step.status,
                "executed": True,
                "logical_query": step.query,
                "physical_query": step.query,
                "requested": limit,
                "total_available": relaxation.total_results if is_success else None,
                "returned": step.result_count,
                "new_unique": len(relaxation.articles) if is_success else 0,
                "contributed": len(relaxation.articles) if is_success else 0,
                "duplicates": 0,
                "ineligible": 0,
                "surplus_discarded": 0,
                "skip_reason": None,
                "level": step.level,
                "action": step.action,
                "description": step.description,
            }
        )
    return rows


def _relaxation_phrase(relaxation: RelaxationResult) -> str:
    step = relaxation.successful_step
    if step is not None:
        phrase = (
            f" → auto-relaxed the PubMed query (level {step.level}: {step.action}), adding "
            f"{len(relaxation.articles)} lower-precision record(s)"
        )
        if relaxation.incomplete:
            phrase += "; an earlier relaxation request failed"
        return phrase
    if relaxation.incomplete:
        return " → auto-relaxation could not complete every broader PubMed query; completeness is unknown"
    return f" → auto-relaxation tried {len(relaxation.steps_tried)} broader PubMed queries; none returned records"


def _mesh_correction_rows(
    mesh_correction: Mapping[str, Any], pubmed_returned: int, pubmed_eligible: int
) -> list[dict[str, Any]]:
    """Attempt rows for a single-pass (non-deep) search whose PubMed query was corrected."""
    counts = mesh_correction.get("hit_counts") or {}
    before, after = counts.get("before"), counts.get("after")
    base = {
        "source": "pubmed",
        "tier": EXACT_TIER,
        "tier_rank": 0,
        "executed": True,
        "duplicates": 0,
        "surplus_discarded": 0,
        "skip_reason": None,
    }
    return [
        {
            **base,
            "strategy": "original",
            "phase": PHASE_SUPERSEDED,
            "ineligible": 0,
            "status": "empty" if before == 0 else "ok",
            "logical_query": mesh_correction.get("original_query"),
            "physical_query": None,
            "requested": None,
            "total_available": before,
            "returned": None,
            "new_unique": 0,
            "contributed": 0,
        },
        {
            **base,
            "strategy": "original:mesh_corrected",
            "phase": "exact",
            "status": "ok" if pubmed_returned else "empty",
            "logical_query": mesh_correction.get("corrected_query"),
            "physical_query": None,
            "requested": None,
            "total_available": after,
            "returned": pubmed_returned,
            "new_unique": pubmed_returned,
            "ineligible": pubmed_returned - pubmed_eligible,
            "contributed": pubmed_eligible,
        },
    ]


def build_broadening_disclosure(
    *,
    requested_limit: int,
    deep_metrics: SearchDepthMetrics | None,
    relaxation: RelaxationResult | None,
    broadening_enabled: bool,
    exact_pubmed_total: int | None = None,
    mesh_correction: Mapping[str, Any] | None = None,
    pubmed_returned: int = 0,
    pubmed_eligible: int | None = None,
) -> dict[str, Any] | None:
    """Describe automatic query changes (MeSH correction, broadening), why, and their yield.

    ``pubmed_returned`` / ``pubmed_eligible`` describe a single-pass PubMed
    exact result before any relaxation: the records returned, and how many
    of them survive the exclude_seen / detected-preprint policy (defaults to
    all of them).

    Returns ``None`` when no MeSH correction was applied and neither tiered
    deep search nor auto-relaxation ran.
    """
    outcome = deep_metrics.tier_outcome if deep_metrics is not None else None
    corrected = bool(mesh_correction and mesh_correction.get("applied"))
    if outcome is None and relaxation is None and not corrected:
        return None

    attempts: list[dict[str, Any]] = []
    mechanisms: list[str] = []
    needed = False
    blocked_reason: str | None = None
    exact_eligible = 0
    eligible = 0
    deepened = 0
    broadened = 0
    failed_attempts = 0
    filled = False
    summary = ""

    if deep_metrics is not None and outcome is not None:
        rows = deep_metrics.strategy_results
        attempts.extend(row.disclosure() for row in rows)
        # A broadening request that failed broadened nothing.
        if _completed(rows, "broaden"):
            mechanisms.append("deep_strategy_tiers")
        failed_attempts += sum(len(_failed(rows, phase)) for phase in sorted(FILL_PHASES))
        needed = outcome.broadening_needed
        blocked_reason = outcome.broadening_blocked_reason
        exact_eligible = outcome.exact_eligible_unique
        eligible = outcome.eligible_unique
        deepened = outcome.deepened_records
        broadened = outcome.broadened_records
        filled = outcome.filled
        summary = _deep_summary(deep_metrics, outcome)

    if corrected and outcome is None and mesh_correction is not None:
        corrected_eligible = pubmed_returned if pubmed_eligible is None else min(pubmed_eligible, pubmed_returned)
        attempts.extend(_mesh_correction_rows(mesh_correction, pubmed_returned, corrected_eligible))
        exact_eligible = eligible = corrected_eligible
        filled = corrected_eligible >= requested_limit
        needed = not filled
        summary = f"corrected query returned {pubmed_returned} of requested {requested_limit}"
        if corrected_eligible != pubmed_returned:
            summary += f" ({corrected_eligible} eligible after exclusions)"

    if relaxation is not None:
        needed = True
        if any(step.status in {"ok", "empty"} for step in relaxation.steps_tried):
            mechanisms.append("auto_relax")
        failed_attempts += sum(1 for step in relaxation.steps_tried if step.status == "error")
        if outcome is None and not corrected:
            total = f" (PubMed total {exact_pubmed_total})" if exact_pubmed_total is not None else ""
            summary = f"original returned 0 of requested {requested_limit}{total}"
            attempts.insert(
                0,
                {
                    "source": "pubmed",
                    "strategy": "original",
                    "tier": EXACT_TIER,
                    "tier_rank": 0,
                    "phase": "exact",
                    "status": "empty",
                    "executed": True,
                    "logical_query": relaxation.original_query,
                    "physical_query": relaxation.original_query,
                    "requested": requested_limit,
                    "total_available": exact_pubmed_total,
                    "returned": 0,
                    "new_unique": 0,
                    "contributed": 0,
                    "duplicates": 0,
                    "ineligible": 0,
                    "surplus_discarded": 0,
                    "skip_reason": None,
                },
            )
        attempts.extend(_relaxation_rows(relaxation, requested_limit))
        summary += _relaxation_phrase(relaxation)
        if relaxation.successful_step is not None:
            relaxed = len(relaxation.articles)
            broadened = relaxed
            eligible = relaxed
            filled = relaxed >= requested_limit

    if needed and not filled:
        summary += f"; still under-filled ({eligible} of {requested_limit})"
    if corrected:
        mechanisms.insert(0, MECHANISM_MESH_CORRECTION)
        summary = f"{correction_summary(mesh_correction)} → {summary}"
    applied = bool(mechanisms)
    return {
        "schema_version": BROADENING_SCHEMA_VERSION,
        "policy": BROADENING_POLICY,
        "requested_limit": requested_limit,
        "needed": needed,
        "applied": applied,
        "enabled": broadening_enabled,
        "mechanisms": mechanisms,
        "blocked_reason": blocked_reason,
        "exact_eligible_unique": exact_eligible,
        "eligible_unique": eligible,
        "deepened_records": deepened,
        "broadened_records": broadened,
        "failed_attempts": failed_attempts,
        "filled": filled,
        "summary": summary,
        "attempts": attempts,
    }


def compact_broadening(disclosure: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the attempt-free projection used by size-capped responses."""
    if not disclosure:
        return None
    return {
        key: disclosure.get(key)
        for key in (
            "schema_version",
            "needed",
            "applied",
            "mechanisms",
            "broadened_records",
            "failed_attempts",
            "filled",
            "summary",
        )
    }


__all__ = [
    "BROADENING_SCHEMA_VERSION",
    "DEEP_FILL_MAX_REQUEST",
    "MECHANISM_MESH_CORRECTION",
    "PHASE_MESH_CORRECTION_FAILED",
    "PHASE_SUPERSEDED",
    "POLICY_SKIP_REASONS",
    "DeepFillTracker",
    "FillAdmission",
    "build_broadening_disclosure",
    "compact_broadening",
    "order_by_retrieval_tier",
    "precision_first_order",
    "provenance_for",
    "relaxation_provenance",
    "source_label",
    "strategy_tier",
    "strategy_tier_rank",
    "tag_retrieval",
    "UNADMITTED_PHASES",
]
