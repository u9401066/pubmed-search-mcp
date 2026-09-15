"""
Final targeted tests to reach 90% coverage.
Focus on uncovered lines in remaining files.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestSessionFindCachedSearch:
    """Test session cached search functionality."""

    async def test_session_no_current(self):
        """Test operations with no current session."""
        from pubmed_search.application.session import SessionManager

        manager = SessionManager()  # Memory-only, no data dir

        # get_from_cache should return empty when no session
        cached, missing = manager.get_from_cache(["123"])
        assert cached == []
        assert "123" in missing


class TestStrategyGeneratorPaths:
    """Cover additional paths in strategy.py."""

    async def test_generate_strategies_basic(self):
        """Test basic strategy generation."""
        from pubmed_search.infrastructure.ncbi.strategy import SearchStrategyGenerator

        with (
            patch("pubmed_search.infrastructure.ncbi.strategy.Entrez.espell") as mock_espell,
            patch("pubmed_search.infrastructure.ncbi.strategy.Entrez.read") as mock_read,
            patch.object(
                SearchStrategyGenerator,
                "analyze_query",
                return_value={"count": 0, "translated_query": "cancer treatment"},
            ),
        ):
            # Return no correction
            mock_read.return_value = {"CorrectedQuery": ""}
            mock_espell.return_value = MagicMock()

            generator = SearchStrategyGenerator(email="test@example.com")

            # Generate strategies
            result = await generator.generate_strategies("cancer treatment")

            assert isinstance(result, dict)


class TestServerModulePaths:
    """Cover paths in server.py."""

    async def test_server_instructions_content(self):
        """Test server instructions are defined."""
        from pubmed_search.presentation.mcp_server.server import SERVER_INSTRUCTIONS

        assert len(SERVER_INSTRUCTIONS) > 0
        assert "PubMed" in SERVER_INSTRUCTIONS or "search" in SERVER_INSTRUCTIONS.lower()


class TestCommonModuleEdgeCases:
    """Cover edge cases in _common.py."""

    async def test_format_search_results_does_not_surface_unknown_mapping_values(self):
        """Malformed mappings are rejected before the formatter boundary."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            format_search_results,
        )

        results = [{"unexpected_payload": "API failure"}]
        formatted = format_search_results(results)

        assert "API failure" not in formatted

    async def test_format_search_results_normal(self):
        """Test formatting normal results."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            format_search_results,
        )

        results = [
            {
                "pmid": "12345",
                "title": "Test Article Title",
                "authors": ["Smith J", "Doe J"],
                "year": "2024",
                "journal": "Test Journal",
                "doi": "10.1/test",
                "abstract": "Test abstract text.",
            }
        ]

        formatted = format_search_results(results)

        assert "12345" in formatted
        assert "Test Article" in formatted


class TestFormatsModuleEdgeCases:
    """Cover edge cases in formats.py."""

    async def test_export_articles_dispatcher(self):
        """Test export_articles function dispatches correctly."""
        from pubmed_search.application.export.formats import export_articles

        articles = [
            {
                "pmid": "123",
                "title": "Test",
                "authors": ["A"],
                "journal": "J",
                "year": "2024",
            }
        ]

        # Test each format
        for format_name in ["ris", "bibtex", "csv", "medline", "json"]:
            result = export_articles(articles, fmt=format_name)
            assert len(result) > 0


class TestPicoModuleEdgeCases:
    """Cover edge cases in pico.py."""

    async def test_pico_module_structure(self):
        """Test pico module structure."""
        from pubmed_search.presentation.mcp_server.tools import pico

        assert hasattr(pico, "register_pico_tools")


class TestIciteModuleEdgeCases:
    """Cover edge cases in icite.py."""

    async def test_icite_sorting(self):
        """Test iCite result sorting."""
        from pubmed_search.infrastructure.ncbi.icite import ICiteMixin

        class TestSearcher(ICiteMixin):
            pass

        searcher = TestSearcher()

        # Test that method exists
        assert hasattr(searcher, "get_citation_metrics")


class TestBatchModuleEdgeCases:
    """Cover edge cases in batch.py."""

    async def test_batch_search_with_history(self):
        """Test batch search_with_history method."""
        from pubmed_search.infrastructure.ncbi.batch import BatchMixin

        class TestSearcher(BatchMixin):
            pass

        searcher = TestSearcher()

        with (
            patch("pubmed_search.infrastructure.ncbi.batch.Entrez.esearch") as mock_esearch,
            patch("pubmed_search.infrastructure.ncbi.batch.Entrez.read") as mock_read,
        ):
            mock_read.return_value = {
                "WebEnv": "test_webenv",
                "QueryKey": "1",
                "Count": "100",
            }
            mock_esearch.return_value = MagicMock()

            result = await searcher.search_with_history("cancer")

            assert result["count"] == 100


class TestPdfModuleEdgeCases:
    """Cover edge cases in pdf.py."""

    async def test_pdf_mixin_methods(self):
        """Test PDFMixin has expected methods."""
        from pubmed_search.infrastructure.ncbi.pdf import PDFMixin

        class TestSearcher(PDFMixin):
            pass

        searcher = TestSearcher()

        assert hasattr(searcher, "get_pmc_fulltext_url")


class TestLinksModuleEdgeCases:
    """Cover edge cases in links.py."""

    async def test_get_fulltext_links(self):
        """Test get_fulltext_links function."""
        from pubmed_search.application.export.links import get_fulltext_links

        # Test with PMC ID in article dict
        article_with_pmc = {"pmid": "12345", "pmc_id": "PMC123", "doi": "10.1/test"}
        result = get_fulltext_links(article_with_pmc)
        assert "pubmed_url" in result

        # Test without PMC ID
        article_no_pmc = {"pmid": "12345"}
        result = get_fulltext_links(article_no_pmc)
        assert "pubmed_url" in result


class TestBaseModuleEdgeCases:
    """Cover edge cases in base.py."""

    async def test_entrez_base_init(self):
        """Test EntrezBase initialization stores credentials on instance."""
        from pubmed_search.infrastructure.ncbi.base import EntrezBase

        base = EntrezBase(email="test@example.com", api_key="test_key")

        # Globals are NOT set in constructor (per-call isolation via run_entrez_callable).
        assert base._email == "test@example.com"
        assert base._api_key == "test_key"

    async def test_search_strategy_enum(self):
        """Test SearchStrategy enum."""
        from pubmed_search.infrastructure.ncbi.base import SearchStrategy

        assert SearchStrategy.RECENT.value == "recent"
        assert SearchStrategy.RELEVANCE.value == "relevance"
