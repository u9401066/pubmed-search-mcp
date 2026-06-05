"""Stable Python SDK facade for PubMed Search MCP.

This module is intentionally lightweight. Importing it must not initialize MCP,
HTTP clients, pydantic settings, or source registries. Runtime dependencies are
created lazily when a method is called, and tests/integrations can inject their
own searcher or unified-search runner.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from pubmed_search.application.unified import (
    UnifiedSearchRunner,
    UnifiedSearchRunRequest,
    UnifiedSearchService,
)


@dataclass(frozen=True)
class PubMedSearchConfig:
    """Configuration used by :class:`PubMedSearchClient`."""

    email: str = "pubmed-search@example.com"
    api_key: str | None = None
    data_dir: str | None = None


@dataclass
class UnifiedSearchResult:
    """Structured SDK result for `PubMedSearchClient.unified_search`."""

    raw: str
    output_format: Literal["markdown", "json", "toon"] = "json"
    structured: dict[str, Any] = field(init=False)

    def __post_init__(self) -> None:
        if self.output_format != "json":
            self.structured = {}
            return
        try:
            parsed = json.loads(self.raw)
        except json.JSONDecodeError as exc:
            msg = "Unable to parse unified_search JSON response"
            raise ValueError(msg) from exc
        if not isinstance(parsed, dict):
            msg = "Expected unified_search JSON response to be an object"
            raise TypeError(msg)
        self.structured = parsed

    @property
    def articles(self) -> list[dict[str, Any]]:
        """Return article dictionaries from structured JSON/TOON output."""
        results = self.structured.get("articles", self.structured.get("results", []))
        return list(results) if isinstance(results, list) else []

    @property
    def source_counts(self) -> list[dict[str, Any]]:
        """Return per-source count rows when present."""
        counts = self.structured.get("source_counts", [])
        return list(counts) if isinstance(counts, list) else []

    @property
    def artifact(self) -> dict[str, Any] | None:
        """Return artifact locator summary when unified_search persisted one."""
        artifact = self.structured.get("artifact_summary")
        return dict(artifact) if isinstance(artifact, dict) else None


class PubMedSearchClient:
    """High-level Python client for package consumers.

    The client deliberately exposes a smaller, stable contract than the MCP
    tool registry. For full agent-oriented behavior, keep using the MCP server.
    """

    def __init__(
        self,
        config: PubMedSearchConfig | None = None,
        *,
        searcher: Any | None = None,
        unified_search_runner: UnifiedSearchRunner | None = None,
    ) -> None:
        self.config = config or PubMedSearchConfig()
        self._searcher = searcher
        self._unified_search_service = (
            UnifiedSearchService(unified_search_runner) if unified_search_runner is not None else None
        )

    @property
    def searcher(self) -> Any:
        """Return the lazily-created low-level PubMed searcher."""
        if self._searcher is None:
            from pubmed_search.infrastructure.ncbi import LiteratureSearcher

            self._searcher = LiteratureSearcher(email=self.config.email, api_key=self.config.api_key)
        return self._searcher

    async def search_pubmed(
        self,
        query: str,
        *,
        limit: int = 10,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Search PubMed directly through the low-level Entrez searcher."""
        result = await self.searcher.search(query=query, limit=limit, **kwargs)
        return list(result)

    async def fetch_details(self, pmids: list[str]) -> list[dict[str, Any]]:
        """Fetch PubMed article details by PMID."""
        result = await self.searcher.fetch_details(pmids)
        return list(result)

    async def unified_search(
        self,
        query: str,
        *,
        limit: int | str = 10,
        sources: str | None = None,
        ranking: Literal["balanced", "impact", "recency", "quality"] = "balanced",
        output_format: Literal["markdown", "json", "toon"] = "json",
        filters: str | None = None,
        options: str | None = None,
        pipeline: str | None = None,
        dry_run: bool = False,
        stop_at: str = "",
    ) -> UnifiedSearchResult:
        """Run unified_search and return an SDK result object.

        `output_format` defaults to JSON for Python callers. Markdown remains
        available for callers that want the MCP-style human response.
        """
        service = self._get_unified_search_service()
        raw = await service.search(
            UnifiedSearchRunRequest(
                query=query,
                limit=limit,
                sources=sources,
                ranking=ranking,
                output_format=output_format,
                filters=filters,
                options=options,
                pipeline=pipeline,
                dry_run=dry_run,
                stop_at=stop_at,
            )
        )
        return UnifiedSearchResult(raw=raw, output_format=output_format)

    def _get_unified_search_service(self) -> UnifiedSearchService:
        if self._unified_search_service is None:
            from pubmed_search.presentation.mcp_server.tools.unified_runner import make_mcp_unified_search_runner

            self._unified_search_service = UnifiedSearchService(make_mcp_unified_search_runner(self.searcher))
        return self._unified_search_service


__all__ = ["PubMedSearchClient", "PubMedSearchConfig", "UnifiedSearchResult"]
