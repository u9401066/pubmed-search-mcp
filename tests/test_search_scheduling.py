"""Observable DAG progress, cancellation and shared upstream capacity."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from pubmed_search.application.pipeline.executor import PipelineExecutor
from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.domain.entities.pipeline import PipelineConfig, PipelineStep
from pubmed_search.infrastructure.ncbi.base import execute_entrez_operation
from pubmed_search.infrastructure.sources.base_client import BaseAPIClient
from pubmed_search.shared.async_utils import RequestExecutionPolicy, RetryPolicy, get_transport_kernel


@pytest.mark.parametrize("provider,capacity", [("ncbi", 1), ("rest", 2)])
async def test_production_provider_instances_share_default_capacity(provider, capacity):
    full, release = asyncio.Event(), asyncio.Event()
    active = peak = calls = 0

    async def operation(*args, **kwargs):
        nonlocal active, peak, calls
        calls += 1
        active += 1
        peak = max(peak, active)
        if active == capacity:
            full.set()
        try:
            await release.wait()
            return httpx.Response(200, json={"ok": True}, request=httpx.Request("GET", "https://offline.invalid"))
        finally:
            active -= 1

    clients = [BaseAPIClient(min_interval=0.001), BaseAPIClient(min_interval=0.001)]
    for client in clients:
        client._execute_request = operation

    async def invoke(index):
        if provider == "ncbi":
            return await execute_entrez_operation(
                operation, service_name=f"different-ncbi-operation-{index}", max_attempts=1
            )
        return await clients[index % 2]._make_request("/fixture")

    tasks = [asyncio.create_task(invoke(index)) for index in range(4)]
    try:
        await asyncio.wait_for(full.wait(), timeout=2)
        assert calls == capacity
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=3)
        assert calls == 4 and peak == capacity and active == 0
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for client in clients:
            await client.close()


def search_step(name, inputs=(), *, on_error="skip"):
    return PipelineStep(name, "search", {"query": name, "sources": ["pubmed"]}, list(inputs), on_error)


def page(query):
    return SourceSearchPage(source="pubmed", query=query, total=1, items=[{"pmid": "12345678", "title": query}])


@pytest.mark.parametrize("reverse_roots", [False, True])
async def test_ready_descendant_runs_while_unrelated_root_is_waiting(reverse_roots):
    child_finished = asyncio.Event()
    calls = []

    async def search_page(query, **kwargs):
        calls.append(query)
        if query == "slow":
            await child_finished.wait()
        if query == "child":
            child_finished.set()
        return page(query)

    roots = [search_step("fast"), search_step("slow")]
    if reverse_roots:
        roots.reverse()
    config = PipelineConfig(
        steps=[*roots, search_step("child", ["fast"]), PipelineStep("merged", "merge", inputs=["slow", "child"])]
    )
    articles, results = await asyncio.wait_for(
        PipelineExecutor(searcher=SimpleNamespace(search_page=search_page)).execute(config), timeout=1
    )
    assert child_finished.is_set()
    assert len(calls) == 3
    assert list(results) == [step.id for step in config.steps]
    assert all(result.ok for result in results.values())
    assert [article.pmid for article in articles] == ["12345678"]
    assert results["merged"].metadata["run_budget"]["external_calls_used"] == 3


async def test_abort_cancels_other_branches_before_launching_descendants():
    slow_started, slow_cancelled = asyncio.Event(), asyncio.Event()
    calls = []

    async def search_page(query, **kwargs):
        calls.append(query)
        if query == "fail":
            await slow_started.wait()
            raise RuntimeError("provider failed")
        slow_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            slow_cancelled.set()

    config = PipelineConfig(
        steps=[search_step("fail", on_error="abort"), search_step("slow"), search_step("child", ["fail"])]
    )
    with pytest.raises(RuntimeError, match="aborted"):
        await asyncio.wait_for(
            PipelineExecutor(searcher=SimpleNamespace(search_page=search_page)).execute(config), timeout=1
        )
    assert slow_cancelled.is_set()
    assert sorted(calls) == ["fail", "slow"]


async def test_two_pipeline_instances_share_the_upstream_concurrency_budget():
    active = peak = calls = 0
    full, release = asyncio.Event(), asyncio.Event()
    policy = RequestExecutionPolicy(
        service_name="two-pipelines", concurrency_limit=2, retry=RetryPolicy(max_attempts=1)
    )

    async def search_page(query, **kwargs):
        async def wire_request():
            nonlocal active, peak, calls
            calls += 1
            active += 1
            peak = max(peak, active)
            if active == 2:
                full.set()
            try:
                await release.wait()
                return page(query)
            finally:
                active -= 1

        return await get_transport_kernel().execute(wire_request, policy=policy)

    config = PipelineConfig(steps=[search_step("first"), search_step("second")])
    tasks = [
        asyncio.create_task(PipelineExecutor(searcher=SimpleNamespace(search_page=search_page)).execute(config))
        for _ in range(2)
    ]
    try:
        await asyncio.wait_for(full.wait(), timeout=1)
        assert calls == 2
        release.set()
        outcomes = await asyncio.wait_for(asyncio.gather(*tasks), timeout=1)
        assert calls == 4 and peak == 2 and active == 0
        assert all(result.ok for _, results in outcomes for result in results.values())
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
