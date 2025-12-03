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

logger = logging.getLogger(__name__)

# Global reference for session manager (set by server.py after initialization)
_session_manager = None


def set_session_manager(session_manager):
    """Set the session manager for automatic caching."""
    global _session_manager
    _session_manager = session_manager


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
        include_mesh: bool = True
    ) -> str:
        """
        Generate multiple search queries for a topic for parallel searching.
        
        This tool returns multiple search queries. The Agent should call search_literature
        in parallel for each query, then use merge_search_results to combine results.
        
        Args:
            topic: Search topic (e.g., "remimazolam ICU sedation")
            strategy: Search strategy
                - "comprehensive": Full search, multiple angles
                - "focused": Fewer but more precise queries
                - "exploratory": Broader related concepts
            include_mesh: Whether to include MeSH terms search
            
        Returns:
            JSON with multiple queries for parallel execution
        """
        logger.info(f"Generating search queries for topic: {topic}, strategy: {strategy}")
        
        words = topic.lower().split()
        queries = []
        
        # Query 1: Exact title search
        queries.append({
            "id": "q1_title",
            "query": f"({topic})[Title]",
            "purpose": "Exact title match",
            "expected": "High relevance, fewer results"
        })
        
        # Query 2: Title/Abstract search
        queries.append({
            "id": "q2_tiab",
            "query": f"({topic})[Title/Abstract]",
            "purpose": "Title or abstract contains keywords",
            "expected": "Medium relevance, moderate results"
        })
        
        # Query 3: AND query
        and_query = " AND ".join(words)
        queries.append({
            "id": "q3_and",
            "query": f"({and_query})",
            "purpose": "All keywords must appear",
            "expected": "Strict filtering"
        })
        
        if strategy in ["comprehensive", "exploratory"]:
            if len(words) >= 2:
                main_word = words[0]
                context_words = " OR ".join(words[1:])
                queries.append({
                    "id": "q4_partial",
                    "query": f"({main_word} AND ({context_words}))",
                    "purpose": "Main keyword + any context word",
                    "expected": "Looser matching"
                })
        
        if include_mesh:
            queries.append({
                "id": "q5_mesh",
                "query": f"({topic})[MeSH Terms]",
                "purpose": "MeSH standardized terms",
                "expected": "Medical concept standardized match"
            })
        
        if strategy == "exploratory":
            queries.append({
                "id": "q6_review",
                "query": f"({words[0]})[Title] AND review[Publication Type]",
                "purpose": "Find related Review articles",
                "expected": "Overview of the field"
            })
        
        result = {
            "topic": topic,
            "strategy": strategy,
            "queries_count": len(queries),
            "queries": queries,
            "instruction": "Call search_literature in parallel for each query, then call merge_search_results to combine.",
            "example": {
                "parallel_calls": [
                    f"search_literature(query=\"{q['query']}\", limit=20)" 
                    for q in queries[:2]
                ] + ["..."]
            }
        }
        
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    def merge_search_results(results_json: str) -> str:
        """
        Merge multiple search results and remove duplicates.
        
        After running multiple search_literature calls in parallel, use this tool to merge results.
        
        Args:
            results_json: JSON array of search results, each containing:
                - query_id: Search ID (from generate_search_queries)
                - pmids: List of PMIDs
                
                Example:
                [
                    {"query_id": "q1_title", "pmids": ["12345", "67890"]},
                    {"query_id": "q2_tiab", "pmids": ["67890", "11111"]}
                ]
                
        Returns:
            Merged results with deduplicated PMID list and source analysis
        """
        logger.info("Merging search results")
        
        try:
            results = json.loads(results_json)
        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON format - {e}"
        
        pmid_sources = {}
        all_pmids = []
        
        for result in results:
            query_id = result.get("query_id", "unknown")
            pmids = result.get("pmids", [])
            
            for pmid in pmids:
                pmid = str(pmid).strip()
                if pmid not in pmid_sources:
                    pmid_sources[pmid] = []
                    all_pmids.append(pmid)
                pmid_sources[pmid].append(query_id)
        
        multi_source = {pmid: sources for pmid, sources in pmid_sources.items() if len(sources) > 1}
        
        by_query = {}
        for result in results:
            query_id = result.get("query_id", "unknown")
            by_query[query_id] = len(result.get("pmids", []))
        
        output = {
            "total_unique": len(all_pmids),
            "total_with_duplicates": sum(by_query.values()),
            "duplicates_removed": sum(by_query.values()) - len(all_pmids),
            "by_query": by_query,
            "appeared_in_multiple_queries": {
                "count": len(multi_source),
                "pmids": list(multi_source.keys())[:10],
                "note": "These articles were found by multiple search strategies, likely more relevant"
            },
            "unique_pmids": all_pmids,
            "next_step": "Use fetch_article_details(pmids=...) to get detailed information"
        }
        
        return json.dumps(output, indent=2, ensure_ascii=False)

    @mcp.tool()
    def expand_search_queries(
        topic: str,
        existing_query_ids: str = "",
        expansion_type: str = "synonyms"
    ) -> str:
        """
        Expand search queries when initial results are insufficient.
        
        This tool generates additional search strategies that don't overlap with initial queries.
        
        Args:
            topic: Original search topic
            existing_query_ids: Comma-separated IDs of already executed queries
                              Example: "q1_title,q2_tiab,q3_and"
            expansion_type: Expansion type
                - "synonyms": Synonym expansion (e.g., sedation → conscious sedation)
                - "related": Related concepts (e.g., ICU → critical care)
                - "broader": Broader search (relax constraints)
                - "narrower": More precise search (add constraints like RCT only)
            
        Returns:
            New search queries for parallel execution
        """
        logger.info(f"Expanding search for topic: {topic}, type: {expansion_type}")
        
        existing = set(existing_query_ids.split(",")) if existing_query_ids else set()
        words = topic.lower().split()
        queries = []
        query_counter = len(existing) + 1
        
        if expansion_type == "synonyms":
            synonym_map = {
                "sedation": ["conscious sedation", "procedural sedation", "moderate sedation"],
                "icu": ["intensive care unit", "critical care unit", "CCU"],
                "anesthesia": ["anaesthesia", "anesthetic", "anaesthetic"],
                "pain": ["analgesia", "analgesic", "nociception"],
                "surgery": ["surgical", "operative", "perioperative"],
                "ventilation": ["mechanical ventilation", "respiratory support"],
                "hypotension": ["low blood pressure", "hemodynamic instability"],
                "mortality": ["death", "survival", "fatality"],
                "machine learning": ["ML", "artificial intelligence", "AI", "deep learning"],
            }
            
            for word in words:
                word_lower = word.lower()
                if word_lower in synonym_map:
                    for synonym in synonym_map[word_lower][:2]:
                        new_topic = topic.replace(word, synonym)
                        query_id = f"q{query_counter}_syn_{word_lower[:3]}"
                        if query_id not in existing:
                            queries.append({
                                "id": query_id,
                                "query": f"({new_topic})[Title/Abstract]",
                                "purpose": f"Synonym expansion: {word} → {synonym}",
                                "expected": "Find articles using different terminology"
                            })
                            query_counter += 1
                            
        elif expansion_type == "related":
            related_concepts = {
                "sedation": ["analgesia", "anxiolysis", "hypnotic"],
                "icu": ["emergency department", "operating room", "PACU"],
                "remimazolam": ["midazolam", "propofol", "dexmedetomidine"],
                "propofol": ["remimazolam", "etomidate", "ketamine"],
            }
            
            for word in words:
                word_lower = word.lower()
                if word_lower in related_concepts:
                    for related in related_concepts[word_lower][:2]:
                        other_words = [w for w in words if w.lower() != word_lower]
                        if other_words:
                            new_topic = f"{related} {' '.join(other_words)}"
                            query_id = f"q{query_counter}_rel_{word_lower[:3]}"
                            if query_id not in existing:
                                queries.append({
                                    "id": query_id,
                                    "query": f"({new_topic})[Title/Abstract]",
                                    "purpose": f"Related concept: {word} → {related}",
                                    "expected": "Find related but different topic articles"
                                })
                                query_counter += 1
                                
        elif expansion_type == "broader":
            if len(words) >= 2:
                or_query = " OR ".join(words)
                query_id = f"q{query_counter}_broad_or"
                if query_id not in existing:
                    queries.append({
                        "id": query_id,
                        "query": f"({or_query})[Title/Abstract]",
                        "purpose": "Broader search: any keyword",
                        "expected": "More results, may be less relevant"
                    })
                    query_counter += 1
            
            main_word = words[0]
            query_id = f"q{query_counter}_broad_main"
            if query_id not in existing:
                queries.append({
                    "id": query_id,
                    "query": f"({main_word})[Title]",
                    "purpose": f"Main keyword only: {main_word}",
                    "expected": "Broader results"
                })
                query_counter += 1
                    
        elif expansion_type == "narrower":
            query_id = f"q{query_counter}_narrow_rct"
            if query_id not in existing:
                queries.append({
                    "id": query_id,
                    "query": f"({topic})[Title] AND (randomized controlled trial[pt] OR RCT[tiab])",
                    "purpose": "RCT studies only",
                    "expected": "High quality evidence"
                })
                query_counter += 1
            
            query_id = f"q{query_counter}_narrow_meta"
            if query_id not in existing:
                queries.append({
                    "id": query_id,
                    "query": f"({topic})[Title/Abstract] AND (meta-analysis[pt] OR systematic review[pt])",
                    "purpose": "Meta-analysis/SR only",
                    "expected": "Synthesized evidence"
                })
                query_counter += 1
                
            current_year = datetime.now().year
            query_id = f"q{query_counter}_narrow_recent"
            if query_id not in existing:
                queries.append({
                    "id": query_id,
                    "query": f"({topic})[Title] AND ({current_year-2}:{current_year}[dp])",
                    "purpose": "Last 2 years only",
                    "expected": "Most recent research"
                })
                query_counter += 1
        
        if not queries:
            query_id = f"q{query_counter}_allfields"
            queries.append({
                "id": query_id,
                "query": f"({topic})[All Fields]",
                "purpose": "Search all fields",
                "expected": "Broadest possible search"
            })
        
        result = {
            "topic": topic,
            "expansion_type": expansion_type,
            "existing_queries": list(existing),
            "new_queries_count": len(queries),
            "queries": queries,
            "instruction": "Execute these new queries in parallel, then merge with previous results using merge_search_results",
            "available_expansion_types": [
                {"type": "synonyms", "description": "Synonym expansion"},
                {"type": "related", "description": "Related concepts"},
                {"type": "broader", "description": "Relax constraints"},
                {"type": "narrower", "description": "More precise search"},
            ]
        }
        
        return json.dumps(result, indent=2, ensure_ascii=False)
