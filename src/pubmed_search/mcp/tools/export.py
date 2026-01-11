"""
Export Tools - MCP tools for citation export and fulltext access.

Provides:
- prepare_export: Export search results to various formats
- get_fulltext_links: Get fulltext URLs for an article
- summarize_fulltext_access: Analyze fulltext availability

Phase 2.1 Updates:
- InputNormalizer for flexible PMID input
- ResponseFormatter for consistent error messages
"""

import json
import logging
import tempfile
import os
from datetime import datetime
from typing import Union, List

from mcp.server.fastmcp import FastMCP

from ...entrez import LiteratureSearcher
from ...exports import (
    export_articles,
    get_fulltext_links_with_lookup,
    summarize_access,
    SUPPORTED_FORMATS,
)
from ._common import get_session_manager, InputNormalizer, ResponseFormatter

logger = logging.getLogger(__name__)

# Export directory for prepared files
EXPORT_DIR = os.path.join(tempfile.gettempdir(), "pubmed_exports")


def register_export_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """Register export-related tools."""
    
    @mcp.tool()
    def prepare_export(
        pmids: Union[str, List, int],
        format: str = "ris",
        include_abstract: bool = True
    ) -> str:
        """
        Prepare citation export in various formats.
        
        This tool prepares article citations for export to reference managers
        or other tools. Returns formatted text directly (not through agent).
        
        Supported formats:
        - ris: EndNote, Zotero, Mendeley (recommended)
        - bibtex: LaTeX documents  
        - csv: Excel, data analysis
        - medline: Original PubMed format
        - json: Programmatic access
        
        Args:
            pmids: PubMed IDs - accepts multiple formats:
                   - "12345678,87654321" (comma-separated)
                   - ["12345678", "87654321"] (list)
                   - "PMID:12345678" (with prefix)
                   - "last" to use results from last search
            format: Export format (ris, bibtex, csv, medline, json)
            include_abstract: Whether to include abstracts (default: True)
            
        Returns:
            Formatted citation text ready for download or copy.
            For large exports (>20 articles), returns a file path instead.
        """
        # Phase 2.1: Input normalization
        normalized_pmids = InputNormalizer.normalize_pmids(pmids)
        normalized_abstract = InputNormalizer.normalize_bool(include_abstract, default=True)
        
        # Handle "last" keyword
        if normalized_pmids == ['last']:
            pmid_list = _resolve_pmids("last")
        else:
            pmid_list = normalized_pmids
        
        if not pmid_list:
            return ResponseFormatter.error(
                error="No valid PMIDs provided",
                suggestion="Use 'last' for last search results or provide PMIDs",
                example='prepare_export(pmids="12345678,87654321", format="ris")',
                tool_name="prepare_export"
            )
        
        # Validate format
        format_lower = format.lower()
        if format_lower not in SUPPORTED_FORMATS:
            return ResponseFormatter.error(
                error=f"Unsupported format: {format}",
                suggestion=f"Use one of: {', '.join(SUPPORTED_FORMATS)}",
                example='prepare_export(pmids="last", format="ris")',
                tool_name="prepare_export"
            )
        
        try:
            # Fetch article details
            articles = searcher.fetch_details(pmid_list)
            
            if not articles:
                return ResponseFormatter.no_results(
                    query=f"PMIDs: {', '.join(pmid_list[:5])}",
                    suggestions=[
                        "Check if the PMIDs are correct",
                        "Use search_literature to find valid PMIDs"
                    ]
                )
            
            # Export to format
            exported_text = export_articles(
                articles,
                format=format_lower,
                include_abstract=normalized_abstract
            )
            
            # For large exports, save to file and return path
            if len(pmid_list) > 20:
                file_path = _save_export_file(exported_text, format_lower, len(pmid_list))
                return json.dumps({
                    "status": "success",
                    "article_count": len(articles),
                    "format": format_lower,
                    "message": "Large export saved to file",
                    "file_path": file_path,
                    "instructions": "Use 'cat' or open the file to view contents"
                })
            
            # For small exports, return text directly
            return json.dumps({
                "status": "success",
                "article_count": len(articles),
                "format": format_lower,
                "export_text": exported_text,
                "instructions": f"Copy the export_text content and save as .{_get_file_extension(format_lower)}"
            })
            
        except Exception as e:
            logger.exception("Error preparing export")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check PMIDs and format, then try again",
                tool_name="prepare_export"
            )
    
    # ❌ REMOVED v0.1.20: Merged into unified get_fulltext tool
    # @mcp.tool()
    def get_article_fulltext_links(pmid: Union[str, int]) -> str:
        """
        Get fulltext links for a single article.
        
        Returns URLs to access the full text:
        - PubMed page
        - PMC (if available - free full text)
        - PMC PDF direct link
        - DOI (publisher page)
        
        Args:
            pmid: PubMed ID (accepts: "12345678", "PMID:12345678", 12345678)
            
        Returns:
            JSON with available links and access type.
        """
        # Phase 2.1: Input normalization
        normalized_pmid = InputNormalizer.normalize_pmid_single(pmid)
        
        if not normalized_pmid:
            return ResponseFormatter.error(
                error="Invalid PMID format",
                suggestion="Provide a valid PMID number",
                example='get_article_fulltext_links(pmid="12345678")',
                tool_name="get_article_fulltext_links"
            )
        
        try:
            # Use API lookup to get PMC status
            links = get_fulltext_links_with_lookup(normalized_pmid, searcher)
            
            # Add article title if available
            articles = searcher.fetch_details([normalized_pmid])
            if articles:
                links["title"] = articles[0].get("title", "")[:100]
                links["doi_url"] = f"https://doi.org/{articles[0].get('doi')}" if articles[0].get("doi") else None
            
            return json.dumps({
                "status": "success",
                "links": links
            })
            
        except Exception as e:
            logger.exception(f"Error getting fulltext links for {normalized_pmid}")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check if the PMID is correct",
                tool_name="get_article_fulltext_links"
            )
    
    # ❌ REMOVED v0.1.20: Auto-handled by unified get_fulltext
    # @mcp.tool()
    def analyze_fulltext_access(pmids: Union[str, List, int]) -> str:
        """
        Analyze fulltext availability for multiple articles.
        
        Useful for planning literature review - shows which articles
        have free full text available via PMC.
        
        Args:
            pmids: PubMed IDs - accepts multiple formats:
                   - "12345678,87654321" (comma-separated)
                   - ["12345678", "87654321"] (list)
                   - "PMID:12345678" (with prefix)
                   - "last" to use results from last search
                   
        Returns:
            Summary statistics with lists of:
            - Open access articles (PMC available)
            - Subscription-required articles
            - Abstract-only articles
        """
        # Phase 2.1: Input normalization
        normalized_pmids = InputNormalizer.normalize_pmids(pmids)
        
        # Handle "last" keyword
        if normalized_pmids == ['last']:
            pmid_list = _resolve_pmids("last")
        else:
            pmid_list = normalized_pmids
        
        if not pmid_list:
            return ResponseFormatter.error(
                error="No valid PMIDs provided",
                suggestion="Use 'last' for last search results or provide PMIDs",
                example='analyze_fulltext_access(pmids="12345678,87654321")',
                tool_name="analyze_fulltext_access"
            )
        
        try:
            # Fetch article details to get PMC info
            articles = searcher.fetch_details(pmid_list)
            
            if not articles:
                return ResponseFormatter.no_results(
                    query=f"PMIDs: {', '.join(pmid_list[:5])}",
                    suggestions=[
                        "Check if the PMIDs are correct",
                        "Use search_literature to find valid PMIDs"
                    ]
                )
            
            # Analyze access
            summary = summarize_access(articles)
            
            return json.dumps({
                "status": "success",
                "summary": summary
            })
            
        except Exception as e:
            logger.exception("Error analyzing fulltext access")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check PMIDs and try again",
                tool_name="analyze_fulltext_access"
            )


