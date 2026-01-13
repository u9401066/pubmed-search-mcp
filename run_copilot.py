#!/usr/bin/env python3
"""
PubMed Search MCP Server - Copilot Studio Mode

Simple launcher for Microsoft Copilot Studio integration.
Includes middleware to handle Copilot Studio compatibility issues.

Usage:
    python run_copilot.py
    python run_copilot.py --port 8765
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from pubmed_search.mcp.server import create_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


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
    parser.add_argument("--email", default=os.environ.get("NCBI_EMAIL", "pubmed-search@example.com"))
    parser.add_argument("--api-key", default=os.environ.get("NCBI_API_KEY"))
    parser.add_argument("--stateless", action="store_true", default=True,
                       help="Use stateless mode (no session, recommended for Copilot Studio)")
    args = parser.parse_args()

    logger.info("Creating PubMed Search MCP Server for Copilot Studio...")
    # Copilot Studio compatibility settings (matching Microsoft's official samples):
    # - json_response=True: Return JSON instead of SSE streams
    # - stateless_http=True: No session management (sessionIdGenerator: undefined)
    server = create_server(
        email=args.email, 
        api_key=args.api_key, 
        disable_security=True,
        json_response=True,
        stateless_http=args.stateless  # Microsoft 官方範例使用 stateless 模式
    )
    
    # Get the streamable-http app directly from FastMCP
    # This includes lifespan handling and the /mcp endpoint
    app = server.streamable_http_app()
    
    # Wrap with Copilot Studio compatibility middleware
    app = CopilotStudioMiddleware(app)
    
    logger.info(f"")
    logger.info(f"═══════════════════════════════════════════════════════")
    logger.info(f"  PubMed Search MCP - Copilot Studio Ready")
    logger.info(f"═══════════════════════════════════════════════════════")
    logger.info(f"  Local:  http://{args.host}:{args.port}/mcp")
    logger.info(f"  ngrok:  https://kmuh-ai.ngrok.dev/mcp")
    logger.info(f"  Mode:   {'Stateless' if args.stateless else 'Stateful'} (json_response=True)")
    logger.info(f"  Middleware: 202→200 conversion enabled")
    logger.info(f"═══════════════════════════════════════════════════════")
    logger.info(f"")
    
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
