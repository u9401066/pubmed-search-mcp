"""Tests for the typed infrastructure source adapter and runtime factories."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.infrastructure.sources import (
    close_source_clients,
    search_alternate_source_adapter,
)
from pubmed_search.shared.async_utils import RetryableOperationError


def test_semantic_scholar_client_uses_env_api_key(monkeypatch):
    import pubmed_search.infrastructure.sources as sources_module
    from pubmed_search.infrastructure.sources.runtime import SourceRuntime, bind_source_runtime

    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "s2-key")

    with patch("pubmed_search.infrastructure.sources.semantic_scholar.SemanticScholarClient") as mock_client_cls:
        mock_client = object()
        mock_client_cls.return_value = mock_client

        with bind_source_runtime(SourceRuntime()):
            assert sources_module.get_semantic_scholar_client() is mock_client

    mock_client_cls.assert_called_once_with(api_key="s2-key")


async def test_close_source_clients_closes_and_resets_cached_clients():
    from pubmed_search.infrastructure.sources.runtime import SourceRuntime, bind_source_runtime

    first = MagicMock()
    first.close = AsyncMock()
    second = MagicMock()
    second.close = AsyncMock()
    runtime = SourceRuntime()
    runtime.set_owned_value(("openalex",), first)
    runtime.set_owned_value(("semantic_scholar",), second)
    with bind_source_runtime(runtime):
        await close_source_clients()

    first.close.assert_awaited_once()
    second.close.assert_awaited_once()
    assert runtime.cached_clients() == ()


# ============================================================
# Sole typed alternate-source adapter
# ============================================================


class TestAlternateSourceAdapter:
    @patch("pubmed_search.infrastructure.sources.get_semantic_scholar_client")
    async def test_preserves_page_counts_continuation_cost_and_provenance(self, mock_get):
        mock_client = MagicMock()
        mock_client.search_page = AsyncMock(
            return_value=SourceSearchPage(
                source="semantic_scholar",
                items=[{"title": "Paper"}],
                total=42,
                next_token=10,
                query="canonical query",
                cost=0.25,
                warnings=["provider warning"],
                mode="relevance",
                metadata={"offset": 0},
            )
        )
        mock_get.return_value = mock_client

        result = await search_alternate_source_adapter("logical query", "semantic_scholar")

        assert result.status == "ok"
        assert result.items == [{"title": "Paper"}]
        assert result.total_count == 42
        assert result.next_token == 10
        assert result.cost == 0.25
        assert result.metadata["warnings"] == ["provider warning"]
        assert result.provenance == {
            "logical_query": "logical query",
            "physical_query": "canonical query",
            "provider_mode": "relevance",
        }

    @patch("pubmed_search.infrastructure.sources.get_semantic_scholar_client")
    async def test_upstream_failure_is_typed_error_not_empty_success(self, mock_get):
        mock_client = MagicMock()
        mock_client.search_page = AsyncMock(
            side_effect=RetryableOperationError("HTTP 429 token=secret", status_code=429)
        )
        mock_get.return_value = mock_client

        result = await search_alternate_source_adapter("query", "semantic_scholar")

        assert result.status == "error"
        assert result.items == []
        assert result.errors[0].retryable is True
        assert result.errors[0].status_code == 429
        assert "secret" not in result.errors[0].message

    async def test_unknown_source_is_typed_error(self):
        result = await search_alternate_source_adapter("query", "unknown_db")  # type: ignore[arg-type]

        assert result.status == "error"
        assert result.items == []
        assert result.errors[0].source == "unknown_db"

    @patch("pubmed_search.infrastructure.sources.get_semantic_scholar_client")
    async def test_rejects_limit_instead_of_provider_clamping(self, mock_get):
        result = await search_alternate_source_adapter("query", "semantic_scholar", limit=101)

        assert result.status == "error"
        assert result.errors[0].message == "Source adapter failed"
        mock_get.assert_not_called()

    async def test_rejects_reversed_year_range(self):
        result = await search_alternate_source_adapter(
            "query",
            "openalex",
            min_year=2025,
            max_year=2020,
        )

        assert result.status == "error"
        assert result.errors[0].message == "Source adapter failed"

    @patch("pubmed_search.infrastructure.sources.get_europe_pmc_client")
    async def test_europe_pmc_preserves_total_and_cursor(self, mock_get):
        mock_client = MagicMock()
        mock_client.search = AsyncMock(
            return_value={
                "results": [{"title": "Europe PMC"}],
                "hit_count": 72,
                "next_cursor": "opaque-cursor",
            }
        )
        mock_get.return_value = mock_client

        result = await search_alternate_source_adapter(
            "cancer",
            "europe_pmc",
            min_year=2020,
            open_access_only=True,
            has_fulltext=True,
        )

        assert result.status == "ok"
        assert result.total_count == 72
        assert result.cursor == "opaque-cursor"
        assert result.provenance["physical_query"] == (
            "cancer AND FIRST_PDATE:[2020-01-01 TO *] AND OPEN_ACCESS:y AND HAS_FT:y"
        )
        mock_client.search.assert_awaited_once_with(
            query="cancer",
            limit=10,
            min_year=2020,
            max_year=None,
            open_access_only=True,
            has_fulltext=True,
        )

    @patch("pubmed_search.infrastructure.sources.get_core_client")
    async def test_core_preserves_total_and_continuation_offset(self, mock_get):
        mock_client = MagicMock()
        mock_client.compile_query.return_value = "compiled CORE query"
        mock_client.search = AsyncMock(
            return_value={
                "results": [{"title": "CORE"}],
                "total_hits": 12,
                "offset": 0,
            }
        )
        mock_get.return_value = mock_client

        result = await search_alternate_source_adapter("query", "core", limit=5)

        assert result.status == "ok"
        assert result.total_count == 12
        assert result.next_token == 5
        assert result.metadata["offset"] == 0
        assert result.provenance["physical_query"] == "compiled CORE query"

    @patch("pubmed_search.infrastructure.sources.get_scopus_client")
    async def test_scopus_uses_page_contract_without_losing_offset(self, mock_get):
        mock_client = MagicMock()
        mock_client.search_page = AsyncMock(
            return_value=SourceSearchPage(
                source="scopus",
                items=[{"title": "Scopus"}],
                total=45,
                next_token=10,
                query="TITLE-ABS-KEY(query)",
                mode="keyword",
                metadata={"offset": 5, "items_per_page": 5, "next_offset": 10},
            )
        )
        mock_get.return_value = mock_client

        with patch("pubmed_search.infrastructure.sources._is_alternate_source", return_value=True):
            result = await search_alternate_source_adapter("query", "scopus", limit=5)

        assert result.total_count == 45
        assert result.next_token == 10
        assert result.metadata["offset"] == 5
        assert result.provenance["physical_query"] == "TITLE-ABS-KEY(query)"
        mock_client.search_page.assert_awaited_once_with(
            query="query",
            limit=5,
            min_year=None,
            max_year=None,
            open_access_only=False,
        )

    @patch("pubmed_search.infrastructure.sources.get_web_of_science_client")
    async def test_web_of_science_uses_page_contract_without_losing_page_token(self, mock_get):
        mock_client = MagicMock()
        mock_client.search_page = AsyncMock(
            return_value=SourceSearchPage(
                source="web_of_science",
                items=[{"title": "WOS"}],
                total=12,
                next_token=3,
                query="TS=(query)",
                mode="keyword",
                metadata={"page": 2, "limit": 5, "next_page": 3, "next_offset": 10},
            )
        )
        mock_get.return_value = mock_client

        with patch("pubmed_search.infrastructure.sources._is_alternate_source", return_value=True):
            result = await search_alternate_source_adapter("query", "web_of_science", limit=5)

        assert result.total_count == 12
        assert result.next_token == 3
        assert result.metadata["next_offset"] == 10
        assert result.provenance["physical_query"] == "TS=(query)"
        mock_client.search_page.assert_awaited_once_with(
            query="query",
            limit=5,
            min_year=None,
            max_year=None,
            open_access_only=False,
        )

    @patch("pubmed_search.infrastructure.sources.get_europe_pmc_client")
    async def test_malformed_provider_rows_fail_closed(self, mock_get):
        mock_client = MagicMock()
        mock_client.search = AsyncMock(return_value={"results": ["not-a-mapping"], "hit_count": 1})
        mock_get.return_value = mock_client

        result = await search_alternate_source_adapter("query", "europe_pmc")

        assert result.status == "error"
        assert result.items == []

    async def test_retired_compatibility_surfaces_are_absent(self):
        import pubmed_search
        from pubmed_search.infrastructure import sources

        retired = {
            "SearchSource",
            "cross_search",
            "get_fulltext_parsed",
            "get_fulltext_xml",
            "get_last_alternate_source_error",
            "get_paper_from_any_source",
            "search_alternate_source",
            "search_alternate_source_page",
        }
        assert retired.isdisjoint(vars(sources))
        assert "SearchSource" not in pubmed_search.__all__


class TestLazyInit:
    async def test_configured_contact_email_is_source_client_fallback(self, monkeypatch):
        import pubmed_search.infrastructure.sources as mod
        from pubmed_search.infrastructure.sources.runtime import SourceRuntime, bind_source_runtime

        monkeypatch.delenv("NCBI_EMAIL", raising=False)
        monkeypatch.delenv("CROSSREF_EMAIL", raising=False)
        monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)

        with bind_source_runtime(SourceRuntime(contact_email="runtime@example.com")):
            assert mod.get_openalex_client()._email == "runtime@example.com"
            assert mod.get_crossref_client()._email == "runtime@example.com"
            assert mod.get_unpaywall_client()._email == "runtime@example.com"

    async def test_get_openalex_client_uses_settings_api_key(self, monkeypatch):
        import pubmed_search.infrastructure.sources as mod
        from pubmed_search.infrastructure.sources.runtime import SourceRuntime, bind_source_runtime

        monkeypatch.setenv("NCBI_EMAIL", "test@example.com")
        monkeypatch.setenv("OPENALEX_API_KEY", "oa-key")

        runtime = SourceRuntime()
        with bind_source_runtime(runtime):
            client = mod.get_openalex_client()

        assert client._email == "test@example.com"
        assert client._api_key == "oa-key"
        assert client._auth_params == {"mailto": "test@example.com"}
        assert client._client.headers["Authorization"] == "Bearer oa-key"

    async def test_get_fulltext_downloader(self):
        import pubmed_search.infrastructure.sources as mod
        from pubmed_search.infrastructure.sources.runtime import SourceRuntime, bind_source_runtime

        with bind_source_runtime(SourceRuntime()):
            downloader = mod.get_fulltext_downloader()
            assert downloader is not None
