#!/usr/bin/env python3
"""Test ICD to MeSH conversion."""

from pubmed_search.presentation.mcp_server.tools.icd import (
    lookup_icd_to_mesh,
    lookup_mesh_to_icd,
)


class TestICDConversion:
    """Test ICD to MeSH conversion functionality."""

    def test_icd10_to_mesh_e11(self):
        """Test ICD-10 E11 (Type 2 Diabetes)."""
        result = lookup_icd_to_mesh("E11")
        assert result["success"] is True
        assert "Diabetes" in result.get("mesh_term", "")

    def test_icd10_to_mesh_i21(self):
        """Test ICD-10 I21 (Myocardial Infarction)."""
        result = lookup_icd_to_mesh("I21")
        assert result["success"] is True
        assert "mesh_term" in result

    def test_icd10_with_decimal(self):
        """Test ICD-10 with decimal notation."""
        result = lookup_icd_to_mesh("E11.9")
        assert result["success"] is True
        assert "mesh_term" in result

    def test_icd9_format(self):
        """Test ICD-9 format (3 digits)."""
        result = lookup_icd_to_mesh("250")
        assert result["success"] is True
        assert result["icd_version"] == "ICD-9"

    def test_covid_icd(self):
        """Test COVID-19 ICD code."""
        result = lookup_icd_to_mesh("U07.1")
        assert result["success"] is True
        assert "COVID" in result.get("mesh_term", "")


class TestMeSHToICD:
    """Test reverse MeSH to ICD conversion."""

    def test_mesh_to_icd_diabetes(self):
        """Test MeSH to ICD for Diabetes."""
        result = lookup_mesh_to_icd("Diabetes Mellitus")
        assert result["success"] is True
        assert len(result.get("icd10_codes", [])) >= 1

    def test_mesh_to_icd_unknown(self):
        """Test MeSH to ICD for unknown term."""
        result = lookup_mesh_to_icd("NonexistentTerm12345")
        # Should return error or empty list
        assert isinstance(result, dict)
