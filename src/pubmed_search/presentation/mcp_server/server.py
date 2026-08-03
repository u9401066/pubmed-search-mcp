"""
PubMed Search MCP Server

A standalone Model Context Protocol server for PubMed literature search.
Can be used independently or integrated into other MCP servers.

Features:
- Literature search with various filters
- Article caching to avoid redundant API calls
- Research session management for Agent context
- Reading list management

Architecture:
- instructions.py: SERVER_INSTRUCTIONS for AI agents
- tool_registry.py: Centralized tool registration
- tools/: Individual tool implementations by category
- container: DI container for service lifecycle
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from pubmed_search import __version__
from pubmed_search.application.session.registry import SessionManagerRegistry
from pubmed_search.container import ApplicationContainer
from pubmed_search.shared.settings import DEFAULT_DATA_DIR, DEFAULT_EMAIL, load_settings

from .auth import build_auth
from .instructions import SERVER_INSTRUCTIONS
from .tenancy import build_tenancy_middleware
from .tool_registry import register_all_mcp_tools
from .tools._common import set_session_registry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from starlette.applications import Starlette

    from pubmed_search.application.session.manager import SessionManager
    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)

# ── Module-level DI container ──────────────────────────────────────────────
_container: ApplicationContainer | None = None

_TRANSPORT_OPTIONS_ATTR = "_pubmed_transport_options"


@dataclass(frozen=True)
class TransportOptions:
    """Transport-level settings chosen at ``create_server()`` time.

    MCP SDK v2 moved these keywords off the server constructor and onto
    ``run()`` / ``sse_app()`` / ``streamable_http_app()``. We record the caller's
    intent here so the launcher that builds the ASGI app can replay it.

    Attributes:
        json_response: Return JSON bodies instead of SSE for Streamable HTTP.
        stateless_http: Serve every request with a fresh transport (no session id).
        transport_security: DNS-rebinding protection settings, or ``None`` for the
            SDK default (auto-enabled for loopback hosts).
    """

    json_response: bool = False
    stateless_http: bool = False
    transport_security: TransportSecuritySettings | None = None


def get_transport_options(server: MCPServer[Any]) -> TransportOptions:
    """Read the transport options recorded on *server* by :func:`create_server`.

    Args:
        server: A server instance produced by :func:`create_server`.

    Returns:
        The recorded :class:`TransportOptions`, or defaults for servers built
        outside :func:`create_server`.
    """
    options = getattr(server, _TRANSPORT_OPTIONS_ATTR, None)
    return options if isinstance(options, TransportOptions) else TransportOptions()


def build_asgi_app(server: MCPServer[Any], transport: str = "streamable-http", *, host: str = "127.0.0.1") -> Starlette:
    """Build the ASGI app for *server* using its recorded transport options.

    Args:
        server: A server instance produced by :func:`create_server`.
        transport: Either ``"streamable-http"`` or ``"sse"``.
        host: Bind host, used only to decide whether the SDK auto-enables DNS
            rebinding protection.

    Returns:
        A Starlette app ready to be served by uvicorn.

    Raises:
        ValueError: If *transport* is not a supported HTTP transport.
    """
    options = get_transport_options(server)

    if transport == "sse":
        return server.sse_app(transport_security=options.transport_security, host=host)
    if transport == "streamable-http":
        return server.streamable_http_app(
            json_response=options.json_response,
            stateless_http=options.stateless_http,
            transport_security=options.transport_security,
            host=host,
        )

    msg = f"Unsupported transport: {transport!r}. Use 'streamable-http' or 'sse'."
    raise ValueError(msg)


def get_container() -> ApplicationContainer:
    """Get the application DI container.

    Raises:
        RuntimeError: If ``create_server()`` has not been called yet.
    """
    if _container is None:
        msg = "Container not initialized. Call create_server() first."
        raise RuntimeError(msg)
    return _container


def _make_lifespan(
    container: ApplicationContainer,
) -> Callable[[MCPServer[Any]], AbstractAsyncContextManager[ApplicationContainer]]:
    """Create an MCPServer lifespan handler bound to *container*."""

    @asynccontextmanager
    async def _lifespan(server: MCPServer[Any]) -> AsyncIterator[ApplicationContainer]:
        """Application lifecycle: startup → yield → shutdown."""
        from pubmed_search.presentation.mcp_server.tools.pipeline_tools import get_pipeline_scheduler

        scheduler = get_pipeline_scheduler()
        if scheduler is not None:
            scheduler.start()
        logger.info("Lifecycle: startup - resources ready")
        try:
            yield container
        finally:
            # Shutdown: close shared httpx client
            from pubmed_search.shared.async_utils import close_shared_async_client

            if scheduler is not None:
                scheduler.shutdown()
            await close_shared_async_client()
            logger.info("Lifecycle: shutdown - shared HTTP client closed")

    return _lifespan


def create_server(
    email: str = DEFAULT_EMAIL,
    api_key: str | None = None,
    name: str = "pubmed-search",
    disable_security: bool = False,
    data_dir: str | None = None,
    workspace_dir: str | None = None,
    json_response: bool = False,
    stateless_http: bool = False,
) -> MCPServer[Any]:
    """
    Create and configure the PubMed Search MCP server.

    Uses :class:`~pubmed_search.container.ApplicationContainer` for
    dependency injection and lifecycle management.

    Args:
        email: Email address for NCBI Entrez API (required by NCBI).
        api_key: Optional NCBI API key for higher rate limits.
        name: Server name.
        disable_security: Disable DNS rebinding protection (needed for remote access).
        data_dir: Directory for session data persistence. Default: ~/.pubmed-search-mcp
        workspace_dir: Explicit workspace root for workspace-scoped pipeline storage.
            When omitted, workspace-scoped pipeline persistence is disabled.
        json_response: Use JSON responses instead of SSE (for Copilot Studio compatibility).
        stateless_http: Use stateless HTTP mode (no session management, for Copilot Studio).

    Returns:
        Configured MCPServer instance. Transport-level options are recorded on the
        instance and replayed by :func:`build_asgi_app`.
    """
    global _container
    logger.info("Initializing PubMed Search MCP Server...")

    from pubmed_search.infrastructure.sources import configure_source_contact_email

    configure_source_contact_email(email)

    # ── DI container ────────────────────────────────────────────────────
    _container = ApplicationContainer()
    _container.config.from_dict(
        {
            "email": email,
            "api_key": api_key,
            "data_dir": data_dir or DEFAULT_DATA_DIR,
        }
    )

    searcher = cast("LiteratureSearcher", _container.searcher())
    strategy_generator = _container.strategy_generator()
    session_manager = cast("SessionManager", _container.session_manager())

    logger.info("Strategy generator initialized (ESpell + MeSH)")
    logger.info("Session data directory: %s", data_dir or DEFAULT_DATA_DIR)

    settings = load_settings()

    # ── Authentication ──────────────────────────────────────────────────
    token_verifier, auth_settings = build_auth(settings)
    if token_verifier is not None:
        logger.info("Bearer auth enabled for %d principal(s)", len(token_verifier))
    elif settings.auth_required:
        msg = "PUBMED_AUTH_REQUIRED is set but PUBMED_AUTH_TOKENS is empty; refusing to start unauthenticated."
        raise RuntimeError(msg)

    # ── Transport security ──────────────────────────────────────────────
    if disable_security:
        transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
        logger.info("DNS rebinding protection disabled for remote access")
    else:
        transport_security = None

    # ── Create MCP server with lifespan ─────────────────────────────────
    mcp: MCPServer[Any] = MCPServer(
        name,
        instructions=SERVER_INSTRUCTIONS,
        version=__version__,
        lifespan=_make_lifespan(_container),
        token_verifier=token_verifier,
        auth=auth_settings,
    )
    # MCPServer has no public middleware hook yet; the low-level server does.
    mcp._lowlevel_server.middleware.append(
        build_tenancy_middleware(
            isolation_enabled=settings.tenant_isolation,
            max_concurrency=settings.tenant_max_concurrency,
        )
    )
    setattr(
        mcp,
        _TRANSPORT_OPTIONS_ATTR,
        TransportOptions(
            json_response=json_response,
            stateless_http=stateless_http,
            transport_security=transport_security,
        ),
    )

    # ── Register all tools via centralized registry ─────────────────────
    stats = register_all_mcp_tools(
        mcp=mcp,
        searcher=searcher,
        session_manager=session_manager,
        strategy_generator=strategy_generator,
        workspace_dir=workspace_dir,
    )
    logger.info("Tool registration complete: %s", stats)

    # ── Per-tenant session isolation ────────────────────────────────────
    # Installed after registration: register_all_mcp_tools() calls
    # set_session_manager(), which intentionally clears any registry.
    if settings.tenant_isolation:
        set_session_registry(SessionManagerRegistry(data_dir or DEFAULT_DATA_DIR))
        logger.info("Tenant isolation enabled (max %d concurrent requests per tenant)", settings.tenant_max_concurrency)
        if token_verifier is None:
            logger.warning(
                "Tenant isolation is on but no auth is configured. Remote callers would be separated only by "
                "the client-supplied mcp-session-id header, which is not an authorization boundary, so tools "
                "that persist research artifacts will refuse to write. Set PUBMED_AUTH_TOKENS to enable them."
            )

    # ── Install performance profiling (optional) ────────────────────────
    from pubmed_search.infrastructure.sources.profiling import install_http_profiling
    from pubmed_search.shared.profiling import install_profiling

    if install_profiling(mcp):
        install_http_profiling()

    logger.info("PubMed Search MCP Server initialized successfully")

    return mcp


def start_http_api_background(session_manager, searcher, port: int = 8765):
    """
    Start HTTP API server in background thread for MCP-to-MCP communication.

    This allows other MCP servers (like mdpaper) to access cached articles
    directly via HTTP, even when running in stdio mode.
    """
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    # Create a dedicated event loop for the background thread
    _bg_loop = asyncio.new_event_loop()

    def _fresh_session_manager() -> Any:
        session_data_dir = getattr(session_manager, "data_dir", None)
        if isinstance(session_data_dir, (str, os.PathLike, Path)):
            from pubmed_search.application.session.manager import SessionManager

            return SessionManager(data_dir=str(session_data_dir))
        return session_manager

    background_searcher = searcher
    try:
        from pubmed_search.infrastructure.ncbi import LiteratureSearcher

        if isinstance(searcher, LiteratureSearcher):
            background_searcher = LiteratureSearcher(email=searcher.email, api_key=searcher.api_key)
    except Exception:
        background_searcher = searcher

    class MCPAPIHandler(BaseHTTPRequestHandler):
        """Simple HTTP handler for the public auxiliary HTTP API."""

        def log_message(self, format, *args):
            # Suppress HTTP access logs to avoid polluting stdio
            pass

        def _send_json(self, data: dict, status: int = 200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def do_GET(self):
            path = self.path

            # Health check
            if path == "/health":
                self._send_json({"status": "ok", "service": "pubmed-search-mcp-api"})
                return

            # Get single cached article
            if path.startswith("/api/cached_article/"):
                pmid = path.split("/")[-1].split("?")[0]
                active_session_manager = _fresh_session_manager()
                cached_article = active_session_manager.get_cached_article(pmid)
                if cached_article is not None:
                    self._send_json(
                        {
                            "source": "pubmed",
                            "verified": True,
                            "data": cached_article,
                        }
                    )
                    return

                # Try to fetch if not in cache (async → sync bridge)
                if background_searcher:
                    try:
                        articles = _bg_loop.run_until_complete(background_searcher.fetch_details([pmid]))
                        if articles:
                            self._send_json(
                                {
                                    "source": "pubmed",
                                    "verified": True,
                                    "data": articles[0],
                                }
                            )
                            return
                    except Exception as e:
                        self._send_json({"detail": f"PubMed API error: {e!s}"}, 502)
                        return

                self._send_json({"detail": f"Article PMID:{pmid} not found"}, 404)
                return

            # Get session summary
            if path == "/api/session/summary":
                self._send_json(_fresh_session_manager().get_session_summary())
                return

            # Root - API info
            if path in {"/", ""}:
                self._send_json(
                    {
                        "service": "pubmed-search-mcp HTTP API",
                        "mode": "background (stdio MCP + public auxiliary HTTP API)",
                        "endpoints": {
                            "/health": "Health check",
                            "/api/cached_article/{pmid}": "Read cached article",
                            "/api/cached_articles?pmids=...": "Read multiple cached articles",
                            "/api/session/summary": "Read current session summary",
                        },
                    }
                )
                return

            self._send_json({"error": "Not found"}, 404)

    def run_server():
        try:
            httpd = HTTPServer(("127.0.0.1", port), MCPAPIHandler)
            logger.info(f"[HTTP API] Started on http://127.0.0.1:{port}")
            httpd.serve_forever()
        except OSError as e:
            # Windows error codes:
            # 10048 = WSAEADDRINUSE (port already in use)
            # 10013 = WSAEACCES (permission denied / firewall blocking)
            # Unix: 98 = EADDRINUSE, 13 = EACCES
            if e.errno in (10048, 10013, 98, 13):
                logger.warning(
                    f"[HTTP API] Port {port} unavailable (errno={e.errno}), "
                    "HTTP API disabled. MCP server will still work normally."
                )
            else:
                logger.warning(f"[HTTP API] Failed to start: {e}")
        except Exception as e:
            logger.warning(f"[HTTP API] Failed to start: {e}")

    # Start in daemon thread (won't block main process)
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    return thread


def _detect_git_email() -> str | None:
    """Auto-detect email from git config (cross-platform)."""
    import shutil
    import subprocess

    git = shutil.which("git")
    if not git:
        return None
    try:
        result = subprocess.run(  # noqa: S603
            [git, "config", "user.email"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        email = result.stdout.strip()
        return email if email and "@" in email else None
    except Exception:
        return None


def main():
    """Run the MCP server."""

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    settings = load_settings()

    # Get email: CLI arg → settings/env → git config → default
    email: str | None = None
    if len(sys.argv) > 1:
        email = sys.argv[1]
    else:
        email = settings.ncbi_email.strip() if "ncbi_email" in settings.model_fields_set else None
        if not email:
            email = _detect_git_email()
            if email:
                logger.info(f"Using git config email: {email}")
            else:
                email = DEFAULT_EMAIL
                logger.info(f"No email configured, using default: {email}")

    # Get API key: CLI arg → settings/env
    api_key = sys.argv[2] if len(sys.argv) > 2 else (settings.ncbi_api_key or None)

    http_api_port = settings.http_api_port

    # Create server
    configured_workspace_dir = getattr(settings, "workspace_dir", None)
    workspace_dir = str(configured_workspace_dir).strip() if configured_workspace_dir else None
    if not workspace_dir:
        workspace_dir = os.environ.get("PUBMED_WORKSPACE_DIR", "").strip() or None

    server = create_server(
        email=email,
        api_key=api_key,
        data_dir=settings.data_dir,  # tenant-ok: root for the session registry, which splits per tenant
        workspace_dir=workspace_dir,
    )

    # Start background HTTP API for MCP-to-MCP communication
    # This runs alongside the stdio MCP server
    container = get_container()
    start_http_api_background(
        container.session_manager(),
        container.searcher(),
        port=http_api_port,
    )

    # Run stdio MCP server (blocks)
    server.run()


if __name__ == "__main__":
    main()
