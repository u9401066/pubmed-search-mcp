"""
Tests for CORE API and NCBI Extended Database integration.
"""

from __future__ import annotations

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
        import pubmed_search.infrastructure.sources as ncbi_module
        from pubmed_search.infrastructure.sources import get_ncbi_extended_client

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

    async def test_core_is_declared_by_the_source_registry(self):
        """The registry, not a parallel enum, owns source identity."""
        from pubmed_search.infrastructure.sources import get_source_registry

        definition = get_source_registry().get("core")
        assert definition is not None
        assert definition.key == "core"
        assert definition.supports_primary_search is True


# =============================================================================
# MCP Tools Tests
# =============================================================================


# =============================================================================
# Server Integration Tests
# =============================================================================


async def test_core_available_fulltext_survives_nullable_optional_metadata():
    from pubmed_search.infrastructure.sources.core import COREClient

    client = COREClient()
    try:
        result = client._normalize_work(
            {
                "id": 123,
                "title": "Paper",
                "fullText": "Complete body",
                "authors": None,
                "identifiers": None,
                "links": None,
                "dataProviders": None,
            }
        )
        assert result["fulltext_available"] is True
        assert result["authors"] == []
        assert result["full_text"] == "Complete body"
    finally:
        await client.close()
