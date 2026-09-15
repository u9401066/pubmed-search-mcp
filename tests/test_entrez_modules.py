"""
Tests for Entrez modules - citation, icite, batch, pdf.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.infrastructure.ncbi.base import EntrezBase, NCBIInfrastructureError


class TestCitationMixin:
    """Tests for CitationMixin methods."""

    @pytest.fixture
    def mock_entrez_read(self):
        """Mock Entrez.read response."""
        return [
            {
                "LinkSetDb": [
                    {
                        "LinkName": "pubmed_pubmed",
                        "Link": [{"Id": "12345"}, {"Id": "67890"}],
                    }
                ]
            }
        ]

    async def test_get_related_articles_success(self, mock_entrez_read):
        """Test getting related articles successfully."""
        from pubmed_search.infrastructure.ncbi.citation import CitationMixin

        class TestSearcher(CitationMixin, EntrezBase):
            async def fetch_details(self, pmids):
                return [{"pmid": pmid, "title": f"Article {pmid}"} for pmid in pmids]

        searcher = TestSearcher()

        with (
            patch("pubmed_search.infrastructure.ncbi.citation.Entrez.elink") as mock_elink,
            patch("pubmed_search.infrastructure.ncbi.citation.Entrez.read") as mock_read,
        ):
            mock_read.return_value = mock_entrez_read
            mock_elink.return_value = MagicMock()

            results = await searcher.get_related_articles("999", limit=5)

            assert len(results) == 2
            assert results[0]["pmid"] == "12345"

    async def test_get_related_articles_empty(self):
        """Test getting related articles when none exist."""
        from pubmed_search.infrastructure.ncbi.citation import CitationMixin

        class TestSearcher(CitationMixin, EntrezBase):
            async def fetch_details(self, pmids):
                return []

        searcher = TestSearcher()

        with (
            patch("pubmed_search.infrastructure.ncbi.citation.Entrez.elink") as mock_elink,
            patch("pubmed_search.infrastructure.ncbi.citation.Entrez.read") as mock_read,
        ):
            mock_read.return_value = [{}]  # No LinkSetDb
            mock_elink.return_value = MagicMock()

            results = await searcher.get_related_articles("999", limit=5)
            assert results == []

    async def test_get_related_articles_error(self):
        """Test getting related articles with error."""
        from pubmed_search.infrastructure.ncbi.citation import CitationMixin

        class TestSearcher(CitationMixin, EntrezBase):
            async def fetch_details(self, pmids):
                return []

        searcher = TestSearcher()

        with patch("pubmed_search.infrastructure.ncbi.citation.Entrez.elink") as mock_elink:
            upstream = Exception("API Error with token=private")
            mock_elink.side_effect = upstream

            with pytest.raises(NCBIInfrastructureError) as exc_info:
                await searcher.get_related_articles("999")

        assert str(exc_info.value) == "NCBI related_articles failed"
        assert exc_info.value.upstream_type == "Exception"
        assert exc_info.value.__cause__ is upstream
        assert "private" not in str(exc_info.value)

    async def test_get_citing_articles_success(self):
        """Test getting citing articles successfully."""
        from pubmed_search.infrastructure.ncbi.citation import CitationMixin

        class TestSearcher(CitationMixin, EntrezBase):
            async def fetch_details(self, pmids):
                return [{"pmid": pmid, "title": f"Article {pmid}"} for pmid in pmids]

        searcher = TestSearcher()

        with (
            patch("pubmed_search.infrastructure.ncbi.citation.Entrez.elink") as mock_elink,
            patch("pubmed_search.infrastructure.ncbi.citation.Entrez.read") as mock_read,
        ):
            mock_read.return_value = [
                {
                    "LinkSetDb": [
                        {
                            "LinkName": "pubmed_pubmed_citedin",
                            "Link": [{"Id": "111"}, {"Id": "222"}],
                        }
                    ]
                }
            ]
            mock_elink.return_value = MagicMock()

            results = await searcher.get_citing_articles("999", limit=10)

            assert len(results) == 2

    async def test_get_article_references_success(self):
        """Test getting article references successfully."""
        from pubmed_search.infrastructure.ncbi.citation import CitationMixin

        class TestSearcher(CitationMixin, EntrezBase):
            async def fetch_details(self, pmids):
                return [{"pmid": pmid, "title": f"Ref {pmid}"} for pmid in pmids]

        searcher = TestSearcher()

        with (
            patch("pubmed_search.infrastructure.ncbi.citation.Entrez.elink") as mock_elink,
            patch("pubmed_search.infrastructure.ncbi.citation.Entrez.read") as mock_read,
        ):
            mock_read.return_value = [
                {
                    "LinkSetDb": [
                        {
                            "LinkName": "pubmed_pubmed_refs",
                            "Link": [{"Id": "111"}, {"Id": "222"}],
                        }
                    ]
                }
            ]
            mock_elink.return_value = MagicMock()

            results = await searcher.get_article_references("999", limit=20)

            assert len(results) == 2


class TestICiteMixin:
    """Tests for ICiteMixin methods."""

    @pytest.fixture
    def mock_icite_response(self):
        """Mock iCite API response."""
        return {
            "data": [
                {
                    "pmid": 12345678,
                    "year": 2024,
                    "title": "Test Article",
                    "journal": "Test Journal",
                    "citation_count": 50,
                    "relative_citation_ratio": 2.5,
                    "nih_percentile": 85.0,
                    "citations_per_year": 10.0,
                    "apt": 0.8,
                }
            ]
        }

    async def test_get_citation_metrics_success(self, mock_icite_response):
        """Test getting citation metrics successfully."""
        from pubmed_search.infrastructure.ncbi.icite import ICiteMixin

        class TestSearcher(ICiteMixin):
            pass

        searcher = TestSearcher()
        searcher._get_icite_cache().clear()

        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_icite_response
        mock_response.raise_for_status = MagicMock()
        mock_http.get = AsyncMock(return_value=mock_response)

        with patch("pubmed_search.infrastructure.ncbi.icite.get_shared_async_client", return_value=mock_http):
            results = await searcher.get_citation_metrics(["12345678"])

            assert "12345678" in results
            assert results["12345678"]["citation_count"] == 50
            assert results["12345678"]["relative_citation_ratio"] == 2.5

    async def test_get_citation_metrics_empty(self):
        """Test getting citation metrics with no PMIDs."""
        from pubmed_search.infrastructure.ncbi.icite import ICiteMixin

        class TestSearcher(ICiteMixin):
            pass

        searcher = TestSearcher()
        results = await searcher.get_citation_metrics([])

        assert results == {}

    async def test_get_citation_metrics_batch(self, mock_icite_response):
        """Test getting citation metrics in batches."""
        from pubmed_search.infrastructure.ncbi.icite import (
            MAX_PMIDS_PER_REQUEST,
            ICiteMixin,
        )

        class TestSearcher(ICiteMixin):
            pass

        searcher = TestSearcher()

        # Create more PMIDs than the batch limit
        pmids = [str(i) for i in range(MAX_PMIDS_PER_REQUEST + 50)]
        searcher._get_icite_cache().clear()

        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = MagicMock()
        mock_http.get = AsyncMock(return_value=mock_response)

        with patch(
            "pubmed_search.infrastructure.ncbi.icite.get_shared_async_client",
            return_value=mock_http,
        ) as mock_get_client:
            await searcher.get_citation_metrics(pmids)

            # Shared client getter is reused for each batch without allocating new clients.
            assert mock_get_client.call_count == 2
            assert mock_http.get.await_count == 2

    async def test_get_citation_metrics_api_error(self):
        """Transport failures are distinct from a legitimate empty iCite result."""
        from pubmed_search.infrastructure.ncbi.icite import ICiteMixin
        from pubmed_search.shared.exceptions import ServiceUnavailableError

        class TestSearcher(ICiteMixin):
            pass

        searcher = TestSearcher()
        searcher._get_icite_cache().clear()

        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_http.get = AsyncMock(side_effect=Exception("API Error"))

        with patch("pubmed_search.infrastructure.ncbi.icite.get_shared_async_client", return_value=mock_http):
            with pytest.raises(ServiceUnavailableError, match="NIH iCite: request failed") as exc_info:
                await searcher.get_citation_metrics(["12345"])

        assert exc_info.value.retryable is True

    async def test_get_citation_metrics_rejects_invalid_response(self):
        """Malformed upstream JSON cannot masquerade as an unindexed PMID."""
        from pubmed_search.infrastructure.ncbi.icite import ICiteMixin
        from pubmed_search.shared.exceptions import ServiceUnavailableError

        class TestSearcher(ICiteMixin):
            pass

        searcher = TestSearcher()
        searcher._get_icite_cache().clear()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"unexpected": []}
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)

        with patch("pubmed_search.infrastructure.ncbi.icite.get_shared_async_client", return_value=mock_http):
            with pytest.raises(ServiceUnavailableError, match="returned an invalid response"):
                await searcher.get_citation_metrics(["12345"])

    async def test_get_citation_metrics_forces_pmid_mapping_field(self):
        """Custom field selections still request PMID for deterministic mapping."""
        from pubmed_search.infrastructure.ncbi.icite import ICiteMixin

        class TestSearcher(ICiteMixin):
            pass

        searcher = TestSearcher()
        searcher._get_icite_cache().clear()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"data": [{"pmid": 12345, "citation_count": 2}]}
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)

        with patch("pubmed_search.infrastructure.ncbi.icite.get_shared_async_client", return_value=mock_http):
            result = await searcher.get_citation_metrics(["12345"], fields=["citation_count"])

        assert result["12345"]["citation_count"] == 2
        assert mock_http.get.await_args.kwargs["params"]["fl"] == "pmid,citation_count"

    async def test_get_related_articles_closes_handle_when_entrez_read_fails(self):
        """Citation mixin should close handles even when Entrez parsing fails."""
        from pubmed_search.infrastructure.ncbi.citation import CitationMixin

        class TestSearcher(CitationMixin, EntrezBase):
            async def fetch_details(self, pmids):
                return []

        searcher = TestSearcher()
        handle = MagicMock()

        with patch.object(searcher, "_rate_limited_call", AsyncMock(return_value=handle)):
            with patch("pubmed_search.infrastructure.ncbi.citation.Entrez.read", side_effect=ValueError("bad xml")):
                with pytest.raises(NCBIInfrastructureError, match="NCBI related_articles failed"):
                    await searcher.get_related_articles("999")

        handle.close.assert_called_once()


class TestBatchMixin:
    """Tests for BatchMixin methods."""

    async def test_search_with_history_success(self):
        """Test search with history server."""
        from pubmed_search.infrastructure.ncbi.batch import BatchMixin

        class TestSearcher(BatchMixin):
            pass

        searcher = TestSearcher()

        with (
            patch("pubmed_search.infrastructure.ncbi.batch.Entrez.esearch") as mock_search,
            patch("pubmed_search.infrastructure.ncbi.batch.Entrez.read") as mock_read,
        ):
            mock_read.return_value = {
                "WebEnv": "WEB_ENV_123",
                "QueryKey": "1",
                "Count": "500",
            }
            mock_search.return_value = MagicMock()

            result = await searcher.search_with_history("cancer therapy")

            assert result["webenv"] == "WEB_ENV_123"
            assert result["query_key"] == "1"
            assert result["count"] == 500

    async def test_search_with_history_error(self):
        """Test search with history server error."""
        from pubmed_search.infrastructure.ncbi.batch import BatchMixin

        class TestSearcher(BatchMixin):
            pass

        searcher = TestSearcher()

        with patch("pubmed_search.infrastructure.ncbi.batch.Entrez.esearch") as mock_search:
            mock_search.side_effect = Exception("API Error")

            with pytest.raises(NCBIInfrastructureError, match="NCBI history_search failed"):
                await searcher.search_with_history("test")

    async def test_fetch_batch_from_history_success(self):
        """Test fetching batch from history."""
        from pubmed_search.infrastructure.ncbi.batch import BatchMixin

        class TestSearcher(BatchMixin):
            pass

        searcher = TestSearcher()

        with (
            patch("pubmed_search.infrastructure.ncbi.batch.Entrez.efetch") as mock_fetch,
            patch("pubmed_search.infrastructure.ncbi.batch.Entrez.read") as mock_read,
        ):
            mock_read.return_value = {
                "PubmedArticle": [
                    {
                        "MedlineCitation": {
                            "PMID": "12345",
                            "Article": {
                                "ArticleTitle": "Test Article",
                                "AuthorList": [{"LastName": "Smith", "ForeName": "John"}],
                                "Journal": {
                                    "Title": "Test Journal",
                                    "JournalIssue": {"PubDate": {"Year": "2024"}},
                                },
                            },
                        }
                    }
                ]
            }
            mock_fetch.return_value = MagicMock()

            results = await searcher.fetch_batch_from_history("WEB_ENV", "1", 0, 10)

            assert len(results) == 1
            assert results[0]["pmid"] == "12345"
            assert results[0]["title"] == "Test Article"


class TestSearchMixin:
    """Tests for SearchMixin routing between summary/direct/history paths."""

    async def test_search_summary_uses_quick_fetch_summary(self):
        """Summary mode should use ESummary-style lightweight fetching."""
        from pubmed_search.infrastructure.ncbi.search import SearchMixin
        from pubmed_search.infrastructure.ncbi.utils import UtilsMixin

        class TestSearcher(SearchMixin, UtilsMixin, EntrezBase):
            pass

        searcher = TestSearcher()
        searcher.quick_fetch_summary = AsyncMock(return_value=[{"pmid": "12345", "title": "Summary Result"}])
        searcher.fetch_details = AsyncMock(return_value=[{"pmid": "12345", "title": "Full Result"}])

        with patch.object(searcher, "_search_ids", AsyncMock(return_value=(["12345", "67890"], 2, "", ""))):
            page = await searcher.search_page("test query", limit=1, detail_level="summary")

        searcher.quick_fetch_summary.assert_awaited_once_with(["12345"])
        searcher.fetch_details.assert_not_called()
        assert page.items[0]["pmid"] == "12345"
        assert page.total == 2
        assert page.metadata["detail_level"] == "summary"

    async def test_search_full_auto_uses_history_server_for_large_result_sets(self):
        """Full-detail searches should switch to History Server when the batch is large enough."""
        from pubmed_search.infrastructure.ncbi.search import SearchMixin
        from pubmed_search.infrastructure.ncbi.utils import UtilsMixin

        class TestSearcher(SearchMixin, UtilsMixin, EntrezBase):
            pass

        searcher = TestSearcher()
        searcher.fetch_details = AsyncMock(return_value=[{"pmid": "12345", "title": "Direct Result"}])
        searcher._fetch_articles = AsyncMock(return_value={"PubmedArticle": []})
        searcher._parse_fetch_results = MagicMock(return_value=[{"pmid": "12345", "title": "History Result"}])

        with (
            patch.object(
                searcher,
                "_search_ids",
                AsyncMock(return_value=(["12345", "67890", "13579"], 3, "WEBENV123", "1")),
            ),
            patch("pubmed_search.infrastructure.ncbi.search._HISTORY_BATCH_THRESHOLD", 2),
        ):
            page = await searcher.search_page("test query", limit=2, detail_level="full")

        searcher._fetch_articles.assert_awaited_once_with(
            ["12345", "67890", "13579"], webenv="WEBENV123", query_key="1"
        )
        searcher._parse_fetch_results.assert_called_once_with(
            {"PubmedArticle": []},
            expected_pmids=["12345", "67890", "13579"],
        )
        searcher.fetch_details.assert_not_called()
        assert page.items[0]["title"] == "History Result"
        assert page.total == 3
        assert page.metadata["detail_level"] == "full"

    async def test_fetch_batch_from_history_error(self):
        """Test fetching batch with error."""
        from pubmed_search.infrastructure.ncbi.batch import BatchMixin

        class TestSearcher(BatchMixin):
            pass

        searcher = TestSearcher()

        with patch("pubmed_search.infrastructure.ncbi.batch.Entrez.efetch") as mock_fetch:
            mock_fetch.side_effect = Exception("API Error")

            with pytest.raises(NCBIInfrastructureError, match="NCBI history_fetch failed"):
                await searcher.fetch_batch_from_history("WEB_ENV", "1", 0, 10)


async def test_icite_cache_respects_fields_and_isolates_returned_records():
    from pubmed_search.infrastructure.ncbi.icite import ICiteMixin

    searcher = ICiteMixin()
    fetch = AsyncMock(
        side_effect=[
            {"123": {"pmid": 123, "citation_count": 2}},
            {"123": {"pmid": 123, "relative_citation_ratio": 1.5}},
        ]
    )
    with patch.object(searcher, "_fetch_icite_batch", fetch):
        first = await searcher.get_citation_metrics(["123"], fields=["citation_count"])
        first["123"]["citation_count"] = 999
        second = await searcher.get_citation_metrics(["123"], fields=["relative_citation_ratio"])
        third = await searcher.get_citation_metrics(["123"], fields=["citation_count"])
    assert second["123"]["relative_citation_ratio"] == 1.5
    assert third["123"]["citation_count"] == 2
    assert fetch.await_count == 2


async def test_search_keeps_boolean_topic_grouped_when_adding_filters():
    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

    searcher = LiteratureSearcher()
    with patch.object(searcher, "_search_ids", AsyncMock(return_value=([], 0, "", ""))) as fetch:
        page = await searcher.search_page("asthma OR diabetes", language="english")
    assert page.query == "(asthma OR diabetes) AND eng[la]"
    assert fetch.await_args.args[0] == page.query
