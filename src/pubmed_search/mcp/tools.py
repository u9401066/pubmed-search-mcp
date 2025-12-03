"""
PubMed Search MCP Tools

Core search tools: search_literature, find_related_articles, find_citing_articles, 
generate_search_queries, merge_search_results, expand_search_queries

Note: Search results are automatically cached via session manager when available.
"""

import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from mcp.server.fastmcp import FastMCP

from ..entrez import LiteratureSearcher
from ..entrez.strategy import SearchStrategyGenerator

logger = logging.getLogger(__name__)

# Global references (set by server.py after initialization)
_session_manager = None
_strategy_generator = None


def set_session_manager(session_manager):
    """Set the session manager for automatic caching."""
    global _session_manager
    _session_manager = session_manager


def set_strategy_generator(generator: SearchStrategyGenerator):
    """Set the strategy generator for intelligent query generation."""
    global _strategy_generator
    _strategy_generator = generator


def _cache_results(results: list, query: str = None):
    """Cache search results if session manager is available."""
    if _session_manager and results and not results[0].get('error'):
        try:
            _session_manager.add_to_cache(results)
            if query:
                pmids = [r.get('pmid') for r in results if r.get('pmid')]
                _session_manager.add_search_record(query, pmids)
            logger.debug(f"Cached {len(results)} articles")
        except Exception as e:
            logger.warning(f"Failed to cache results: {e}")


def format_search_results(results: list, include_doi: bool = True) -> str:
    """Format search results for display."""
    if not results:
        return "No results found."
        
    if "error" in results[0]:
        return f"Error searching PubMed: {results[0]['error']}"
        
    formatted_output = f"Found {len(results)} results:\n\n"
    for i, paper in enumerate(results, 1):
        formatted_output += f"{i}. **{paper['title']}**\n"
        authors = paper.get('authors', [])
        formatted_output += f"   Authors: {', '.join(authors[:3])}{' et al.' if len(authors) > 3 else ''}\n"
        journal = paper.get('journal', 'Unknown Journal')
        year = paper.get('year', '')
        volume = paper.get('volume', '')
        pages = paper.get('pages', '')
        
        journal_info = f"{journal} ({year})"
        if volume:
            journal_info += f"; {volume}"
            if pages:
                journal_info += f": {pages}"
        formatted_output += f"   Journal: {journal_info}\n"
        formatted_output += f"   PMID: {paper.get('pmid', '')}"
        
        if include_doi and paper.get('doi'):
            formatted_output += f" | DOI: {paper['doi']}"
        if paper.get('pmc_id'):
            formatted_output += f" | PMC: {paper['pmc_id']} 📄"
        
        formatted_output += "\n"
        
        abstract = paper.get('abstract', '')
        if abstract:
            formatted_output += f"   Abstract: {abstract[:200]}...\n"
        formatted_output += "\n"
        
    return formatted_output


