"""Concurrent tests for Bio.Entrez runtime metadata isolation."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING

from pubmed_search.infrastructure.ncbi.base import run_entrez_callable

if TYPE_CHECKING:
    from collections.abc import Callable


class FakeEntrezModule:
    """Minimal Entrez-like object with mutable module-level metadata."""

    def __init__(self) -> None:
        self.email = "baseline@example.com"
        self.api_key = "baseline-api-key"
        self.tool = "baseline-tool"
        self.max_tries = 7
        self.sleep_between_tries = 9


def _capture_runtime_state(entrez_module: FakeEntrezModule) -> dict[str, object]:
    return {
        "email": entrez_module.email,
        "api_key": entrez_module.api_key,
        "tool": entrez_module.tool,
        "max_tries": entrez_module.max_tries,
        "sleep_between_tries": entrez_module.sleep_between_tries,
    }


async def test_run_entrez_callable_serializes_concurrent_metadata_updates() -> None:
    """Concurrent callers should each observe their own Entrez metadata and restore globals."""

    entrez_module = FakeEntrezModule()
    counter_lock = threading.Lock()
    active_calls = 0
    max_active_calls = 0

    def make_callable() -> Callable[[], tuple[dict[str, object], dict[str, object]]]:
        def _call() -> tuple[dict[str, object], dict[str, object]]:
            nonlocal active_calls, max_active_calls
            with counter_lock:
                active_calls += 1
                max_active_calls = max(max_active_calls, active_calls)
            try:
                observed_before = _capture_runtime_state(entrez_module)
                time.sleep(0.01)
                observed_after = _capture_runtime_state(entrez_module)
                return observed_before, observed_after
            finally:
                with counter_lock:
                    active_calls -= 1

        return _call

    requested_states = [
        (f"user{i}@example.com", f"api-key-{i}", f"tool-{i}")
        for i in range(8)
    ]
    tasks = [
        asyncio.to_thread(
            run_entrez_callable,
            entrez_module,
            make_callable(),
            email=email,
            api_key=api_key,
            tool=tool,
        )
        for email, api_key, tool in requested_states
    ]

    results = await asyncio.gather(*tasks)

    assert max_active_calls == 1
    for requested, observed in zip(requested_states, results, strict=True):
        email, api_key, tool = requested
        observed_before, observed_after = observed

        assert observed_before == {
            "email": email,
            "api_key": api_key,
            "tool": tool,
            "max_tries": 1,
            "sleep_between_tries": 0,
        }
        assert observed_after == observed_before

    assert _capture_runtime_state(entrez_module) == {
        "email": "baseline@example.com",
        "api_key": "baseline-api-key",
        "tool": "baseline-tool",
        "max_tries": 7,
        "sleep_between_tries": 9,
    }


async def test_run_entrez_callable_restores_metadata_after_concurrent_failure() -> None:
    """A failing concurrent caller should not leak Entrez metadata into other calls."""

    entrez_module = FakeEntrezModule()
    counter_lock = threading.Lock()
    active_calls = 0
    max_active_calls = 0

    def make_callable(*, should_fail: bool) -> Callable[[], dict[str, object]]:
        def _call() -> dict[str, object]:
            nonlocal active_calls, max_active_calls
            with counter_lock:
                active_calls += 1
                max_active_calls = max(max_active_calls, active_calls)
            try:
                observed = _capture_runtime_state(entrez_module)
                time.sleep(0.01)
                if should_fail:
                    raise RuntimeError("boom")
                return observed
            finally:
                with counter_lock:
                    active_calls -= 1

        return _call

    requested_states = [
        ("ok1@example.com", "ok-key-1", "ok-tool-1", False),
        ("boom@example.com", "boom-key", "boom-tool", True),
        ("ok2@example.com", "ok-key-2", "ok-tool-2", False),
    ]
    tasks = [
        asyncio.to_thread(
            run_entrez_callable,
            entrez_module,
            make_callable(should_fail=should_fail),
            email=email,
            api_key=api_key,
            tool=tool,
        )
        for email, api_key, tool, should_fail in requested_states
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert max_active_calls == 1
    assert isinstance(results[1], RuntimeError)
    assert str(results[1]) == "boom"

    for index in (0, 2):
        email, api_key, tool, _should_fail = requested_states[index]
        assert results[index] == {
            "email": email,
            "api_key": api_key,
            "tool": tool,
            "max_tries": 1,
            "sleep_between_tries": 0,
        }

    assert _capture_runtime_state(entrez_module) == {
        "email": "baseline@example.com",
        "api_key": "baseline-api-key",
        "tool": "baseline-tool",
        "max_tries": 7,
        "sleep_between_tries": 9,
    }


async def test_run_entrez_callable_stress_preserves_runtime_across_many_mixed_callers() -> None:
    """Stress the runtime lock with many concurrent mixed success/failure callers."""

    entrez_module = FakeEntrezModule()
    counter_lock = threading.Lock()
    active_calls = 0
    max_active_calls = 0

    def make_callable(index: int, *, should_fail: bool) -> Callable[[], dict[str, object]]:
        def _call() -> dict[str, object]:
            nonlocal active_calls, max_active_calls
            with counter_lock:
                active_calls += 1
                max_active_calls = max(max_active_calls, active_calls)
            try:
                observed = _capture_runtime_state(entrez_module)
                time.sleep(0.002 + (index % 5) * 0.001)
                if should_fail:
                    raise RuntimeError(f"boom-{index}")
                return observed
            finally:
                with counter_lock:
                    active_calls -= 1

        return _call

    requested_states = [
        (index, f"stress{index}@example.com", f"stress-key-{index}", f"stress-tool-{index}", index % 7 == 0)
        for index in range(40)
    ]
    tasks = [
        asyncio.to_thread(
            run_entrez_callable,
            entrez_module,
            make_callable(index, should_fail=should_fail),
            email=email,
            api_key=api_key,
            tool=tool,
        )
        for index, email, api_key, tool, should_fail in requested_states
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert max_active_calls == 1
    for requested, result in zip(requested_states, results, strict=True):
        index, email, api_key, tool, should_fail = requested
        if should_fail:
            assert isinstance(result, RuntimeError)
            assert str(result) == f"boom-{index}"
            continue

        assert result == {
            "email": email,
            "api_key": api_key,
            "tool": tool,
            "max_tries": 1,
            "sleep_between_tries": 0,
        }

    assert _capture_runtime_state(entrez_module) == {
        "email": "baseline@example.com",
        "api_key": "baseline-api-key",
        "tool": "baseline-tool",
        "max_tries": 7,
        "sleep_between_tries": 9,
    }


async def test_run_entrez_callable_high_pressure_throughput_budget() -> None:
    """Benchmark serialized throughput under high concurrency.

    This is a benchmark-style regression guard rather than a microbenchmark:
    it checks that lock serialization does not collapse throughput below a
    practical lower bound when many callers contend for Entrez runtime state.
    """

    entrez_module = FakeEntrezModule()
    task_count = 96
    service_time = 0.0015
    lower_bound = task_count * service_time

    def _call() -> None:
        time.sleep(service_time)

    started = time.perf_counter()
    await asyncio.gather(
        *[
            asyncio.to_thread(
                run_entrez_callable,
                entrez_module,
                _call,
                email=f"bench{i}@example.com",
                api_key=f"bench-key-{i}",
                tool=f"bench-tool-{i}",
            )
            for i in range(task_count)
        ]
    )
    elapsed = time.perf_counter() - started
    throughput = task_count / elapsed
    coordination_overhead = elapsed - lower_bound

    assert elapsed >= lower_bound
    assert throughput >= 250.0
    assert coordination_overhead < 0.25


async def test_run_entrez_callable_high_pressure_wait_cost_budget() -> None:
    """Benchmark queue wait cost introduced by lock serialization.

    The expected mean wait is roughly half the serialized service window; this
    guard ensures coordination overhead stays bounded instead of exploding far
    beyond the synthetic critical-section duration.
    """

    entrez_module = FakeEntrezModule()
    task_count = 72
    service_time = 0.001
    entered_at: list[float] = [0.0] * task_count
    scheduled_at: list[float] = [0.0] * task_count

    def _make_callable(index: int):
        def _call() -> None:
            entered_at[index] = time.perf_counter()
            time.sleep(service_time)

        return _call

    async def _run_one(index: int) -> None:
        scheduled_at[index] = time.perf_counter()
        await asyncio.to_thread(
            run_entrez_callable,
            entrez_module,
            _make_callable(index),
            email=f"wait{index}@example.com",
            api_key=f"wait-key-{index}",
            tool=f"wait-tool-{index}",
        )

    await asyncio.gather(*[_run_one(index) for index in range(task_count)])

    waits = sorted(entered - scheduled for entered, scheduled in zip(entered_at, scheduled_at, strict=True))
    mean_wait = sum(waits) / len(waits)
    p95_wait = waits[int(len(waits) * 0.95) - 1]
    theoretical_mean_wait = ((task_count - 1) * service_time) / 2

    assert mean_wait < theoretical_mean_wait + 0.03
    assert p95_wait < (task_count * service_time) + 0.03
