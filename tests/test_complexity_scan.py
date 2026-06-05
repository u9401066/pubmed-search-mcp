from __future__ import annotations

import math

from scripts.perf.complexity_scan import (
    ComplexityModel,
    fit_complexity,
    iter_target_specs,
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
