"""
ImageQueryAdvisor - Intelligent Query Analysis for Image Search

Analyzes user queries before image search to:
1. Determine if the query is suitable for image search
2. Recommend the best image_type parameter
3. Warn about Open-i temporal limitations (~2020 cutoff)
4. Suggest alternative tools when image search is not appropriate

Architecture Decision:
    ImageQueryAdvisor is stateless and uses heuristics + patterns.
    It does NOT call any external APIs - pure local processing for speed.
    Follows the same pattern as QueryAnalyzer (text search).

Example:
    >>> advisor = ImageQueryAdvisor()
    >>> advice = advisor.advise("chest pneumonia X-ray")
    >>> advice.is_suitable
    True
    >>> advice.recommended_image_type
    'x'
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .advisor_policy import NON_ENGLISH_EXAMPLES, NON_LATIN_PATTERN, SUITABILITY_THRESHOLD, TYPE_LABELS
from .advisor_scorer import (
    build_diagnostics,
    check_temporal_relevance,
    enhance_query,
    recommend_collection,
    recommend_image_type,
    score_image_suitability,
)


@dataclass
class ImageSearchAdvice:
    """
    Result of image query analysis.

    Contains guidance for the agent on how to use the image search tool,
    or whether to use a different tool entirely.
    """

    # Core assessment
    is_suitable: bool  # Query is suitable for image search
    confidence: float  # 0.0-1.0 confidence in assessment

    # Image type recommendation
    recommended_image_type: str | None = None  # "xg", "mc", "ph", "g", etc.
    image_type_reason: str = ""  # Why this type was recommended

    # Coarse category (粗分類)
    coarse_category: str | None = None  # "radiology", "microscopy", etc.

    # Collection recommendation
    recommended_collection: str | None = None  # "pmc", "cxr", "mpx", etc.
    collection_reason: str = ""

    # Warnings and suggestions
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    # Query enhancement
    enhanced_query: str | None = None  # Optimized query for image search

    # Explainable diagnostics
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def has_warnings(self) -> bool:
        """Check if any warnings were generated."""
        return len(self.warnings) > 0

    def format_warnings(self) -> str:
        """Format warnings as a single string."""
        if not self.warnings:
            return ""
        return " | ".join(f"⚠️ {w}" for w in self.warnings)

    def format_suggestions(self) -> str:
        """Format suggestions as a single string."""
        if not self.suggestions:
            return ""
        return " | ".join(f"💡 {s}" for s in self.suggestions)


class ImageQueryAdvisor:
    """
    Intelligent image search query advisor.

    Analyzes queries to prevent agent misuse of the image search tool:
    - Detects non-image queries (pure literature search)
    - Recommends optimal image_type based on query content
    - Warns about Open-i temporal limitations
    - Suggests image_type corrections

    Usage:
        advisor = ImageQueryAdvisor()
        advice = advisor.advise("histology liver biopsy")
        # advice.recommended_image_type == "mc"  (microscopy)

        advice = advisor.advise("remimazolam pharmacokinetics")
        # advice.is_suitable == False  (not an image query)
    """

    def advise(
        self,
        query: str,
        image_type: str | None = None,
    ) -> ImageSearchAdvice:
        """
        Analyze a query and provide image search guidance.

        Args:
            query: User's search query
            image_type: Explicitly specified image type (if any)

        Returns:
            ImageSearchAdvice with suitability, recommendations, and warnings
        """
        query_lower = query.lower().strip()
        warnings: list[str] = []
        suggestions: list[str] = []

        # 1. Check image suitability
        suitability_score, suitability_hits = score_image_suitability(query_lower)
        is_suitable = suitability_score >= SUITABILITY_THRESHOLD

        # 2. Recommend image type (all 10 types)
        recommended_type, type_reason, coarse_category, image_type_scores, image_type_hits = recommend_image_type(
            query_lower
        )

        # 3. Determine coarse category
        recommended_coll, coll_reason, collection_scores, collection_hits = recommend_collection(query_lower)

        # 5. Non-English query detection (Agent must translate)
        non_english_info = self._detect_non_english(query_lower)
        if non_english_info["is_non_english"]:
            # MCP only detects - Agent must translate (see CONSTITUTION 第 7.4 條)
            warnings.append(f"⚠️ {non_english_info['error_message']}")
            suggestions.append(
                "Translate the query to English medical terms, then call "
                "search_biomedical_images() with the English query.\n"
                f"{non_english_info['examples']}"
            )

        # 6. Check image_type mismatch
        if image_type and recommended_type and image_type != recommended_type:
            warnings.append(
                f"查詢內容偏向 {self._type_label(recommended_type)}，"
                f"但指定了 {self._type_label(image_type)}。"
                f'建議用 image_type="{recommended_type}"'
            )

        # 7. Temporal relevance check
        temporal_warning, temporal_hit = check_temporal_relevance(query_lower)
        if temporal_warning:
            warnings.append(temporal_warning)

        # 8. Non-image query suggestions
        if not is_suitable:
            suggestions.append("此查詢更適合文獻搜尋。建議改用 unified_search()")
            if suitability_score < 0.1:
                suggestions.append(
                    "查詢內容不含影像相關詞彙。若確實需要圖片，請加入 X-ray、histology、CT scan 等關鍵字"
                )

        # 9. Query enhancement (non-English queries: Agent must translate first)
        # MCP does NOT translate - it only enhances English queries
        # Cannot enhance non-English - Agent must translate first
        enhancement_hits: list[dict[str, Any]] = []
        if non_english_info["is_non_english"]:
            enhanced = None
        else:
            enhanced, enhancement_hits = enhance_query(query_lower)

        diagnostics = build_diagnostics(
            suitability_score=suitability_score,
            suitability_hits=suitability_hits,
            image_type_scores=image_type_scores,
            image_type_hits=image_type_hits,
            collection_scores=collection_scores,
            collection_hits=collection_hits,
            temporal_hit=temporal_hit,
            enhancement_hits=enhancement_hits,
            non_english_info=non_english_info,
            explicit_image_type=image_type,
            recommended_type=recommended_type,
        )

        return ImageSearchAdvice(
            is_suitable=is_suitable,
            confidence=min(abs(suitability_score), 1.0),
            recommended_image_type=recommended_type,
            image_type_reason=type_reason,
            coarse_category=coarse_category,
            recommended_collection=recommended_coll,
            collection_reason=coll_reason,
            warnings=warnings,
            suggestions=suggestions,
            enhanced_query=enhanced if enhanced != query_lower else None,
            diagnostics=diagnostics,
        )

    def _score_image_suitability(self, query_lower: str) -> float:
        """
        Score how suitable a query is for image search.

        Returns:
            Score from -1.0 (definitely NOT image) to 1.0 (definitely image).
            Threshold for suitability: >= 0.3
        """
        score, _ = score_image_suitability(query_lower)
        return score

    def _recommend_image_type(self, query_lower: str) -> tuple[str | None, str]:
        """
        Recommend the best image_type based on query content.

        Covers all 10 valid Open-i `it` values:
        xg, x, xm (radiology), mc, m (microscopy),
        ph, p (photo), g (graphics), u (ultrasound), c (CT).

        Strategy:
        - Score each of the 5 keyword groups
        - Map winner to the best specific `it` value
        - CT and ultrasound have their own dedicated types

        Returns:
            (image_type, reason) tuple
        """
        recommended_type, reason, _coarse_category, _scores, _hits = recommend_image_type(query_lower)
        return recommended_type, reason

    def _recommend_collection(self, query_lower: str) -> tuple[str | None, str]:
        """
        Recommend the best collection based on query content.

        Valid collections: pmc, cxr, mpx, hmd, usc

        Returns:
            (collection, reason) tuple. None means all collections.
        """
        recommended_collection, reason, _scores, _hits = recommend_collection(query_lower)
        return recommended_collection, reason

    def _check_temporal_relevance(self, query_lower: str) -> str | None:
        """
        Check if the query targets content newer than Open-i's index (~2020).

        Returns:
            Warning message string, or None if no temporal issue
        """
        warning, _hit = check_temporal_relevance(query_lower)
        return warning

    def _enhance_query(self, query_lower: str, recommended_type: str | None) -> str:
        """
        Optionally enhance the query for better image search results.

        Removes non-image-relevant terms that might reduce results.
        """
        enhanced, _hits = enhance_query(query_lower)
        return enhanced

    def _detect_non_english(self, query: str) -> dict:
        """
        Detect non-English (CJK/Cyrillic/Arabic/Thai) characters in query.

        NOTE: This method ONLY detects - it does NOT translate.
        Translation is the Agent's responsibility (Agent has LLM capability).
        See CONSTITUTION.md 第 7.4 條.

        Returns:
            dict with:
            - is_non_english: bool
            - detected_script: str (e.g., "CJK", "Cyrillic", "Latin")
            - error_message: str | None (guidance for Agent)
            - examples: str | None (translation examples for Agent)
        """
        if not NON_LATIN_PATTERN.search(query):
            return {
                "is_non_english": False,
                "detected_script": "Latin",
                "error_message": None,
                "examples": None,
            }

        # Detect script type
        detected_script = "Unknown"
        for char in query:
            cp = ord(char)
            if 0x4E00 <= cp <= 0x9FFF:
                detected_script = "CJK"
                break
            if 0x3040 <= cp <= 0x30FF:
                detected_script = "Japanese"
                break
            if 0xAC00 <= cp <= 0xD7AF:
                detected_script = "Korean"
                break
            if 0x0400 <= cp <= 0x04FF:
                detected_script = "Cyrillic"
                break
            if 0x0600 <= cp <= 0x06FF:
                detected_script = "Arabic"
                break

        return {
            "is_non_english": True,
            "detected_script": detected_script,
            "error_message": (
                f"Open-i API only supports English queries. "
                f"Your query '{query}' contains {detected_script} characters. "
                f"Please translate to English medical terminology and retry."
            ),
            "examples": NON_ENGLISH_EXAMPLES,
        }

    @staticmethod
    def _type_label(image_type: str) -> str:
        """Human-readable label for image type codes."""
        return TYPE_LABELS.get(image_type, image_type)


# Convenience function
def advise_image_search(query: str, image_type: str | None = None) -> ImageSearchAdvice:
    """
    Analyze a query for image search suitability (convenience function).

    Args:
        query: User's search query
        image_type: Explicitly specified image type (if any)

    Returns:
        ImageSearchAdvice with recommendations and warnings
    """
    advisor = ImageQueryAdvisor()
    return advisor.advise(query, image_type)
