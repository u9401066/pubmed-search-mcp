from __future__ import annotations

import math

import pytest
from scripts.perf.complexity_scan import (
    ComplexityModel,
    fit_complexity,
    iter_target_specs,
    run_scan,
    summarize_static_hotspots,
)


def test_fit_complexity_identifies_linear_growth() -> None:
    samples = [(10, 0.0002), (20, 0.0004), (40, 0.0008), (80, 0.0016)]

    result = fit_complexity(samples)

    assert result.best.name in {"linear", "linearithmic"}
    assert math.isfinite(result.best.r_squared)
    assert result.best.r_squared > 0.95


def test_fit_complexity_reports_multiple_models() -> None:
    samples = [(10, 0.0001), (20, 0.0004), (40, 0.0016), (80, 0.0064)]

    result = fit_complexity(samples)

    model_names = {model.name for model in result.models}
    assert {"constant", "linear", "quadratic", "linearithmic"}.issubset(model_names)
    assert isinstance(result.best, ComplexityModel)


def test_iter_target_specs_has_core_repo_paths() -> None:
    target_names = {target.name for target in iter_target_specs()}

    assert "aggregate_deduplicate" in target_names
    assert "rank_articles" in target_names
    assert "format_unified_results" in target_names
    assert "pipeline_filter" in target_names
    assert "export_ris" in target_names
    assert "session_cache_lookup" in target_names


def test_static_hotspot_summary_returns_repo_files() -> None:
    hotspots = summarize_static_hotspots(limit=5)

    assert hotspots
    assert all(item.path.startswith("src/pubmed_search/") for item in hotspots)
    assert hotspots[0].lines >= hotspots[-1].lines


@pytest.mark.parametrize(
    "samples",
    [
        [(1, 0.1), (2, -0.1), (3, 0.3)],
        [(1, 0.1), (2, float("nan")), (3, 0.3)],
        [(1, 0.1), (2, float("inf")), (3, 0.3)],
        [(0, 0.1), (2, 0.2), (3, 0.3)],
        [(1, 0.1), (1, 0.2), (1, 0.3)],
    ],
)
def test_invalid_measurements_cannot_produce_a_successful_complexity_report(samples) -> None:
    with pytest.raises(ValueError):
        fit_complexity(samples)


def test_unknown_target_is_rejected_before_running_any_benchmark() -> None:
    with pytest.raises(ValueError, match="Unknown complexity targets"):
        run_scan({"rank_article_typo"})


def test_cache_misses_cannot_be_reported_as_fast_cache_hits(monkeypatch) -> None:
    from pubmed_search.application.session.manager import SessionManager

    monkeypatch.setattr(SessionManager, "get_from_cache", lambda self, pmids: ({}, pmids))
    target = next(target for target in iter_target_specs() if target.name == "session_cache_lookup")
    with pytest.raises(RuntimeError, match="requires all articles to be cache hits"):
        target.runner(3)
