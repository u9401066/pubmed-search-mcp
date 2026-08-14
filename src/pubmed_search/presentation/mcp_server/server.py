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
import ipaddress
import logging
import os
import sys
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from pubmed_search import __version__
from pubmed_search.application.session.registry import SessionManagerRegistry
from pubmed_search.container import ApplicationContainer
from pubmed_search.shared.settings import DEFAULT_DATA_DIR, DEFAULT_EMAIL, load_settings

from .auth import build_auth
from .http_security import is_allowed_host, is_allowed_origin
from .instructions import SERVER_INSTRUCTIONS
from .tenancy import build_tenancy_middleware
from .tool_registry import register_all_mcp_tools
from .tools._common import get_session_manager, set_session_registry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from starlette.applications import Starlette

    from pubmed_search.application.session.manager import SessionManager
    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)

# ── Module-level DI container ──────────────────────────────────────────────
_container: ApplicationContainer | None = None

_TRANSPORT_OPTIONS_ATTR = "_pubmed_transport_options"

ServerMode = Literal["local", "service"]

_LOCAL_ALLOWED_HOSTS = (
    "127.0.0.1",
    "127.0.0.1:*",
    "localhost",
    "localhost:*",
    "[::1]",
    "[::1]:*",
)
_LOCAL_ALLOWED_ORIGINS = (
    "http://127.0.0.1",
    "http://127.0.0.1:*",
    "http://localhost",
    "http://localhost:*",
    "https://127.0.0.1",
    "https://127.0.0.1:*",
    "https://localhost",
    "https://localhost:*",
)


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
    mode: ServerMode = "local"
    allow_container_bind: bool = False


