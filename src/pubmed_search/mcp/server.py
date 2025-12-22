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
find_citing_articles(pmid="12345678")   # 引用這篇的後續研究 (forward)
get_article_references(pmid="12345678") # 這篇文章的參考文獻 (backward)
```

═══════════════════════════════════════════════════════════════════════════════
📦 匯出工具 (搜尋完成後)
═══════════════════════════════════════════════════════════════════════════════

- prepare_export(pmids, format): 匯出引用格式 (ris/bibtex/csv/medline/json)
- get_article_fulltext_links(pmid): 取得全文連結 (PMC/DOI)
- analyze_fulltext_access(pmids): 分析哪些文章有免費全文

═══════════════════════════════════════════════════════════════════════════════
🇪🇺 Europe PMC 工具 (全文存取 + 文本挖掘)
═══════════════════════════════════════════════════════════════════════════════

Europe PMC 提供 33M+ 文獻，6.5M 開放取用全文。最適合：找全文、歐洲研究。

### 搜尋與全文
- search_europe_pmc(query, open_access_only=True): 搜尋 Europe PMC
- get_fulltext(pmcid): 📄 取得解析後的全文 (分段顯示)
- get_fulltext_xml(pmcid): 取得原始 JATS XML

### 文本挖掘與引用
- get_text_mined_terms(pmid/pmcid): 🔬 取得標註 (基因、疾病、藥物)
- get_europe_pmc_citations(pmid/pmcid, direction): 引用網路

### 使用範例
```
# 找到文章後，直接閱讀全文
search_europe_pmc("CRISPR gene therapy", has_fulltext=True, limit=5)
get_fulltext(pmcid="PMC7096777", sections="introduction,results")

# 找出文章提到的所有基因
get_text_mined_terms(pmid="12345678", semantic_type="GENE_PROTEIN")
```

═══════════════════════════════════════════════════════════════════════════════
📚 CORE 開放取用工具 (200M+ 論文)
═══════════════════════════════════════════════════════════════════════════════

CORE 聚合全球 14,000+ 機構庫的開放取用研究，42M+ 有全文。

### 使用時機
- 需要開放取用版本的論文
- 搜尋預印本和機構庫內容
- 在論文全文中搜尋特定內容
- 用 DOI/PMID 找到文章的開放版本

### 搜尋語法
- title:"machine learning"    → 標題搜尋
- authors:"John Smith"        → 作者搜尋
- fullText:"neural network"  → 全文內容搜尋

### 使用範例
```
# 找開放取用論文
search_core("machine learning healthcare", has_fulltext=True, limit=10)

# 在全文中搜尋
search_core_fulltext("propofol dose calculation", limit=5)

# 用 DOI 找開放版本
find_in_core(identifier="10.1038/s41586-021-03819-2", identifier_type="doi")

# 取得全文
get_core_fulltext(core_id="123456789")
```

═══════════════════════════════════════════════════════════════════════════════
🧬 NCBI 延伸資料庫工具 (Gene, PubChem, ClinVar)
═══════════════════════════════════════════════════════════════════════════════

這些工具讓你從 NCBI 其他資料庫取得相關資訊，與文獻搜尋互補。

### Gene 資料庫 - 基因資訊
```
# 搜尋基因
search_gene("BRCA1", organism="human", limit=5)

# 取得基因詳情
get_gene_details(gene_id="672")  # BRCA1

# 找基因相關文獻
get_gene_literature(gene_id="672", limit=20)
→ 返回 PMID 列表，可用 fetch_article_details 取得文章
```

### PubChem - 化合物/藥物資訊
```
# 搜尋化合物
search_compound("aspirin", limit=5)
search_compound("remimazolam", limit=3)

# 取得化合物詳情 (分子式、SMILES、InChI 等)
get_compound_details(cid="2244")  # aspirin

