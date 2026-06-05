"""Packaged Streamable HTTP/SSE launcher for PubMed Search MCP."""

from __future__ import annotations

import argparse
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pubmed_search import __version__
from pubmed_search.presentation.mcp_server.http_compat import wrap_copilot_compatibility
from pubmed_search.presentation.mcp_server.server import create_server, get_container

if TYPE_CHECKING:
    from pubmed_search.application.session.manager import SessionManager
    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _default_port() -> int:
    port = os.environ.get("MCP_PORT") or os.environ.get("PORT") or "8765"
    return int(port)


def _default_export_dir() -> Path:
    return Path(tempfile.gettempdir()) / "pubmed_exports"


def build_parser() -> argparse.ArgumentParser:
    """Build the packaged HTTP CLI parser."""
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
        help="Transport protocol (default: streamable-http)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MCP_HOST", "0.0.0.0"),  # noqa: S104  # nosec B104
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
        help="Enable Copilot-compatible JSON/stateless HTTP semantics. Requires streamable-http.",
    )
    parser.add_argument(
        "--no-security",
        action="store_true",
        default=False,
        help="Disable DNS rebinding protection (not recommended for production)",
    )
    parser.add_argument(
        "--workspace-dir",
        default=os.environ.get("PUBMED_WORKSPACE_DIR"),
        help="Explicit workspace root for workspace-scoped pipeline persistence",
    )
    return parser


