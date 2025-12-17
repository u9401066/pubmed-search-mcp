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
    from starlette.responses import JSONResponse, FileResponse, Response
    from starlette.routing import Route, Mount
    from pathlib import Path
    
    # Export directory
    EXPORT_DIR = Path("/tmp/pubmed_exports")
    
    if args.transport == "sse":
        mcp_app = server.sse_app()
    else:
        mcp_app = server.streamable_http_app()
    
    # Get session manager for HTTP API endpoints
    session_manager = server._mcp._session_manager
    searcher = server._mcp._searcher
    
    # Add health check and info endpoints
    async def health(request):
        return JSONResponse({"status": "ok", "service": "pubmed-search-mcp"})
    
    async def info(request):
        return JSONResponse({
            "service": "PubMed Search MCP Server",
            "version": "0.1.2",
            "transport": args.transport,
            "endpoints": {
                "mcp": {
                    "sse": "/sse",
                    "messages": "/messages"
                },
                "api": {
                    "cached_article": "/api/cached_article/{pmid}",
                    "cached_articles": "/api/cached_articles?pmids=...",
                    "session_summary": "/api/session/summary"
                },
                "utility": {
                    "health": "/health",
                    "downloads": "/download/{filename}",
                    "list_exports": "/exports"
                }
            },
            "mcp_to_mcp": {
                "description": "Other MCP servers can call /api/* endpoints directly",
                "example": f"GET http://localhost:{args.port}/api/cached_article/12345678"
            },
            "usage": {
                "vscode_mcp_json": {
                    "type": "sse",
                    "url": f"http://YOUR_SERVER_IP:{args.port}/sse"
                }
            }
        })
    
    async def list_exports(request):
        """List available export files."""
        if not EXPORT_DIR.exists():
            return JSONResponse({"files": [], "message": "No exports yet"})
        
        files = []
        for f in EXPORT_DIR.iterdir():
            if f.is_file():
                stat = f.stat()
                files.append({
                    "filename": f.name,
                    "size_bytes": stat.st_size,
                    "download_url": f"/download/{f.name}"
                })
        
        return JSONResponse({
            "export_dir": str(EXPORT_DIR),
            "files": sorted(files, key=lambda x: x["filename"], reverse=True)
        })
    
    async def download_file(request):
        """Download an export file."""
        filename = request.path_params["filename"]
        filepath = EXPORT_DIR / filename
        
        # Security: prevent directory traversal
        if ".." in filename or "/" in filename:
            return JSONResponse({"error": "Invalid filename"}, status_code=400)
        
        if not filepath.exists():
            return JSONResponse({"error": "File not found"}, status_code=404)
        
        # Determine content type
        ext = filepath.suffix.lower()
        content_types = {
            ".csv": "text/csv",
            ".ris": "application/x-research-info-systems",
            ".bib": "application/x-bibtex",
            ".json": "application/json",
            ".txt": "text/plain"
        }
        content_type = content_types.get(ext, "application/octet-stream")
        
        return FileResponse(
            str(filepath),
            media_type=content_type,
            filename=filename
        )
    
    # ===== MCP-to-MCP HTTP API Endpoints =====
    # These endpoints allow other MCP servers (like mdpaper) to access
    # cached article data directly without going through the Agent.
    
    async def api_get_cached_article(request):
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
            return JSONResponse({
                "source": "pubmed",
                "verified": True,
                "data": session.article_cache[pmid]
            })
        
        # Fetch if requested
        if fetch_if_missing and searcher:
            logger.info(f"[API] Cache miss for PMID {pmid}, fetching from PubMed")
            try:
                articles = searcher.fetch_details([pmid])
                if articles:
                    session_manager.add_to_cache(articles)
                    return JSONResponse({
                        "source": "pubmed",
                        "verified": True,
                        "data": articles[0]
                    })
            except Exception as e:
                logger.error(f"[API] Failed to fetch PMID {pmid}: {e}")
                return JSONResponse(
                    {"detail": f"PubMed API error: {str(e)}"}, 
                    status_code=502
                )
        
        return JSONResponse(
            {"detail": f"Article PMID:{pmid} not found in cache"},
            status_code=404
        )
    
    async def api_get_multiple_articles(request):
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
                articles = searcher.fetch_details(missing)
                for article in articles:
                    pmid = article.get('pmid', '')
                    if pmid:
                        found[pmid] = article
                        if pmid in missing:
                            missing.remove(pmid)
                session_manager.add_to_cache(articles)
            except Exception as e:
                logger.warning(f"[API] Failed to fetch some articles: {e}")
        
        return JSONResponse({
            "found": found,
            "missing": missing,
            "total_requested": len(pmid_list),
            "total_found": len(found)
        })
    
    async def api_session_summary(request):
        """Get current session summary for MCP-to-MCP."""
        return JSONResponse(session_manager.get_session_summary())
    
    # Add middleware to handle host header issues
    from starlette.middleware import Middleware
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    
    # Combine routes
    routes = [
        Route("/", info),
        Route("/health", health),
        Route("/exports", list_exports),
        Route("/download/{filename}", download_file),
        # MCP-to-MCP HTTP API endpoints
        Route("/api/cached_article/{pmid}", api_get_cached_article),
        Route("/api/cached_articles", api_get_multiple_articles),
        Route("/api/session/summary", api_session_summary),
        Mount("/", app=mcp_app),
    ]
    
    # Allow all hosts
    app = Starlette(routes=routes)
    
    logger.info(f"Download endpoint: http://{args.host}:{args.port}/download/{{filename}}")
    logger.info(f"List exports: http://{args.host}:{args.port}/exports")
    logger.info(f"[MCP-to-MCP API]")
    logger.info(f"  GET /api/cached_article/{{pmid}} - Get single article")
    logger.info(f"  GET /api/cached_articles?pmids=... - Get multiple articles")
    logger.info(f"  GET /api/session/summary - Get session info")
    
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
