from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from pubmed_search.infrastructure.ncbi.citation_exporter import NCBICitationExporter, get_exporter
from pubmed_search.infrastructure.sources.runtime import SourceRuntime, bind_source_runtime


@pytest.mark.asyncio
async def test_citation_exporter_client_is_owned_and_closed_by_one_source_runtime() -> None:
    runtime_a = SourceRuntime(contact_email="a@example.org")
    runtime_b = SourceRuntime(contact_email="b@example.org")

    with bind_source_runtime(runtime_a):
        exporter_a = get_exporter()
        assert get_exporter() is exporter_a
    with bind_source_runtime(runtime_b):
        exporter_b = get_exporter()

    client_a = AsyncMock()
    client_a.is_closed = False
    exporter_a._client = client_a
    client_b = AsyncMock()
    client_b.is_closed = False
    exporter_b._client = client_b

    assert exporter_a is not exporter_b
    await runtime_a.close()

    client_a.aclose.assert_awaited_once()
    client_b.aclose.assert_not_awaited()

    await runtime_b.close()
    client_b.aclose.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure, expected_error",
    [
        (
            httpx.HTTPStatusError(
                "secret response /srv/private/export.txt",
                request=httpx.Request("GET", "https://example.invalid/?token=secret"),
                response=httpx.Response(
                    503,
                    request=httpx.Request("GET", "https://example.invalid/?token=secret"),
                    text="api_key=secret /srv/private/export.txt",
                ),
            ),
            "Citation API request failed with HTTP 503",
        ),
        (
            httpx.RequestError(
                "https://example.invalid/?token=secret /srv/private/export.txt",
                request=httpx.Request("GET", "https://example.invalid/?token=secret"),
            ),
            "Citation API request failed",
        ),
        (RuntimeError("api_key=secret /srv/private/export.txt"), "Citation export failed"),
    ],
)
async def test_citation_exporter_never_exposes_upstream_failure_details(
    failure: Exception,
    expected_error: str,
) -> None:
    exporter = NCBICitationExporter()
    with patch.object(exporter._transport_kernel, "execute", new=AsyncMock(side_effect=failure)):
        result = await exporter.export_citations(["12345"])

    assert result.success is False
    assert result.error == expected_error
    assert "secret" not in (result.error or "")
    assert "/srv/private" not in (result.error or "")
