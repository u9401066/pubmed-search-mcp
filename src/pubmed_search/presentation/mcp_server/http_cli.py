"""Packaged Streamable HTTP/SSE launcher for PubMed Search MCP."""

from __future__ import annotations

import argparse
import logging
import os
from typing import TYPE_CHECKING, Any, cast

from pubmed_search import __version__
from pubmed_search.application.export import list_export_artifacts, resolve_export_artifact, tenant_export_root
from pubmed_search.application.session.registry import SessionManagerRegistry
from pubmed_search.presentation.mcp_server.auth import build_auth
from pubmed_search.presentation.mcp_server.http_compat import wrap_copilot_compatibility
from pubmed_search.presentation.mcp_server.http_security import AuxiliaryApiGuard, TransportSecurityASGIMiddleware
from pubmed_search.presentation.mcp_server.server import (
    build_asgi_app,
    create_server,
    get_container,
    get_transport_options,
)
from pubmed_search.presentation.mcp_server.tools._common import get_session_registry
from pubmed_search.shared.settings import load_settings

if TYPE_CHECKING:
    from mcp.server.transport_security import TransportSecuritySettings

    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _default_port() -> int:
    port = os.environ.get("MCP_PORT") or os.environ.get("PORT") or "8765"
    return int(port)


def build_parser() -> argparse.ArgumentParser:
    """Build the packaged HTTP CLI parser."""
    parser = argparse.ArgumentParser(description="Run PubMed Search MCP Server in HTTP mode")
    parser.add_argument(
        "--mode",
        choices=["local", "service"],
        default=os.environ.get("PUBMED_SERVER_MODE", "local").strip().lower(),
        help="Deployment profile: local loopback or authenticated multi-tenant service",
    )
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
        default=os.environ.get("MCP_HOST") or None,
        help="Server host (default: 127.0.0.1 in local mode; 0.0.0.0 in service mode)",
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
        "--allow-container-bind",
        action="store_true",
        default=_env_flag("PUBMED_LOCAL_ALLOW_CONTAINER_BIND"),
        help="Allow local mode to bind 0.0.0.0 inside a container published only to host loopback",
    )
    parser.add_argument(
        "--trusted-proxy-ips",
        default=os.environ.get("PUBMED_TRUSTED_PROXY_IPS", ""),
        help="Comma-separated proxy IPs allowed to supply forwarded headers (default: none)",
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
    data_dir: str,
    transport_security: TransportSecuritySettings,
    guard: AuxiliaryApiGuard,
    searcher: LiteratureSearcher,
) -> None:
    """Mount the auxiliary HTTP endpoints onto the MCP ASGI app.

    ``/health`` and ``/ready`` stay open for orchestrator probes; every route
    that returns session data goes through *guard* and is scoped to the calling
    tenant.
    """
    from anyio import to_thread
    from starlette.responses import FileResponse, JSONResponse
    from starlette.routing import Route as StarletteRoute

    async def health(_request: Any) -> Any:
        return JSONResponse({"status": "ok", "service": "pubmed-search-mcp", "version": __version__})

    async def ready(_request: Any) -> Any:
        registry_stats = guard.registry.stats()
        return JSONResponse(
            {
                "status": "ready",
                "service": "pubmed-search-mcp",
                "version": __version__,
                "transport": transport,
                "auth_enforced": guard.enforcing,
                "active_tenants": registry_stats["active_tenants"],
            }
        )

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
                        "ready": "/ready",
                        "downloads": "/download/{export_id}",
                        "list_exports": "/exports",
                    },
                },
                "python_sdk": {
                    "import": "from pubmed_search.api import PubMedSearchClient, PubMedSearchConfig",
                    "note": "Use the SDK for in-process Python calls; /mcp remains the agent tool contract.",
                },
                "auxiliary_http_api": {
                    "classification": "read-only API, bearer-authenticated when PUBMED_AUTH_TOKENS is set",
                    "auth_enforced": guard.enforcing,
                    "example": f"GET http://localhost:{port}/api/cached_article/12345678",
                },
            }
        )

    async def list_exports(request: Any) -> Any:
        outcome = await guard.authenticate(request)
        if outcome.identity is None:
            return JSONResponse({"detail": outcome.detail}, status_code=outcome.status_code)
        export_root = tenant_export_root(data_dir, outcome.identity)
        if export_root is None:
            return JSONResponse({"detail": "Durable storage is required"}, status_code=403)

        files = await to_thread.run_sync(list_export_artifacts, export_root)
        for item in files:
            item["download_url"] = f"/download/{item['export_id']}"
        return JSONResponse({"files": files})

    async def download_file(request: Any) -> Any:
        outcome = await guard.authenticate(request)
        if outcome.identity is None:
            return JSONResponse({"detail": outcome.detail}, status_code=outcome.status_code)
        export_root = tenant_export_root(data_dir, outcome.identity)
        if export_root is None:
            return JSONResponse({"detail": "Durable storage is required"}, status_code=403)

        export_id = str(request.path_params["export_id"])
        filepath = await to_thread.run_sync(resolve_export_artifact, export_root, export_id)
        if filepath is None:
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
            filename=export_id,
        )

    async def api_get_cached_article(request: Any) -> Any:
        outcome = await guard.authenticate(request)
        if outcome.identity is None:
            return JSONResponse({"detail": outcome.detail}, status_code=outcome.status_code)
        session_manager = guard.session_manager_for(outcome.identity)

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
        outcome = await guard.authenticate(request)
        if outcome.identity is None:
            return JSONResponse({"detail": outcome.detail}, status_code=outcome.status_code)
        session_manager = guard.session_manager_for(outcome.identity)

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

    async def api_session_summary(request: Any) -> Any:
        outcome = await guard.authenticate(request)
        if outcome.identity is None:
            return JSONResponse({"detail": outcome.detail}, status_code=outcome.status_code)
        return JSONResponse(guard.session_manager_for(outcome.identity).get_session_summary())

    app.router.routes[:0] = [
        StarletteRoute("/", info),
        StarletteRoute("/info", info),
        StarletteRoute("/health", health),
        StarletteRoute("/ready", ready),
        StarletteRoute("/exports", list_exports),
        StarletteRoute("/download/{export_id}", download_file),
        StarletteRoute("/api/exports", list_exports),
        StarletteRoute("/api/exports/{export_id}/download", download_file),
        StarletteRoute("/api/cached_article/{pmid}", api_get_cached_article),
        StarletteRoute("/api/cached_articles", api_get_multiple_articles),
        StarletteRoute("/api/session/summary", api_session_summary),
    ]
    app.add_middleware(TransportSecurityASGIMiddleware, settings=transport_security)


