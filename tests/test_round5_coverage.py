"""
Round 5 coverage tests — server module, CORE infra, Europe PMC infra,
clinical_trials, citation_exporter, openurl infra, NCBI strategy.

NOTE: search_literature, expand_search_queries, search_europe_pmc are
      UNREGISTERED closures (commented-out @mcp.tool()).
      We test the underlying infrastructure and helper functions instead.
"""

import time
from unittest.mock import MagicMock, patch
import urllib.error


# ============================================================
# MCP server.py — start_http_api_background
# ============================================================


class TestMCPAPIHandler:
    """Test the HTTP API handler that runs alongside MCP server."""

    def test_start_http_api_returns_thread(self):
        from pubmed_search.presentation.mcp_server.server import (
            start_http_api_background,
        )

        mock_sm = MagicMock()
        mock_searcher = MagicMock()

        with patch(
            "pubmed_search.presentation.mcp_server.server.HTTPServer",
            create=True,
        ) as mock_hs:
            mock_server = MagicMock()
            mock_hs.return_value = mock_server
            thread = start_http_api_background(mock_sm, mock_searcher, port=19999)
            assert thread.daemon is True
            time.sleep(0.15)

    def test_start_http_api_port_in_use(self):
        from pubmed_search.presentation.mcp_server.server import (
            start_http_api_background,
        )

        mock_sm = MagicMock()
        mock_searcher = MagicMock()

        with patch(
            "pubmed_search.presentation.mcp_server.server.HTTPServer",
            create=True,
        ) as mock_hs:
            err = OSError("Address already in use")
            err.errno = 10048
            mock_hs.side_effect = err
            thread = start_http_api_background(mock_sm, mock_searcher, port=8765)
            assert thread.daemon is True
            time.sleep(0.2)


class TestServerModule:
    def test_import(self):
        import pubmed_search.presentation.mcp_server.server as mod

        assert hasattr(mod, "start_http_api_background")
        assert hasattr(mod, "main")

    def test_create_server(self):
        from pubmed_search.presentation.mcp_server.server import create_server

        srv = create_server(email="test@test.com")
        assert srv is not None


# ============================================================
# CORE infrastructure — COREClient
# ============================================================


