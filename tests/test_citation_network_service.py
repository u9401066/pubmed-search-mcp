"""Correctness and resilience tests for citation-network traversal."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from pubmed_search.application.citation_network import (
    CitationBuildError,
    CitationNetworkConfig,
    CitationNetworkService,
    CitationTaskSupervisor,
)


def _article(pmid: str) -> dict[str, Any]:
    return {
        "pmid": pmid,
        "title": f"Paper {pmid}",
        "year": "2024",
        "journal": "Journal",
        "authors": ["Author"],
    }


class _CitationSource:
    def __init__(self, citing: dict[str, Any]) -> None:
        self.citing = citing

    async def fetch_details(self, pmids: list[str]) -> list[dict[str, Any]]:
        return [_article(pmids[0])]

    async def get_citing_articles(self, pmid: str, limit: int) -> list[dict[str, Any]]:
        outcome = self.citing.get(pmid, [])
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            outcome = await outcome()
        return list(outcome)[:limit]

    async def get_article_references(self, pmid: str, limit: int) -> list[dict[str, Any]]:
        return []


@pytest.mark.asyncio
async def test_convergent_paper_retains_every_shared_edge() -> None:
    source = _CitationSource(
        {
            "1": [_article("2"), _article("3")],
            "2": [_article("4")],
            "3": [_article("4")],
        }
    )
    result = await CitationNetworkService(source).build(
        "1",
        CitationNetworkConfig(depth=2, direction="forward", limit_per_level=5),
    )

    assert {node["pmid"] for node in result.nodes} == {"1", "2", "3", "4"}
    assert {(edge["source"], edge["target"]) for edge in result.edges} == {
        ("2", "1"),
        ("3", "1"),
        ("4", "2"),
        ("4", "3"),
    }
    assert result.coverage()["status"] == "complete"


@pytest.mark.asyncio
async def test_level_fetches_respect_concurrency_bound() -> None:
    active = 0
    maximum_active = 0

    async def delayed() -> list[dict[str, Any]]:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        try:
            await asyncio.sleep(0.01)
            return []
        finally:
            active -= 1

    source = _CitationSource(
        {
            "1": [_article(str(pmid)) for pmid in range(2, 10)],
            **{str(pmid): delayed for pmid in range(2, 10)},
        }
    )
    await CitationNetworkService(source).build(
        "1",
        CitationNetworkConfig(
            depth=2,
            direction="forward",
            limit_per_level=10,
            max_concurrency=3,
            timeout_seconds=1,
        ),
    )

    assert maximum_active == 3


@pytest.mark.asyncio
async def test_overall_deadline_returns_completed_partial_graph() -> None:
    async def fast() -> list[dict[str, Any]]:
        await asyncio.sleep(0.005)
        return [_article("4")]

    async def slow() -> list[dict[str, Any]]:
        await asyncio.sleep(1)
        return [_article("5")]

    source = _CitationSource(
        {
            "1": [_article("2"), _article("3")],
            "2": fast,
            "3": slow,
        }
    )
    result = await CitationNetworkService(source).build(
        "1",
        CitationNetworkConfig(
            depth=2,
            direction="forward",
            limit_per_level=5,
            timeout_seconds=0.05,
        ),
    )

    assert {node["pmid"] for node in result.nodes} == {"1", "2", "3", "4"}
    assert ("4", "2") in {(edge["source"], edge["target"]) for edge in result.edges}
    coverage = result.coverage()
    assert coverage["status"] == "partial"
    assert coverage["timed_out_expansions"] == 1
    assert any(error["kind"] == "overall_timeout" for error in coverage["source_errors"])


@pytest.mark.asyncio
async def test_source_exception_is_reported_without_discarding_other_branches() -> None:
    source = _CitationSource(
        {
            "1": [_article("2"), _article("3")],
            "2": RuntimeError("secret upstream details"),
            "3": [_article("4")],
        }
    )
    result = await CitationNetworkService(source).build(
        "1",
        CitationNetworkConfig(depth=2, direction="forward", limit_per_level=5),
    )

    assert {node["pmid"] for node in result.nodes} == {"1", "2", "3", "4"}
    coverage = result.coverage()
    assert coverage["status"] == "partial"
    assert coverage["source_errors"] == [
        {
            "source": "pubmed_citing",
            "direction": "forward",
            "level": 2,
            "parent_pmid": "2",
            "kind": "source_exception",
        }
    ]
    assert "secret upstream details" not in str(coverage)


@pytest.mark.asyncio
async def test_cancellation_swallowing_source_cannot_extend_overall_deadline() -> None:
    released = asyncio.Event()

    async def stubborn() -> list[dict[str, Any]]:
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            await asyncio.sleep(0.15)
            released.set()
        return [_article("3")]

    source = _CitationSource({"1": [_article("2")], "2": stubborn})
    supervisor = CitationTaskSupervisor(max_pending=2)
    started = time.monotonic()
    result = await CitationNetworkService(source, task_supervisor=supervisor).build(
        "1",
        CitationNetworkConfig(
            depth=2,
            direction="forward",
            limit_per_level=5,
            timeout_seconds=0.01,
        ),
    )
    elapsed = time.monotonic() - started

    assert elapsed < 0.08
    assert result.coverage()["status"] == "partial"
    assert supervisor.pending_count == 1
    await asyncio.wait_for(released.wait(), timeout=0.4)
    await asyncio.sleep(0)
    assert supervisor.pending_count == 0


@pytest.mark.asyncio
async def test_supervisor_bounds_repeated_cancellation_resistant_tasks() -> None:
    release = asyncio.Event()
    started = 0

    async def stubborn() -> list[dict[str, Any]]:
        nonlocal started
        started += 1
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await release.wait()
        return []

    supervisor = CitationTaskSupervisor(max_pending=2)
    source = _CitationSource({"1": stubborn})
    config = CitationNetworkConfig(
        depth=1,
        direction="forward",
        limit_per_level=1,
        timeout_seconds=0.01,
    )

    results = [await CitationNetworkService(source, task_supervisor=supervisor).build("1", config) for _ in range(2)]
    for _ in range(2):
        with pytest.raises(CitationBuildError, match="runtime_saturated"):
            await CitationNetworkService(source, task_supervisor=supervisor).build("1", config)

    assert started == 2
    assert supervisor.pending_count == 2
    assert all(result.coverage()["status"] == "partial" for result in results)

    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert supervisor.pending_count == 0


@pytest.mark.asyncio
async def test_supervisor_close_cancels_owned_tasks_with_bounded_grace() -> None:
    started = asyncio.Event()
    released = asyncio.Event()

    async def cooperative() -> None:
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            released.set()

    supervisor = CitationTaskSupervisor(max_pending=1)
    assert supervisor.schedule(cooperative(), name="citation-close-test") is not None
    await started.wait()

    await supervisor.aclose(grace_seconds=0.1)

    assert released.is_set()
    assert supervisor.pending_count == 0
