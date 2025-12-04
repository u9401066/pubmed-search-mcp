"""
PICO Tool - Parse clinical questions into PICO structure.

Tools:
- parse_pico: Parse clinical question into P/I/C/O elements
"""

import json
import logging

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_pico_tools(mcp: FastMCP):
    """Register PICO parsing tool."""
    
    @mcp.tool()
    def parse_pico(
        description: str,
        p: str = None,
        i: str = None,
        c: str = None,
        o: str = None
    ) -> str:
        """
        Parse a clinical question into PICO elements OR accept pre-parsed PICO.
        
        This tool is the ENTRY POINT for PICO-based search workflow.
        
        ══════════════════════════════════════════════════════════════════════
        PICO SEARCH WORKFLOW (連續技):
        ══════════════════════════════════════════════════════════════════════
        
        Step 1: parse_pico() ← YOU ARE HERE
        ───────────────────
        Option A - Agent parses PICO from description:
            parse_pico(description="remimazolam 在 ICU 比 propofol 好嗎？")
            
        Option B - User provides structured PICO:
            parse_pico(p="ICU patients", i="remimazolam", c="propofol", o="delirium")
        
        Step 2: generate_search_queries() - PARALLEL CALLS
        ───────────────────────────────────────────────────
        For each PICO element returned, call generate_search_queries():
            - generate_search_queries(P_element)  → P materials
            - generate_search_queries(I_element)  → I materials
            - generate_search_queries(C_element)  → C materials (if exists)
            - generate_search_queries(O_element)  → O materials
        
        Step 3: Build combined query
        ────────────────────────────
        Using materials from Step 2, build queries with Boolean logic:
        
        High Precision:
            (P_mesh OR P_synonyms) AND 
            (I_mesh OR I_synonyms) AND 
            (C_mesh OR C_synonyms) AND 
            (O_mesh OR O_synonyms)
        
        High Recall:
            (P_mesh) AND (I_mesh OR C_mesh) AND (O_mesh)
        
        Step 4: Add Clinical Query filter
        ──────────────────────────────────
        Based on question_type returned:
            - "therapy"   → AND therapy[filter]
            - "diagnosis" → AND diagnosis[filter]
            - "prognosis" → AND prognosis[filter]
            - "etiology"  → AND etiology[filter]
        
        Step 5: search_literature() - PARALLEL CALLS
        ─────────────────────────────────────────────
        Execute multiple search strategies in parallel
        
        Step 6: merge_search_results()
        ──────────────────────────────
        Combine and deduplicate results
        
        ══════════════════════════════════════════════════════════════════════
        
        Args:
            description: Natural language clinical question (Agent will parse)
            p: Population/Patient - who? (optional, if pre-parsed)
            i: Intervention - what treatment/exposure? (optional)
            c: Comparison - compared to what? (optional, may be empty)
            o: Outcome - what result? (optional)
            
        Returns:
            JSON with:
            - pico: Structured PICO elements
            - question_type: Suggested Clinical Query filter
            - next_steps: Instructions for the workflow
            - example_queries: Reference query patterns
        """
        logger.info(f"Parsing PICO from: {description[:50] if description else 'structured input'}...")
        
        # If structured PICO provided, use it directly
        if any([p, i, c, o]):
            pico = {
                "P": p or "",
                "I": i or "",
                "C": c or "",
                "O": o or ""
            }
            source = "user_provided"
        else:
            # Agent should parse the description
            # Return a template for Agent to fill
            pico = {
                "P": "[Agent: extract Population from description]",
                "I": "[Agent: extract Intervention from description]",
                "C": "[Agent: extract Comparison from description, may be empty]",
                "O": "[Agent: extract Outcome from description]"
            }
            source = "needs_parsing"
        
        # Infer question type from description
        question_type = "therapy"  # default
        if description:
            desc_lower = description.lower()
            if any(w in desc_lower for w in ["診斷", "diagnos", "detect", "sensitivity", "specificity"]):
                question_type = "diagnosis"
            elif any(w in desc_lower for w in ["預後", "prognos", "survival", "mortality", "outcome"]):
                question_type = "prognosis"
            elif any(w in desc_lower for w in ["原因", "病因", "cause", "etiolog", "risk factor"]):
                question_type = "etiology"
            elif any(w in desc_lower for w in ["治療", "效果", "比較", "therap", "treatment", "vs", "versus", "比"]):
                question_type = "therapy"
        
        result = {
            "pico": pico,
            "source": source,
            "original_description": description,
            "question_type": question_type,
            "suggested_filter": f"{question_type}[filter]",
            "next_steps": [
                "1. If source='needs_parsing': Agent fills in PICO elements from description",
                "2. Call generate_search_queries() for EACH non-empty PICO element (IN PARALLEL)",
                "3. Combine materials: (P) AND (I) AND (C if exists) AND (O)",
                "4. Add suggested_filter to query",
                "5. Call search_literature() with combined queries",
                "6. Call merge_search_results() to deduplicate"
            ],
            "query_patterns": {
                "high_precision": "(P_terms) AND (I_terms) AND (C_terms) AND (O_terms) AND {filter}",
                "high_recall": "(P_mesh) AND (I_mesh OR C_mesh) AND (O_mesh)",
                "intervention_focused": "(I_terms) AND (O_terms) AND therapy[filter]"
            }
        }
        
        return json.dumps(result, indent=2, ensure_ascii=False)
