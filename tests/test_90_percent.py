"""Final push to reach 90% coverage."""

from __future__ import annotations

import tempfile
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest


class TestClientMissingLines:
    """Target client.py lines 153-165, 185, 207-210, etc."""

    async def test_fetch_details_empty_pmids(self):
        """Test fetch_details with empty list."""
        from pubmed_search import LiteratureSearcher

        with patch("pubmed_search.infrastructure.ncbi.base.Entrez") as mock_entrez:
            mock_entrez.email = None
            searcher = LiteratureSearcher(email="test@example.com")

            # Empty list should return empty
            result = await searcher.fetch_details([])
            assert result == []


class TestSessionToolsMissingLines:
    """Target session_tools.py - mostly pass functions."""

    async def test_register_session_resources(self):
        """Test session resources registration."""
        from pubmed_search.application.session import SessionManager
        from pubmed_search.presentation.mcp_server.session_tools import (
            register_session_resources,
        )

        mock_mcp = Mock()
        mock_mcp.resource = Mock(return_value=lambda f: f)

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(data_dir=tmpdir)

            register_session_resources(mock_mcp, manager)

            # Should have registered resource
            assert mock_mcp.resource.called


class TestCommonMissingLines:
    """Target _common.py lines 56-60, 72-73, 87-88, 106-108."""

    async def test_format_results_empty(self):
        """Test formatting empty results."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            format_search_results,
        )

        result = format_search_results([])
        assert "No results" in result or result == ""


class TestDiscoveryMissingLines:
    """Target discovery.py lines 135-138, etc."""

    async def test_find_related_no_results(self):
        """Test find_related with no results."""
        from pubmed_search.infrastructure.ncbi.base import EntrezBase
        from pubmed_search.infrastructure.ncbi.citation import CitationMixin

        class TestSearcher(CitationMixin, EntrezBase):
            async def fetch_details(self, pmids):
                return []

        searcher = TestSearcher()

        with (
            patch("pubmed_search.infrastructure.ncbi.citation.Entrez.elink") as mock_elink,
            patch("pubmed_search.infrastructure.ncbi.citation.Entrez.read") as mock_read,
        ):
            mock_read.return_value = [{"LinkSetDb": []}]
            mock_elink.return_value = MagicMock()

            results = await searcher.get_related_articles("12345")

            assert results == []


class TestSearchMissingLines:
    """Target search.py lines 49, 224-225, etc."""

    async def test_search_with_article_type_filter(self):
        """Test search with article type filter."""
        from pubmed_search.infrastructure.ncbi.search import SearchMixin

        class TestSearcher(SearchMixin):
            async def fetch_details(self, pmids):
                return [{"pmid": p} for p in pmids]

        searcher = TestSearcher()

        with (
            patch("pubmed_search.infrastructure.ncbi.search.Entrez.esearch") as mock_esearch,
            patch("pubmed_search.infrastructure.ncbi.search.Entrez.read") as mock_read,
        ):
            mock_read.return_value = {"IdList": ["123"], "Count": "1"}
            mock_esearch.return_value = MagicMock()

            page = await searcher.search_page("diabetes", article_type="Review", limit=5)

            assert page.items == [{"pmid": "123"}]
            assert page.total == 1

    async def test_search_impact_strategy(self):
        """Test search with impact strategy."""
        from pubmed_search.infrastructure.ncbi.search import SearchMixin

        class TestSearcher(SearchMixin):
            async def fetch_details(self, pmids):
                return [{"pmid": p} for p in pmids]

            async def get_citation_metrics(self, pmids):
                return {p: {"citation_count": 10} for p in pmids}

        searcher = TestSearcher()

        with (
            patch("pubmed_search.infrastructure.ncbi.search.Entrez.esearch") as mock_esearch,
            patch("pubmed_search.infrastructure.ncbi.search.Entrez.read") as mock_read,
        ):
            mock_read.return_value = {"IdList": ["123", "456"], "Count": "2"}
            mock_esearch.return_value = MagicMock()

            page = await searcher.search_page("test", strategy="impact", limit=5)

            assert [item["pmid"] for item in page.items] == ["123", "456"]
            assert page.total == 2


class TestFormatsMissingLines:
    """Target formats.py remaining lines."""

    async def test_export_medline(self):
        """Test MEDLINE format export."""
        from pubmed_search.application.export.formats import export_medline

        articles = [
            {
                "pmid": "123",
                "title": "Test Title",
                "authors": ["Smith J", "Jones M"],
                "journal": "Test Journal",
                "year": "2024",
                "abstract": "Test abstract",
            }
        ]

        result = export_medline(articles)

        assert "PMID" in result or "Test" in result

    async def test_export_csv_many_columns(self):
        """Test CSV export with all columns."""
        from pubmed_search.application.export.formats import export_csv

        articles = [
            {
                "pmid": "123",
                "title": "Test",
                "authors": ["A"],
                "journal": "J",
                "year": "2024",
                "doi": "10.1000/test",
                "pmc_id": "PMC123",
                "keywords": ["k1", "k2"],
                "mesh_terms": ["m1"],
            }
        ]

        result = export_csv(articles)

        assert "123" in result
        assert "," in result  # CSV format


class TestSessionMissingLines:
    """Target session.py remaining uncovered lines."""

    async def test_session_manager_reading_list(self):
        """Test manager add_to_reading_list."""
        from pubmed_search.application.session import SessionManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(data_dir=tmpdir)
            manager.create_session("Test")

            manager.add_to_reading_list("12345", priority=5, notes="Important")

            # Check it was added to current session
            session = manager.get_current_session()
            assert "12345" in session.reading_list

    async def test_session_manager_get_summary(self):
        """Test manager get_session_summary."""
        from pubmed_search.application.session import SessionManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(data_dir=tmpdir)
            manager.create_session("Test Summary Session")

            summary = manager.get_session_summary()

            # Returns dict or string
            assert isinstance(summary, (str, dict))


class TestICiteMissingLines:
    """Target icite.py remaining lines."""

    async def test_icite_error_handling(self):
        """Test that iCite outages raise an explicit retryable error."""
        from pubmed_search.infrastructure.ncbi.icite import ICiteMixin
        from pubmed_search.shared.exceptions import ServiceUnavailableError

        class TestSearcher(ICiteMixin):
            pass

        searcher = TestSearcher()
        searcher._get_icite_cache().clear()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Network error"))
        with patch(
            "pubmed_search.infrastructure.ncbi.icite.get_shared_async_client",
            return_value=mock_client,
        ):
            with pytest.raises(ServiceUnavailableError):
                await searcher.get_citation_metrics(["123"])


class TestCitationMissingLines:
    """Target citation.py lines 77-79, 107-109."""

    async def test_citation_no_linksetdb(self):
        """Test citation when LinkSetDb is empty."""
        from pubmed_search.infrastructure.ncbi.base import EntrezBase
        from pubmed_search.infrastructure.ncbi.citation import CitationMixin

        class TestSearcher(CitationMixin, EntrezBase):
            async def fetch_details(self, pmids):
                return []

        searcher = TestSearcher()

        with (
            patch("pubmed_search.infrastructure.ncbi.citation.Entrez.elink") as mock_elink,
            patch("pubmed_search.infrastructure.ncbi.citation.Entrez.read") as mock_read,
        ):
            # No LinkSetDb at all
            mock_read.return_value = [{}]
            mock_elink.return_value = MagicMock()

            results = await searcher.get_citing_articles("12345")

            assert results == []
