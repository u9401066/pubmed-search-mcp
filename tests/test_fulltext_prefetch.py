"""Behavioral contracts for bounded background XML and demand reuse."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.fulltext.cache import FulltextCache, FulltextCacheError
from pubmed_search.application.unified.request import normalize_unified_search_request
from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.presentation.mcp_server.tools.fulltext_runtime import (
    get_cached_fulltext_xml,
    prefetch_search_fulltext,
)
from pubmed_search.presentation.mcp_server.tools.tool_session import ToolSessionRuntime, bind_tool_session_runtime
from pubmed_search.shared.tenancy import ANONYMOUS_HTTP_TENANT, TenantIdentity, bind_tenant


def _article(pmc: str = "PMC123", *, oa: bool | None = True) -> UnifiedArticle:
    return UnifiedArticle(title="Evidence", pmc=pmc, is_open_access=oa, primary_source="pubmed")


async def _settle() -> None:
    # Advance callbacks without wall-clock sleeps; provider events control the races.
    for _ in range(8):
        await asyncio.sleep(0)


async def test_prefetch_returns_without_io_and_demand_joins_then_reuses_xml() -> None:
    cache = FulltextCache()
    started, release = asyncio.Event(), asyncio.Event()

    async def load(_: str) -> str:
        started.set()
        await release.wait()
        return "<article>complete XML</article>"

    speculative = AsyncMock(side_effect=load)
    demand = AsyncMock(side_effect=AssertionError("duplicate upstream download"))
    try:
        snapshot = cache.prefetch([_article()], tenant="a", fetch=speculative)
        assert snapshot["articles"][0]["status"] == "scheduled"
        speculative.assert_not_awaited()
        await started.wait()
        request = asyncio.create_task(cache.get("PMC123", tenant="a", fetch=demand))
        await _settle()
        assert not request.done()
        release.set()
        assert await request == "<article>complete XML</article>"
        assert await cache.get("PMC123", tenant="a", fetch=demand) == "<article>complete XML</article>"
        speculative.assert_awaited_once_with("PMC123")
        demand.assert_not_awaited()
        assert cache.prefetch([_article()], tenant="a", fetch=speculative)["articles"][0]["status"] == "cached"
    finally:
        await cache.aclose()


async def test_background_selects_only_top_three_and_one_source_at_a_time() -> None:
    cache = FulltextCache()
    release = asyncio.Event()
    calls: list[str] = []

    async def load(pmcid: str) -> str:
        calls.append(pmcid)
        await release.wait()
        return "<article/>"

    try:
        first = cache.prefetch([_article(f"PMC{i}") for i in range(1, 6)], tenant="a", fetch=load)
        assert len(first["articles"]) == 3
        repeated = cache.prefetch([_article("PMC1")], tenant="a", fetch=load)
        assert repeated["articles"][0]["status"] == "in_progress"
        overflow = cache.prefetch([_article("PMC99")], tenant="b", fetch=load)
        assert overflow["articles"][0]["status"] == "capacity_limited"
        await _settle()
        assert calls == ["PMC1"]
        release.set()
        await asyncio.gather(*(cache.get(f"PMC{i}", tenant="a", fetch=load) for i in range(1, 4)))
        assert calls == ["PMC1", "PMC2", "PMC3"]
    finally:
        await cache.aclose()


@pytest.mark.parametrize("start_queue", [False, True])
async def test_queued_prefetch_promotes_demand_without_waiting_or_duplicate_fetch(start_queue: bool) -> None:
    cache = FulltextCache()
    background_started, demand_started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    background_calls: list[str] = []

    async def speculative(pmcid: str) -> str:
        background_calls.append(pmcid)
        background_started.set()
        await release.wait()
        return "background XML"

    async def foreground(_: str) -> str:
        demand_started.set()
        await release.wait()
        return "requested XML"

    demand = AsyncMock(side_effect=foreground)
    try:
        cache.prefetch([_article("PMC1"), _article("PMC2")], tenant="a", fetch=speculative)
        if start_queue:
            await background_started.wait()
        first = asyncio.create_task(cache.get("PMC2", tenant="a", fetch=demand))
        second = asyncio.create_task(cache.get("PMC2", tenant="a", fetch=demand))
        await asyncio.wait_for(demand_started.wait(), timeout=1)
        assert not release.is_set()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        assert await second == "requested XML"
        assert await cache.get("PMC2", tenant="a", fetch=demand) == "requested XML"
        await cache.get("PMC1", tenant="a", fetch=speculative)
        demand.assert_awaited_once_with("PMC2")
        assert background_calls == ["PMC1"]
    finally:
        release.set()
        await cache.aclose()


async def test_read_handoff_uses_actual_operator_limit_and_native_tool_arguments() -> None:
    runtime = ToolSessionRuntime()
    fetch = AsyncMock(return_value="xml")
    try:
        with (
            bind_tool_session_runtime(runtime),
            bind_tenant(TenantIdentity()),
            patch("pubmed_search.presentation.mcp_server.tools.fulltext_runtime.fetch_prefetch_xml", fetch),
            patch(
                "pubmed_search.presentation.mcp_server.tools.fulltext_runtime.load_settings",
                return_value=SimpleNamespace(fulltext_prefetch_limit=1),
            ),
        ):
            snapshot = prefetch_search_fulltext([_article("PMC1"), _article("PMC2")])
            assert snapshot["max_articles"] == 1
            assert len(snapshot["articles"]) == 1
            assert snapshot["articles"][0]["read_request"] == {
                "tool": "get_fulltext",
                "arguments": {
                    "source": {"kind": "pmcid", "value": "PMC1"},
                    "include_pdf_links": False,
                    "output_format": "json",
                },
            }
    finally:
        await runtime.fulltext_cache.aclose()


async def test_unknown_ids_closed_access_and_duplicates_do_not_expand_selection() -> None:
    cache = FulltextCache()
    fetch = AsyncMock(return_value="<article/>")
    try:
        snapshot = cache.prefetch(
            [_article(""), _article("PMC2", oa=False), _article("broken"), _article("PMC4")],
            tenant="a",
            fetch=fetch,
        )
        assert snapshot["articles"] == []
        fetch.assert_not_awaited()
        rows = cache.prefetch([_article(), _article(), _article("PMC2")], tenant="a", fetch=fetch)["articles"]
        assert len(rows) == 2
    finally:
        await cache.aclose()


async def test_cancelling_one_reader_preserves_the_other_and_cancels_abandoned_demand() -> None:
    cache = FulltextCache()
    started, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def load(_: str) -> str:
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "xml"

    fetch = AsyncMock(side_effect=load)
    try:
        first = asyncio.create_task(cache.get("PMC1", tenant="a", fetch=fetch))
        second = asyncio.create_task(cache.get("PMC1", tenant="a", fetch=fetch))
        await started.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not cancelled.is_set()
        release.set()
        assert await second == "xml"
        fetch.assert_awaited_once()
        release.clear()
        started.clear()
        abandoned = asyncio.create_task(cache.get("PMC2", tenant="a", fetch=fetch))
        await started.wait()
        abandoned.cancel()
        with pytest.raises(asyncio.CancelledError):
            await abandoned
        await asyncio.wait_for(cancelled.wait(), timeout=1)
    finally:
        await cache.aclose()


async def test_failed_prefetch_has_cooldown_but_explicit_read_retries_once() -> None:
    cache = FulltextCache()
    speculative = AsyncMock(side_effect=RuntimeError("private provider failure"))
    demand = AsyncMock(return_value="xml")
    try:
        cache.prefetch([_article()], tenant="a", fetch=speculative)
        await _settle()
        snapshot = cache.prefetch([_article()], tenant="a", fetch=speculative)
        assert snapshot["articles"][0]["status"] == "cooldown"
        assert "private" not in json.dumps(snapshot)
        assert await cache.get("PMC123", tenant="a", fetch=demand) == "xml"
        speculative.assert_awaited_once()
        demand.assert_awaited_once()
    finally:
        await cache.aclose()


async def test_ttl_negative_results_and_tenant_isolation() -> None:
    now = [100.0]
    cache = FulltextCache(clock=lambda: now[0], ttl_seconds=10, negative_ttl_seconds=2)
    fetch = AsyncMock(side_effect=[None, "tenant-b", "tenant-a", "refreshed"])
    try:
        assert await cache.get("PMC1", tenant="a", fetch=fetch) is None
        assert await cache.get("PMC1", tenant="a", fetch=fetch) is None
        assert await cache.get("PMC1", tenant="b", fetch=fetch) == "tenant-b"
        now[0] += 3
        assert await cache.get("PMC1", tenant="a", fetch=fetch) == "tenant-a"
        now[0] += 11
        assert await cache.get("PMC1", tenant="a", fetch=fetch) == "refreshed"
        assert fetch.await_count == 4
    finally:
        await cache.aclose()


async def test_cache_lru_byte_bound_and_large_demand_result_not_retained() -> None:
    cache = FulltextCache(max_entries=2, max_bytes=8)
    fetch = AsyncMock(return_value="1234")
    try:
        for pmcid in ("PMC1", "PMC2", "PMC1", "PMC3", "PMC1"):
            assert await cache.get(pmcid, tenant="a", fetch=fetch) == "1234"
        assert fetch.await_count == 3
        await cache.get("PMC2", tenant="a", fetch=fetch)
        assert fetch.await_count == 4
        large = AsyncMock(return_value="too large for this cache")
        await cache.get("PMC99", tenant="a", fetch=large)
        await cache.get("PMC99", tenant="a", fetch=large)
        assert large.await_count == 2
    finally:
        await cache.aclose()


async def test_timeout_contains_cancellation_resistant_work_and_shutdown_prevents_late_cache() -> None:
    cache = FulltextCache(prefetch_timeout_seconds=0.02)
    cancelled, release = asyncio.Event(), asyncio.Event()
    calls: list[str] = []

    async def stubborn(pmcid: str) -> str:
        calls.append(pmcid)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    continue
        return "late XML"

    try:
        cache.prefetch([_article("PMC1"), _article("PMC2")], tenant="a", fetch=stubborn)
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        await asyncio.sleep(0.03)
        assert calls == ["PMC1"]
        assert cache.prefetch([_article("PMC1")], tenant="a", fetch=stubborn)["articles"][0]["status"] == "cooldown"
        await asyncio.wait_for(cache.aclose(), timeout=0.5)
        assert cache.prefetch([_article("PMC3")], tenant="a", fetch=stubborn)["articles"][0]["status"] == "disabled"
        with pytest.raises(FulltextCacheError, match="closed"):
            await cache.get("PMC1", tenant="a", fetch=stubborn)
    finally:
        release.set()
        await _settle()
        await cache.aclose()


@pytest.mark.parametrize("reason", ["anonymous", "operator", "source"])
async def test_prefetch_respects_identity_and_operator_source_switches(reason: str) -> None:
    runtime = ToolSessionRuntime()
    tenant = ANONYMOUS_HTTP_TENANT if reason == "anonymous" else TenantIdentity()
    fetch = AsyncMock(return_value="xml")
    with (
        bind_tool_session_runtime(runtime),
        bind_tenant(tenant),
        patch("pubmed_search.presentation.mcp_server.tools.fulltext_runtime.fetch_prefetch_xml", fetch),
        patch(
            "pubmed_search.presentation.mcp_server.tools.fulltext_runtime.load_settings",
            return_value=SimpleNamespace(fulltext_prefetch_limit=0 if reason == "operator" else 3),
        ),
        patch(
            "pubmed_search.presentation.mcp_server.tools.fulltext_runtime.get_source_registry",
            return_value=SimpleNamespace(is_enabled=lambda _: reason != "source"),
        ),
    ):
        snapshot = prefetch_search_fulltext([_article()])
        assert snapshot["status"] == "disabled"
        fetch.assert_not_awaited()
    await runtime.fulltext_cache.aclose()


async def test_two_server_runtimes_and_tenants_never_share_xml() -> None:
    first, second = ToolSessionRuntime(), ToolSessionRuntime()
    fetch = AsyncMock(side_effect=["first-a", "first-b", "second-a"])
    try:
        with bind_tool_session_runtime(first), bind_tenant(TenantIdentity.for_principal("a")):
            assert await get_cached_fulltext_xml("PMC1", fetch) == "first-a"
        with bind_tool_session_runtime(first), bind_tenant(TenantIdentity.for_principal("b")):
            assert await get_cached_fulltext_xml("PMC1", fetch) == "first-b"
        with bind_tool_session_runtime(second), bind_tenant(TenantIdentity.for_principal("a")):
            assert await get_cached_fulltext_xml("PMC1", fetch) == "second-a"
        with bind_tool_session_runtime(first), bind_tenant(TenantIdentity.for_principal("a")):
            assert await get_cached_fulltext_xml("PMC1", fetch) == "first-a"
        assert fetch.await_count == 3
    finally:
        await first.fulltext_cache.aclose()
        await second.fulltext_cache.aclose()


def test_prefetch_request_is_explicit_and_pipeline_combination_rejected() -> None:
    assert normalize_unified_search_request(query="sedation").fulltext == "off"
    assert normalize_unified_search_request(query="sedation", fulltext="prefetch").fulltext == "prefetch"
    with pytest.raises(ValueError, match="pipeline"):
        normalize_unified_search_request(query="sedation", fulltext="prefetch", pipeline="template: pico")


async def test_search_use_case_schedules_after_ranking_without_awaiting_provider() -> None:
    from pubmed_search.application.unified.use_case import UnifiedSearchUseCase

    execution = SimpleNamespace(ranked=[_article()], enrichment_metadata={})
    prefetch = MagicMock(return_value={"articles": [{"status": "scheduled"}]})
    use_case = UnifiedSearchUseCase(
        planner=AsyncMock(),
        executor=AsyncMock(return_value=execution),
        source_broker=MagicMock(),
        enrichment=MagicMock(),
        analyzer_factory=MagicMock(),
        enhancer_factory=MagicMock(),
        source_registry_factory=MagicMock(),
        fulltext_prefetch=prefetch,
    )
    await use_case.execute(normalize_unified_search_request(query="sedation"), progress=AsyncMock())
    prefetch.assert_not_called()
    await use_case.execute(
        normalize_unified_search_request(query="sedation", fulltext="prefetch"), progress=AsyncMock()
    )
    prefetch.assert_called_once_with(execution.ranked)
    assert execution.enrichment_metadata["fulltext_prefetch"]["articles"][0]["status"] == "scheduled"
    prefetch.side_effect = RuntimeError("private credentials")
    await use_case.execute(
        normalize_unified_search_request(query="sedation", fulltext="prefetch"), progress=AsyncMock()
    )
    assert execution.enrichment_metadata["fulltext_prefetch"]["status"] == "unavailable"
    assert "credentials" not in str(execution.enrichment_metadata)


async def test_cached_xml_preserves_section_selection_and_skips_unrequested_link_lookup() -> None:
    from pubmed_search.application.fulltext import FulltextRequest, FulltextService

    cache = FulltextCache()
    provider = MagicMock()
    provider.get_article = AsyncMock(return_value={"pmc_id": "PMC123", "doi": "10.1000/test"})
    provider.get_fulltext_xml = AsyncMock(return_value="complete XML")
    provider.parse_fulltext_xml.return_value = {
        "title": "Article",
        "sections": [
            {"title": "Methods", "content": "Method evidence"},
            {"title": "Results", "content": "Result evidence"},
        ],
    }
    unpaywall = AsyncMock()
    unpaywall.get_oa_status.return_value = None

    async def structured(pmcid: str) -> str | None:
        return await cache.get(pmcid, tenant="a", fetch=provider.get_fulltext_xml)

    service = FulltextService(
        europe_pmc_client_factory=lambda: provider,
        unpaywall_client_factory=lambda: unpaywall,
        core_client_factory=MagicMock(),
        downloader_factory=MagicMock(),
        structured_xml_fetcher=structured,
    )
    try:
        methods = await service.retrieve(FulltextRequest(pmid="123", sections="methods", include_pdf_links=False))
        results = await service.retrieve(FulltextRequest(pmid="123", sections="results", include_pdf_links=False))
        assert methods.content_sections == [{"title": "Methods", "content": "Method evidence"}]
        assert results.content_sections == [{"title": "Results", "content": "Result evidence"}]
        provider.get_fulltext_xml.assert_awaited_once()
        unpaywall.get_oa_status.assert_not_awaited()
        await service.retrieve(FulltextRequest(pmid="123"))
        unpaywall.get_oa_status.assert_awaited_once_with("10.1000/test")
    finally:
        await cache.aclose()


@pytest.mark.parametrize("status", [429, 503])
async def test_prefetch_transport_never_retries_and_shares_provider_budget(status: int) -> None:
    import httpx

    from pubmed_search.infrastructure.sources.europe_pmc import EuropePMCClient
    from pubmed_search.infrastructure.sources.fulltext_prefetch import _PrefetchClient
    from pubmed_search.infrastructure.sources.runtime import SourceRuntime
    from pubmed_search.shared.async_utils import RetryableOperationError

    runtime = SourceRuntime()
    with bind_tool_session_runtime(ToolSessionRuntime(source_runtime=runtime)):
        speculative = _PrefetchClient()
        demand = EuropePMCClient()
        try:
            assert speculative._rate_limiter_name == demand._rate_limiter_name
            assert speculative._concurrency_name == demand._concurrency_name
            response = httpx.Response(
                status, headers={"Retry-After": "0"}, request=httpx.Request("GET", "https://example.test")
            )
            with patch.object(speculative, "_execute_request", new=AsyncMock(return_value=response)) as request:
                with pytest.raises(RetryableOperationError):
                    await speculative.get_fulltext_xml("PMC123")
            request.assert_awaited_once()
        finally:
            await speculative.close()
            await demand.close()
            await runtime.close()


async def test_prefetch_transport_rejects_large_xml_body() -> None:
    import httpx

    from pubmed_search.application.fulltext.cache import MAX_XML_CACHE_ITEM_BYTES
    from pubmed_search.infrastructure.sources.base_client import APIResponseTooLargeError
    from pubmed_search.infrastructure.sources.fulltext_prefetch import _PrefetchClient

    client = _PrefetchClient()
    await client.close()
    body = b"x" * (MAX_XML_CACHE_ITEM_BYTES + 1)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body)))
    try:
        with pytest.raises(APIResponseTooLargeError):
            await client.get_fulltext_xml("PMC123")
    finally:
        await client.close()
