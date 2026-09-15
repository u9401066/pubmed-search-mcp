"""
Unified Search — Query Helpers Module.

Contains ICD code detection, dispatch strategy, composite parameter parsers,
search depth metrics dataclasses, and relaxation step generation.

Application-owned query policy shared by the planner and source broker.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pubmed_search.application.search.icd import lookup_icd_to_mesh
from pubmed_search.application.search.query_analyzer import (
    AnalyzedQuery,
    QueryComplexity,
    QueryIntent,
)
from pubmed_search.application.search.result_aggregator import RankingConfig

if TYPE_CHECKING:
    from pubmed_search.domain.entities.article import UnifiedArticle
    from pubmed_search.shared.source_contracts import SourceAdapterError

    from .use_case import SourceAutoDispatchProfile, SourceRegistryPort

logger = logging.getLogger(__name__)


# ============================================================================
# ICD Code Detection and Conversion
# ============================================================================


# ICD-10 pattern: Letter + 2-3 digits + optional dot + more digits
ICD10_PATTERN = re.compile(r"(?<![\w.])([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?)(?![\w.])", re.IGNORECASE)
# A bare three-digit number is commonly a dose, count, or measurement. Numeric
# ICD-9-CM codes are therefore detected only when the whole query is a code or
# when an explicit ICD-9/code marker precedes it.
ICD9_PATTERN = re.compile(r"\d{3}(?:\.\d{1,2})?")
ICD9_CONTEXT_PATTERN = re.compile(
    r"\b(?:ICD(?:-?9(?:-CM)?)?|diagnosis\s+code|dx\s+code)\s*[:#]?\s*(\d{3}(?:\.\d{1,2})?)\b",
    re.IGNORECASE,
)


def expand_icd_matches(query: str, matches: list[dict], *, dialect: Literal["pubmed", "boolean", "semantic"]) -> str:
    """Replace original code occurrences once, avoiding nested re-expansion."""
    by_code = {item["code"].upper(): item["mesh"] for item in matches}
    if not by_code:
        return query
    alternatives = "|".join(re.escape(code) for code in sorted(by_code, key=len, reverse=True))
    pattern = re.compile(rf"(?<![\w.])({alternatives})(?![\w.])", re.IGNORECASE)

    def replace(match: re.Match[str]) -> str:
        code = match.group(1).upper()
        mesh = by_code[code]
        if dialect == "semantic":
            return f"{mesh} ({code})"
        tag = "[MeSH]" if dialect == "pubmed" else ""
        return f'("{mesh}"{tag} OR {code})'

    return pattern.sub(replace, query)


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
        if any(item["code"] == code for item in icd_matches):
            continue
        result = lookup_icd_to_mesh(code)
        mesh_term = (result.get("mesh_term") or result.get("mesh")) if result else None
        if isinstance(mesh_term, str) and mesh_term:
            icd_matches.append(
                {
                    "code": code,
                    "type": "ICD-10",
                    "mesh": mesh_term,
                    "description": result.get("description", ""),
                }
            )

    # Detect numeric ICD-9-CM only with unambiguous context. This prevents
    # queries such as "aspirin 250 mg" from becoming diabetes searches.
    stripped_query = query.strip()
    numeric_candidates = (
        [stripped_query]
        if ICD9_PATTERN.fullmatch(stripped_query)
        else [match.group(1) for match in ICD9_CONTEXT_PATTERN.finditer(query)]
    )
    for code in dict.fromkeys(numeric_candidates):
        # Only consider valid ICD-9 ranges (001-999)
        try:
            base = int(code.split(".")[0])
            if 1 <= base <= 999:
                result = lookup_icd_to_mesh(code)
                mesh_term = (result.get("mesh_term") or result.get("mesh")) if result else None
                if isinstance(mesh_term, str) and mesh_term:
                    icd_matches.append(
                        {
                            "code": code,
                            "type": "ICD-9-CM",
                            "mesh": mesh_term,
                            "description": result.get("description", ""),
                        }
                    )
        except ValueError:
            pass

    if not icd_matches:
        return query, []

    expanded_query = expand_icd_matches(query, icd_matches, dialect="pubmed")

    # Queries and diagnosis codes may be sensitive in a multi-user service.
    # Operational logs retain only cardinality; exact query provenance belongs
    # in the caller-scoped artifact, never in the process-wide log stream.
    logger.info("Expanded %s ICD code(s) into provider-specific query forms", len(icd_matches))

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
    def get_sources(
        analysis: AnalyzedQuery,
        *,
        registry: SourceRegistryPort,
    ) -> list[str]:
        """Get ordered sources from one explicitly selected registry."""
        profile = DispatchStrategy.get_auto_dispatch_profile(analysis)
        sources = registry.list_auto_dispatch_sources(profile)
        if sources:
            return sources
        return registry.filter_unified_sources(["pubmed"])

    @staticmethod
    def get_auto_dispatch_profile(analysis: AnalyzedQuery) -> SourceAutoDispatchProfile:
        """Map query analysis to a registry-owned auto-dispatch profile."""
        complexity = analysis.complexity
        intent = analysis.intent

        if intent == QueryIntent.LOOKUP:
            if analysis.identifiers:
                return "lookup_identifier"
            return "lookup"

        if complexity == QueryComplexity.SIMPLE:
            return "simple"

        if complexity == QueryComplexity.MODERATE:
            return "moderate"

        if complexity == QueryComplexity.COMPLEX:
            if intent == QueryIntent.COMPARISON:
                return "complex_comparison"
            if intent == QueryIntent.SYSTEMATIC:
                return "complex_systematic"
            return "complex_default"

        if complexity == QueryComplexity.AMBIGUOUS:
            return "ambiguous"

        return "simple"

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


_ALLOWED_AGE_GROUPS = frozenset(
    {
        "newborn",
        "infant",
        "preschool",
        "child",
        "adolescent",
        "young_adult",
        "adult",
        "middle_aged",
        "aged",
        "aged_80",
    }
)
_ALLOWED_SEX_FILTERS = frozenset({"male", "female"})
_ALLOWED_SPECIES_FILTERS = frozenset({"humans", "animals"})
_ALLOWED_LANGUAGE_FILTERS = frozenset(
    {
        "english",
        "chinese",
        "japanese",
        "german",
        "french",
        "spanish",
        "korean",
        "italian",
        "portuguese",
        "russian",
    }
)
_ALLOWED_CLINICAL_FILTERS = frozenset(
    {
        "therapy",
        "therapy_narrow",
        "diagnosis",
        "diagnosis_narrow",
        "prognosis",
        "prognosis_narrow",
        "etiology",
        "etiology_narrow",
        "clinical_prediction",
        "clinical_prediction_narrow",
    }
)


def _parse_filters_detailed(filters_str: str | None) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Parse the canonical filter grammar without repairing input aliases."""
    if filters_str is None:
        return {}, ()

    result: dict[str, Any] = {}
    diagnostics: list[str] = []
    seen_keys: set[str] = set()
    for raw_part in filters_str.split(","):
        if not raw_part:
            diagnostics.append("filter list contains an empty token")
            continue
        if raw_part != raw_part.strip():
            diagnostics.append(f"filter '{raw_part}' contains surrounding whitespace")
            continue
        if ":" not in raw_part:
            diagnostics.append(f"filter '{raw_part}' must use key:value syntax")
            continue

        key, value = raw_part.split(":", 1)
        if key != key.strip() or value != value.strip():
            diagnostics.append(f"filter '{raw_part}' contains whitespace around its key or value")
            continue
        if not key:
            diagnostics.append(f"filter '{raw_part}' has an empty key")
            continue
        if not value:
            diagnostics.append(f"filter '{key}' has an empty value")
            continue
        if key in seen_keys:
            diagnostics.append(f"filter '{key}' is duplicated")
            continue
        seen_keys.add(key)

        if key == "year":
            year_match = re.fullmatch(r"(?:([0-9]{4})|([0-9]{4})?-([0-9]{4})?)", value)
            if year_match is None or all(group is None for group in year_match.groups()):
                diagnostics.append(f"filter 'year:{value}' is not a valid year or range")
                continue
            lower = year_match.group(1) or year_match.group(2)
            upper = year_match.group(3)
            min_year = int(lower) if lower is not None else None
            max_year = int(upper) if upper is not None else None
            if min_year is not None and not 1000 <= min_year <= 2100:
                diagnostics.append(f"minimum year {min_year} is outside 1000-2100")
                continue
            if max_year is not None and not 1000 <= max_year <= 2100:
                diagnostics.append(f"maximum year {max_year} is outside 1000-2100")
                continue
            if min_year is not None and max_year is not None and min_year > max_year:
                diagnostics.append(f"year range {min_year}-{max_year} is reversed")
                continue
            if min_year is not None:
                result["min_year"] = min_year
            if max_year is not None:
                result["max_year"] = max_year
        elif key == "age_group":
            if value not in _ALLOWED_AGE_GROUPS:
                diagnostics.append(f"unsupported age filter '{value}'")
            else:
                result["age_group"] = value
        elif key == "sex":
            if value not in _ALLOWED_SEX_FILTERS:
                diagnostics.append(f"unsupported sex filter '{value}'")
            else:
                result["sex"] = value
        elif key == "species":
            if value not in _ALLOWED_SPECIES_FILTERS:
                diagnostics.append(f"unsupported species filter '{value}'")
            else:
                result["species"] = value
        elif key == "language":
            if value not in _ALLOWED_LANGUAGE_FILTERS:
                diagnostics.append(f"unsupported language filter '{value}'")
            else:
                result["language"] = value
        elif key == "clinical_query":
            if value not in _ALLOWED_CLINICAL_FILTERS:
                diagnostics.append(f"unsupported clinical filter '{value}'")
            else:
                result["clinical_query"] = value
        else:
            diagnostics.append(f"unknown filter key '{key}'")

    return result, tuple(diagnostics)


