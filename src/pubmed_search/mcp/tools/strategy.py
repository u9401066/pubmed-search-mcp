"""
Strategy Tools - Generate and expand search queries.

Tools:
- generate_search_queries: Generate multiple search strategies with MeSH expansion
- expand_search_queries: Expand search when results are insufficient
"""

import json
import logging
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from ...entrez import LiteratureSearcher
from ._common import get_strategy_generator

logger = logging.getLogger(__name__)


def register_strategy_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """Register search strategy tools."""
    
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
        
        ══════════════════════════════════════════════════════════════════════
        TWO USAGE MODES:
        ══════════════════════════════════════════════════════════════════════
        
        MODE 1: KEYWORD SEARCH (single topic)
        ─────────────────────────────────────
        User: "搜尋 remimazolam 的文獻"
        
        Step 1: generate_search_queries("remimazolam")
        Step 2: Build queries from returned materials
        Step 3: search_literature (parallel calls)
        Step 4: merge_search_results
        
        ══════════════════════════════════════════════════════════════════════
        
        MODE 2: PICO SEARCH (clinical question)
        ───────────────────────────────────────
        User: "remimazolam 在 ICU 鎮靜比 propofol 好嗎？會減少 delirium 嗎？"
        
        Step 1: Call parse_pico() to extract PICO elements
                → Returns: P=ICU patients, I=remimazolam, C=propofol, O=delirium
        
        Step 2: For EACH PICO element, call generate_search_queries() IN PARALLEL:
                - generate_search_queries("ICU patients")     → P materials
                - generate_search_queries("remimazolam")      → I materials  
                - generate_search_queries("propofol")         → C materials
                - generate_search_queries("delirium")         → O materials
        
        Step 3: Combine materials using Boolean logic:
                High precision: (P_terms) AND (I_terms) AND (C_terms) AND (O_terms)
                High recall:    (P_terms) AND (I_terms OR C_terms) AND (O_terms)
                
        Step 4: Add Clinical Query filter if appropriate:
                - therapy[filter]   → 治療效果比較
                - diagnosis[filter] → 診斷相關
                - prognosis[filter] → 預後相關
                - etiology[filter]  → 病因相關
        
        Step 5: search_literature (parallel calls with different strategies)
        Step 6: merge_search_results
        
        ══════════════════════════════════════════════════════════════════════
        
        Features:
        - Spelling correction via NCBI ESpell
        - MeSH term lookup for standardized vocabulary
        - Synonym expansion from MeSH database
        - **Query analysis**: Shows how PubMed actually interprets each query
          (Agent's understanding vs PubMed's actual interpretation)
        
        Args:
            topic: Search topic - can be a single keyword or PICO element
            strategy: Affects suggested_queries (if included)
                - "comprehensive": Multiple angles, includes reviews (default)
                - "focused": Adds RCT filter for high evidence
                - "exploratory": Broader search with more synonyms
            check_spelling: Whether to check/correct spelling (default: True)
            include_suggestions: Include pre-built query suggestions (default: True)
            
        Returns:
            JSON with RAW MATERIALS:
            - corrected_topic: Spell-checked topic
            - keywords: Extracted significant keywords
            - mesh_terms: MeSH data with preferred terms and synonyms
            - all_synonyms: Flattened list of all synonyms
            - suggested_queries: Optional pre-built queries with:
              - estimated_count: How many results PubMed would return
              - pubmed_translation: How PubMed actually interprets the query
        """
        logger.info(f"Generating search queries for topic: {topic}, strategy: {strategy}")
        
        _strategy_generator = get_strategy_generator()
        
        # Use intelligent strategy generator if available
        if _strategy_generator:
            try:
                result = _strategy_generator.generate_strategies(
                    topic=topic,
                    strategy=strategy,
                    use_mesh=True,
                    check_spelling=check_spelling,
                    include_suggestions=include_suggestions,
                    analyze_queries=True  # Enable PubMed query analysis
                )
                
                # Add usage hint (Agent can ignore)
                result["_hint"] = {
                    "usage": "Use mesh_terms and all_synonyms to build your own queries, or use suggested_queries as reference",
                    "example_mesh_query": '"{preferred_term}"[MeSH Terms]',
                    "example_synonym_query": '({synonym})[Title/Abstract]',
                    "note": "Check pubmed_translation to see how PubMed actually interprets each query"
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
            "suggested_queries": queries,
            "instruction": "Execute search_literature in PARALLEL for each query, then merge_search_results",
            "note": "Using fallback generator (MeSH lookup unavailable)"
        }
        
        return json.dumps(result, indent=2, ensure_ascii=False)

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
        
        _strategy_generator = get_strategy_generator()
        
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
            "suggested_queries": queries,
            "instruction": "Execute in PARALLEL, then merge_search_results with previous"
        }
        
        return json.dumps(result, indent=2, ensure_ascii=False)
