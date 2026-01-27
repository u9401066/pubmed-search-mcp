"""
ICD Conversion Tools - ICD-9/ICD-10 與 MeSH 轉換

Tools:
- convert_icd_to_mesh: ICD 代碼轉 MeSH 詞彙
- convert_mesh_to_icd: MeSH 詞彙轉 ICD 代碼
- search_by_icd: 使用 ICD 代碼搜尋 PubMed
"""

import json
import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


# ============================================================================
# ICD to MeSH Mapping (Common codes)
# Based on NLM UMLS mappings
# ============================================================================

# ICD-10-CM to MeSH mapping (selected common codes)
ICD10_TO_MESH = {
    # Diabetes
    "E10": {
        "mesh": "Diabetes Mellitus, Type 1",
        "description": "Type 1 diabetes mellitus",
    },
    "E11": {
        "mesh": "Diabetes Mellitus, Type 2",
        "description": "Type 2 diabetes mellitus",
    },
    "E13": {
        "mesh": "Diabetes Mellitus",
        "description": "Other specified diabetes mellitus",
    },
    # Hypertension
    "I10": {
        "mesh": "Essential Hypertension",
        "description": "Essential (primary) hypertension",
    },
    "I11": {
        "mesh": "Hypertensive Heart Disease",
        "description": "Hypertensive heart disease",
    },
    "I12": {
        "mesh": "Hypertension, Renal",
        "description": "Hypertensive chronic kidney disease",
    },
    # Heart diseases
    "I20": {"mesh": "Angina Pectoris", "description": "Angina pectoris"},
    "I21": {
        "mesh": "Myocardial Infarction",
        "description": "Acute myocardial infarction",
    },
    "I25": {
        "mesh": "Coronary Artery Disease",
        "description": "Chronic ischemic heart disease",
    },
    "I50": {"mesh": "Heart Failure", "description": "Heart failure"},
    # Respiratory
    "J18": {"mesh": "Pneumonia", "description": "Pneumonia, unspecified organism"},
    "J44": {"mesh": "Pulmonary Disease, Chronic Obstructive", "description": "COPD"},
    "J45": {"mesh": "Asthma", "description": "Asthma"},
    # Cancer
    "C34": {
        "mesh": "Lung Neoplasms",
        "description": "Malignant neoplasm of bronchus and lung",
    },
    "C50": {"mesh": "Breast Neoplasms", "description": "Malignant neoplasm of breast"},
    "C61": {
        "mesh": "Prostatic Neoplasms",
        "description": "Malignant neoplasm of prostate",
    },
    "C18": {"mesh": "Colonic Neoplasms", "description": "Malignant neoplasm of colon"},
    # Neurological
    "G20": {"mesh": "Parkinson Disease", "description": "Parkinson's disease"},
    "G30": {"mesh": "Alzheimer Disease", "description": "Alzheimer's disease"},
    "G35": {"mesh": "Multiple Sclerosis", "description": "Multiple sclerosis"},
    "G40": {"mesh": "Epilepsy", "description": "Epilepsy"},
    # Mental disorders
    "F32": {
        "mesh": "Depressive Disorder, Major",
        "description": "Major depressive episode",
    },
    "F33": {
        "mesh": "Depressive Disorder, Major",
        "description": "Major depressive disorder, recurrent",
    },
    "F41": {"mesh": "Anxiety Disorders", "description": "Other anxiety disorders"},
    # Kidney
    "N18": {
        "mesh": "Renal Insufficiency, Chronic",
        "description": "Chronic kidney disease",
    },
    # Liver
    "K70": {
        "mesh": "Liver Diseases, Alcoholic",
        "description": "Alcoholic liver disease",
    },
    "K74": {
        "mesh": "Liver Cirrhosis",
        "description": "Fibrosis and cirrhosis of liver",
    },
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
    "250.0": {
        "mesh": "Diabetes Mellitus, Type 2",
        "description": "DM without complication",
    },
    "250.01": {
        "mesh": "Diabetes Mellitus, Type 1",
        "description": "DM Type 1 without complication",
    },
    # Hypertension
    "401": {"mesh": "Essential Hypertension", "description": "Essential hypertension"},
    "402": {
        "mesh": "Hypertensive Heart Disease",
        "description": "Hypertensive heart disease",
    },
    # Heart
    "410": {
        "mesh": "Myocardial Infarction",
        "description": "Acute myocardial infarction",
    },
    "411": {"mesh": "Angina, Unstable", "description": "Unstable angina"},
    "414": {
        "mesh": "Coronary Artery Disease",
        "description": "Chronic ischemic heart disease",
    },
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
    "585": {
        "mesh": "Renal Insufficiency, Chronic",
        "description": "Chronic kidney disease",
    },
    # Infectious
    "042": {"mesh": "HIV Infections", "description": "HIV infection"},
    "038": {"mesh": "Sepsis", "description": "Septicemia"},
}


# ============================================================================
# ICD Helper Functions
# ============================================================================


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
            "search_suggestion": f"search_literature(query='\"{entry['mesh']}\"[MeSH]')",
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
            "search_suggestion": f"search_literature(query='\"{entry['mesh']}\"[MeSH]')",
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
            results["icd10_codes"].append(
                {
                    "code": code,
                    "description": entry["description"],
                }
            )

    # Search ICD-9
    for code, entry in ICD9_TO_MESH.items():
        if mesh_term_lower in entry["mesh"].lower():
            results["icd9_codes"].append(
                {
                    "code": code,
                    "description": entry["description"],
                }
            )

    if results["icd10_codes"] or results["icd9_codes"]:
        results["success"] = True
    else:
        results["error"] = f"No ICD codes found for MeSH term: {mesh_term}"
        results["hint"] = "Try a more specific or different MeSH term"

    return results


def get_icd_reference() -> dict:
    """Get ICD mapping reference data."""
    return {
        "description": "ICD to MeSH bidirectional mapping",
        "supported_icd10_codes": list(ICD10_TO_MESH.keys()),
        "supported_icd9_codes": list(ICD9_TO_MESH.keys()),
        "usage": {
            "icd_to_mesh": 'convert_icd_to_mesh(code="E11")',
            "mesh_to_icd": 'convert_mesh_to_icd(mesh_term="Diabetes Mellitus")',
        },
    }


# ============================================================================
# Tool Registration
# ============================================================================


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
        from pubmed_search.infrastructure.ncbi import LiteratureSearcher

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

    logger.info("Registered ICD conversion tools (3 tools)")


__all__ = [
    "ICD10_TO_MESH",
    "ICD9_TO_MESH",
    "detect_icd_version",
    "lookup_icd_to_mesh",
    "lookup_mesh_to_icd",
    "get_icd_reference",
    "register_icd_tools",
]
