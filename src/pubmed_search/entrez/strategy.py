"""
Search Strategy Module - Intelligent query generation using NCBI APIs.

Uses:
- ESpell for spelling correction
- MeSH database for synonyms and related terms
- EInfo for query translation
"""

import logging
import time
from typing import List, Dict, Any, Optional, Tuple
from Bio import Entrez

logger = logging.getLogger(__name__)

# Retry settings for NCBI intermittent errors
MAX_RETRIES = 3
RETRY_DELAY = 1.0
RETRYABLE_ERRORS = [
    "Database is not supported",
    "Backend failed",
    "Server Error"
]


def _is_retryable(error: Exception) -> bool:
    """Check if an error is retryable."""
    error_str = str(error)
    return any(msg in error_str for msg in RETRYABLE_ERRORS)


class SearchStrategyGenerator:
    """
    Generates intelligent search strategies using NCBI APIs.
    
    Features:
    - Spelling correction via ESpell
    - MeSH term lookup for standardized vocabulary
    - Synonym expansion from MeSH
    - Query translation analysis
    """
    
    def __init__(self, email: str, api_key: Optional[str] = None):
        Entrez.email = email
        if api_key:
            Entrez.api_key = api_key
    
    def _retry_operation(self, operation, *args, **kwargs):
        """Execute operation with retry logic for NCBI intermittent errors."""
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                return operation(*args, **kwargs)
            except Exception as e:
                last_error = e
                if _is_retryable(e) and attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAY * (attempt + 1)
                    logger.warning(f"NCBI error (attempt {attempt+1}): {e}, retrying in {delay}s")
                    time.sleep(delay)
                else:
                    raise
        raise last_error
    
    def spell_check(self, query: str) -> Tuple[str, bool]:
        """
        Check and correct spelling using NCBI ESpell.
        
        Returns:
            Tuple of (corrected_query, was_corrected)
        """
        try:
            def _do_spell_check():
                handle = Entrez.espell(db="pubmed", term=query)
                result = Entrez.read(handle)
                handle.close()
                return result
            
            result = self._retry_operation(_do_spell_check)
            
            corrected = result.get("CorrectedQuery", "")
            if corrected and corrected != query:
                logger.info(f"Spelling correction: '{query}' → '{corrected}'")
                return corrected, True
            return query, False
        except Exception as e:
            logger.warning(f"ESpell failed: {e}")
            return query, False
    
    def get_mesh_info(self, term: str) -> Optional[Dict[str, Any]]:
        """
        Get MeSH information for a term including synonyms.
        
        Uses multiple search strategies for best results:
        1. First try term[MeSH Terms] for exact MeSH matching
        2. Fall back to quoted search if needed
        
        Returns:
            Dict with mesh_id, preferred_term, synonyms, tree_numbers
        """
        def _search_mesh_exact():
            """Try exact MeSH term search first."""
            handle = Entrez.esearch(db="mesh", term=f'{term}[MeSH Terms]', retmax=1)
            result = Entrez.read(handle)
            handle.close()
            return result
        
        def _search_mesh_quoted():
            """Fall back to quoted search."""
            handle = Entrez.esearch(db="mesh", term=f'"{term}"', retmax=1)
            result = Entrez.read(handle)
            handle.close()
            return result
        
        def _fetch_mesh_text(mesh_id):
            # Use text mode - more reliable than XML
            handle = Entrez.efetch(db="mesh", id=mesh_id, rettype="full", retmode="text")
            content = handle.read()
            handle.close()
            return content
        
        def _parse_mesh_text(content: str) -> Dict[str, Any]:
            """Parse MeSH text format to extract info."""
            lines = content.strip().split('\n')
            
            result = {
                "preferred_term": "",
                "synonyms": [],
                "tree_numbers": [],
                "description": ""
            }
            
            # First line format: "1: Term Name"
            if lines and lines[0].strip().startswith("1:"):
                # Extract term name after "1:"
                first_line = lines[0].strip()
                result["preferred_term"] = first_line[2:].strip()
            
            # Parse Entry Terms section
            in_entry_terms = False
            for line in lines:
                if "Entry Terms:" in line:
                    in_entry_terms = True
                    continue
                if in_entry_terms:
                    stripped = line.strip()
                    # Stop at empty line or new section
                    if not stripped or stripped.startswith("Previous") or stripped.startswith("All MeSH"):
                        in_entry_terms = False
                        continue
                    if stripped:
                        result["synonyms"].append(stripped)
            
            # Parse Tree Numbers - format: "Tree Number(s): E03.295"
            for line in lines:
                if line.strip().startswith("Tree Number(s):"):
                    # Tree number is on same line after colon
                    parts = line.split(":", 1)
                    if len(parts) > 1:
                        tree_str = parts[1].strip()
                        result["tree_numbers"] = [t.strip() for t in tree_str.split(',') if t.strip()]
                    break
            
            return result
        
        try:
            # Strategy 1: Try exact MeSH term search first
            result = self._retry_operation(_search_mesh_exact)
            mesh_ids = result.get("IdList", [])
            
            # Strategy 2: Fall back to quoted search
            if not mesh_ids:
                result = self._retry_operation(_search_mesh_quoted)
                mesh_ids = result.get("IdList", [])
            
            if not mesh_ids:
                return None
            
            mesh_id = mesh_ids[0]
            
            # Fetch MeSH record in text mode with retry
            content = self._retry_operation(_fetch_mesh_text, mesh_id)
            
            if not content:
                return None
            
            # Parse the text content
            parsed = _parse_mesh_text(content)
            
            return {
                "mesh_id": mesh_id,
                "preferred_term": parsed["preferred_term"] or term,
                "synonyms": parsed["synonyms"][:10],  # Limit to 10
                "tree_numbers": parsed["tree_numbers"]
            }
            
        except Exception as e:
            logger.warning(f"MeSH lookup failed for '{term}': {e}")
            return None
    
    def analyze_query(self, query: str) -> Dict[str, Any]:
        """
        Analyze how PubMed interprets a query using ESearch translation.
        
        Returns:
            Dict with translated_query, query_translation breakdown
        """
        def _do_esearch():
            handle = Entrez.esearch(
                db="pubmed", 
                term=query, 
                retmax=0,  # Don't need results, just translation
                usehistory="n"
            )
            result = Entrez.read(handle)
            handle.close()
            return result
        
        try:
            result = self._retry_operation(_do_esearch)
            
            return {
                "original": query,
                "count": int(result.get("Count", 0)),
                "translated_query": result.get("QueryTranslation", query),
                "translation_set": result.get("TranslationSet", []),
                "translation_stack": result.get("TranslationStack", [])
            }
        except Exception as e:
            logger.warning(f"Query analysis failed: {e}")
            return {"original": query, "count": 0}
    
    def generate_strategies(
        self, 
        topic: str,
        strategy: str = "comprehensive",
        use_mesh: bool = True,
        check_spelling: bool = True,
        include_suggestions: bool = True,
        analyze_queries: bool = True
    ) -> Dict[str, Any]:
        """
        Gather search intelligence for a topic - returns RAW MATERIALS for Agent to decide.
        
        The Agent (or a lightweight LLM like minimind) can decide how to use these materials:
        - Use mesh_terms to build MeSH queries
        - Use synonyms for query expansion  
        - Use corrected spelling or not
        - Generate its own query combinations
        
        NEW: When analyze_queries=True, each suggested query includes:
        - estimated_count: How many results PubMed would return
        - pubmed_translation: How PubMed actually interprets the query
        
        This helps the Agent understand the difference between:
        - What the Agent thinks the query means
        - What PubMed actually searches for
        
        Args:
            topic: Research topic
            strategy: "comprehensive", "focused", or "exploratory" (for suggestions)
            use_mesh: Whether to lookup MeSH terms
            check_spelling: Whether to check spelling
            include_suggestions: Whether to include pre-built query suggestions
            analyze_queries: Whether to analyze how PubMed interprets each query
            
        Returns:
            Dict with raw materials (spelling, mesh_terms, keywords) and optional suggestions
        """
        result = {
            "topic": topic,
            "corrected_topic": topic,  # May be updated by spell check
            "spelling": None,
            "keywords": [],      # Extracted keywords from topic
            "mesh_terms": [],    # MeSH data for Agent to use
            "all_synonyms": [],  # Flattened list of all synonyms
            # Optional: pre-built suggestions (Agent can ignore)
            "suggested_queries": [] if include_suggestions else None
        }
        
        # Step 1: Spell check
        working_topic = topic
        if check_spelling:
            corrected, was_corrected = self.spell_check(topic)
            result["spelling"] = {
                "original": topic,
                "corrected": corrected,
                "was_corrected": was_corrected
            }
            if was_corrected:
                working_topic = corrected
                result["corrected_topic"] = corrected
        
        # Step 2: Extract key terms and lookup MeSH
        words = working_topic.split()
        mesh_data = {}
        stop_words = {"and", "or", "the", "in", "of", "for", "with", "to", "a", "an", "icu"}
        
        if use_mesh:
            # Try full topic first
            full_mesh = self.get_mesh_info(working_topic)
            if full_mesh:
                mesh_data[working_topic] = full_mesh
                result["mesh_terms"].append({
                    "input": working_topic,
                    "preferred": full_mesh["preferred_term"],
                    "synonyms": full_mesh["synonyms"][:5]
                })
            
            # Try bigrams (two-word phrases) - often match MeSH better
            # e.g. "mechanical ventilation" instead of just "mechanical"
            for i in range(len(words) - 1):
                bigram = f"{words[i]} {words[i+1]}"
                if bigram.lower() not in stop_words:
                    bigram_mesh = self.get_mesh_info(bigram)
                    if bigram_mesh and bigram not in mesh_data:
                        mesh_data[bigram] = bigram_mesh
                        result["mesh_terms"].append({
                            "input": bigram,
                            "preferred": bigram_mesh["preferred_term"],
                            "synonyms": bigram_mesh["synonyms"][:3]
                        })
            
            # Try individual significant words (if not covered by bigrams)
            covered_words = set()
            for key in mesh_data.keys():
                covered_words.update(key.lower().split())
            
            for word in words:
                if len(word) > 3 and word.lower() not in stop_words and word.lower() not in covered_words:
                    word_mesh = self.get_mesh_info(word)
                    if word_mesh and word not in mesh_data:
                        mesh_data[word] = word_mesh
                        result["mesh_terms"].append({
                            "input": word,
                            "preferred": word_mesh["preferred_term"],
                            "synonyms": word_mesh["synonyms"][:3]
                        })
        
        # Extract keywords for Agent to use
        result["keywords"] = [w for w in words if w.lower() not in stop_words and len(w) > 2]
        
        # Flatten all synonyms for easy access
        all_synonyms = []
        for mesh in result["mesh_terms"]:
            all_synonyms.extend(mesh.get("synonyms", []))
        result["all_synonyms"] = list(set(all_synonyms))[:15]  # Dedupe, limit
        
        # Step 3: Generate suggested queries (optional - Agent can ignore or use as reference)
        if not include_suggestions:
            return result
            
        queries = []
        query_id = 1
        
        # Basic queries
        queries.append({
            "id": f"q{query_id}_title",
            "query": f"({working_topic})[Title]",
            "purpose": "Exact title match - highest precision",
            "priority": 1
        })
        query_id += 1
        
        queries.append({
            "id": f"q{query_id}_tiab",
            "query": f"({working_topic})[Title/Abstract]",
            "purpose": "Title or abstract - balanced",
            "priority": 2
        })
        query_id += 1
        
        # AND query with all words
        if len(words) > 1:
            and_query = " AND ".join(words)
            queries.append({
                "id": f"q{query_id}_and",
                "query": f"({and_query})",
                "purpose": "All keywords required",
                "priority": 2
            })
            query_id += 1
        
        # MeSH-based queries
        if mesh_data:
            # Use preferred MeSH terms
            for term, data in list(mesh_data.items())[:2]:
                preferred = data["preferred_term"]
                if preferred != term:
                    queries.append({
                        "id": f"q{query_id}_mesh",
                        "query": f'"{preferred}"[MeSH Terms]',
                        "purpose": f"MeSH standardized: {term} → {preferred}",
                        "priority": 2
                    })
                    query_id += 1
            
            # Use synonyms for expansion
            if strategy in ["comprehensive", "exploratory"]:
                for term, data in list(mesh_data.items())[:1]:
                    synonyms = data.get("synonyms", [])[:2]
                    for syn in synonyms:
                        queries.append({
                            "id": f"q{query_id}_syn",
                            "query": f"({syn})[Title/Abstract]",
                            "purpose": f"MeSH synonym: {term} → {syn}",
                            "priority": 3
                        })
                        query_id += 1
        
        # Strategy-specific queries
        if strategy == "comprehensive":
            # Add review filter
            queries.append({
                "id": f"q{query_id}_review",
                "query": f"({working_topic}) AND (review[pt] OR systematic review[pt])",
                "purpose": "Review articles only",
                "priority": 3
            })
            query_id += 1
        
        if strategy == "exploratory":
            # Broader search
            if len(words) >= 2:
                queries.append({
                    "id": f"q{query_id}_broad",
                    "query": f"({words[0]})[Title] AND ({' OR '.join(words[1:])})",
                    "purpose": "Broader: main term + any modifier",
                    "priority": 4
                })
                query_id += 1
        
        if strategy == "focused":
            # Add RCT filter for high-quality evidence
            queries.append({
                "id": f"q{query_id}_rct",
                "query": f"({working_topic}) AND (randomized controlled trial[pt])",
                "purpose": "RCT only - highest evidence",
                "priority": 1
            })
            query_id += 1
        
        # Step 4: Analyze how PubMed interprets each query (optional but recommended)
        if analyze_queries:
            for q in queries:
                try:
                    analysis = self.analyze_query(q["query"])
                    q["estimated_count"] = analysis.get("count", 0)
                    q["pubmed_translation"] = analysis.get("translated_query", q["query"])
                except Exception as e:
                    logger.warning(f"Query analysis failed for {q['id']}: {e}")
                    q["estimated_count"] = None
                    q["pubmed_translation"] = None
        
        result["suggested_queries"] = queries
        
        return result
    
    def expand_with_mesh(
        self,
        topic: str,
        existing_queries: List[str]
    ) -> Dict[str, Any]:
        """
        Generate expansion queries using MeSH relationships.
        
        Args:
            topic: Original topic
            existing_queries: List of already-used query IDs
            
        Returns:
            New queries for expansion
        """
        result = {
            "topic": topic,
            "expansion_type": "mesh_based",
            "queries": []
        }
        
        existing_set = set(existing_queries)
        query_id = len(existing_set) + 1
        
        # Get MeSH info
        mesh_info = self.get_mesh_info(topic)
        
        if mesh_info:
            # Use remaining synonyms
            for syn in mesh_info.get("synonyms", [])[5:10]:
                qid = f"q{query_id}_exp_syn"
                if qid not in existing_set:
                    result["queries"].append({
                        "id": qid,
                        "query": f"({syn})[Title/Abstract]",
                        "purpose": f"Expanded synonym: {syn}",
                        "priority": 4
                    })
                    query_id += 1
        
        # Try related terms for individual words
        words = topic.split()
        for word in words[:2]:
            if len(word) > 4:
                word_mesh = self.get_mesh_info(word)
                if word_mesh:
                    for syn in word_mesh.get("synonyms", [])[:2]:
                        new_topic = topic.replace(word, syn)
                        qid = f"q{query_id}_exp_word"
                        if qid not in existing_set:
                            result["queries"].append({
                                "id": qid,
                                "query": f"({new_topic})[Title/Abstract]",
                                "purpose": f"Word expansion: {word} → {syn}",
                                "priority": 4
                            })
                            query_id += 1
        
        result["queries_count"] = len(result["queries"])
        return result
