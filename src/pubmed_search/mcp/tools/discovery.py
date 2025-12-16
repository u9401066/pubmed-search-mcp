"""
Discovery Tools - Search and explore PubMed literature.

Tools:
- search_literature: Basic PubMed search (supports alternate sources internally)
- find_related_articles: Find related papers (similar articles)
- find_citing_articles: Find papers that cite this article (forward in time)
- get_article_references: Get this article's bibliography (backward in time)
- fetch_article_details: Get full article details
- get_citation_metrics: Get NIH iCite citation metrics (RCR, percentile)

Internal Features:
- Multi-source search: PubMed (default), Semantic Scholar, OpenAlex
- Cross-search fallback when PubMed results are insufficient
"""

import logging
from typing import Literal

from mcp.server.fastmcp import FastMCP

from ...entrez import LiteratureSearcher
from ...sources import search_alternate_source, cross_search
from ._common import format_search_results, _cache_results, _record_search_only, check_cache

logger = logging.getLogger(__name__)

# Known journal names that might be confused with topics
# Format: {lowercase_name: (journal_title, ISSN, hint)}
AMBIGUOUS_JOURNAL_NAMES = {
    "anesthesiology": ("Anesthesiology", "1528-1175", "journal[ta]"),
    "anesthesia": ("Anesthesia & Analgesia", None, "anesthesia[ta]"),
    "lancet": ("The Lancet", "1474-547X", "lancet[ta]"),
    "nature": ("Nature", "1476-4687", "nature[ta]"),
    "science": ("Science", "1095-9203", "science[ta]"),
    "cell": ("Cell", "1097-4172", "cell[ta]"),
    "circulation": ("Circulation", "1524-4539", "circulation[ta]"),
    "neurology": ("Neurology", "1526-632X", "neurology[ta]"),
    "pediatrics": ("Pediatrics", "1098-4275", "pediatrics[ta]"),
    "radiology": ("Radiology", "1527-1315", "radiology[ta]"),
    "surgery": ("Surgery", "1532-7361", "surgery[ta]"),
    "medicine": ("Medicine", "1536-5964", "medicine[ta]"),
    "chest": ("Chest", "1931-3543", "chest[ta]"),
    "gut": ("Gut", "1468-3288", "gut[ta]"),
    "brain": ("Brain", "1460-2156", "brain[ta]"),
    "blood": ("Blood", "1528-0020", "blood[ta]"),
    "pain": ("Pain", "1872-6623", "pain[ta]"),
    "sleep": ("Sleep", "1550-9109", "sleep[ta]"),
    "critical care": ("Critical Care", "1466-609X", "critical care[ta]"),
    "intensive care": ("Intensive Care Medicine", "1432-1238", "intensive care[ta]"),
}


def _detect_ambiguous_terms(query: str) -> list:
    """Detect if query contains terms that could be journal names."""
    query_lower = query.lower()
    ambiguous = []
    
    for term, (journal, issn, hint) in AMBIGUOUS_JOURNAL_NAMES.items():
        # Check if the term appears as a standalone word
        if term in query_lower:
            # Simple check: is it likely being used as a topic rather than journal?
            # If query has other substantive terms, it's probably a topic search
            other_terms = query_lower.replace(term, "").strip()
            if len(other_terms.split()) <= 2:  # Few other terms = might mean journal
                ambiguous.append({
                    "term": term,
                    "journal": journal,
                    "hint": hint
                })
    
    return ambiguous


def _format_ambiguity_hint(ambiguous_terms: list, query: str) -> str:
    """Format a concise hint about ambiguous terms."""
    if not ambiguous_terms:
        return ""
    
    hints = []
    for item in ambiguous_terms[:2]:  # Limit to 2 hints
        term = item["term"]
        journal = item["journal"]
        hint = item["hint"]
        hints.append(f'"{term}" = journal "{journal}"? Use: {hint}')
    
    return "\n\n⚠️ **Tip**: " + " | ".join(hints)