class TestCOREClient:
    """Test infrastructure/sources/core.py."""

    def test_init_defaults(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        assert c._api_key is None
        assert c._timeout == 30.0

    def test_init_with_key(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient(api_key="test-key")
        assert c._api_key == "test-key"
        assert c._min_interval == 2.5  # Faster with key

    def test_rate_limit_delay(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        c._min_interval = 0.01
        c._last_request_time = time.time()
        c._rate_limit()  # Should wait briefly

    def test_make_request_success(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        c._last_request_time = 0

        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = c._make_request("https://example.com/api")
        assert result == {"ok": True}

    def test_make_request_http_error_401(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        c._last_request_time = 0

        err = urllib.error.HTTPError(
            "url", 401, "Unauthorized", {}, None
        )
        with patch("urllib.request.urlopen", side_effect=err):
            result = c._make_request("https://example.com/api")
        assert result is None

    def test_make_request_http_error_429(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        c._last_request_time = 0

        err = urllib.error.HTTPError(
            "url", 429, "Rate Limit", {}, None
        )
        with patch("urllib.request.urlopen", side_effect=err):
            result = c._make_request("https://example.com/api")
        assert result is None

    def test_make_request_url_error(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        c._last_request_time = 0

        err = urllib.error.URLError("Connection refused")
        with patch("urllib.request.urlopen", side_effect=err):
            result = c._make_request("https://example.com/api")
        assert result is None

    def test_search_success(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        c._last_request_time = 0

        mock_response_data = {
            "totalHits": 50,
            "results": [
                {
                    "id": 12345,
                    "title": "Machine Learning Paper",
                    "authors": [{"name": "John Doe"}],
                    "yearPublished": 2023,
                    "abstract": "Abstract text",
                    "doi": "10.1234/test",
                    "downloadUrl": "https://core.ac.uk/pdf/12345.pdf",
                    "fullText": None,
                    "journals": [{"title": "Test Journal"}],
                    "citationCount": 10,
                }
            ],
        }

        with patch.object(c, "_make_request", return_value=mock_response_data):
            result = c.search("machine learning", limit=5)
        assert result["total_hits"] == 50
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Machine Learning Paper"
        assert result["results"][0]["doi"] == "10.1234/test"

    def test_search_empty(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        with patch.object(c, "_make_request", return_value=None):
            result = c.search("xyz_no_match")
        assert result["total_hits"] == 0
        assert result["results"] == []

    def test_search_with_filters(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        with patch.object(
            c, "_make_request", return_value={"totalHits": 0, "results": []}
        ) as mock_req:
            c.search(
                "test",
                year_from=2020,
                year_to=2024,
                has_fulltext=True,
                sort="recency",
            )
        assert mock_req.called
        url_arg = mock_req.call_args[0][0]
        assert "2020" in url_arg
        assert "fullText" in url_arg

    def test_search_fulltext(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        with patch.object(
            c, "search", return_value={"total_hits": 0, "results": []}
        ) as mock_s:
            c.search_fulltext("deep learning", limit=5)
        assert mock_s.called
        # search_fulltext wraps query in fullText:"..." 
        call_query = mock_s.call_args[1].get("query") or mock_s.call_args[0][0]
        assert "fullText" in call_query

    def test_get_work_success(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        work_data = {
            "id": 999,
            "title": "A Paper",
            "authors": [{"name": "A B"}],
            "yearPublished": 2022,
        }
        with patch.object(c, "_make_request", return_value=work_data):
            result = c.get_work(999)
        assert result is not None
        assert result["title"] == "A Paper"

    def test_get_work_not_found(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        with patch.object(c, "_make_request", return_value=None):
            result = c.get_work(99999)
        assert result is None

    def test_get_output(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        output_data = {
            "id": 888,
            "title": "Output",
            "fullText": "Full text here",
            "authors": [],
        }
        with patch.object(c, "_make_request", return_value=output_data):
            result = c.get_output(888)
        assert result is not None
        assert result["full_text"] == "Full text here"

    def test_get_fulltext(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        output_data = {
            "id": 777,
            "title": "FT Paper",
            "fullText": "The full text content",
            "authors": [],
        }
        with patch.object(c, "_make_request", return_value=output_data):
            result = c.get_fulltext(777)
        assert result == "The full text content"

    def test_get_fulltext_none(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        with patch.object(c, "_make_request", return_value=None):
            result = c.get_fulltext(999)
        assert result is None

    def test_search_by_doi(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        with patch.object(
            c,
            "search",
            return_value={"results": [{"title": "Found by DOI", "doi": "10.1234/x"}]},
        ):
            result = c.search_by_doi("10.1234/x")
        assert result["title"] == "Found by DOI"

    def test_search_by_doi_not_found(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        with patch.object(c, "search", return_value={"results": []}):
            result = c.search_by_doi("10.9999/none")
        assert result is None

    def test_search_by_pmid(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        with patch.object(
            c,
            "search",
            return_value={"results": [{"title": "Found by PMID", "pmid": "111"}]},
        ):
            result = c.search_by_pmid("111")
        assert result["title"] == "Found by PMID"

    def test_normalize_work_identifiers(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        work = {
            "id": 1,
            "title": "Test",
            "authors": [{"name": "Alice"}, "Bob"],
            "identifiers": [
                {"type": "DOI", "identifier": "10.1/doi"},
                {"type": "PMID", "identifier": "12345"},
                {"type": "ARXIV", "identifier": "2301.00001"},
            ],
            "journals": [{"title": "J of Test"}],
            "links": [
                {"type": "download", "url": "https://pdf.example.com"},
                {"type": "reader", "url": "https://reader.example.com"},
            ],
            "language": {"name": "English"},
            "dataProviders": [{"name": "Provider1"}],
            "citationCount": 42,
        }
        result = c._normalize_work(work)
        assert result["doi"] == "10.1/doi"
        assert result["pmid"] == "12345"
        assert result["arxiv_id"] == "2301.00001"
        assert result["journal"] == "J of Test"
        assert result["pdf_url"] == "https://pdf.example.com"
        assert result["reader_url"] == "https://reader.example.com"
        assert result["language"] == "English"
        assert result["citation_count"] == 42
        assert "Alice" in result["author_string"]

    def test_normalize_output(self):
        from pubmed_search.infrastructure.sources.core import COREClient

        c = COREClient()
        output = {
            "id": 2,
            "title": "Output",
            "fullText": "Content",
            "fulltextStatus": "available",
            "authors": [],
            "repositories": [{"name": "Repo1", "urlHomepage": "https://repo.com"}],
        }
        result = c._normalize_output(output)
        assert result["full_text"] == "Content"
        assert result["repository"] == "Repo1"


class TestCOREConvenience:
    """Test convenience functions."""

    def test_get_core_client_singleton(self):
        from pubmed_search.infrastructure.sources.core import get_core_client
        import pubmed_search.infrastructure.sources.core as mod

        mod._core_client = None
        c1 = get_core_client()
        c2 = get_core_client()
        assert c1 is c2
        mod._core_client = None

    def test_search_core(self):
        from pubmed_search.infrastructure.sources.core import search_core

        with patch(
            "pubmed_search.infrastructure.sources.core.get_core_client"
        ) as mock_gc:
            mock_client = MagicMock()
            mock_client.search.return_value = {
                "total_hits": 1,
                "results": [{"title": "Test"}],
            }
            mock_gc.return_value = mock_client
            result = search_core("test", limit=5)
        assert len(result) == 1

    def test_search_core_fulltext(self):
        from pubmed_search.infrastructure.sources.core import search_core_fulltext

        with patch(
            "pubmed_search.infrastructure.sources.core.get_core_client"
        ) as mock_gc:
            mock_client = MagicMock()
            mock_client.search_fulltext.return_value = {
                "total_hits": 0,
                "results": [],
            }
            mock_gc.return_value = mock_client
            result = search_core_fulltext("test")
        assert result == []


# ============================================================
# ClinicalTrialsClient
# ============================================================


class TestClinicalTrialsClient:
    """Test infrastructure/sources/clinical_trials.py."""

    def test_init(self):
        from pubmed_search.infrastructure.sources.clinical_trials import (
            ClinicalTrialsClient,
        )

        c = ClinicalTrialsClient()
        assert c.timeout == 10.0

    def test_lazy_client(self):
        from pubmed_search.infrastructure.sources.clinical_trials import (
            ClinicalTrialsClient,
        )

        c = ClinicalTrialsClient()
        assert c._client is None
        client = c.client
        assert client is not None
        c._client = None  # cleanup

    def test_search_success(self):
        from pubmed_search.infrastructure.sources.clinical_trials import (
            ClinicalTrialsClient,
        )

        c = ClinicalTrialsClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "studies": [
                {
                    "protocolSection": {
                        "identificationModule": {
                            "nctId": "NCT12345",
                            "briefTitle": "Test Trial",
                            "officialTitle": "Official Title",
                        },
                        "statusModule": {
                            "overallStatus": "RECRUITING",
                            "startDateStruct": {"date": "2023-01-01"},
                        },
                        "designModule": {
                            "phases": ["PHASE3"],
                            "enrollmentInfo": {"count": 200},
                            "studyType": "INTERVENTIONAL",
                        },
                        "conditionsModule": {
                            "conditions": ["Diabetes"],
                        },
                        "armsInterventionsModule": {
                            "interventions": [
                                {"type": "DRUG", "name": "Metformin"},
                            ],
                        },
                        "sponsorCollaboratorsModule": {
                            "leadSponsor": {"name": "Test University"},
                        },
                    }
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        c._client = mock_client

        result = c.search("diabetes treatment", limit=5)
        assert len(result) == 1
        assert result[0]["nct_id"] == "NCT12345"
        assert result[0]["status"] == "RECRUITING"
        assert result[0]["phase"] == "PHASE3"
        assert result[0]["enrollment"] == 200
        c._client = None

    def test_search_with_status_filter(self):
        from pubmed_search.infrastructure.sources.clinical_trials import (
            ClinicalTrialsClient,
        )

        c = ClinicalTrialsClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"studies": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        c._client = mock_client

        result = c.search("test", status=["RECRUITING", "COMPLETED"])
        assert result == []
        call_params = mock_client.get.call_args
        assert "RECRUITING" in str(call_params)
        c._client = None

    def test_search_empty(self):
        from pubmed_search.infrastructure.sources.clinical_trials import (
            ClinicalTrialsClient,
        )

        c = ClinicalTrialsClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"studies": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        c._client = mock_client

        result = c.search("xyz_no_results")
        assert result == []
        c._client = None

    def test_search_timeout(self):
        from pubmed_search.infrastructure.sources.clinical_trials import (
            ClinicalTrialsClient,
        )
        import httpx

        c = ClinicalTrialsClient()
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.TimeoutException("timeout")
        c._client = mock_client

        result = c.search("test")
        assert result == []
        c._client = None

    def test_search_http_error(self):
        from pubmed_search.infrastructure.sources.clinical_trials import (
            ClinicalTrialsClient,
        )
        import httpx

        c = ClinicalTrialsClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=mock_resp
        )
        c._client = mock_client

        result = c.search("test")
        assert result == []
        c._client = None

    def test_normalize_study_minimal(self):
        from pubmed_search.infrastructure.sources.clinical_trials import (
            ClinicalTrialsClient,
        )

        c = ClinicalTrialsClient()
        study = {"protocolSection": {}}
        result = c._normalize_study(study)
        assert result["nct_id"] == ""
        assert result["status"] == "UNKNOWN"
        assert result["phase"] == "N/A"


class TestClinicalTrialsGetStudy:
    """Test get_study method."""

    def test_get_study_success(self):
        from pubmed_search.infrastructure.sources.clinical_trials import (
            ClinicalTrialsClient,
        )

        c = ClinicalTrialsClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT99999",
                    "briefTitle": "Specific Trial",
                },
                "statusModule": {"overallStatus": "COMPLETED"},
                "designModule": {},
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        c._client = mock_client

        result = c.get_study("NCT99999")
        assert result is not None
        assert result["nct_id"] == "NCT99999"
        c._client = None

    def test_get_study_not_found(self):
        from pubmed_search.infrastructure.sources.clinical_trials import (
            ClinicalTrialsClient,
        )
        import httpx

        c = ClinicalTrialsClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=mock_resp
        )
        c._client = mock_client

        result = c.get_study("NCT00000")
        assert result is None
        c._client = None


# ============================================================
# NCBICitationExporter
# ============================================================


class TestNCBICitationExporter:
    """Test infrastructure/ncbi/citation_exporter.py."""

    def test_init(self):
        from pubmed_search.infrastructure.ncbi.citation_exporter import (
            NCBICitationExporter,
        )

        e = NCBICitationExporter()
        assert e.timeout == 30.0

    def test_lazy_client(self):
        from pubmed_search.infrastructure.ncbi.citation_exporter import (
            NCBICitationExporter,
        )

        e = NCBICitationExporter()
        assert e._client is None
        client = e.client
        assert client is not None
        e._client = None

    def test_export_no_pmids(self):
        from pubmed_search.infrastructure.ncbi.citation_exporter import (
            NCBICitationExporter,
        )

        e = NCBICitationExporter()
        result = e.export_citations([])
        assert result.success is False
        assert "No PMIDs" in result.error

    def test_export_invalid_format(self):
        from pubmed_search.infrastructure.ncbi.citation_exporter import (
            NCBICitationExporter,
        )

        e = NCBICitationExporter()
        result = e.export_citations(["12345"], format="invalid_format")
        assert result.success is False
        assert "Unsupported" in result.error

    def test_export_ris_success(self):
        from pubmed_search.infrastructure.ncbi.citation_exporter import (
            NCBICitationExporter,
        )

        e = NCBICitationExporter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "TY  - JOUR\nTI  - Test Article\nER  -\n"
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        e._client = mock_client

        result = e.export_citations(["12345"], format="ris")
        assert result.success is True
        assert "TY  - JOUR" in result.content
        assert result.pmid_count == 1
        e._client = None

    def test_export_medline_success(self):
        from pubmed_search.infrastructure.ncbi.citation_exporter import (
            NCBICitationExporter,
        )

        e = NCBICitationExporter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "PMID- 12345\nTI  - Test\n"
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        e._client = mock_client

        result = e.export_citations(["12345"], format="medline")
        assert result.success is True
        assert "PMID" in result.content
        e._client = None

    def test_export_csl_success(self):
        from pubmed_search.infrastructure.ncbi.citation_exporter import (
            NCBICitationExporter,
        )

        e = NCBICitationExporter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '[{"type": "article-journal"}]'
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        e._client = mock_client

        result = e.export_citations(["12345"], format="csl")
        assert result.success is True
        e._client = None

    def test_export_api_error_response(self):
        from pubmed_search.infrastructure.ncbi.citation_exporter import (
            NCBICitationExporter,
        )

        e = NCBICitationExporter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"format": "unknown_fmt"}'
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        e._client = mock_client

        result = e.export_citations(["12345"], format="ris")
        assert result.success is False
        assert "Invalid format" in result.error
        e._client = None

    def test_export_http_error(self):
        from pubmed_search.infrastructure.ncbi.citation_exporter import (
            NCBICitationExporter,
        )
        import httpx

        e = NCBICitationExporter()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=mock_resp
        )
        e._client = mock_client

        result = e.export_citations(["12345"], format="ris")
        assert result.success is False
        e._client = None

    def test_export_multiple_pmids(self):
        from pubmed_search.infrastructure.ncbi.citation_exporter import (
            NCBICitationExporter,
        )

        e = NCBICitationExporter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "TY  - JOUR\nER  -\nTY  - JOUR\nER  -\n"
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        e._client = mock_client

        result = e.export_citations(["11111", "22222", "33333"], format="ris")
        assert result.success is True
        assert result.pmid_count == 3
        e._client = None


# ============================================================
# Europe PMC infrastructure — deeper coverage
# ============================================================


class TestEuropePMCInfra:
    """Test infrastructure/sources/europe_pmc.py."""

    def test_singleton(self):
        from pubmed_search.infrastructure.sources import get_europe_pmc_client

        c1 = get_europe_pmc_client()
        c2 = get_europe_pmc_client()
        assert c1 is c2

    def test_search_with_filters(self):
        from pubmed_search.infrastructure.sources.europe_pmc import EuropePMCClient

        c = EuropePMCClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "hitCount": 5,
            "resultList": {
                "result": [
                    {
                        "pmid": "111",
                        "title": "Test",
                        "authorString": "Smith J",
                        "pubYear": "2023",
                        "journalTitle": "J Test",
                    }
                ]
            },
        }

        with patch.object(c, "_make_request", return_value=mock_resp.json.return_value):
            result = c.search("diabetes", limit=10, min_year=2020, open_access_only=True)
        assert result["hit_count"] == 5

    def test_get_citations(self):
        from pubmed_search.infrastructure.sources.europe_pmc import EuropePMCClient

        c = EuropePMCClient()

        mock_data = {
            "hitCount": 2,
            "citationList": {
                "citation": [
                    {
                        "title": "Citing 1",
                        "pubYear": "2024",
                        "authorString": "A B",
                    },
                    {"title": "Citing 2", "pubYear": "2023"},
                ]
            },
        }

        with patch.object(c, "_make_request", return_value=mock_data):
            result = c.get_citations("MED", "12345")
        assert len(result) == 2

    def test_get_references(self):
        from pubmed_search.infrastructure.sources.europe_pmc import EuropePMCClient

        c = EuropePMCClient()

        mock_data = {
            "hitCount": 1,
            "referenceList": {
                "reference": [
                    {"title": "Ref 1", "pubYear": "2020"},
                ]
            },
        }

        with patch.object(c, "_make_request", return_value=mock_data):
            result = c.get_references("MED", "12345")
        assert len(result) == 1


# ============================================================
# NCBI Strategy infrastructure
# ============================================================


class TestNCBIStrategy:
    """Test infrastructure/ncbi/strategy.py — SearchStrategyGenerator."""

    def test_import(self):
        from pubmed_search.infrastructure.ncbi.strategy import SearchStrategyGenerator

        assert SearchStrategyGenerator is not None

    def test_init(self):
        from pubmed_search.infrastructure.ncbi.strategy import SearchStrategyGenerator

        sg = SearchStrategyGenerator(email="test@test.com")
        assert sg is not None

    def test_spell_check(self):
        from pubmed_search.infrastructure.ncbi.strategy import SearchStrategyGenerator

        sg = SearchStrategyGenerator(email="test@test.com")
        # Mock the Entrez call
        mock_record = {"CorrectedQuery": "diabetes", "Query": "diabtes"}
        with patch(
            "pubmed_search.infrastructure.ncbi.strategy.Entrez.espell",
            return_value=MagicMock(),
        ), patch(
            "pubmed_search.infrastructure.ncbi.strategy.Entrez.read",
            return_value=mock_record,
        ):
            corrected, changed = sg.spell_check("diabtes")
        assert corrected == "diabetes"
        assert changed is True

    def test_spell_check_no_correction(self):
        from pubmed_search.infrastructure.ncbi.strategy import SearchStrategyGenerator

        sg = SearchStrategyGenerator(email="test@test.com")
        mock_record = {"CorrectedQuery": "", "Query": "diabetes"}
        with patch(
            "pubmed_search.infrastructure.ncbi.strategy.Entrez.espell",
            return_value=MagicMock(),
        ), patch(
            "pubmed_search.infrastructure.ncbi.strategy.Entrez.read",
            return_value=mock_record,
        ):
            corrected, changed = sg.spell_check("diabetes")
        assert corrected == "diabetes"
        assert changed is False

    def test_get_mesh_terms(self):
        from pubmed_search.infrastructure.ncbi.strategy import SearchStrategyGenerator

        sg = SearchStrategyGenerator(email="test@test.com")
        mock_record = {
            "IdList": ["68003920"],
            "TranslationStack": [],
        }
        with patch(
            "pubmed_search.infrastructure.ncbi.strategy.Entrez.esearch",
            return_value=MagicMock(),
        ), patch(
            "pubmed_search.infrastructure.ncbi.strategy.Entrez.read",
            return_value=mock_record,
        ):
            info = sg.get_mesh_info("diabetes")
        # May return None or dict depending on mock
        assert info is None or isinstance(info, dict)
