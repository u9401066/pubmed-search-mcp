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
