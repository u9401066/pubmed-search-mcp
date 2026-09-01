"""Regression coverage for server-owned external source lifecycles."""

from __future__ import annotations

import asyncio

from pubmed_search.container import ApplicationContainer
from pubmed_search.infrastructure.cache import get_entity_cache
from pubmed_search.infrastructure.pubtator import get_pubtator_client
from pubmed_search.infrastructure.pubtator.semantic_adapter import get_semantic_enhancer
from pubmed_search.infrastructure.sources import get_openalex_client
from pubmed_search.infrastructure.sources.runtime import SourceRuntime
from pubmed_search.presentation.mcp_server.server import _make_lifespan
from pubmed_search.presentation.mcp_server.tools.pipeline_tools import PipelineToolRuntime
from pubmed_search.presentation.mcp_server.tools.tool_session import ToolSessionRuntime, bind_tool_session_runtime
from pubmed_search.shared.async_utils import get_shared_async_client


async def test_overlapping_server_lifespans_close_only_their_owned_clients() -> None:
    runtime_a = SourceRuntime(contact_email="a@example.test")
    runtime_b = SourceRuntime(contact_email="b@example.test")
    tool_runtime_a = ToolSessionRuntime(source_runtime=runtime_a)
    tool_runtime_b = ToolSessionRuntime(source_runtime=runtime_b)

    with bind_tool_session_runtime(tool_runtime_a):
        openalex_a = get_openalex_client()
        pubtator_a = get_pubtator_client()
        enhancer_a = get_semantic_enhancer()
        entity_cache_a = get_entity_cache()
        shared_a = get_shared_async_client()
    with bind_tool_session_runtime(tool_runtime_b):
        openalex_b = get_openalex_client()
        pubtator_b = get_pubtator_client()
        enhancer_b = get_semantic_enhancer()
        entity_cache_b = get_entity_cache()
        shared_b = get_shared_async_client()

    assert openalex_a._email == "a@example.test"
    assert openalex_b._email == "b@example.test"
    assert openalex_a is not openalex_b
    assert pubtator_a is not pubtator_b
    assert enhancer_a is not enhancer_b
    assert entity_cache_a is not entity_cache_b
    assert shared_a is not shared_b
    pubtator_http_a = pubtator_a._client
    pubtator_http_b = pubtator_b._client

    container_a = ApplicationContainer()
    container_b = ApplicationContainer()
    lifespan_a = _make_lifespan(container_a, PipelineToolRuntime(base_store=None), runtime_a)
    lifespan_b = _make_lifespan(container_b, PipelineToolRuntime(base_store=None), runtime_b)
    async with lifespan_b(object()):  # type: ignore[arg-type]
        async with lifespan_a(object()):  # type: ignore[arg-type]
            pass
        assert openalex_a._client.is_closed
        assert pubtator_http_a.is_closed
        assert shared_a.is_closed
        assert not openalex_b._client.is_closed
        assert not pubtator_http_b.is_closed
        assert not shared_b.is_closed


def test_source_runtime_can_be_reused_across_sequential_event_loops() -> None:
    runtime = SourceRuntime(contact_email="loop@example.test")

    async def _cycle() -> object:
        with bind_tool_session_runtime(ToolSessionRuntime(source_runtime=runtime)):
            client = get_pubtator_client()
            http_client = client._client
        await runtime.close()
        assert http_client.is_closed
        return client

    first = asyncio.run(_cycle())
    second = asyncio.run(_cycle())
    assert first is not second
