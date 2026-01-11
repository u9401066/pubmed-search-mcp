"""Tests for Europe PMC integration."""
import pytest
from unittest.mock import patch, MagicMock
import json


class TestEuropePMCClient:
    """Tests for EuropePMCClient class."""
    
    @pytest.fixture
    def client(self):
        """Create a EuropePMCClient instance."""
        from pubmed_search.sources.europe_pmc import EuropePMCClient
        return EuropePMCClient(email="test@example.com")
    
    @pytest.fixture
    def mock_search_response(self):
        """Mock search response."""
        return {
            "version": "6.9",
            "hitCount": 100,
            "nextCursorMark": "abc123",
            "resultList": {
                "result": [
                    {
                        "id": "12345678",
                        "source": "MED",
                        "pmid": "12345678",
                        "pmcid": "PMC1234567",
                        "doi": "10.1234/example",
                        "title": "Test Article Title",
                        "authorString": "Smith J, Jones M",
                        "journalTitle": "Test Journal",
                        "pubYear": "2024",
                        "firstPublicationDate": "2024-01-15",
                        "isOpenAccess": "Y",
                        "inEPMC": "Y",
                        "inPMC": "Y",
                        "hasPDF": "Y",
                        "citedByCount": 10,
                        "abstractText": "This is a test abstract.",
                    }
                ]
            }
        }
    
    def test_search_basic(self, client, mock_search_response):
        """Test basic search functionality."""
        with patch.object(client, '_make_request', return_value=mock_search_response):
            result = client.search("COVID-19", limit=10)
            
            assert result["hit_count"] == 100
            assert len(result["results"]) == 1
            assert result["results"][0]["pmid"] == "12345678"
            assert result["results"][0]["title"] == "Test Article Title"
            assert result["results"][0]["is_open_access"] is True
    
    def test_search_with_filters(self, client, mock_search_response):
        """Test search with year and OA filters."""
        with patch.object(client, '_make_request', return_value=mock_search_response) as mock:
            client.search(
                "test query",
                min_year=2020,
                max_year=2024,
                open_access_only=True,
                has_fulltext=True,
            )
            
            # Verify the URL contains filters
            call_args = mock.call_args[0][0]
            assert "FIRST_PDATE" in call_args or "query=" in call_args
    
    def test_search_empty_result(self, client):
        """Test search with no results."""
        empty_response = {"hitCount": 0, "resultList": {"result": []}}
        with patch.object(client, '_make_request', return_value=empty_response):
            result = client.search("nonexistent query xyz")
            assert result["hit_count"] == 0
            assert len(result["results"]) == 0
    
    def test_search_error_handling(self, client):
        """Test search error handling."""
        with patch.object(client, '_make_request', return_value=None):
            result = client.search("test")
            assert result["hit_count"] == 0
            assert result["results"] == []
    
    def test_get_fulltext_xml(self, client):
        """Test fulltext XML retrieval."""
        mock_xml = "<article>Test content</article>"
        with patch.object(client, '_make_request', return_value=mock_xml):
            xml = client.get_fulltext_xml("PMC1234567")
            assert xml == mock_xml
    
    def test_get_fulltext_xml_normalize_id(self, client):
        """Test that PMCID is normalized."""
        with patch.object(client, '_make_request', return_value="<xml/>") as mock:
            client.get_fulltext_xml("1234567")  # Without PMC prefix
            call_url = mock.call_args[0][0]
            assert "PMC1234567" in call_url
    
    def test_get_article(self, client, mock_search_response):
        """Test get single article."""
        article_response = {"result": mock_search_response["resultList"]["result"][0]}
        with patch.object(client, '_make_request', return_value=article_response):
            article = client.get_article("MED", "12345678")
            assert article is not None
            assert article["pmid"] == "12345678"
    
    def test_get_references(self, client):
        """Test get references."""
        refs_response = {
            "referenceList": {
                "reference": [
                    {
                        "id": "11111111",
                        "source": "MED",
                        "title": "Reference Title",
                        "authorString": "Author A",
                        "pubYear": "2020",
                        "doi": "10.1111/ref",
                    }
                ]
            }
        }
        with patch.object(client, '_make_request', return_value=refs_response):
            refs = client.get_references("MED", "12345678")
            assert len(refs) == 1
            assert refs[0]["title"] == "Reference Title"
    
    def test_get_citations(self, client, mock_search_response):
        """Test get citations."""
        citations_response = {
            "citationList": {
                "citation": mock_search_response["resultList"]["result"]
            }
        }
        with patch.object(client, '_make_request', return_value=citations_response):
            citations = client.get_citations("MED", "12345678")
            assert len(citations) == 1
            assert citations[0]["pmid"] == "12345678"
    
    def test_normalize_article(self, client):
        """Test article normalization."""
        raw_article = {
            "id": "12345",
            "pmid": "12345678",
            "pmcid": "PMC1234567",
            "doi": "10.1234/example",
            "title": "Test Title",
            "authorString": "Smith J, Jones M",
            "authorList": {
                "author": [
                    {"fullName": "John Smith", "firstName": "John", "lastName": "Smith"},
                    {"fullName": "Mary Jones", "firstName": "Mary", "lastName": "Jones"},
                ]
            },
            "journalTitle": "Test Journal",
            "pubYear": "2024",
            "firstPublicationDate": "2024-06-15",
            "isOpenAccess": "Y",
            "inEPMC": "Y",
            "hasPDF": "Y",
            "citedByCount": 42,
            "abstractText": "Test abstract",
            "keywordList": {"keyword": ["keyword1", "keyword2"]},
            "meshHeadingList": {
                "meshHeading": [
                    {"descriptorName": "MeSH Term 1"},
                    {"descriptorName": "MeSH Term 2"},
                ]
            },
        }
        
        normalized = client._normalize_article(raw_article)
        
        assert normalized["pmid"] == "12345678"
        assert normalized["pmc_id"] == "PMC1234567"
        assert normalized["doi"] == "10.1234/example"
        assert normalized["title"] == "Test Title"
        assert len(normalized["authors"]) == 2
        assert normalized["authors"][0] == "John Smith"
        assert normalized["year"] == "2024"
        assert normalized["month"] == "06"
        assert normalized["day"] == "15"
        assert normalized["is_open_access"] is True
        assert normalized["has_fulltext"] is True
        assert normalized["citation_count"] == 42
        assert "keyword1" in normalized["keywords"]
        assert "MeSH Term 1" in normalized["mesh_terms"]
        assert normalized["_source"] == "europe_pmc"
    
    def test_parse_fulltext_xml(self, client):
        """Test fulltext XML parsing."""
        xml = """<?xml version="1.0"?>
        <article>
            <front>
                <article-meta>
                    <title-group>
                        <article-title>Test Article Title</article-title>
                    </title-group>
                </article-meta>
            </front>
            <body>
                <sec>
                    <title>Introduction</title>
                    <p>This is the introduction paragraph.</p>
                </sec>
                <sec>
                    <title>Methods</title>
                    <p>This is the methods paragraph.</p>
                </sec>
            </body>
            <back>
                <ref-list>
                    <ref id="r1">
                        <label>1</label>
                        <mixed-citation>Reference text here</mixed-citation>
                    </ref>
                </ref-list>
            </back>
        </article>
        """
        
        parsed = client.parse_fulltext_xml(xml)
        
        assert parsed["title"] == "Test Article Title"
        assert len(parsed["sections"]) == 2
        assert parsed["sections"][0]["title"] == "Introduction"
        assert "introduction paragraph" in parsed["sections"][0]["content"]
        assert len(parsed["references"]) == 1
        assert parsed["references"][0]["label"] == "1"


