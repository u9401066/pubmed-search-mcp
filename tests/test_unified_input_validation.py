"""Fail-closed input contracts for the unified-search facade."""

from __future__ import annotations

import pytest

from pubmed_search.presentation.mcp_server.tools.unified_request import normalize_unified_search_request


@pytest.mark.parametrize(
    ("filters", "message"),
    [
        ("yaer:2020-2025", "unknown filter key 'yaer'"),
        ("year:recent", "not a valid year or range"),
        ("year:2025-2020", "range 2025-2020 is reversed"),
        ("age:elderly", "unsupported age filter 'elderly'"),
        ("sex:any", "unsupported sex filter 'any'"),
        ("species:both", "unsupported species filter 'both'"),
        ("clinical:screening", "unsupported clinical filter 'screening'"),
        ("year", "must use key:value syntax"),
    ],
)
def test_invalid_filters_never_silently_broaden_a_search(filters: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_unified_search_request(query="cancer", filters=filters)


def test_unknown_option_never_silently_changes_the_requested_protocol() -> None:
    with pytest.raises(ValueError, match="unknown option 'systemtic'"):
        normalize_unified_search_request(query="cancer", options="systemtic")


@pytest.mark.parametrize("limit", [0, 101, "many", True])
def test_invalid_limits_fail_instead_of_being_defaulted_or_clamped(limit: object) -> None:
    with pytest.raises(ValueError, match="limit"):
        normalize_unified_search_request(query="cancer", limit=limit)  # type: ignore[arg-type]


def test_valid_filter_aliases_are_normalized_once() -> None:
    request = normalize_unified_search_request(
        query="cancer",
        filters="year:2020-2025, age:middle-aged, lang:English, clinical:therapy-narrow",
        options="counts-first, shallow",
    )

    assert request.min_year == 2020
    assert request.max_year == 2025
    assert request.age_group == "middle_aged"
    assert request.language == "english"
    assert request.clinical_query == "therapy_narrow"
    assert request.counts_first is True
    assert request.deep_search is False
