"""Deadline and hedged-attempt primitives for fulltext orchestration.

Design:
    Several sources can answer the same question (identifier metadata, or a
    PMC JATS body). The preferred source is started first. A fallback starts
    as soon as the preferred one fails or answers unusably, or when it has not
    answered within a short hedge delay. The first usable answer wins and the
    remaining attempts are cancelled. Everything is bounded by the request
    deadline, and every attempt's fate is reported rather than hidden.

Maintenance:
    Attempts must convert their own provider exceptions into return values or
    raise; this module records exceptions without interpreting them. Keep
    timing here and source semantics in ``service.py``.

    A cancelled attempt gets a short grace period to finish. One that
    outlives it (for example a client that swallows the first cancellation)
    is not waited for, but it is not abandoned either: a strong reference is
    kept until it ends and its result or exception is then retrieved, so it
    can neither be garbage-collected mid-flight nor surface later as an
    unretrieved task exception.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

logger = logging.getLogger(__name__)

T = TypeVar("T")
_CANCEL_GRACE_SECONDS = 1.0
_ABANDONED_ATTEMPTS: set[asyncio.Future[Any]] = set()
"""Cancelled attempts still running after the grace period, held until they end."""
# Event-loop timers can fire a few milliseconds early (notably on Windows);
# starting a source with less budget than this cannot produce an answer.
MIN_USEFUL_BUDGET_SECONDS = 0.05


class FulltextDeadline:
    """Monotonic overall budget for one get_fulltext request."""

    def __init__(self, seconds: float | None, *, clock: Callable[[], float] = time.monotonic) -> None:
        if seconds is not None and (
            isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds)
        ):
            raise ValueError("Fulltext deadline must be a finite number of seconds or None")
        if seconds is not None and seconds <= 0:
            raise ValueError("Fulltext deadline must be positive")
        self.seconds = float(seconds) if seconds is not None else None
        self._clock = clock
        self._expires_at = clock() + self.seconds if self.seconds is not None else None

    def remaining(self) -> float | None:
        """Seconds left, ``None`` when unbounded; never negative."""
        if self._expires_at is None:
            return None
        return max(0.0, self._expires_at - self._clock())

    @property
    def expired(self) -> bool:
        """True once too little budget remains to start or keep waiting on a source."""
        remaining = self.remaining()
        return remaining is not None and remaining <= MIN_USEFUL_BUDGET_SECONDS


@dataclass(frozen=True)
class HedgedAttempt(Generic[T]):
    """One way to answer a question, identified by its stable source key."""

    source: str
    run: Callable[[], Awaitable[T]]


@dataclass
class HedgedOutcome(Generic[T]):
    """What happened to one attempt; exactly one terminal state applies."""

    source: str
    started: bool = False
    value: T | None = None
    error: BaseException | None = None
    stopped: Literal["superseded", "deadline"] | None = None
    skipped_by_deadline: bool = False

    @property
    def answered(self) -> bool:
        """The attempt ran to completion without raising."""
        return self.started and self.error is None and self.stopped is None


async def run_hedged(
    attempts: Sequence[HedgedAttempt[T]],
    *,
    usable: Callable[[T], bool],
    hedge_after: float,
    deadline: FulltextDeadline,
    on_start: Callable[[str], Awaitable[None]] | None = None,
) -> list[HedgedOutcome[T]]:
    """Run attempts in order with hedging; return one outcome per attempt.

    The next attempt starts as soon as a running attempt answers unusably or
    fails, or when ``hedge_after`` seconds pass without a usable answer.
    The first usable answer cancels the rest (``stopped="superseded"``). When
    the deadline elapses, running attempts are cancelled
    (``stopped="deadline"``) and unstarted ones are ``skipped_by_deadline``.
    """
    outcomes = [HedgedOutcome[T](source=attempt.source) for attempt in attempts]
    pending: dict[asyncio.Future[T], int] = {}
    next_index = 0
    winner: int | None = None

    async def start_next() -> None:
        nonlocal next_index
        index = next_index
        next_index += 1
        outcomes[index].started = True
        if on_start is not None:
            await on_start(attempts[index].source)
        pending[asyncio.ensure_future(attempts[index].run())] = index

    try:
        if attempts and not deadline.expired:
            await start_next()
        while pending:
            if deadline.expired:
                break
            remaining = deadline.remaining()
            can_hedge = next_index < len(attempts)
            # Only a hedge-bound wait may start the next source when it times
            # out; a deadline-bound wait that wakes early just re-checks time.
            hedge_bound = can_hedge and (remaining is None or hedge_after < remaining)
            timeout = hedge_after if hedge_bound else remaining
            done, _ = await asyncio.wait(pending, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                index = pending.pop(task)
                try:
                    value = task.result()
                except (asyncio.CancelledError, Exception) as exc:
                    # A dependency cancelled this attempt (not us): a failure.
                    outcomes[index].error = exc
                    continue
                outcomes[index].value = value
                if winner is None and usable(value):
                    winner = index
            if winner is not None or deadline.expired:
                break
            # A running attempt answered unusably or failed, or the hedge delay
            # elapsed: bring in the next source while still accepting a late
            # usable answer from the earlier ones.
            if can_hedge and (done or hedge_bound):
                await start_next()
    finally:
        reason: Literal["superseded", "deadline"] = "superseded" if winner is not None else "deadline"
        for task, index in pending.items():
            task.cancel()
            outcomes[index].stopped = reason
        if pending:
            with contextlib.suppress(Exception):
                await asyncio.wait(pending, timeout=_CANCEL_GRACE_SECONDS)
            for task, index in pending.items():
                if task.done():
                    _retrieve_outcome(task)
                else:
                    _reap_when_done(task, outcomes[index].source)
        if winner is None:
            for outcome in outcomes[next_index:]:
                outcome.skipped_by_deadline = deadline.expired
    return outcomes


def abandoned_attempt_count() -> int:
    """Cancelled attempts that outlived the grace period and are still running."""
    return len(_ABANDONED_ATTEMPTS)


def _retrieve_outcome(task: asyncio.Future[Any]) -> None:
    """Consume a stopped attempt's result so its exception is never reported as unretrieved."""
    _ABANDONED_ATTEMPTS.discard(task)
    if not task.cancelled():
        task.exception()


def _reap_when_done(task: asyncio.Future[Any], source: str) -> None:
    logger.warning("Fulltext source %s ignored cancellation; it is reaped when it finishes", source)
    _ABANDONED_ATTEMPTS.add(task)
    task.add_done_callback(_retrieve_outcome)


__all__ = [
    "MIN_USEFUL_BUDGET_SECONDS",
    "FulltextDeadline",
    "HedgedAttempt",
    "HedgedOutcome",
    "abandoned_attempt_count",
    "run_hedged",
]
