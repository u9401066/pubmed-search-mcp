"""
PubMed Search MCP Server

A standalone Model Context Protocol server for PubMed literature search.
Can be used independently or integrated into other MCP servers.

Features:
- Literature search with various filters
- Article caching to avoid redundant API calls
- Research session management for Agent context
- Reading list management
"""

import logging
import os
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from ..entrez import LiteratureSearcher
from ..session import SessionManager
from .tools import register_all_tools, set_session_manager, set_strategy_generator
from .session_tools import register_session_tools, register_session_resources

logger = logging.getLogger(__name__)

SERVER_INSTRUCTIONS = """
PubMed Search MCP Server - AI Agent 的文獻搜尋助理

## 🔍 搜尋工具

### 基本搜尋
- search_literature: 搜尋 PubMed 文獻
- find_related_articles: 尋找相關文章 (by PMID)
- find_citing_articles: 尋找引用文章 (by PMID)
- fetch_article_details: 取得文章詳細資訊

### 批次搜尋 (系統性文獻回顧)
- generate_search_queries: 產生多個搜尋策略
- merge_search_results: 合併去重搜尋結果
- expand_search_queries: 擴展搜尋策略

---

## 📋 使用流程

### 快速搜尋
```
search_literature(query="topic", limit=10)
```

### 深入探索 (找到重要論文後)
```
find_related_articles(pmid="12345678")  # 相關文章
find_citing_articles(pmid="12345678")   # 後續研究
```

### 系統性搜尋 (文獻回顧)
```
1. generate_search_queries(topic="research question")
2. 並行呼叫 search_literature() (每個 query 各一次)
3. merge_search_results(results_json="{...}")
4. expand_search_queries() 若需更多
```

---

NOTE: Cache 和 Session 是內部機制，自動運作，無需管理。
"""

DEFAULT_EMAIL = "pubmed-search@example.com"
DEFAULT_DATA_DIR = os.path.expanduser("~/.pubmed-search-mcp")


def create_server(
    email: str = DEFAULT_EMAIL,
    api_key: Optional[str] = None,
    name: str = "pubmed-search",
    disable_security: bool = False,
    data_dir: Optional[str] = None
) -> FastMCP:
    """
    Create and configure the PubMed Search MCP server.
    
    Args:
        email: Email address for NCBI Entrez API (required by NCBI).
        api_key: Optional NCBI API key for higher rate limits.
        name: Server name.
        disable_security: Disable DNS rebinding protection (needed for remote access).
        data_dir: Directory for session data persistence. Default: ~/.pubmed-search-mcp
        
    Returns:
        Configured FastMCP server instance.
    """
    logger.info("Initializing PubMed Search MCP Server...")
    
    # Initialize searcher
    searcher = LiteratureSearcher(email=email, api_key=api_key)
    
    # Initialize strategy generator for intelligent query generation
    from ..entrez.strategy import SearchStrategyGenerator
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
    mcp = FastMCP(name, instructions=SERVER_INSTRUCTIONS, transport_security=transport_security)
    
    # Set session manager and strategy generator for search tools
    set_session_manager(session_manager)
    set_strategy_generator(strategy_generator)
    
    # Register tools
    logger.info("Registering search tools...")
    register_all_tools(mcp, searcher)
    
    # Register session tools and resources
    logger.info("Registering session tools...")
    register_session_tools(mcp, session_manager)
    register_session_resources(mcp, session_manager)
    
    # Store references for later use
    mcp._session_manager = session_manager
    mcp._searcher = searcher
    mcp._strategy_generator = strategy_generator
    
    logger.info("PubMed Search MCP Server initialized successfully")
    
    return mcp


def main():
    """Run the MCP server."""
    import os
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
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
    
    # Create and run server
    server = create_server(email=email, api_key=api_key)
    server.run()


if __name__ == "__main__":
    main()
