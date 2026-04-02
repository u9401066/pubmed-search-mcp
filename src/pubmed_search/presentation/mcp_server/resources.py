"""
MCP Resources - 提供過濾條件說明和工具文檔

Resources:
- pubmed://filters/age_group
- pubmed://filters/clinical_query
- pubmed://filters/all
- pubmed://tools/reference
- pubmed://icd/lookup
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from .tool_registry import TOOL_CATEGORIES as TOOL_REGISTRY_CATEGORIES

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


# ============================================================================
# Filter Reference Data
# ============================================================================

AGE_GROUP_REFERENCE = {
    "description": "PubMed 年齡層過濾器 (MeSH-based)",
    "options": {
        "newborn": {"mesh": '"Infant, Newborn"[MeSH]', "age_range": "0-1 month"},
        "infant": {"mesh": '"Infant"[MeSH]', "age_range": "1-23 months"},
        "preschool": {"mesh": '"Child, Preschool"[MeSH]', "age_range": "2-5 years"},
        "child": {"mesh": '"Child"[MeSH]', "age_range": "6-12 years"},
        "adolescent": {"mesh": '"Adolescent"[MeSH]', "age_range": "13-18 years"},
        "young_adult": {"mesh": '"Young Adult"[MeSH]', "age_range": "19-24 years"},
        "adult": {"mesh": '"Adult"[MeSH]', "age_range": "19+ years (general)"},
        "middle_aged": {"mesh": '"Middle Aged"[MeSH]', "age_range": "45-64 years"},
        "aged": {"mesh": '"Aged"[MeSH]', "age_range": "65+ years"},
        "aged_80": {"mesh": '"Aged, 80 and over"[MeSH]', "age_range": "80+ years"},
    },
    "usage_example": 'unified_search(query="diabetes", filters="age:aged")',
}

SEX_REFERENCE = {
    "description": "性別過濾器 (MeSH-based)",
    "options": {
        "male": {"mesh": '"Male"[MeSH]'},
        "female": {"mesh": '"Female"[MeSH]'},
    },
    "usage_example": 'unified_search(query="breast cancer", filters="sex:female")',
}

SPECIES_REFERENCE = {
    "description": "物種過濾器 (MeSH-based)",
    "options": {
        "humans": {"mesh": '"Humans"[MeSH]', "note": "Human studies only"},
        "animals": {"mesh": '"Animals"[MeSH]', "note": "Animal studies only"},
    },
    "usage_example": 'unified_search(query="gene therapy", filters="species:humans")',
}

LANGUAGE_REFERENCE = {
    "description": "語言過濾器",
    "options": {
        "english": {"syntax": "eng[la]"},
        "chinese": {"syntax": "chi[la]"},
        "japanese": {"syntax": "jpn[la]"},
        "german": {"syntax": "ger[la]"},
        "french": {"syntax": "fre[la]"},
        "spanish": {"syntax": "spa[la]"},
        "korean": {"syntax": "kor[la]"},
        "italian": {"syntax": "ita[la]"},
        "portuguese": {"syntax": "por[la]"},
        "russian": {"syntax": "rus[la]"},
    },
    "note": "也可使用其他 ISO 語言代碼如 'jpn', 'kor' 等",
    "usage_example": 'unified_search(query="COVID-19", filters="lang:english")',
}

CLINICAL_QUERY_REFERENCE = {
    "description": "PubMed Clinical Queries 過濾器 (EBM 搜尋策略)",
    "reference_url": "https://www.ncbi.nlm.nih.gov/pubmed/clinical",
    "options": {
        "therapy": {
            "syntax": "(Therapy/Broad[filter])",
            "scope": "Broad (high sensitivity)",
            "use_case": "治療效果、臨床試驗",
        },
        "therapy_narrow": {
            "syntax": "(Therapy/Narrow[filter])",
            "scope": "Narrow (high specificity)",
            "use_case": "只要高品質 RCT",
        },
        "diagnosis": {
            "syntax": "(Diagnosis/Broad[filter])",
            "scope": "Broad",
            "use_case": "診斷準確度、敏感度/特異度",
        },
        "diagnosis_narrow": {
            "syntax": "(Diagnosis/Narrow[filter])",
            "scope": "Narrow",
            "use_case": "高品質診斷研究",
        },
        "prognosis": {
            "syntax": "(Prognosis/Broad[filter])",
            "scope": "Broad",
            "use_case": "預後、存活率、疾病進程",
        },
        "prognosis_narrow": {
            "syntax": "(Prognosis/Narrow[filter])",
            "scope": "Narrow",
            "use_case": "高品質預後研究",
        },
        "etiology": {
            "syntax": "(Etiology/Broad[filter])",
            "scope": "Broad",
            "use_case": "病因、風險因子",
        },
        "etiology_narrow": {
            "syntax": "(Etiology/Narrow[filter])",
            "scope": "Narrow",
            "use_case": "高品質病因研究",
        },
        "clinical_prediction": {
            "syntax": "(Clinical Prediction Guides/Broad[filter])",
            "scope": "Broad",
            "use_case": "臨床預測規則、決策輔助",
        },
        "clinical_prediction_narrow": {
            "syntax": "(Clinical Prediction Guides/Narrow[filter])",
            "scope": "Narrow",
            "use_case": "驗證過的預測工具",
        },
    },
    "usage_example": 'unified_search(query="diabetes treatment", filters="clinical:therapy")',
}

ARTICLE_TYPE_REFERENCE = {
    "description": "文章類型過濾器 [pt]",
    "common_types": {
        "Review": "綜述文章",
        "Systematic Review": "系統性回顧",
        "Meta-Analysis": "統合分析",
        "Randomized Controlled Trial": "隨機對照試驗",
        "Clinical Trial": "臨床試驗",
        "Case Reports": "個案報告",
        "Guideline": "指引",
        "Practice Guideline": "臨床指引",
        "Editorial": "社論",
        "Letter": "讀者來函",
        "Comment": "評論",
    },
    "usage_example": 'unified_search(query="COVID-19 AND "Systematic Review"[pt]")',
}

# ============================================================================
# ============================================================================
# Tool Reference
# ============================================================================

TOOL_CATEGORIES = TOOL_REGISTRY_CATEGORIES


# ============================================================================
# Register Resources
# ============================================================================


def register_resources(mcp: FastMCP):
    """Register all MCP resources for filter and tool documentation."""

    @mcp.resource("pubmed://filters/age_group")
    def get_age_group_filters() -> str:
        """Age group filter options for PubMed search."""
        return json.dumps(AGE_GROUP_REFERENCE, indent=2, ensure_ascii=False)

    @mcp.resource("pubmed://filters/sex")
    def get_sex_filters() -> str:
        """Sex filter options for PubMed search."""
        return json.dumps(SEX_REFERENCE, indent=2, ensure_ascii=False)

    @mcp.resource("pubmed://filters/species")
    def get_species_filters() -> str:
        """Species filter options for PubMed search."""
        return json.dumps(SPECIES_REFERENCE, indent=2, ensure_ascii=False)

    @mcp.resource("pubmed://filters/language")
    def get_language_filters() -> str:
        """Language filter options for PubMed search."""
        return json.dumps(LANGUAGE_REFERENCE, indent=2, ensure_ascii=False)

    @mcp.resource("pubmed://filters/clinical_query")
    def get_clinical_query_filters() -> str:
        """Clinical query filter options (PubMed Clinical Queries)."""
        return json.dumps(CLINICAL_QUERY_REFERENCE, indent=2, ensure_ascii=False)

    @mcp.resource("pubmed://filters/article_type")
    def get_article_type_filters() -> str:
        """Article type filter options for PubMed search."""
        return json.dumps(ARTICLE_TYPE_REFERENCE, indent=2, ensure_ascii=False)

    @mcp.resource("pubmed://filters/all")
    def get_all_filters() -> str:
        """Complete reference for all PubMed search filters."""
        return json.dumps(
            {
                "age_group": AGE_GROUP_REFERENCE,
                "sex": SEX_REFERENCE,
                "species": SPECIES_REFERENCE,
                "language": LANGUAGE_REFERENCE,
                "clinical_query": CLINICAL_QUERY_REFERENCE,
                "article_type": ARTICLE_TYPE_REFERENCE,
            },
            indent=2,
            ensure_ascii=False,
        )

    @mcp.resource("pubmed://tools/reference")
    def get_tools_reference() -> str:
        """Complete reference for all available MCP tools."""
        return json.dumps(TOOL_CATEGORIES, indent=2, ensure_ascii=False)

    @mcp.resource("pubmed://icd/mapping")
    def get_icd_mapping() -> str:
        """ICD-9/10 to MeSH mapping reference."""
        return json.dumps(
            {
                "description": "ICD to MeSH bidirectional mapping",
                "supported_icd10_codes": "See tools/icd.py",
                "supported_icd9_codes": "See tools/icd.py",
                "usage": {
                    "icd_to_mesh": 'convert_icd_mesh(code="E11")',
                    "mesh_to_icd": 'convert_icd_mesh(mesh_term="Diabetes Mellitus")',
                },
            },
            indent=2,
            ensure_ascii=False,
        )

    logger.info("Registered MCP resources for filters and tools")
