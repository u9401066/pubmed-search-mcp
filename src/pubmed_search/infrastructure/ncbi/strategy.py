"""
Search Strategy Module - Intelligent query generation using NCBI APIs.

Uses:
- ESpell for spelling correction
- MeSH database for synonyms and related terms
- EInfo for query translation
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from Bio import Entrez

from .base import (
    DEFAULT_ENTREZ_TOOL,
    NCBIInfrastructureError,
    execute_entrez_operation,
    raise_ncbi_infrastructure_error,
    run_entrez_callable,
)

logger = logging.getLogger(__name__)

# Retry settings for NCBI intermittent errors
MAX_RETRIES = 3
RETRY_DELAY = 1.0


async def _read_entrez_handle(handle: Any) -> Any:
    """Read an Entrez handle and close it even if parsing fails."""
    try:
        return await asyncio.to_thread(Entrez.read, handle)
    finally:
        handle.close()


async def _read_text_handle(handle: Any) -> str:
    """Read text from an Entrez handle and close it even on failure."""
    try:
        return await asyncio.to_thread(handle.read)
    finally:
        handle.close()


class SearchStrategyGenerator:
    """
    Generates intelligent search strategies using NCBI APIs.

    Features:
    - Spelling correction via ESpell
    - MeSH term lookup for standardized vocabulary
    - Synonym expansion from MeSH
    - Query translation analysis
    """

    def __init__(self, email: str, api_key: str | None = None):
        # NOTE: Entrez global state is not set here; run_entrez_callable() handles
        # per-call snapshot/set/restore under a threading lock.
        self._email = email
        self._api_key = api_key
        self._tool = DEFAULT_ENTREZ_TOOL

    async def _execute_entrez(self, operation, *, service_name: str, timeout: float = 45.0):
        return await execute_entrez_operation(
            operation,
            api_key=self._api_key,
            service_name=service_name,
            timeout=timeout,
            max_attempts=MAX_RETRIES,
            base_delay=RETRY_DELAY,
        )

    async def spell_check(self, query: str) -> tuple[str, bool]:
        """
        Check and correct spelling using NCBI ESpell.

        Returns:
            Tuple of (corrected_query, was_corrected)
        """

        async def _do_spell_check():
            handle = await asyncio.to_thread(
                run_entrez_callable,
                Entrez,
                Entrez.espell,
                db="pubmed",
                term=query,
                email=self._email,
                api_key=self._api_key,
                tool=self._tool,
            )
            return await _read_entrez_handle(handle)

        try:
            result = await self._execute_entrez(_do_spell_check, service_name="ncbi-strategy:espell")
        except Exception as exc:
            raise_ncbi_infrastructure_error("strategy_spell_check", exc)

        try:
            corrected = result.get("CorrectedQuery", "")
        except (AttributeError, TypeError, ValueError) as exc:
            raise_ncbi_infrastructure_error("strategy spelling response", exc)
        if corrected and corrected != query:
            logger.info(
                "NCBI spelling correction applied (input_length=%s, output_length=%s)",
                len(query),
                len(corrected),
            )
            return corrected, True
        return query, False

    async def get_mesh_info(self, term: str) -> dict[str, Any] | None:
        """
        Get MeSH information for a term including synonyms.

        Uses multiple search strategies for best results:
        1. First try term[MeSH Terms] for exact MeSH matching
        2. Fall back to quoted search if needed

        Returns:
            Dict with mesh_id, preferred_term, synonyms, tree_numbers
        """

        async def _search_mesh_exact():
            """Try exact MeSH term search first."""
            handle = await asyncio.to_thread(
                run_entrez_callable,
                Entrez,
                Entrez.esearch,
                db="mesh",
                term=f"{term}[MeSH Terms]",
                retmax=1,
                email=self._email,
                api_key=self._api_key,
                tool=self._tool,
            )
            return await _read_entrez_handle(handle)

        async def _search_mesh_quoted():
            """Fall back to quoted search."""
            handle = await asyncio.to_thread(
                run_entrez_callable,
                Entrez,
                Entrez.esearch,
                db="mesh",
                term=f'"{term}"',
                retmax=1,
                email=self._email,
                api_key=self._api_key,
                tool=self._tool,
            )
            return await _read_entrez_handle(handle)

        async def _fetch_mesh_text(mesh_id):
            # Use text mode - more reliable than XML
            handle = await asyncio.to_thread(
                run_entrez_callable,
                Entrez,
                Entrez.efetch,
                db="mesh",
                id=mesh_id,
                rettype="full",
                retmode="text",
                email=self._email,
                api_key=self._api_key,
                tool=self._tool,
            )
            return await _read_text_handle(handle)

        def _parse_mesh_text(content: str) -> dict[str, Any]:
            """Parse MeSH text format to extract info."""
            lines = content.strip().split("\n")

            result: dict[str, Any] = {
                "preferred_term": "",
                "synonyms": [],
                "tree_numbers": [],
                "description": "",
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
                    if not stripped or stripped.startswith(("Previous", "All MeSH")):
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
                        result["tree_numbers"] = [t.strip() for t in tree_str.split(",") if t.strip()]
                    break

            return result

        # Strategy 1: Try exact MeSH term search first.
        try:
            result = await self._execute_entrez(
                _search_mesh_exact,
                service_name="ncbi-strategy:mesh-esearch",
            )
        except Exception as exc:
            raise_ncbi_infrastructure_error("strategy_mesh_lookup", exc)
        try:
            mesh_ids = result.get("IdList", [])
        except (AttributeError, TypeError, ValueError) as exc:
            raise_ncbi_infrastructure_error("strategy MeSH search response", exc)

        # Strategy 2: Fall back to quoted search. A provider failure raises;
        # only a successful pair of empty searches means "no matching term".
        if not mesh_ids:
            try:
                result = await self._execute_entrez(
                    _search_mesh_quoted,
                    service_name="ncbi-strategy:mesh-esearch",
                )
            except Exception as exc:
                raise_ncbi_infrastructure_error("strategy_mesh_lookup", exc)
            try:
                mesh_ids = result.get("IdList", [])
            except (AttributeError, TypeError, ValueError) as exc:
                raise_ncbi_infrastructure_error("strategy MeSH search response", exc)

        if not mesh_ids:
            return None

        mesh_id = mesh_ids[0]
        try:
            content = await self._execute_entrez(
                lambda: _fetch_mesh_text(mesh_id),
                service_name="ncbi-strategy:mesh-efetch",
                timeout=60.0,
            )
        except Exception as exc:
            raise_ncbi_infrastructure_error("strategy_mesh_lookup", exc)
        if not content:
            return None

        try:
            parsed = _parse_mesh_text(content)
        except (AttributeError, TypeError, ValueError) as exc:
            raise_ncbi_infrastructure_error("strategy MeSH fetch response", exc)
        return {
            "mesh_id": mesh_id,
            "preferred_term": parsed["preferred_term"] or term,
            "synonyms": parsed["synonyms"][:10],
            "tree_numbers": parsed["tree_numbers"],
        }

    async def analyze_query(self, query: str) -> dict[str, Any]:
        """
        Analyze how PubMed interprets a query using ESearch translation.

        Returns:
            Dict with translated_query, query_translation breakdown
        """

        async def _do_esearch():
            handle = await asyncio.to_thread(
                run_entrez_callable,
                Entrez,
                Entrez.esearch,
                db="pubmed",
                term=query,
                retmax=0,  # Don't need results, just translation
                usehistory="n",
                email=self._email,
                api_key=self._api_key,
                tool=self._tool,
            )
            return await _read_entrez_handle(handle)

        try:
            result = await self._execute_entrez(_do_esearch, service_name="ncbi-strategy:analyze-query")
        except Exception as exc:
            raise_ncbi_infrastructure_error("strategy_query_analysis", exc)

        try:
            return {
                "original": query,
                "count": int(result.get("Count", 0)),
                "translated_query": result.get("QueryTranslation", query),
                "translation_set": result.get("TranslationSet", []),
                "translation_stack": result.get("TranslationStack", []),
            }
        except (AttributeError, TypeError, ValueError) as exc:
            raise_ncbi_infrastructure_error("strategy query-analysis response", exc)

    async def generate_strategies(
        self,
        topic: str,
        strategy: str = "comprehensive",
        use_mesh: bool = True,
        check_spelling: bool = True,
        include_suggestions: bool = True,
        analyze_queries: bool = True,
    ) -> dict[str, Any]:
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
        result: dict[str, Any] = {
            "topic": topic,
            "corrected_topic": topic,  # May be updated by spell check
            "spelling": None,
            "keywords": [],  # Extracted keywords from topic
            "mesh_terms": [],  # MeSH data for Agent to use
            "all_synonyms": [],  # Flattened list of all synonyms
            # Optional: pre-built suggestions (Agent can ignore)
            "suggested_queries": [] if include_suggestions else None,
            "coverage": {
                "spelling": {
                    "status": "pending" if check_spelling else "disabled",
                    "attempted": 0,
                    "completed": 0,
                    "failed": 0,
                },
                "mesh": {
                    "status": "pending" if use_mesh else "disabled",
                    "attempted": 0,
                    "completed": 0,
                    "failed": 0,
                    "matched": 0,
                },
                "query_analysis": {
                    "status": "pending" if include_suggestions and analyze_queries else "disabled",
                    "attempted": 0,
                    "completed": 0,
                    "failed": 0,
                },
            },
            "warnings": [],
        }

        # Step 1: Spell check
        working_topic = topic
        if check_spelling:
            try:
                corrected, was_corrected = await self.spell_check(topic)
            except NCBIInfrastructureError:
                result["coverage"]["spelling"] = {
                    "status": "failed",
                    "attempted": 1,
                    "completed": 0,
                    "failed": 1,
                }
                result["warnings"].append("NCBI spelling analysis was unavailable.")
            else:
                result["spelling"] = {
                    "original": topic,
                    "corrected": corrected,
                    "was_corrected": was_corrected,
                }
                result["coverage"]["spelling"] = {
                    "status": "completed",
                    "attempted": 1,
                    "completed": 1,
                    "failed": 0,
                    "corrected": was_corrected,
                }
                if was_corrected:
                    working_topic = corrected
                    result["corrected_topic"] = corrected

        # Step 2: Extract key terms and lookup MeSH
        words = working_topic.split()
        mesh_data = {}
        stop_words = {
            "and",
            "or",
            "the",
            "in",
            "of",
            "for",
            "with",
            "to",
            "a",
            "an",
        }

        if use_mesh:
            mesh_lookups = 0
            mesh_completed = 0
            mesh_failures = 0
            mesh_available = True

            async def _lookup_mesh(term: str) -> dict[str, Any] | None:
                nonlocal mesh_available, mesh_completed, mesh_failures, mesh_lookups
                if not mesh_available:
                    return None
                mesh_lookups += 1
                try:
                    mesh_info = await self.get_mesh_info(term)
                except NCBIInfrastructureError:
                    mesh_failures += 1
                    mesh_available = False
                    return None
                mesh_completed += 1
                return mesh_info

            # Try full topic first
            full_mesh = await _lookup_mesh(working_topic)
            if full_mesh:
                mesh_data[working_topic] = full_mesh
                result["mesh_terms"].append(
                    {
                        "input": working_topic,
                        "preferred": full_mesh["preferred_term"],
                        "synonyms": full_mesh["synonyms"][:5],
                    }
                )

            # Try bigrams (two-word phrases) - often match MeSH better
            # e.g. "mechanical ventilation" instead of just "mechanical"
            for i in range(len(words) - 1):
                bigram = f"{words[i]} {words[i + 1]}"
                if bigram.lower() not in stop_words:
                    bigram_mesh = await _lookup_mesh(bigram)
                    if bigram_mesh and bigram not in mesh_data:
                        mesh_data[bigram] = bigram_mesh
                        result["mesh_terms"].append(
                            {
                                "input": bigram,
                                "preferred": bigram_mesh["preferred_term"],
                                "synonyms": bigram_mesh["synonyms"][:3],
                            }
                        )

            # Try individual significant words (if not covered by bigrams)
            covered_words = set()
            for key in mesh_data:
                covered_words.update(key.lower().split())

            for word in words:
                if len(word) > 3 and word.lower() not in stop_words and word.lower() not in covered_words:
                    word_mesh = await _lookup_mesh(word)
                    if word_mesh and word not in mesh_data:
                        mesh_data[word] = word_mesh
                        result["mesh_terms"].append(
                            {
                                "input": word,
                                "preferred": word_mesh["preferred_term"],
                                "synonyms": word_mesh["synonyms"][:3],
                            }
                        )
            result["coverage"]["mesh"] = {
                "status": ("completed" if not mesh_failures else "partial" if mesh_completed else "failed"),
                "attempted": mesh_lookups,
                "completed": mesh_completed,
                "failed": mesh_failures,
                "matched": len(mesh_data),
            }
            if mesh_failures:
                result["warnings"].append("NCBI MeSH analysis was unavailable for one or more terms.")

        # Extract keywords for Agent to use
        result["keywords"] = [w for w in words if w.lower() not in stop_words and len(w) > 2]

        # Flatten all synonyms for easy access
        all_synonyms = []
        for mesh in result["mesh_terms"]:
            all_synonyms.extend(mesh.get("synonyms", []))
        result["all_synonyms"] = list(dict.fromkeys(all_synonyms))[:15]  # Dedupe, limit

        # Step 3: Generate suggested queries (optional - Agent can ignore or use as reference)
        if not include_suggestions:
            return result

        queries = []
        query_id = 1

        # Basic queries
        queries.append(
            {
                "id": f"q{query_id}_title",
                "query": f"({working_topic})[Title]",
                "purpose": "Exact title match - highest precision",
                "priority": 1,
            }
        )
        query_id += 1

        queries.append(
            {
                "id": f"q{query_id}_tiab",
                "query": f"({working_topic})[Title/Abstract]",
                "purpose": "Title or abstract - balanced",
                "priority": 2,
            }
        )
        query_id += 1

        # AND query with all words
        if len(words) > 1:
            and_query = " AND ".join(words)
            queries.append(
                {
                    "id": f"q{query_id}_and",
                    "query": f"({and_query})",
                    "purpose": "All keywords required",
                    "priority": 2,
                }
            )
            query_id += 1

        # MeSH-based queries
        if mesh_data:
            # Use preferred MeSH terms
            for term, data in list(mesh_data.items())[:2]:
                preferred = data["preferred_term"]
                if preferred != term:
                    queries.append(
                        {
                            "id": f"q{query_id}_mesh",
                            "query": f'"{preferred}"[MeSH Terms]',
                            "purpose": f"MeSH standardized: {term} → {preferred}",
                            "priority": 2,
                        }
                    )
                    query_id += 1

            # Use synonyms for expansion
            if strategy in ["comprehensive", "exploratory"]:
                for term, data in list(mesh_data.items())[:1]:
                    synonyms = data.get("synonyms", [])[:2]
                    for syn in synonyms:
                        queries.append(
                            {
                                "id": f"q{query_id}_syn",
                                "query": f"({syn})[Title/Abstract]",
                                "purpose": f"MeSH synonym: {term} → {syn}",
                                "priority": 3,
                            }
                        )
                        query_id += 1

        # Strategy-specific queries
        if strategy == "comprehensive":
            # Add review filter
            queries.append(
                {
                    "id": f"q{query_id}_review",
                    "query": f"({working_topic}) AND (review[pt] OR systematic review[pt])",
                    "purpose": "Review articles only",
                    "priority": 3,
                }
            )
            query_id += 1

        if strategy == "exploratory" and len(words) >= 2:
            # Broader search
            queries.append(
                {
                    "id": f"q{query_id}_broad",
                    "query": f"({words[0]})[Title] AND ({' OR '.join(words[1:])})",
                    "purpose": "Broader: main term + any modifier",
                    "priority": 4,
                }
            )
            query_id += 1

        if strategy == "focused":
            # Add RCT filter for high-quality evidence
            queries.append(
                {
                    "id": f"q{query_id}_rct",
                    "query": f"({working_topic}) AND (randomized controlled trial[pt])",
                    "purpose": "Randomized controlled trial publication type; quality not assessed",
                    "priority": 1,
                }
            )
            query_id += 1

        # Step 4: Analyze how PubMed interprets each query (optional but recommended)
        if analyze_queries:
            completed_analyses = 0
            failed_analyses = 0
            for q in queries:
                try:
                    analysis = await self.analyze_query(str(q["query"]))
                    q["estimated_count"] = analysis.get("count", 0)
                    q["pubmed_translation"] = analysis.get("translated_query", q["query"])
                    completed_analyses += 1
                except NCBIInfrastructureError as exc:
                    logger.warning("Suggested-query analysis failed (%s)", type(exc).__name__)
                    q["estimated_count"] = None
                    q["pubmed_translation"] = None
                    failed_analyses += 1
            result["coverage"]["query_analysis"] = {
                "status": "completed" if not failed_analyses else "partial" if completed_analyses else "failed",
                "attempted": len(queries),
                "completed": completed_analyses,
                "failed": failed_analyses,
            }
            if failed_analyses:
                result["warnings"].append(
                    "PubMed translation analysis was unavailable for one or more suggested queries."
                )

        result["suggested_queries"] = queries

        return result

    async def expand_with_mesh(self, topic: str, existing_queries: list[str]) -> dict[str, Any]:
        """
        Generate expansion queries using MeSH relationships.

        Args:
            topic: Original topic
            existing_queries: List of already-used query IDs

        Returns:
            New queries for expansion
        """
        result: dict[str, Any] = {"topic": topic, "expansion_type": "mesh_based", "queries": []}

        existing_set = set(existing_queries)
        query_id = 1
        # Reserve both generated suffixes before allocating the next numeric ID.
        while any(f"q{query_id}_{suffix}" in existing_set for suffix in ("exp_syn", "exp_word")):
            query_id += 1

        # Get MeSH info
        mesh_info = await self.get_mesh_info(topic)

        if mesh_info:
            # Use remaining synonyms
            for syn in mesh_info.get("synonyms", [])[5:10]:
                while f"q{query_id}_exp_syn" in existing_set:
                    query_id += 1
                qid = f"q{query_id}_exp_syn"
                if qid not in existing_set:
                    result["queries"].append(
                        {
                            "id": qid,
                            "query": f"({syn})[Title/Abstract]",
                            "purpose": f"Expanded synonym: {syn}",
                            "priority": 4,
                        }
                    )
                    query_id += 1

        # Try related terms for individual words
        words = topic.split()
        for word in words[:2]:
            if len(word) > 4:
                word_mesh = await self.get_mesh_info(word)
                if word_mesh:
                    for syn in word_mesh.get("synonyms", [])[:2]:
                        new_topic = topic.replace(word, syn)
                        while f"q{query_id}_exp_word" in existing_set:
                            query_id += 1
                        qid = f"q{query_id}_exp_word"
                        if qid not in existing_set:
                            result["queries"].append(
                                {
                                    "id": qid,
                                    "query": f"({new_topic})[Title/Abstract]",
                                    "purpose": f"Word expansion: {word} → {syn}",
                                    "priority": 4,
                                }
                            )
                            query_id += 1

        result["queries_count"] = len(result["queries"])
        return result
