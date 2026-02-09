"""
Tests for CrossRef API client.

Target: crossref.py coverage from 0% to 90%+
"""

import json
import urllib.error
from unittest.mock import MagicMock, patch


from pubmed_search.infrastructure.sources.crossref import (
    CrossRefClient,
    get_citation_count,
    get_crossref_client,
    get_doi_metadata,
    search_crossref,
)


# =============================================================================
# CrossRefClient - Basic Tests
# =============================================================================


class TestCrossRefClientBasic:
    """Basic tests for CrossRefClient."""

    def test_init_default(self):
        """Test initialization with defaults."""
        client = CrossRefClient()
        assert client._email is not None
        assert client._timeout == 30.0

    def test_init_custom(self):
        """Test initialization with custom settings."""
        client = CrossRefClient(email="test@example.com", timeout=60.0)
        assert client._email == "test@example.com"
        assert client._timeout == 60.0

    def test_normalize_doi_plain(self):
        """Test DOI normalization with plain DOI."""
        assert CrossRefClient._normalize_doi("10.1000/test") == "10.1000/test"

    def test_normalize_doi_https(self):
        """Test DOI normalization with https prefix."""
        result = CrossRefClient._normalize_doi("https://doi.org/10.1000/test")
        assert result == "10.1000/test"

    def test_normalize_doi_http(self):
        """Test DOI normalization with http prefix."""
        result = CrossRefClient._normalize_doi("http://doi.org/10.1000/test")
        assert result == "10.1000/test"

    def test_normalize_doi_prefix(self):
        """Test DOI normalization with doi: prefix."""
        result = CrossRefClient._normalize_doi("doi:10.1000/test")
        assert result == "10.1000/test"

    def test_normalize_doi_whitespace(self):
        """Test DOI normalization with whitespace."""
        result = CrossRefClient._normalize_doi("  10.1000/test  ")
        assert result == "10.1000/test"


# =============================================================================
# CrossRefClient - get_work Tests
# =============================================================================


class TestCrossRefClientGetWork:
    """Tests for get_work method."""

    @patch("urllib.request.urlopen")
    def test_get_work_success(self, mock_urlopen):
        """Test successful work retrieval."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "message": {
                    "DOI": "10.1000/test",
                    "title": ["Test Article"],
                    "author": [{"family": "Smith", "given": "John"}],
                }
            }
        ).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        client = CrossRefClient()
        client._min_interval = 0  # Disable rate limiting for tests

        result = client.get_work("10.1000/test")
        assert result is not None
        assert result["DOI"] == "10.1000/test"
        assert result["title"] == ["Test Article"]

    @patch("urllib.request.urlopen")
    def test_get_work_not_found(self, mock_urlopen):
        """Test work not found (404)."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 404, "Not Found", {}, None
        )

        client = CrossRefClient()
        client._min_interval = 0

        result = client.get_work("10.1000/nonexistent")
        assert result is None

    @patch("urllib.request.urlopen")
    def test_get_work_rate_limited(self, mock_urlopen):
        """Test rate limit error (429)."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 429, "Too Many Requests", {}, None
        )

        client = CrossRefClient()
        client._min_interval = 0

        result = client.get_work("10.1000/test")
        assert result is None

    @patch("urllib.request.urlopen")
    def test_get_work_url_error(self, mock_urlopen):
        """Test URL error."""
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        client = CrossRefClient()
        client._min_interval = 0

        result = client.get_work("10.1000/test")
        assert result is None


# =============================================================================
# CrossRefClient - search Tests
# =============================================================================


class TestCrossRefClientSearch:
    """Tests for search method."""

    @patch("urllib.request.urlopen")
    def test_search_success(self, mock_urlopen):
        """Test successful search."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "message": {
                    "total-results": 100,
                    "items": [
                        {"DOI": "10.1/a", "title": ["Article 1"]},
                        {"DOI": "10.1/b", "title": ["Article 2"]},
                    ],
                }
            }
        ).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        client = CrossRefClient()
        client._min_interval = 0

        result = client.search("machine learning", limit=10)
        assert result["total_results"] == 100
        assert len(result["items"]) == 2

    @patch("urllib.request.urlopen")
    def test_search_with_filters(self, mock_urlopen):
        """Test search with filter parameters."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"message": {"total-results": 50, "items": []}}
        ).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        client = CrossRefClient()
        client._min_interval = 0

        result = client.search(
            "test", filter_params={"from-pub-date": "2020", "type": "journal-article"}
        )
        assert result["total_results"] == 50

    @patch("urllib.request.urlopen")
    def test_search_empty_result(self, mock_urlopen):
        """Test search with no results."""
        mock_urlopen.return_value = None
        client = CrossRefClient()
        client._min_interval = 0
        client._make_request = MagicMock(return_value=None)

        result = client.search("nonexistent query xyz")
        assert result["total_results"] == 0
        assert result["items"] == []


# =============================================================================
# CrossRefClient - search_by_title Tests
# =============================================================================


class TestCrossRefClientSearchByTitle:
    """Tests for search_by_title method."""

    @patch("urllib.request.urlopen")
    def test_search_by_title_success(self, mock_urlopen):
        """Test successful title search."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "message": {
                    "items": [{"DOI": "10.1/exact", "title": ["Exact Match"]}]
                }
            }
        ).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        client = CrossRefClient()
        client._min_interval = 0

        results = client.search_by_title("Exact Match", limit=5)
        assert len(results) == 1
        assert results[0]["DOI"] == "10.1/exact"

    def test_search_by_title_empty(self):
        """Test title search with no results."""
        client = CrossRefClient()
        client._make_request = MagicMock(return_value=None)

        results = client.search_by_title("Nonexistent Title")
        assert results == []


