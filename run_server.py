#!/usr/bin/env python3
"""
PubMed Search MCP Server - HTTP Mode

This script runs the PubMed Search MCP server in HTTP mode (SSE or streamable-http),
allowing remote clients from other machines to connect.

Usage:
    # Run with streamable-http transport (default)
    uv run python run_server.py --transport streamable-http --port 8765

    # Run with legacy SSE transport
    uv run python run_server.py --transport sse --port 8765

    # Run with Copilot-compatible HTTP semantics (full tool schemas)
    uv run python run_server.py --transport streamable-http --copilot-compatible

    # Run with custom email and API key
    uv run python run_server.py --email your@email.com --api-key YOUR_API_KEY

Environment Variables:
    NCBI_EMAIL: Email for NCBI Entrez API
    NCBI_API_KEY: Optional API key for higher rate limits
    MCP_PORT: Preferred server port
    PORT: Fallback server port for container platforms
    MCP_HOST: Server host (default: 0.0.0.0)
    MCP_COPILOT_COMPATIBLE: Enable Copilot-compatible HTTP semantics
"""

import argparse
import logging
import os
import sys
from typing import TYPE_CHECKING, Any, cast

from anyio import Path as AsyncPath

# Add src to path for development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from pubmed_search import __version__
from pubmed_search.presentation.mcp_server.http_compat import wrap_copilot_compatibility
from pubmed_search.presentation.mcp_server.server import create_server

