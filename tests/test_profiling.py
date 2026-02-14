"""Tests for shared/profiling.py — MCP tool performance profiler."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.shared.profiling import (
    CallRecord,
    ToolStats,
    _http_time_accumulator,
    _metrics,
    format_metrics_report,
    get_metrics,
    record_http_time,
    reset_metrics,
)

# ── ToolStats unit tests ────────────────────────────────────────────────────


class TestToolStats:
    def test_empty_stats(self):
        stats = ToolStats()
        assert stats.count == 0
        assert stats.total_avg == 0
        assert stats.total_min == 0
        assert stats.total_max == 0
        assert stats.total_p95 == 0
        assert stats.http_avg == 0
        assert stats.processing_avg == 0

    def test_record_single(self):
        stats = ToolStats()
        stats.record(total_ms=100.0, http_ms=80.0)
        assert stats.count == 1
        assert stats.total_avg == 100.0
        assert stats.http_avg == 80.0
        assert stats.processing_avg == 20.0

    def test_record_multiple(self):
        stats = ToolStats()
        stats.record(100.0, 60.0)
        stats.record(200.0, 150.0)
        stats.record(150.0, 100.0)
        assert stats.count == 3
        assert stats.total_avg == 150.0
        assert stats.total_min == 100.0
        assert stats.total_max == 200.0
        assert stats.http_avg == pytest.approx(103.33, abs=0.1)
        assert stats.processing_avg == pytest.approx(46.67, abs=0.1)

    def test_p95_calculation(self):
        stats = ToolStats()
        # 20 values: 10, 20, 30, ..., 200
        for i in range(1, 21):
            stats.record(float(i * 10), 0.0)
        # p95 index = int(20 * 0.95) = 19 → sorted_vals[19] = 200
        assert stats.total_p95 == 200.0

    def test_rolling_window(self):
        stats = ToolStats()
        from pubmed_search.shared.profiling import MAX_HISTORY_PER_TOOL

        for i in range(MAX_HISTORY_PER_TOOL + 50):
            stats.record(float(i), 0.0)
        assert stats.count == MAX_HISTORY_PER_TOOL

    def test_negative_processing_clamped_to_zero(self):
        """If http_ms > total_ms (timing edge case), processing should be 0."""
        stats = ToolStats()
        stats.record(total_ms=50.0, http_ms=60.0)  # Edge case
        assert stats.calls[0].processing_ms == 0.0

    def test_summary_dict(self):
        stats = ToolStats()
        stats.record(100.0, 70.0)
        stats.record(200.0, 140.0)
        d = stats.summary_dict()
        assert d["calls"] == 2
        assert d["total_ms"]["avg"] == 150.0
        assert d["total_ms"]["min"] == 100.0
        assert d["total_ms"]["max"] == 200.0
        assert d["http_ms_avg"] == 105.0
        assert d["processing_ms_avg"] == 45.0


# ── record_http_time & contextvar ────────────────────────────────────────────


class TestRecordHttpTime:
    def test_record_into_contextvar(self):
        """record_http_time should append to the current contextvar list."""
        acc: list[float] = []
        token = _http_time_accumulator.set(acc)
        try:
            record_http_time(50.0)
            record_http_time(30.0)
            assert acc == [50.0, 30.0]
        finally:
            _http_time_accumulator.reset(token)

    def test_record_without_contextvar_no_error(self):
        """Should not raise even if contextvar has no value."""
        # Default is [] so this should work
        record_http_time(10.0)


# ── Global metrics store ─────────────────────────────────────────────────────


class TestGlobalMetrics:
    def setup_method(self):
        reset_metrics()

    def teardown_method(self):
        reset_metrics()

    def test_get_metrics_empty(self):
        assert get_metrics() == {}

    def test_get_metrics_returns_copy(self):
        _metrics["test"].record(100.0, 50.0)
        m = get_metrics()
        assert "test" in m
        # Modifying returned dict shouldn't affect global
        m.pop("test")
        assert "test" in _metrics

    def test_reset_metrics(self):
        _metrics["tool_a"].record(100.0, 50.0)
        _metrics["tool_b"].record(200.0, 100.0)
        assert len(_metrics) == 2
        reset_metrics()
        assert len(_metrics) == 0


# ── format_metrics_report ────────────────────────────────────────────────────


class TestFormatMetricsReport:
    def setup_method(self):
        reset_metrics()

    def teardown_method(self):
        reset_metrics()

    def test_empty_report(self):
        report = format_metrics_report()
        assert "No performance data" in report

    def test_report_with_data(self):
        _metrics["slow_tool"].record(500.0, 400.0)
        _metrics["fast_tool"].record(10.0, 5.0)
        report = format_metrics_report()
        assert "Performance Report" in report
        assert "slow_tool" in report
        assert "fast_tool" in report
        assert "Total calls: 2" in report
        # slow_tool should appear before fast_tool (sorted by avg desc)
        assert report.index("slow_tool") < report.index("fast_tool")


# ── install_profiling ────────────────────────────────────────────────────────


class TestInstallProfiling:
    def setup_method(self):
        reset_metrics()

    def teardown_method(self):
        reset_metrics()

    def test_disabled_when_env_not_set(self):
        with patch.dict(os.environ, {}, clear=False):
            # Re-import to get fresh PROFILING_ENABLED value
            # But since it's module-level, we patch the variable directly
            with patch("pubmed_search.shared.profiling.PROFILING_ENABLED", False):
                from pubmed_search.shared.profiling import install_profiling

                mcp = MagicMock()
                result = install_profiling(mcp)
                assert result is False

    def test_enabled_patches_call_tool(self):
        with patch("pubmed_search.shared.profiling.PROFILING_ENABLED", True):
            from pubmed_search.shared.profiling import install_profiling

            mcp = MagicMock()
            mcp.call_tool = AsyncMock(return_value=[])
            mcp.tool = MagicMock(return_value=lambda fn: fn)  # Passthrough decorator

            result = install_profiling(mcp)
            assert result is True
            # call_tool should be replaced
            assert mcp.call_tool != AsyncMock

    @pytest.mark.asyncio
    async def test_profiled_call_tool_records_metrics(self):
        with patch("pubmed_search.shared.profiling.PROFILING_ENABLED", True):
            from pubmed_search.shared.profiling import install_profiling

            mcp = MagicMock()

            async def fake_call_tool(name, arguments):
                return [{"type": "text", "text": "ok"}]

            mcp.call_tool = fake_call_tool
            mcp.tool = MagicMock(return_value=lambda fn: fn)

            install_profiling(mcp)

            # Call the wrapped function
            result = await mcp.call_tool("test_tool", {"q": "hello"})
            assert result == [{"type": "text", "text": "ok"}]

            # Metrics should be recorded
            assert "test_tool" in _metrics
            assert _metrics["test_tool"].count == 1
            assert _metrics["test_tool"].total_avg > 0


# ── install_http_profiling ────────────────────────────────────────────────────


class TestInstallHttpProfiling:
    def test_disabled_returns_false(self):
        with patch("pubmed_search.shared.profiling.PROFILING_ENABLED", False):
            from pubmed_search.shared.profiling import install_http_profiling

            assert install_http_profiling() is False

    def test_enabled_patches_base_client(self):
        with patch("pubmed_search.shared.profiling.PROFILING_ENABLED", True):
            from pubmed_search.infrastructure.sources.base_client import BaseAPIClient
            from pubmed_search.shared.profiling import install_http_profiling

            original = BaseAPIClient._make_request
            try:
                result = install_http_profiling()
                assert result is True
                # _make_request should be replaced
                assert BaseAPIClient._make_request is not original
            finally:
                # Restore original to not affect other tests
                BaseAPIClient._make_request = original  # type: ignore[assignment]


# ── CallRecord dataclass ─────────────────────────────────────────────────────


class TestCallRecord:
    def test_fields(self):
        rec = CallRecord(timestamp=1000.0, total_ms=100.0, http_ms=70.0, processing_ms=30.0)
        assert rec.timestamp == 1000.0
        assert rec.total_ms == 100.0
        assert rec.http_ms == 70.0
        assert rec.processing_ms == 30.0
