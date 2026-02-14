"""
Lightweight MCP tool performance profiling.

Toggle via environment variable: PUBMED_PROFILING=1

Features:
- Per-tool execution time tracking (total, min, max, avg, p95)
- HTTP API time separation via contextvars
- In-memory rolling window (last N calls per tool)
- Zero overhead when disabled (early return)

Usage:
    # In server.py after create_server():
    from pubmed_search.shared.profiling import install_profiling
    install_profiling(mcp)

    # Query metrics (when profiling enabled, auto-registers MCP tool):
    get_performance_metrics()
"""

from __future__ import annotations

import contextvars
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# ── Toggle ──────────────────────────────────────────────────────────────────
PROFILING_ENABLED = os.environ.get("PUBMED_PROFILING", "").lower() in ("1", "true", "yes")

# ── Context var for tracking HTTP time within a tool call ───────────────────
_http_time_accumulator: contextvars.ContextVar[list[float]] = contextvars.ContextVar(
    "http_time_accumulator",
)


def record_http_time(elapsed_ms: float) -> None:
    """Record HTTP request time for the current tool call context."""
    try:
        acc = _http_time_accumulator.get()
        acc.append(elapsed_ms)
    except LookupError:
        pass


# ── Data structures ─────────────────────────────────────────────────────────

MAX_HISTORY_PER_TOOL = 200  # Rolling window size


@dataclass
class CallRecord:
    """Single tool call record."""

    timestamp: float
    total_ms: float
    http_ms: float  # Sum of all HTTP calls during this tool invocation
    processing_ms: float  # total_ms - http_ms


@dataclass
class ToolStats:
    """Aggregated stats for a single tool."""

    calls: list[CallRecord] = field(default_factory=list)

    def record(self, total_ms: float, http_ms: float) -> None:
        proc_ms = max(0.0, total_ms - http_ms)
        self.calls.append(
            CallRecord(
                timestamp=time.time(),
                total_ms=total_ms,
                http_ms=http_ms,
                processing_ms=proc_ms,
            )
        )
        # Rolling window
        if len(self.calls) > MAX_HISTORY_PER_TOOL:
            self.calls = self.calls[-MAX_HISTORY_PER_TOOL:]

    @property
    def count(self) -> int:
        return len(self.calls)

    @property
    def total_avg(self) -> float:
        return sum(c.total_ms for c in self.calls) / len(self.calls) if self.calls else 0

    @property
    def total_min(self) -> float:
        return min(c.total_ms for c in self.calls) if self.calls else 0

    @property
    def total_max(self) -> float:
        return max(c.total_ms for c in self.calls) if self.calls else 0

    @property
    def total_p95(self) -> float:
        if not self.calls:
            return 0
        sorted_vals = sorted(c.total_ms for c in self.calls)
        idx = int(len(sorted_vals) * 0.95)
        return sorted_vals[min(idx, len(sorted_vals) - 1)]

    @property
    def http_avg(self) -> float:
        return sum(c.http_ms for c in self.calls) / len(self.calls) if self.calls else 0

    @property
    def processing_avg(self) -> float:
        return sum(c.processing_ms for c in self.calls) / len(self.calls) if self.calls else 0

    def summary_dict(self) -> dict[str, Any]:
        return {
            "calls": self.count,
            "total_ms": {
                "avg": round(self.total_avg, 1),
                "min": round(self.total_min, 1),
                "max": round(self.total_max, 1),
                "p95": round(self.total_p95, 1),
            },
            "http_ms_avg": round(self.http_avg, 1),
            "processing_ms_avg": round(self.processing_avg, 1),
        }


# ── Global metrics store ───────────────────────────────────────────────────
_metrics: dict[str, ToolStats] = defaultdict(ToolStats)


def get_metrics() -> dict[str, ToolStats]:
    """Get the global metrics store (read-only access)."""
    return dict(_metrics)


def reset_metrics() -> None:
    """Clear all recorded metrics."""
    _metrics.clear()


