"""Regression tests for bounded source API response streaming."""

from __future__ import annotations

import gzip
from typing import TYPE_CHECKING

import httpx
import pytest

from pubmed_search.infrastructure.sources.base_client import (
    MAX_API_RESPONSE_BYTES,
    APIResponseTooLargeError,
    BaseAPIClient,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable


class _TrackingStream(httpx.AsyncByteStream):
    def __init__(self, *chunks: bytes) -> None:
        self.chunks = chunks
        self.iterations = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.iterations += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class _BoundedClient(BaseAPIClient):
    _service_name = "Bounded Test API"
    _MAX_RETRIES = 0

    def __init__(
        self,
        handler: Callable[[httpx.Request], httpx.Response],
        *,
        max_response_bytes: int,
    ) -> None:
        super().__init__(
            base_url="https://api.example.test",
            min_interval=0,
            max_response_bytes=max_response_bytes,
        )
        self._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_rejects_declared_oversize_before_reading_stream() -> None:
    stream = _TrackingStream(b"not-read")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": "9"},
            stream=stream,
            request=request,
        )

    client = _BoundedClient(handler, max_response_bytes=8)
    try:
        with pytest.raises(APIResponseTooLargeError, match=r"Bounded Test API response exceeded the 8-byte limit"):
            await client._make_request("/records?secret=do-not-leak")
    finally:
        await client.close()

    assert stream.iterations == 0
    assert stream.closed is True


async def test_rejects_chunked_body_when_stream_crosses_limit() -> None:
    stream = _TrackingStream(b"1234", b"56789", b"must-not-be-read")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream, request=request)

    client = _BoundedClient(handler, max_response_bytes=8)
    try:
        with pytest.raises(APIResponseTooLargeError) as error:
            await client._make_request("/records?token=sentinel-secret")
    finally:
        await client.close()

    assert stream.iterations == 2
    assert stream.closed is True
    assert "sentinel-secret" not in str(error.value)


async def test_decoded_bytes_enforce_limit_for_compressed_response() -> None:
    compressed = gzip.compress(b"x" * 128)
    assert len(compressed) < 32
    stream = _TrackingStream(compressed)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Encoding": "gzip",
                "Content-Length": str(len(compressed)),
            },
            stream=stream,
            request=request,
        )

    client = _BoundedClient(handler, max_response_bytes=32)
    try:
        with pytest.raises(APIResponseTooLargeError):
            await client._make_request("/compressed")
    finally:
        await client.close()

    assert stream.closed is True


async def test_redirect_chain_shares_one_byte_budget() -> None:
    streams = [_TrackingStream(b"1234"), _TrackingStream(b"56789")]
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/start":
            return httpx.Response(
                302,
                headers={"Location": "/finish", "Content-Length": "4"},
                stream=streams[0],
                request=request,
            )
        return httpx.Response(200, stream=streams[1], request=request)

    client = _BoundedClient(handler, max_response_bytes=8)
    try:
        with pytest.raises(APIResponseTooLargeError):
            await client._make_request("/start")
    finally:
        await client.close()

    assert requested_paths == ["/start", "/finish"]
    assert all(stream.closed for stream in streams)


async def test_exact_limit_returns_normal_parsed_response() -> None:
    payload = b'{"ok":1}'
    stream = _TrackingStream(payload)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": str(len(payload))},
            stream=stream,
            request=request,
        )

    client = _BoundedClient(handler, max_response_bytes=len(payload))
    try:
        assert await client._make_request("/records") == {"ok": 1}
    finally:
        await client.close()

    assert stream.closed is True


async def test_oversize_failure_never_exposes_response_details(caplog: pytest.LogCaptureFixture) -> None:
    secret_body = b"private-upstream-body"
    stream = _TrackingStream(secret_body)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream, request=request)

    client = _BoundedClient(handler, max_response_bytes=4)
    try:
        with pytest.raises(APIResponseTooLargeError):
            await client._make_request("/records?token=private-query")
    finally:
        await client.close()

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "private-upstream-body" not in messages
    assert "private-query" not in messages


@pytest.mark.parametrize("value", [0, MAX_API_RESPONSE_BYTES + 1])
def test_response_limit_cannot_disable_or_exceed_hard_cap(value: int) -> None:
    with pytest.raises(ValueError, match="max_response_bytes"):
        BaseAPIClient(max_response_bytes=value)


def test_response_limit_rejects_bool() -> None:
    with pytest.raises(TypeError, match="max_response_bytes"):
        BaseAPIClient(max_response_bytes=True)


async def test_empty_json_post_keeps_method_and_body() -> None:
    observed = []

    def handler(request):
        observed.append((request.method, request.content))
        return httpx.Response(200, json={"ok": True})

    client = _BoundedClient(handler, max_response_bytes=64)
    try:
        await client._make_request("/batch", method="POST", data={})
    finally:
        await client.close()
    assert observed == [("POST", b"{}")]


async def test_custom_credentials_are_not_forwarded_to_another_origin() -> None:
    observed = []

    def handler(request):
        observed.append(request)
        if request.url.host == "api.example.test":
            return httpx.Response(302, headers={"Location": "https://other.example.test/finish"})
        return httpx.Response(200, json={"ok": True})

    client = _BoundedClient(handler, max_response_bytes=64)
    try:
        await client._make_request(
            "/start", headers={"X-ApiKey": "test-private-key", "X-ELS-Insttoken": "test-private-token"}
        )
    finally:
        await client.close()
    assert "x-apikey" in observed[0].headers
    assert "x-apikey" not in observed[1].headers
    assert "x-els-insttoken" not in observed[1].headers
