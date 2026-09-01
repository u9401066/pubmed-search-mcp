"""Tests for the canonical diagnostic-preserving composite parsers."""

from __future__ import annotations

import pytest

from pubmed_search.application.unified.helpers import (
    _parse_filters_detailed,
    _parse_options_detailed,
)


def _filters(value: str | None) -> dict:
    parsed, _diagnostics = _parse_filters_detailed(value)
    return parsed


def _options(value: str | None) -> dict[str, bool]:
    parsed, _diagnostics = _parse_options_detailed(value)
    return parsed


class TestParseFilters:
    """Test the diagnostic-preserving filter parser."""

    def test_none_returns_empty(self):
        assert _filters(None) == {}

    def test_empty_string_is_rejected(self):
        result, diagnostics = _parse_filters_detailed("")

        assert result == {}
        assert diagnostics == ("filter list contains an empty token",)

    def test_year_range(self):
        result = _filters("year:2020-2025")
        assert result["min_year"] == 2020
        assert result["max_year"] == 2025

    def test_year_from_only(self):
        result = _filters("year:2020-")
        assert result["min_year"] == 2020
        assert "max_year" not in result

    def test_year_to_only(self):
        result = _filters("year:-2025")
        assert result["max_year"] == 2025
        assert "min_year" not in result

    def test_year_single(self):
        result = _filters("year:2024")
        assert result["min_year"] == 2024
        assert "max_year" not in result

    def test_age_group(self):
        assert _filters("age_group:child")["age_group"] == "child"

    def test_sex(self):
        assert _filters("sex:female")["sex"] == "female"

    def test_species(self):
        assert _filters("species:humans")["species"] == "humans"

    def test_language(self):
        assert _filters("language:chinese")["language"] == "chinese"

    def test_clinical_query(self):
        assert _filters("clinical_query:diagnosis_narrow")["clinical_query"] == "diagnosis_narrow"

    def test_multiple_filters(self):
        result = _filters("year:2020-2025,age_group:aged,sex:female,clinical_query:therapy")
        assert result["min_year"] == 2020
        assert result["max_year"] == 2025
        assert result["age_group"] == "aged"
        assert result["sex"] == "female"
        assert result["clinical_query"] == "therapy"

    def test_whitespace_variants_are_rejected(self):
        result, diagnostics = _parse_filters_detailed(" year:2020-2025,age_group:aged ")

        assert result == {}
        assert len(diagnostics) == 2

    def test_separator_whitespace_is_rejected(self):
        result, diagnostics = _parse_filters_detailed("year:2020, age_group:adult")

        assert result == {"min_year": 2020}
        assert diagnostics == ("filter ' age_group:adult' contains surrounding whitespace",)

    def test_empty_interior_and_trailing_tokens_are_rejected(self):
        result, diagnostics = _parse_filters_detailed("year:2020,,sex:female,")

        assert result == {"min_year": 2020, "sex": "female"}
        assert diagnostics == (
            "filter list contains an empty token",
            "filter list contains an empty token",
        )

    def test_invalid_year_ignored(self):
        result = _filters("year:abc")
        assert "min_year" not in result
        assert "max_year" not in result

    def test_empty_value_ignored(self):
        result = _filters("age_group:,sex:female")
        assert "age_group" not in result
        assert result["sex"] == "female"

    def test_no_colon_ignored(self):
        result = _filters("something_weird,sex:male")
        assert result == {"sex": "male"}

    def test_invalid_tokens_are_reported(self):
        result, diagnostics = _parse_filters_detailed("year:abc,age_group:,unknown:value")
        assert result == {}
        assert len(diagnostics) == 3

    @pytest.mark.parametrize("retired", ["age:aged", "lang:english", "clinical:therapy"])
    def test_retired_filter_aliases_are_rejected(self, retired: str):
        result, diagnostics = _parse_filters_detailed(retired)

        assert result == {}
        assert diagnostics == (f"unknown filter key '{retired.split(':', 1)[0]}'",)

    @pytest.mark.parametrize(
        "variant",
        ["Age_group:aged", "age_group:AGED", "age_group:middle-aged", "clinical_query:therapy-narrow"],
    )
    def test_case_and_hyphen_variants_are_rejected(self, variant: str):
        result, diagnostics = _parse_filters_detailed(variant)

        assert result == {}
        assert diagnostics

    def test_duplicate_filter_is_rejected(self):
        result, diagnostics = _parse_filters_detailed("sex:female,sex:male")

        assert result == {"sex": "female"}
        assert diagnostics == ("filter 'sex' is duplicated",)


