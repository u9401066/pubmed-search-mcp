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

Maintenance:
    This module is pure policy: no I/O, no presentation strings beyond the
    disclosure summary. The infrastructure broker drives provider calls with
    :class:`DeepFillTracker`; the application executor builds the disclosure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pubmed_search.application.search.semantic_enhancer import STRATEGY_TIER_RANKS
from pubmed_search.domain.entities.article import RetrievalProvenance
from pubmed_search.shared.article_identity import (
    normalize_article_doi,
    normalize_article_identifier,
    normalize_article_title,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

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
    """Return the identity keys the aggregator would use to merge a record."""
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
    """Outcome of admitting one provider attempt into the fill pool."""

    accepted: list[UnifiedArticle] = field(default_factory=list)
    new_unique: int = 0
    duplicates: int = 0
    ineligible: int = 0
    surplus_discarded: int = 0


class DeepFillTracker:
    """Count eligible unique records against the requested limit.

    ``admit_exact`` keeps every record of an exact-tier attempt (cross-source
    duplicates still merge in the aggregator) while counting new eligible
    identities. ``admit_fill`` keeps only new eligible records up to the
    remaining slots and discards duplicates, ineligible records, and surplus.
    """

    def __init__(self, requested_limit: int, eligibility: Eligibility | None = None) -> None:
        if requested_limit < 1:
            msg = "requested_limit must be positive"
            raise ValueError(msg)
        self.requested_limit = requested_limit
        self._eligibility = eligibility
        self._seen: set[tuple[str, str]] = set()
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

    def admit_exact(self, articles: Sequence[UnifiedArticle], provenance: RetrievalProvenance) -> FillAdmission:
        """Admit an exact-tier attempt; every record is kept and tagged."""
        admission = FillAdmission(accepted=list(articles))
        for article in articles:
            tokens = _identity_tokens(article)
            if tokens & self._seen:
                admission.duplicates += 1
                self._seen.update(tokens)
                continue
            self._seen.update(tokens)
            self.unique_count += 1
            admission.new_unique += 1
            if self._is_eligible(article):
                self.eligible_unique += 1
            else:
                admission.ineligible += 1
        tag_retrieval(admission.accepted, provenance)
        return admission

    def admit_fill(self, articles: Sequence[UnifiedArticle], provenance: RetrievalProvenance) -> FillAdmission:
        """Admit a fill attempt; keep only new eligible records for open slots."""
        admission = FillAdmission()
        for article in articles:
            tokens = _identity_tokens(article)
            if tokens & self._seen:
                admission.duplicates += 1
                continue
            admission.new_unique += 1
            if not self._is_eligible(article):
                admission.ineligible += 1
                continue
            if self.remaining == 0:
                admission.surplus_discarded += 1
                continue
            self._seen.update(tokens)
            self.unique_count += 1
            self.eligible_unique += 1
            admission.accepted.append(article)
        tag_retrieval(admission.accepted, provenance)
        return admission


# ============================================================================
# Broadening disclosure
# ============================================================================


def _executed(rows: Iterable[StrategyResult], phase: str) -> list[StrategyResult]:
    return [row for row in rows if row.phase == phase and row.executed]


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
    broadened = list(dict.fromkeys(row.strategy_name for row in _executed(rows, "broaden")))
    if broadened:
        if outcome.broadened_records:
            summary += (
                f" → broadened with {', '.join(broadened)}, adding {outcome.broadened_records} "
                "lower-precision record(s)"
            )
        else:
            summary += f" → broadened with {', '.join(broadened)}, but no new eligible records were found"
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


def build_broadening_disclosure(
    *,
    requested_limit: int,
    deep_metrics: SearchDepthMetrics | None,
    relaxation: RelaxationResult | None,
    broadening_enabled: bool,
    exact_pubmed_total: int | None = None,
) -> dict[str, Any] | None:
    """Describe whether automatic broadening happened, why, and its yield.

    Returns ``None`` when neither tiered deep search nor auto-relaxation ran.
    """
    outcome = deep_metrics.tier_outcome if deep_metrics is not None else None
    if outcome is None and relaxation is None:
        return None

    attempts: list[dict[str, Any]] = []
    mechanisms: list[str] = []
    needed = False
    blocked_reason: str | None = None
    exact_eligible = 0
    eligible = 0
    deepened = 0
    broadened = 0
    filled = False
    summary = ""

    if deep_metrics is not None and outcome is not None:
        attempts.extend(row.disclosure() for row in deep_metrics.strategy_results)
        if any(row.phase == "broaden" and row.executed for row in deep_metrics.strategy_results):
            mechanisms.append("deep_strategy_tiers")
        needed = outcome.broadening_needed
        blocked_reason = outcome.broadening_blocked_reason
        exact_eligible = outcome.exact_eligible_unique
        eligible = outcome.eligible_unique
        deepened = outcome.deepened_records
        broadened = outcome.broadened_records
        filled = outcome.filled
        summary = _deep_summary(deep_metrics, outcome)

    if relaxation is not None:
        needed = True
        if relaxation.steps_tried:
            mechanisms.append("auto_relax")
        if outcome is None:
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
            "filled",
            "summary",
        )
    }


__all__ = [
    "BROADENING_SCHEMA_VERSION",
    "DEEP_FILL_MAX_REQUEST",
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
]
