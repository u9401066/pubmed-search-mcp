"""Comprehensive tests for PreprintSearcher, ArXivClient, MedBioRxivClient."""

from unittest.mock import MagicMock, patch


from pubmed_search.infrastructure.sources.preprints import (
    PreprintArticle,
    ArXivClient,
    MedBioRxivClient,
    PreprintSearcher,
)


# ============================================================
# PreprintArticle (extended)
# ============================================================

class TestPreprintArticleExtended:
    def test_to_dict_complete(self):
        article = PreprintArticle(
            id="2301.00001",
            title="Test Paper",
            abstract="Short abstract",
            authors=["John Doe", "Jane Smith"],
            published="2023-01-15",
            updated="2023-02-01",
            source="arxiv",
            categories=["cs.AI", "q-bio"],
            pdf_url="https://arxiv.org/pdf/2301.00001.pdf",
            doi="10.48550/arXiv.2301.00001",
        )
        d = article.to_dict()
        assert d["id"] == "2301.00001"
        assert d["title"] == "Test Paper"
        assert d["source"] == "arxiv"
        assert d["doi"] == "10.48550/arXiv.2301.00001"
        assert "arxiv.org/abs/2301.00001" in d["source_url"]

    def test_to_dict_long_abstract_truncated(self):
        article = PreprintArticle(
            id="1", title="T", abstract="A" * 600,
            authors=[], published="2023-01-01", updated=None,
            source="arxiv", categories=[], pdf_url=None, doi=None,
        )
        d = article.to_dict()
        assert len(d["abstract"]) == 503

    def test_source_url_medrxiv(self):
        article = PreprintArticle(
            id="1", title="T", abstract="A",
            authors=[], published="2023-01-01", updated=None,
            source="medrxiv", categories=[], pdf_url=None,
            doi="10.1101/2023.01.01.123456",
        )
        assert "medrxiv.org" in article._get_source_url()

    def test_source_url_biorxiv(self):
        article = PreprintArticle(
            id="1", title="T", abstract="A",
            authors=[], published="2023-01-01", updated=None,
            source="biorxiv", categories=[], pdf_url=None,
            doi="10.1101/2023.01.01.999999",
        )
        assert "biorxiv.org" in article._get_source_url()

    def test_source_url_no_doi(self):
        article = PreprintArticle(
            id="1", title="T", abstract="A",
            authors=[], published="", updated=None,
            source="medrxiv", categories=[], pdf_url=None, doi=None,
        )
        assert article._get_source_url() == ""

    def test_source_url_unknown_source(self):
        article = PreprintArticle(
            id="1", title="T", abstract="A",
            authors=[], published="", updated=None,
            source="unknown", categories=[], pdf_url=None, doi=None,
        )
        assert article._get_source_url() == ""


# ============================================================
# ArXivClient (extended)
# ============================================================

class TestArXivClientExtended:
    @patch("httpx.Client")
    def test_search_with_atom_response(self, MockClient):
        mock_client = MagicMock()
        MockClient.return_value = mock_client

        xml_response = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom"
              xmlns:arxiv="http://arxiv.org/schemas/atom">
            <entry>
                <id>http://arxiv.org/abs/2301.00001v1</id>
                <title>Test Paper Title</title>
                <summary>Test abstract content</summary>
                <author><name>John Doe</name></author>
                <author><name>Jane Smith</name></author>
                <published>2023-01-15T00:00:00Z</published>
                <updated>2023-01-20T00:00:00Z</updated>
                <category term="cs.AI"/>
                <link title="pdf" href="https://arxiv.org/pdf/2301.00001v1"/>
                <arxiv:doi>10.48550/arXiv.2301.00001</arxiv:doi>
            </entry>
        </feed>"""

        mock_response = MagicMock()
        mock_response.text = xml_response
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        client = ArXivClient()
        client._client = mock_client
        results = client.search("deep learning", limit=10)

        assert len(results) == 1
        assert results[0].title == "Test Paper Title"
        assert results[0].source == "arxiv"
        assert len(results[0].authors) == 2
        assert results[0].doi == "10.48550/arXiv.2301.00001"

    @patch("httpx.Client")
    def test_search_empty_result(self, MockClient):
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        client = ArXivClient()
        client._client = mock_client
        results = client.search("nonexistent topic xyz")
        assert results == []

    @patch("httpx.Client")
    def test_search_exception(self, MockClient):
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        mock_client.get.side_effect = Exception("network error")

        client = ArXivClient()
        client._client = mock_client
        results = client.search("test")
        assert results == []

    @patch("httpx.Client")
    def test_get_by_id(self, MockClient):
        mock_client = MagicMock()
        MockClient.return_value = mock_client

        xml_response = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
            <entry>
                <id>http://arxiv.org/abs/2301.00001v1</id>
                <title>Found Paper</title>
                <summary>Abstract</summary>
                <published>2023-01-15T00:00:00Z</published>
            </entry>
        </feed>"""

        mock_response = MagicMock()
        mock_response.text = xml_response
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        client = ArXivClient()
        client._client = mock_client
        result = client.get_by_id("2301.00001")
        assert result is not None
        assert result.title == "Found Paper"

    @patch("httpx.Client")
    def test_get_by_id_not_found(self, MockClient):
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        client = ArXivClient()
        client._client = mock_client
        assert client.get_by_id("9999.99999") is None

    @patch("httpx.Client")
    def test_get_by_id_error(self, MockClient):
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        mock_client.get.side_effect = Exception("error")

        client = ArXivClient()
        client._client = mock_client
        assert client.get_by_id("2301.00001") is None


