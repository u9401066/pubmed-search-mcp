"""Outbound transport logs must not expose biomedical queries or credentials."""

from __future__ import annotations

import logging

import httpx

from pubmed_search.shared.logging_utils import harden_http_client_logging


def test_httpx_info_request_url_is_suppressed(caplog) -> None:  # type: ignore[no-untyped-def]
    httpx_logger = logging.getLogger("httpx")
    httpcore_logger = logging.getLogger("httpcore")
    previous_httpx = httpx_logger.level
    previous_httpcore = httpcore_logger.level
    sentinel_query = "PRIVATE_QUERY_SENTINEL"
    sentinel_secret = "TOPSECRET_SENTINEL"

    try:
        caplog.set_level(logging.INFO)
        harden_http_client_logging()
        transport = httpx.MockTransport(lambda request: httpx.Response(200, request=request, json={"ok": True}))
        with httpx.Client(transport=transport) as client:
            client.get(f"https://provider.invalid/works?query={sentinel_query}&api_key={sentinel_secret}")

        assert httpx_logger.level >= logging.WARNING
        assert httpcore_logger.level >= logging.WARNING
        assert sentinel_query not in caplog.text
        assert sentinel_secret not in caplog.text
    finally:
        httpx_logger.setLevel(previous_httpx)
        httpcore_logger.setLevel(previous_httpcore)