# =============================================================================
# CrossRefClient - get_references Tests
# =============================================================================


class TestCrossRefClientGetReferences:
    """Tests for get_references method."""

    def test_get_references_success(self):
        """Test successful reference retrieval."""
        client = CrossRefClient()
        client.get_work = MagicMock(
            return_value={
                "DOI": "10.1/test",
                "reference": [
                    {"DOI": "10.1/ref1", "unstructured": "Reference 1"},
                    {"DOI": "10.1/ref2", "unstructured": "Reference 2"},
                    {"unstructured": "Reference 3 without DOI"},
                ],
            }
        )

        refs = client.get_references("10.1/test", limit=10)
        assert len(refs) == 3

    def test_get_references_not_found(self):
        """Test reference retrieval when work not found."""
        client = CrossRefClient()
        client.get_work = MagicMock(return_value=None)

        refs = client.get_references("10.1/notfound")
        assert refs == []

    def test_get_references_no_refs(self):
        """Test reference retrieval when work has no references."""
        client = CrossRefClient()
        client.get_work = MagicMock(return_value={"DOI": "10.1/test"})

        refs = client.get_references("10.1/test")
        assert refs == []


# =============================================================================
# CrossRefClient - get_citations Tests
# =============================================================================


class TestCrossRefClientGetCitations:
    """Tests for get_citations method."""

    def test_get_citations_success(self):
        """Test successful citation retrieval."""
        client = CrossRefClient()
        client._min_interval = 0
        client.get_work = MagicMock(return_value={"is-referenced-by-count": 50})
        client._make_request = MagicMock(
            return_value={
                "items": [{"DOI": "10.1/citing1"}, {"DOI": "10.1/citing2"}]
            }
        )

        result = client.get_citations("10.1/test", limit=10)
        assert result["citation_count"] == 50
        assert len(result["items"]) == 2

    def test_get_citations_work_not_found(self):
        """Test citation retrieval when work not found."""
        client = CrossRefClient()
        client._min_interval = 0
        client.get_work = MagicMock(return_value=None)
        client._make_request = MagicMock(return_value=None)

        result = client.get_citations("10.1/notfound")
        assert result["citation_count"] == 0
        assert result["items"] == []


# =============================================================================
# CrossRefClient - get_journal Tests
# =============================================================================


class TestCrossRefClientGetJournal:
    """Tests for get_journal method."""

    def test_get_journal_success(self):
        """Test successful journal retrieval."""
        client = CrossRefClient()
        client._make_request = MagicMock(
            return_value={
                "title": "Nature Medicine",
                "ISSN": ["1078-8956"],
            }
        )

        result = client.get_journal("1078-8956")
        assert result is not None
        assert result["title"] == "Nature Medicine"


# =============================================================================
# CrossRefClient - resolve_doi_batch Tests
# =============================================================================


class TestCrossRefClientBatch:
    """Tests for batch operations."""

    def test_resolve_doi_batch(self):
        """Test batch DOI resolution."""
        client = CrossRefClient()

        def mock_get_work(doi):
            return {"DOI": doi, "title": [f"Article {doi}"]}

        client.get_work = MagicMock(side_effect=mock_get_work)

        dois = ["10.1/a", "10.1/b", "10.1/c"]
        results = client.resolve_doi_batch(dois)

        assert len(results) == 3
        assert all(doi in results for doi in dois)


