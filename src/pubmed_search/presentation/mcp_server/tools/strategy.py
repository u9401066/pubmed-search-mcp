"""Strategy tool for generating bounded query intelligence.

Tools:
- generate_search_queries: Generate multiple search strategies with MeSH expansion

"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field

from pubmed_search.application.search.query_materials import (
    attach_cooccurrence_candidates,
    build_fallback_query_materials,
)

from ._common import InputNormalizer, ResponseFormatter, get_mesh_correction_service, get_strategy_generator

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)

StrategyMode = Literal["comprehensive", "focused", "exploratory"]
StrategyTopic = Annotated[str, Field(min_length=1, max_length=2_000)]


def register_strategy_tools(mcp: MCPServer, searcher: LiteratureSearcher):
    """Register search strategy tools."""

    @mcp.tool()
    async def generate_search_queries(
        topic: StrategyTopic,
        strategy: StrategyMode = "comprehensive",
        check_spelling: bool = True,
        include_suggestions: bool = True,
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
        Step 2: Build a Boolean query from returned materials
        Step 3: analyze_search_query(query="<combined_boolean_query>")
        Step 4: unified_search(query="<combined_boolean_query>")

        ══════════════════════════════════════════════════════════════════════

        MODE 2: PICO SEARCH (clinical question)
        ───────────────────────────────────────
        User: "remimazolam 在 ICU 鎮靜比 propofol 好嗎？會減少 delirium 嗎？"

        Step 1: Agent extracts P/I/C/O from the clinical question, then calls
                validate_pico_plan(description=..., p=..., i=..., c=..., o=...) to
                validate the structured handoff and get a runnable PICO pipeline.

        Step 2: For EACH PICO element, call generate_search_queries() IN PARALLEL:
                - generate_search_queries("ICU patients")     → P materials
                - generate_search_queries("remimazolam")      → I materials
                - generate_search_queries("propofol")         → C materials
                - generate_search_queries("delirium")         → O materials

        Step 3: Combine materials using Boolean logic:
                High precision: (P_terms) AND (I_terms) AND (C_terms) AND (O_terms)
                Recall-oriented: (P_terms) AND (I_terms OR C_terms); validate against eligible seed papers

        Step 4: Add Clinical Query filter if appropriate:
                - filters="clinical_query:therapy"   → 治療效果比較
                - filters="clinical_query:diagnosis" → 診斷相關
                - filters="clinical_query:prognosis" → 預後相關
                - filters="clinical_query:etiology"  → 病因相關

            Step 5: Validate the final query with analyze_search_query()
            Step 6: Execute unified_search() with the final Boolean query

        ══════════════════════════════════════════════════════════════════════

        Features:
        - Spelling correction via NCBI ESpell
        - MeSH lookup of stopword-bounded topic phrases, longest first; a phrase
          maps only when it equals a record's preferred term or an entry term
          (ignoring case, hyphen spacing and simple plurals)
        - Synonym expansion from confirmed MeSH records
        - Data-driven MeSH candidates for up to 2 unmapped phrases (multi-word
          first): MeSH headings most often indexed on MEDLINE records that use
          the phrase in title/abstract, after removing check tags (Humans,
          Male, Adult...) and study-design headings, ranked by the F1 of
          share (recall) and estimated precision. Bounded NCBI traffic:
          one search, one MEDLINE fetch and up to 8 heading counts per phrase,
          at most 16 requests per call; see coverage.mesh_cooccurrence.
        - **Query analysis**: Shows how PubMed actually interprets each query
          (Agent's understanding vs PubMed's actual interpretation)

        Args:
            topic: Search topic - can be a single keyword or PICO element
            strategy: Affects suggested_queries (if included)
                - "comprehensive": Multiple angles, includes reviews (default)
                - "focused": Adds RCT publication-type filter; study quality still requires appraisal
                - "exploratory": Broader search with more synonyms
            check_spelling: Whether to check/correct spelling (default: True)
            include_suggestions: Include pre-built query suggestions (default: True)

        Returns:
            JSON with RAW MATERIALS:
            - corrected_topic: Spell-checked topic
            - keywords: Extracted significant keywords
            - mesh_terms: Confirmed mappings only. Each has input, preferred,
              synonyms, mesh_id, search_field, matched_on ("preferred" or
              "entry_term"), matched_term and pubmed_atm (whether PubMed's own
              automatic term mapping agrees, differs or does not map the phrase)
            - mesh_candidates: Unconfirmed links with a reason
              ("pubmed_atm_only", "ambiguous_exact_term", "co_occurrence");
              review before use. co_occurrence entries list candidates with
              preferred, search_clause, share, records, background_count,
              estimated_precision and score, plus evidence (query, sort,
              retrieved_at, evidence_total, sample_size, excluded headings).
              They are related concepts, not equivalents, and never appear
              in mesh_terms or suggested_queries
            - unmapped_phrases: Topic phrases without a confirmed MeSH term;
              cover them with free-text [Title/Abstract] terms
            - all_synonyms: Flattened synonyms of confirmed mappings
            - suggested_queries: Optional pre-built queries (MeSH clauses come
              from confirmed mappings only) with:
              - estimated_count: How many results PubMed would return
              - pubmed_translation: How PubMed actually interprets the query
        """
        # Normalize inputs
        topic = InputNormalizer.normalize_query(topic)
        if not topic:
            return ResponseFormatter.error(
                "Empty topic",
                suggestion="Provide a search topic",
                example='generate_search_queries(topic="remimazolam sedation")',
                tool_name="generate_search_queries",
            )
        if len(topic) > 2_000:
            return ResponseFormatter.error(
                "Topic exceeds 2000 characters",
                suggestion="Provide one bounded biomedical topic or PICO element",
                tool_name="generate_search_queries",
            )

        if strategy not in {"comprehensive", "focused", "exploratory"}:
            return ResponseFormatter.error(
                f"Unsupported strategy: {strategy}",
                suggestion="Use comprehensive, focused, or exploratory",
                tool_name="generate_search_queries",
            )

        logger.info("Generating search queries: strategy=%s", strategy)

        _strategy_generator = get_strategy_generator()
        fallback_reason = "strategy_generator_not_configured"

        # Use intelligent strategy generator if available
        if _strategy_generator:
            try:
                result = await _strategy_generator.generate_strategies(
                    topic=topic,
                    strategy=strategy,
                    use_mesh=True,
                    check_spelling=check_spelling,
                    include_suggestions=include_suggestions,
                    analyze_queries=True,  # Enable PubMed query analysis
                )
                result = await attach_cooccurrence_candidates(result, get_mesh_correction_service())

                # Add usage hint (Agent can ignore)
                result["_hint"] = {
                    "usage": "Use mesh_terms and all_synonyms to build your own queries, or use suggested_queries as reference",
                    "mesh_review": (
                        "mesh_terms are exact preferred/entry-term matches; verify mesh_candidates "
                        "(co_occurrence ones are related headings, not equivalents) and cover "
                        "unmapped_phrases with text words"
                    ),
                    "example_mesh_query": '"{preferred}"[{search_field}]',
                    "example_synonym_query": "({synonym})[Title/Abstract]",
                    "note": 'Check pubmed_translation. To preview combined blocks use analyze_search_query(query=fixed_scope, comparison={"blocks": named_clauses}).',
                }

                return json.dumps(result, indent=2, ensure_ascii=False)

            except Exception as exc:
                fallback_reason = "strategy_generator_failed"
                logger.warning(
                    "Strategy generator failed; returning explicit basic fallback (%s)",
                    type(exc).__name__,
                )

        result = build_fallback_query_materials(
            topic,
            strategy=strategy,
            include_suggestions=include_suggestions,
            fallback_reason=fallback_reason,
        )
        return json.dumps(result, indent=2, ensure_ascii=False)
