"""
Discovery Tools - Search and explore PubMed literature.

Tools:
- search_literature: Basic PubMed search
- find_related_articles: Find related papers
- find_citing_articles: Find citing papers
- fetch_article_details: Get full article details
"""

import logging

from mcp.server.fastmcp import FastMCP

from ...entrez import LiteratureSearcher
from ._common import format_search_results, _cache_results

logger = logging.getLogger(__name__)


def register_discovery_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """Register discovery tools for exploring PubMed."""
    
    @mcp.tool()
    def search_literature(
        query: str, 
        limit: int = 5, 
        min_year: int = None, 
        max_year: int = None,
        date_from: str = None,
        date_to: str = None,
        date_type: str = "edat",
        article_type: str = None, 
        strategy: str = "relevance"
    ) -> str:
        """
        Search for medical literature based on a query using PubMed.
        
        Results are automatically cached to avoid redundant API calls.
        
        Args:
            query: The search query (e.g., "diabetes treatment guidelines").
            limit: The maximum number of results to return.
            min_year: Optional minimum publication year (e.g., 2020).
            max_year: Optional maximum publication year.
            date_from: Precise start date in YYYY/MM/DD format (e.g., "2025/10/01").
            date_to: Precise end date in YYYY/MM/DD format (e.g., "2025/11/28").
            date_type: Which date field to search. Options:
                       - "edat" (default): Entrez date - when added to PubMed (best for NEW articles)
                       - "pdat": Publication date
                       - "mdat": Modification date
            article_type: Optional article type (e.g., "Review", "Clinical Trial", "Meta-Analysis").
            strategy: Search strategy ("recent", "most_cited", "relevance", "impact"). 
                     Default is "relevance".
        """
        logger.info(f"Searching literature: query='{query}', limit={limit}, strategy='{strategy}'")
        try:
            if not query:
                return "Error: Query is required."

            results = searcher.search(
                query, limit, min_year, max_year, 
                article_type, strategy,
                date_from=date_from, date_to=date_to, date_type=date_type
            )
            
            # Cache results
            _cache_results(results, query)
                
            return format_search_results(results[:limit])
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return f"Error: {e}"

    @mcp.tool()
    def find_related_articles(pmid: str, limit: int = 5) -> str:
        """
        Find articles related to a given PubMed article.
        Uses PubMed's "Related Articles" feature to find similar papers.
        
        Args:
            pmid: PubMed ID of the source article.
            limit: Maximum number of related articles to return.
            
        Returns:
            List of related articles with details.
        """
        logger.info(f"Finding related articles for PMID: {pmid}")
        try:
            results = searcher.get_related_articles(pmid, limit)
            
            if not results:
                return f"No related articles found for PMID {pmid}."
            
            if "error" in results[0]:
                return f"Error finding related articles: {results[0]['error']}"
            
            output = f"📚 **Related Articles for PMID {pmid}** ({len(results)} found)\n\n"
            output += format_search_results(results)
            return output
        except Exception as e:
            logger.error(f"Find related articles failed: {e}")
            return f"Error: {e}"

    @mcp.tool()
    def find_citing_articles(pmid: str, limit: int = 10) -> str:
        """
        Find articles that cite a given PubMed article.
        Uses PubMed Central's citation data to find papers that reference this article.
        
        Args:
            pmid: PubMed ID of the source article.
            limit: Maximum number of citing articles to return.
            
        Returns:
            List of citing articles with details.
        """
        logger.info(f"Finding citing articles for PMID: {pmid}")
        try:
            results = searcher.get_citing_articles(pmid, limit)
            
            if not results:
                return f"No citing articles found for PMID {pmid}. (Article may not be indexed in PMC or has no citations yet.)"
            
            if "error" in results[0]:
                return f"Error finding citing articles: {results[0]['error']}"
            
            output = f"📖 **Articles Citing PMID {pmid}** ({len(results)} found)\n\n"
            output += format_search_results(results)
            return output
        except Exception as e:
            logger.error(f"Find citing articles failed: {e}")
            return f"Error: {e}"

    @mcp.tool()
    def fetch_article_details(pmids: str) -> str:
        """
        Fetch detailed information for one or more PubMed articles.
        
        Args:
            pmids: Comma-separated list of PubMed IDs (e.g., "12345678,87654321").
            
        Returns:
            Detailed information for each article.
        """
        logger.info(f"Fetching details for PMIDs: {pmids}")
        try:
            pmid_list = [p.strip() for p in pmids.split(",")]
            results = searcher.fetch_details(pmid_list)
            
            if not results:
                return f"No articles found for PMIDs: {pmids}"
            
            if "error" in results[0]:
                return f"Error fetching details: {results[0]['error']}"
            
            return format_search_results(results, include_doi=True)
        except Exception as e:
            logger.error(f"Fetch details failed: {e}")
            return f"Error: {e}"
