#!/usr/bin/env python3
"""
PubMed Search MCP Server - Copilot Studio Mode

Simple launcher for Microsoft Copilot Studio integration.
Includes middleware and simplified tool schemas for compatibility.

⚠️ Copilot Studio Known Limitations (as of 2025):
- Schema truncation with anyOf/oneOf (multi-type arrays)
- exclusiveMinimum must be boolean, not integer
- Reference types ($ref) not supported
- Enum inputs interpreted as string

This launcher uses a simplified tool set with single-type parameters.

Usage:
    python run_copilot.py
    python run_copilot.py --port 8765
    python run_copilot.py --full-tools  # Use all tools (may have issues)
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from pubmed_search.mcp_server.server import DEFAULT_EMAIL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def create_copilot_server(email: str, api_key: str = None, use_full_tools: bool = False):
    """
    Create MCP server optimized for Copilot Studio.
    
    Args:
        email: NCBI email
        api_key: NCBI API key (optional)
        use_full_tools: If True, use all tools (may have schema issues)
                       If False, use simplified Copilot-compatible tools
    
    Returns:
        FastMCP server instance
    """
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings
    from pubmed_search.entrez import LiteratureSearcher
    from pubmed_search.session import SessionManager
    from pubmed_search.mcp_server.tools._common import set_session_manager, set_strategy_generator
    
    logger.info("Initializing PubMed Search MCP Server (Copilot Studio mode)...")
    
    # Initialize core components
    searcher = LiteratureSearcher(email=email, api_key=api_key)
    
    from pubmed_search.entrez.strategy import SearchStrategyGenerator
    strategy_generator = SearchStrategyGenerator(email=email, api_key=api_key)
    
    session_manager = SessionManager()
    
    # Create MCP server with Copilot Studio settings
    mcp = FastMCP(
        "pubmed-search-copilot",
        instructions="""PubMed Search MCP Server - Copilot Studio Edition

Available tools:
- search_pubmed: Search for scientific literature
- get_article: Get article details by PMID
- find_related: Find related articles
- find_citations: Find articles that cite a paper
- get_references: Get reference list of an article
- analyze_clinical_question: Parse PICO elements
- expand_search_terms: Get MeSH terms and synonyms
- get_fulltext: Get full text from Europe PMC
- export_citations: Export in RIS/BibTeX/CSV format
- search_gene: Search NCBI Gene database
- search_compound: Search PubChem compounds
""",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
        json_response=True,
        stateless_http=True,  # Required for Copilot Studio
    )
    
    # Set global references
    set_session_manager(session_manager)
    set_strategy_generator(strategy_generator)
    
    # Register tools
    if use_full_tools:
        logger.warning("Using FULL tool set - may have schema compatibility issues!")
        from pubmed_search.mcp_server.tools import register_all_tools
        from pubmed_search.mcp_server.session_tools import register_session_tools, register_session_resources
        register_all_tools(mcp, searcher)
        register_session_tools(mcp, session_manager)
        register_session_resources(mcp, session_manager)
    else:
        logger.info("Using SIMPLIFIED Copilot-compatible tool set")
        from pubmed_search.mcp_server.copilot_tools import register_copilot_compatible_tools
        register_copilot_compatible_tools(mcp, searcher)
    
    # Store references
    mcp._pubmed_session_manager = session_manager
    mcp._searcher = searcher
    mcp._strategy_generator = strategy_generator
    
    return mcp


class CopilotStudioMiddleware:
    """
    Middleware to handle Copilot Studio compatibility issues:
    1. Convert 202 Accepted to 200 OK with empty JSON object
    2. Log all requests for debugging
    """
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        # Capture the response status
        response_started = False
        original_status = 200
        
        async def send_wrapper(message):
            nonlocal response_started, original_status
            
            if message["type"] == "http.response.start":
                response_started = True
                original_status = message.get("status", 200)
                
                # Convert 202 Accepted to 200 OK for Copilot Studio
                if original_status == 202:
                    logger.info("Converting 202 Accepted to 200 OK for Copilot Studio")
                    message = dict(message)  # Make mutable copy
                    message["status"] = 200
                    # Also need to set content-length for the empty body
                    headers = list(message.get("headers", []))
                    # Update content-length to 2 for "{}"
                    headers = [(k, v) for k, v in headers if k.lower() != b"content-length"]
                    headers.append((b"content-length", b"2"))
                    message["headers"] = headers
            
            elif message["type"] == "http.response.body":
                # If we converted 202 to 200, return empty JSON object
                if original_status == 202:
                    message = dict(message)
                    message["body"] = b"{}"
            
            await send(message)
        
        await self.app(scope, receive, send_wrapper)


def main():
    parser = argparse.ArgumentParser(description="Run PubMed Search MCP for Copilot Studio")
    parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_PORT", "8765")))
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "0.0.0.0"))
    parser.add_argument("--email", default=os.environ.get("NCBI_EMAIL", DEFAULT_EMAIL))
    parser.add_argument("--api-key", default=os.environ.get("NCBI_API_KEY"))
    parser.add_argument("--full-tools", action="store_true", default=False,
                       help="Use full tool set (may have schema issues with Copilot Studio)")
    args = parser.parse_args()

    logger.info("Creating PubMed Search MCP Server for Copilot Studio...")
    
    # Create server with appropriate tool set
    server = create_copilot_server(
        email=args.email, 
        api_key=args.api_key,
        use_full_tools=args.full_tools
    )
    
    # Get the streamable-http app directly from FastMCP
    app = server.streamable_http_app()
    
    # Wrap with Copilot Studio compatibility middleware
    app = CopilotStudioMiddleware(app)
    
    # Get tool count for display
    tool_count = len(server._tool_manager.list_tools())
    tool_mode = "FULL (may have issues)" if args.full_tools else "SIMPLIFIED (Copilot-compatible)"
    
    logger.info("")
    logger.info("═══════════════════════════════════════════════════════")
    logger.info("  PubMed Search MCP - Copilot Studio Ready")
    logger.info("═══════════════════════════════════════════════════════")
    logger.info(f"  Local:  http://{args.host}:{args.port}/mcp")
    logger.info("  ngrok:  https://kmuh-ai.ngrok.dev/mcp")
    logger.info(f"  Tools:  {tool_count} ({tool_mode})")
    logger.info("  Mode:   Stateless HTTP (json_response=True)")
    logger.info("  Middleware: 202→200 conversion enabled")
    logger.info("═══════════════════════════════════════════════════════")
    logger.info("")
    
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
