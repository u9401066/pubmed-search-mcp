"""
QueryAnalyzer - Intelligent Query Analysis for Multi-Source Search

This module analyzes user queries to determine:
1. Query complexity (simple keyword vs. complex clinical question)
2. Query intent (lookup, exploration, systematic review)
3. PICO elements (Population, Intervention, Comparison, Outcome)
4. Recommended search strategy and source selection

Architecture Decision:
    QueryAnalyzer is stateless and uses heuristics + patterns for analysis.
    It does NOT call any external APIs - pure local processing for speed.
    
    For MeSH expansion and synonym lookup, the existing generate_search_queries
    tool should be called separately.

Example:
    >>> analyzer = QueryAnalyzer()
    >>> result = analyzer.analyze("remimazolam vs propofol for ICU sedation")
    >>> result.complexity
    QueryComplexity.COMPLEX
    >>> result.pico
    {'P': 'ICU patients', 'I': 'remimazolam', 'C': 'propofol', 'O': 'sedation'}
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class QueryComplexity(Enum):
    """
    Query complexity levels determining search strategy.
    
    SIMPLE: Single concept, direct lookup
        → PubMed only, title search
        Example: "PMID:12345678", "aspirin mechanism"
    
    MODERATE: Multiple concepts, standard search
        → PubMed + optional CrossRef
        Example: "diabetes treatment guidelines 2024"
    
    COMPLEX: Clinical question, comparison, PICO structure
        → Full multi-source search, parallel queries
        Example: "Is remimazolam better than propofol for ICU sedation?"
    
    AMBIGUOUS: Unclear intent, needs clarification
        → Exploratory search with broad sources
        Example: "cancer" (too broad)
    """
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    AMBIGUOUS = "ambiguous"


class QueryIntent(Enum):
    """
    User's search intent determining result presentation.
    
    LOOKUP: Find specific article(s) by identifier
        → Exact match, single result expected
        Example: "PMID:12345678", "doi:10.1000/example"
    
    EXPLORATION: General topic exploration
        → Diverse results, good for literature review start
        Example: "machine learning in anesthesia"
    
    COMPARISON: Compare interventions/treatments
        → Need studies comparing A vs B
        Example: "metformin vs glipizide for diabetes"
    
    SYSTEMATIC: Comprehensive search for systematic review
        → High recall, multiple strategies
        Example: PICO-structured clinical questions
    
    CITATION_TRACKING: Find related/citing articles
        → Citation network exploration
        Example: "papers citing PMID:12345678"
    
    AUTHOR_SEARCH: Find works by specific author
        → Author-focused search
        Example: "publications by John Smith Harvard"
    """
    LOOKUP = "lookup"
    EXPLORATION = "exploration"
    COMPARISON = "comparison"
    SYSTEMATIC = "systematic"
    CITATION_TRACKING = "citation_tracking"
    AUTHOR_SEARCH = "author_search"


@dataclass
class PICOElements:
    """
    PICO framework elements for clinical questions.
    
    PICO helps structure clinical questions:
    - P: Population/Patient/Problem
    - I: Intervention/Indicator
    - C: Comparison/Control
    - O: Outcome
    
    Optional extensions:
    - T: Timeframe
    - S: Study type
    """
    population: str | None = None
    intervention: str | None = None
    comparison: str | None = None
    outcome: str | None = None
    timeframe: str | None = None
    study_type: str | None = None
    
    @property
    def is_complete(self) -> bool:
        """Check if core PICO elements are present."""
        return bool(self.population and self.intervention and self.outcome)
    
    @property
    def has_comparison(self) -> bool:
        """Check if comparison element is present."""
        return bool(self.comparison)
    
    def to_dict(self) -> dict[str, str | None]:
        """Convert to dictionary."""
        return {
            "P": self.population,
            "I": self.intervention,
            "C": self.comparison,
            "O": self.outcome,
            "T": self.timeframe,
            "S": self.study_type,
        }


@dataclass 
class ExtractedIdentifier:
    """Identifier extracted from query."""
    type: Literal["pmid", "doi", "pmc", "arxiv", "title"]
    value: str
    confidence: float = 1.0


@dataclass
class AnalyzedQuery:
    """
    Result of query analysis.
    
    Contains all information needed to dispatch search to appropriate sources.
    """
    # Original query
    original_query: str
    
    # Normalized/cleaned query
    normalized_query: str
    
    # Analysis results
    complexity: QueryComplexity
    intent: QueryIntent
    
    # PICO elements (if detected)
    pico: PICOElements | None = None
    
    # Extracted identifiers (PMIDs, DOIs, etc.)
    identifiers: list[ExtractedIdentifier] = field(default_factory=list)
    
    # Extracted keywords (significant terms)
    keywords: list[str] = field(default_factory=list)
    
    # Detected clinical question type (for PubMed Clinical Queries filter)
    clinical_category: Literal["therapy", "diagnosis", "prognosis", "etiology", "prediction"] | None = None
    
    # Year constraints detected
    year_from: int | None = None
    year_to: int | None = None
    
    # Recommended sources (ordered by priority)
    recommended_sources: list[str] = field(default_factory=list)
    
    # Recommended search strategies
    recommended_strategies: list[str] = field(default_factory=list)
    
    # Confidence score (0-1)
    confidence: float = 0.5
    
    # Additional metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "original_query": self.original_query,
            "normalized_query": self.normalized_query,
            "complexity": self.complexity.value,
            "intent": self.intent.value,
            "pico": self.pico.to_dict() if self.pico else None,
            "identifiers": [
                {"type": i.type, "value": i.value, "confidence": i.confidence}
                for i in self.identifiers
            ],
            "keywords": self.keywords,
            "clinical_category": self.clinical_category,
            "year_constraints": {
                "from": self.year_from,
                "to": self.year_to,
            },
            "recommended_sources": self.recommended_sources,
            "recommended_strategies": self.recommended_strategies,
            "confidence": self.confidence,
        }


class QueryAnalyzer:
    """
    Intelligent query analyzer for multi-source search.
    
    Analyzes user queries to determine:
    - Complexity level
    - Search intent
    - PICO elements (for clinical questions)
    - Recommended sources and strategies
    
    Usage:
        analyzer = QueryAnalyzer()
        result = analyzer.analyze("remimazolam vs propofol in ICU")
        
        print(result.complexity)  # QueryComplexity.COMPLEX
        print(result.intent)      # QueryIntent.COMPARISON
        print(result.pico)        # PICOElements(...)
    
    Note:
        QueryAnalyzer is purely local - no API calls.
        For MeSH expansion, use generate_search_queries tool.
    """
    
    # Identifier patterns
    PMID_PATTERN = re.compile(r"(?:PMID[:\s]?)?(\d{7,8})\b", re.IGNORECASE)
    DOI_PATTERN = re.compile(r"(?:doi[:\s]?)?(10\.\d{4,}/[^\s]+)", re.IGNORECASE)
    PMC_PATTERN = re.compile(r"PMC\s?(\d{6,8})\b", re.IGNORECASE)
    ARXIV_PATTERN = re.compile(r"(?:arxiv[:\s]?)?([\d]{4}\.[\d]{4,5}(?:v\d+)?)", re.IGNORECASE)
    
    # Year patterns
    YEAR_PATTERN = re.compile(r"\b(19\d{2}|20[0-3]\d)\b")
    YEAR_RANGE_PATTERN = re.compile(r"\b(19\d{2}|20[0-3]\d)\s*[-–to]+\s*(19\d{2}|20[0-3]\d)\b", re.IGNORECASE)
    RECENT_PATTERN = re.compile(r"\b(recent|last\s+\d+\s+years?|past\s+\d+\s+years?)\b", re.IGNORECASE)
    
    # Comparison keywords
    COMPARISON_KEYWORDS = {
        "vs", "versus", "compared", "comparison", "comparing", 
        "better", "worse", "superior", "inferior", "equivalent",
        "vs.", "v.", "or", "and", "比較", "相比", "優於", "劣於",
    }
    
    # Clinical question keywords
    CLINICAL_THERAPY_KEYWORDS = {
        "treatment", "therapy", "intervention", "effect", "efficacy",
        "effective", "治療", "療效", "治療效果",
    }
    CLINICAL_DIAGNOSIS_KEYWORDS = {
        "diagnosis", "diagnostic", "sensitivity", "specificity",
        "accuracy", "診斷", "敏感度", "特異度",
    }
    CLINICAL_PROGNOSIS_KEYWORDS = {
        "prognosis", "outcome", "survival", "mortality", "risk",
        "prediction", "預後", "存活", "死亡率",
    }
    CLINICAL_ETIOLOGY_KEYWORDS = {
        "cause", "etiology", "aetiology", "pathogenesis", "mechanism",
        "association", "risk factor", "病因", "機轉",
    }
    
    # PICO indicator patterns
    PICO_POPULATION_INDICATORS = {
        "in", "among", "for", "with", "患者", "病人", "患有",
    }
    PICO_INTERVENTION_INDICATORS = {
        "using", "with", "receiving", "given", "administered",
        "使用", "給予", "接受",
    }
    PICO_COMPARISON_INDICATORS = {
        "vs", "versus", "compared to", "compared with", "or",
        "相比", "對比", "比較",
    }
    PICO_OUTCOME_INDICATORS = {
        "on", "effect on", "impact on", "outcome", "result",
        "對", "影響", "效果",
    }
    
    # Study type keywords
    STUDY_TYPE_KEYWORDS = {
        "rct": "Randomized Controlled Trial",
        "randomized": "Randomized Controlled Trial",
        "meta-analysis": "Meta-Analysis",
        "systematic review": "Systematic Review",
        "cohort": "Cohort Study",
        "case-control": "Case-Control Study",
        "observational": "Observational Study",
        "clinical trial": "Clinical Trial",
    }
    
    def __init__(self):
        """Initialize QueryAnalyzer."""
        pass
    
    def analyze(self, query: str) -> AnalyzedQuery:
        """
        Analyze a search query.
        
        Args:
            query: User's search query
            
        Returns:
            AnalyzedQuery with analysis results
        """
        # Normalize query
        normalized = self._normalize_query(query)
        
        # Extract identifiers
        identifiers = self._extract_identifiers(query)
        
        # Extract year constraints
        year_from, year_to = self._extract_year_constraints(query)
        
        # Detect intent
        intent = self._detect_intent(normalized, identifiers)
        
        # Extract keywords
        keywords = self._extract_keywords(normalized)
        
        # Detect PICO elements
        pico = self._detect_pico(normalized)
        
        # Detect clinical category
        clinical_category = self._detect_clinical_category(normalized)
        
        # Determine complexity
        complexity = self._determine_complexity(
            normalized, identifiers, pico, keywords
        )
        
        # Recommend sources
        sources = self._recommend_sources(complexity, intent, pico)
        
        # Recommend strategies
        strategies = self._recommend_strategies(complexity, intent, pico)
        
        # Calculate confidence
        confidence = self._calculate_confidence(
            identifiers, pico, clinical_category, keywords
        )
        
        return AnalyzedQuery(
            original_query=query,
            normalized_query=normalized,
            complexity=complexity,
            intent=intent,
            pico=pico,
            identifiers=identifiers,
            keywords=keywords,
            clinical_category=clinical_category,
            year_from=year_from,
            year_to=year_to,
            recommended_sources=sources,
            recommended_strategies=strategies,
            confidence=confidence,
        )
    
    def _normalize_query(self, query: str) -> str:
        """Normalize query string."""
        # Strip whitespace
        query = query.strip()
        
        # Normalize whitespace
        query = re.sub(r"\s+", " ", query)
        
        # Don't lowercase (preserve case for identifiers)
        return query
    
    def _extract_identifiers(self, query: str) -> list[ExtractedIdentifier]:
        """Extract identifiers (PMID, DOI, etc.) from query."""
        identifiers = []
        
        # Check for PMID
        for match in self.PMID_PATTERN.finditer(query):
            identifiers.append(ExtractedIdentifier(
                type="pmid",
                value=match.group(1),
                confidence=1.0,
            ))
        
        # Check for DOI
        for match in self.DOI_PATTERN.finditer(query):
            identifiers.append(ExtractedIdentifier(
                type="doi",
                value=match.group(1),
                confidence=1.0,
            ))
        
        # Check for PMC
        for match in self.PMC_PATTERN.finditer(query):
            identifiers.append(ExtractedIdentifier(
                type="pmc",
                value=f"PMC{match.group(1)}",
                confidence=1.0,
            ))
        
        # Check for arXiv
        for match in self.ARXIV_PATTERN.finditer(query):
            identifiers.append(ExtractedIdentifier(
                type="arxiv",
                value=match.group(1),
                confidence=1.0,
            ))
        
        return identifiers
    
    def _extract_year_constraints(self, query: str) -> tuple[int | None, int | None]:
        """Extract year constraints from query."""
        year_from = None
        year_to = None
        
        # Check for year range
        range_match = self.YEAR_RANGE_PATTERN.search(query)
        if range_match:
            year_from = int(range_match.group(1))
            year_to = int(range_match.group(2))
            return year_from, year_to
        
        # Check for "recent" or "last N years"
        recent_match = self.RECENT_PATTERN.search(query)
        if recent_match:
            # Default to last 5 years
            import datetime
            current_year = datetime.datetime.now().year
            year_from = current_year - 5
            year_to = current_year
            return year_from, year_to
        
        # Check for single year mentions
        years = []
        for match in self.YEAR_PATTERN.finditer(query):
            years.append(int(match.group(1)))
        
        if years:
            # If single year mentioned, use as lower bound
            if len(years) == 1:
                year_from = years[0]
            else:
                year_from = min(years)
                year_to = max(years)
        
        return year_from, year_to
    
    def _detect_intent(
        self, 
        query: str, 
        identifiers: list[ExtractedIdentifier]
    ) -> QueryIntent:
        """Detect user's search intent."""
        query_lower = query.lower()
        
        # LOOKUP: Has specific identifiers
        if identifiers:
            return QueryIntent.LOOKUP
        
        # CITATION_TRACKING: Mentions citing/related
        if any(kw in query_lower for kw in ["citing", "cited by", "related to", "引用"]):
            return QueryIntent.CITATION_TRACKING
        
        # AUTHOR_SEARCH: Mentions author/publications by
        if any(kw in query_lower for kw in ["author", "publications by", "papers by", "作者"]):
            return QueryIntent.AUTHOR_SEARCH
        
        # COMPARISON: Has comparison keywords
        if any(kw in query_lower for kw in self.COMPARISON_KEYWORDS):
            return QueryIntent.COMPARISON
        
        # SYSTEMATIC: Has PICO-like structure or mentions systematic
        if any(kw in query_lower for kw in ["systematic", "meta-analysis", "pico", "系統性"]):
            return QueryIntent.SYSTEMATIC
        
        # Default: EXPLORATION
        return QueryIntent.EXPLORATION
    
    def _extract_keywords(self, query: str) -> list[str]:
        """Extract significant keywords from query."""
        # Remove common stop words
        stop_words = {
            "a", "an", "the", "is", "are", "was", "were", "be", "been",
            "in", "on", "at", "for", "to", "of", "and", "or", "with",
            "by", "from", "as", "that", "which", "this", "these",
            "what", "how", "why", "when", "where", "who",
            "can", "could", "would", "should", "may", "might",
            "have", "has", "had", "do", "does", "did",
            "的", "是", "在", "和", "與", "或", "對", "於",
        }
        
        # Tokenize (simple word split)
        words = re.findall(r"\b[a-zA-Z\u4e00-\u9fff]{2,}\b", query)
        
        # Filter stop words and short words
        keywords = [
            word for word in words 
            if word.lower() not in stop_words and len(word) > 2
        ]
        
        return keywords[:10]  # Limit to top 10
    
    def _detect_pico(self, query: str) -> PICOElements | None:
        """
        Detect PICO elements from query.
        
        This is a heuristic detection - for accurate PICO extraction,
        use the parse_pico tool.
        """
        query_lower = query.lower()
        
        # Quick check: Does it look like a clinical question?
        has_comparison = any(kw in query_lower for kw in self.COMPARISON_KEYWORDS)
        has_clinical = any(kw in query_lower for kw in 
                         self.CLINICAL_THERAPY_KEYWORDS | 
                         self.CLINICAL_DIAGNOSIS_KEYWORDS)
        
        if not (has_comparison or has_clinical):
            return None
        
        # Try to extract basic PICO structure
        pico = PICOElements()
        
        # Pattern: "X vs Y in/for Z"
        vs_pattern = re.compile(
            r"(\w+(?:\s+\w+)?)\s+(?:vs\.?|versus|compared?\s+(?:to|with))\s+(\w+(?:\s+\w+)?)"
            r"(?:\s+(?:in|for|among)\s+(.+?))?(?:\s+(?:on|for)\s+(.+))?",
            re.IGNORECASE
        )
        
        match = vs_pattern.search(query)
        if match:
            pico.intervention = match.group(1)
            pico.comparison = match.group(2)
            if match.group(3):
                pico.population = match.group(3)
            if match.group(4):
                pico.outcome = match.group(4)
        
        # Only return if we found something
        if pico.intervention or pico.comparison:
            return pico
        
        return None
    
    def _detect_clinical_category(
        self, 
        query: str
    ) -> Literal["therapy", "diagnosis", "prognosis", "etiology", "prediction"] | None:
        """Detect clinical question category for PubMed Clinical Queries."""
        query_lower = query.lower()
        
        # Check each category
        if any(kw in query_lower for kw in self.CLINICAL_THERAPY_KEYWORDS):
            return "therapy"
        if any(kw in query_lower for kw in self.CLINICAL_DIAGNOSIS_KEYWORDS):
            return "diagnosis"
        if any(kw in query_lower for kw in self.CLINICAL_PROGNOSIS_KEYWORDS):
            return "prognosis"
        if any(kw in query_lower for kw in self.CLINICAL_ETIOLOGY_KEYWORDS):
            return "etiology"
        
        return None
    
    def _determine_complexity(
        self,
        query: str,
        identifiers: list[ExtractedIdentifier],
        pico: PICOElements | None,
        keywords: list[str],
    ) -> QueryComplexity:
        """Determine query complexity level."""
        query_lower = query.lower()
        
        # SIMPLE: Direct identifier lookup
        if identifiers and len(keywords) < 3:
            return QueryComplexity.SIMPLE
        
        # SIMPLE: Very short query (1-2 words) without comparison
        if len(keywords) <= 2 and not pico:
            # Check if it's a genuine comparison (e.g., "A vs B")
            has_real_comparison = bool(re.search(
                r'\b\w+\s+(?:vs\.?|versus)\s+\w+', query_lower
            ))
            if not has_real_comparison:
                return QueryComplexity.SIMPLE
        
        # COMPLEX: Has PICO structure with at least intervention AND (comparison OR outcome)
        if pico and pico.intervention and (pico.comparison or pico.outcome):
            return QueryComplexity.COMPLEX
        
        # COMPLEX: Has genuine comparison structure (A vs B pattern, not just "vs" anywhere)
        # Must have actual entities on both sides
        comparison_match = re.search(
            r'\b(\w{3,})\s+(?:vs\.?|versus|compared?\s+(?:to|with))\s+(\w{3,})', 
            query_lower
        )
        if comparison_match:
            # Only COMPLEX if both sides are substantive words (not "the vs that")
            left = comparison_match.group(1)
            right = comparison_match.group(2)
            stopwords = {'the', 'this', 'that', 'with', 'and', 'for', 'from'}
            if left not in stopwords and right not in stopwords:
                return QueryComplexity.COMPLEX
        
        # AMBIGUOUS: Very broad single term
        if len(keywords) == 1 and keywords[0].lower() in {
            "cancer", "diabetes", "heart", "brain", "treatment",
            "癌症", "糖尿病", "心臟", "大腦", "治療",
        }:
            return QueryComplexity.AMBIGUOUS
        
        # MODERATE: Default for multi-term queries (3+ keywords)
        if len(keywords) >= 3:
            return QueryComplexity.MODERATE
        
        # Default: SIMPLE for 2-keyword queries without special structure
        return QueryComplexity.SIMPLE
    
    def _recommend_sources(
        self,
        complexity: QueryComplexity,
        intent: QueryIntent,
        pico: PICOElements | None,
    ) -> list[str]:
        """Recommend data sources based on analysis."""
        sources = []
        
        # LOOKUP: Just need primary source
        if intent == QueryIntent.LOOKUP:
            sources = ["pubmed", "crossref"]
            return sources
        
        # SIMPLE: PubMed + optional CrossRef for DOI enrichment
        if complexity == QueryComplexity.SIMPLE:
            sources = ["pubmed"]
            return sources
        
        # COMPLEX/SYSTEMATIC: Full multi-source
        if complexity in (QueryComplexity.COMPLEX, QueryComplexity.AMBIGUOUS):
            sources = ["pubmed", "crossref", "openalex", "semantic_scholar"]
            return sources
        
        # MODERATE: PubMed + one alternative
        sources = ["pubmed", "crossref"]
        return sources
    
    def _recommend_strategies(
        self,
        complexity: QueryComplexity,
        intent: QueryIntent,
        pico: PICOElements | None,
    ) -> list[str]:
        """Recommend search strategies based on analysis."""
        strategies = []
        
        # LOOKUP: Direct identifier search
        if intent == QueryIntent.LOOKUP:
            strategies = ["direct_lookup"]
            return strategies
        
        # COMPARISON: Need comparison-focused search
        if intent == QueryIntent.COMPARISON:
            strategies = ["pico_search", "comparison_filter"]
            if pico:
                strategies.append("mesh_expansion")
            return strategies
        
        # SYSTEMATIC: Comprehensive strategies
        if intent == QueryIntent.SYSTEMATIC:
            strategies = ["pico_search", "mesh_expansion", "title_abstract", "clinical_queries"]
            return strategies
        
        # Default strategies
        if complexity == QueryComplexity.COMPLEX:
            strategies = ["mesh_expansion", "title_abstract", "clinical_queries"]
        elif complexity == QueryComplexity.AMBIGUOUS:
            strategies = ["broad_search", "faceted_search"]
        else:
            strategies = ["relevance_search"]
        
        return strategies
    
    def _calculate_confidence(
        self,
        identifiers: list[ExtractedIdentifier],
        pico: PICOElements | None,
        clinical_category: str | None,
        keywords: list[str],
    ) -> float:
        """Calculate confidence in analysis (0-1)."""
        confidence = 0.5  # Base confidence
        
        # Boost for identifiers
        if identifiers:
            confidence += 0.3
        
        # Boost for complete PICO
        if pico and pico.is_complete:
            confidence += 0.2
        elif pico:
            confidence += 0.1
        
        # Boost for clinical category detection
        if clinical_category:
            confidence += 0.1
        
        # Boost for meaningful keywords
        if len(keywords) >= 3:
            confidence += 0.1
        
        return min(confidence, 1.0)


# Convenience function
def analyze_query(query: str) -> AnalyzedQuery:
    """
    Analyze a search query (convenience function).
    
    Args:
        query: User's search query
        
    Returns:
        AnalyzedQuery with analysis results
    """
    analyzer = QueryAnalyzer()
    return analyzer.analyze(query)
