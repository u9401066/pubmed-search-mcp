"""
Unified Search — Query Helpers Module.

Contains ICD code detection, dispatch strategy, composite parameter parsers,
search depth metrics dataclasses, and relaxation step generation.

Extracted from unified.py to keep each module under 400 lines.
"""

from __future__ import annotations

import contextlib
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pubmed_search.application.search.query_analyzer import (
    AnalyzedQuery,
    QueryComplexity,
    QueryIntent,
)
from pubmed_search.application.search.result_aggregator import RankingConfig

from .icd import lookup_icd_to_mesh

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ============================================================================
# ICD Code Detection and Conversion
# ============================================================================


# ICD-10 pattern: Letter + 2-3 digits + optional dot + more digits
ICD10_PATTERN = re.compile(r"\b([A-Z]\d{2}(?:\.\d{1,4})?)\b", re.IGNORECASE)
# ICD-9 pattern: 3-5 digits with optional dot
ICD9_PATTERN = re.compile(r"\b(\d{3}(?:\.\d{1,2})?)\b")


def detect_and_expand_icd_codes(query: str) -> tuple[str, list[dict]]:
    """
    Detect ICD codes in query and expand to MeSH terms.

    Args:
        query: Search query that may contain ICD codes

    Returns:
        Tuple of (expanded_query, icd_matches)
        - expanded_query: Query with ICD codes replaced/augmented by MeSH terms
        - icd_matches: List of detected ICD codes and their mappings
    """
    icd_matches: list[dict] = []

    # Detect ICD-10 codes
    for match in ICD10_PATTERN.finditer(query):
        code = match.group(1).upper()
        result = lookup_icd_to_mesh(code)
        if result:
            icd_matches.append(
                {
                    "code": code,
                    "type": "ICD-10",
                    "mesh": result["mesh"],
                    "description": result.get("description", ""),
                }
            )

    # Detect ICD-9 codes (3-digit numeric)
    for match in ICD9_PATTERN.finditer(query):
        code = match.group(1)
        # Only consider valid ICD-9 ranges (001-999)
        try:
            base = int(code.split(".")[0])
            if 1 <= base <= 999:
                result = lookup_icd_to_mesh(code)
                if result:
                    icd_matches.append(
                        {
                            "code": code,
                            "type": "ICD-9",
                            "mesh": result["mesh"],
                            "description": result.get("description", ""),
                        }
                    )
        except ValueError:
            pass

    if not icd_matches:
        return query, []

    # Build expanded query
    # Replace ICD codes with MeSH terms in the query
    expanded_query = query
    for icd in icd_matches:
        mesh_term = icd["mesh"]
        # Replace or augment the ICD code with MeSH
        expanded_query = re.sub(
            rf"\b{re.escape(icd['code'])}\b",
            f'("{mesh_term}"[MeSH] OR {icd["code"]})',
            expanded_query,
            flags=re.IGNORECASE,
        )

    logger.info(f"ICD codes detected: {[i['code'] for i in icd_matches]}")
    logger.info(f"Expanded query: {expanded_query}")

    return expanded_query, icd_matches


# ============================================================================
# Dispatch Strategy Matrix
# ============================================================================


