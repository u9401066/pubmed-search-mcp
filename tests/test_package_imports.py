"""
Package Import Tests - Verify all exports are working correctly.

This test module ensures:
1. All __all__ exports are importable
2. All classes/functions are callable/instantiable
3. No circular import issues
4. Version is correct

Run with: uv run pytest tests/test_package_imports.py -v
"""

import pytest


class TestPackageImports:
    """Test all package imports work correctly."""

    def test_version(self):
        """Version should be a valid semver string."""
        import pubmed_search
        
        version = pubmed_search.__version__
        assert version is not None
        parts = version.split(".")
        assert len(parts) >= 2
        assert all(p.isdigit() for p in parts[:2])

    def test_all_exports_importable(self):
        """All items in __all__ should be importable."""
        import pubmed_search
        
        for name in pubmed_search.__all__:
            obj = getattr(pubmed_search, name, None)
            assert obj is not None, f"Export '{name}' is None or missing"

    def test_core_entrez_imports(self):
        """Core Entrez classes should be importable."""
        from pubmed_search import (
            LiteratureSearcher,
            EntrezBase,
            SearchStrategy,
        )
        
        assert LiteratureSearcher is not None
        assert EntrezBase is not None
        assert SearchStrategy is not None

    def test_http_client_imports(self):
        """HTTP client classes should be importable."""
        from pubmed_search import PubMedClient, SearchResult
        
        assert PubMedClient is not None
        assert SearchResult is not None

    def test_ncbi_extended_imports(self):
        """NCBI Extended client should be importable."""
        from pubmed_search import NCBIExtendedClient
        
        assert NCBIExtendedClient is not None

    def test_europe_pmc_imports(self):
        """Europe PMC client should be importable."""
        from pubmed_search import EuropePMCClient
        
        assert EuropePMCClient is not None

    def test_multi_source_client_factories(self):
        """Multi-source client factories should be importable."""
        from pubmed_search import (
            get_semantic_scholar_client,
            get_openalex_client,
            get_europe_pmc_client,
            get_ncbi_extended_client,
            get_crossref_client,
            get_unpaywall_client,
        )
        
        assert callable(get_semantic_scholar_client)
        assert callable(get_openalex_client)
        assert callable(get_europe_pmc_client)
        assert callable(get_ncbi_extended_client)
        assert callable(get_crossref_client)
        assert callable(get_unpaywall_client)

    def test_search_source_enum(self):
        """SearchSource enum should be importable."""
        from pubmed_search import SearchSource
        
        assert hasattr(SearchSource, "PUBMED")
        assert hasattr(SearchSource, "SEMANTIC_SCHOLAR")
        assert hasattr(SearchSource, "OPENALEX")

    def test_export_functions(self):
        """Export functions should be importable."""
        from pubmed_search import (
            export_ris,
            export_bibtex,
            export_csv,
            export_medline,
            export_json,
            export_articles,
            SUPPORTED_FORMATS,
            get_fulltext_links,
        )
        
        assert callable(export_ris)
        assert callable(export_bibtex)
        assert callable(export_csv)
        assert callable(export_medline)
        assert callable(export_json)
        assert callable(export_articles)
        assert isinstance(SUPPORTED_FORMATS, (list, tuple, set, dict))
        assert callable(get_fulltext_links)

    def test_openurl_imports(self):
        """OpenURL functions should be importable."""
        from pubmed_search import (
            get_openurl_link,
            list_openurl_presets,
            configure_openurl,
            get_openurl_config,
        )
        
        assert callable(get_openurl_link)
        assert callable(list_openurl_presets)
        assert callable(configure_openurl)
        assert callable(get_openurl_config)

    def test_query_analysis_imports(self):
        """Query analysis classes should be importable."""
        from pubmed_search import (
            QueryAnalyzer,
            QueryComplexity,
            QueryIntent,
            AnalyzedQuery,
            ResultAggregator,
            RankingConfig,
        )
        
        assert QueryAnalyzer is not None
        assert QueryComplexity is not None
        assert QueryIntent is not None
        assert AnalyzedQuery is not None
        assert ResultAggregator is not None
        assert RankingConfig is not None

    def test_domain_entity_imports(self):
        """Domain entities should be importable."""
        from pubmed_search import UnifiedArticle
        
        assert UnifiedArticle is not None

    def test_mcp_server_imports(self):
        """MCP server functions should be importable."""
        from pubmed_search import create_mcp_server, mcp_main
        
        assert callable(create_mcp_server)
        assert callable(mcp_main)