def _is_loopback_host(host: str) -> bool:
    """Return whether *host* is a loopback-only bind target."""
    normalized = host.strip().lower().removeprefix("[").removesuffix("]")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


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

    if options.mode == "local" and not _is_loopback_host(host) and not options.allow_container_bind:
        msg = (
            "Local server mode only binds loopback addresses. Use --mode service for remote access, "
            "or explicitly enable PUBMED_LOCAL_ALLOW_CONTAINER_BIND for a loopback-published container."
        )
        raise RuntimeError(msg)

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
            # Shutdown: close source-owned clients and the shared httpx client.
            from pubmed_search.infrastructure.sources import close_source_clients
            from pubmed_search.shared.async_utils import close_shared_async_client

            if scheduler is not None:
                scheduler.shutdown()
            await close_source_clients()
            await close_shared_async_client()
            logger.info("Lifecycle: shutdown - source and shared HTTP clients closed")

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
    mode: ServerMode | None = None,
    allow_container_bind: bool | None = None,
) -> MCPServer[Any]:
    """
    Create and configure the PubMed Search MCP server.

    Uses :class:`~pubmed_search.container.ApplicationContainer` for
    dependency injection and lifecycle management.

    Args:
        email: Email address for NCBI Entrez API (required by NCBI).
        api_key: Optional NCBI API key for higher rate limits.
        name: Server name.
        disable_security: Disable DNS rebinding protection in local development only.
        data_dir: Directory for session data persistence. Default: ~/.pubmed-search-mcp
        workspace_dir: Explicit workspace root for workspace-scoped pipeline storage.
            When omitted, workspace-scoped pipeline persistence is disabled.
        json_response: Use JSON responses instead of SSE (for Copilot Studio compatibility).
        stateless_http: Use stateless HTTP mode (no session management, for Copilot Studio).
        mode: ``"local"`` for stdio/loopback single-user use or ``"service"``
            for authenticated multi-tenant HTTP.
        allow_container_bind: Permit a local-mode all-interface bind only when
            a container port is published to host loopback.

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
    effective_mode: ServerMode = mode or settings.server_mode

    # ── Authentication ──────────────────────────────────────────────────
    token_verifier, auth_settings = build_auth(settings)
    if token_verifier is not None:
        logger.info("Bearer auth enabled for %d principal(s)", len(token_verifier))
    elif settings.auth_required:
        msg = "PUBMED_AUTH_REQUIRED is set but PUBMED_AUTH_TOKENS is empty; refusing to start unauthenticated."
        raise RuntimeError(msg)

    if effective_mode == "service":
        if disable_security:
            msg = "Service mode forbids --no-security. Configure explicit Host and Origin allowlists instead."
            raise RuntimeError(msg)
        if token_verifier is None:
            msg = "Service mode requires PUBMED_AUTH_TOKENS; refusing to start an anonymous multi-user server."
            raise RuntimeError(msg)
        if not settings.auth_resource_server_url:
            msg = "Service mode requires PUBMED_AUTH_RESOURCE_SERVER_URL pointing to the public MCP endpoint."
            raise RuntimeError(msg)
        if not settings.tenant_isolation:
            msg = "Service mode requires PUBMED_TENANT_ISOLATION=true."
            raise RuntimeError(msg)
        if not settings.allowed_hosts or not settings.allowed_origins:
            msg = "Service mode requires non-empty PUBMED_ALLOWED_HOSTS and PUBMED_ALLOWED_ORIGINS allowlists."
            raise RuntimeError(msg)

    # ── Transport security ──────────────────────────────────────────────
    if disable_security:
        transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
        logger.warning("DNS rebinding protection disabled for local development")
    else:
        allowed_hosts = settings.allowed_hosts or _LOCAL_ALLOWED_HOSTS
        allowed_origins = settings.allowed_origins or _LOCAL_ALLOWED_ORIGINS
        transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(allowed_hosts),
            allowed_origins=list(allowed_origins),
        )

    # Always install a registry. Trusted local HTTP and stdio share its durable
    # default tenant; authenticated service callers receive isolated tenants.
    tenant_registry = SessionManagerRegistry(
        data_dir or DEFAULT_DATA_DIR,
        default_manager=session_manager,
    )
    tenancy_middleware = build_tenancy_middleware(
        isolation_enabled=settings.tenant_isolation,
        max_concurrency=settings.tenant_max_concurrency,
        registry=tenant_registry,
        trusted_local_http=effective_mode == "local",
    )

    # ── Create MCP server with lifespan ─────────────────────────────────
    mcp: MCPServer[Any] = MCPServer(
        name,
        instructions=SERVER_INSTRUCTIONS,
        version=__version__,
        lifespan=_make_lifespan(_container),
        token_verifier=token_verifier,
        auth=auth_settings,
        middleware=[tenancy_middleware],
    )
    setattr(
        mcp,
        _TRANSPORT_OPTIONS_ATTR,
        TransportOptions(
            json_response=json_response,
            stateless_http=stateless_http,
            transport_security=transport_security,
            mode=effective_mode,
            allow_container_bind=(
                settings.local_allow_container_bind if allow_container_bind is None else allow_container_bind
            ),
        ),
    )

    # ── Register all tools via centralized registry ─────────────────────
    stats = register_all_mcp_tools(
        mcp=mcp,
        searcher=searcher,
        session_manager=session_manager,
        strategy_generator=strategy_generator,
        workspace_dir=workspace_dir,
        session_registry=tenant_registry,
    )
    logger.info("Tool registration complete: %s", stats)

    # ── Per-tenant session isolation ────────────────────────────────────
    # Installed after registration: register_all_mcp_tools() calls
    # set_session_manager(), which intentionally clears any process accessor.
    # Session closures already hold this registry through explicit injection.
    set_session_registry(tenant_registry)
    if settings.tenant_isolation:
        logger.info("Tenant isolation enabled (max %d concurrent requests per tenant)", settings.tenant_max_concurrency)
        if token_verifier is None and effective_mode == "local":
            logger.warning(
                "Local mode has no auth. Loopback HTTP and stdio share the single-user durable tenant; "
                "never expose this mode beyond the trusted local boundary."
            )
    else:
        logger.info("Caller isolation disabled; local transports share the durable default tenant")

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
    background_transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(_LOCAL_ALLOWED_HOSTS),
        allowed_origins=list(_LOCAL_ALLOWED_ORIGINS),
    )

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
            origin = self.headers.get("Origin")
            if origin and is_allowed_origin(origin, background_transport_security):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def _reject_untrusted_request(self) -> bool:
            if not is_allowed_host(self.headers.get("Host"), background_transport_security):
                self._send_json({"detail": "Invalid Host header"}, 421)
                return True
            if not is_allowed_origin(self.headers.get("Origin"), background_transport_security):
                self._send_json({"detail": "Invalid Origin header"}, 403)
                return True
            return False

        def do_GET(self):
            if self._reject_untrusted_request():
                return
            path = self.path

            # Health check
            if path == "/health":
                self._send_json({"status": "ok", "service": "pubmed-search-mcp-api"})
                return

            # Get single cached article
            if path.startswith("/api/cached_article/"):
                pmid = path.split("/")[-1].split("?")[0]
                cached_article = session_manager.get_cached_article(pmid)
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
                self._send_json(session_manager.get_session_summary())
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

    from pubmed_search.shared.logging_utils import harden_http_client_logging

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    harden_http_client_logging()

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
                logger.info("Using contact email from git config")
            else:
                email = DEFAULT_EMAIL
                logger.info("No contact email configured; using the packaged default")

    # Get API key: CLI arg → settings/env
    api_key = sys.argv[2] if len(sys.argv) > 2 else (settings.ncbi_api_key or None)

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
        mode="local",
    )

    # The stdio contract is local-only by default. The legacy auxiliary HTTP
    # bridge must be explicitly requested because it opens another API surface.
    if settings.stdio_aux_http_enabled:
        container = get_container()
        installed_session_manager = get_session_manager() or container.session_manager()
        start_http_api_background(
            installed_session_manager,
            container.searcher(),
            port=settings.http_api_port,
        )

    # Run stdio MCP server (blocks)
    server.run()


if __name__ == "__main__":
    main()
