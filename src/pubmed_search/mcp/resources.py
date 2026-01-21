"""
MCP Resources - 提供過濾條件說明和工具文檔

Resources:
- pubmed://filters/age_group
- pubmed://filters/clinical_query
- pubmed://filters/all
- pubmed://tools/reference
- pubmed://icd/lookup
"""

import json
import logging
from typing import Optional

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
    "usage_example": 'search_literature(query="diabetes", age_group="aged")',
}

SEX_REFERENCE = {
    "description": "性別過濾器 (MeSH-based)",
    "options": {
        "male": {"mesh": '"Male"[MeSH]'},
        "female": {"mesh": '"Female"[MeSH]'},
    },
    "usage_example": 'search_literature(query="breast cancer", sex="female")',
}

SPECIES_REFERENCE = {
    "description": "物種過濾器 (MeSH-based)",
    "options": {
        "humans": {"mesh": '"Humans"[MeSH]', "note": "Human studies only"},
        "animals": {"mesh": '"Animals"[MeSH]', "note": "Animal studies only"},
    },
    "usage_example": 'search_literature(query="gene therapy", species="humans")',
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
    "usage_example": 'search_literature(query="COVID-19", language="english")',
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
    "usage_example": 'unified_search(query="diabetes treatment", clinical_query="therapy")',
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
    "usage_example": 'search_literature(query="COVID-19", article_type="Systematic Review")',
}

# ============================================================================
# ICD to MeSH Mapping (Common codes)
# Based on NLM UMLS mappings
# ============================================================================

# ICD-10-CM to MeSH mapping (selected common codes)
# Full mapping would require UMLS access
ICD10_TO_MESH = {
    # Diabetes
    "E10": {"mesh": "Diabetes Mellitus, Type 1", "description": "Type 1 diabetes mellitus"},
    "E11": {"mesh": "Diabetes Mellitus, Type 2", "description": "Type 2 diabetes mellitus"},
    "E13": {"mesh": "Diabetes Mellitus", "description": "Other specified diabetes mellitus"},
    # Hypertension
    "I10": {"mesh": "Essential Hypertension", "description": "Essential (primary) hypertension"},
    "I11": {"mesh": "Hypertensive Heart Disease", "description": "Hypertensive heart disease"},
    "I12": {"mesh": "Hypertension, Renal", "description": "Hypertensive chronic kidney disease"},
    # Heart diseases
    "I20": {"mesh": "Angina Pectoris", "description": "Angina pectoris"},
    "I21": {"mesh": "Myocardial Infarction", "description": "Acute myocardial infarction"},
    "I25": {"mesh": "Coronary Artery Disease", "description": "Chronic ischemic heart disease"},
    "I50": {"mesh": "Heart Failure", "description": "Heart failure"},
    # Respiratory
    "J18": {"mesh": "Pneumonia", "description": "Pneumonia, unspecified organism"},
    "J44": {"mesh": "Pulmonary Disease, Chronic Obstructive", "description": "COPD"},
    "J45": {"mesh": "Asthma", "description": "Asthma"},
    # Cancer
    "C34": {"mesh": "Lung Neoplasms", "description": "Malignant neoplasm of bronchus and lung"},
    "C50": {"mesh": "Breast Neoplasms", "description": "Malignant neoplasm of breast"},
    "C61": {"mesh": "Prostatic Neoplasms", "description": "Malignant neoplasm of prostate"},
    "C18": {"mesh": "Colonic Neoplasms", "description": "Malignant neoplasm of colon"},
    # Neurological
    "G20": {"mesh": "Parkinson Disease", "description": "Parkinson's disease"},
    "G30": {"mesh": "Alzheimer Disease", "description": "Alzheimer's disease"},
    "G35": {"mesh": "Multiple Sclerosis", "description": "Multiple sclerosis"},
    "G40": {"mesh": "Epilepsy", "description": "Epilepsy"},
    # Mental disorders
    "F32": {"mesh": "Depressive Disorder, Major", "description": "Major depressive episode"},
    "F33": {"mesh": "Depressive Disorder, Major", "description": "Major depressive disorder, recurrent"},
    "F41": {"mesh": "Anxiety Disorders", "description": "Other anxiety disorders"},
    # Kidney
    "N18": {"mesh": "Renal Insufficiency, Chronic", "description": "Chronic kidney disease"},
    # Liver
    "K70": {"mesh": "Liver Diseases, Alcoholic", "description": "Alcoholic liver disease"},
    "K74": {"mesh": "Liver Cirrhosis", "description": "Fibrosis and cirrhosis of liver"},
    # Infectious
    "B20": {"mesh": "HIV Infections", "description": "HIV disease"},
    "A41": {"mesh": "Sepsis", "description": "Sepsis"},
    # COVID-19
    "U07.1": {"mesh": "COVID-19", "description": "COVID-19, virus identified"},
    "U07.2": {"mesh": "COVID-19", "description": "COVID-19, virus not identified"},
}

