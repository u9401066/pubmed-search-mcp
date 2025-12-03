#!/usr/bin/env python3
"""
PubMed Search MCP Server - HTTP Mode

This script runs the PubMed Search MCP server in HTTP mode (SSE or streamable-http),
allowing remote clients from other machines to connect.

Usage:
    # Run with SSE transport (default, more compatible)
    python run_server.py --transport sse --port 8765
    
    # Run with streamable-http transport
    python run_server.py --transport streamable-http --port 8765
    
    # Run with custom email and API key
    python run_server.py --email your@email.com --api-key YOUR_API_KEY

Environment Variables:
    NCBI_EMAIL: Email for NCBI Entrez API
    NCBI_API_KEY: Optional API key for higher rate limits
    MCP_PORT: Server port (default: 8765)
    MCP_HOST: Server host (default: 0.0.0.0)
"""

import argparse
import logging
import os
import sys

# Add src to path for development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from pubmed_search.mcp.server import create_server

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Run PubMed Search MCP Server in HTTP mode"
    )
    parser.add_argument(
        "--email", 
        default=os.environ.get("NCBI_EMAIL", "pubmed-search@example.com"),
        help="Email for NCBI Entrez API (required by NCBI)"
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("NCBI_API_KEY"),
        help="Optional NCBI API key for higher rate limits"
    )
    parser.add_argument(
        "--transport",
        choices=["sse", "streamable-http"],
        default="sse",
        help="Transport protocol (default: sse)"
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MCP_HOST", "0.0.0.0"),
        help="Server host (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_PORT", "8765")),
        help="Server port (default: 8765)"
    )
    parser.add_argument(
        "--no-security",
        action="store_true",
        default=True,
        help="Disable DNS rebinding protection (default: True for remote access)"
    )
    
    args = parser.parse_args()
    
    # Create server
    logger.info(f"Creating PubMed Search MCP Server...")
    logger.info(f"  Email: {args.email}")
    logger.info(f"  API Key: {'Set' if args.api_key else 'Not set'}")
    logger.info(f"  Transport: {args.transport}")
    logger.info(f"  Host: {args.host}")
    logger.info(f"  Port: {args.port}")
    logger.info(f"  DNS Rebinding Protection: {'Disabled' if args.no_security else 'Enabled'}")
    
    server = create_server(email=args.email, api_key=args.api_key, disable_security=args.no_security)
    
    # Run server with selected transport
    logger.info(f"Starting server at http://{args.host}:{args.port}")
    
    if args.transport == "sse":
        logger.info("SSE endpoint: /sse")
        logger.info("Message endpoint: /messages")
    else:
        logger.info("Streamable HTTP endpoint: /mcp")
    
    # Run the server using uvicorn directly for proper host/port control
    import uvicorn
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route, Mount
    
    if args.transport == "sse":
        mcp_app = server.sse_app()
    else:
        mcp_app = server.streamable_http_app()
    
    # Add health check and info endpoints
    async def health(request):
        return JSONResponse({"status": "ok", "service": "pubmed-search-mcp"})
    
    async def info(request):
        return JSONResponse({
            "service": "PubMed Search MCP Server",
            "version": "0.1.0",
            "transport": args.transport,
            "endpoints": {
                "sse": "/sse",
                "messages": "/messages",
                "health": "/health"
            },
            "usage": {
                "vscode_mcp_json": {
                    "type": "sse",
                    "url": f"http://YOUR_SERVER_IP:{args.port}/sse"
                }
            }
        })
    
    # Add middleware to handle host header issues
    from starlette.middleware import Middleware
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    
    # Combine routes
    routes = [
        Route("/", info),
        Route("/health", health),
        Mount("/", app=mcp_app),
    ]
    
    # Allow all hosts
    app = Starlette(routes=routes)
    
    # Run with settings to accept any host
    uvicorn.run(
        app, 
        host=args.host, 
        port=args.port,
        proxy_headers=True,
        forwarded_allow_ips="*",
        server_header=False
    )


if __name__ == "__main__":
    main()