class DispatchStrategy:
    """
    Determines which sources to query based on query analysis.

    Strategy Matrix:
    ┌─────────────────┬─────────────┬────────────────────────────────────┐
    │ Complexity      │ Intent      │ Sources                            │
    ├─────────────────┼─────────────┼────────────────────────────────────┤
    │ SIMPLE          │ LOOKUP      │ PubMed only (fast)                 │
    │ SIMPLE          │ EXPLORATION │ PubMed                             │
    │ MODERATE        │ *           │ PubMed + CrossRef enrichment       │
    │ COMPLEX         │ COMPARISON  │ PubMed + OpenAlex + S2             │
    │ COMPLEX         │ SYSTEMATIC  │ All sources (max coverage)         │
    │ AMBIGUOUS       │ *           │ PubMed + OpenAlex (broad)          │
    └─────────────────┴─────────────┴────────────────────────────────────┘
    """

    @staticmethod
    def get_sources(analysis: AnalyzedQuery) -> list[str]:
        """Get ordered list of sources to query."""
        complexity = analysis.complexity
        intent = analysis.intent

        # LOOKUP: Direct identifier search
        if intent == QueryIntent.LOOKUP:
            if analysis.identifiers:
                # Has identifiers - just PubMed
                return ["pubmed"]
            return ["pubmed", "crossref"]

        # SIMPLE: PubMed only for speed
        if complexity == QueryComplexity.SIMPLE:
            return ["pubmed"]

        # MODERATE: PubMed + CrossRef for DOI enrichment
        if complexity == QueryComplexity.MODERATE:
            return ["pubmed", "crossref"]

        # COMPLEX - depends on intent
        if complexity == QueryComplexity.COMPLEX:
            if intent == QueryIntent.COMPARISON:
                # Comparison needs diverse results
                return ["pubmed", "openalex", "semantic_scholar"]
            if intent == QueryIntent.SYSTEMATIC:
                # Systematic review needs maximum coverage
                return ["pubmed", "openalex", "semantic_scholar", "europe_pmc"]
            # Default complex
            return ["pubmed", "openalex", "crossref"]

        # AMBIGUOUS: Broad search
        if complexity == QueryComplexity.AMBIGUOUS:
            return ["pubmed", "openalex"]

        # Default fallback
        return ["pubmed"]

    @staticmethod
    def get_ranking_config(analysis: AnalyzedQuery) -> RankingConfig:
        """Get ranking configuration based on query analysis."""
        intent = analysis.intent

        # SYSTEMATIC: Quality focused (favor RCTs, meta-analyses)
        if intent == QueryIntent.SYSTEMATIC:
            return RankingConfig.quality_focused()

        # COMPARISON: Impact focused (favor high-cited comparative studies)
        if intent == QueryIntent.COMPARISON:
            return RankingConfig.impact_focused()

        # EXPLORATION with recent constraint: Recency focused
        if intent == QueryIntent.EXPLORATION and analysis.year_from:
            return RankingConfig.recency_focused()

        # Default: Balanced
        return RankingConfig.default()

    @staticmethod
    def should_enrich_with_unpaywall(analysis: AnalyzedQuery) -> bool:
        """Determine if results should be enriched with Unpaywall OA links."""
        # Always enrich for systematic reviews (need full text)
        if analysis.intent == QueryIntent.SYSTEMATIC:
            return True
        # Enrich for complex queries
        return analysis.complexity == QueryComplexity.COMPLEX


# ============================================================================
# Composite Parameter Parsers (Agent-Centric Design)
# ============================================================================


def _parse_filters(filters_str: str | None) -> dict:
    """Parse composite filters string into individual filter values.

    Format: "key:value, key:value, ..."

    Supported keys:
        year:2020-2025  → min_year=2020, max_year=2025
        year:2020-      → min_year=2020
        year:-2025      → max_year=2025
        year:2024       → min_year=2024
        age:<value>     → age_group (newborn/infant/child/adolescent/adult/aged/aged_80)
        sex:<value>     → sex (male/female)
        species:<value> → species (humans/animals)
        lang:<value>    → language (english/chinese/...)
        clinical:<value>→ clinical_query (therapy/diagnosis/prognosis/etiology/...)

    Returns:
        Dict with keys: min_year, max_year, age_group, sex, species, language, clinical_query
    """
    if not filters_str:
        return {}

    result: dict = {}
    for raw_part in filters_str.split(","):
        part = raw_part.strip()
        if not part or ":" not in part:
            continue
        key, value = part.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if not value:
            continue

        if key == "year":
            if "-" in value:
                parts = value.split("-", 1)
                if parts[0].strip():
                    with contextlib.suppress(ValueError):
                        result["min_year"] = int(parts[0].strip())
                if parts[1].strip():
                    with contextlib.suppress(ValueError):
                        result["max_year"] = int(parts[1].strip())
            else:
                with contextlib.suppress(ValueError):
                    result["min_year"] = int(value)
        elif key in ("age", "age_group"):
            result["age_group"] = value
        elif key == "sex":
            result["sex"] = value
        elif key == "species":
            result["species"] = value
        elif key in ("lang", "language"):
            result["language"] = value
        elif key in ("clinical", "clinical_query"):
            result["clinical_query"] = value

    return result


