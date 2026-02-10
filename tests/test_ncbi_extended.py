"""Tests for NCBIExtendedClient (Gene, PubChem, ClinVar)."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.infrastructure.sources.ncbi_extended import (
    NCBIExtendedClient,
    get_ncbi_extended_client,
    DEFAULT_EMAIL,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def client():
    return NCBIExtendedClient(email="test@example.com", api_key="test_key")


@pytest.fixture
def client_no_key():
    return NCBIExtendedClient(email="test@example.com")


# ============================================================
# Init & Config
# ============================================================


class TestInit:
    async def test_default_email(self):
        c = NCBIExtendedClient()
        assert c._email == DEFAULT_EMAIL

    async def test_custom_email(self, client):
        assert client._email == "test@example.com"

    async def test_api_key(self, client):
        assert client._api_key == "test_key"
        assert client._min_interval == 0.1  # with key

    async def test_no_api_key_interval(self, client_no_key):
        assert client_no_key._min_interval == 0.34

    async def test_timeout(self, client):
        assert client._timeout == 30.0


# ============================================================
# Rate Limiting
# ============================================================


class TestRateLimit:
    async def test_rate_limit_waits(self, client):
        client._last_request_time = time.time()
        start = time.time()
        await client._rate_limit()
        # Should have waited at least some time
        assert client._last_request_time >= start


# ============================================================
# _make_request
# ============================================================


class TestMakeRequest:
    async def test_json_response(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "ok"}
        mock_response.text = '{"result": "ok"}'
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        result = await client._make_request("https://example.com/api", expect_json=True)
        assert result == {"result": "ok"}

    async def test_text_response(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<xml>data</xml>"
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        result = await client._make_request(
            "https://example.com/api", expect_json=False
        )
        assert result == "<xml>data</xml>"

    async def test_http_error(self, client):
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.reason_phrase = "Server Error"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        result = await client._make_request("https://example.com/api")
        assert result is None

    async def test_generic_error(self, client):
        client._client = AsyncMock()
        client._client.get = AsyncMock(side_effect=Exception("Connection failed"))

        result = await client._make_request("https://example.com/api")
        assert result is None

    async def test_adds_email_and_tool(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        await client._make_request("https://example.com/api?db=gene")
        # Check the URL includes email and tool params
        call_args = client._client.get.call_args
        url = call_args[0][0]
        assert "email=" in url
        assert "tool=pubmed-search-mcp" in url


# ============================================================
# Gene Database
# ============================================================


class TestSearchGene:
    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_search_gene_success(self, mock_req, client):
        # First call: esearch
        mock_req.side_effect = [
            {"esearchresult": {"idlist": ["672"]}},
            {
                "result": {
                    "672": {
                        "uid": "672",
                        "name": "BRCA1",
                        "description": "BRCA1 DNA repair associated",
                        "organism": {"scientificname": "Homo sapiens", "taxid": "9606"},
                        "chromosome": "17",
                        "maplocation": "17q21.31",
                        "otheraliases": "BRCAI,BRCC1",
                        "summary": "Tumor suppressor",
                        "geneticsource": "protein-coding",
                    }
                }
            },
        ]
        genes = await client.search_gene("BRCA1")
        assert len(genes) == 1
        assert genes[0]["symbol"] == "BRCA1"
        assert genes[0]["gene_id"] == "672"
        assert genes[0]["organism"] == "Homo sapiens"
        assert genes[0]["aliases"] == ["BRCAI,BRCC1"]
        assert genes[0]["_source"] == "ncbi_gene"

    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_search_gene_with_organism(self, mock_req, client):
        mock_req.side_effect = [
            {"esearchresult": {"idlist": []}},
        ]
        result = await client.search_gene("BRCA1", organism="human")
        assert result == []
        # Verify organism was added to query
        call_url = mock_req.call_args_list[0][0][0]
        assert "human%5BOrganism%5D" in call_url or "human[Organism]" in call_url

    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_search_gene_no_results(self, mock_req, client):
        mock_req.return_value = {"esearchresult": {"idlist": []}}
        assert await client.search_gene("nonexistent") == []

    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_search_gene_search_fails(self, mock_req, client):
        mock_req.return_value = None
        assert await client.search_gene("BRCA1") == []

    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_search_gene_summary_fails(self, mock_req, client):
        mock_req.side_effect = [
            {"esearchresult": {"idlist": ["672"]}},
            None,
        ]
        assert await client.search_gene("BRCA1") == []

    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_search_gene_exception(self, mock_req, client):
        mock_req.side_effect = Exception("fail")
        assert await client.search_gene("BRCA1") == []


class TestGetGene:
    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_get_gene_success(self, mock_req, client):
        mock_req.return_value = {
            "result": {
                "672": {
                    "uid": "672",
                    "name": "BRCA1",
                    "description": "BRCA1 DNA repair",
                    "organism": {"scientificname": "Homo sapiens", "taxid": "9606"},
                    "chromosome": "17",
                    "maplocation": "",
                    "otheraliases": "",
                    "summary": "",
                    "geneticsource": "",
                }
            }
        }
        gene = await client.get_gene("672")
        assert gene is not None
        assert gene["gene_id"] == "672"

    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_get_gene_not_found(self, mock_req, client):
        mock_req.return_value = {"result": {}}
        assert await client.get_gene("99999") is None

    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_get_gene_request_fails(self, mock_req, client):
        mock_req.return_value = None
        assert await client.get_gene("672") is None

    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_get_gene_exception(self, mock_req, client):
        mock_req.side_effect = Exception("fail")
        assert await client.get_gene("672") is None


class TestGetGenePubmedLinks:
    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_success(self, mock_req, client):
        mock_req.return_value = {
            "linksets": [
                {
                    "linksetdbs": [
                        {"dbto": "pubmed", "links": [12345, 67890]},
                    ]
                }
            ]
        }
        pmids = await client.get_gene_pubmed_links("672")
        assert pmids == ["12345", "67890"]

    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_limit(self, mock_req, client):
        mock_req.return_value = {
            "linksets": [
                {
                    "linksetdbs": [
                        {"dbto": "pubmed", "links": list(range(100))},
                    ]
                }
            ]
        }
        pmids = await client.get_gene_pubmed_links("672", limit=5)
        assert len(pmids) == 5

    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_no_links(self, mock_req, client):
        mock_req.return_value = {"linksets": [{"linksetdbs": []}]}
        assert await client.get_gene_pubmed_links("672") == []

    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_request_fails(self, mock_req, client):
        mock_req.return_value = None
        assert await client.get_gene_pubmed_links("672") == []

    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_exception(self, mock_req, client):
        mock_req.side_effect = Exception("fail")
        assert await client.get_gene_pubmed_links("672") == []


# ============================================================
# PubChem Database
# ============================================================


class TestSearchCompound:
    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_success(self, mock_req, client):
        mock_req.side_effect = [
            {"esearchresult": {"idlist": ["2244"]}},
            {
                "result": {
                    "2244": {
                        "uid": "2244",
                        "synonymlist": ["Aspirin", "Acetylsalicylic acid"],
                        "iupacname": "2-acetoxybenzoic acid",
                        "molecularformula": "C9H8O4",
                        "molecularweight": "180.16",
                        "canonicalsmiles": "CC(=O)OC1=CC=CC=C1C(=O)O",
                        "isomericsmiles": "",
                        "inchi": "InChI=1S/...",
                        "inchikey": "BSYNRYMUTXBXSQ",
                        "charge": 0,
                        "heavyatomcount": 13,
                        "rotatablebondcount": 3,
                        "hydrogenbonddonorcount": 1,
                        "hydrogenbondacceptorcount": 4,
                    }
                }
            },
        ]
        compounds = await client.search_compound("aspirin")
        assert len(compounds) == 1
        assert compounds[0]["cid"] == "2244"
        assert compounds[0]["name"] == "Aspirin"
        assert compounds[0]["_source"] == "pubchem"
        assert len(compounds[0]["synonyms"]) == 2

    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_no_results(self, mock_req, client):
        mock_req.return_value = {"esearchresult": {"idlist": []}}
        assert await client.search_compound("nonexistent") == []

    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_exception(self, mock_req, client):
        mock_req.side_effect = Exception("fail")
        assert await client.search_compound("aspirin") == []


class TestGetCompound:
    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_success(self, mock_req, client):
        mock_req.return_value = {
            "result": {
                "2244": {
                    "uid": "2244",
                    "synonymlist": ["Aspirin"],
                    "iupacname": "",
                    "molecularformula": "C9H8O4",
                    "molecularweight": "",
                    "canonicalsmiles": "",
                    "isomericsmiles": "",
                    "inchi": "",
                    "inchikey": "",
                }
            }
        }
        compound = await client.get_compound("2244")
        assert compound is not None
        assert compound["cid"] == "2244"

    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_not_found(self, mock_req, client):
        mock_req.return_value = {"result": {}}
        assert await client.get_compound("99999") is None

    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_exception(self, mock_req, client):
        mock_req.side_effect = Exception("fail")
        assert await client.get_compound("2244") is None


class TestGetCompoundPubmedLinks:
    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_success(self, mock_req, client):
        mock_req.return_value = {
            "linksets": [
                {
                    "linksetdbs": [
                        {"dbto": "pubmed", "links": [11111, 22222]},
                    ]
                }
            ]
        }
        pmids = await client.get_compound_pubmed_links("2244")
        assert pmids == ["11111", "22222"]

    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_exception(self, mock_req, client):
        mock_req.side_effect = Exception("fail")
        assert await client.get_compound_pubmed_links("2244") == []


# ============================================================
# ClinVar Database
# ============================================================


class TestSearchClinvar:
    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_success(self, mock_req, client):
        mock_req.side_effect = [
            {"esearchresult": {"idlist": ["12345"]}},
            {
                "result": {
                    "12345": {
                        "uid": "12345",
                        "accession": "VCV000012345",
                        "title": "NM_007294.4(BRCA1):c.5266dupC",
                        "clinical_significance": {"description": "Pathogenic"},
                        "genes": [{"symbol": "BRCA1"}],
                        "review_status": "reviewed by expert panel",
                        "obj_type": "single nucleotide variant",
                        "chr": "17",
                        "start": 43057051,
                        "stop": 43057051,
                        "trait_set": [{"trait_name": "Breast-ovarian cancer"}],
                    }
                }
            },
        ]
        variants = await client.search_clinvar("BRCA1")
        assert len(variants) == 1
        assert variants[0]["clinvar_id"] == "12345"
        assert variants[0]["clinical_significance"] == "Pathogenic"
        assert variants[0]["gene_symbols"] == ["BRCA1"]
        assert variants[0]["_source"] == "clinvar"

    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_clinvar_string_significance(self, mock_req, client):
        mock_req.side_effect = [
            {"esearchresult": {"idlist": ["1"]}},
            {
                "result": {
                    "1": {
                        "uid": "1",
                        "clinical_significance": "Benign",
                        "genes": [],
                        "trait_set": [],
                    }
                }
            },
        ]
        variants = await client.search_clinvar("test")
        assert variants[0]["clinical_significance"] == "Benign"

    @patch.object(NCBIExtendedClient, "_make_request")
    async def test_exception(self, mock_req, client):
        mock_req.side_effect = Exception("fail")
        assert await client.search_clinvar("BRCA1") == []


# ============================================================
# Normalize helpers
# ============================================================


class TestNormalizeGene:
    async def test_no_aliases(self, client):
        gene = client._normalize_gene({"uid": "1", "otheraliases": ""})
        assert gene["aliases"] == []

    async def test_with_aliases(self, client):
        gene = client._normalize_gene({"uid": "1", "otheraliases": "A, B, C"})
        assert gene["aliases"] == ["A", "B", "C"]


class TestNormalizeCompound:
    async def test_string_synonyms(self, client):
        compound = client._normalize_compound({"synonymlist": "Aspirin"})
        assert compound["synonyms"] == ["Aspirin"]

    async def test_list_synonyms_limited(self, client):
        syns = [f"Syn{i}" for i in range(20)]
        compound = client._normalize_compound({"synonymlist": syns})
        assert len(compound["synonyms"]) == 10

    async def test_cid_fallback(self, client):
        compound = client._normalize_compound({"cid": "999", "synonymlist": []})
        assert compound["cid"] == "999"


class TestNormalizeClinvar:
    async def test_non_dict_gene(self, client):
        variant = client._normalize_clinvar(
            {
                "uid": "1",
                "genes": ["not_a_dict"],
                "clinical_significance": {"description": "VUS"},
                "trait_set": [],
            }
        )
        assert variant["gene_symbols"] == []

    async def test_non_dict_trait(self, client):
        variant = client._normalize_clinvar(
            {
                "uid": "1",
                "genes": [],
                "clinical_significance": {"description": "VUS"},
                "trait_set": ["not_a_dict"],
            }
        )
        assert variant["conditions"] == []


# ============================================================
# Singleton
# ============================================================


class TestSingleton:
    async def test_get_ncbi_extended_client(self):
        import pubmed_search.infrastructure.sources.ncbi_extended as mod

        mod._ncbi_extended_client = None
        with patch.dict("os.environ", {"NCBI_EMAIL": "e@e.com", "NCBI_API_KEY": "k"}):
            c = get_ncbi_extended_client()
            assert c is not None
        mod._ncbi_extended_client = None  # Reset
