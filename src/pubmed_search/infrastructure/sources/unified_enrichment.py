"""
Unified Search — Enrichment Module.

Builds typed, non-mutating patches from Crossref, OpenAlex journal metrics, and
Unpaywall, then applies those patches centrally with deterministic precedence.
It also contains local rank-percentile and preprint-detection helpers.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

import httpx

from pubmed_search.domain.entities.article import JournalMetrics, OpenAccessLink, OpenAccessStatus
from pubmed_search.domain.services.article_mapper import article_from_crossref
from pubmed_search.infrastructure.sources import (
    get_crossref_client,
    get_openalex_client,
    get_unpaywall_client,
)
from pubmed_search.infrastructure.sources.base_client import APIRequestError
from pubmed_search.shared.async_utils import RetryableOperationError

if TYPE_CHECKING:
    from pubmed_search.domain.entities.article import UnifiedArticle

logger = logging.getLogger(__name__)

EnrichmentSource = Literal["crossref", "journal_metrics", "unpaywall"]
EnrichmentFailureCategory = Literal[
    "invalid_response",
    "provider_unavailable",
    "rate_limited",
    "timeout",
    "unexpected",
]
EnrichmentItemStatus = Literal["succeeded", "skipped", "failed"]

_ENRICHMENT_ORDER: dict[EnrichmentSource, int] = {
    "crossref": 0,
    "journal_metrics": 1,
    "unpaywall": 2,
}
_MAX_ITEM_ENRICHMENTS = 10


@dataclass(frozen=True, slots=True)
class ArticleEnrichmentPatch:
    """One provider-owned patch to apply after every enrichment task finishes."""

    source: EnrichmentSource
    article_index: int
    crossref_article: UnifiedArticle | None = None
    journal_metrics: JournalMetrics | None = None
    is_open_access: bool | None = None
    oa_status: OpenAccessStatus | None = None
    oa_links: tuple[OpenAccessLink, ...] = ()


@dataclass(frozen=True, slots=True)
class EnrichmentFailure:
    """Stable, non-sensitive enrichment failure metadata."""

    category: EnrichmentFailureCategory
    article_index: int | None = None


@dataclass(frozen=True, slots=True)
class EnrichmentOutcome:
    """Pure result from one optional enrichment provider."""

    source: EnrichmentSource
    attempted: int
    succeeded: int
    skipped: int
    patches: tuple[ArticleEnrichmentPatch, ...] = ()
    failures: tuple[EnrichmentFailure, ...] = ()

    @property
    def failed(self) -> int:
        return len(self.failures)

    @property
    def status(self) -> Literal["completed", "failed", "partial", "skipped"]:
        if self.failures and self.succeeded:
            return "partial"
        if self.failures:
            return "failed"
        if self.attempted == 0:
            return "skipped"
        return "completed"

    def to_diagnostic(self) -> dict[str, Any]:
        category_counts = Counter(failure.category for failure in self.failures)
        return {
            "source": self.source,
            "status": self.status,
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "skipped": self.skipped,
            "failed": self.failed,
            "failure_categories": dict(sorted(category_counts.items())),
        }


@dataclass(frozen=True, slots=True)
class EnrichmentReport:
    """Deterministic aggregate of all requested optional enrichments."""

    outcomes: tuple[EnrichmentOutcome, ...] = ()

    @property
    def attempted(self) -> int:
        return sum(outcome.attempted for outcome in self.outcomes)

    @property
    def succeeded(self) -> int:
        return sum(outcome.succeeded for outcome in self.outcomes)

    @property
    def skipped(self) -> int:
        return sum(outcome.skipped for outcome in self.outcomes)

    @property
    def failed(self) -> int:
        return sum(outcome.failed for outcome in self.outcomes)

    @property
    def status(self) -> Literal["completed", "failed", "not_requested", "partial"]:
        if not self.outcomes:
            return "not_requested"
        if self.failed and self.succeeded:
            return "partial"
        if self.failed:
            return "failed"
        return "completed"

    def to_diagnostic(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "skipped": self.skipped,
            "failed": self.failed,
            "providers": [outcome.to_diagnostic() for outcome in self.outcomes],
        }


@dataclass(frozen=True, slots=True)
class _EnrichmentItemResult:
    article_index: int
    status: EnrichmentItemStatus
    patch: ArticleEnrichmentPatch | None = None
    failure_category: EnrichmentFailureCategory | None = None


def _classify_enrichment_failure(error: Exception) -> EnrichmentFailureCategory:
    """Classify a failure without retaining its message, URL, or traceback."""
    status_code = getattr(error, "status_code", None)
    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
    if status_code == 429:
        return "rate_limited"
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return "timeout"
    if isinstance(error, httpx.HTTPStatusError):
        return "provider_unavailable"
    if isinstance(error, (APIRequestError, RetryableOperationError, httpx.RequestError)):
        return "provider_unavailable"
    if isinstance(error, (AttributeError, IndexError, KeyError, TypeError, ValueError)):
        return "invalid_response"
    return "unexpected"


def _failure_item(article_index: int, error: Exception) -> _EnrichmentItemResult:
    return _EnrichmentItemResult(
        article_index=article_index,
        status="failed",
        failure_category=_classify_enrichment_failure(error),
    )


def _require_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError
    return cast("dict[str, Any]", value)


def _journal_metrics_from_payload(value: object) -> JournalMetrics:
    data = _require_mapping(value)
    subject_areas = data.get("subject_areas", [])
    if not isinstance(subject_areas, list) or any(not isinstance(item, str) for item in subject_areas):
        raise TypeError
    return JournalMetrics(
        issn=data.get("issn"),
        issn_l=data.get("issn_l"),
        openalex_source_id=data.get("openalex_source_id"),
        h_index=data.get("h_index"),
        two_year_mean_citedness=data.get("two_year_mean_citedness"),
        i10_index=data.get("i10_index"),
        works_count=data.get("works_count"),
        cited_by_count=data.get("cited_by_count"),
        is_in_doaj=data.get("is_in_doaj"),
        source_type=data.get("source_type"),
        subject_areas=subject_areas,
    )


def _outcome_from_items(
    source: EnrichmentSource,
    *,
    total_articles: int,
    attempted: int,
    items: list[_EnrichmentItemResult],
) -> EnrichmentOutcome:
    patches = tuple(
        item.patch
        for item in sorted(items, key=lambda item: item.article_index)
        if item.status == "succeeded" and item.patch is not None
    )
    failures = tuple(
        EnrichmentFailure(
            category=item.failure_category,
            article_index=item.article_index,
        )
        for item in sorted(items, key=lambda item: item.article_index)
        if item.status == "failed" and item.failure_category is not None
    )
    skipped = max(total_articles - attempted, 0) + sum(item.status == "skipped" for item in items)
    return EnrichmentOutcome(
        source=source,
        attempted=attempted,
        succeeded=len(patches),
        skipped=skipped,
        patches=patches,
        failures=failures,
    )


def _provider_initialization_failure(
    source: EnrichmentSource,
    *,
    total_articles: int,
    article_indices: list[int],
    error: Exception,
) -> EnrichmentOutcome:
    category = _classify_enrichment_failure(error)
    return EnrichmentOutcome(
        source=source,
        attempted=len(article_indices),
        succeeded=0,
        skipped=max(total_articles - len(article_indices), 0),
        failures=tuple(EnrichmentFailure(category=category, article_index=index) for index in article_indices),
    )


# ============================================================================
# CrossRef Enrichment
# ============================================================================


async def _enrich_with_crossref(articles: list[UnifiedArticle]) -> EnrichmentOutcome:
    """Return Crossref patches without mutating the shared article list."""
    candidates = [
        (index, article.doi) for index, article in enumerate(articles) if article.doi and not article.citation_metrics
    ][:_MAX_ITEM_ENRICHMENTS]
    if not candidates:
        return _outcome_from_items(
            "crossref",
            total_articles=len(articles),
            attempted=0,
            items=[],
        )

    try:
        client = get_crossref_client()
    except Exception as error:
        return _provider_initialization_failure(
            "crossref",
            total_articles=len(articles),
            article_indices=[index for index, _doi in candidates],
            error=error,
        )

    async def _fetch(article_index: int, doi: str) -> _EnrichmentItemResult:
        try:
            work = await client.get_work(doi)
            if work is None:
                return _EnrichmentItemResult(article_index=article_index, status="skipped")
            crossref_article = article_from_crossref(_require_mapping(work))
        except Exception as error:
            return _failure_item(article_index, error)
        return _EnrichmentItemResult(
            article_index=article_index,
            status="succeeded",
            patch=ArticleEnrichmentPatch(
                source="crossref",
                article_index=article_index,
                crossref_article=crossref_article,
            ),
        )

    items = await asyncio.gather(*(_fetch(index, doi) for index, doi in candidates))
    return _outcome_from_items(
        "crossref",
        total_articles=len(articles),
        attempted=len(candidates),
        items=list(items),
    )


# ============================================================================
# Journal Metrics Enrichment (OpenAlex Sources API)
# ============================================================================


async def _enrich_with_journal_metrics(articles: list[UnifiedArticle]) -> EnrichmentOutcome:
    """Return OpenAlex journal-metric patches without shared mutation.

    Fetches journal h-index, 2yr_mean_citedness (OpenAlex citation metric), ISSN, DOAJ status,
    subject areas, etc. Uses batch API for efficiency.

    Strategy:
    1. Collect OpenAlex source IDs from articles that came from OpenAlex
    2. Batch-fetch source metadata
    3. For articles without source IDs, skip (no reliable lookup available)
    4. Create JournalMetrics objects and assign to articles
    """
    source_id_to_articles: dict[str, list[int]] = {}
    for index, article in enumerate(articles):
        if article.journal_metrics:
            continue
        source_id = _extract_openalex_source_id(article)
        if source_id:
            clean_id = source_id.replace("https://openalex.org/", "")
            source_id_to_articles.setdefault(clean_id, []).append(index)

    article_indices = sorted(index for indices in source_id_to_articles.values() for index in indices)
    if not article_indices:
        return _outcome_from_items(
            "journal_metrics",
            total_articles=len(articles),
            attempted=0,
            items=[],
        )

    try:
        client = get_openalex_client()
        source_data = _require_mapping(await client.get_sources_batch(list(source_id_to_articles.keys())))
    except Exception as error:
        return _provider_initialization_failure(
            "journal_metrics",
            total_articles=len(articles),
            article_indices=article_indices,
            error=error,
        )

    items: list[_EnrichmentItemResult] = []
    for source_id in sorted(source_id_to_articles):
        data = source_data.get(source_id)
        for article_index in sorted(source_id_to_articles[source_id]):
            if data is None:
                items.append(_EnrichmentItemResult(article_index=article_index, status="skipped"))
                continue
            try:
                journal_metrics = _journal_metrics_from_payload(data)
            except Exception as error:
                items.append(_failure_item(article_index, error))
                continue
            items.append(
                _EnrichmentItemResult(
                    article_index=article_index,
                    status="succeeded",
                    patch=ArticleEnrichmentPatch(
                        source="journal_metrics",
                        article_index=article_index,
                        journal_metrics=journal_metrics,
                    ),
                )
            )

    return _outcome_from_items(
        "journal_metrics",
        total_articles=len(articles),
        attempted=len(article_indices),
        items=items,
    )


def _extract_openalex_source_id(article: UnifiedArticle) -> str | None:
    """Extract OpenAlex source ID from an article's metadata.

    Checks:
    1. raw_data._openalex_source_id (set by OpenAlex _normalize_work)
    2. raw_data.primary_location.source.id (direct OpenAlex response)
    """
    for source_meta in article.sources:
        if source_meta.source == "openalex" and source_meta.raw_data:
            raw = source_meta.raw_data
            # Check _openalex_source_id (set in _normalize_work)
            source_id = raw.get("_openalex_source_id")
            if isinstance(source_id, str) and source_id:
                return source_id
            # Fallback: check nested structure
            location = raw.get("primary_location", {})
            if isinstance(location, dict):
                source = location.get("source", {})
                source_id = source.get("id") if isinstance(source, dict) else None
                if isinstance(source_id, str) and source_id:
                    return source_id
    return None


# ============================================================================
# Unpaywall OA Link Enrichment
# ============================================================================


def _unpaywall_patch(article_index: int, oa_info: object) -> _EnrichmentItemResult:
    if not isinstance(oa_info, dict):
        raise TypeError
    is_oa = oa_info.get("is_oa")
    if not isinstance(is_oa, bool):
        raise TypeError
    if not is_oa:
        return _EnrichmentItemResult(article_index=article_index, status="skipped")

    raw_links = oa_info.get("oa_links", [])
    if not isinstance(raw_links, list):
        raise TypeError
    links: list[OpenAccessLink] = []
    for raw_link in raw_links:
        if not isinstance(raw_link, dict):
            raise TypeError
        url = raw_link.get("url")
        if url is None:
            continue
        if not isinstance(url, str) or not url:
            raise TypeError
        raw_version = raw_link.get("version", "unknown")
        version = (
            raw_version if raw_version in {"acceptedVersion", "publishedVersion", "submittedVersion"} else "unknown"
        )
        raw_host_type = raw_link.get("host_type")
        host_type = raw_host_type if raw_host_type in {"preprint", "publisher", "repository"} else None
        links.append(
            OpenAccessLink(
                url=url,
                version=cast("Any", version),
                host_type=cast("Any", host_type),
                license=raw_link.get("license") if isinstance(raw_link.get("license"), str) else None,
                is_best=raw_link.get("is_best") is True,
            )
        )

    status_map = {
        "gold": OpenAccessStatus.GOLD,
        "green": OpenAccessStatus.GREEN,
        "hybrid": OpenAccessStatus.HYBRID,
        "bronze": OpenAccessStatus.BRONZE,
    }
    raw_status = oa_info.get("oa_status")
    status = raw_status if isinstance(raw_status, str) else "unknown"
    patch = ArticleEnrichmentPatch(
        source="unpaywall",
        article_index=article_index,
        is_open_access=True,
        oa_status=status_map.get(status, OpenAccessStatus.UNKNOWN),
        oa_links=tuple(sorted(links, key=lambda link: (not link.is_best, link.url, link.version))),
    )
    return _EnrichmentItemResult(article_index=article_index, status="succeeded", patch=patch)


async def _enrich_with_unpaywall(articles: list[UnifiedArticle]) -> EnrichmentOutcome:
    """Return Unpaywall patches without mutating the shared article list."""
    candidates = [
        (index, article.doi) for index, article in enumerate(articles) if article.doi and not article.has_open_access
    ][:_MAX_ITEM_ENRICHMENTS]
    if not candidates:
        return _outcome_from_items(
            "unpaywall",
            total_articles=len(articles),
            attempted=0,
            items=[],
        )

    try:
        client = get_unpaywall_client()
    except Exception as error:
        return _provider_initialization_failure(
            "unpaywall",
            total_articles=len(articles),
            article_indices=[index for index, _doi in candidates],
            error=error,
        )

    async def _fetch(article_index: int, doi: str) -> _EnrichmentItemResult:
        try:
            return _unpaywall_patch(article_index, await client.enrich_article(doi))
        except Exception as error:
            return _failure_item(article_index, error)

    items = await asyncio.gather(*(_fetch(index, doi) for index, doi in candidates))
    return _outcome_from_items(
        "unpaywall",
        total_articles=len(articles),
        attempted=len(candidates),
        items=list(items),
    )


def _apply_enrichment_outcomes(
    articles: list[UnifiedArticle],
    outcomes: list[EnrichmentOutcome] | tuple[EnrichmentOutcome, ...],
) -> None:
    """Apply patches centrally using stable provider and article precedence."""
    ordered_outcomes = sorted(outcomes, key=lambda outcome: _ENRICHMENT_ORDER[outcome.source])
    for outcome in ordered_outcomes:
        for patch in sorted(outcome.patches, key=lambda item: item.article_index):
            if not 0 <= patch.article_index < len(articles):
                continue
            article = articles[patch.article_index]
            if patch.crossref_article is not None:
                article.merge_from(patch.crossref_article)
            if patch.journal_metrics is not None and article.journal_metrics is None:
                article.journal_metrics = patch.journal_metrics
            if patch.is_open_access is not None:
                article.is_open_access = patch.is_open_access
            if patch.oa_status is not None:
                article.oa_status = patch.oa_status
            if patch.oa_links:
                links_by_url = {link.url: link for link in article.oa_links}
                links_by_url.update({link.url: link for link in patch.oa_links})
                article.oa_links = sorted(
                    links_by_url.values(),
                    key=lambda link: (not link.is_best, link.url, link.version),
                )


async def run_unified_enrichments(
    articles: list[UnifiedArticle],
    *,
    include_crossref: bool,
    include_journal_metrics: bool,
    include_unpaywall: bool,
) -> EnrichmentReport:
    """Gather pure enrichment outcomes, then apply their patches once."""
    tasks: list[tuple[EnrichmentSource, asyncio.Task[EnrichmentOutcome]]] = []
    if include_crossref:
        tasks.append(("crossref", asyncio.create_task(_enrich_with_crossref(articles))))
    if include_journal_metrics:
        tasks.append(("journal_metrics", asyncio.create_task(_enrich_with_journal_metrics(articles))))
    if include_unpaywall:
        tasks.append(("unpaywall", asyncio.create_task(_enrich_with_unpaywall(articles))))
    if not tasks:
        return EnrichmentReport()

    gathered = await asyncio.gather(*(task for _source, task in tasks), return_exceptions=True)
    outcomes: list[EnrichmentOutcome] = []
    for (source, _task), result in zip(tasks, gathered, strict=True):
        if isinstance(result, EnrichmentOutcome):
            outcomes.append(result)
            continue
        if isinstance(result, asyncio.CancelledError):
            raise result
        error = result if isinstance(result, Exception) else TypeError()
        outcomes.append(
            _provider_initialization_failure(
                source,
                total_articles=len(articles),
                article_indices=list(range(len(articles))),
                error=error,
            )
        )

    outcomes.sort(key=lambda outcome: _ENRICHMENT_ORDER[outcome.source])
    _apply_enrichment_outcomes(articles, outcomes)
    report = EnrichmentReport(tuple(outcomes))
    if report.failed:
        categories = sorted({failure.category for outcome in report.outcomes for failure in outcome.failures})
        logger.warning(
            "Optional enrichment incomplete (failed=%s, categories=%s)",
            report.failed,
            ",".join(categories),
        )
    return report


@dataclass(frozen=True, slots=True)
class UnifiedEnrichmentAdapter:
    """Infrastructure implementation of the application enrichment port."""

    async def enrich(
        self,
        articles: list[UnifiedArticle],
        *,
        include_crossref: bool,
        include_journal_metrics: bool,
        include_unpaywall: bool,
    ) -> EnrichmentReport:
        """Run optional provider enrichments and apply deterministic patches."""
        return await run_unified_enrichments(
            articles,
            include_crossref=include_crossref,
            include_journal_metrics=include_journal_metrics,
            include_unpaywall=include_unpaywall,
        )
