"""
Performance benchmarks for key code paths.

Run with::

    uv run pytest tests/benchmarks/ --benchmark-only -p no:xdist

Benchmarks are automatically DISABLED under xdist (``-n auto``),
so ``uv run pytest`` will silently skip them.  This is intentional:
benchmarks need single-process precision.

Baselines are stored in ``.benchmarks/`` (git-ignored).
"""

from __future__ import annotations

import pytest

from pubmed_search.container import ApplicationContainer

# ============================================================================
# Benchmark: DI Container
# ============================================================================


class TestContainerBenchmarks:
    """Benchmark DI container creation and resolution."""

    def test_container_creation(self, benchmark: pytest.BenchmarkFixture) -> None:
        """Container instantiation should be < 1 ms."""

        def _create() -> ApplicationContainer:
            c = ApplicationContainer()
            c.config.from_dict({"email": "bench@test.com", "api_key": None, "data_dir": "/tmp"})
            return c

        benchmark(_create)

    def test_singleton_resolution(self, benchmark: pytest.BenchmarkFixture) -> None:
        """Subsequent singleton lookups should be < 10 µs."""
        container = ApplicationContainer()
        container.config.from_dict({"email": "bench@test.com", "api_key": None, "data_dir": "/tmp"})
        # warm up — create the singleton
        container.session_manager()

        benchmark(container.session_manager)


# ============================================================================
# Benchmark: Article Formatting
# ============================================================================


class TestFormattingBenchmarks:
    """Benchmark article formatting hot paths."""

    @pytest.fixture()
    def sample_articles(self) -> list[dict]:
        """Generate a list of realistic article dicts."""
        return [
            {
                "pmid": str(10000 + i),
                "title": f"A systematic review of topic {i} in clinical practice",
                "authors": [f"Author{j}" for j in range(5)],
                "journal": f"Journal of Medicine {i % 10}",
                "year": 2020 + (i % 5),
                "abstract": f"Background: topic {i}. Methods: RCT. Results: significant. Conclusion: effective." * 3,
                "doi": f"10.1000/test.{10000 + i}",
            }
            for i in range(50)
        ]

    def test_format_articles_list(self, benchmark: pytest.BenchmarkFixture, sample_articles: list[dict]) -> None:
        """Formatting 50 articles for export (RIS) should be < 5 ms."""
        from pubmed_search.application.export.formats import export_articles

        benchmark(export_articles, sample_articles, "ris")


# ============================================================================
# Benchmark: Session Cache
# ============================================================================


class TestSessionBenchmarks:
    """Benchmark session cache operations."""

    def test_session_add_and_lookup(self, benchmark: pytest.BenchmarkFixture) -> None:
        """Adding + looking up a cached article should be < 1 ms."""
        from pubmed_search.application.session.manager import SessionManager

        sm = SessionManager(data_dir="/tmp/bench-session")
        article = {
            "pmid": "99999",
            "title": "Benchmark article",
            "authors": ["Auth1"],
            "journal": "J Bench",
            "year": 2025,
        }

        def _add_and_get() -> tuple[list[dict], list[str]]:
            sm.add_to_cache([article])
            return sm.get_from_cache(["99999"])

        benchmark(_add_and_get)


# ============================================================================
# Benchmark: Profiling overhead
# ============================================================================


class TestProfilingBenchmarks:
    """Benchmark the profiling instrumentation overhead."""

    def test_tool_stats_record(self, benchmark: pytest.BenchmarkFixture) -> None:
        """Recording a single ToolStats entry should be < 10 µs."""
        from pubmed_search.shared.profiling import ToolStats

        stats = ToolStats()

        def _record() -> None:
            stats.record(total_ms=150.0, http_ms=120.0)

        benchmark(_record)

    def test_format_metrics_report(self, benchmark: pytest.BenchmarkFixture) -> None:
        """Formatting a metrics report with 20 tools should be < 5 ms."""
        from pubmed_search.shared.profiling import ToolStats, _metrics, format_metrics_report

        # Populate with realistic data
        _metrics.clear()
        for i in range(20):
            stats = ToolStats()
            for _ in range(50):
                stats.record(total_ms=100.0 + i * 10, http_ms=80.0 + i * 5)
            _metrics[f"tool_{i}"] = stats

        try:
            benchmark(format_metrics_report)
        finally:
            _metrics.clear()


# ============================================================================
# Benchmark: Query Analysis
# ============================================================================


class TestQueryAnalysisBenchmarks:
    """Benchmark query parsing (no network calls)."""

    def test_query_analyzer_parse(self, benchmark: pytest.BenchmarkFixture) -> None:
        """QueryAnalyzer.analyze() without network should be < 2 ms."""
        from pubmed_search.application.search.query_analyzer import QueryAnalyzer

        analyzer = QueryAnalyzer()
        query = '"Artificial Intelligence"[MeSH] AND "Anesthesiology"[MeSH] AND clinical trial[pt]'

        benchmark(analyzer.analyze, query)