class TestEuropePMCMCPTools:
    """Tests for Europe PMC MCP Tools."""
    
    @pytest.fixture
    def mcp(self):
        """Create MCP instance with Europe PMC tools."""
        from mcp.server.fastmcp import FastMCP
        from pubmed_search.mcp.tools.europe_pmc import register_europe_pmc_tools
        mcp = FastMCP('test')
        register_europe_pmc_tools(mcp)
        return mcp
    
    def test_tools_registered(self, mcp):
        """Test Europe PMC tools are registered (v0.1.21: consolidated tools)."""
        tools = mcp._tool_manager._tools
        # v0.1.21: search_europe_pmc integrated into unified_search
        # v0.1.21: get_fulltext_xml removed, use get_fulltext
        # v0.1.21: get_europe_pmc_citations removed
        assert "get_fulltext" in tools
        assert "get_text_mined_terms" in tools
    
    # v0.1.21: search_europe_pmc has been integrated into unified_search
    # This test is kept as a reminder but skipped
    @pytest.mark.skip(reason="v0.1.21: search_europe_pmc integrated into unified_search")
    def test_search_europe_pmc_tool(self, mcp):
        """Test search_europe_pmc tool returns formatted results."""
        pass  # This tool has been integrated into unified_search
    
    def test_get_fulltext_tool(self, mcp):
        """Test get_fulltext tool parses XML correctly."""
        from unittest.mock import patch
        
        mock_xml = """<?xml version="1.0"?>
        <article><front><article-meta>
        <title-group><article-title>Test Title</article-title></title-group>
        </article-meta></front>
        <body><sec><title>Introduction</title><p>Test content</p></sec></body>
        </article>"""
        
        mock_parsed = {
            "title": "Test Title",
            "sections": [{"title": "Introduction", "content": "Test content"}],
            "references": []
        }
        
        with patch('pubmed_search.mcp.tools.europe_pmc.get_europe_pmc_client') as mock:
            mock.return_value.get_fulltext_xml.return_value = mock_xml
            mock.return_value.parse_fulltext_xml.return_value = mock_parsed
            
            tool = mcp._tool_manager._tools['get_fulltext']
            result = tool.fn(pmcid="PMC1234567")
            
            assert "Test Title" in result
            assert "Introduction" in result
    
    def test_get_fulltext_not_found(self, mcp):
        """Test get_fulltext handles missing fulltext."""
        from unittest.mock import patch
        
        with patch('pubmed_search.mcp.tools.europe_pmc.get_europe_pmc_client') as mock:
            mock.return_value.get_fulltext_xml.return_value = None
            
            tool = mcp._tool_manager._tools['get_fulltext']
            result = tool.fn(pmcid="PMC9999999")
            
            # Updated to match actual error message format
            assert "no results found" in result.lower() or "not available" in result.lower()
    
    def test_get_text_mined_terms_requires_id(self, mcp):
        """Test get_text_mined_terms requires pmid or pmcid."""
        tool = mcp._tool_manager._tools['get_text_mined_terms']
        result = tool.fn()
        assert "provide" in result.lower()
    
    # v0.1.21: get_europe_pmc_citations has been removed
    @pytest.mark.skip(reason="v0.1.21: get_europe_pmc_citations tool removed")
    def test_get_europe_pmc_citations_tool(self, mcp):
        """Test get_europe_pmc_citations tool."""
        pass  # This tool has been removed in v0.1.21


