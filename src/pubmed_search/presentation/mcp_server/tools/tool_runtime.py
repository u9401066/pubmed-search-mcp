"""Small runtime guards for host-facing MCP callbacks.

Design:
    Progress, logging, and resource update callbacks should never block core
    tool execution. Each callback receives a short, hard deadline. A callback
    that cooperates with cancellation is reaped immediately; a broken callback
    that suppresses cancellation is quarantined in a server-owned, bounded
    supervisor so it cannot stall a tool or accumulate without limit.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal

from pubmed_search.shared.bounded_tasks import BoundedTaskSupervisor

if TYPE_CHECKING:
    from mcp.server.mcpserver import Context

HOST_CALLBACK_TIMEOUT_SECONDS = 0.1
MAX_PENDING_HOST_CALLBACKS = 32


class HostCallbackRuntime(BoundedTaskSupervisor):
    """Own and bound cancellation-resistant callbacks for one MCP server."""

    __slots__ = ()

    def __init__(self, *, max_pending: int = MAX_PENDING_HOST_CALLBACKS) -> None:
        super().__init__(max_pending=max_pending)

    async def aclose(self, *, grace_seconds: float = HOST_CALLBACK_TIMEOUT_SECONDS) -> None:
        """Cancel owned callbacks and give cooperative callbacks time to exit."""
        await super().aclose(grace_seconds=grace_seconds)


def _get_host_callback_runtime() -> HostCallbackRuntime:
    # Lazy import avoids a module cycle: ToolSessionRuntime owns this runtime,
    # while this low-level helper is used by the tool/session wrappers.
    from .tool_session import get_tool_session_runtime

    return get_tool_session_runtime().host_callbacks


async def best_effort_host_callback(
    awaitable: Any,
    *,
    timeout: float = HOST_CALLBACK_TIMEOUT_SECONDS,
) -> None:
    """Run a host callback under a hard deadline and swallow host failures."""
    runtime = _get_host_callback_runtime()
    task = runtime.schedule(awaitable)
    if task is None:
        return
    try:
        done, _ = await asyncio.wait({task}, timeout=max(0.0, timeout))
        if done:
            return
        task.cancel()
        # Deliver cancellation once without waiting for a callback that chooses
        # to suppress it. The server-owned runtime retains and bounds such work.
        await asyncio.sleep(0)
    except asyncio.CancelledError:
        task.cancel()
        await asyncio.sleep(0)
        raise
    except Exception:
        return


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