class TestInfrastructureImports:
    """Test infrastructure layer imports."""

    def test_fulltext_downloader_import(self):
        """FulltextDownloader should be importable."""
        from pubmed_search.infrastructure.sources.fulltext_download import (
            FulltextDownloader,
            PDFSource,
            PDFLink,
        )
        
        assert FulltextDownloader is not None
        assert PDFSource is not None
        assert PDFLink is not None

    def test_fulltext_downloader_factory(self):
        """get_fulltext_downloader factory should work."""
        from pubmed_search.infrastructure.sources import get_fulltext_downloader
        
        downloader = get_fulltext_downloader()
        assert downloader is not None

    def test_core_client_import(self):
        """CORE client should be importable."""
        from pubmed_search.infrastructure.sources.core import COREClient
        
        assert COREClient is not None

    def test_semantic_scholar_import(self):
        """Semantic Scholar client should be importable."""
        from pubmed_search.infrastructure.sources.semantic_scholar import (
            SemanticScholarClient,
        )
        
        assert SemanticScholarClient is not None

    def test_openalex_import(self):
        """OpenAlex client should be importable."""
        from pubmed_search.infrastructure.sources.openalex import OpenAlexClient
        
        assert OpenAlexClient is not None


class TestDomainImports:
    """Test domain layer imports."""

    def test_unified_article_creation(self):
        """UnifiedArticle should be creatable."""
        from pubmed_search.domain.entities.article import UnifiedArticle
        
        article = UnifiedArticle(
            pmid="12345678",
            title="Test Article",
            primary_source="pubmed",
        )
        assert article.pmid == "12345678"
        assert article.title == "Test Article"
        assert article.primary_source == "pubmed"


class TestApplicationImports:
    """Test application layer imports."""

    def test_session_manager_import(self):
        """SessionManager should be importable."""
        from pubmed_search.application.session import SessionManager
        
        assert SessionManager is not None

    def test_export_formats_import(self):
        """Export format functions should be importable."""
        # Use top-level exports instead of internal functions
        from pubmed_search import (
            export_ris,
            export_bibtex,
        )
        
        assert callable(export_ris)
        assert callable(export_bibtex)


class TestNoCircularImports:
    """Ensure no circular import issues."""

    def test_import_order_1(self):
        """Import infrastructure before presentation."""
        from pubmed_search.infrastructure.ncbi import LiteratureSearcher
        from pubmed_search.presentation.mcp_server import create_server
        
        assert LiteratureSearcher is not None
        assert create_server is not None

    def test_import_order_2(self):
        """Import domain before application."""
        from pubmed_search.domain.entities.article import UnifiedArticle
        from pubmed_search.application.search import QueryAnalyzer
        
        assert UnifiedArticle is not None
        assert QueryAnalyzer is not None

    def test_import_order_3(self):
        """Import shared before everything."""
        from pubmed_search.shared.exceptions import PubMedSearchError
        from pubmed_search import LiteratureSearcher
        
        assert PubMedSearchError is not None
        assert LiteratureSearcher is not None


class TestMCPToolsAccessible:
    """Test that MCP tools are registered and accessible."""

    def test_create_server_returns_valid_server(self):
        """create_mcp_server should return a valid FastMCP server."""
        from pubmed_search import create_mcp_server
        
        # Use correct API: email, api_key (not ncbi_api_key)
        server = create_mcp_server(
            email="test@example.com",
            api_key="test_key",
        )
        assert server is not None
        assert hasattr(server, "_tool_manager")

    def test_server_has_expected_tools(self):
        """Server should have expected number of tools."""
        from pubmed_search import create_mcp_server
        
        server = create_mcp_server(
            email="test@example.com",
            api_key="test_key",
        )
        tools = server._tool_manager.list_tools()
        
        # Should have 34 tools (consolidated in v0.3.1)
        assert len(tools) >= 30, f"Expected at least 30 tools, got {len(tools)}"

    def test_key_tools_registered(self):
        """Key tools should be registered."""
        from pubmed_search import create_mcp_server
        
        server = create_mcp_server(
            email="test@example.com",
            api_key="test_key",
        )
        tools = server._tool_manager.list_tools()
        tool_names = [t.name for t in tools]
        
        expected_tools = [
            "unified_search",
            "get_fulltext",
            "fetch_article_details",
            "find_related_articles",
            "find_citing_articles",
            "prepare_export",
            "search_gene",
            "search_compound",
            "build_citation_tree",
        ]
        
        for expected in expected_tools:
            assert expected in tool_names, f"Tool '{expected}' not found in registered tools"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
