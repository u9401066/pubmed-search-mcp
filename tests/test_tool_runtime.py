"""Tests for MCP host callback runtime guards."""

from __future__ import annotations

import asyncio

import pytest

from pubmed_search.presentation.mcp_server.tools.tool_runtime import HostCallbackRuntime, best_effort_host_callback
from pubmed_search.presentation.mcp_server.tools.tool_session import ToolSessionRuntime, bind_tool_session_runtime


@pytest.mark.asyncio
async def test_best_effort_host_callback_cancels_cooperative_stalled_host_callback():
    started = asyncio.Event()
    release = asyncio.Event()
    completed = asyncio.Event()
    cancelled = asyncio.Event()

    async def _slow_host_callback() -> None:
        started.set()
        try:
            await release.wait()
            completed.set()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    await best_effort_host_callback(_slow_host_callback(), timeout=0.01)

    assert started.is_set()
    assert cancelled.is_set()
    assert not completed.is_set()


@pytest.mark.asyncio
async def test_best_effort_host_callback_bounds_cancellation_resistant_tasks():
    release = asyncio.Event()
    callbacks = HostCallbackRuntime(max_pending=2)

    async def _ignore_cancellation() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()

    with bind_tool_session_runtime(ToolSessionRuntime(host_callbacks=callbacks)):
        for _ in range(3):
            await best_effort_host_callback(_ignore_cancellation(), timeout=0.001)

        assert callbacks.pending_count == 2
        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert callbacks.pending_count == 0