# Mapping of option flag names to (internal_key, value_when_set)
_OPTION_FLAGS: dict[str, tuple[str, bool]] = {
    # Turn ON features (default OFF)
    "preprints": ("include_preprints", True),
    # Turn OFF features (default ON)
    "all_types": ("peer_reviewed_only", False),
    "no_peer_review": ("peer_reviewed_only", False),
    "no_oa": ("include_oa_links", False),
    "no_analysis": ("show_analysis", False),
    "no_scores": ("include_similarity_scores", False),
    "no_relax": ("auto_relax", False),
    "shallow": ("deep_search", False),
}


def _parse_options(options_str: str | None) -> dict[str, bool]:
    """Parse composite options string into boolean flags.

    Format: "flag1, flag2, ..."

    Supported flags:
        preprints      → include preprint servers (arXiv, medRxiv, bioRxiv)
        all_types      → include non-peer-reviewed articles
        no_oa          → skip Unpaywall OA link enrichment
        no_analysis    → hide query analysis section in output
        no_scores      → hide similarity scores
        no_relax       → disable auto-relaxation on 0 results
        shallow        → disable deep search (faster, keyword-only)

    Returns:
        Dict with boolean values for each recognized flag.
    """
    if not options_str:
        return {}

    flags = {f.strip().lower() for f in options_str.split(",") if f.strip()}
    result: dict[str, bool] = {}

    for flag in flags:
        if flag in _OPTION_FLAGS:
            internal_key, value = _OPTION_FLAGS[flag]
            result[internal_key] = value
        else:
            logger.warning(f"Unknown option flag: '{flag}' (available: {', '.join(sorted(_OPTION_FLAGS))})")

    return result


# ============================================================================
# Auto Search Relaxation — Constants
# ============================================================================

# Pattern matching PubMed field tags like [Title], [tiab], [MeSH Terms], etc.
_FIELD_TAG_PATTERN = re.compile(
    r"\s*\[(?:Title|tiab|Title/Abstract|MeSH Terms?|All Fields|pt|"
    r"Author|Journal|Affiliation|Publication Type|"
    r"MeSH Major Topic|MeSH Subheading|dp)\]",
    re.IGNORECASE,
)

# Publication type filters like "randomized controlled trial[pt]"
_PUB_TYPE_FILTER_PATTERN = re.compile(
    r"\s+AND\s+(?:\()?(?:randomized controlled trial|meta-analysis|"
    r"systematic review|clinical trial|review|case reports?)"
    r"(?:\[pt\])?(?:\s+OR\s+(?:randomized controlled trial|meta-analysis|"
    r"systematic review|clinical trial|review|case reports?)"
    r"(?:\[pt\])?)*(?:\))?",
    re.IGNORECASE,
)

# Stop words to filter when extracting core keywords
_STOP_WORDS = frozenset(
    {
        "in",
        "of",
        "for",
        "the",
        "a",
        "an",
        "and",
        "or",
        "with",
        "to",
        "on",
        "by",
        "is",
        "vs",
        "versus",
        "from",
        "at",
        "as",
        "not",
        "between",
        "during",
        "after",
        "before",
        "using",
        "through",
        "about",
        "into",
    }
)


# ============================================================================
# Search Depth Metrics (Quantified Deep Search)
# ============================================================================


@dataclass
class StrategyResult:
    """Result from executing one search strategy."""

    strategy_name: str
    query: str
    source: str
    articles_count: int
    expected_precision: float
    expected_recall: float
    execution_time_ms: float = 0.0


