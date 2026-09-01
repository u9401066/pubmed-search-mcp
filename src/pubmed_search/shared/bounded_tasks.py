"""Bounded ownership for best-effort asynchronous work.

Cancellation is cooperative in asyncio: a broken dependency can catch
``CancelledError`` and keep running.  This supervisor lets callers preserve a
hard response deadline while retaining, reaping, and capacity-limiting those
tasks for the lifetime of their owning application runtime.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from typing import Any, cast


class BoundedTaskSupervisor:
    """Own asynchronous work behind a fixed pending-task capacity."""

    __slots__ = ("_max_pending", "_pending")

    def __init__(self, *, max_pending: int) -> None:
        if max_pending < 1:
            raise ValueError("max_pending must be at least 1")
        self._max_pending = max_pending
        self._pending: set[asyncio.Future[Any]] = set()

    @property
    def pending_count(self) -> int:
        """Return work that has not finished or accepted cancellation."""
        self._prune_done()
        return len(self._pending)

    def schedule(self, awaitable: Any, *, name: str | None = None) -> asyncio.Future[Any] | None:
        """Schedule *awaitable*, or dispose it when the bounded pool is full."""
        self._prune_done()
        if len(self._pending) >= self._max_pending:
            self._dispose_unstarted(awaitable)
            return None
        try:
            task = cast("asyncio.Future[Any]", asyncio.ensure_future(awaitable))
        except (TypeError, RuntimeError):
            self._dispose_unstarted(awaitable)
            return None
        if name and isinstance(task, asyncio.Task):
            task.set_name(name)
        self._pending.add(task)
        task.add_done_callback(self._on_done)
        return task

    async def aclose(self, *, grace_seconds: float = 0.1) -> None:
        """Cancel owned work and give cooperative tasks bounded cleanup time."""
        self._prune_done()
        tasks = tuple(self._pending)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=max(0.0, grace_seconds))
        self._prune_done()

    def _prune_done(self) -> None:
        for task in tuple(self._pending):
            if task.done():
                self._on_done(task)

    def _on_done(self, task: asyncio.Future[Any]) -> None:
        self._pending.discard(task)
        with contextlib.suppress(asyncio.CancelledError, Exception):
            task.result()

    @staticmethod
    def _dispose_unstarted(awaitable: Any) -> None:
        if isinstance(awaitable, asyncio.Future):
            awaitable.cancel()
            return
        if inspect.iscoroutine(awaitable):
            awaitable.close()
            return
        closer = getattr(awaitable, "close", None)
        if callable(closer):
            closer()


__all__ = ["BoundedTaskSupervisor"]
