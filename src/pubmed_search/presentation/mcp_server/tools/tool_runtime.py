"""Small runtime guards for host-facing MCP callbacks.

Design:
    Progress, logging, and resource update callbacks should never block core
    tool execution. These helpers apply a short deadline and swallow host-side
    issues so external backpressure does not turn into apparent tool hangs.
"""

from __future__ import annotations

import asyncio
import contextlib
import weakref
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

HOST_CALLBACK_TIMEOUT_SECONDS = 0.1
_BACKGROUND_HOST_CALLBACKS: weakref.WeakSet[asyncio.Task[Any]] = weakref.WeakSet()


def _finalize_background_task(task: asyncio.Task[Any]) -> None:
    """Consume task results so best-effort host callbacks never leak warnings."""
    with contextlib.suppress(asyncio.CancelledError, Exception):
        task.result()


def _cancel_background_task(task: asyncio.Task[Any]) -> None:
    """Cancel a lingering host callback task after its grace window expires."""
    if not task.done():
        task.cancel()


async def best_effort_host_callback(
    awaitable: Any,
    *,
    timeout: float = HOST_CALLBACK_TIMEOUT_SECONDS,
) -> None:
    """Let a host callback run briefly without pinning the main tool path.

    The callback is scheduled as a background task, waited on only for a short
    grace period, and then cancelled if it does not finish in time.
    """
    task = asyncio.create_task(awaitable)
    _BACKGROUND_HOST_CALLBACKS.add(task)
    task.add_done_callback(_finalize_background_task)

    loop = asyncio.get_running_loop()
    loop.call_later(timeout, _cancel_background_task, task)
    await asyncio.sleep(0)


async def safe_report_progress(
    ctx: Context | None,
    progress: float,
    total: float,
    message: str,
    *,
    timeout: float = HOST_CALLBACK_TIMEOUT_SECONDS,
) -> None:
    """Report progress without allowing the host callback to stall the tool."""
    if ctx is None:
        return
    await best_effort_host_callback(ctx.report_progress(progress, total, message), timeout=timeout)


async def safe_log(
    ctx: Context | None,
    level: Literal["debug", "info", "warning", "error"],
    message: str,
    *,
    logger_name: str,
    timeout: float = HOST_CALLBACK_TIMEOUT_SECONDS,
) -> None:
    """Emit a best-effort MCP log event with a short host deadline."""
    if ctx is None:
        return
    await best_effort_host_callback(ctx.log(level, message, logger_name=logger_name), timeout=timeout)


async def safe_send_resource_updated(session: Any, uri: str, *, timeout: float = HOST_CALLBACK_TIMEOUT_SECONDS) -> None:
    """Notify a dynamic resource update without blocking the current tool."""
    if session is None:
        return
    await best_effort_host_callback(session.send_resource_updated(uri), timeout=timeout)