# Mapping of option flag names to (internal_key, value_when_set)
_OPTION_FLAGS: dict[str, tuple[str, bool]] = {
    # Turn ON features (default OFF)
    "preprints": ("include_preprints", True),
    "include_detected_preprints": ("include_detected_preprints", True),
    "clinical_trials": ("include_clinical_trials", True),
    "counts_first": ("counts_first", True),
    # Provider-neutral retrieval policies.  These remain options on the one
    # unified_search facade; they never become provider-shaped MCP tools.
    "native_semantic": ("native_semantic", True),
    "systematic": ("systematic_search", True),
    # Turn OFF features (default ON)
    "no_oa": ("include_oa_links", False),
    "no_analysis": ("show_analysis", False),
    "no_scores": ("include_rank_scores", False),
    "no_next": ("include_next_tools", False),
    "no_provenance": ("include_section_provenance", False),
    "no_relax": ("auto_relax", False),
    "shallow": ("deep_search", False),
}
_COMPACT_OPTION_DEFAULTS: dict[str, bool] = {
    "compact_output": True,
    "show_analysis": False,
    "include_rank_scores": False,
    "include_next_tools": False,
    "include_section_provenance": False,
    "deep_search": False,
}


def _parse_options_detailed(options_str: str | None) -> tuple[dict[str, bool], tuple[str, ...]]:
    """Parse exact canonical option tokens without case or spelling repair."""
    if options_str is None:
        return {}, ()

    result: dict[str, bool] = {}
    diagnostics: list[str] = []
    seen_flags: set[str] = set()
    for flag in options_str.split(","):
        if not flag:
            diagnostics.append("option list contains an empty token")
            continue
        if flag != flag.strip():
            diagnostics.append(f"option '{flag}' contains surrounding whitespace")
            continue
        if flag in seen_flags:
            diagnostics.append(f"option '{flag}' is duplicated")
            continue
        seen_flags.add(flag)
        if flag == "compact":
            result.update(_COMPACT_OPTION_DEFAULTS)
        elif flag in _OPTION_FLAGS:
            internal_key, value = _OPTION_FLAGS[flag]
            result[internal_key] = value
        else:
            diagnostics.append(f"unknown option '{flag}'")
    return result, tuple(diagnostics)


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
    status: str = "ok"
    allocated_limit: int = 0
    total_available: int | None = None
    physical_query: str | None = None
    query_executed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


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
    heuristic_recall_proxy: float = 0.0  # Unvalidated coverage heuristic (0-1)
    heuristic_precision_proxy: float = 0.0  # Unvalidated specificity heuristic (0-1)
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
        - Unvalidated recall proxy: up to 20 points (coverage heuristic)
        """
        entity_score = min(30, self.entities_resolved * 10)
        mesh_score = min(30, self.mesh_terms_used * 10)
        strategy_score = min(20, self.strategies_with_results * 5)
        recall_score = self.heuristic_recall_proxy * 20

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
            "heuristic_recall_proxy": round(self.heuristic_recall_proxy, 2),
            "heuristic_precision_proxy": round(self.heuristic_precision_proxy, 2),
            "depth_score": round(self.depth_score, 1),
            "strategy_results": [
                {
                    "name": s.strategy_name,
                    "query": s.query[:100] + "..." if len(s.query) > 100 else s.query,
                    "source": s.source,
                    "articles": s.articles_count,
                    "status": s.status,
                    "allocated_limit": s.allocated_limit,
                    "total_available": s.total_available,
                    "physical_query": s.physical_query,
                    "query_executed": s.query_executed,
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
    status: Literal["pending", "ok", "empty", "error"] = "pending"
    error: SourceAdapterError | None = None


@dataclass
class RelaxationResult:
    """Result of auto-relaxation process."""

    original_query: str
    relaxed_query: str
    steps_tried: list[RelaxationStep]
    successful_step: RelaxationStep | None
    total_results: int
    articles: list[UnifiedArticle] = field(default_factory=list)

    @property
    def errors(self) -> list[SourceAdapterError]:
        """Return normalized failures without conflating them with empty results."""
        return [step.error for step in self.steps_tried if step.error is not None]

    @property
    def incomplete(self) -> bool:
        """Whether at least one planned relaxation request failed."""
        return bool(self.errors)


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
