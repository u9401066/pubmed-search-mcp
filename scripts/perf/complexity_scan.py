"""Low-memory empirical complexity scanner for repository hot paths.

The scanner intentionally avoids new runtime dependencies.  It estimates
growth classes by timing synthetic inputs at increasing N and fitting simple
least-squares models, similar in spirit to packages such as ``big-o``.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "pubmed_search"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "scripts" / "_tmp" / "complexity"


@dataclass(frozen=True)
class ComplexityModel:
    name: str
    r_squared: float
    mse: float
    coefficient: float
    intercept: float
    expression: str


@dataclass(frozen=True)
class FitResult:
    best: ComplexityModel
    models: list[ComplexityModel]


@dataclass(frozen=True)
class TargetSpec:
    name: str
    description: str
    path: str
    sizes: tuple[int, ...]
    repeats: int
    runner: Callable[[int], float]


@dataclass(frozen=True)
class StaticHotspot:
    path: str
    lines: int
    complexity_findings: int


def _linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    if len(xs) != len(ys):
        raise ValueError("xs and ys must have the same length")
    if not xs:
        raise ValueError("at least one sample is required")

    x_mean = statistics.fmean(xs)
    y_mean = statistics.fmean(ys)
    variance = sum((x - x_mean) ** 2 for x in xs)
    slope = 0.0 if variance == 0 else sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / variance
    intercept = y_mean - slope * x_mean
    predictions = [intercept + slope * x for x in xs]
    mse = statistics.fmean((y - pred) ** 2 for y, pred in zip(ys, predictions))
    total = sum((y - y_mean) ** 2 for y in ys)
    r_squared = 1.0 if total == 0 else 1.0 - (sum((y - pred) ** 2 for y, pred in zip(ys, predictions)) / total)
    return slope, intercept, max(min(r_squared, 1.0), float("-inf")), mse


def _model_features(n: int) -> dict[str, tuple[float, str]]:
    safe_n = max(n, 2)
    return {
        "constant": (1.0, "1"),
        "logarithmic": (math.log(safe_n), "log(n)"),
        "linear": (float(n), "n"),
        "linearithmic": (float(n) * math.log(safe_n), "n log(n)"),
        "quadratic": (float(n) ** 2, "n^2"),
        "cubic": (float(n) ** 3, "n^3"),
    }


def fit_complexity(samples: list[tuple[int, float]]) -> FitResult:
    """Fit common growth models to ``(N, seconds)`` samples."""
    if len(samples) < 3:
        raise ValueError("at least three samples are required")

    sizes = [n for n, _ in samples]
    timings = [max(sec, 0.0) for _, sec in samples]
    models: list[ComplexityModel] = []

    for name in _model_features(sizes[0]):
        xs = [_model_features(n)[name][0] for n in sizes]
        expression = _model_features(sizes[0])[name][1]
        coefficient, intercept, r_squared, mse = _linear_regression(xs, timings)
        models.append(
            ComplexityModel(
                name=name,
                r_squared=r_squared,
                mse=mse,
                coefficient=coefficient,
                intercept=intercept,
                expression=expression,
            )
        )

    # Prefer simpler models when scores are nearly tied; empirical timings are noisy.
    complexity_order = {
        "constant": 0,
        "logarithmic": 1,
        "linear": 2,
        "linearithmic": 3,
        "quadratic": 4,
        "cubic": 5,
    }
    best_score = max(model.r_squared for model in models)
    candidates = [model for model in models if model.r_squared >= best_score - 0.015]
    best = min(candidates, key=lambda model: (complexity_order[model.name], model.mse))
    return FitResult(best=best, models=sorted(models, key=lambda model: model.r_squared, reverse=True))


def _time_callable(fn: Callable[[], Any], repeats: int) -> float:
    warmup = fn()
    if asyncio.iscoroutine(warmup):
        asyncio.run(warmup)

    timings: list[float] = []
    for _ in range(repeats):
        gc.collect()
        start = time.perf_counter()
        result = fn()
        if asyncio.iscoroutine(result):
            asyncio.run(result)
        timings.append(time.perf_counter() - start)
    return statistics.median(timings)


def _make_articles(n: int, *, duplicate_ratio: float = 0.2) -> list[Any]:
    from pubmed_search.domain.entities.article import ArticleType, UnifiedArticle

    duplicate_every = max(int(1 / duplicate_ratio), 2) if duplicate_ratio > 0 else n + 1
    articles = []
    for i in range(n):
        canonical = i if i % duplicate_every else max(i - 1, 0)
        articles.append(
            UnifiedArticle(
                title=f"Benchmark article {canonical} about remimazolam ICU sedation",
                primary_source=["pubmed", "openalex", "europe_pmc"][i % 3],
                pmid=str(10_000_000 + canonical) if i % 2 == 0 else None,
                doi=f"10.1000/bench.{canonical}" if i % 3 == 0 else None,
                abstract=("Background methods results conclusion. " * 8) + str(i),
                journal=f"Journal {i % 11}",
                year=2020 + (i % 6),
                article_type=ArticleType.REVIEW if i % 5 == 0 else ArticleType.JOURNAL_ARTICLE,
                keywords=["sedation", "icu", "trial", str(i % 13)],
                mesh_terms=["Hypnotics and Sedatives", "Intensive Care Units"],
            )
        )
    return articles


def _target_aggregate_deduplicate(n: int) -> float:
    from pubmed_search.application.search.result_aggregator import ResultAggregator

    articles = _make_articles(n, duplicate_ratio=0.25)
    aggregator = ResultAggregator()

    def run() -> None:
        aggregator.aggregate([articles])

    return _time_callable(run, repeats=3)


def _target_rank_articles(n: int) -> float:
    from pubmed_search.application.search.result_aggregator import (
        RankingConfig,
        ResultAggregator,
    )

    articles = _make_articles(n, duplicate_ratio=0.0)
    config = RankingConfig.default()
    config.use_mmr = False
    aggregator = ResultAggregator(config)

    def run() -> None:
        aggregator.rank(articles, config, query="remimazolam ICU sedation randomized trial")

    return _time_callable(run, repeats=3)


def _target_format_unified_results(n: int) -> float:
    from pubmed_search.application.search.query_analyzer import QueryAnalyzer
    from pubmed_search.application.search.result_aggregator import AggregationStats
    from pubmed_search.presentation.mcp_server.tools.unified_formatting import _format_unified_results

    analysis = QueryAnalyzer().analyze("remimazolam ICU sedation randomized trial")
    articles = _make_articles(n, duplicate_ratio=0.0)
    stats = AggregationStats(total_input=n, unique_articles=n, by_source={"pubmed": n})

    async def run_async() -> str:
        return await _format_unified_results(
            articles,
            analysis,
            stats,
            include_trials=False,
            include_similarity_scores=True,
            original_query="remimazolam ICU sedation randomized trial",
            source_api_counts={"pubmed": (n, n * 3)},
        )

    return _time_callable(run_async, repeats=3)


def _target_pipeline_filter(n: int) -> float:
    from pubmed_search.application.pipeline.executor import PipelineExecutor
    from pubmed_search.domain.entities.pipeline import PipelineStep, StepResult

    articles = _make_articles(n, duplicate_ratio=0.0)
    step = PipelineStep(
        id="filter",
        action="filter",
        inputs=["input"],
        params={"min_year": 2021, "max_year": 2025, "has_abstract": True},
    )
    inputs = {"input": StepResult(step_id="input", action="search", articles=articles)}
    executor = PipelineExecutor()

    async def run_async() -> None:
        await executor._action_filter(step, inputs)

    return _time_callable(run_async, repeats=3)


def _target_article_to_dict(n: int) -> float:
    articles = _make_articles(n, duplicate_ratio=0.0)

    def run() -> None:
        for article in articles:
            article.to_dict()

    return _time_callable(run, repeats=3)


def _make_article_dicts(n: int) -> list[dict[str, Any]]:
    return [
        {
            "pmid": str(20_000_000 + i),
            "title": f"Export benchmark article {i}",
            "authors": [f"Author {j}" for j in range(i % 8)],
            "journal": f"Journal {i % 9}",
            "year": 2020 + (i % 6),
            "abstract": "Background methods results conclusion. " * 12,
            "doi": f"10.2000/export.{i}",
            "keywords": ["sedation", "icu", "trial"],
        }
        for i in range(n)
    ]


def _target_export_ris(n: int) -> float:
    from pubmed_search.application.export.formats import export_articles

    articles = _make_article_dicts(n)

    def run() -> None:
        export_articles(articles, "ris")

    return _time_callable(run, repeats=3)


def _target_session_cache_lookup(n: int) -> float:
    from pubmed_search.application.session.manager import SessionManager

    manager = SessionManager(data_dir=str(DEFAULT_OUTPUT_DIR / "session-bench"))
    articles = _make_article_dicts(n)
    manager.add_to_cache(articles, _skip_save=True)
    pmids = [article["pmid"] for article in articles]

    def run() -> None:
        manager.get_from_cache(pmids)

    return _time_callable(run, repeats=3)


def iter_target_specs() -> list[TargetSpec]:
    """Return low-memory empirical scan targets."""
    return [
        TargetSpec(
            name="aggregate_deduplicate",
            description="ResultAggregator.aggregate with mixed identifiers and duplicates.",
            path="src/pubmed_search/application/search/result_aggregator.py",
            sizes=(20, 50, 100, 200, 400, 800),
            repeats=3,
            runner=_target_aggregate_deduplicate,
        ),
        TargetSpec(
            name="rank_articles",
            description="ResultAggregator.rank with BM25/RRF scoring over synthetic articles.",
            path="src/pubmed_search/application/search/result_aggregator.py",
            sizes=(20, 50, 100, 200, 400, 800),
            repeats=3,
            runner=_target_rank_articles,
        ),
        TargetSpec(
            name="format_unified_results",
            description="Markdown formatting for unified search output.",
            path="src/pubmed_search/presentation/mcp_server/tools/unified_formatting.py",
            sizes=(10, 25, 50, 100, 200, 400),
            repeats=3,
            runner=_target_format_unified_results,
        ),
        TargetSpec(
            name="pipeline_filter",
            description="PipelineExecutor filter action over article lists.",
            path="src/pubmed_search/application/pipeline/executor.py",
            sizes=(100, 500, 1000, 2000, 4000, 8000),
            repeats=3,
            runner=_target_pipeline_filter,
        ),
        TargetSpec(
            name="article_to_dict",
            description="UnifiedArticle.to_dict serialization over article lists.",
            path="src/pubmed_search/domain/entities/article.py",
            sizes=(20, 50, 100, 200, 400, 800),
            repeats=3,
            runner=_target_article_to_dict,
        ),
        TargetSpec(
            name="export_ris",
            description="RIS export formatting over in-memory article dictionaries.",
            path="src/pubmed_search/application/export/formats.py",
            sizes=(20, 50, 100, 200, 400, 800),
            repeats=3,
            runner=_target_export_ris,
        ),
        TargetSpec(
            name="session_cache_lookup",
            description="SessionManager in-memory cache lookup by PMID list.",
            path="src/pubmed_search/application/session/manager.py",
            sizes=(20, 50, 100, 200, 400, 800),
            repeats=3,
            runner=_target_session_cache_lookup,
        ),
    ]


def summarize_static_hotspots(limit: int = 20) -> list[StaticHotspot]:
    """Summarize largest Python files and local ruff complexity findings."""
    complexity_counts: dict[str, int] = {}
    for path in SRC_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        count = 0
        for marker in ("C901", "PLR0911", "PLR0912", "PLR0915"):
            count += text.count(f"# noqa: {marker}")
        complexity_counts[rel] = count

    hotspots = []
    for path in SRC_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        try:
            lines = sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        hotspots.append(
            StaticHotspot(
                path=rel,
                lines=lines,
                complexity_findings=complexity_counts.get(rel, 0),
            )
        )
    return sorted(hotspots, key=lambda item: (item.lines, item.complexity_findings), reverse=True)[:limit]


def run_target(target: TargetSpec) -> dict[str, Any]:
    samples = [(size, target.runner(size)) for size in target.sizes]
    fit = fit_complexity(samples)
    return {
        "name": target.name,
        "description": target.description,
        "path": target.path,
        "samples": [{"n": n, "seconds": seconds} for n, seconds in samples],
        "best_model": asdict(fit.best),
        "models": [asdict(model) for model in fit.models],
    }


def run_scan(target_names: set[str] | None = None) -> dict[str, Any]:
    specs = iter_target_specs()
    if target_names:
        specs = [spec for spec in specs if spec.name in target_names]
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": "Empirical estimates from synthetic inputs; use as triage, not proof.",
        "targets": [run_target(spec) for spec in specs],
        "static_hotspots": [asdict(item) for item in summarize_static_hotspots(limit=25)],
    }


def write_markdown_report(scan: dict[str, Any], output_path: Path) -> None:
    lines = [
        "# Repo Complexity Analysis",
        "",
        f"Generated: {scan['generated_at']}",
        "",
        "This report uses low-memory empirical timing over synthetic inputs. Treat fitted Big-O labels as triage signals.",
        "",
        "## Empirical Targets",
        "",
    ]
    for target in scan["targets"]:
        best = target["best_model"]
        lines.append(f"### {target['name']}")
        lines.append("")
        lines.append(f"- Path: `{target['path']}`")
        lines.append(f"- Estimated class: `{best['name']}` (`R^2={best['r_squared']:.3f}`)")
        lines.append("- Samples:")
        for sample in target["samples"]:
            lines.append(f"  - N={sample['n']}: {sample['seconds'] * 1000:.3f} ms")
        lines.append("")
    lines.extend(["## Largest Source Files", ""])
    for item in scan["static_hotspots"]:
        lines.append(f"- `{item['path']}`: {item['lines']} lines")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", action="append", help="Target name to run. Repeatable. Defaults to all.")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT_DIR / "complexity_scan.json")
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    scan = run_scan(set(args.target or []) or None)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(scan, indent=2), encoding="utf-8")
    if args.markdown_output:
        write_markdown_report(scan, args.markdown_output)
    print(f"Wrote {args.json_output}")
    if args.markdown_output:
        print(f"Wrote {args.markdown_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
