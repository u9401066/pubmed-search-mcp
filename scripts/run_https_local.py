#!/usr/bin/env python3
"""Run the PubMed Search MCP server over local HTTPS for development tests."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import uvicorn
from starlette.responses import JSONResponse
from starlette.routing import Route

PROJECT_ROOT = Path(__file__).resolve().parents[1]


async def health(_request: Any) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "pubmed-search-mcp"})


async def info(_request: Any) -> JSONResponse:
    return JSONResponse(
        {
            "service": "PubMed Search MCP",
            "transport": "streamable-http",
            "copilot_compatible": True,
            "endpoints": {
                "mcp": "/mcp",
                "health": "/health",
                "info": "/info",
            },
        }
    )


def create_https_app(email: str, api_key: str | None) -> Any:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

    from pubmed_search.presentation.mcp_server.http_compat import wrap_copilot_compatibility
    from pubmed_search.presentation.mcp_server.server import create_server

    server = create_server(
        email=email,
        api_key=api_key,
        disable_security=True,
        json_response=True,
        stateless_http=True,
    )
    mcp_app: Any = server.streamable_http_app()

    mcp_app.router.routes[:0] = [
        Route("/health", health),
        Route("/info", info),
    ]
    return wrap_copilot_compatibility(mcp_app)


def main() -> None:
    default_ssl_dir = PROJECT_ROOT / "nginx" / "ssl"

    parser = argparse.ArgumentParser(description="Run PubMed Search MCP over local HTTPS")
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--email", default=os.environ.get("NCBI_EMAIL", "pubmed-search@example.com"))
    parser.add_argument("--api-key", default=os.environ.get("NCBI_API_KEY"))
    parser.add_argument("--certfile", type=Path, default=default_ssl_dir / "server.crt")
    parser.add_argument("--keyfile", type=Path, default=default_ssl_dir / "server.key")
    args = parser.parse_args()

    app = create_https_app(email=args.email, api_key=args.api_key)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        ssl_keyfile=str(args.keyfile),
        ssl_certfile=str(args.certfile),
        log_level="info",
    )


if __name__ == "__main__":
    main()