# ICD-9-CM to MeSH mapping (legacy codes)
ICD9_TO_MESH = {
    # Diabetes
    "250": {"mesh": "Diabetes Mellitus", "description": "Diabetes mellitus"},
    "250.0": {"mesh": "Diabetes Mellitus, Type 2", "description": "DM without complication"},
    "250.01": {"mesh": "Diabetes Mellitus, Type 1", "description": "DM Type 1 without complication"},
    # Hypertension
    "401": {"mesh": "Essential Hypertension", "description": "Essential hypertension"},
    "402": {"mesh": "Hypertensive Heart Disease", "description": "Hypertensive heart disease"},
    # Heart
    "410": {"mesh": "Myocardial Infarction", "description": "Acute myocardial infarction"},
    "411": {"mesh": "Angina, Unstable", "description": "Unstable angina"},
    "414": {"mesh": "Coronary Artery Disease", "description": "Chronic ischemic heart disease"},
    "428": {"mesh": "Heart Failure", "description": "Heart failure"},
    # Respiratory
    "486": {"mesh": "Pneumonia", "description": "Pneumonia"},
    "493": {"mesh": "Asthma", "description": "Asthma"},
    "496": {"mesh": "Pulmonary Disease, Chronic Obstructive", "description": "COPD"},
    # Cancer
    "162": {"mesh": "Lung Neoplasms", "description": "Lung cancer"},
    "174": {"mesh": "Breast Neoplasms", "description": "Breast cancer female"},
    "185": {"mesh": "Prostatic Neoplasms", "description": "Prostate cancer"},
    "153": {"mesh": "Colonic Neoplasms", "description": "Colon cancer"},
    # Neurological
    "332": {"mesh": "Parkinson Disease", "description": "Parkinson's disease"},
    "331.0": {"mesh": "Alzheimer Disease", "description": "Alzheimer's disease"},
    "340": {"mesh": "Multiple Sclerosis", "description": "Multiple sclerosis"},
    "345": {"mesh": "Epilepsy", "description": "Epilepsy"},
    # Mental
    "296": {"mesh": "Depressive Disorder, Major", "description": "Major depression"},
    "300": {"mesh": "Anxiety Disorders", "description": "Anxiety disorders"},
    # Kidney
    "585": {"mesh": "Renal Insufficiency, Chronic", "description": "Chronic kidney disease"},
    # Infectious
    "042": {"mesh": "HIV Infections", "description": "HIV infection"},
    "038": {"mesh": "Sepsis", "description": "Septicemia"},
}


def detect_icd_version(code: str) -> Optional[str]:
    """Detect ICD version from code format."""
    code = code.strip().upper()
    
    # ICD-10 patterns: letter followed by digits (e.g., E11, J45, C50.9)
    if code and code[0].isalpha() and len(code) >= 2:
        return "ICD-10"
    
    # ICD-9 patterns: 3-5 digit codes (e.g., 250, 410.01)
    if code.replace(".", "").isdigit():
        return "ICD-9"
    
    return None


