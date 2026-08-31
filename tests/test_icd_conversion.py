#!/usr/bin/env python3
"""Test ICD to MeSH conversion."""

from __future__ import annotations

from pubmed_search.application.search.icd import (
    detect_icd_version,
    get_icd_reference,
    lookup_icd_to_mesh,
    lookup_mesh_to_icd,
)


class TestICDConversion:
    """Test ICD to MeSH conversion functionality."""

    async def test_icd10_to_mesh_e11(self):
        """Test ICD-10 E11 (Type 2 Diabetes)."""
        result = lookup_icd_to_mesh("E11")
        assert result["success"] is True
        assert "Diabetes" in result.get("mesh_term", "")

    async def test_icd10_to_mesh_i21(self):
        """Test ICD-10 I21 (Myocardial Infarction)."""
        result = lookup_icd_to_mesh("I21")
        assert result["success"] is True
        assert "mesh_term" in result

    async def test_icd10_with_decimal(self):
        """Test ICD-10 with decimal notation."""
        result = lookup_icd_to_mesh("E11.9")
        assert result["success"] is True
        assert "mesh_term" in result

    async def test_icd9_format(self):
        """Test ICD-9 format (3 digits)."""
        result = lookup_icd_to_mesh("250")
        assert result["success"] is True
        assert result["icd_version"] == "ICD-9-CM"

    async def test_covid_icd(self):
        """Test COVID-19 ICD code."""
        result = lookup_icd_to_mesh("U07.1")
        assert result["success"] is True
        assert "COVID" in result.get("mesh_term", "")

    async def test_malformed_alphanumeric_is_not_misclassified_as_icd10(self):
        assert detect_icd_version("NOT-A-CODE") is None
        assert detect_icd_version("A1") is None
        assert detect_icd_version("E11 trailing") is None

    async def test_icd9_external_cause_and_ambiguous_v_code_detection(self):
        assert detect_icd_version("E880.9") == "ICD-9-CM"
        assert detect_icd_version("V58.69") is None
        result = lookup_icd_to_mesh("V58.69")
        assert result["success"] is False
        assert "ambiguous" in result["error"]

    async def test_result_discloses_curated_mapping_scope(self):
        result = lookup_icd_to_mesh("E11")
        assert result["mapping_scope"] == "curated_subset"
        assert result["is_comprehensive"] is False

    async def test_reference_describes_application_mapping_data(self):
        reference = get_icd_reference()
        assert reference["mapping_scope"] == "curated_subset"
        assert reference["is_comprehensive"] is False
        assert "E11" in reference["supported_icd10_codes"]
        assert "usage" not in reference


class TestMeSHToICD:
    """Test reverse MeSH to ICD conversion."""

    async def test_mesh_to_icd_diabetes(self):
        """Test MeSH to ICD for Diabetes."""
        result = lookup_mesh_to_icd("Diabetes Mellitus")
        assert result["success"] is True
        assert len(result.get("icd10_codes", [])) >= 1

    async def test_mesh_to_icd_unknown(self):
        """Test MeSH to ICD for unknown term."""
        result = lookup_mesh_to_icd("NonexistentTerm12345")
        # Should return error or empty list
        assert isinstance(result, dict)

    async def test_empty_mesh_term_does_not_match_every_mapping(self):
        result = lookup_mesh_to_icd("   ")
        assert result["success"] is False
        assert result.get("icd10_codes", []) == []
