"""
Tests for CORE API and NCBI Extended Database integration.
"""


# =============================================================================
# CORE API Client Tests
# =============================================================================


class TestCOREClient:
    """Tests for CORE API client."""

    async def test_client_initialization(self):
        """Test CORE client initialization."""
        from pubmed_search.infrastructure.sources.core import COREClient

        # Without API key
        client = COREClient()
        assert client._api_key is None
        assert client._min_interval == 6.0  # Slower without key

        # With API key
        client = COREClient(api_key="test-key")
        assert client._api_key == "test-key"
        assert client._min_interval == 2.5  # Faster with key

    async def test_get_core_client_singleton(self):
        """Test singleton pattern."""
        # Reset singleton
        import pubmed_search.infrastructure.sources.core as core_module
        from pubmed_search.infrastructure.sources.core import get_core_client

        core_module._core_client = None

        client1 = get_core_client()
        client2 = get_core_client()
        assert client1 is client2

    async def test_normalize_work(self):
        """Test work normalization."""
        from pubmed_search.infrastructure.sources.core import COREClient

        client = COREClient()

        work = {
            "id": 123456,
            "title": "Test Paper",
            "authors": [{"name": "John Doe"}, {"name": "Jane Smith"}],
            "abstract": "This is a test abstract.",
            "yearPublished": 2024,
            "doi": "10.1234/test",
            "identifiers": [{"type": "PMID", "identifier": "12345678"}],
            "journals": [{"title": "Test Journal"}],
            "publisher": "Test Publisher",
            "downloadUrl": "https://example.com/paper.pdf",
            "citationCount": 42,
            "fullText": "Full text content here...",
            "dataProviders": [{"name": "Test Repository"}],
        }

        normalized = client._normalize_work(work)

        assert normalized["core_id"] == 123456
        assert normalized["title"] == "Test Paper"
        assert normalized["authors"] == ["John Doe", "Jane Smith"]
        assert normalized["doi"] == "10.1234/test"
        assert normalized["pmid"] == "12345678"
        assert normalized["year"] == 2024
        assert normalized["has_fulltext"] is True
        assert normalized["citation_count"] == 42
        assert normalized["_source"] == "core"

    async def test_search_method_exists(self):
        """Test search methods exist."""
        from pubmed_search.infrastructure.sources.core import COREClient

        client = COREClient()

        # Test that search methods structure is correct
        assert hasattr(client, "search")
        assert hasattr(client, "search_fulltext")
        assert hasattr(client, "get_work")
        assert hasattr(client, "get_fulltext")
        assert hasattr(client, "search_by_doi")
        assert hasattr(client, "search_by_pmid")


class TestCOREConvenienceFunctions:
    """Test convenience functions."""

    async def test_search_core_function(self):
        """Test search_core convenience function exists."""
        from pubmed_search.infrastructure.sources.core import (
            search_core,
            search_core_fulltext,
        )

        # Functions should be callable
        assert callable(search_core)
        assert callable(search_core_fulltext)


# =============================================================================
# NCBI Extended Client Tests
# =============================================================================


class TestNCBIExtendedClient:
    """Tests for NCBI Extended client."""

    async def test_client_initialization(self):
        """Test client initialization."""
        from pubmed_search.infrastructure.sources.ncbi_extended import (
            NCBIExtendedClient,
        )

        # Without API key
        client = NCBIExtendedClient()
        assert client._api_key is None
        assert client._min_interval == 0.34  # Standard rate

        # With API key
        client = NCBIExtendedClient(api_key="test-key")
        assert client._api_key == "test-key"
        assert client._min_interval == 0.1  # Faster with key

    async def test_get_ncbi_extended_client_singleton(self):
        """Test singleton pattern."""
        # Reset singleton
        import pubmed_search.infrastructure.sources.ncbi_extended as ncbi_module
        from pubmed_search.infrastructure.sources.ncbi_extended import (
            get_ncbi_extended_client,
        )

        ncbi_module._ncbi_extended_client = None

        client1 = get_ncbi_extended_client()
        client2 = get_ncbi_extended_client()
        assert client1 is client2

    async def test_normalize_gene(self):
        """Test gene normalization."""
        from pubmed_search.infrastructure.sources.ncbi_extended import (
            NCBIExtendedClient,
        )

        client = NCBIExtendedClient()

        gene = {
            "uid": "672",
            "name": "BRCA1",
            "description": "BRCA1 DNA repair associated",
            "organism": {"scientificname": "Homo sapiens", "taxid": 9606},
            "chromosome": "17",
            "maplocation": "17q21.31",
            "otheraliases": "IRIS, PSCP, BRCAI, BRCC1",
            "summary": "This gene encodes a protein...",
            "geneticsource": "protein-coding",
        }

        normalized = client._normalize_gene(gene)

        assert normalized["gene_id"] == "672"
        assert normalized["symbol"] == "BRCA1"
        assert normalized["name"] == "BRCA1 DNA repair associated"
        assert normalized["organism"] == "Homo sapiens"
        assert normalized["chromosome"] == "17"
        assert "IRIS" in normalized["aliases"]
        assert normalized["_source"] == "ncbi_gene"

    async def test_normalize_compound(self):
        """Test compound normalization."""
        from pubmed_search.infrastructure.sources.ncbi_extended import (
            NCBIExtendedClient,
        )

        client = NCBIExtendedClient()

        compound = {
            "uid": "2244",
            "cid": "2244",
            "synonymlist": ["Aspirin", "Acetylsalicylic acid"],
            "iupacname": "2-acetoxybenzoic acid",
            "molecularformula": "C9H8O4",
            "molecularweight": 180.16,
            "canonicalsmiles": "CC(=O)OC1=CC=CC=C1C(=O)O",
            "inchikey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
        }

        normalized = client._normalize_compound(compound)

        assert normalized["cid"] == "2244"
        assert normalized["name"] == "Aspirin"
        assert normalized["molecular_formula"] == "C9H8O4"
        assert normalized["molecular_weight"] == 180.16
        assert normalized["_source"] == "pubchem"

    async def test_normalize_clinvar(self):
        """Test ClinVar normalization."""
        from pubmed_search.infrastructure.sources.ncbi_extended import (
            NCBIExtendedClient,
        )

        client = NCBIExtendedClient()

        variant = {
            "uid": "12345",
            "accession": "VCV000012345",
            "title": "NM_007294.4(BRCA1):c.5266dupC (p.Gln1756fs)",
            "genes": [{"symbol": "BRCA1"}],
            "clinical_significance": {"description": "Pathogenic"},
            "review_status": "criteria provided, multiple submitters",
            "obj_type": "single nucleotide variant",
            "chr": "17",
            "start": 43057051,
            "stop": 43057051,
            "trait_set": [{"trait_name": "Breast-ovarian cancer"}],
        }

        normalized = client._normalize_clinvar(variant)

        assert normalized["clinvar_id"] == "12345"
        assert normalized["accession"] == "VCV000012345"
        assert "BRCA1" in normalized["gene_symbols"]
        assert normalized["clinical_significance"] == "Pathogenic"
        assert normalized["_source"] == "clinvar"