def lookup_icd_to_mesh(code: str) -> dict:
    """
    Convert ICD code to MeSH term.
    
    Supports both ICD-9-CM and ICD-10-CM codes.
    Returns MeSH term and search query suggestions.
    """
    code = code.strip().upper()
    version = detect_icd_version(code)
    
    if not version:
        return {
            "success": False,
            "error": f"Cannot detect ICD version for code: {code}",
            "hint": "ICD-10 codes start with a letter (e.g., E11), ICD-9 codes are numeric (e.g., 250)",
        }
    
    # Try exact match first, then prefix match
    mapping = ICD10_TO_MESH if version == "ICD-10" else ICD9_TO_MESH
    
    # Exact match
    if code in mapping:
        entry = mapping[code]
        return {
            "success": True,
            "input_code": code,
            "icd_version": version,
            "mesh_term": entry["mesh"],
            "description": entry["description"],
            "pubmed_query": f'"{entry["mesh"]}"[MeSH]',
            "search_suggestion": f'search_literature(query=\'"{entry["mesh"]}"[MeSH]\')',
        }
    
    # Prefix match (e.g., E11.9 -> E11)
    prefix = code.split(".")[0]
    if prefix in mapping:
        entry = mapping[prefix]
        return {
            "success": True,
            "input_code": code,
            "matched_prefix": prefix,
            "icd_version": version,
            "mesh_term": entry["mesh"],
            "description": entry["description"],
            "pubmed_query": f'"{entry["mesh"]}"[MeSH]',
            "search_suggestion": f'search_literature(query=\'"{entry["mesh"]}"[MeSH]\')',
            "note": f"Matched via prefix {prefix}",
        }
    
    return {
        "success": False,
        "input_code": code,
        "icd_version": version,
        "error": f"No MeSH mapping found for {code}",
        "hint": "Try using generate_search_queries() with the disease name instead",
        "available_codes": list(mapping.keys())[:20],
    }


def lookup_mesh_to_icd(mesh_term: str) -> dict:
    """
    Reverse lookup: MeSH term to ICD codes.
    
    Returns both ICD-9 and ICD-10 codes if available.
    """
    mesh_term_lower = mesh_term.lower().strip()
    
    results = {
        "success": False,
        "input_mesh": mesh_term,
        "icd10_codes": [],
        "icd9_codes": [],
    }
    
    # Search ICD-10
    for code, entry in ICD10_TO_MESH.items():
        if mesh_term_lower in entry["mesh"].lower():
            results["icd10_codes"].append({
                "code": code,
                "description": entry["description"],
            })
    
    # Search ICD-9
    for code, entry in ICD9_TO_MESH.items():
        if mesh_term_lower in entry["mesh"].lower():
            results["icd9_codes"].append({
                "code": code,
                "description": entry["description"],
            })
    
    if results["icd10_codes"] or results["icd9_codes"]:
        results["success"] = True
    else:
        results["error"] = f"No ICD codes found for MeSH term: {mesh_term}"
        results["hint"] = "Try a more specific or different MeSH term"
    
    return results


# ============================================================================
# Tool Reference
# ============================================================================

TOOL_CATEGORIES = {
    "search": {
        "description": "搜尋工具",
        "tools": [
            {"name": "unified_search", "purpose": "統一入口，自動選擇最佳來源"},
            {"name": "search_literature", "purpose": "直接 PubMed 搜尋"},
            {"name": "generate_search_queries", "purpose": "產生 MeSH 擴展搜尋策略"},
            {"name": "parse_pico", "purpose": "解析 PICO 臨床問題"},
        ],
    },
    "discovery": {
        "description": "探索工具 (從已知文章出發)",
        "tools": [
            {"name": "find_related_articles", "purpose": "找相似文章 (PubMed Similar Articles)"},
            {"name": "find_citing_articles", "purpose": "找引用這篇的文章 (Forward citation)"},
            {"name": "get_article_references", "purpose": "取得參考文獻 (Backward citation)"},
            {"name": "build_citation_tree", "purpose": "建立引用網路圖"},
        ],
    },
    "fulltext": {
        "description": "全文取得",
        "tools": [
            {"name": "get_fulltext", "purpose": "從 Europe PMC / CORE / Unpaywall 取得全文"},
            {"name": "get_text_mined_terms", "purpose": "取得文本挖掘標註 (基因/疾病/藥物)"},
        ],
    },
    "ncbi_extended": {
        "description": "NCBI 延伸資料庫",
        "tools": [
            {"name": "search_gene", "purpose": "搜尋 NCBI Gene"},
            {"name": "get_gene_details", "purpose": "取得基因詳情"},
            {"name": "get_gene_literature", "purpose": "取得基因相關文獻"},
            {"name": "search_compound", "purpose": "搜尋 PubChem 化合物"},
            {"name": "get_compound_details", "purpose": "取得化合物詳情"},
            {"name": "get_compound_literature", "purpose": "取得化合物相關文獻"},
            {"name": "search_clinvar", "purpose": "搜尋 ClinVar 臨床變異"},
        ],
    },
    "export": {
        "description": "匯出工具",
        "tools": [
            {"name": "prepare_export", "purpose": "匯出引用格式 (RIS/BibTeX/CSV)"},
            {"name": "get_citation_metrics", "purpose": "取得引用指標 (iCite RCR)"},
        ],
    },
    "session": {
        "description": "Session 管理",
        "tools": [
            {"name": "get_session_pmids", "purpose": "取得暫存的 PMID 列表"},
            {"name": "list_search_history", "purpose": "列出搜尋歷史"},
            {"name": "get_session_summary", "purpose": "Session 狀態摘要"},
        ],
    },
    "conversion": {
        "description": "代碼轉換",
        "tools": [
            {"name": "convert_icd_to_mesh", "purpose": "ICD-9/10 轉 MeSH 詞彙"},
            {"name": "convert_mesh_to_icd", "purpose": "MeSH 轉 ICD 代碼"},
        ],
    },
}


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
                "supported_icd10_codes": list(ICD10_TO_MESH.keys()),
                "supported_icd9_codes": list(ICD9_TO_MESH.keys()),
                "usage": {
                    "icd_to_mesh": 'convert_icd_to_mesh(code="E11")',
                    "mesh_to_icd": 'convert_mesh_to_icd(mesh_term="Diabetes Mellitus")',
                },
            },
            indent=2,
            ensure_ascii=False,
        )

    logger.info("Registered MCP resources for filters and tools")


