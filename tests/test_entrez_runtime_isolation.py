"""Concurrent tests for Bio.Entrez runtime metadata isolation."""

from __future__ import annotations

import asyncio
import itertools
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


async def test_run_entrez_callable_high_pressure_completes_without_runtime_leakage() -> None:
    """High concurrency should finish without overlapping or leaking metadata."""

    entrez_module = FakeEntrezModule()
    counter_lock = threading.Lock()
    active_calls = 0
    max_active_calls = 0
    task_count = 96
    service_time = 0.0015

    def _make_callable(index: int) -> Callable[[], dict[str, object]]:
        def _call() -> dict[str, object]:
            nonlocal active_calls, max_active_calls
            with counter_lock:
                active_calls += 1
                max_active_calls = max(max_active_calls, active_calls)
            try:
                observed = _capture_runtime_state(entrez_module)
                time.sleep(service_time)
                return observed
            finally:
                with counter_lock:
                    active_calls -= 1

        return _call

    started = time.perf_counter()
    results = await asyncio.gather(
        *[
            asyncio.to_thread(
                run_entrez_callable,
                entrez_module,
                _make_callable(i),
                email=f"bench{i}@example.com",
                api_key=f"bench-key-{i}",
                tool=f"bench-tool-{i}",
            )
            for i in range(task_count)
        ]
    )
    elapsed = time.perf_counter() - started

    assert max_active_calls == 1
    assert len(results) == task_count
    assert elapsed < 10.0
    for index, observed in enumerate(results):
        assert observed == {
            "email": f"bench{index}@example.com",
            "api_key": f"bench-key-{index}",
            "tool": f"bench-tool-{index}",
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


async def test_run_entrez_callable_high_pressure_serializes_entry_windows() -> None:
    """Queued callers should enter the Entrez critical section one at a time."""

    entrez_module = FakeEntrezModule()
    task_count = 72
    service_time = 0.001
    scheduled_at: list[float] = [0.0] * task_count

    def _make_callable(index: int) -> Callable[[], tuple[int, float, float, dict[str, object]]]:
        def _call() -> tuple[int, float, float, dict[str, object]]:
            entered = time.perf_counter()
            observed = _capture_runtime_state(entrez_module)
            time.sleep(service_time)
            exited = time.perf_counter()
            return index, entered, exited, observed

        return _call

    async def _run_one(index: int) -> tuple[int, float, float, dict[str, object]]:
        scheduled_at[index] = time.perf_counter()
        return await asyncio.to_thread(
            run_entrez_callable,
            entrez_module,
            _make_callable(index),
            email=f"wait{index}@example.com",
            api_key=f"wait-key-{index}",
            tool=f"wait-tool-{index}",
        )

    results = await asyncio.gather(*[_run_one(index) for index in range(task_count)])

    entry_windows = sorted((entered, exited) for _index, entered, exited, _observed in results)
    for (_previous_entered, previous_exited), (current_entered, _current_exited) in itertools.pairwise(entry_windows):
        assert previous_exited <= current_entered

    waits = [entered - scheduled_at[index] for index, entered, _exited, _observed in results]
    assert min(waits) >= 0
    assert max(waits) < 10.0
    for index, _entered, _exited, observed in results:
        assert observed == {
            "email": f"wait{index}@example.com",
            "api_key": f"wait-key-{index}",
            "tool": f"wait-tool-{index}",
            "max_tries": 1,
            "sleep_between_tries": 0,
        }