def main() -> None:
    """Run the packaged HTTP MCP server."""
    from pubmed_search.shared.logging_utils import harden_http_client_logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    harden_http_client_logging()
    parser = build_parser()
    args = parser.parse_args()
    if args.copilot_compatible and args.transport != "streamable-http":
        parser.error("--copilot-compatible requires --transport streamable-http")
    if args.mode == "service" and args.no_security:
        parser.error("--no-security is forbidden in service mode")
    if args.mode == "service" and args.allow_container_bind:
        parser.error("--allow-container-bind applies only to local mode")

    host = args.host or ("127.0.0.1" if args.mode == "local" else "0.0.0.0")  # noqa: S104  # nosec B104
    settings = load_settings()

    server = create_server(
        email=args.email,
        api_key=args.api_key,
        disable_security=args.no_security,
        json_response=args.copilot_compatible,
        stateless_http=args.copilot_compatible,
        data_dir=settings.data_dir,
        workspace_dir=args.workspace_dir,
        mode=args.mode,
        allow_container_bind=args.allow_container_bind,
    )

    app: Any = build_asgi_app(server, args.transport, host=host)
    container = get_container()
    token_verifier, _ = build_auth(settings)
    transport_security = get_transport_options(server).transport_security
    if transport_security is None:  # pragma: no cover - create_server always installs explicit settings
        msg = "Packaged HTTP server is missing transport security settings"
        raise RuntimeError(msg)
    registry_root = settings.data_dir  # tenant-ok: registry splits per tenant below
    registry = get_session_registry() or SessionManagerRegistry(registry_root)
    _mount_auxiliary_routes(
        app,
        transport=args.transport,
        port=args.port,
        data_dir=settings.data_dir,
        transport_security=transport_security,
        guard=AuxiliaryApiGuard(
            verifier=token_verifier,
            registry=registry,
            mode=args.mode,
            require_auth=settings.auth_required or args.mode == "service",
        ),
        searcher=cast("LiteratureSearcher", container.searcher()),
    )
    if args.copilot_compatible:
        app = wrap_copilot_compatibility(app)

    logger.info("Starting PubMed Search MCP HTTP server on http://%s:%s", host, args.port)
    logger.info("Server mode: %s", args.mode)
    logger.info("MCP endpoint: %s", "/mcp" if args.transport == "streamable-http" else "/sse")
    logger.info(
        "Auth: %s",
        "bearer tokens enforced"
        if token_verifier
        else "trusted local single-user HTTP (shared durable default tenant)",
    )
    logger.info("Tenant isolation: %s", "on" if settings.tenant_isolation else "off")
    logger.info("Python SDK facade: from pubmed_search.api import PubMedSearchClient")

    import uvicorn

    trusted_proxy_ips = args.trusted_proxy_ips.strip()
    uvicorn.run(
        app,
        host=host,
        port=args.port,
        proxy_headers=bool(trusted_proxy_ips),
        forwarded_allow_ips=trusted_proxy_ips,
        server_header=False,
    )


if __name__ == "__main__":
    main()


__all__ = ["build_parser", "main"]