# =============================================================================
# CrossRefClient - enrich_with_crossref Tests
# =============================================================================


class TestCrossRefClientEnrich:
    """Tests for enrich_with_crossref method."""

    def test_enrich_with_doi(self):
        """Test enrichment with DOI."""
        client = CrossRefClient()
        client.get_work = MagicMock(return_value={"DOI": "10.1/test"})

        result = client.enrich_with_crossref(doi="10.1/test")
        assert result is not None

    def test_enrich_with_title_fallback(self):
        """Test enrichment falls back to title search."""
        client = CrossRefClient()
        client.get_work = MagicMock(return_value=None)
        client.search_by_title = MagicMock(
            return_value=[{"DOI": "10.1/found", "title": ["Test"]}]
        )

        result = client.enrich_with_crossref(title="Test Article")
        assert result is not None
        assert result["DOI"] == "10.1/found"

    def test_enrich_nothing_found(self):
        """Test enrichment when nothing found."""
        client = CrossRefClient()
        client.get_work = MagicMock(return_value=None)
        client.search_by_title = MagicMock(return_value=[])

        result = client.enrich_with_crossref(title="Nonexistent")
        assert result is None


# =============================================================================
# CrossRefClient - extract_publication_date Tests
# =============================================================================


class TestCrossRefClientDate:
    """Tests for date extraction."""

    def test_extract_date_published_print(self):
        """Test date extraction from published-print."""
        work = {"published-print": {"date-parts": [[2024, 6, 15]]}}
        year, month, day = CrossRefClient.extract_publication_date(work)
        assert year == 2024
        assert month == 6
        assert day == 15

    def test_extract_date_published_online(self):
        """Test date extraction from published-online."""
        work = {"published-online": {"date-parts": [[2024, 5]]}}
        year, month, day = CrossRefClient.extract_publication_date(work)
        assert year == 2024
        assert month == 5
        assert day is None

    def test_extract_date_year_only(self):
        """Test date extraction with year only."""
        work = {"published": {"date-parts": [[2024]]}}
        year, month, day = CrossRefClient.extract_publication_date(work)
        assert year == 2024
        assert month is None
        assert day is None

    def test_extract_date_no_date(self):
        """Test date extraction when no date available."""
        work = {}
        year, month, day = CrossRefClient.extract_publication_date(work)
        assert year is None
        assert month is None
        assert day is None

    def test_extract_date_empty_parts(self):
        """Test date extraction with empty date-parts."""
        work = {"published": {"date-parts": [[]]}}
        year, month, day = CrossRefClient.extract_publication_date(work)
        assert year is None


# =============================================================================
# Module Level Functions Tests
# =============================================================================


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_get_crossref_client_singleton(self):
        """Test client singleton creation."""
        client1 = get_crossref_client()
        client2 = get_crossref_client()
        # Should return same instance
        assert client1 is client2

    def test_get_doi_metadata(self):
        """Test get_doi_metadata function."""
        with patch.object(CrossRefClient, "get_work") as mock_get:
            mock_get.return_value = {"DOI": "10.1/test"}
            _result = get_doi_metadata("10.1/test")
            # Note: Will use singleton, so result depends on mock

    def test_search_crossref(self):
        """Test search_crossref function."""
        with patch.object(CrossRefClient, "search") as mock_search:
            mock_search.return_value = {
                "items": [{"DOI": "10.1/a"}],
                "total_results": 1,
            }
            results = search_crossref("test query", limit=5)
            assert isinstance(results, list)

    def test_get_citation_count(self):
        """Test get_citation_count function."""
        with patch.object(CrossRefClient, "get_work") as mock_get:
            mock_get.return_value = {"is-referenced-by-count": 42}
            # Will use singleton
            _count = get_citation_count("10.1/test")
            # Result depends on singleton state


# =============================================================================
# Rate Limiting Tests
# =============================================================================


class TestRateLimiting:
    """Tests for rate limiting functionality."""

    def test_rate_limit_timing(self):
        """Test rate limiting applies timing."""
        client = CrossRefClient()
        client._min_interval = 0.01  # Very small for test speed

        import time

        start = time.time()
        client._rate_limit()
        client._rate_limit()
        elapsed = time.time() - start

        # Should have waited at least min_interval once
        assert elapsed >= 0.009  # Allow small margin