# 找化合物相關文獻
get_compound_literature(cid="2244", limit=20)
```

### ClinVar - 臨床變異
```
# 搜尋臨床變異
search_clinvar("BRCA1", limit=10)
search_clinvar("cystic fibrosis", limit=10)
→ 返回變異紀錄，包含臨床意義和相關疾病
```

═══════════════════════════════════════════════════════════════════════════════
💾 Session 管理工具 (解決記憶滿載問題)
═══════════════════════════════════════════════════════════════════════════════

搜尋結果會自動暫存在 session 中，不需要記住所有 PMID！

- get_session_pmids(search_index=-1): 取得指定搜尋的 PMID 列表
  - search_index=-1: 最近一次搜尋
  - search_index=-2: 前一次搜尋
  - query_filter="BJA": 篩選包含 "BJA" 的搜尋

- list_search_history(limit=10): 列出搜尋歷史

- get_cached_article(pmid): 從快取取得文章詳情 (不消耗 API)

- get_session_summary(): 查看 session 狀態和可用資料

### 快捷用法
- `pmids="last"` - 在 prepare_export, get_citation_metrics 等工具中使用
- `get_session_pmids()` 回傳 `pmids_csv` 可直接複製使用

═══════════════════════════════════════════════════════════════════════════════
🔧 所有可用工具
═══════════════════════════════════════════════════════════════════════════════

### 搜尋
- search_literature: 基本 PubMed 搜尋
- search_europe_pmc: Europe PMC 搜尋 (含 OA/全文篩選)
- search_core: CORE 開放取用搜尋 (200M+ 論文)
- search_core_fulltext: CORE 全文內容搜尋
- generate_search_queries: 產生 MeSH 擴展搜尋策略
- parse_pico: 解析 PICO 臨床問題
- merge_search_results: 合併多個搜尋結果
- expand_search_queries: 擴展搜尋 (結果不足時)

### 探索
- find_related_articles: 相似文章 (by PMID)
- find_citing_articles: 引用這篇的文章 (by PMID, forward in time)
- get_article_references: 這篇的參考文獻 (by PMID, backward in time)
- fetch_article_details: 文章詳細資訊
- get_citation_metrics: 引用指標 (iCite RCR/Percentile, 可排序篩選)

### 全文與文本挖掘 (Europe PMC)
- get_fulltext: 📄 取得解析後全文 (分段顯示)
- get_fulltext_xml: 取得原始 JATS XML
- get_text_mined_terms: 🔬 取得標註 (基因、疾病、藥物)
- get_europe_pmc_citations: Europe PMC 引用網路

### CORE 開放取用 (200M+ 論文)
- get_core_paper: 取得 CORE 論文詳情
- get_core_fulltext: 📄 取得 CORE 全文內容
- find_in_core: 用 DOI/PMID 在 CORE 找開放版本

### NCBI 延伸資料庫 (基因、化合物、變異)
- search_gene: 🧬 搜尋 NCBI Gene 資料庫
- get_gene_details: 取得基因詳情
- get_gene_literature: 取得與基因相關的 PubMed 文章
- search_compound: 💊 搜尋 PubChem 化合物
- get_compound_details: 取得化合物詳情
- get_compound_literature: 取得與化合物相關的 PubMed 文章
- search_clinvar: 🔬 搜尋 ClinVar 臨床變異

### 匯出
- prepare_export: 匯出引用格式
- get_article_fulltext_links: 全文連結
- analyze_fulltext_access: 全文可用性分析

### Session 管理
- get_session_pmids: 取得暫存的 PMID 列表
- list_search_history: 列出搜尋歷史
- get_cached_article: 從快取取得文章
- get_session_summary: Session 狀態摘要

NOTE: 搜尋結果自動暫存，使用 session 工具可隨時取回，不需依賴 Agent 記憶。
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
    
    # Register prompts (research workflow templates)
    logger.info("Registering research prompts...")
    from .prompts import register_prompts
    register_prompts(mcp)
    
    # Store references for later use
    mcp._session_manager = session_manager
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
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import json
    
    class MCPAPIHandler(BaseHTTPRequestHandler):
        """Simple HTTP handler for MCP-to-MCP API."""
        
        def log_message(self, format, *args):
            # Suppress HTTP access logs to avoid polluting stdio
            pass
        
        def _send_json(self, data: dict, status: int = 200):
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        
        def do_GET(self):
            path = self.path
            
            # Health check
            if path == '/health':
                self._send_json({"status": "ok", "service": "pubmed-search-mcp-api"})
                return
            
            # Get single cached article
            if path.startswith('/api/cached_article/'):
                pmid = path.split('/')[-1].split('?')[0]
                session = session_manager.get_current_session()
                
                if session and pmid in session.article_cache:
                    self._send_json({
                        "source": "pubmed",
                        "verified": True,
                        "data": session.article_cache[pmid]
                    })
                    return
                
                # Try to fetch if not in cache
                if searcher:
                    try:
                        articles = searcher.fetch_details([pmid])
                        if articles:
                            session_manager.add_to_cache(articles)
                            self._send_json({
                                "source": "pubmed",
                                "verified": True,
                                "data": articles[0]
                            })
                            return
                    except Exception as e:
                        self._send_json({"detail": f"PubMed API error: {str(e)}"}, 502)
                        return
                
                self._send_json({"detail": f"Article PMID:{pmid} not found"}, 404)
                return
            
            # Get session summary
            if path == '/api/session/summary':
                self._send_json(session_manager.get_session_summary())
                return
            
            # Root - API info
            if path == '/' or path == '':
                self._send_json({
                    "service": "pubmed-search-mcp HTTP API",
                    "mode": "background (stdio MCP + HTTP API)",
                    "endpoints": {
                        "/health": "Health check",
                        "/api/cached_article/{pmid}": "Get cached article",
                        "/api/session/summary": "Session info"
                    }
                })
                return
            
            self._send_json({"error": "Not found"}, 404)
    
    def run_server():
        try:
            httpd = HTTPServer(('127.0.0.1', port), MCPAPIHandler)
            logger.info(f"[HTTP API] Started on http://127.0.0.1:{port}")
            httpd.serve_forever()
        except OSError as e:
            if e.errno == 10048:  # Port already in use (Windows)
                logger.warning(f"[HTTP API] Port {port} already in use, skipping")
            else:
                logger.error(f"[HTTP API] Failed to start: {e}")
        except Exception as e:
            logger.error(f"[HTTP API] Failed to start: {e}")
    
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
    
    # Get HTTP API port from environment (default: 8765)
    http_api_port = int(os.environ.get("PUBMED_HTTP_API_PORT", "8765"))
    
    # Create server
    server = create_server(email=email, api_key=api_key)
    
    # Start background HTTP API for MCP-to-MCP communication
    # This runs alongside the stdio MCP server
    start_http_api_background(
        server._session_manager, 
        server._searcher,
        port=http_api_port
    )
    
    # Run stdio MCP server (blocks)
    server.run()


if __name__ == "__main__":
    main()
