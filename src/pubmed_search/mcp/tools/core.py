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
from typing import Any

from mcp.server import Server

logger = logging.getLogger(__name__)


def register_core_tools(mcp: Server) -> None:
    """Register CORE API tools with MCP server."""
    
    @mcp.tool()
    async def search_core(
        query: str,
        limit: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
        has_fulltext: bool = False,
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
        try:
            from ..sources.core import get_core_client
            
            client = get_core_client()
            result = client.search(
                query=query,
                limit=min(limit, 100),
                year_from=year_from,
                year_to=year_to,
                has_fulltext=has_fulltext,
            )
            
            return json.dumps({
                "total_hits": result.get("total_hits", 0),
                "papers": result.get("results", []),
                "note": "Use get_core_fulltext with core_id to retrieve full text"
            }, indent=2, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"CORE search failed: {e}")
            return json.dumps({"error": str(e)})
    
    @mcp.tool()
    async def search_core_fulltext(
        query: str,
        limit: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
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
        try:
            from ..sources.core import get_core_client
            
            client = get_core_client()
            result = client.search_fulltext(
                query=query,
                limit=min(limit, 100),
                year_from=year_from,
                year_to=year_to,
            )
            
            return json.dumps({
                "total_hits": result.get("total_hits", 0),
                "papers": result.get("results", []),
            }, indent=2, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"CORE fulltext search failed: {e}")
            return json.dumps({"error": str(e)})
    
    @mcp.tool()
    async def get_core_paper(core_id: str) -> str:
        """
        Get detailed information about a CORE paper.
        
        Args:
            core_id: CORE work ID (from search results)
            
        Returns:
            JSON with paper details including metadata and availability
        """
        try:
            from ..sources.core import get_core_client
            
            client = get_core_client()
            result = client.get_work(core_id)
            
            if result:
                return json.dumps(result, indent=2, ensure_ascii=False)
            else:
                return json.dumps({"error": f"Paper {core_id} not found"})
                
        except Exception as e:
            logger.error(f"Get CORE paper failed: {e}")
            return json.dumps({"error": str(e)})
    
    @mcp.tool()
    async def get_core_fulltext(core_id: str) -> str:
        """
        Get full text content of a CORE paper.
        
        Returns the actual text content of the paper if available.
        This is one of CORE's unique features - direct access to full text.
        
        Args:
            core_id: CORE work ID
            
        Returns:
            Full text content or error message
        """
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
                return json.dumps({
                    "error": "Full text not available for this paper",
                    "suggestion": "Try get_core_paper to check download_url"
                })
                
        except Exception as e:
            logger.error(f"Get CORE fulltext failed: {e}")
            return json.dumps({"error": str(e)})
    
    @mcp.tool()
    async def find_in_core(
        identifier: str,
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
        try:
            from ..sources.core import get_core_client
            
            client = get_core_client()
            
            if identifier_type.lower() == "doi":
                result = client.search_by_doi(identifier)
            elif identifier_type.lower() == "pmid":
                result = client.search_by_pmid(identifier)
            else:
                return json.dumps({
                    "error": f"Unknown identifier type: {identifier_type}",
                    "supported": ["doi", "pmid"]
                })
            
            if result:
                return json.dumps(result, indent=2, ensure_ascii=False)
            else:
                return json.dumps({
                    "error": f"Paper not found in CORE with {identifier_type}: {identifier}",
                    "note": "Paper may not be in open access repositories"
                })
                
        except Exception as e:
            logger.error(f"Find in CORE failed: {e}")
            return json.dumps({"error": str(e)})
