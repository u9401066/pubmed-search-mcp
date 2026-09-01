"""Fail-closed input contracts for the unified-search facade."""

from __future__ import annotations

import pytest

from pubmed_search.application.unified.request import (
    MAX_UNIFIED_QUERY_CHARS,
    normalize_unified_search_request,
    validate_unified_search_input_envelope,
)
from pubmed_search.presentation.mcp_server.tools.unified_runner import _rejected_request_snapshot


@pytest.mark.parametrize(
    ("filters", "message"),
    [
        ("yaer:2020-2025", "unknown filter key 'yaer'"),
        ("year:recent", "not a valid year or range"),
        ("year:2025-2020", "range 2025-2020 is reversed"),
        ("age_group:elderly", "unsupported age filter 'elderly'"),
        ("sex:any", "unsupported sex filter 'any'"),
        ("species:both", "unsupported species filter 'both'"),
        ("clinical_query:screening", "unsupported clinical filter 'screening'"),
        ("year", "must use key:value syntax"),
    ],
)
def test_invalid_filters_never_silently_broaden_a_search(filters: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_unified_search_request(query="cancer", filters=filters)


def test_unknown_option_never_silently_changes_the_requested_protocol() -> None:
    with pytest.raises(ValueError, match="unknown option 'systemtic'"):
        normalize_unified_search_request(query="cancer", options="systemtic")


@pytest.mark.parametrize(("field", "message"), [("filters", "empty token"), ("options", "empty token")])
def test_empty_composite_expression_is_not_treated_as_absent(field: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_unified_search_request(query="cancer", **{field: ""})


@pytest.mark.parametrize("limit", [0, 101, "10", "many", True, 10.0, None])
def test_invalid_limits_fail_instead_of_being_defaulted_or_clamped(limit: object) -> None:
    with pytest.raises(ValueError, match="limit"):
        normalize_unified_search_request(query="cancer", limit=limit)  # type: ignore[arg-type]


def test_canonical_filter_and_option_spellings_are_preserved() -> None:
    request = normalize_unified_search_request(
        query="cancer",
        filters="year:2020-2025,age_group:middle_aged,language:english,clinical_query:therapy_narrow",
        options="counts_first,shallow",
    )

    assert request.min_year == 2020
    assert request.max_year == 2025
    assert request.age_group == "middle_aged"
    assert request.language == "english"
    assert request.clinical_query == "therapy_narrow"
    assert request.counts_first is True
    assert request.deep_search is False


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("filters", "age:aged", "unknown filter key 'age'"),
        ("filters", "lang:english", "unknown filter key 'lang'"),
        ("filters", "clinical:therapy", "unknown filter key 'clinical'"),
        ("filters", "age_group:Middle_Aged", "unsupported age filter"),
        ("filters", "age_group:middle-aged", "unsupported age filter"),
        ("options", "trials", "unknown option 'trials'"),
        ("options", "counts-first", "unknown option 'counts-first'"),
        ("options", "native-semantic", "unknown option 'native-semantic'"),
        ("options", "minimal", "unknown option 'minimal'"),
        ("options", "COMPACT", "unknown option 'COMPACT'"),
    ],
)
def test_retired_aliases_and_variants_are_rejected(field: str, value: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_unified_search_request(query="cancer", **{field: value})


def test_oversized_query_is_rejected_before_analysis() -> None:
    with pytest.raises(ValueError, match="query exceeds the maximum length"):
        normalize_unified_search_request(query="x" * (MAX_UNIFIED_QUERY_CHARS + 1))


def test_string_limit_is_rejected_by_the_pre_journal_envelope() -> None:
    with pytest.raises(ValueError, match="limit must be an integer"):
        validate_unified_search_input_envelope(query="precision medicine", limit="10", pipeline="steps: []")  # type: ignore[arg-type]


def test_pipeline_limit_uses_the_same_semantic_bounds_as_normal_mode() -> None:
    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        validate_unified_search_input_envelope(query="precision medicine", limit=101, pipeline="steps: []")


def test_rejected_non_scalar_input_is_not_copied_into_the_journal_snapshot() -> None:
    snapshot = _rejected_request_snapshot(query=["private"] * 10_000, limit=10)

    assert snapshot["query"] == "[rejected query: type=list]"
    assert snapshot["limit"] == 10


@pytest.mark.parametrize("field_name", ["query", "sources", "filters", "options", "pipeline", "stop_at"])
def test_every_replay_bearing_string_rejects_credential_material(field_name: str) -> None:
    values = {"query": "cancer", field_name: "api_key=TOPSECRET_SENTINEL"}

    with pytest.raises(ValueError, match=rf"{field_name} appears to contain credential material"):
        validate_unified_search_input_envelope(**values)