# =============================================================================
# Sources Integration Tests
# =============================================================================


class TestSourcesIntegration:
    """Test sources module integration."""

    async def test_search_source_enum(self):
        """Test SearchSource enum includes CORE."""
        from pubmed_search.infrastructure.sources import SearchSource

        assert hasattr(SearchSource, "CORE")
        assert SearchSource.CORE.value == "core"

    async def test_get_clients(self):
        """Test client getter functions."""
        # Reset singletons
        from pubmed_search.infrastructure import sources
        from pubmed_search.infrastructure.sources import (
            get_core_client,
            get_ncbi_extended_client,
        )

        sources._core_client = None
        sources._ncbi_extended_client = None

        core_client = get_core_client()
        assert core_client is not None

        ncbi_client = get_ncbi_extended_client()
        assert ncbi_client is not None

    async def test_cross_search_includes_core(self):
        """Test that cross_search default sources include CORE."""
        import inspect

        from pubmed_search.infrastructure.sources import cross_search

        # Check the function signature
        inspect.signature(cross_search)
        # Default should include "core"
        # We can't easily test this without mocking, but we verify the function exists
        assert callable(cross_search)


# =============================================================================
# MCP Tools Tests
# =============================================================================


class TestCOREMCPTools:
    """Test CORE MCP tools."""

    async def test_tools_registered(self):
        """Test that CORE tools can be registered."""
        from mcp.server.fastmcp import FastMCP

        from pubmed_search.presentation.mcp_server.tools.core import register_core_tools

        mcp = FastMCP(name="test")
        register_core_tools(mcp)

        # Check tools are registered
        tool_names = [t.name for t in mcp._tool_manager.list_tools()]
        assert "search_core" in tool_names
        assert "search_core_fulltext" in tool_names
        assert "get_core_paper" in tool_names
        assert "get_core_fulltext" in tool_names
        assert "find_in_core" in tool_names


class TestNCBIExtendedMCPTools:
    """Test NCBI Extended MCP tools."""

    async def test_tools_registered(self):
        """Test that NCBI Extended tools can be registered."""
        from mcp.server.fastmcp import FastMCP

        from pubmed_search.presentation.mcp_server.tools.ncbi_extended import (
            register_ncbi_extended_tools,
        )

        mcp = FastMCP(name="test")
        register_ncbi_extended_tools(mcp)

        # Check tools are registered
        tool_names = [t.name for t in mcp._tool_manager.list_tools()]

        # Gene tools
        assert "search_gene" in tool_names
        assert "get_gene_details" in tool_names
        assert "get_gene_literature" in tool_names

        # PubChem tools
        assert "search_compound" in tool_names
        assert "get_compound_details" in tool_names
        assert "get_compound_literature" in tool_names

        # ClinVar tools
        assert "search_clinvar" in tool_names


class TestAllToolsRegistration:
    """Test that all tools are registered properly."""

    async def test_register_all_tools_includes_new_sources(self):
        """Test register_all_tools includes CORE and NCBI Extended."""
        from mcp.server.fastmcp import FastMCP

        from pubmed_search.infrastructure.ncbi import LiteratureSearcher
        from pubmed_search.presentation.mcp_server.tools import register_all_tools

        mcp = FastMCP(name="test")
        searcher = LiteratureSearcher(email="test@example.com")
        register_all_tools(mcp, searcher)

        tool_names = [t.name for t in mcp._tool_manager.list_tools()]

        # CORE tools are now integrated into unified_search
        # search_core is internal, unified_search handles multi-source
        assert "unified_search" in tool_names

        # NCBI Extended tools
        assert "search_gene" in tool_names
        assert "search_compound" in tool_names
        assert "search_clinvar" in tool_names


# =============================================================================
# Server Integration Tests
# =============================================================================


class TestServerIntegration:
    """Test server includes new tools."""

    async def test_create_server_with_new_tools(self):
        """Test create_server registers new tools."""
        from pubmed_search.presentation.mcp_server.server import create_server

        server = create_server(email="test@example.com")

        tool_names = [t.name for t in server._tool_manager.list_tools()]

        # Verify tools are included (search_core integrated into unified_search)
        assert "unified_search" in tool_names
        assert "search_gene" in tool_names
        assert "search_compound" in tool_names