def register_search_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """Register PubMed search tools."""
    
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

    @mcp.tool()
    def generate_search_queries(
        topic: str,
        strategy: str = "comprehensive",
        check_spelling: bool = True,
        include_suggestions: bool = True
    ) -> str:
        """
        Gather search intelligence for a topic - returns RAW MATERIALS for Agent to decide.
        
        This tool provides the BUILDING BLOCKS for search, not finished queries.
        The Agent decides how to use them.
        
        ═══════════════════════════════════════════════════════════════════════
        USAGE MODES
        ═══════════════════════════════════════════════════════════════════════
        
        Mode 1: KEYWORD (single call)
        ─────────────────────────────
        User says: "搜尋 remimazolam"
        → Call generate_search_queries(topic="remimazolam")
        → Get mesh_terms + synonyms
        → Build query → search_literature
        
        Mode 2: PICO (multiple calls) 
        ─────────────────────────────
        User says: "remimazolam 在 ICU 鎮靜比 propofol 好嗎？"
        
        Step 1: Agent parses PICO from user's question:
          P = "ICU patients"
          I = "remimazolam" 
          C = "propofol"
          O = "sedation outcomes"
        
        Step 2: Call this tool for EACH element (can be parallel):
          generate_search_queries(topic="ICU patients")
          generate_search_queries(topic="remimazolam")
          generate_search_queries(topic="propofol")
          generate_search_queries(topic="sedation outcomes")
        
        Step 3: Combine results with Boolean logic:
          (P_terms) AND (I_terms OR C_terms) AND (O_terms)
          
        Step 4: Apply Clinical Query filter if appropriate:
          + therapy[filter]     ← for treatment comparison
          + diagnosis[filter]   ← for diagnostic accuracy
          + prognosis[filter]   ← for outcome prediction
          + etiology[filter]    ← for causation
        
        ═══════════════════════════════════════════════════════════════════════
        
        Features:
        - Spelling correction via NCBI ESpell
        - MeSH term lookup for standardized vocabulary
        - Synonym expansion from MeSH database
        - Keyword extraction
        
        Args:
            topic: Search topic - can be single keyword or PICO element
                   Examples: "remimazolam", "ICU patients", "postoperative delirium"
            strategy: Affects suggested_queries (if included)
                - "comprehensive": Multiple angles, includes reviews (default)
                - "focused": Adds RCT filter for high evidence
                - "exploratory": Broader search with more synonyms
            check_spelling: Whether to check/correct spelling (default: True)
            include_suggestions: Include pre-built query suggestions (default: True)
                Set to False if Agent will build its own queries
            
        Returns:
            JSON with RAW MATERIALS:
            - corrected_topic: Spell-checked topic (Agent decides whether to use)
            - keywords: Extracted significant keywords
            - mesh_terms: MeSH data with preferred terms and synonyms
            - all_synonyms: Flattened list of all synonyms for easy use
            - suggested_queries: Optional pre-built queries (Agent can ignore)
        """
        logger.info(f"Generating search queries for topic: {topic}, strategy: {strategy}")
        
        # Use intelligent strategy generator if available
        if _strategy_generator:
            try:
                result = _strategy_generator.generate_strategies(
                    topic=topic,
                    strategy=strategy,
                    use_mesh=True,
                    check_spelling=check_spelling,
                    include_suggestions=include_suggestions
                )
                
                # Add usage hint (Agent can ignore)
                result["_hint"] = {
                    "usage": "Use mesh_terms and all_synonyms to build your own queries, or use suggested_queries as reference",
                    "example_mesh_query": f'"{{preferred_term}}"[MeSH Terms]',
                    "example_synonym_query": f'({{synonym}})[Title/Abstract]'
                }
                
                return json.dumps(result, indent=2, ensure_ascii=False)
                
            except Exception as e:
                logger.warning(f"Strategy generator failed, using fallback: {e}")
        
        # Fallback: basic strategy generation
        words = topic.lower().split()
        queries = []
        
        queries.append({
            "id": "q1_title",
            "query": f"({topic})[Title]",
            "purpose": "Exact title match",
            "priority": 1
        })
        
        queries.append({
            "id": "q2_tiab",
            "query": f"({topic})[Title/Abstract]",
            "purpose": "Title or abstract",
            "priority": 2
        })
        
        if len(words) > 1:
            and_query = " AND ".join(words)
            queries.append({
                "id": "q3_and",
                "query": f"({and_query})",
                "purpose": "All keywords required",
                "priority": 2
            })
        
        queries.append({
            "id": "q4_mesh",
            "query": f"({topic})[MeSH Terms]",
            "purpose": "MeSH standardized",
            "priority": 2
        })
        
        result = {
            "topic": topic,
            "strategy": strategy,
            "spelling": None,
            "mesh_terms": [],
            "queries_count": len(queries),
            "queries": queries,
            "instruction": "Execute search_literature in PARALLEL for each query, then merge_search_results",
            "note": "Using fallback generator (MeSH lookup unavailable)"
        }
        
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    def merge_search_results(results_json: str) -> str:
        """
        Merge multiple search results and remove duplicates.
        
        After running search_literature calls in parallel, use this to combine results.
        
        Accepts TWO formats:
        
        Format 1 (Simple - just PMIDs):
        [
            ["12345", "67890"],
            ["67890", "11111", "22222"]
        ]
        
        Format 2 (With query IDs):
        [
            {"query_id": "q1_title", "pmids": ["12345", "67890"]},
            {"query_id": "q2_tiab", "pmids": ["67890", "11111"]}
        ]
        
        Args:
            results_json: JSON array of search results (see formats above)
                
        Returns:
            Merged results with:
            - unique_pmids: Deduplicated list
            - high_relevance_pmids: Found in multiple searches (more relevant)
            - statistics: Counts and duplicates removed
        """
        logger.info("Merging search results")
        
        try:
            results = json.loads(results_json)
        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON format - {e}"
        
        pmid_sources = {}
        all_pmids = []
        by_query = {}
        
        for i, result in enumerate(results):
            # Support both formats
            if isinstance(result, list):
                # Format 1: Simple list of PMIDs
                query_id = f"search_{i+1}"
                pmids = result
            elif isinstance(result, dict):
                # Format 2: With query_id
                query_id = result.get("query_id", f"search_{i+1}")
                pmids = result.get("pmids", [])
            else:
                continue
            
            by_query[query_id] = len(pmids)
            
            for pmid in pmids:
                pmid = str(pmid).strip()
                if not pmid:
                    continue
                if pmid not in pmid_sources:
                    pmid_sources[pmid] = []
                    all_pmids.append(pmid)
                pmid_sources[pmid].append(query_id)
        
        # Find PMIDs that appeared in multiple searches (higher relevance)
        high_relevance = [pmid for pmid, sources in pmid_sources.items() if len(sources) > 1]
        
        # Sort: high relevance first, then others
        sorted_pmids = high_relevance + [p for p in all_pmids if p not in high_relevance]
        
        output = {
            "total_unique": len(all_pmids),
            "total_before_dedup": sum(by_query.values()),
            "duplicates_removed": sum(by_query.values()) - len(all_pmids),
            "high_relevance": {
                "count": len(high_relevance),
                "pmids": high_relevance[:20],
                "note": "Found by multiple search strategies - likely more relevant"
            },
            "by_source": by_query,
            "unique_pmids": sorted_pmids,
            "pmids_csv": ",".join(sorted_pmids[:50]),
            "next_step": f"fetch_article_details(pmids=\"{','.join(sorted_pmids[:20])}\")"
        }
        
        return json.dumps(output, indent=2, ensure_ascii=False)

    @mcp.tool()
    def expand_search_queries(
        topic: str,
        existing_query_ids: str = "",
        expansion_type: str = "mesh"
    ) -> str:
        """
        Expand search when initial results are insufficient.
        
        Uses NCBI MeSH database to find synonyms and related terms.
        
        Args:
            topic: Original search topic
            existing_query_ids: Comma-separated IDs of already executed queries
                              Example: "q1_title,q2_tiab,q3_and"
            expansion_type: How to expand
                - "mesh": Use MeSH synonyms (default, recommended)
                - "broader": Relax constraints (OR instead of AND)
                - "narrower": Add filters (RCT, recent years)
            
        Returns:
            New search queries for parallel execution
        """
        logger.info(f"Expanding search for topic: {topic}, type: {expansion_type}")
        
        existing = set(x.strip() for x in existing_query_ids.split(",") if x.strip())
        queries = []
        query_counter = len(existing) + 1
        
        # Use intelligent MeSH-based expansion if available
        if expansion_type == "mesh" and _strategy_generator:
            try:
                result = _strategy_generator.expand_with_mesh(
                    topic=topic,
                    existing_queries=list(existing)
                )
                
                if result.get("queries"):
                    result["instruction"] = "Execute these in PARALLEL, then merge with previous results"
                    return json.dumps(result, indent=2, ensure_ascii=False)
                    
            except Exception as e:
                logger.warning(f"MeSH expansion failed: {e}")
        
        # Fallback expansion logic
        words = topic.lower().split()
        
        if expansion_type in ["mesh", "synonyms"]:
            # Basic synonym map (fallback when MeSH unavailable)
            synonym_map = {
                "sedation": ["conscious sedation", "procedural sedation"],
                "icu": ["intensive care unit", "critical care"],
                "anesthesia": ["anaesthesia", "anesthetic"],
                "ventilation": ["mechanical ventilation", "respiratory support"],
            }
            
            for word in words:
                if word in synonym_map:
                    for syn in synonym_map[word][:2]:
                        new_topic = topic.replace(word, syn)
                        qid = f"q{query_counter}_syn"
                        if qid not in existing:
                            queries.append({
                                "id": qid,
                                "query": f"({new_topic})[Title/Abstract]",
                                "purpose": f"Synonym: {word} → {syn}",
                                "priority": 3
                            })
                            query_counter += 1
                                
        elif expansion_type == "broader":
            if len(words) >= 2:
                or_query = " OR ".join(words)
                qid = f"q{query_counter}_broad"
                if qid not in existing:
                    queries.append({
                        "id": qid,
                        "query": f"({or_query})[Title/Abstract]",
                        "purpose": "Any keyword (broader)",
                        "priority": 4
                    })
                    query_counter += 1
            
            qid = f"q{query_counter}_allfields"
            if qid not in existing:
                queries.append({
                    "id": qid,
                    "query": f"({topic})[All Fields]",
                    "purpose": "Search all fields",
                    "priority": 5
                })
                query_counter += 1
                    
        elif expansion_type == "narrower":
            qid = f"q{query_counter}_rct"
            if qid not in existing:
                queries.append({
                    "id": qid,
                    "query": f"({topic}) AND randomized controlled trial[pt]",
                    "purpose": "RCT only - high evidence",
                    "priority": 1
                })
                query_counter += 1
            
            qid = f"q{query_counter}_meta"
            if qid not in existing:
                queries.append({
                    "id": qid,
                    "query": f"({topic}) AND (meta-analysis[pt] OR systematic review[pt])",
                    "purpose": "Meta-analysis/Systematic Review",
                    "priority": 1
                })
                query_counter += 1
                
            current_year = datetime.now().year
            qid = f"q{query_counter}_recent"
            if qid not in existing:
                queries.append({
                    "id": qid,
                    "query": f"({topic})[Title] AND {current_year-2}:{current_year}[dp]",
                    "purpose": "Last 2 years only",
                    "priority": 2
                })
                query_counter += 1
        
        result = {
            "topic": topic,
            "expansion_type": expansion_type,
            "existing_queries": list(existing),
            "queries_count": len(queries),
            "queries": queries,
            "instruction": "Execute in PARALLEL, then merge_search_results with previous"
        }
        
        return json.dumps(result, indent=2, ensure_ascii=False)