# ============================================================
# MedBioRxivClient (extended)
# ============================================================

class TestMedBioRxivClientExtended:
    @patch("httpx.Client")
    def test_search_medrxiv_success(self, MockClient):
        mock_client = MagicMock()
        MockClient.return_value = mock_client

        mock_response = MagicMock()
        mock_response.json.return_value = {"collection": [
            {
                "doi": "10.1101/2023.01.01.123456",
                "title": "COVID-19 Treatment Study",
                "abstract": "A study about COVID-19 treatment options",
                "authors": "Smith J; Doe A",
                "date": "2023-01-15",
                "category": "infectious diseases",
            },
        ]}
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        client = MedBioRxivClient()
        client._client = mock_client
        results = client.search_medrxiv("COVID-19 treatment")

        assert len(results) == 1
        assert results[0].source == "medrxiv"

    @patch("httpx.Client")
    def test_search_biorxiv_success(self, MockClient):
        mock_client = MagicMock()
        MockClient.return_value = mock_client

        mock_response = MagicMock()
        mock_response.json.return_value = {"collection": [
            {
                "doi": "10.1101/2023.02.01.999",
                "title": "CRISPR gene editing advances",
                "abstract": "CRISPR gene editing study",
                "authors": "Lee K",
                "date": "2023-02-01",
                "category": "molecular biology",
            },
        ]}
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        client = MedBioRxivClient()
        client._client = mock_client
        results = client.search_biorxiv("CRISPR gene editing")

        assert len(results) == 1
        assert results[0].source == "biorxiv"

    @patch("httpx.Client")
    def test_filter_by_query_terms(self, MockClient):
        mock_client = MagicMock()
        MockClient.return_value = mock_client

        mock_response = MagicMock()
        mock_response.json.return_value = {"collection": [
            {"doi": "1", "title": "COVID Treatment", "abstract": "Treatment study",
             "authors": "A", "date": "2023-01-01", "category": ""},
            {"doi": "2", "title": "Cancer Research", "abstract": "Oncology study",
             "authors": "B", "date": "2023-01-01", "category": ""},
        ]}
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        client = MedBioRxivClient()
        client._client = mock_client
        results = client.search_medrxiv("COVID")
        assert len(results) == 1

    @patch("httpx.Client")
    def test_search_error(self, MockClient):
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        mock_client.get.side_effect = Exception("network error")

        client = MedBioRxivClient()
        client._client = mock_client
        results = client.search_medrxiv("test")
        assert results == []

    @patch("httpx.Client")
    def test_limit_applied(self, MockClient):
        mock_client = MagicMock()
        MockClient.return_value = mock_client

        articles = [
            {"doi": f"doi{i}", "title": f"Study {i} about test",
             "abstract": f"Test abstract {i}",
             "authors": "A", "date": "2023-01-01", "category": ""}
            for i in range(20)
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = {"collection": articles}
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        client = MedBioRxivClient()
        client._client = mock_client
        results = client.search_medrxiv("test", limit=5)
        assert len(results) <= 5


# ============================================================
# PreprintSearcher (extended)
# ============================================================

class TestPreprintSearcherExtended:
    @patch.object(ArXivClient, "search")
    @patch.object(MedBioRxivClient, "search_medrxiv")
    @patch.object(MedBioRxivClient, "search_biorxiv")
    def test_search_all_sources(self, mock_bio, mock_med, mock_arxiv):
        mock_arxiv.return_value = [
            PreprintArticle(id="1", title="arXiv paper", abstract="",
                            authors=[], published="", updated=None,
                            source="arxiv", categories=[], pdf_url=None, doi=None),
        ]
        mock_med.return_value = [
            PreprintArticle(id="2", title="medRxiv paper", abstract="",
                            authors=[], published="", updated=None,
                            source="medrxiv", categories=[], pdf_url=None, doi=None),
        ]
        mock_bio.return_value = []

        searcher = PreprintSearcher()
        result = searcher.search("deep learning")
        assert result["total"] == 2
        assert "arxiv" in result["by_source"]
        assert "medrxiv" in result["by_source"]
        assert "biorxiv" in result["by_source"]

    @patch.object(ArXivClient, "search")
    def test_search_specific_sources(self, mock_arxiv):
        mock_arxiv.return_value = []
        searcher = PreprintSearcher()
        result = searcher.search("test", sources=["arxiv"])
        assert "arxiv" in result["by_source"]
        assert "medrxiv" not in result["by_source"]

    @patch.object(MedBioRxivClient, "search_medrxiv")
    @patch.object(ArXivClient, "search")
    def test_search_medical_preprints(self, mock_arxiv, mock_med):
        mock_arxiv.return_value = []
        mock_med.return_value = []
        searcher = PreprintSearcher()
        result = searcher.search_medical_preprints("COVID-19")
        assert result["total"] == 0

    @patch.object(ArXivClient, "get_by_id")
    def test_get_arxiv_paper_found(self, mock_get):
        mock_get.return_value = PreprintArticle(
            id="2301.00001", title="Found", abstract="",
            authors=[], published="", updated=None,
            source="arxiv", categories=[], pdf_url=None, doi=None,
        )
        searcher = PreprintSearcher()
        result = searcher.get_arxiv_paper("2301.00001")
        assert result["title"] == "Found"

    @patch.object(ArXivClient, "get_by_id")
    def test_get_arxiv_paper_not_found(self, mock_get):
        mock_get.return_value = None
        searcher = PreprintSearcher()
        assert searcher.get_arxiv_paper("9999.99999") is None
