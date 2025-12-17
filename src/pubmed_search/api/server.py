"""
HTTP API Server for MCP-to-MCP communication.

This server runs alongside the MCP server and provides direct HTTP access
to cached article data. Other MCP servers (like mdpaper) can call these
endpoints directly without going through the Agent.

Author: u9401066@gap.kmu.edu.tw
"""

import logging
import os
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..session import SessionManager
from ..entrez import LiteratureSearcher

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_EMAIL = "u9401066@gap.kmu.edu.tw"
DEFAULT_DATA_DIR = os.path.expanduser("~/.pubmed-search-mcp")
DEFAULT_API_PORT = 8765


# Pydantic models for API responses
class ArticleResponse(BaseModel):
    """Response model for cached article."""
    source: str = "pubmed"
    verified: bool = True
    data: Dict[str, Any]


class ErrorResponse(BaseModel):
    """Error response model."""
    detail: str


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    session_count: int
    cached_articles: int


# Global instances (initialized on startup)
_session_manager: Optional[SessionManager] = None
_searcher: Optional[LiteratureSearcher] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global _session_manager, _searcher
    
    # Startup
    email = os.environ.get("NCBI_EMAIL", DEFAULT_EMAIL)
    api_key = os.environ.get("NCBI_API_KEY")
    data_dir = os.environ.get("PUBMED_DATA_DIR", DEFAULT_DATA_DIR)
    
    logger.info(f"Initializing HTTP API server with email: {email}")
    logger.info(f"Session data directory: {data_dir}")
    
    _session_manager = SessionManager(data_dir=data_dir)
    _searcher = LiteratureSearcher(email=email, api_key=api_key)
    
    logger.info("HTTP API server initialized")
    
    yield
    
    # Shutdown
    logger.info("HTTP API server shutting down")


def create_api_server(
    email: str = DEFAULT_EMAIL,
    api_key: Optional[str] = None,
    data_dir: Optional[str] = None
) -> FastAPI:
    """
    Create the FastAPI server for MCP-to-MCP communication.
    
    Args:
        email: Email for NCBI API (required by NCBI).
        api_key: Optional NCBI API key.
        data_dir: Session data directory.
        
    Returns:
        Configured FastAPI instance.
    """
    global _session_manager, _searcher
    
    app = FastAPI(
        title="PubMed Search API",
        description="HTTP API for MCP-to-MCP communication. "
                    "Allows other MCP servers to access cached article data directly.",
        version="1.0.0",
        lifespan=lifespan
    )
    
    # Add CORS middleware for local development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Allow all origins for MCP-to-MCP
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Initialize instances if not using lifespan
    if data_dir:
        _session_manager = SessionManager(data_dir=data_dir)
    if email:
        _searcher = LiteratureSearcher(email=email, api_key=api_key)
    
    return app


# Create the app instance
app = create_api_server()


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    if not _session_manager:
        return HealthResponse(status="initializing", session_count=0, cached_articles=0)
    
    sessions = _session_manager.list_sessions()
    current = _session_manager.get_current_session()
    cached_count = len(current.article_cache) if current else 0
    
    return HealthResponse(
        status="healthy",
        session_count=len(sessions),
        cached_articles=cached_count
    )