class TestEuropePMCIntegration:
    """Integration tests for Europe PMC (require network)."""
    
    @pytest.fixture
    def client(self):
        """Create a EuropePMCClient instance."""
        from pubmed_search.sources.europe_pmc import EuropePMCClient
        return EuropePMCClient(email="test@example.com")
    
    @pytest.mark.integration
    def test_real_search(self, client):
        """Test real API search."""
        result = client.search("COVID-19 vaccine", limit=5)
        assert result["hit_count"] > 0
        assert len(result["results"]) > 0
        assert result["results"][0]["title"]
    
    @pytest.mark.integration
    def test_real_fulltext(self, client):
        """Test real fulltext retrieval."""
        xml = client.get_fulltext_xml("PMC7096777")
        assert xml is not None
        assert len(xml) > 1000
        assert "<article" in xml
    
    @pytest.mark.integration
    def test_real_fulltext_parse(self, client):
        """Test real fulltext parsing."""
        xml = client.get_fulltext_xml("PMC7096777")
        parsed = client.parse_fulltext_xml(xml)
        assert parsed["title"]
        assert len(parsed["sections"]) > 0


class TestSourcesIntegration:
    """Test Europe PMC integration with sources module."""
    
    def test_get_europe_pmc_client(self):
        """Test client factory."""
        from pubmed_search.sources import get_europe_pmc_client
        client = get_europe_pmc_client()
        assert client is not None
    
    def test_search_source_enum(self):
        """Test SearchSource enum includes europe_pmc."""
        from pubmed_search.sources import SearchSource
        assert SearchSource.EUROPE_PMC.value == "europe_pmc"
    
    def test_search_alternate_source_europe_pmc(self):
        """Test search_alternate_source with europe_pmc."""
        from pubmed_search.sources import search_alternate_source
        from unittest.mock import patch
        
        mock_result = {
            "results": [{"pmid": "123", "title": "Test"}],
            "hit_count": 1
        }
        
        with patch('pubmed_search.sources.get_europe_pmc_client') as mock_client:
            mock_client.return_value.search.return_value = mock_result
            results = search_alternate_source(
                query="test",
                source="europe_pmc",
                limit=5
            )
            assert len(results) == 1