@dataclass
class SearchDepthMetrics:
    """
    Quantified metrics for search depth.

    This answers the question: "How deep was this search?"
    """

    # Semantic Enhancement
    entities_resolved: int = 0  # PubTator3 entities found
    mesh_terms_used: int = 0  # MeSH terms in search
    synonyms_expanded: int = 0  # Synonym expansions

    # Strategy Execution
    strategies_generated: int = 0  # How many strategies were planned
    strategies_executed: int = 0  # How many actually ran
    strategies_with_results: int = 0  # How many returned results

    # Coverage Metrics
    estimated_recall: float = 0.0  # Combined recall estimate (0-1)
    estimated_precision: float = 0.0  # Combined precision estimate (0-1)
    depth_score: float = 0.0  # Overall depth score (0-100)

    # Strategy Details
    strategy_results: list[StrategyResult] = field(default_factory=list)

    def calculate_depth_score(self) -> float:
        """
        Calculate overall search depth score (0-100).

        Factors:
        - Entity resolution: up to 30 points (semantic understanding)
        - MeSH coverage: up to 30 points (standardized vocabulary)
        - Strategy diversity: up to 20 points (multiple approaches)
        - Recall estimate: up to 20 points (coverage)
        """
        entity_score = min(30, self.entities_resolved * 10)
        mesh_score = min(30, self.mesh_terms_used * 10)
        strategy_score = min(20, self.strategies_with_results * 5)
        recall_score = self.estimated_recall * 20

        self.depth_score = entity_score + mesh_score + strategy_score + recall_score
        return self.depth_score

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON output."""
        return {
            "entities_resolved": self.entities_resolved,
            "mesh_terms_used": self.mesh_terms_used,
            "synonyms_expanded": self.synonyms_expanded,
            "strategies_generated": self.strategies_generated,
            "strategies_executed": self.strategies_executed,
            "strategies_with_results": self.strategies_with_results,
            "estimated_recall": round(self.estimated_recall, 2),
            "estimated_precision": round(self.estimated_precision, 2),
            "depth_score": round(self.depth_score, 1),
            "strategy_results": [
                {
                    "name": s.strategy_name,
                    "query": s.query[:100] + "..." if len(s.query) > 100 else s.query,
                    "source": s.source,
                    "articles": s.articles_count,
                }
                for s in self.strategy_results
            ],
        }

    def summary(self) -> str:
        """Human-readable summary."""
        self.calculate_depth_score()
        level = "🟢 Deep" if self.depth_score >= 60 else "🟡 Moderate" if self.depth_score >= 30 else "🔴 Shallow"
        return (
            f"{level} (Score: {self.depth_score:.0f}/100) | "
            f"Entities: {self.entities_resolved}, MeSH: {self.mesh_terms_used}, "
            f"Strategies: {self.strategies_with_results}/{self.strategies_executed}"
        )


@dataclass
class RelaxationStep:
    """Describes one step of query relaxation."""

    level: int
    action: str
    description: str
    query: str
    min_year: int | None = None
    max_year: int | None = None
    advanced_filters: dict = field(default_factory=dict)
    result_count: int = 0


@dataclass
class RelaxationResult:
    """Result of auto-relaxation process."""

    original_query: str
    relaxed_query: str
    steps_tried: list[RelaxationStep]
    successful_step: RelaxationStep | None
    total_results: int


def _generate_relaxation_steps(
    query: str,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict,
) -> list[RelaxationStep]:
    """Generate progressive relaxation steps from narrow to broad.

    Scope ordering principle (narrow → broad):
      Level 1: Remove advanced clinical filters (least core impact)
      Level 2: Remove year constraints
      Level 3: Remove publication type filters (e.g., AND RCT[pt])
      Level 4: Remove PubMed field tags ([Title], [MeSH Terms], etc.)
      Level 5: Relax Boolean logic (AND → OR)
      Level 6: Extract core keywords only (most broad)

    Only generates steps that are actually applicable to the given query.
    """
    steps: list[RelaxationStep] = []
    level = 1

    current_query = query
    current_min_year = min_year
    current_max_year = max_year
    current_filters = dict(advanced_filters)

    # --- Level 1: Remove advanced filters ---
    active_filters = {k: v for k, v in current_filters.items() if v is not None}
    if active_filters:
        filter_names = ", ".join(f"{k}={v}" for k, v in active_filters.items())
        steps.append(
            RelaxationStep(
                level=level,
                action="remove_advanced_filters",
                description=f"移除進階篩選條件: {filter_names}",
                query=current_query,
                min_year=current_min_year,
                max_year=current_max_year,
                advanced_filters={},
            )
        )
        current_filters = {}
        level += 1

    # --- Level 2: Remove year constraints ---
    if current_min_year or current_max_year:
        year_parts = []
        if current_min_year:
            year_parts.append(f"min_year={current_min_year}")
        if current_max_year:
            year_parts.append(f"max_year={current_max_year}")
        steps.append(
            RelaxationStep(
                level=level,
                action="remove_year_filter",
                description=f"移除年份限制: {', '.join(year_parts)}",
                query=current_query,
                min_year=None,
                max_year=None,
                advanced_filters=current_filters,
            )
        )
        current_min_year = None
        current_max_year = None
        level += 1

    # --- Level 3: Remove publication type filters ---
    if _PUB_TYPE_FILTER_PATTERN.search(current_query):
        relaxed = _PUB_TYPE_FILTER_PATTERN.sub("", current_query).strip()
        relaxed = re.sub(r"\s+", " ", relaxed).strip()
        if relaxed and relaxed != current_query:
            steps.append(
                RelaxationStep(
                    level=level,
                    action="remove_pub_type_filter",
                    description="移除出版類型篩選 (如 RCT, Meta-analysis 等)",
                    query=relaxed,
                    min_year=current_min_year,
                    max_year=current_max_year,
                    advanced_filters=current_filters,
                )
            )
            current_query = relaxed
            level += 1

    # --- Level 4: Remove field tags ---
    if _FIELD_TAG_PATTERN.search(current_query):
        relaxed = _FIELD_TAG_PATTERN.sub("", current_query)
        # Clean up leftover parentheses and whitespace
        relaxed = re.sub(r"\(\s*\)", "", relaxed)
        relaxed = re.sub(r"\s+", " ", relaxed).strip()
        # Remove leading/trailing Boolean operators
        relaxed = re.sub(r"^\s*(AND|OR)\s+", "", relaxed, flags=re.IGNORECASE)
        relaxed = re.sub(r"\s+(AND|OR)\s*$", "", relaxed, flags=re.IGNORECASE)
        if relaxed and relaxed != current_query:
            steps.append(
                RelaxationStep(
                    level=level,
                    action="remove_field_tags",
                    description="移除 PubMed 欄位限制 (如 [Title], [MeSH Terms])",
                    query=relaxed,
                    min_year=current_min_year,
                    max_year=current_max_year,
                    advanced_filters=current_filters,
                )
            )
            current_query = relaxed
            level += 1

    # --- Level 5: AND → OR ---
    if re.search(r"\bAND\b", current_query, re.IGNORECASE):
        relaxed = re.sub(r"\s+AND\s+", " OR ", current_query, flags=re.IGNORECASE)
        steps.append(
            RelaxationStep(
                level=level,
                action="and_to_or",
                description="放寬布林邏輯: AND → OR (任一關鍵字即可匹配)",
                query=relaxed,
                min_year=current_min_year,
                max_year=current_max_year,
                advanced_filters=current_filters,
            )
        )
        current_query = relaxed
        level += 1

    # --- Level 6: Core keywords only ---
    # Strip all operators, quotes, parentheses, field tags
    core = re.sub(r'"([^"]+)"', r"\1", current_query)  # unquote
    core = re.sub(r"\b(AND|OR|NOT)\b", " ", core, flags=re.IGNORECASE)
    core = re.sub(r"[\[\]()\"']", " ", core)
    core = re.sub(r"\s+", " ", core).strip()

    words = core.split()
    significant = [w for w in words if w.lower() not in _STOP_WORDS and len(w) > 2]

    if len(significant) > 2:
        # Keep at most 2-3 core keywords
        core_keywords = significant[:3]
        core_query = " ".join(core_keywords)
        if core_query.lower() != current_query.lower().strip():
            steps.append(
                RelaxationStep(
                    level=level,
                    action="core_keywords_only",
                    description=f"簡化為核心關鍵字: {core_query}",
                    query=core_query,
                    min_year=None,
                    max_year=None,
                    advanced_filters={},
                )
            )

    return steps
