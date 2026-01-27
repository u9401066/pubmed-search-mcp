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
"""

import logging
import os
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from pubmed_search.application.session.manager import SessionManager
from pubmed_search.infrastructure.ncbi import LiteratureSearcher

from .instructions import SERVER_INSTRUCTIONS
from .tool_registry import register_all_mcp_tools

logger = logging.getLogger(__name__)

DEFAULT_EMAIL = "pubmed-search@example.com"
DEFAULT_DATA_DIR = os.path.expanduser("~/.pubmed-search-mcp")


def create_server(
    email: str = DEFAULT_EMAIL,
    api_key: Optional[str] = None,
    name: str = "pubmed-search",
    disable_security: bool = False,
    data_dir: Optional[str] = None,
    json_response: bool = False,
    stateless_http: bool = False,
) -> FastMCP:
    """
    Create and configure the PubMed Search MCP server.

    Args:
        email: Email address for NCBI Entrez API (required by NCBI).
        api_key: Optional NCBI API key for higher rate limits.
        name: Server name.
        disable_security: Disable DNS rebinding protection (needed for remote access).
        data_dir: Directory for session data persistence. Default: ~/.pubmed-search-mcp
        json_response: Use JSON responses instead of SSE (for Copilot Studio compatibility).
        stateless_http: Use stateless HTTP mode (no session management, for Copilot Studio).

    Returns:
        Configured FastMCP server instance.
    """
    logger.info("Initializing PubMed Search MCP Server...")

    # Initialize searcher
    searcher = LiteratureSearcher(email=email, api_key=api_key)

    # Initialize strategy generator for intelligent query generation
    from pubmed_search.infrastructure.ncbi.strategy import SearchStrategyGenerator

    strategy_generator = SearchStrategyGenerator(email=email, api_key=api_key)
    logger.info("Strategy generator initialized (ESpell + MeSH)")

    # Initialize session manager
    session_data_dir = data_dir or DEFAULT_DATA_DIR
    session_manager = SessionManager(data_dir=session_data_dir)
    logger.info(f"Session data directory: {session_data_dir}")

    # Configure transport security
    # Disable DNS rebinding protection for remote access
    if disable_security:
        transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )
        logger.info("DNS rebinding protection disabled for remote access")
    else:
        transport_security = None

    # Create MCP server
    mcp = FastMCP(
        name,
        instructions=SERVER_INSTRUCTIONS,
        transport_security=transport_security,
        json_response=json_response,
        stateless_http=stateless_http,  # Stateless mode for Copilot Studio
    )

    # Register all tools via centralized registry
    stats = register_all_mcp_tools(
        mcp=mcp,
        searcher=searcher,
        session_manager=session_manager,
        strategy_generator=strategy_generator,
    )
    logger.info(f"Tool registration complete: {stats}")

    # Store references for later use
    # Note: Use _pubmed_session_manager to avoid conflicting with FastMCP's _session_manager
    # which is used by streamable_http_app() for StreamableHTTPSessionManager
    mcp._pubmed_session_manager = session_manager
    mcp._searcher = searcher
    mcp._strategy_generator = strategy_generator

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

    class MCPAPIHandler(BaseHTTPRequestHandler):
        """Simple HTTP handler for MCP-to-MCP API."""

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
                session = session_manager.get_current_session()

                if session and pmid in session.article_cache:
                    self._send_json(
                        {
                            "source": "pubmed",
                            "verified": True,
                            "data": session.article_cache[pmid],
                        }
                    )
                    return

                # Try to fetch if not in cache
                if searcher:
                    try:
                        articles = searcher.fetch_details([pmid])
                        if articles:
                            session_manager.add_to_cache(articles)
                            self._send_json(
                                {
                                    "source": "pubmed",
                                    "verified": True,
                                    "data": articles[0],
                                }
                            )
                            return
                    except Exception as e:
                        self._send_json({"detail": f"PubMed API error: {str(e)}"}, 502)
                        return

                self._send_json({"detail": f"Article PMID:{pmid} not found"}, 404)
                return

            # Get session summary
            if path == "/api/session/summary":
                self._send_json(session_manager.get_session_summary())
                return

            # Root - API info
            if path == "/" or path == "":
                self._send_json(
                    {
                        "service": "pubmed-search-mcp HTTP API",
                        "mode": "background (stdio MCP + HTTP API)",
                        "endpoints": {
                            "/health": "Health check",
                            "/api/cached_article/{pmid}": "Get cached article",
                            "/api/session/summary": "Session info",
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


def main():
    """Run the MCP server."""
    import os

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Get email from args or environment
    if len(sys.argv) > 1:
        email = sys.argv[1]
    else:
        email = os.environ.get("NCBI_EMAIL", DEFAULT_EMAIL)

    # Get API key from args or environment
    if len(sys.argv) > 2:
        api_key = sys.argv[2]
    else:
        api_key = os.environ.get("NCBI_API_KEY")

    # Get HTTP API port from environment (default: 8765)
    http_api_port = int(os.environ.get("PUBMED_HTTP_API_PORT", "8765"))

    # Create server
    server = create_server(email=email, api_key=api_key)

    # Start background HTTP API for MCP-to-MCP communication
    # This runs alongside the stdio MCP server
    start_http_api_background(
        server._pubmed_session_manager, server._searcher, port=http_api_port
    )

    # Run stdio MCP server (blocks)
    server.run()


if __name__ == "__main__":
    main()
