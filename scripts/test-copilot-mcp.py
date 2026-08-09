#!/usr/bin/env python3
"""Exercise the MCP SDK v2 modern HTTP contract used by Copilot Studio.

MCP protocol revision 2026-07-28 removed the initialize exchange and
``Mcp-Session-Id`` lifecycle. Every request therefore carries modern protocol
metadata and is independently routable.

Usage:
    uv run python scripts/test-copilot-mcp.py http://127.0.0.1:8765/mcp
    uv run python scripts/test-copilot-mcp.py https://mcp.example.org/mcp --token "$TOKEN"
    uv run python scripts/test-copilot-mcp.py http://127.0.0.1:8765/mcp --live-search
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests
from mcp.types.version import LATEST_MODERN_VERSION
from mcp_types import CLIENT_CAPABILITIES_META_KEY, PROTOCOL_VERSION_META_KEY

REQUEST_TIMEOUT_SECONDS = 30
LIVE_SEARCH_TIMEOUT_SECONDS = 60


def _endpoint_url(value: str) -> str:
    """Normalize a server URL to its MCP endpoint."""
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        msg = "URL must be an absolute http:// or https:// address"
        raise argparse.ArgumentTypeError(msg)
    path = parsed.path.rstrip("/")
    if not path:
        path = "/mcp"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _health_url(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    return urlunsplit((parsed.scheme, parsed.netloc, "/health", "", ""))


def _headers(method: str, token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json; charset=utf-8",
        "MCP-Protocol-Version": LATEST_MODERN_VERSION,
        "MCP-Method": method,
        "X-Ms-User-Agent": "CopilotStudio-modern-http-smoke/2.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _params(values: dict[str, Any] | None = None) -> dict[str, Any]:
    result = dict(values or {})
    result["_meta"] = {
        PROTOCOL_VERSION_META_KEY: LATEST_MODERN_VERSION,
        CLIENT_CAPABILITIES_META_KEY: {},
    }
    return result


def _decode_response(response: requests.Response) -> dict[str, Any]:
    """Decode either JSON mode or a one-event SSE response."""
    content_type = response.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        payload = response.json()
        return payload if isinstance(payload, dict) else {"result": payload}

    for line in response.text.splitlines():
        if line.startswith("data:"):
            payload = json.loads(line.removeprefix("data:").strip())
            return payload if isinstance(payload, dict) else {"result": payload}
    msg = f"Unsupported MCP response content type: {content_type or 'missing'}"
    raise ValueError(msg)


def _post(
    session: requests.Session,
    endpoint: str,
    *,
    method: str,
    request_id: int,
    token: str | None,
    params: dict[str, Any] | None = None,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": _params(params),
    }
    response = session.post(
        endpoint,
        json=payload,
        headers=_headers(method, token),
        timeout=timeout,
    )
    response.raise_for_status()
    if "mcp-session-id" in {name.lower() for name in response.headers}:
        msg = "Server returned legacy Mcp-Session-Id under the modern protocol"
        raise RuntimeError(msg)
    decoded = _decode_response(response)
    if "error" in decoded:
        msg = f"MCP {method} failed: {decoded['error']}"
        raise RuntimeError(msg)
    return decoded


def _select_diagnostic_tool(tool_names: set[str]) -> tuple[str, dict[str, Any]] | None:
    """Choose a deterministic, non-network tool shared by the two surfaces."""
    if "analyze_clinical_question" in tool_names:
        return "analyze_clinical_question", {"question": "Does treatment A improve outcome B in adults?"}
    if "analyze_search_query" in tool_names:
        return "analyze_search_query", {"query": "remimazolam ICU sedation"}
    return None


def _select_live_search(tool_names: set[str]) -> tuple[str, dict[str, Any]] | None:
    if "search_pubmed" in tool_names:
        return "search_pubmed", {"query": "remimazolam ICU sedation", "limit": 3}
    if "unified_search" in tool_names:
        return "unified_search", {
            "query": "remimazolam ICU sedation",
            "limit": 3,
            "output_format": "json",
            "options": "shallow,no_analysis,no_scores,no_relax",
        }
    return None


def test_mcp_server(endpoint: str, *, token: str | None, live_search: bool) -> bool:
    """Validate health, tool discovery, and modern stateless tool calls."""
    session = requests.Session()

    health = session.get(_health_url(endpoint), timeout=REQUEST_TIMEOUT_SECONDS)
    health.raise_for_status()
    print(f"[ok] health: {health.status_code} {_health_url(endpoint)}")

    listed = _post(
        session,
        endpoint,
        method="tools/list",
        request_id=1,
        token=token,
    )
    tools = listed.get("result", {}).get("tools", [])
    tool_names = {str(tool.get("name")) for tool in tools if isinstance(tool, dict)}
    if not tool_names:
        msg = "tools/list returned no tools"
        raise RuntimeError(msg)
    print(f"[ok] modern tools/list: {len(tool_names)} tools; no initialize/session header")

    diagnostic = _select_diagnostic_tool(tool_names)
    if diagnostic is not None:
        name, arguments = diagnostic
        _post(
            session,
            endpoint,
            method="tools/call",
            request_id=2,
            token=token,
            params={"name": name, "arguments": arguments},
        )
        print(f"[ok] deterministic tools/call: {name}")
    else:
        print("[warn] no deterministic diagnostic tool found; discovery still passed")

    if live_search:
        selected = _select_live_search(tool_names)
        if selected is None:
            msg = "No supported search tool is available"
            raise RuntimeError(msg)
        name, arguments = selected
        _post(
            session,
            endpoint,
            method="tools/call",
            request_id=3,
            token=token,
            params={"name": name, "arguments": arguments},
            timeout=LIVE_SEARCH_TIMEOUT_SECONDS,
        )
        print(f"[ok] live tools/call: {name}")

    print(f"[ok] MCP modern HTTP smoke passed: {endpoint}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Test MCP SDK v2 modern HTTP / Copilot compatibility")
    parser.add_argument("url", nargs="?", type=_endpoint_url, default="http://127.0.0.1:8765/mcp")
    parser.add_argument("--token", default=os.environ.get("PUBMED_BEARER_TOKEN"))
    parser.add_argument("--live-search", action="store_true", help="Also make one real upstream PubMed search")
    args = parser.parse_args()

    try:
        test_mcp_server(args.url, token=args.token, live_search=args.live_search)
    except (requests.RequestException, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"[failed] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