@app.get(
    "/api/cached_article/{pmid}",
    response_model=ArticleResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Article not found in cache"}
    }
)
async def get_cached_article(
    pmid: str,
    fetch_if_missing: bool = Query(
        default=True,
        description="If True, fetch from PubMed if not in cache"
    )
):
    """
    Get cached article by PMID.
    
    This endpoint is designed for MCP-to-MCP communication.
    Other MCP servers (like mdpaper) can call this directly to get
    verified PubMed data without going through the Agent.
    
    Args:
        pmid: PubMed ID
        fetch_if_missing: If True, fetch from PubMed API if not cached
        
    Returns:
        ArticleResponse with verified PubMed data
        
    Raises:
        404: If article not found and fetch_if_missing is False
    """
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Server not initialized")
    
    # Try to get from cache first
    session = _session_manager.get_current_session()
    if session and pmid in session.article_cache:
        logger.info(f"Cache hit for PMID {pmid}")
        return ArticleResponse(
            source="pubmed",
            verified=True,
            data=session.article_cache[pmid]
        )
    
    # Not in cache - try to fetch if requested
    if fetch_if_missing and _searcher:
        logger.info(f"Cache miss for PMID {pmid}, fetching from PubMed")
        try:
            articles = _searcher.fetch_details([pmid])
            if articles:
                article = articles[0]
                # Cache the result
                _session_manager.add_to_cache([article])
                return ArticleResponse(
                    source="pubmed",
                    verified=True,
                    data=article
                )
        except Exception as e:
            logger.error(f"Failed to fetch PMID {pmid}: {e}")
            raise HTTPException(status_code=502, detail=f"PubMed API error: {str(e)}")
    
    raise HTTPException(
        status_code=404,
        detail=f"Article PMID:{pmid} not found in cache. "
               "Please search for it first using pubmed-search MCP."
    )


@app.get("/api/cached_articles")
async def get_multiple_cached_articles(
    pmids: str = Query(..., description="Comma-separated PMIDs"),
    fetch_if_missing: bool = Query(default=False)
):
    """
    Get multiple cached articles by PMIDs.
    
    Args:
        pmids: Comma-separated list of PMIDs
        fetch_if_missing: If True, fetch missing articles from PubMed
        
    Returns:
        Dict with found and missing articles
    """
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Server not initialized")
    
    pmid_list = [p.strip() for p in pmids.split(",") if p.strip()]
    
    found = {}
    missing = []
    
    session = _session_manager.get_current_session()
    
    for pmid in pmid_list:
        if session and pmid in session.article_cache:
            found[pmid] = session.article_cache[pmid]
        else:
            missing.append(pmid)
    
    # Optionally fetch missing
    if fetch_if_missing and missing and _searcher:
        try:
            articles = _searcher.fetch_details(missing)
            for article in articles:
                pmid = article.get('pmid', '')
                if pmid:
                    found[pmid] = article
                    missing.remove(pmid)
            # Cache newly fetched
            _session_manager.add_to_cache(articles)
        except Exception as e:
            logger.warning(f"Failed to fetch some articles: {e}")
    
    return {
        "found": found,
        "missing": missing,
        "total_requested": len(pmid_list),
        "total_found": len(found)
    }


@app.get("/api/session/summary")
async def get_session_summary():
    """Get current session summary including all cached PMIDs."""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Server not initialized")
    
    return _session_manager.get_session_summary()


def run_api_server(
    host: str = "127.0.0.1",
    port: int = DEFAULT_API_PORT,
    email: str = DEFAULT_EMAIL,
    api_key: Optional[str] = None,
    data_dir: Optional[str] = None
):
    """
    Run the HTTP API server.
    
    Args:
        host: Host to bind to (default: 127.0.0.1 for local only)
        port: Port to bind to (default: 8765)
        email: NCBI email
        api_key: NCBI API key
        data_dir: Session data directory
    """
    import uvicorn
    
    # Set environment variables for lifespan
    os.environ["NCBI_EMAIL"] = email
    if api_key:
        os.environ["NCBI_API_KEY"] = api_key
    if data_dir:
        os.environ["PUBMED_DATA_DIR"] = data_dir
    
    logger.info(f"Starting HTTP API server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="PubMed Search HTTP API Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=DEFAULT_API_PORT, help="Port to bind to")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help="NCBI email")
    parser.add_argument("--api-key", help="NCBI API key")
    parser.add_argument("--data-dir", help="Session data directory")
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    run_api_server(
        host=args.host,
        port=args.port,
        email=args.email,
        api_key=args.api_key,
        data_dir=args.data_dir
    )
