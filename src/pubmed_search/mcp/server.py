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

═══════════════════════════════════════════════════════════════════════════════
🎯 搜尋策略選擇指南 (IMPORTANT - 請根據用戶需求選擇正確流程)
═══════════════════════════════════════════════════════════════════════════════

## 情境 1️⃣: 快速搜尋 (用戶只是想找幾篇文章看看)
───────────────────────────────────────────────────────────────────────────────
觸發條件: "幫我找...", "搜尋...", "有沒有關於..."
流程: 直接呼叫 search_literature()

範例:
```
search_literature(query="remimazolam sedation", limit=10)
```

## 情境 2️⃣: 精確搜尋 (用戶要求專業/精確/完整的搜尋)
───────────────────────────────────────────────────────────────────────────────
觸發條件: "系統性搜尋", "完整搜尋", "文獻回顧", "精確搜尋", 
          或用戶提到 MeSH、同義詞、專業搜尋策略

流程:
1. generate_search_queries(topic) → 取得 MeSH 詞彙和同義詞
2. 根據返回的 suggested_queries 選擇最佳策略
3. search_literature(query=優化後的查詢)

範例:
```
# Step 1: 取得搜尋材料
generate_search_queries("anesthesiology artificial intelligence")

# Step 2: 用 MeSH 標準化查詢 (從結果中選擇)
search_literature(query='"Artificial Intelligence"[MeSH] AND "Anesthesiology"[MeSH]')
```

## 情境 3️⃣: PICO 臨床問題搜尋 (用戶問的是比較性問題)
───────────────────────────────────────────────────────────────────────────────
觸發條件: "A比B好嗎?", "...相比...", "...對...的效果", "在...病人中..."

流程:
1. parse_pico(description) → 解析 PICO 元素
2. 對每個 PICO 元素並行呼叫 generate_search_queries()
3. 組合 Boolean 查詢: (P) AND (I) AND (C) AND (O)
4. search_literature() 執行搜尋
5. merge_search_results() 合併結果

範例:
```
# Step 1: 解析 PICO
parse_pico(description="remimazolam 在 ICU 鎮靜比 propofol 好嗎")
→ P=ICU patients, I=remimazolam, C=propofol, O=sedation outcome

# Step 2: 並行取得各元素的 MeSH
generate_search_queries("ICU patients")
generate_search_queries("remimazolam") 
generate_search_queries("propofol")

# Step 3: 組合搜尋
search_literature(query='("Intensive Care Units"[MeSH]) AND (remimazolam OR CNS7056) AND (propofol)')
```

## 情境 4️⃣: 深入探索 (用戶找到一篇重要論文，想看相關的)
───────────────────────────────────────────────────────────────────────────────
觸發條件: "這篇文章的相關研究", "有誰引用這篇", "類似的文章"

流程:
```
find_related_articles(pmid="12345678")  # PubMed 演算法找相似文章
find_citing_articles(pmid="12345678")   # 引用這篇的後續研究
```

═══════════════════════════════════════════════════════════════════════════════
📦 匯出工具 (搜尋完成後)
═══════════════════════════════════════════════════════════════════════════════

- prepare_export(pmids, format): 匯出引用格式 (ris/bibtex/csv/medline/json)
- get_article_fulltext_links(pmid): 取得全文連結 (PMC/DOI)
- analyze_fulltext_access(pmids): 分析哪些文章有免費全文

═══════════════════════════════════════════════════════════════════════════════
🔧 所有可用工具
═══════════════════════════════════════════════════════════════════════════════

### 搜尋
- search_literature: 基本 PubMed 搜尋
- generate_search_queries: 產生 MeSH 擴展搜尋策略
- parse_pico: 解析 PICO 臨床問題
- merge_search_results: 合併多個搜尋結果
- expand_search_queries: 擴展搜尋 (結果不足時)

### 探索
- find_related_articles: 相似文章 (by PMID)
- find_citing_articles: 引用文章 (by PMID)
- fetch_article_details: 文章詳細資訊

### 匯出
- prepare_export: 匯出引用格式
- get_article_fulltext_links: 全文連結
- analyze_fulltext_access: 全文可用性分析

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
