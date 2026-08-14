"""Deterministic stdio MCP fixture with one successful and one failed source."""

from __future__ import annotations

import os

from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.presentation.mcp_server import create_server
from pubmed_search.presentation.mcp_server.tools import unified as unified_module
from pubmed_search.shared.source_contracts import SourceAdapterError, SourceAdapterResult


async def _offline_pubmed(*args: object, **kwargs: object) -> SourceAdapterResult[UnifiedArticle]:
    del args, kwargs
    article = UnifiedArticle(
        title="Deterministic Offline Evidence",
        primary_source="pubmed",
        pmid="42424242",
        doi="10.1000/offline-smoke",
        year=2026,
    )
    return SourceAdapterResult(
        source="pubmed",
        operation="search",
        items=[article],
        total_count=1,
        metadata={
            "total_available": 1,
            "physical_query": "offline smoke",
            "query_executed": True,
        },
    )


async def _offline_semantic_scholar(*args: object, **kwargs: object) -> SourceAdapterResult[UnifiedArticle]:
    del args, kwargs
    return SourceAdapterResult.failure(
        source="semantic_scholar",
        operation="search",
        error=SourceAdapterError(
            source="semantic_scholar",
            operation="search",
            message="deterministic offline rate limit",
            kind="http",
            retryable=True,
            status_code=429,
        ),
        metadata={"physical_query": "offline smoke", "query_executed": True},
    )


def main() -> None:
    unified_module._search_pubmed_adapter = _offline_pubmed  # type: ignore[attr-defined]
    unified_module._search_semantic_scholar_adapter = _offline_semantic_scholar  # type: ignore[attr-defined]
    server = create_server(
        email="offline-smoke@example.com",
        data_dir=os.environ["PUBMED_DATA_DIR"],
        mode="local",
    )
    server.run()


if __name__ == "__main__":
    main()