def register_discovery_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """Register discovery tools for exploring PubMed."""
    
    # Supported alternate sources
    ALTERNATE_SOURCES = ("semantic_scholar", "openalex")
    
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
        strategy: str = "relevance",
        force_refresh: bool = False,
        source: Literal["pubmed", "semantic_scholar", "openalex"] = "pubmed",
        open_access_only: bool = False,
        cross_search_fallback: bool = False,
        cross_search_threshold: int = 3,
    ) -> str:
        """
        Search for medical literature based on a query using PubMed.
        
        Results are automatically cached to avoid redundant API calls.
        Repeated searches with the same query will return cached results.
        
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
            force_refresh: If True, bypass cache and fetch fresh results from API.
        """
        # === Internal parameters (not shown in docstring) ===
        # source: Search source ("pubmed", "semantic_scholar", "openalex")
        # open_access_only: Only return open access papers (for alternate sources)
        # cross_search_fallback: Auto-search alternate sources if PubMed < threshold
        # cross_search_threshold: Minimum results before triggering cross-search
        
        logger.info(f"Searching literature: query='{query}', limit={limit}, source='{source}', strategy='{strategy}'")
        try:
            if not query:
                return "Error: Query is required."
            
            # === Handle alternate sources (internal feature) ===
            if source in ALTERNATE_SOURCES:
                return _search_alternate_source_internal(
                    query=query,
                    source=source,
                    limit=limit,
                    min_year=min_year,
                    max_year=max_year,
                    open_access_only=open_access_only,
                )
            
            # === PubMed search (default) ===
            # Detect ambiguous terms (journal vs topic)
            ambiguous = _detect_ambiguous_terms(query)

            # Check cache first (unless force_refresh or filters applied)
            has_filters = any([min_year, max_year, date_from, date_to, article_type])
            if not force_refresh and not has_filters:
                cached = check_cache(query, limit)
                if cached:
                    logger.info(f"Returning {len(cached)} cached results for '{query}'")
                    result = format_search_results(cached[:limit]) + "\n\n_(cached results)_"
                    result += _format_ambiguity_hint(ambiguous, query)
                    return result

            # No cache hit - call API
            results = searcher.search(
                query, limit, min_year, max_year, 
                article_type, strategy,
                date_from=date_from, date_to=date_to, date_type=date_type
            )
            
            # Extract total count from metadata (if present)
            total_count = None
            if results and "_search_metadata" in results[0]:
                total_count = results[0]["_search_metadata"].get("total_count")
                # Remove metadata from results before caching/formatting
                del results[0]["_search_metadata"]
                # If this was a metadata-only result (no actual article data), remove it
                if len(results[0]) == 0 or (len(results[0]) == 1 and "error" not in results[0]):
                    results = results[1:] if len(results) > 1 else []
            
            # Cache results (only for queries without filters)
            if not has_filters:
                _cache_results(results, query)
            else:
                # Always record search history for "last" export feature
                _record_search_only(results, query)
            
            # Format results with total count info
            returned_count = len(results[:limit])
            
            # Always show total_count if available, even when returned_count == 0
            if total_count is not None:
                if returned_count == 0:
                    result = f"📊 PubMed 共有 **{total_count}** 篇符合條件，但無法取得詳細資料\n\n"
                elif total_count > returned_count:
                    result = f"📊 Found **{returned_count}** results (of **{total_count}** total in PubMed)\n\n"
                else:
                    result = f"📊 Found **{returned_count}** results\n\n"
            else:
                result = f"📊 Found **{returned_count}** results\n\n"
            result += format_search_results(results[:limit])
            
            # Add hint about potential journal name confusion 
            # Always show for single-word queries or when results suggest broad topic
            if ambiguous:
                result += _format_ambiguity_hint(ambiguous, query)
            
            # Add session persistence hint for large result sets
            if returned_count >= 5:
                pmids_list = [r.get('pmid') for r in results[:limit] if r.get('pmid')]
                result += f"\n---\n💾 **Session 已暫存 {len(pmids_list)} 篇 PMIDs**"
                result += f"\n🔖 後續可用: `get_session_pmids()` 或 `pmids='last'`"
            
            # === Cross-search fallback (when PubMed results insufficient) ===
            if cross_search_fallback and returned_count < cross_search_threshold:
                result += _perform_cross_search_fallback(
                    query=query,
                    existing_results=results[:limit],
                    limit=limit - returned_count,
                    min_year=min_year,
                    max_year=max_year,
                    open_access_only=open_access_only,
                )
                
            return result
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return f"Error: {e}"
    
    def _search_alternate_source_internal(
        query: str,
        source: str,
        limit: int,
        min_year: int | None,
        max_year: int | None,
        open_access_only: bool,
    ) -> str:
        """Internal: Search alternate sources (Semantic Scholar, OpenAlex)."""
        try:
            results = search_alternate_source(
                query=query,
                source=source,
                limit=limit,
                min_year=min_year,
                max_year=max_year,
                open_access_only=open_access_only,
            )
            
            source_name = {
                "semantic_scholar": "Semantic Scholar",
                "openalex": "OpenAlex",
            }.get(source, source)
            
            if not results:
                return f"📊 No results found from {source_name} for '{query}'."
            
            # Format header
            returned_count = len(results)
            oa_note = " (Open Access only)" if open_access_only else ""
            result = f"📊 Found **{returned_count}** results from **{source_name}**{oa_note}\n\n"
            
            # Format results
            result += format_search_results(results)
            
            # Note about source
            result += f"\n---\n📚 Source: {source_name}"
            if source == "openalex":
                result += " | Has citation counts & open access info"
            elif source == "semantic_scholar":
                result += " | Has influential citations & TLDR"
            
            return result
            
        except Exception as e:
            logger.error(f"Alternate source search failed: {e}")
            return f"Error searching {source}: {e}"
    
    def _perform_cross_search_fallback(
        query: str,
        existing_results: list,
        limit: int,
        min_year: int | None,
        max_year: int | None,
        open_access_only: bool,
    ) -> str:
        """Internal: Perform cross-search when PubMed results insufficient."""
        if limit <= 0:
            return ""
        
        try:
            cross_results = cross_search(
                query=query,
                sources=["openalex"],  # OpenAlex is more reliable for fallback
                limit_per_source=limit,
                min_year=min_year,
                max_year=max_year,
                open_access_only=open_access_only,
                deduplicate=True,
            )
            
            if not cross_results.get("results"):
                return ""
            
            # Filter out papers already in PubMed results (by PMID or title)
            existing_pmids = {r.get("pmid") for r in existing_results if r.get("pmid")}
            existing_titles = {r.get("title", "").lower()[:50] for r in existing_results}
            
            new_results = []
            for paper in cross_results["results"]:
                if paper.get("pmid") in existing_pmids:
                    continue
                if paper.get("title", "").lower()[:50] in existing_titles:
                    continue
                new_results.append(paper)
            
            if not new_results:
                return ""
            
            # Format supplemental results
            output = f"\n\n---\n🔄 **Cross-search results from OpenAlex** ({len(new_results)} additional)\n\n"
            output += format_search_results(new_results[:limit])
            
            return output
            
        except Exception as e:
            logger.warning(f"Cross-search fallback failed: {e}")
            return ""

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
    def get_article_references(pmid: str, limit: int = 20) -> str:
        """
        Get the references (bibliography) of a PubMed article.
        
        Returns the list of articles that this paper cites in its bibliography.
        This is the OPPOSITE of find_citing_articles:
        - get_article_references: Papers THIS article cites (backward in time)
        - find_citing_articles: Papers that cite THIS article (forward in time)
        
        Args:
            pmid: PubMed ID of the source article.
            limit: Maximum number of references to return.
            
        Returns:
            List of referenced articles with details.
        """
        logger.info(f"Getting references for PMID: {pmid}")
        try:
            results = searcher.get_article_references(pmid, limit)
            
            if not results:
                return f"No references found for PMID {pmid}. (Article may not be indexed in PMC or references not available.)"
            
            if "error" in results[0]:
                return f"Error getting references: {results[0]['error']}"
            
            output = f"📚 **References of PMID {pmid}** ({len(results)} found)\n\n"
            output += "These are the papers cited BY this article (its bibliography):\n\n"
            output += format_search_results(results)
            return output
        except Exception as e:
            logger.error(f"Get article references failed: {e}")
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

    @mcp.tool()
    def get_citation_metrics(
        pmids: str,
        sort_by: str = "citation_count",
        min_citations: int = None,
        min_rcr: float = None,
        min_percentile: float = None
    ) -> str:
        """
        Get citation metrics from NIH iCite for articles.
        
        Returns field-normalized citation data including:
        - citation_count: Total number of citations
        - relative_citation_ratio (RCR): Field-normalized metric (1.0 = average)
        - nih_percentile: Percentile ranking (0-100)
        - citations_per_year: Citation velocity
        - apt: Approximate Potential to Translate (clinical relevance 0-1)
        
        Can sort and filter results by citation metrics.
        
        Args:
            pmids: Comma-separated list of PubMed IDs (e.g., "12345678,87654321")
                   OR "last" to use PMIDs from the last search
            sort_by: Metric to sort by:
                - "citation_count": Raw citation count (default)
                - "relative_citation_ratio": Field-normalized (recommended)
                - "nih_percentile": Percentile ranking
                - "citations_per_year": Citation velocity
            min_citations: Filter out articles with fewer citations
            min_rcr: Filter out articles with RCR below threshold (e.g., 1.0 = average)
            min_percentile: Filter out articles below percentile (e.g., 50 = top half)
            
        Returns:
            Articles with citation metrics, sorted and filtered as requested.
        """
        
        logger.info(f"Getting citation metrics for: {pmids}")
        
        try:
            # Handle "last" keyword
            if pmids.strip().lower() == "last":
                from ._common import get_last_search_pmids
                pmid_list = get_last_search_pmids()
                if not pmid_list:
                    return "No previous search results found. Please search first or provide PMIDs."
            else:
                pmid_list = [p.strip() for p in pmids.split(",")]
            
            if not pmid_list:
                return "No PMIDs provided."
            
            # Get metrics from iCite
            metrics = searcher.get_citation_metrics(pmid_list)
            
            if not metrics:
                return f"No citation data found for PMIDs: {pmids}. Articles may be too recent or not indexed in iCite."
            
            # Convert to list for sorting/filtering
            articles = [{"pmid": pmid, "icite": data} for pmid, data in metrics.items()]
            
            # Apply filters
            if min_citations is not None:
                articles = [a for a in articles 
                           if (a["icite"].get("citation_count") or 0) >= min_citations]
            
            if min_rcr is not None:
                articles = [a for a in articles 
                           if (a["icite"].get("relative_citation_ratio") or 0) >= min_rcr]
            
            if min_percentile is not None:
                articles = [a for a in articles 
                           if (a["icite"].get("nih_percentile") or 0) >= min_percentile]
            
            if not articles:
                return "No articles match the specified filters."
            
            # Sort
            def get_sort_value(a):
                val = a["icite"].get(sort_by)
                return val if val is not None else -1
            
            articles = sorted(articles, key=get_sort_value, reverse=True)
            
            # Format output
            output = f"📊 **Citation Metrics** ({len(articles)} articles)\n"
            output += f"Sorted by: {sort_by}\n"
            
            if min_citations or min_rcr or min_percentile:
                filters = []
                if min_citations:
                    filters.append(f"citations≥{min_citations}")
                if min_rcr:
                    filters.append(f"RCR≥{min_rcr}")
                if min_percentile:
                    filters.append(f"percentile≥{min_percentile}")
                output += f"Filters: {', '.join(filters)}\n"
            
            output += "\n"
            
            for i, article in enumerate(articles, 1):
                icite = article["icite"]
                pmid = icite.get("pmid", article["pmid"])
                title = icite.get("title", "Unknown")[:80]
                year = icite.get("year", "?")
                journal = icite.get("journal", "Unknown")
                
                citations = icite.get("citation_count", 0) or 0
                rcr = icite.get("relative_citation_ratio")
                percentile = icite.get("nih_percentile")
                cpy = icite.get("citations_per_year")
                apt = icite.get("apt")
                
                output += f"**{i}. [{pmid}]** {title}...\n"
                output += f"   📅 {year} | 📰 {journal}\n"
                output += f"   📈 Citations: **{citations}**"
                
                if rcr is not None:
                    output += f" | RCR: **{rcr:.2f}**"
                if percentile is not None:
                    output += f" | Percentile: **{percentile:.1f}%**"
                if cpy is not None:
                    output += f" | {cpy:.1f}/yr"
                if apt is not None and apt > 0.5:
                    output += f" | 🏥 APT: {apt:.2f}"
                
                output += "\n\n"
            
            # Add legend
            output += "---\n"
            output += "**Legend**: RCR=Relative Citation Ratio (1.0=field average), "
            output += "APT=Approximate Potential to Translate (clinical relevance)\n"
            
            return output
            
        except Exception as e:
            logger.error(f"Get citation metrics failed: {e}")
            return f"Error: {e}"

