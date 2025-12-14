"""
Export Tools - MCP tools for citation export and fulltext access.

Provides:
- prepare_export: Export search results to various formats
- get_fulltext_links: Get fulltext URLs for an article
- summarize_fulltext_access: Analyze fulltext availability
"""

import json
import logging
import tempfile
import os
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from ...entrez import LiteratureSearcher
from ...exports import (
    export_articles,
    get_fulltext_links_with_lookup,
    summarize_access,
    SUPPORTED_FORMATS,
)
from ._common import get_session_manager

logger = logging.getLogger(__name__)

# Export directory for prepared files
EXPORT_DIR = os.path.join(tempfile.gettempdir(), "pubmed_exports")


def register_export_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """Register export-related tools."""
    
    @mcp.tool()
    def prepare_export(
        pmids: str,
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
            pmids: Comma-separated PubMed IDs (e.g., "12345678,87654321")
                   OR "last" to use results from last search
            format: Export format (ris, bibtex, csv, medline, json)
            include_abstract: Whether to include abstracts (default: True)
            
        Returns:
            Formatted citation text ready for download or copy.
            For large exports (>20 articles), returns a file path instead.
        """
        # Resolve PMIDs
        pmid_list = _resolve_pmids(pmids)
        
        if not pmid_list:
            return json.dumps({
                "status": "error",
                "message": "No PMIDs provided. Use 'last' for last search results or provide comma-separated PMIDs."
            })
        
        # Validate format
        format_lower = format.lower()
        if format_lower not in SUPPORTED_FORMATS:
            return json.dumps({
                "status": "error",
                "message": f"Unsupported format: {format}. Supported: {SUPPORTED_FORMATS}"
            })
        
        try:
            # Fetch article details
            articles = searcher.fetch_details(pmid_list)
            
            if not articles:
                return json.dumps({
                    "status": "error",
                    "message": "Failed to fetch article details"
                })
            
            # Export to format
            exported_text = export_articles(
                articles,
                format=format_lower,
                include_abstract=include_abstract
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
            return json.dumps({
                "status": "error",
                "message": str(e)
            })
    
    @mcp.tool()
    def get_article_fulltext_links(pmid: str) -> str:
        """
        Get fulltext links for a single article.
        
        Returns URLs to access the full text:
        - PubMed page
        - PMC (if available - free full text)
        - PMC PDF direct link
        - DOI (publisher page)
        
        Args:
            pmid: PubMed ID of the article
            
        Returns:
            JSON with available links and access type.
        """
        try:
            # Use API lookup to get PMC status
            links = get_fulltext_links_with_lookup(pmid, searcher)
            
            # Add article title if available
            articles = searcher.fetch_details([pmid])
            if articles:
                links["title"] = articles[0].get("title", "")[:100]
                links["doi_url"] = f"https://doi.org/{articles[0].get('doi')}" if articles[0].get("doi") else None
            
            return json.dumps({
                "status": "success",
                "links": links
            })
            
        except Exception as e:
            logger.exception(f"Error getting fulltext links for {pmid}")
            return json.dumps({
                "status": "error",
                "message": str(e)
            })
    
    @mcp.tool()
    def analyze_fulltext_access(pmids: str) -> str:
        """
        Analyze fulltext availability for multiple articles.
        
        Useful for planning literature review - shows which articles
        have free full text available via PMC.
        
        Args:
            pmids: Comma-separated PubMed IDs (e.g., "12345678,87654321")
                   OR "last" to use results from last search
                   
        Returns:
            Summary statistics with lists of:
            - Open access articles (PMC available)
            - Subscription-required articles
            - Abstract-only articles
        """
        # Resolve PMIDs
        pmid_list = _resolve_pmids(pmids)
        
        if not pmid_list:
            return json.dumps({
                "status": "error",
                "message": "No PMIDs provided."
            })
        
        try:
            # Fetch article details to get PMC info
            articles = searcher.fetch_details(pmid_list)
            
            if not articles:
                return json.dumps({
                    "status": "error",
                    "message": "Failed to fetch article details"
                })
            
            # Analyze access
            summary = summarize_access(articles)
            
            return json.dumps({
                "status": "success",
                "summary": summary
            })
            
        except Exception as e:
            logger.exception("Error analyzing fulltext access")
            return json.dumps({
                "status": "error",
                "message": str(e)
            })


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