def _mount_auxiliary_routes(
    app: Any,
    *,
    transport: str,
    port: int,
    export_dir: Path,
    session_manager: SessionManager,
    searcher: LiteratureSearcher,
) -> None:
    """Mount public auxiliary HTTP endpoints onto the MCP ASGI app."""
    from anyio import Path as AsyncPath
    from starlette.responses import FileResponse, JSONResponse
    from starlette.routing import Route as StarletteRoute

    async def health(_request: Any) -> Any:
        return JSONResponse({"status": "ok", "service": "pubmed-search-mcp"})

    async def info(_request: Any) -> Any:
        if transport == "streamable-http":
            mcp_endpoints = {"streamable_http": "/mcp", "method": "POST"}
        else:
            mcp_endpoints = {"sse": "/sse", "messages": "/messages"}
        return JSONResponse(
            {
                "service": "PubMed Search MCP Server",
                "version": __version__,
                "transport": transport,
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
                "python_sdk": {
                    "import": "from pubmed_search.api import PubMedSearchClient, PubMedSearchConfig",
                    "note": "Use the SDK for in-process Python calls; /mcp remains the agent tool contract.",
                },
                "auxiliary_http_api": {
                    "classification": "public auxiliary read-only API",
                    "example": f"GET http://localhost:{port}/api/cached_article/12345678",
                },
            }
        )

    async def list_exports(_request: Any) -> Any:
        async_export_dir = AsyncPath(export_dir)
        if not await async_export_dir.exists():
            return JSONResponse({"export_dir": str(export_dir), "files": []})

        files = []
        async for entry in async_export_dir.iterdir():
            if await entry.is_file():
                stat = await entry.stat()
                files.append(
                    {
                        "filename": entry.name,
                        "size_bytes": stat.st_size,
                        "download_url": f"/download/{entry.name}",
                    }
                )
        return JSONResponse({"export_dir": str(export_dir), "files": sorted(files, key=lambda x: x["filename"])})

    async def download_file(request: Any) -> Any:
        filename = str(request.path_params["filename"])
        if ".." in filename or "/" in filename or "\\" in filename:
            return JSONResponse({"error": "Invalid filename"}, status_code=400)

        filepath = export_dir / filename
        async_filepath = AsyncPath(filepath)
        if not await async_filepath.exists():
            return JSONResponse({"error": "File not found"}, status_code=404)

        content_types = {
            ".csv": "text/csv",
            ".ris": "application/x-research-info-systems",
            ".bib": "application/x-bibtex",
            ".json": "application/json",
            ".txt": "text/plain",
        }
        return FileResponse(
            str(filepath),
            media_type=content_types.get(filepath.suffix.lower(), "application/octet-stream"),
            filename=filename,
        )

    async def api_get_cached_article(request: Any) -> Any:
        pmid = str(request.path_params["pmid"])
        fetch_if_missing = request.query_params.get("fetch_if_missing", "true").lower() == "true"

        cached_article = session_manager.get_cached_article(pmid)
        if cached_article is not None:
            return JSONResponse({"source": "pubmed", "verified": True, "data": cached_article})

        if fetch_if_missing:
            try:
                articles = await searcher.fetch_details([pmid])
                if articles:
                    session_manager.warm_article_cache(articles)
                    return JSONResponse({"source": "pubmed", "verified": True, "data": articles[0]})
            except Exception as exc:
                logger.exception("[API] Failed to fetch PMID %s", pmid)
                return JSONResponse({"detail": f"PubMed API error: {exc!s}"}, status_code=502)

        return JSONResponse({"detail": f"Article PMID:{pmid} not found in cache"}, status_code=404)

    async def api_get_multiple_articles(request: Any) -> Any:
        pmid_list = [pmid.strip() for pmid in request.query_params.get("pmids", "").split(",") if pmid.strip()]
        fetch_if_missing = request.query_params.get("fetch_if_missing", "false").lower() == "true"
        if not pmid_list:
            return JSONResponse({"error": "No PMIDs provided"}, status_code=400)

        found, missing = session_manager.get_cached_article_map(pmid_list)
        if fetch_if_missing and missing:
            try:
                articles = await searcher.fetch_details(missing)
                for article in articles:
                    pmid = article.get("pmid", "")
                    if pmid:
                        found[pmid] = article
                        if pmid in missing:
                            missing.remove(pmid)
                session_manager.warm_article_cache(articles)
            except Exception as exc:
                logger.warning("[API] Failed to fetch some articles: %s", exc)

        return JSONResponse(
            {
                "found": found,
                "missing": missing,
                "total_requested": len(pmid_list),
                "total_found": len(found),
            }
        )

    async def api_session_summary(_request: Any) -> Any:
        return JSONResponse(session_manager.get_session_summary())

    app.router.routes[:0] = [
        StarletteRoute("/", info),
        StarletteRoute("/info", info),
        StarletteRoute("/health", health),
        StarletteRoute("/exports", list_exports),
        StarletteRoute("/download/{filename}", download_file),
        StarletteRoute("/api/cached_article/{pmid}", api_get_cached_article),
        StarletteRoute("/api/cached_articles", api_get_multiple_articles),
        StarletteRoute("/api/session/summary", api_session_summary),
    ]


def main() -> None:
    """Run the packaged HTTP MCP server."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = build_parser()
    args = parser.parse_args()
    if args.copilot_compatible and args.transport != "streamable-http":
        parser.error("--copilot-compatible requires --transport streamable-http")

    server = create_server(
        email=args.email,
        api_key=args.api_key,
        disable_security=args.no_security,
        json_response=args.copilot_compatible,
        stateless_http=args.copilot_compatible,
        workspace_dir=args.workspace_dir,
    )

    app: Any = server.sse_app() if args.transport == "sse" else server.streamable_http_app()
    container = get_container()
    _mount_auxiliary_routes(
        app,
        transport=args.transport,
        port=args.port,
        export_dir=_default_export_dir(),
        session_manager=cast("SessionManager", container.session_manager()),
        searcher=cast("LiteratureSearcher", container.searcher()),
    )
    if args.copilot_compatible:
        app = wrap_copilot_compatibility(app)

    logger.info("Starting PubMed Search MCP HTTP server on http://%s:%s", args.host, args.port)
    logger.info("MCP endpoint: %s", "/mcp" if args.transport == "streamable-http" else "/sse")
    logger.info("Python SDK facade: from pubmed_search.api import PubMedSearchClient")

    import uvicorn

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


__all__ = ["build_parser", "main"]
