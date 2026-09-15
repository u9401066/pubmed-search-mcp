"""Stable, typed Python SDK facade for PubMed Search MCP.

The SDK composes the same application use case as MCP without importing the
presentation package or producing MCP response strings, session records, and
artifacts. Runtime clients are created lazily and owned by this client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from typing_extensions import Self

from pubmed_search.application.search.source_models import SourceSearchPage

if TYPE_CHECKING:
    from pubmed_search.application.unified.planning import UnifiedSearchPlan
    from pubmed_search.application.unified.request import UnifiedSearchRequest
    from pubmed_search.application.unified.use_case import UnifiedSearchUseCase
    from pubmed_search.domain.entities.article import UnifiedArticle
    from pubmed_search.infrastructure.sources.runtime import SourceRuntime


@dataclass(frozen=True)
class PubMedSearchConfig:
    """SDK settings; ``data_dir`` is reserved and does not enable persistence."""

    email: str = "pubmed-search@example.com"
    api_key: str | None = field(default=None, repr=False)
    data_dir: str | None = None


@dataclass(frozen=True, slots=True)
class UnifiedSourceCount:
    """Typed provider coverage row returned by the Python SDK."""

    source: str
    returned: int
    total_available: int | None
    status: str


@dataclass(frozen=True, slots=True)
class UnifiedSearchResult:
    """Typed application result with no MCP serialization side effects."""

    request: UnifiedSearchRequest
    plan: UnifiedSearchPlan
    articles: tuple[UnifiedArticle, ...]
    source_counts: tuple[UnifiedSourceCount, ...]
    source_errors: tuple[dict[str, Any], ...]
    result_filter_counts: dict[str, int]

    @classmethod
    def from_outcome(cls, outcome: Any) -> UnifiedSearchResult:
        """Project an application outcome into the SDK result contract."""
        execution = outcome.execution
        counts = tuple(
            UnifiedSourceCount(
                source=source,
                returned=returned,
                total_available=total_available,
                status=execution.source_statuses.get(source, "unknown"),
            )
            for source, (returned, total_available) in sorted(execution.source_api_counts.items())
        )
        return cls(
            request=outcome.request,
            plan=outcome.plan,
            articles=tuple(execution.ranked),
            source_counts=counts,
            source_errors=tuple(dict(error) for error in execution.source_errors),
            result_filter_counts=dict(execution.result_filter_counts),
        )


class PubMedSearchClient:
    """High-level in-process client for package and notebook consumers."""

    def __init__(
        self,
        config: PubMedSearchConfig | None = None,
        *,
        searcher: Any | None = None,
        unified_search_use_case: UnifiedSearchUseCase | None = None,
    ) -> None:
        self.config = config or PubMedSearchConfig()
        self._searcher = searcher
        self._source_runtime: SourceRuntime | None = None
        self._unified_search_use_case = unified_search_use_case

    @property
    def searcher(self) -> Any:
        """Return the lazily-created low-level PubMed searcher."""
        if self._searcher is None:
            from pubmed_search.infrastructure.ncbi import LiteratureSearcher

            self._searcher = LiteratureSearcher(email=self.config.email, api_key=self.config.api_key)
        return self._searcher

    async def search_pubmed_page(
        self,
        query: str,
        *,
        limit: int = 10,
        **kwargs: Any,
    ) -> SourceSearchPage[dict[str, Any]]:
        """Search PubMed through the sole typed provider-page contract."""
        page = await self.searcher.search_page(query=query, limit=limit, **kwargs)
        if not isinstance(page, SourceSearchPage) or page.source != "pubmed":
            raise TypeError("PubMed searcher must return a pubmed SourceSearchPage")
        return page

    async def fetch_details(self, pmids: list[str]) -> list[dict[str, Any]]:
        """Fetch PubMed article details by PMID."""
        result = await self.searcher.fetch_details(pmids)
        return list(result)

    async def unified_search(
        self,
        query: str,
        *,
        limit: int = 10,
        sources: str | None = None,
        ranking: Literal["balanced", "impact", "recency", "quality"] = "balanced",
        filters: str | None = None,
        options: str | None = None,
    ) -> UnifiedSearchResult:
        """Execute the application use case and return typed search state."""
        from pubmed_search.application.unified.request import normalize_unified_search_request

        request = normalize_unified_search_request(
            query=query,
            limit=limit,
            sources=sources,
            ranking=ranking,
            output_format="json",
            filters=filters,
            options=options,
        )
        use_case = self._get_unified_search_use_case()

        from pubmed_search.infrastructure.sources.runtime import bind_source_runtime
        from pubmed_search.shared.async_utils import bind_shared_async_client_runtime

        source_runtime = self._get_source_runtime()
        with (
            bind_source_runtime(source_runtime),
            bind_shared_async_client_runtime(source_runtime.shared_http),
        ):
            outcome = await use_case.execute(request, progress=_ignore_progress)
        return UnifiedSearchResult.from_outcome(outcome)

    async def aclose(self) -> None:
        """Close provider clients and HTTP pools owned by this SDK client."""
        runtime = self._source_runtime
        self._source_runtime = None
        if runtime is not None:
            await runtime.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    def _get_source_runtime(self) -> SourceRuntime:
        if self._source_runtime is None:
            from pubmed_search.infrastructure.sources.runtime import SourceRuntime

            self._source_runtime = SourceRuntime(contact_email=self.config.email)
        return self._source_runtime

    def _get_unified_search_use_case(self) -> UnifiedSearchUseCase:
        if self._unified_search_use_case is None:
            from pubmed_search.application.search.query_analyzer import QueryAnalyzer
            from pubmed_search.application.unified.execution import execute_unified_search
            from pubmed_search.application.unified.planning import build_unified_search_plan
            from pubmed_search.application.unified.use_case import UnifiedSearchUseCase
            from pubmed_search.infrastructure.pubtator.semantic_adapter import get_semantic_enhancer
            from pubmed_search.infrastructure.sources.registry import get_source_registry
            from pubmed_search.infrastructure.sources.unified_broker import UnifiedSourceBroker
            from pubmed_search.infrastructure.sources.unified_enrichment import UnifiedEnrichmentAdapter

            self._unified_search_use_case = UnifiedSearchUseCase(
                planner=build_unified_search_plan,
                executor=execute_unified_search,
                source_broker=UnifiedSourceBroker(self.searcher),
                enrichment=UnifiedEnrichmentAdapter(),
                analyzer_factory=QueryAnalyzer,
                enhancer_factory=get_semantic_enhancer,
                source_registry_factory=get_source_registry,
            )
        return self._unified_search_use_case


async def _ignore_progress(progress: float, total: float, message: str) -> None:
    """SDK progress adapter used when the caller has no reporting channel."""
    del progress, total, message


__all__ = [
    "PubMedSearchClient",
    "PubMedSearchConfig",
    "SourceSearchPage",
    "UnifiedSearchResult",
    "UnifiedSourceCount",
]