def format_metrics_report() -> str:
    """Format a human-readable performance report."""
    if not _metrics:
        return "📊 No performance data recorded yet.\n\nEnsure `PUBMED_PROFILING=1` is set."

    lines = ["📊 **MCP Tool Performance Report**\n"]
    lines.append(f"{'Tool':<35} {'Calls':>5} {'Avg':>8} {'P95':>8} {'Max':>8} {'HTTP%':>6}")
    lines.append("-" * 75)

    # Sort by total avg descending (slowest first)
    sorted_tools = sorted(_metrics.items(), key=lambda x: x[1].total_avg, reverse=True)

    for name, stats in sorted_tools:
        http_pct = (stats.http_avg / stats.total_avg * 100) if stats.total_avg > 0 else 0
        lines.append(
            f"{name:<35} {stats.count:>5} "
            f"{stats.total_avg:>7.0f}ms "
            f"{stats.total_p95:>7.0f}ms "
            f"{stats.total_max:>7.0f}ms "
            f"{http_pct:>5.0f}%"
        )

    lines.append("-" * 75)
    total_calls = sum(s.count for s in _metrics.values())
    lines.append(f"Total calls: {total_calls}")
    lines.append("\n*HTTP% = percentage of time spent on external API calls*")
    lines.append("*Lower HTTP% means more processing overhead in our code*")

    return "\n".join(lines)


# ── Installation ────────────────────────────────────────────────────────────


def install_profiling(mcp: FastMCP) -> bool:
    """
    Install performance profiling on the MCP server.

    Monkey-patches mcp.call_tool() to wrap every tool invocation with timing.
    Also registers a `get_performance_metrics` tool for querying results.

    Returns True if profiling was installed, False if disabled.
    """
    if not PROFILING_ENABLED:
        logger.debug("Profiling disabled (set PUBMED_PROFILING=1 to enable)")
        return False

    logger.info("🔬 Performance profiling ENABLED")

    # ── Patch call_tool ─────────────────────────────────────────────────
    original_call_tool = mcp.call_tool

    async def profiled_call_tool(name: str, arguments: dict[str, Any]) -> Sequence[Any] | dict[str, Any]:
        # Set up HTTP time accumulator for this call
        http_times: list[float] = []
        token = _http_time_accumulator.set(http_times)

        start = time.perf_counter()
        try:
            return await original_call_tool(name, arguments)
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            http_ms = sum(http_times)
            _metrics[name].record(elapsed_ms, http_ms)

            # Log to stderr (visible in MCP stdio mode)
            proc_ms = max(0.0, elapsed_ms - http_ms)
            logger.info(f"[PERF] {name}: {elapsed_ms:.0f}ms total (http={http_ms:.0f}ms, proc={proc_ms:.0f}ms)")

            _http_time_accumulator.reset(token)

    mcp.call_tool = profiled_call_tool  # type: ignore[assignment]

    # ── Register metrics query tool ─────────────────────────────────────
    @mcp.tool()
    async def get_performance_metrics(
        tool_name: str = "",
        reset: bool = False,
    ) -> str:
        """
        [DEV] Get MCP tool execution performance metrics.

        Only available when PUBMED_PROFILING=1.

        Args:
            tool_name: Filter to specific tool (empty = all tools)
            reset: Reset all metrics after reporting
        """
        if tool_name:
            stats = _metrics.get(tool_name)
            if not stats:
                return f"No metrics for tool '{tool_name}'"
            import json

            report = f"📊 **{tool_name}** Performance\n\n"
            report += f"```json\n{json.dumps(stats.summary_dict(), indent=2)}\n```\n"
            if stats.calls:
                report += "\nLast 5 calls (ms): "
                recent = stats.calls[-5:]
                report += ", ".join(f"{c.total_ms:.0f}" for c in recent)
            return report

        report = format_metrics_report()

        if reset:
            count = sum(s.count for s in _metrics.values())
            reset_metrics()
            report += f"\n\n🔄 Metrics reset ({count} records cleared)"

        return report

    logger.info("Registered dev tool: get_performance_metrics")
    return True


def install_http_profiling() -> bool:
    """
    Instrument BaseAPIClient._make_request to track HTTP time.

    Call this once at startup (after imports).
    Returns True if installed, False if profiling disabled.
    """
    if not PROFILING_ENABLED:
        return False

    from pubmed_search.infrastructure.sources.base_client import BaseAPIClient

    original_make_request = BaseAPIClient._make_request  # noqa: SLF001

    async def profiled_make_request(self: Any, url: str, **kwargs: Any) -> Any:
        start = time.perf_counter()
        try:
            return await original_make_request(self, url, **kwargs)
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            record_http_time(elapsed_ms)

    BaseAPIClient._make_request = profiled_make_request  # type: ignore[assignment]  # noqa: SLF001
    logger.info("HTTP profiling installed on BaseAPIClient")
    return True
