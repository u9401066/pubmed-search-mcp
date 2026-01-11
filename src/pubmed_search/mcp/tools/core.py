"""
CORE API MCP Tools

Provides MCP tools for searching CORE's 200M+ open access research papers.
CORE aggregates content from thousands of institutional repositories worldwide.

Features:
- Fulltext search across 42M+ papers
- Open access focused
- DOI/PMID lookup
- Direct access to full text content
"""

import json
import logging
from typing import Any, Union

from mcp.server import Server

from ._common import InputNormalizer, ResponseFormatter

logger = logging.getLogger(__name__)


def register_core_tools(mcp: Server) -> None:
    """Register CORE API tools with MCP server."""
    
    @mcp.tool()
    async def search_core(
        query: str,
        limit: Union[int, str] = 10,
        year_from: Union[int, str, None] = None,
        year_to: Union[int, str, None] = None,
        has_fulltext: Union[bool, str] = False,
    ) -> str:
        """
        Search CORE's 200M+ open access research papers.
        
        CORE aggregates open access content from institutional repositories,
        making it ideal for finding open access versions of papers.
        
        ═══════════════════════════════════════════════════════════════
        WHEN TO USE THIS TOOL:
        ═══════════════════════════════════════════════════════════════
        - Finding open access papers
        - Searching for preprints and institutional repository content
        - Looking for papers with full text available
        - Cross-referencing with PubMed results for open versions
        
        ═══════════════════════════════════════════════════════════════
        QUERY SYNTAX:
        ═══════════════════════════════════════════════════════════════
        - title:"machine learning"    → Search in title
        - authors:"John Smith"        → Search by author
        - doi:"10.1234/example"      → Find by DOI
        - fullText:"neural network"  → Search in full text content
        
        Args:
            query: Search query (supports field-specific syntax)
            limit: Maximum results (1-100)
            year_from: Minimum publication year
            year_to: Maximum publication year
            has_fulltext: Only return papers with full text
            
        Returns:
            JSON with total_hits and list of papers
        """
        # Normalize inputs
        query = InputNormalizer.normalize_query(query)
        if not query:
            return ResponseFormatter.error(
                "Empty query",
                suggestion="Provide a search query",
                example='search_core(query="machine learning healthcare")',
                tool_name="search_core"
            )
        
        limit = InputNormalizer.normalize_limit(limit, default=10, max_val=100)
        year_from = InputNormalizer.normalize_year(year_from)
        year_to = InputNormalizer.normalize_year(year_to)
        has_fulltext = InputNormalizer.normalize_bool(has_fulltext, default=False)
        
        try:
            from ..sources.core import get_core_client
            
            client = get_core_client()
            result = client.search(
                query=query,
                limit=limit,
                year_from=year_from,
                year_to=year_to,
                has_fulltext=has_fulltext,
            )
            
            papers = result.get("results", [])
            if not papers:
                return ResponseFormatter.no_results(
                    query=query,
                    suggestions=[
                        "Try broader search terms",
                        "Remove year filters",
                        "Use fullText: prefix for content search"
                    ],
                    alternative_tools=["search_europe_pmc", "search_literature"]
                )
            
            return json.dumps({
                "total_hits": result.get("total_hits", 0),
                "papers": papers,
                "note": "Use get_core_fulltext with core_id to retrieve full text"
            }, indent=2, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"CORE search failed: {e}")
            return ResponseFormatter.error(
                e,
                suggestion="Check if CORE API is available",
                tool_name="search_core"
            )
    
    @mcp.tool()
    async def search_core_fulltext(
        query: str,
        limit: Union[int, str] = 10,
        year_from: Union[int, str, None] = None,
        year_to: Union[int, str, None] = None,
    ) -> str:
        """
        Search within full text content in CORE.
        
        Unlike title/abstract search, this searches the actual content
        of papers - useful for finding specific discussions, methods,
        or cited passages.
        
        ═══════════════════════════════════════════════════════════════
        USE CASES:
        ═══════════════════════════════════════════════════════════════
        - Find papers that discuss specific techniques
        - Locate papers that mention specific drugs/genes/diseases
        - Search for specific methodology descriptions
        - Find papers that cite specific concepts in their text
        
        Args:
            query: Text to search for in paper content
            limit: Maximum results (1-100)
            year_from: Minimum publication year
            year_to: Maximum publication year
            
        Returns:
            JSON with papers containing the search terms in their full text
        """
        # Normalize inputs
        query = InputNormalizer.normalize_query(query)
        if not query:
            return ResponseFormatter.error(
                "Empty query",
                suggestion="Provide a search query for fulltext search",
                example='search_core_fulltext(query="propofol dose calculation")',
                tool_name="search_core_fulltext"
            )
        
        limit = InputNormalizer.normalize_limit(limit, default=10, max_val=100)
        year_from = InputNormalizer.normalize_year(year_from)
        year_to = InputNormalizer.normalize_year(year_to)
        
        try:
            from ..sources.core import get_core_client
            
            client = get_core_client()
            result = client.search_fulltext(
                query=query,
                limit=limit,
                year_from=year_from,
                year_to=year_to,
            )
            
            papers = result.get("results", [])
            if not papers:
                return ResponseFormatter.no_results(
                    query=query,
                    suggestions=[
                        "Try simpler search terms",
                        "Full text search requires exact phrase matches",
                        "Try title/abstract search with search_core instead"
                    ]
                )
            
            return json.dumps({
                "total_hits": result.get("total_hits", 0),
                "papers": papers,
            }, indent=2, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"CORE fulltext search failed: {e}")
            return ResponseFormatter.error(e, tool_name="search_core_fulltext")
    
    @mcp.tool()
    async def get_core_paper(core_id: Union[str, int]) -> str:
        """
        Get detailed information about a CORE paper.
        
        Args:
            core_id: CORE work ID (from search results)
            
        Returns:
            JSON with paper details including metadata and availability
        """
        # Normalize input
        if core_id is None:
            return ResponseFormatter.error(
                "Missing core_id",
                suggestion="Provide a CORE work ID from search results",
                example='get_core_paper(core_id="123456789")',
                tool_name="get_core_paper"
            )
        core_id = str(core_id).strip()
        
        try:
            from ..sources.core import get_core_client
            
            client = get_core_client()
            result = client.get_work(core_id)
            
            if result:
                return json.dumps(result, indent=2, ensure_ascii=False)
            else:
                return ResponseFormatter.no_results(
                    suggestions=[f"Paper with CORE ID '{core_id}' not found"],
                    alternative_tools=["search_core", "find_in_core"]
                )
                
        except Exception as e:
            logger.error(f"Get CORE paper failed: {e}")
            return ResponseFormatter.error(e, tool_name="get_core_paper")
    
    @mcp.tool()
    async def get_core_fulltext(core_id: Union[str, int]) -> str:
        """
        Get full text content of a CORE paper.
        
        Returns the actual text content of the paper if available.
        This is one of CORE's unique features - direct access to full text.
        
        Args:
            core_id: CORE work ID
            
        Returns:
            Full text content or error message
        """
        # Normalize input
        if core_id is None:
            return ResponseFormatter.error(
                "Missing core_id",
                suggestion="Provide a CORE work ID",
                example='get_core_fulltext(core_id="123456789")',
                tool_name="get_core_fulltext"
            )
        core_id = str(core_id).strip()
        
        try:
            from ..sources.core import get_core_client
            
            client = get_core_client()
            fulltext = client.get_fulltext(core_id)
            
            if fulltext:
                # Truncate if too long
                if len(fulltext) > 50000:
                    return json.dumps({
                        "content": fulltext[:50000],
                        "truncated": True,
                        "total_length": len(fulltext),
                        "note": "Full text truncated to 50,000 characters"
                    }, ensure_ascii=False)
                return json.dumps({
                    "content": fulltext,
                    "truncated": False,
                    "total_length": len(fulltext),
                }, ensure_ascii=False)
            else:
                return ResponseFormatter.no_results(
                    suggestions=[
                        "Full text not available for this paper",
                        "Try get_core_paper to check download_url",
                        "Consider using get_fulltext for PMC articles"
                    ]
                )
                
        except Exception as e:
            logger.error(f"Get CORE fulltext failed: {e}")
            return ResponseFormatter.error(e, tool_name="get_core_fulltext")
    
    @mcp.tool()
    async def find_in_core(
        identifier: Union[str, int],
        identifier_type: str = "doi",
    ) -> str:
        """
        Find a paper in CORE by DOI or PMID.
        
        Useful for finding open access versions of papers you already know.
        
        Args:
            identifier: The identifier value (e.g., "10.1234/example" or "12345678")
            identifier_type: Type of identifier ("doi" or "pmid")
            
        Returns:
            JSON with paper details if found in CORE
        """
        # Normalize inputs
        if identifier is None:
            return ResponseFormatter.error(
                "Missing identifier",
                suggestion="Provide a DOI or PMID",
                example='find_in_core(identifier="10.1038/s41586-021-03819-2", identifier_type="doi")',
                tool_name="find_in_core"
            )
        
        identifier = str(identifier).strip()
        identifier_type = identifier_type.lower().strip() if identifier_type else "doi"
        
        # Normalize PMID if type is pmid
        if identifier_type == "pmid":
            normalized = InputNormalizer.normalize_pmid_single(identifier)
            if normalized:
                identifier = normalized
        
        try:
            from ..sources.core import get_core_client
            
            client = get_core_client()
            
            if identifier_type == "doi":
                result = client.search_by_doi(identifier)
            elif identifier_type == "pmid":
                result = client.search_by_pmid(identifier)
            else:
                return ResponseFormatter.error(
                    f"Unknown identifier type: {identifier_type}",
                    suggestion="Use 'doi' or 'pmid'",
                    example='find_in_core(identifier="12345678", identifier_type="pmid")',
                    tool_name="find_in_core"
                )
            
            if result:
                return json.dumps(result, indent=2, ensure_ascii=False)
            else:
                return ResponseFormatter.no_results(
                    suggestions=[
                        f"Paper not found in CORE with {identifier_type}: {identifier}",
                        "Paper may not be in open access repositories",
                        "Try search_core with title keywords instead"
                    ]
                )
                
        except Exception as e:
            logger.error(f"Find in CORE failed: {e}")
            return ResponseFormatter.error(e, tool_name="find_in_core")