if TYPE_CHECKING:
    from pubmed_search.application.session.manager import SessionManager
    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _default_port() -> int:
    port = os.environ.get("MCP_PORT") or os.environ.get("PORT") or "8765"
    return int(port)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run PubMed Search MCP Server in HTTP mode")
    parser.add_argument(
        "--email",
        default=os.environ.get("NCBI_EMAIL", "pubmed-search@example.com"),
        help="Email for NCBI Entrez API (required by NCBI)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("NCBI_API_KEY"),
        help="Optional NCBI API key for higher rate limits",
    )
    parser.add_argument(
        "--transport",
        choices=["sse", "streamable-http"],
        default=os.environ.get("MCP_TRANSPORT", "streamable-http"),
        help="Transport protocol (default: streamable-http, recommended for Copilot Studio)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MCP_HOST", "0.0.0.0"),  # nosec B104
        help="Server host (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_default_port(),
        help="Server port (default: MCP_PORT, PORT, or 8765)",
    )
    parser.add_argument(
        "--copilot-compatible",
        action="store_true",
        default=_env_flag("MCP_COPILOT_COMPATIBLE"),
        help=(
            "Enable Copilot-compatible JSON/stateless HTTP semantics. "
            "Requires streamable-http. Use run_copilot.py for simplified tool schemas."
        ),
    )
    parser.add_argument(
        "--no-security",
        action="store_true",
        default=False,
        help="Disable DNS rebinding protection (not recommended for production)",
    )

    args = parser.parse_args()

    if args.copilot_compatible and args.transport != "streamable-http":
        parser.error("--copilot-compatible requires --transport streamable-http")

    # Create server
    logger.info("Creating PubMed Search MCP Server...")
    logger.info(f"  Email: {args.email}")
    logger.info(f"  API Key: {'Set' if args.api_key else 'Not set'}")
    logger.info(f"  Transport: {args.transport}")
    logger.info(f"  Host: {args.host}")
    logger.info(f"  Port: {args.port}")
    logger.info(f"  Copilot-compatible HTTP: {'Enabled' if args.copilot_compatible else 'Disabled'}")
    logger.info(f"  DNS Rebinding Protection: {'Disabled' if args.no_security else 'Enabled'}")

    server = create_server(
        email=args.email,
        api_key=args.api_key,
        disable_security=args.no_security,
        json_response=args.copilot_compatible,
        stateless_http=args.copilot_compatible,
    )

    # Run server with selected transport
    logger.info(f"Starting server at http://{args.host}:{args.port}")

    if args.transport == "sse":
        logger.info("SSE endpoint: /sse")
        logger.info("Message endpoint: /messages")
    else:
        logger.info("Streamable HTTP endpoint: /mcp")

    # Run the server using uvicorn directly for proper host/port control
    from pathlib import Path

    import uvicorn
    from starlette.responses import FileResponse, JSONResponse

    # Export directory
    EXPORT_DIR = Path("/tmp/pubmed_exports")  # nosec B108

    if args.transport == "sse":
        mcp_app = server.sse_app()
    else:
        mcp_app = server.streamable_http_app()

    # Get session manager for HTTP API endpoints via DI container
    from pubmed_search.presentation.mcp_server.server import get_container

    container = get_container()
    session_manager = cast("SessionManager", container.session_manager())
    searcher = cast("LiteratureSearcher", container.searcher())

    # Add health check and info endpoints
    async def health(request: Any) -> Any:
        return JSONResponse({"status": "ok", "service": "pubmed-search-mcp"})

    async def info(request: Any) -> Any:
        # Build endpoint info based on transport
        if args.transport == "streamable-http":
            mcp_endpoints = {"streamable_http": "/mcp", "method": "POST"}
            if args.copilot_compatible:
                copilot_studio = {
                    "compatible": True,
                    "server_url": "https://YOUR_DOMAIN/mcp",
                    "transport": "mcp-streamable-1.0",
                    "mode": "json_response + stateless_http",
                    "tool_schemas": "full",
                    "note": (
                        "Replace YOUR_DOMAIN with your public HTTPS domain. "
                        "If Copilot Studio rejects full schemas, use run_copilot.py."
                    ),
                }
            else:
                copilot_studio = {
                    "compatible": False,
                    "transport_ready": True,
                    "note": (
                        "Streamable HTTP is enabled, but Copilot-specific HTTP semantics are off. "
                        "Start with --copilot-compatible for full HTTP compatibility or use run_copilot.py "
                        "for simplified tool schemas."
                    ),
                }
        else:
            mcp_endpoints = {"sse": "/sse", "messages": "/messages"}
            copilot_studio = {
                "compatible": False,
                "note": "SSE deprecated for Copilot Studio since Aug 2025. Use --transport streamable-http",
            }

        return JSONResponse(
            {
                "service": "PubMed Search MCP Server",
                "version": __version__,
                "transport": args.transport,
                "endpoints": {
                    "mcp": mcp_endpoints,
                    "auxiliary_api": {
                        "cached_article": "/api/cached_article/{pmid}",
                        "cached_articles": "/api/cached_articles?pmids=...",
                        "session_summary": "/api/session/summary",
                    },
                    "utility": {
                        "info": "/info",
                        "root_info": "/",
                        "health": "/health",
                        "downloads": "/download/{filename}",
                        "list_exports": "/exports",
                    },
                },
                "microsoft_copilot_studio": copilot_studio,
                "auxiliary_http_api": {
                    "classification": "public auxiliary read-only API",
                    "description": (
                        "Cache/session endpoints are callable directly, but they are auxiliary to the "
                        "primary MCP contract at /mcp."
                    ),
                    "example": f"GET http://localhost:{args.port}/api/cached_article/12345678",
                },
            }
        )

    async def list_exports(request: Any) -> Any:
        """List available export files."""
        export_dir = AsyncPath(EXPORT_DIR)

        if not await export_dir.exists():
            return JSONResponse({"files": [], "message": "No exports yet"})

        files = []
        async for entry in export_dir.iterdir():
            if await entry.is_file():
                stat = await entry.stat()
                files.append(
                    {
                        "filename": entry.name,
                        "size_bytes": stat.st_size,
                        "download_url": f"/download/{entry.name}",
                    }
                )

        return JSONResponse(
            {
                "export_dir": str(EXPORT_DIR),
                "files": sorted(files, key=lambda x: x["filename"], reverse=True),
            }
        )

    async def download_file(request: Any) -> Any:
        """Download an export file."""
        filename = request.path_params["filename"]
        filepath = EXPORT_DIR / filename
        async_filepath = AsyncPath(filepath)

        # Security: prevent directory traversal
        if ".." in filename or "/" in filename:
            return JSONResponse({"error": "Invalid filename"}, status_code=400)

        if not await async_filepath.exists():
            return JSONResponse({"error": "File not found"}, status_code=404)

        # Determine content type
        ext = filepath.suffix.lower()
        content_types = {
            ".csv": "text/csv",
            ".ris": "application/x-research-info-systems",
            ".bib": "application/x-bibtex",
            ".json": "application/json",
            ".txt": "text/plain",
        }
        content_type = content_types.get(ext, "application/octet-stream")

        return FileResponse(str(filepath), media_type=content_type, filename=filename)

    # ===== MCP-to-MCP HTTP API Endpoints =====
    # These endpoints allow other MCP servers (like mdpaper) to access
    # cached article data directly without going through the Agent.

    async def api_get_cached_article(request: Any) -> Any:
        """
        Get cached article by PMID.

        MCP-to-MCP endpoint: Other MCP servers call this directly.
        """
        pmid = request.path_params["pmid"]
        fetch_if_missing = request.query_params.get("fetch_if_missing", "true").lower() == "true"

        # Try cache first
        session = session_manager.get_current_session()
        if session and pmid in session.article_cache:
            logger.info(f"[API] Cache hit for PMID {pmid}")
            return JSONResponse(
                {
                    "source": "pubmed",
                    "verified": True,
                    "data": session.article_cache[pmid],
                }
            )

        # Fetch if requested
        if fetch_if_missing and searcher:
            logger.info(f"[API] Cache miss for PMID {pmid}, fetching from PubMed")
            try:
                articles = await searcher.fetch_details([pmid])
                if articles:
                    session_manager.add_to_cache(articles)
                    return JSONResponse({"source": "pubmed", "verified": True, "data": articles[0]})
            except Exception as e:
                logger.error(f"[API] Failed to fetch PMID {pmid}: {e}")
                return JSONResponse({"detail": f"PubMed API error: {e!s}"}, status_code=502)

        return JSONResponse({"detail": f"Article PMID:{pmid} not found in cache"}, status_code=404)

    async def api_get_multiple_articles(request: Any) -> Any:
        """Get multiple cached articles by PMIDs."""
        pmids_param = request.query_params.get("pmids", "")
        fetch_if_missing = request.query_params.get("fetch_if_missing", "false").lower() == "true"

        pmid_list = [p.strip() for p in pmids_param.split(",") if p.strip()]

        if not pmid_list:
            return JSONResponse({"error": "No PMIDs provided"}, status_code=400)

        found = {}
        missing = []

        session = session_manager.get_current_session()

        for pmid in pmid_list:
            if session and pmid in session.article_cache:
                found[pmid] = session.article_cache[pmid]
            else:
                missing.append(pmid)

        if fetch_if_missing and missing and searcher:
            try:
                articles = await searcher.fetch_details(missing)
                for article in articles:
                    pmid = article.get("pmid", "")
                    if pmid:
                        found[pmid] = article
                        if pmid in missing:
                            missing.remove(pmid)
                session_manager.add_to_cache(articles)
            except Exception as e:
                logger.warning(f"[API] Failed to fetch some articles: {e}")

        return JSONResponse(
            {
                "found": found,
                "missing": missing,
                "total_requested": len(pmid_list),
                "total_found": len(found),
            }
        )

    async def api_session_summary(request: Any) -> Any:
        """Get current session summary for MCP-to-MCP."""
        return JSONResponse(session_manager.get_session_summary())

    # Add middleware to handle host header issues

    # For streamable-http, we need to add routes to the MCP app directly
    # because it has a lifespan handler that must be preserved
    # The MCP app already has /mcp route, we just add our utility routes

    # Add additional routes to the MCP app
    from starlette.routing import Route as StarletteRoute

    # Insert our routes at the beginning of mcp_app.routes
    additional_routes = [
        StarletteRoute("/", info),
        StarletteRoute("/info", info),
        StarletteRoute("/health", health),
        StarletteRoute("/exports", list_exports),
        StarletteRoute("/download/{filename}", download_file),
        # MCP-to-MCP HTTP API endpoints
        StarletteRoute("/api/cached_article/{pmid}", api_get_cached_article),
        StarletteRoute("/api/cached_articles", api_get_multiple_articles),
        StarletteRoute("/api/session/summary", api_session_summary),
    ]

    # Prepend our routes to the MCP app's routes
    # This way /mcp still works (from MCP SDK) and our routes work too
    mcp_app.router.routes[:0] = additional_routes

    # Use mcp_app directly (preserves lifespan handling)
    app: Any = mcp_app

    if args.copilot_compatible:
        app = wrap_copilot_compatibility(app)

    # Log appropriate endpoints based on transport
    logger.info(f"Download endpoint: http://{args.host}:{args.port}/download/{{filename}}")
    logger.info(f"List exports: http://{args.host}:{args.port}/exports")

    if args.transport == "streamable-http":
        logger.info("")
        logger.info("═══════════════════════════════════════════════════════")
        logger.info("  PubMed Search MCP HTTP Server")
        logger.info("═══════════════════════════════════════════════════════")
        logger.info(f"  MCP Endpoint: http://{args.host}:{args.port}/mcp")
        logger.info("  Transport:    Streamable HTTP (POST /mcp)")
        if args.copilot_compatible:
            logger.info("  Mode:         Copilot-compatible HTTP enabled")
            logger.info("  Caveat:       Full tool schemas remain enabled")
            logger.info("  Use run_copilot.py if schema simplification is needed")
        else:
            logger.info("  Mode:         Standard streamable HTTP")
            logger.info("  For Copilot Studio HTTP semantics, add: --copilot-compatible")
        logger.info("")
        logger.info("  For remote clients, use HTTPS URL:")
        logger.info("    Server URL: https://your-domain.com/mcp")
        logger.info("═══════════════════════════════════════════════════════")
    else:
        logger.info("")
        logger.info("  ⚠️  SSE transport - Deprecated for Copilot Studio")
        logger.info(f"  SSE endpoint: http://{args.host}:{args.port}/sse")
        logger.info(f"  Message endpoint: http://{args.host}:{args.port}/messages")
        logger.info("")
        logger.info("  For Copilot Studio, use: --transport streamable-http")

    logger.info("")
    logger.info("[Public Auxiliary HTTP API]")
    logger.info("  GET /api/cached_article/{pmid} - Read one cached article")
    logger.info("  GET /api/cached_articles?pmids=... - Read multiple cached articles")
    logger.info("  GET /api/session/summary - Read current session summary")
    logger.info("  These endpoints are public auxiliary APIs; /mcp remains the primary external contract")

    # Run with settings to accept any host
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        proxy_headers=True,
        forwarded_allow_ips="*",
        server_header=False,
    )


if __name__ == "__main__":
    main()