def _resolve_pmids(pmids: str) -> list:
    """Resolve PMID string to list. Supports 'last' for last search results."""
    if pmids.lower() == "last":
        # Get from session manager
        session_manager = get_session_manager()
        if session_manager:
            session = session_manager.get_or_create_session()
            if session.search_history:
                last_search = session.search_history[-1]
                # search_history is List[Dict], each dict has 'pmids' key
                if isinstance(last_search, dict):
                    return last_search.get("pmids", [])[:100]  # Limit to 100
                # Fallback for SearchRecord dataclass
                elif hasattr(last_search, "pmids"):
                    return last_search.pmids[:100]
        return []
    
    # Parse comma-separated list
    pmid_list = [p.strip() for p in pmids.split(",") if p.strip()]
    return pmid_list


def _save_export_file(content: str, format: str, count: int) -> str:
    """Save export content to a temporary file."""
    os.makedirs(EXPORT_DIR, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    extension = _get_file_extension(format)
    filename = f"pubmed_export_{count}_{timestamp}.{extension}"
    file_path = os.path.join(EXPORT_DIR, filename)
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    
    return file_path


def _get_file_extension(format: str) -> str:
    """Get file extension for format."""
    extensions = {
        "ris": "ris",
        "bibtex": "bib",
        "csv": "csv",
        "medline": "txt",
        "json": "json"
    }
    return extensions.get(format, "txt")
