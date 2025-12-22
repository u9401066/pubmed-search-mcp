"""
Europe PMC Integration

Provides access to Europe PMC's RESTful API for literature search and full text retrieval.
This is an internal module - not exposed as separate MCP tools.

API Documentation: https://europepmc.org/RestfulWebService

Features:
- 33+ million publications from PubMed, Agricola, EPO, NICE, etc.
- 6.5 million open access full text articles
- Full text XML retrieval (unique feature!)
- Citations and references network
- Text-mined annotations (genes, diseases, chemicals)
- No API key required
"""

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

# Europe PMC API endpoints
EPMC_API_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
EPMC_SEARCH_URL = f"{EPMC_API_BASE}/search"
EPMC_ARTICLE_URL = f"{EPMC_API_BASE}/article"

# Default email for contact
DEFAULT_EMAIL = "pubmed-search-mcp@example.com"


class EuropePMCClient:
    """
    Europe PMC API client.
    
    Usage:
        client = EuropePMCClient(email="your@email.com")
        results = client.search("CRISPR gene editing", limit=10)
        
        # Get full text XML (unique feature!)
        fulltext = client.get_fulltext_xml("PMC7096777")
    """
    
    def __init__(self, email: str | None = None, timeout: float = 30.0):
        """
        Initialize client.
        
        Args:
            email: Contact email (for good citizenship)
            timeout: Request timeout in seconds
        """
        self._email = email or DEFAULT_EMAIL
        self._timeout = timeout
        self._last_request_time = 0
        self._min_interval = 0.1  # Europe PMC is generous with rate limits
    
    def _rate_limit(self):
        """Simple rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()
    
    def _make_request(self, url: str, expect_xml: bool = False) -> dict | str | None:
        """Make HTTP GET request."""
        self._rate_limit()
        
        request = urllib.request.Request(url)
        request.add_header("User-Agent", f"pubmed-search-mcp/1.0 (mailto:{self._email})")
        
        if not expect_xml:
            request.add_header("Accept", "application/json")
        
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                content = response.read().decode("utf-8")
                if expect_xml:
                    return content
                return json.loads(content)
        except urllib.error.HTTPError as e:
            logger.error(f"HTTP error {e.code}: {e.reason}")
            return None
        except urllib.error.URLError as e:
            logger.error(f"URL error: {e.reason}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return None
    
    def search(
        self,
        query: str,
        limit: int = 10,
        result_type: str = "lite",
        min_year: int | None = None,
        max_year: int | None = None,
        open_access_only: bool = False,
        has_fulltext: bool = False,
        sort: str | None = None,
        cursor_mark: str = "*",
    ) -> dict[str, Any]:
        """
        Search Europe PMC publications.
        
        Args:
            query: Search query (supports Europe PMC search syntax)
            limit: Maximum results (max 1000 per request)
            result_type: "idlist", "lite" (default), or "core"
            min_year: Minimum publication year
            max_year: Maximum publication year
            open_access_only: Only return open access articles
            has_fulltext: Only return articles with full text
            sort: Sort order (e.g., "CITED desc", "P_PDATE_D desc")
            cursor_mark: Cursor for pagination (use nextCursorMark from response)
            
        Returns:
            Dict with results and pagination info
        """
        try:
            # Build query with filters
            query_parts = [query]
            
            if min_year:
                query_parts.append(f"FIRST_PDATE:[{min_year}-01-01 TO *]")
            if max_year:
                query_parts.append(f"FIRST_PDATE:[* TO {max_year}-12-31]")
            if open_access_only:
                query_parts.append("OPEN_ACCESS:y")
            if has_fulltext:
                query_parts.append("HAS_FT:y")
            
            full_query = " AND ".join(query_parts) if len(query_parts) > 1 else query
            
            params = {
                "query": full_query,
                "resultType": result_type,
                "pageSize": str(min(limit, 1000)),
                "format": "json",
                "cursorMark": cursor_mark,
            }
            
            if sort:
                params["sort"] = sort
            
            url = f"{EPMC_SEARCH_URL}?{urllib.parse.urlencode(params)}"
            data = self._make_request(url)
            
            if not data:
                return {"results": [], "hit_count": 0}
            
            results = data.get("resultList", {}).get("result", [])
            
            return {
                "results": [self._normalize_article(r) for r in results],
                "hit_count": data.get("hitCount", 0),
                "next_cursor": data.get("nextCursorMark"),
                "next_page_url": data.get("nextPageUrl"),
            }
            
        except Exception as e:
            logger.error(f"Europe PMC search failed: {e}")
            return {"results": [], "hit_count": 0}
    
    def get_article(
        self,
        source: str,
        article_id: str,
        result_type: str = "core",
    ) -> dict[str, Any] | None:
        """
        Get article details by source and ID.
        
        Args:
            source: Source database (e.g., "MED" for PubMed, "PMC" for PMC)
            article_id: Article identifier (PMID or PMCID)
            result_type: "lite" or "core" (with abstract, MeSH, etc.)
            
        Returns:
            Article dictionary or None
        """
        try:
            params = {
                "resultType": result_type,
                "format": "json",
            }
            
            url = f"{EPMC_ARTICLE_URL}/{source}/{article_id}?{urllib.parse.urlencode(params)}"
            data = self._make_request(url)
            
            if not data:
                return None
            
            result = data.get("result")
            if result:
                return self._normalize_article(result)
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get article {source}/{article_id}: {e}")
            return None
    
    def get_fulltext_xml(self, pmcid: str) -> str | None:
        """
        Get full text XML for an Open Access article.
        
        This is the UNIQUE feature of Europe PMC - direct full text access!
        
        Args:
            pmcid: PMC ID (e.g., "PMC7096777" or just "7096777")
            
        Returns:
            Full text XML string or None
        """
        try:
            # Normalize PMCID
            if not pmcid.upper().startswith("PMC"):
                pmcid = f"PMC{pmcid}"
            
            url = f"{EPMC_API_BASE}/{pmcid}/fullTextXML"
            return self._make_request(url, expect_xml=True)
            
        except Exception as e:
            logger.error(f"Failed to get fulltext for {pmcid}: {e}")
            return None
    
    def get_references(
        self,
        source: str,
        article_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get references cited by an article.
        
        Args:
            source: Source database ("MED", "PMC", etc.)
            article_id: Article identifier
            limit: Maximum references to return
            
        Returns:
            List of reference dictionaries
        """
        try:
            params = {
                "format": "json",
                "pageSize": str(min(limit, 1000)),
            }
            
            url = f"{EPMC_API_BASE}/{source}/{article_id}/references?{urllib.parse.urlencode(params)}"
            data = self._make_request(url)
            
            if not data:
                return []
            
            refs = data.get("referenceList", {}).get("reference", [])
            return [self._normalize_reference(r) for r in refs]
            
        except Exception as e:
            logger.error(f"Failed to get references for {source}/{article_id}: {e}")
            return []
    
    def get_citations(
        self,
        source: str,
        article_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get articles that cite this article.
        
        Args:
            source: Source database ("MED", "PMC", etc.)
            article_id: Article identifier
            limit: Maximum citations to return
            
        Returns:
            List of citing article dictionaries
        """
        try:
            params = {
                "format": "json",
                "pageSize": str(min(limit, 1000)),
            }
            
            url = f"{EPMC_API_BASE}/{source}/{article_id}/citations?{urllib.parse.urlencode(params)}"
            data = self._make_request(url)
            
            if not data:
                return []
            
            citations = data.get("citationList", {}).get("citation", [])
            return [self._normalize_article(c) for c in citations]
            
        except Exception as e:
            logger.error(f"Failed to get citations for {source}/{article_id}: {e}")
            return []
    
    def get_text_mined_terms(
        self,
        source: str,
        article_id: str,
        semantic_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get text-mined terms (genes, diseases, chemicals, etc.).
        
        Args:
            source: Source database
            article_id: Article identifier
            semantic_type: Filter by type (e.g., "GENE_PROTEIN", "DISEASE", "CHEMICAL")
            
        Returns:
            List of text-mined term dictionaries
        """
        try:
            params = {"format": "json"}
            if semantic_type:
                params["semanticType"] = semantic_type
            
            url = f"{EPMC_API_BASE}/{source}/{article_id}/textMinedTerms?{urllib.parse.urlencode(params)}"
            data = self._make_request(url)
            
            if not data:
                return []
            
            return data.get("semanticTypeList", {}).get("semanticType", [])
            
        except Exception as e:
            logger.error(f"Failed to get text-mined terms for {source}/{article_id}: {e}")
            return []
    
    def _normalize_article(self, article: dict[str, Any]) -> dict[str, Any]:
        """
        Normalize Europe PMC article to common format compatible with PubMed results.
        """
        # Extract IDs
        pmid = article.get("pmid", "")
        pmcid = article.get("pmcid", "")
        doi = article.get("doi", "")
        
        # Extract authors
        author_string = article.get("authorString", "")
        author_list = article.get("authorList", {}).get("author", [])
        
        authors = []
        authors_full = []
        for auth in author_list:
            full_name = auth.get("fullName", "")
            if full_name:
                authors.append(full_name)
                authors_full.append({
                    "fore_name": auth.get("firstName", ""),
                    "last_name": auth.get("lastName", ""),
                    "initials": auth.get("initials", ""),
                })
        
        if not authors and author_string:
            authors = [a.strip() for a in author_string.split(",")]
        
        # Extract date
        pub_year = article.get("pubYear", "")
        first_pub_date = article.get("firstPublicationDate", "")
        
        year = pub_year or (first_pub_date[:4] if first_pub_date else "")
        month = first_pub_date[5:7] if len(first_pub_date) >= 7 else ""
        day = first_pub_date[8:10] if len(first_pub_date) >= 10 else ""
        
        # Extract journal info
        journal = article.get("journalTitle", "") or article.get("journalInfo", {}).get("journal", {}).get("title", "")
        journal_abbrev = article.get("journalInfo", {}).get("journal", {}).get("isoabbreviation", "")
        
        # Extract keywords and MeSH
        keywords = []
        keyword_list = article.get("keywordList", {}).get("keyword", [])
        if isinstance(keyword_list, list):
            keywords = keyword_list
        
        mesh_terms = []
        mesh_list = article.get("meshHeadingList", {}).get("meshHeading", [])
        for mesh in mesh_list:
            descriptor = mesh.get("descriptorName", "")
            if descriptor:
                mesh_terms.append(descriptor)
        
        # Open access info
        is_oa = article.get("isOpenAccess", "N") == "Y"
        has_fulltext = article.get("inEPMC", "N") == "Y" or article.get("inPMC", "N") == "Y"
        has_pdf = article.get("hasPDF", "N") == "Y"
        
        return {
            # Core fields - matching PubMed format
            "pmid": pmid,
            "title": article.get("title", ""),
            "abstract": article.get("abstractText", ""),
            "year": year,
            "month": month,
            "day": day,
            "authors": authors,
            "authors_full": authors_full,
            "journal": journal,
            "journal_abbrev": journal_abbrev,
            "volume": article.get("journalVolume", ""),
            "issue": article.get("issue", ""),
            "pages": article.get("pageInfo", ""),
            "doi": doi,
            "pmc_id": pmcid,
            "keywords": keywords,
            "mesh_terms": mesh_terms,
            
            # Metrics
            "citation_count": article.get("citedByCount", 0),
            
            # Access
            "is_open_access": is_oa,
            "has_fulltext": has_fulltext,
            "has_pdf": has_pdf,
            
            # Europe PMC specific
            "source": article.get("source", ""),  # MED, PMC, etc.
            "pub_type": article.get("pubType", ""),
            
            # Source marker
            "_source": "europe_pmc",
            "_epmc_id": article.get("id", ""),
        }
    
    def _normalize_reference(self, ref: dict[str, Any]) -> dict[str, Any]:
        """Normalize reference to common format."""
        return {
            "pmid": ref.get("id", "") if ref.get("source") == "MED" else "",
            "title": ref.get("title", ""),
            "authors": ref.get("authorString", ""),
            "journal": ref.get("journalAbbreviation", ""),
            "year": ref.get("pubYear", ""),
            "volume": ref.get("volume", ""),
            "issue": ref.get("issue", ""),
            "pages": ref.get("pageInfo", ""),
            "doi": ref.get("doi", ""),
            "source": ref.get("source", ""),
            "match": ref.get("match", ""),  # Y/N if matched to Europe PMC record
        }
    
    def parse_fulltext_xml(self, xml_content: str) -> dict[str, Any]:
        """
        Parse JATS XML full text into structured sections.
        
        Args:
            xml_content: Full text XML string
            
        Returns:
            Dict with structured content (title, abstract, sections, references)
        """
        try:
            # Remove XML declaration and DOCTYPE
            xml_content = re.sub(r'<\?xml[^>]*\?>', '', xml_content)
            xml_content = re.sub(r'<!DOCTYPE[^>]*>', '', xml_content)
            
            root = ElementTree.fromstring(xml_content)
            
            # Define namespace handling
            ns = {
                'xlink': 'http://www.w3.org/1999/xlink',
                'mml': 'http://www.w3.org/1998/Math/MathML',
            }
            
            result = {
                "title": "",
                "abstract": "",
                "sections": [],
                "references": [],
            }
            
            # Extract title
            title_elem = root.find(".//article-title")
            if title_elem is not None:
                result["title"] = self._get_text(title_elem)
            
            # Extract abstract
            abstract_elem = root.find(".//abstract")
            if abstract_elem is not None:
                result["abstract"] = self._get_text(abstract_elem)
            
            # Extract body sections
            body = root.find(".//body")
            if body is not None:
                for sec in body.findall(".//sec"):
                    section = self._parse_section(sec)
                    if section:
                        result["sections"].append(section)
            
            # Extract references
            ref_list = root.find(".//ref-list")
            if ref_list is not None:
                for ref in ref_list.findall(".//ref"):
                    ref_data = self._parse_reference(ref)
                    if ref_data:
                        result["references"].append(ref_data)
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to parse fulltext XML: {e}")
            return {"error": str(e)}
    
    def _get_text(self, elem) -> str:
        """Recursively get all text from an element."""
        text = elem.text or ""
        for child in elem:
            text += self._get_text(child)
            if child.tail:
                text += child.tail
        return text.strip()
    
    def _parse_section(self, sec_elem) -> dict[str, Any] | None:
        """Parse a section element."""
        title_elem = sec_elem.find("title")
        title = self._get_text(title_elem) if title_elem is not None else ""
        
        # Get paragraphs
        paragraphs = []
        for p in sec_elem.findall("p"):
            text = self._get_text(p)
            if text:
                paragraphs.append(text)
        
        if not title and not paragraphs:
            return None
        
        return {
            "title": title,
            "content": "\n\n".join(paragraphs),
        }
    
    def _parse_reference(self, ref_elem) -> dict[str, Any] | None:
        """Parse a reference element."""
        label = ref_elem.find("label")
        mixed_citation = ref_elem.find(".//mixed-citation")
        
        if mixed_citation is None:
            return None
        
        return {
            "label": self._get_text(label) if label is not None else "",
            "text": self._get_text(mixed_citation),
            "pmid": mixed_citation.findtext(".//pub-id[@pub-id-type='pmid']", ""),
            "doi": mixed_citation.findtext(".//pub-id[@pub-id-type='doi']", ""),
        }
    
    def close(self):
        """Close resources (no-op for urllib, but keeps interface consistent)."""
        pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()


# Convenience functions
def search_europe_pmc(
    query: str,
    limit: int = 10,
    open_access_only: bool = False,
    has_fulltext: bool = False,
    email: str | None = None,
) -> list[dict[str, Any]]:
    """
    Quick search function for Europe PMC.
    
    Args:
        query: Search query
        limit: Maximum results
        open_access_only: Only OA articles
        has_fulltext: Only articles with full text
        email: Contact email
        
    Returns:
        List of article dictionaries
    """
    client = EuropePMCClient(email=email)
    result = client.search(
        query=query,
        limit=limit,
        open_access_only=open_access_only,
        has_fulltext=has_fulltext,
    )
    return result.get("results", [])


def get_fulltext(pmcid: str, email: str | None = None) -> str | None:
    """
    Quick function to get full text XML.
    
    Args:
        pmcid: PMC ID
        email: Contact email
        
    Returns:
        Full text XML string or None
    """
    client = EuropePMCClient(email=email)
    return client.get_fulltext_xml(pmcid)
