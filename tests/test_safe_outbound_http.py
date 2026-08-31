"""Security regression tests for user-influenced outbound HTTP fetches."""

from __future__ import annotations

import gzip
import logging
import socket
from typing import TYPE_CHECKING

import httpx
import pytest

from pubmed_search.infrastructure.http import safe_outbound
from pubmed_search.infrastructure.http.safe_outbound import (
    OutboundResponseTooLargeError,
    SafeFetchPolicy,
    UnsafeOutboundURLError,
    fetch_public_url,
    redact_url_for_log,
    validate_public_url,
)
from pubmed_search.infrastructure.sources.institutional_fetch import _probe_url

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


async def _public_resolver(_host: str, _port: int) -> tuple[str, ...]:
    return ("93.184.216.34",)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://0.0.0.0/",
        "http://224.0.0.1/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[2002:7f00:1::]/",
        "http://[64:ff9b::7f00:1]/",
    ],
)
async def test_literal_non_public_addresses_are_rejected(url: str) -> None:
    with pytest.raises(UnsafeOutboundURLError, match="non-public"):
        await validate_public_url(url, resolver=_public_resolver)


async def test_dns_answer_must_contain_only_public_addresses() -> None:
    async def mixed_resolver(_host: str, _port: int) -> tuple[str, ...]:
        return ("93.184.216.34", "10.0.0.8")

    with pytest.raises(UnsafeOutboundURLError, match="non-public"):
        await validate_public_url("https://papers.example/article", resolver=mixed_resolver)


async def test_non_default_ports_and_credentials_are_rejected() -> None:
    with pytest.raises(UnsafeOutboundURLError, match="port"):
        await validate_public_url("https://papers.example:8443/article", resolver=_public_resolver)
    with pytest.raises(UnsafeOutboundURLError, match="credentials"):
        await validate_public_url("https://user:secret@papers.example/article", resolver=_public_resolver)


async def test_public_url_is_streamed_successfully() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "papers.example"
        assert request.extensions["sni_hostname"] == "papers.example"
        return httpx.Response(200, content=b"bounded", request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch_public_url(
            "https://papers.example/article?token=secret",
            policy=SafeFetchPolicy(max_bytes=64),
            resolver=_public_resolver,
            client=client,
        )

    assert result.response.content == b"bounded"
    assert str(result.response.url) == "https://papers.example/article?token=secret"
    assert result.redirect_chain == ("https://papers.example/…",)


async def test_redirect_to_private_address_is_blocked_before_second_request() -> None:
    requested: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append((request.url.host, request.headers["host"]))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UnsafeOutboundURLError, match="non-public"):
            await fetch_public_url(
                "https://papers.example/start",
                policy=SafeFetchPolicy(max_bytes=64),
                resolver=_public_resolver,
                client=client,
            )

    assert requested == [("93.184.216.34", "papers.example")]


async def test_content_length_over_limit_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-length": "1000"},
            stream=httpx.ByteStream(b"small"),
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(OutboundResponseTooLargeError):
            await fetch_public_url(
                "https://papers.example/large",
                policy=SafeFetchPolicy(max_bytes=32),
                resolver=_public_resolver,
                client=client,
            )


async def test_compressed_response_is_rejected_before_decompression() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            content=gzip.compress(b"not-read-as-a-compressed-body"),
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(safe_outbound.SafeOutboundError, match="Encoded"):
            await fetch_public_url(
                "https://papers.example/compressed",
                policy=SafeFetchPolicy(max_bytes=64),
                resolver=_public_resolver,
                client=client,
            )


class _ChunkedBody(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"a" * 20
        yield b"b" * 20


async def test_chunked_body_over_limit_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_ChunkedBody(), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(OutboundResponseTooLargeError):
            await fetch_public_url(
                "https://papers.example/chunked",
                policy=SafeFetchPolicy(max_bytes=32),
                resolver=_public_resolver,
                client=client,
            )


class _PrivatePeer:
    def get_extra_info(self, _name: str) -> tuple[str, int]:
        return ("127.0.0.1", 443)


async def test_connected_private_peer_is_rejected_when_transport_exposes_it() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"must not be accepted",
            extensions={"network_stream": _PrivatePeer()},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UnsafeOutboundURLError, match="peer"):
            await fetch_public_url(
                "https://papers.example/content",
                policy=SafeFetchPolicy(max_bytes=64),
                resolver=_public_resolver,
                client=client,
            )


async def test_query_secret_is_absent_from_logs_and_redirect_chain(caplog: pytest.LogCaptureFixture) -> None:
    sentinel = "TOPSECRET_QUERY_SENTINEL"
    previous_httpx = logging.getLogger("httpx").level
    previous_httpcore = logging.getLogger("httpcore").level
    try:
        caplog.set_level(logging.INFO)
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"ok", request=request))
        async with httpx.AsyncClient(transport=transport) as client:
            result = await fetch_public_url(
                f"https://papers.example/image.png?signature={sentinel}",
                policy=SafeFetchPolicy(max_bytes=64),
                resolver=_public_resolver,
                client=client,
            )

        assert sentinel not in caplog.text
        assert sentinel not in "".join(result.redirect_chain)
        assert redact_url_for_log(f"https://user:{sentinel}@papers.example/private/{sentinel}?x={sentinel}") == (
            "https://papers.example/…"
        )
    finally:
        logging.getLogger("httpx").setLevel(previous_httpx)
        logging.getLogger("httpcore").setLevel(previous_httpcore)


async def test_sensitive_headers_and_cookies_do_not_cross_origins() -> None:
    seen: list[tuple[str, str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (
                request.url.host,
                request.headers["host"],
                request.headers.get("authorization", ""),
                request.headers.get("cookie", ""),
            )
        )
        if request.headers["host"] == "papers.example":
            return httpx.Response(302, headers={"location": "https://cdn.example/image.png"}, request=request)
        return httpx.Response(200, content=b"ok", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await fetch_public_url(
            "https://papers.example/start",
            policy=SafeFetchPolicy(max_bytes=64),
            headers={"Authorization": "Bearer private", "cookie": "must-not-win=yes"},
            cookies={"session": "private"},
            resolver=_public_resolver,
            client=client,
        )

    assert seen == [
        ("93.184.216.34", "papers.example", "Bearer private", "session=private"),
        ("93.184.216.34", "cdn.example", "", ""),
    ]


async def test_response_cookies_are_not_retained_by_shared_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"set-cookie": "publisher_session=secret; Path=/; Secure"},
            content=b"ok",
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await fetch_public_url(
            "https://papers.example/content",
            policy=SafeFetchPolicy(max_bytes=64),
            resolver=_public_resolver,
            client=client,
        )
        assert list(client.cookies.jar) == []


async def test_institutional_soft_redirect_to_private_address_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[str] = []

    def fake_getaddrinfo(host: str, port: int, **_kwargs: object) -> list[tuple[object, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.headers["host"])
        if request.headers["host"] == "doi.org":
            target = "http%3A%2F%2F127.0.0.1%2Finternal"
            return httpx.Response(
                302,
                headers={"location": f"https://linkinghub.elsevier.com/select?Redirect={target}"},
                request=request,
            )
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html></html>", request=request)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(safe_outbound, "get_shared_async_client", lambda: client)
        response, chain, error = await _probe_url("https://doi.org/10.1000/test")

    assert response is None
    assert error and "non-public" in error
    assert requested == ["doi.org", "linkinghub.elsevier.com"]
    assert all("127.0.0.1" not in item for item in chain)
