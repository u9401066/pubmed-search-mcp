"""Tests for browser-session broker client safety checks."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock

import httpx

from pubmed_search.infrastructure.sources.browser_session import BrowserSessionConfig, BrowserSessionFetcher


async def test_broker_json_success_must_contain_pdf_magic_bytes() -> None:
    fetcher = BrowserSessionFetcher(
        BrowserSessionConfig(
            enabled=True,
            broker_url="http://127.0.0.1:8765/fetch",
            token="secret",
            allowed_hosts=["publisher.example"],
        )
    )
    response = httpx.Response(
        200,
        json={
            "success": True,
            "content_b64": base64.b64encode(b"<html>not pdf</html>").decode("ascii"),
            "content_type": "application/pdf",
            "final_url": "https://publisher.example/not-pdf",
        },
        request=httpx.Request("POST", "http://127.0.0.1:8765/fetch"),
    )
    fetcher._post_to_broker = AsyncMock(return_value=response)  # type: ignore[method-assign]

    result = await fetcher.fetch_pdf("https://publisher.example/article")

    assert result.success is False
    assert "not a PDF" in (result.error or "")


async def test_broker_rejects_oversized_or_malformed_pdf_payloads():
    fetcher = BrowserSessionFetcher(
        BrowserSessionConfig(
            enabled=True,
            broker_url="http://127.0.0.1:8765/fetch",
            token="secret",
            allowed_hosts=["publisher.example"],
            max_bytes=8,
        )
    )
    request = httpx.Request("POST", fetcher.config.broker_url)
    responses = [
        httpx.Response(200, content=b"%PDF-" + b"x" * 20, headers={"content-type": "application/pdf"}, request=request),
        httpx.Response(
            200, json={"success": True, "content_b64": base64.b64encode(b"%PDF-" + b"x" * 20).decode()}, request=request
        ),
        httpx.Response(200, json=[], request=request),
        httpx.Response(200, text="bad json", request=request),
    ]
    for response in responses:
        fetcher._post_to_broker = AsyncMock(return_value=response)  # type: ignore[method-assign]
        result = await fetcher.fetch_pdf("https://publisher.example/article")
        assert not result.success
        assert result.content is None


async def test_raw_broker_pdf_never_uses_local_broker_url_as_article_source():
    fetcher = BrowserSessionFetcher(
        BrowserSessionConfig(
            enabled=True,
            broker_url="http://127.0.0.1:8765/fetch",
            token="secret",
            allowed_hosts=["publisher.example"],
        )
    )
    fetcher._post_to_broker = AsyncMock(
        return_value=httpx.Response(  # type: ignore[method-assign]
            200,
            content=b"%PDF-1.4",
            headers={"content-type": "application/pdf"},
            request=httpx.Request("POST", fetcher.config.broker_url),
        )
    )
    result = await fetcher.fetch_pdf("https://publisher.example/article")
    assert result.success
    assert result.final_url is None  # Raw transport provides no resolved publisher URL.
