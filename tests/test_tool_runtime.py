"""Tests for MCP host callback runtime guards."""

from __future__ import annotations

import asyncio

import pytest

from pubmed_search.presentation.mcp_server.tools.tool_runtime import best_effort_host_callback


@pytest.mark.asyncio
async def test_best_effort_host_callback_does_not_cancel_transiently_slow_host_callback():
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

    await asyncio.wait_for(started.wait(), timeout=0.1)
    await asyncio.sleep(0.03)

    assert not cancelled.is_set()

    release.set()
    await asyncio.wait_for(completed.wait(), timeout=0.1)
