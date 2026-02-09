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
    'xg'
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


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
    recommended_image_type: str | None = None  # "xg", "mc", "ph", "g"
    image_type_reason: str = ""  # Why this type was recommended

    # Warnings and suggestions
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    # Query enhancement
    enhanced_query: str | None = None  # Optimized query for image search

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

    # ─── Image Relevance Keywords ───────────────────────────────────
    # Queries containing these are LIKELY suitable for image search

    IMAGE_POSITIVE_KEYWORDS = {
        # English
        "image", "images", "picture", "pictures", "photo", "photos",
        "photograph", "scan", "scans", "x-ray", "xray", "x ray",
        "radiograph", "radiography", "ct scan", "mri", "ultrasound",
        "echocardiography", "mammography", "fluoroscopy",
        "microscopy", "histology", "histopathology", "pathology",
        "cytology", "biopsy", "slide", "staining",
        "figure", "illustration", "diagram", "chart",
        "clinical appearance", "gross appearance", "visual",
        "morphology", "anatomy", "dermoscopy", "endoscopy",
        "fundoscopy", "ophthalmoscopy", "angiography",
        # Chinese
        "圖片", "影像", "照片", "X光", "X射線", "掃描",
        "顯微鏡", "組織學", "病理", "切片",
    }

    # Queries containing these are UNLIKELY suitable for image search
    IMAGE_NEGATIVE_KEYWORDS = {
        # English
        "pharmacokinetics", "pharmacodynamics", "mechanism of action",
        "drug interaction", "dosing", "dosage", "protocol",
        "guideline", "guidelines", "meta-analysis", "systematic review",
        "randomized", "randomised", "clinical trial", "rct",
        "prevalence", "incidence", "epidemiology", "statistics",
        "gene expression", "molecular", "genomics", "proteomics",
        "biomarker", "pathway", "signaling", "receptor",
        "cost-effectiveness", "economic", "policy",
        "survey", "questionnaire", "interview",
        # Chinese
        "藥物動力學", "藥理", "劑量", "指南", "統合分析",
        "系統性回顧", "隨機", "臨床試驗", "流行病學",
        "基因表達", "分子", "生物標記",
    }

    # ─── Image Type Detection Keywords ──────────────────────────────

    # X-ray / Radiology → "xg"
    RADIOLOGY_KEYWORDS = {
        "x-ray", "xray", "x ray", "radiograph", "radiography",
        "chest", "lung", "thorax", "bone", "fracture", "skeletal",
        "spine", "vertebra", "pelvis", "abdomen", "abdominal",
        "ct", "ct scan", "computed tomography",
        "mri", "magnetic resonance",
        "mammography", "mammogram",
        "fluoroscopy", "barium",
        "angiography", "angiogram",
        "pneumonia", "pneumothorax", "pleural", "effusion",
        "cardiomegaly", "mediastinal",
        "X光", "胸部", "骨折", "脊椎", "腹部",
    }

    # Microscopy → "mc"
    MICROSCOPY_KEYWORDS = {
        "histology", "histological", "histopathology", "histopathological",
        "microscopy", "microscopic", "micrograph",
        "pathology", "pathological",
        "cytology", "cytological",
        "biopsy", "tissue", "specimen",
        "staining", "stain", "h&e", "hematoxylin", "eosin",
        "immunohistochemistry", "ihc",
        "slide", "section", "thin section",
        "cell", "cells", "cellular",
        "tumor", "tumour", "neoplasm",
        "granuloma", "fibrosis", "necrosis", "inflammation",
        "顯微鏡", "組織學", "病理", "切片", "染色", "細胞",
    }

    # Photo → "ph"
    PHOTO_KEYWORDS = {
        "photo", "photograph", "photography", "clinical photo",
        "clinical appearance", "gross appearance", "gross pathology",
        "skin", "dermatology", "dermatological", "rash", "lesion",
        "wound", "ulcer", "burn", "scar",
        "eye", "ophthalmology", "fundus", "retina",
        "endoscopy", "endoscopic", "colonoscopy", "bronchoscopy",
        "surgery", "surgical", "intraoperative",
        "anatomical", "cadaver", "dissection",
        "照片", "皮膚", "傷口", "內視鏡", "手術",
    }

    # Graphics → "gl"
    GRAPHICS_KEYWORDS = {
        "diagram", "schematic", "illustration", "drawing",
        "flowchart", "flow chart", "algorithm",
        "graph", "chart", "plot", "figure",
        "infographic", "visualization",
        "anatomical diagram", "pathway diagram",
        "圖表", "流程圖", "示意圖", "插圖",
    }

    # ─── Temporal Limitation Detection ──────────────────────────────
    # Open-i index is frozen at ~2020

    POST_2020_KEYWORDS = {
        "covid-19", "sars-cov-2", "omicron", "delta variant",
        "monkeypox", "mpox", "long covid",
        "2021", "2022", "2023", "2024", "2025", "2026",
        "chatgpt", "gpt-4", "large language model", "llm",
        "新冠", "猴痘", "長新冠",
    }

    # Year pattern for detecting recent year ranges
    YEAR_PATTERN = re.compile(r"\b(202[1-9]|20[3-9]\d)\b")

    # ─── Anatomical / Clinical Keywords (image-suitable) ───────────
    # These terms suggest visual/anatomical content even without
    # explicit "image" keywords

    ANATOMICAL_KEYWORDS = {
        "fracture", "dislocation", "effusion", "opacity",
        "consolidation", "infiltrate", "nodule", "mass",
        "tumor", "tumour", "cyst", "abscess",
        "stenosis", "occlusion", "aneurysm",
        "edema", "oedema", "hemorrhage", "haemorrhage",
        "atrophy", "hypertrophy", "calcification",
        "erosion", "deformity", "swelling",
    }

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
        suitability_score = self._score_image_suitability(query_lower)
        is_suitable = suitability_score >= 0.3

        # 2. Recommend image type
        recommended_type, type_reason = self._recommend_image_type(query_lower)

        # 3. Check image_type mismatch
        if image_type and recommended_type and image_type != recommended_type:
            warnings.append(
                f"查詢內容偏向 {self._type_label(recommended_type)}，"
                f"但指定了 {self._type_label(image_type)}。"
                f"建議用 image_type=\"{recommended_type}\""
            )

        # 4. Temporal relevance check
        temporal_warning = self._check_temporal_relevance(query_lower)
        if temporal_warning:
            warnings.append(temporal_warning)

        # 5. Non-image query suggestions
        if not is_suitable:
            suggestions.append(
                "此查詢更適合文獻搜尋。建議改用 unified_search() 或 search_literature()"
            )
            if suitability_score < 0.1:
                suggestions.append(
                    "查詢內容不含影像相關詞彙。若確實需要圖片，"
                    "請加入 X-ray、histology、CT scan 等關鍵字"
                )

        # 6. Query enhancement
        enhanced = self._enhance_query(query_lower, recommended_type)

        return ImageSearchAdvice(
            is_suitable=is_suitable,
            confidence=min(abs(suitability_score), 1.0),
            recommended_image_type=recommended_type,
            image_type_reason=type_reason,
            warnings=warnings,
            suggestions=suggestions,
            enhanced_query=enhanced if enhanced != query_lower else None,
        )

    def _score_image_suitability(self, query_lower: str) -> float:
        """
        Score how suitable a query is for image search.

        Returns:
            Score from -1.0 (definitely NOT image) to 1.0 (definitely image).
            Threshold for suitability: >= 0.3
        """
        score = 0.0

        # Positive signals
        positive_hits = sum(
            1 for kw in self.IMAGE_POSITIVE_KEYWORDS if kw in query_lower
        )
        score += min(positive_hits * 0.3, 0.9)

        # Anatomical/clinical keywords (moderate positive signal)
        anatomical_hits = sum(
            1 for kw in self.ANATOMICAL_KEYWORDS if kw in query_lower
        )
        score += min(anatomical_hits * 0.15, 0.45)

        # Negative signals
        negative_hits = sum(
            1 for kw in self.IMAGE_NEGATIVE_KEYWORDS if kw in query_lower
        )
        score -= min(negative_hits * 0.25, 0.75)

        # Radiology/Microscopy/Photo keywords are strong positive signals
        radiology_hits = sum(
            1 for kw in self.RADIOLOGY_KEYWORDS if kw in query_lower
        )
        microscopy_hits = sum(
            1 for kw in self.MICROSCOPY_KEYWORDS if kw in query_lower
        )
        photo_hits = sum(
            1 for kw in self.PHOTO_KEYWORDS if kw in query_lower
        )
        type_hits = radiology_hits + microscopy_hits + photo_hits
        score += min(type_hits * 0.2, 0.6)

        return max(-1.0, min(1.0, score))

    def _recommend_image_type(
        self, query_lower: str
    ) -> tuple[str | None, str]:
        """
        Recommend the best image_type based on query content.

        Returns:
            (image_type, reason) tuple
        """
        scores: dict[str, int] = {"xg": 0, "mc": 0, "ph": 0, "g": 0}

        for kw in self.RADIOLOGY_KEYWORDS:
            if kw in query_lower:
                scores["xg"] += 1

        for kw in self.MICROSCOPY_KEYWORDS:
            if kw in query_lower:
                scores["mc"] += 1

        for kw in self.PHOTO_KEYWORDS:
            if kw in query_lower:
                scores["ph"] += 1

        for kw in self.GRAPHICS_KEYWORDS:
            if kw in query_lower:
                scores["g"] += 1

        # Find the highest-scoring type
        max_score = max(scores.values())
        if max_score == 0:
            return "xg", "未偵測到特定影像類型關鍵字，使用預設 X-ray (xg) 最大覆蓋"

        best_type = max(scores, key=lambda k: scores[k])
        reasons = {
            "xg": "偵測到放射學/X光相關關鍵字",
            "mc": "偵測到顯微鏡/組織學/病理相關關鍵字",
            "ph": "偵測到臨床照片/皮膚/內視鏡相關關鍵字",
            "g": "偵測到圖表/示意圖/流程圖相關關鍵字",
        }

        return best_type, reasons.get(best_type, "")

    def _check_temporal_relevance(self, query_lower: str) -> str | None:
        """
        Check if the query targets content newer than Open-i's index (~2020).

        Returns:
            Warning message string, or None if no temporal issue
        """
        # Check post-2020 keywords
        for kw in self.POST_2020_KEYWORDS:
            if kw in query_lower:
                return (
                    f"Open-i 索引凍結於 ~2020，查詢含 '{kw}' "
                    "可能找不到相關結果。較新主題建議用 Europe PMC 全文搜尋"
                )

        # Check year patterns
        year_match = self.YEAR_PATTERN.search(query_lower)
        if year_match:
            year = year_match.group(1)
            return (
                f"Open-i 索引凍結於 ~2020，查詢含 '{year}' "
                "年份的文獻可能尚未索引"
            )

        return None

    def _enhance_query(
        self, query_lower: str, recommended_type: str | None
    ) -> str:
        """
        Optionally enhance the query for better image search results.

        Removes non-image-relevant terms that might reduce results.
        """
        # Remove common non-image modifiers that Open-i doesn't handle well
        noise_patterns = [
            r"\b(?:systematic review|meta-analysis|rct|randomized)\b",
            r"\b(?:guideline|protocol|consensus)\b",
            r"\b(?:recent|latest|2020s?|2021|2022|2023|2024|2025|2026)\b",
        ]
        enhanced = query_lower
        for pattern in noise_patterns:
            enhanced = re.sub(pattern, "", enhanced, flags=re.IGNORECASE)

        # Clean up extra whitespace
        enhanced = re.sub(r"\s+", " ", enhanced).strip()

        return enhanced if enhanced else query_lower

    @staticmethod
    def _type_label(image_type: str) -> str:
        """Human-readable label for image type codes."""
        labels = {
            "xg": "X-ray/放射 (xg)",
            "mc": "顯微鏡 (mc)",
            "ph": "臨床照片 (ph)",
            "g": "圖表/示意圖 (g)",
        }
        return labels.get(image_type, image_type)


# Convenience function
def advise_image_search(
    query: str, image_type: str | None = None
) -> ImageSearchAdvice:
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
