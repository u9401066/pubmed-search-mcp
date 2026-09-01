"""Application-owned curated ICD-9-CM/ICD-10-CM ↔ MeSH crosswalk.

The mapping is intentionally small and is not a substitute for UMLS or a
licensed terminology service. Presentation layers may format these results,
but code validation, matching, and reference data live here.
"""

from __future__ import annotations

from typing import Any

from pubmed_search.domain.value_objects import IcdCodeValidationError, normalize_icd_code

# ============================================================================
# ICD to MeSH Mapping (Common codes)
# This is a small, manually curated convenience crosswalk. It is not a full
# UMLS, ICD, or MeSH mapping dataset and must never be represented as one.
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
}

# ICD-9-CM to MeSH mapping (historical coding standard)
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


def detect_icd_version(code: str) -> str | None:
    """Detect a complete ICD code without accepting arbitrary alphanumerics."""

    try:
        return normalize_icd_code(code).version
    except IcdCodeValidationError:
        return None


def lookup_icd_to_mesh(code: str) -> dict:
    """
    Convert ICD code to MeSH term.

    Supports both ICD-9-CM and ICD-10-CM codes.
    Returns MeSH term and search query suggestions.
    """
    try:
        parsed_code = normalize_icd_code(code)
    except IcdCodeValidationError as exc:
        return {
            "success": False,
            "error": str(exc),
            "hint": "Provide one complete code such as E11, I21.9, or 250.01",
            "mapping_scope": "curated_subset",
            "is_comprehensive": False,
        }
    code = parsed_code.value
    version = parsed_code.version

    # Try exact match first, then prefix match
    mapping = ICD10_TO_MESH if version == "ICD-10-CM" else ICD9_TO_MESH

    # Exact match
    if code in mapping:
        entry = mapping[code]
        return {
            "success": True,
            "mapping_scope": "curated_subset",
            "is_comprehensive": False,
            "match_type": "exact",
            "input_code": code,
            "icd_version": version,
            "mesh_term": entry["mesh"],
            "description": entry["description"],
            "pubmed_query": f'"{entry["mesh"]}"[MeSH]',
            "search_suggestion": f"unified_search(query='\"{entry['mesh']}\"[MeSH Terms]')",
        }

    # Prefix match (e.g., E11.9 -> E11)
    prefix = code.split(".")[0]
    if prefix in mapping:
        entry = mapping[prefix]
        return {
            "success": True,
            "mapping_scope": "curated_subset",
            "is_comprehensive": False,
            "match_type": "category_prefix",
            "input_code": code,
            "matched_prefix": prefix,
            "icd_version": version,
            "mesh_term": entry["mesh"],
            "description": entry["description"],
            "pubmed_query": f'"{entry["mesh"]}"[MeSH]',
            "search_suggestion": f"unified_search(query='\"{entry['mesh']}\"[MeSH Terms]')",
            "note": f"Matched via prefix {prefix}",
        }

    return {
        "success": False,
        "mapping_scope": "curated_subset",
        "is_comprehensive": False,
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
    if not isinstance(mesh_term, str):
        return {
            "success": False,
            "error": "MeSH term must be a string",
            "mapping_scope": "curated_subset",
            "is_comprehensive": False,
        }
    mesh_term = mesh_term.strip()
    if not mesh_term:
        return {
            "success": False,
            "error": "MeSH term is empty",
            "mapping_scope": "curated_subset",
            "is_comprehensive": False,
        }
    if len(mesh_term) > 500:
        return {
            "success": False,
            "error": "MeSH term exceeds 500 characters",
            "mapping_scope": "curated_subset",
            "is_comprehensive": False,
        }
    mesh_term_lower = mesh_term.casefold()

    results: dict[str, Any] = {
        "success": False,
        "mapping_scope": "curated_subset",
        "is_comprehensive": False,
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
        "description": "Small curated ICD-to-MeSH convenience crosswalk",
        "mapping_scope": "curated_subset",
        "is_comprehensive": False,
        "supported_icd10_codes": list(ICD10_TO_MESH.keys()),
        "supported_icd9_codes": list(ICD9_TO_MESH.keys()),
    }


__all__ = [
    "ICD9_TO_MESH",
    "ICD10_TO_MESH",
    "detect_icd_version",
    "get_icd_reference",
    "lookup_icd_to_mesh",
    "lookup_mesh_to_icd",
]
