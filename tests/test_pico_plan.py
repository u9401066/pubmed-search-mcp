"""Focused tests for the application-layer PICO plan contract."""

from __future__ import annotations

import pytest

from pubmed_search.application.search.pico_plan import (
    PicoPlanValidationError,
    build_pico_search_plan,
)


def test_pico_plan_rejects_unknown_source_without_fallback() -> None:
    with pytest.raises(PicoPlanValidationError, match="Unsupported PICO sources"):
        build_pico_search_plan(
            p="adults",
            i="intervention",
            sources=["pubmed", "typo_source"],  # type: ignore[list-item]
        )


@pytest.mark.parametrize("limit", [0, 101, True, "20"])
def test_pico_plan_rejects_invalid_limits(limit: object) -> None:
    with pytest.raises(PicoPlanValidationError, match="limit must be"):
        build_pico_search_plan(p="adults", i="intervention", limit=limit)  # type: ignore[arg-type]


def test_pico_plan_rejects_overlong_query_fragment() -> None:
    with pytest.raises(PicoPlanValidationError, match="P_query exceeds"):
        build_pico_search_plan(p="adults", i="intervention", p_query="x" * 5_001)
