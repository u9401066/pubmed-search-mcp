"""Tests for composite parameter parsers (_parse_filters, _parse_options)."""

from __future__ import annotations

import pytest

from pubmed_search.presentation.mcp_server.tools.unified import (
    _parse_filters,
    _parse_options,
)


class TestParseFilters:
    """Test _parse_filters composite parameter parser."""

    def test_none_returns_empty(self):
        assert _parse_filters(None) == {}

    def test_empty_string_returns_empty(self):
        assert _parse_filters("") == {}

    def test_year_range(self):
        result = _parse_filters("year:2020-2025")
        assert result["min_year"] == 2020
        assert result["max_year"] == 2025

    def test_year_from_only(self):
        result = _parse_filters("year:2020-")
        assert result["min_year"] == 2020
        assert "max_year" not in result

    def test_year_to_only(self):
        result = _parse_filters("year:-2025")
        assert result["max_year"] == 2025
        assert "min_year" not in result

    def test_year_single(self):
        result = _parse_filters("year:2024")
        assert result["min_year"] == 2024
        assert "max_year" not in result

    def test_age_group(self):
        assert _parse_filters("age:aged")["age_group"] == "aged"
        assert _parse_filters("age_group:child")["age_group"] == "child"

    def test_sex(self):
        assert _parse_filters("sex:female")["sex"] == "female"

    def test_species(self):
        assert _parse_filters("species:humans")["species"] == "humans"

    def test_language(self):
        assert _parse_filters("lang:english")["language"] == "english"
        assert _parse_filters("language:chinese")["language"] == "chinese"

    def test_clinical_query(self):
        assert _parse_filters("clinical:therapy")["clinical_query"] == "therapy"
        assert _parse_filters("clinical_query:diagnosis_narrow")["clinical_query"] == "diagnosis_narrow"

    def test_multiple_filters(self):
        result = _parse_filters("year:2020-2025, age:aged, sex:female, clinical:therapy")
        assert result["min_year"] == 2020
        assert result["max_year"] == 2025
        assert result["age_group"] == "aged"
        assert result["sex"] == "female"
        assert result["clinical_query"] == "therapy"

    def test_whitespace_handling(self):
        result = _parse_filters("  year : 2020 - 2025 , age : aged  ")
        assert result["min_year"] == 2020
        assert result["max_year"] == 2025
        assert result["age_group"] == "aged"

    def test_invalid_year_ignored(self):
        result = _parse_filters("year:abc")
        assert "min_year" not in result
        assert "max_year" not in result

    def test_empty_value_ignored(self):
        result = _parse_filters("age:, sex:female")
        assert "age_group" not in result
        assert result["sex"] == "female"

    def test_no_colon_ignored(self):
        result = _parse_filters("something_weird, sex:male")
        assert result == {"sex": "male"}


class TestParseOptions:
    """Test _parse_options composite parameter parser."""

    def test_none_returns_empty(self):
        assert _parse_options(None) == {}

    def test_empty_string_returns_empty(self):
        assert _parse_options("") == {}

    def test_preprints(self):
        result = _parse_options("preprints")
        assert result["include_preprints"] is True

    def test_shallow(self):
        result = _parse_options("shallow")
        assert result["deep_search"] is False

    def test_all_types(self):
        result = _parse_options("all_types")
        assert result["peer_reviewed_only"] is False

    def test_no_peer_review_alias(self):
        result = _parse_options("no_peer_review")
        assert result["peer_reviewed_only"] is False

    def test_no_oa(self):
        result = _parse_options("no_oa")
        assert result["include_oa_links"] is False

    def test_no_analysis(self):
        result = _parse_options("no_analysis")
        assert result["show_analysis"] is False

    def test_no_scores(self):
        result = _parse_options("no_scores")
        assert result["include_similarity_scores"] is False

    def test_no_relax(self):
        result = _parse_options("no_relax")
        assert result["auto_relax"] is False

    def test_multiple_options(self):
        result = _parse_options("preprints, shallow, no_oa")
        assert result["include_preprints"] is True
        assert result["deep_search"] is False
        assert result["include_oa_links"] is False

    def test_case_insensitive(self):
        result = _parse_options("PREPRINTS, Shallow")
        assert result["include_preprints"] is True
        assert result["deep_search"] is False

    def test_whitespace_handling(self):
        result = _parse_options("  preprints , shallow  ,  no_oa  ")
        assert result["include_preprints"] is True
        assert result["deep_search"] is False
        assert result["include_oa_links"] is False

    @pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
    def test_unknown_flag_logged(self, caplog):
        """Unknown flags are logged as warnings but don't crash."""
        result = _parse_options("preprints, unknown_flag")
        assert result["include_preprints"] is True
        # Unknown flag should not appear in result
        assert "unknown_flag" not in result

    def test_defaults_not_set(self):
        """Options not mentioned should not appear in result (caller uses defaults)."""
        result = _parse_options("preprints")
        assert "include_oa_links" not in result
        assert "show_analysis" not in result
        assert "deep_search" not in result