def register_icd_tools(mcp: FastMCP):
    """Register ICD conversion tools."""

    @mcp.tool()
    def convert_icd_to_mesh(code: str) -> str:
        """
        Convert ICD-9 or ICD-10 code to MeSH term for PubMed search.

        Automatically detects ICD version and returns:
        - MeSH term mapping
        - Ready-to-use PubMed query
        - Search suggestion

        Args:
            code: ICD-9 or ICD-10 code (e.g., "E11", "250", "I21.9")

        Returns:
            JSON with MeSH mapping and search query

        Example:
            convert_icd_to_mesh("E11")     → Diabetes Mellitus, Type 2
            convert_icd_to_mesh("I21")     → Myocardial Infarction
            convert_icd_to_mesh("250")     → Diabetes Mellitus (ICD-9)
            convert_icd_to_mesh("U07.1")   → COVID-19
        """
        result = lookup_icd_to_mesh(code)
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    def convert_mesh_to_icd(mesh_term: str) -> str:
        """
        Convert MeSH term to ICD-9 and ICD-10 codes.

        Useful for clinical documentation or billing code lookup.

        Args:
            mesh_term: MeSH term (e.g., "Diabetes Mellitus", "Heart Failure")

        Returns:
            JSON with matching ICD-9 and ICD-10 codes

        Example:
            convert_mesh_to_icd("Diabetes Mellitus")
            convert_mesh_to_icd("Myocardial Infarction")
        """
        result = lookup_mesh_to_icd(mesh_term)
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    def search_by_icd(
        code: str,
        limit: int = 10,
        min_year: Optional[int] = None,
        article_type: Optional[str] = None,
    ) -> str:
        """
        Search PubMed using ICD code (auto-converts to MeSH).

        Convenience tool that:
        1. Converts ICD code to MeSH term
        2. Executes PubMed search with the MeSH query

        Args:
            code: ICD-9 or ICD-10 code
            limit: Maximum results (default 10)
            min_year: Minimum publication year
            article_type: Article type filter (e.g., "Review", "Clinical Trial")

        Returns:
            Search results or conversion error

        Example:
            search_by_icd("E11", limit=5)  # Type 2 diabetes
            search_by_icd("I21", limit=10, article_type="Clinical Trial")  # MI
        """
        # First convert
        mapping = lookup_icd_to_mesh(code)
        
        if not mapping.get("success"):
            return json.dumps(mapping, indent=2, ensure_ascii=False)
        
        # Import here to avoid circular dependency
        from ..entrez import LiteratureSearcher
        
        searcher = LiteratureSearcher()
        mesh_query = mapping["pubmed_query"]
        
        results = searcher.search(
            query=mesh_query,
            limit=limit,
            min_year=min_year,
            article_type=article_type,
        )
        
        return json.dumps(
            {
                "icd_code": code,
                "mesh_term": mapping["mesh_term"],
                "query_used": mesh_query,
                "total_results": len(results),
                "articles": results,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )

    logger.info("Registered ICD conversion tools")