class TestParseOptions:
    """Test the diagnostic-preserving option parser."""

    def test_none_returns_empty(self):
        assert _options(None) == {}

    def test_empty_string_is_rejected(self):
        result, diagnostics = _parse_options_detailed("")

        assert result == {}
        assert diagnostics == ("option list contains an empty token",)

    def test_preprints(self):
        result = _options("preprints")
        assert result["include_preprints"] is True

    def test_shallow(self):
        result = _options("shallow")
        assert result["deep_search"] is False

    def test_include_detected_preprints(self):
        result = _options("include_detected_preprints")
        assert result["include_detected_preprints"] is True

    def test_no_oa(self):
        result = _options("no_oa")
        assert result["include_oa_links"] is False

    def test_no_analysis(self):
        result = _options("no_analysis")
        assert result["show_analysis"] is False

    def test_no_scores(self):
        result = _options("no_scores")
        assert result["include_rank_scores"] is False

    def test_no_next(self):
        result = _options("no_next")
        assert result["include_next_tools"] is False

    def test_no_provenance(self):
        result = _options("no_provenance")
        assert result["include_section_provenance"] is False

    def test_compact_expands_to_safe_structured_defaults(self):
        result = _options("compact")
        assert result["compact_output"] is True
        assert result["show_analysis"] is False
        assert result["include_rank_scores"] is False
        assert result["include_next_tools"] is False
        assert result["include_section_provenance"] is False
        assert result["deep_search"] is False

    def test_no_relax(self):
        result = _options("no_relax")
        assert result["auto_relax"] is False

    def test_multiple_options(self):
        result = _options("preprints,shallow,no_oa")
        assert result["include_preprints"] is True
        assert result["deep_search"] is False
        assert result["include_oa_links"] is False

    def test_case_variants_are_rejected(self):
        result, diagnostics = _parse_options_detailed("PREPRINTS,Shallow")

        assert result == {}
        assert diagnostics == ("unknown option 'PREPRINTS'", "unknown option 'Shallow'")

    def test_whitespace_variants_are_rejected(self):
        result, diagnostics = _parse_options_detailed(" preprints,shallow ")

        assert result == {}
        assert len(diagnostics) == 2

    def test_separator_whitespace_is_rejected(self):
        result, diagnostics = _parse_options_detailed("preprints, shallow")

        assert result == {"include_preprints": True}
        assert diagnostics == ("option ' shallow' contains surrounding whitespace",)

    def test_empty_interior_and_trailing_tokens_are_rejected(self):
        result, diagnostics = _parse_options_detailed("preprints,,shallow,")

        assert result == {"include_preprints": True, "deep_search": False}
        assert diagnostics == (
            "option list contains an empty token",
            "option list contains an empty token",
        )

    def test_unknown_flag_is_reported(self):
        result, diagnostics = _parse_options_detailed("preprints,unknown_flag")
        assert result["include_preprints"] is True
        assert "unknown_flag" not in result
        assert diagnostics == ("unknown option 'unknown_flag'",)

    @pytest.mark.parametrize("retired", ["all_types", "no_peer_review", "context_graph"])
    def test_retired_options_are_rejected(self, retired):
        result, diagnostics = _parse_options_detailed(retired)

        assert result == {}
        assert diagnostics == (f"unknown option '{retired}'",)

    @pytest.mark.parametrize("retired", ["trials", "counts-first", "native-semantic", "minimal"])
    def test_retired_option_aliases_are_rejected(self, retired: str):
        result, diagnostics = _parse_options_detailed(retired)

        assert result == {}
        assert diagnostics == (f"unknown option '{retired}'",)

    def test_canonical_strict_options_are_accepted(self):
        result = _options("clinical_trials,counts_first,native_semantic,compact")

        assert result["include_clinical_trials"] is True
        assert result["counts_first"] is True
        assert result["native_semantic"] is True
        assert result["compact_output"] is True

    def test_duplicate_option_is_rejected(self):
        result, diagnostics = _parse_options_detailed("preprints,preprints")

        assert result == {"include_preprints": True}
        assert diagnostics == ("option 'preprints' is duplicated",)

    def test_defaults_not_set(self):
        """Options not mentioned should not appear in result (caller uses defaults)."""
        result = _options("preprints")
        assert "include_oa_links" not in result
        assert "show_analysis" not in result
        assert "deep_search" not in result
