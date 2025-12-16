"""
Session Tools - PMID 持久化與 Session 管理

提供 Agent 存取 session 暫存資料的工具，解決記憶滿載問題。

Tools:
- get_session_pmids: 取得指定搜尋的 PMID 列表
- list_search_history: 列出搜尋歷史
- get_cached_article: 從快取取得文章詳情
"""

import logging
import json

from mcp.server.fastmcp import FastMCP

from ..session import SessionManager

logger = logging.getLogger(__name__)


def register_session_tools(mcp: FastMCP, session_manager: SessionManager):
    """
    Register session tools for PMID persistence.
    
    These tools help Agent access cached data without
    relying on context memory.
    """
    
    @mcp.tool()
    def get_session_pmids(
        search_index: int = -1,
        query_filter: str = None
    ) -> str:
        """
        取得 session 中暫存的 PMID 列表。
        
        解決 Agent 記憶滿載問題 - 不需要記住所有 PMID，
        可以隨時從 session 取回。
        
        Args:
            search_index: 搜尋索引
                - -1: 最近一次搜尋 (預設)
                - -2: 前一次搜尋
                - 0, 1, 2...: 第 N 次搜尋
            query_filter: 可選，篩選包含此字串的搜尋
                
        Returns:
            JSON 格式的 PMID 列表和搜尋資訊
            
        Example:
            get_session_pmids()  # 最近一次搜尋的 PMIDs
            get_session_pmids(-2)  # 前一次搜尋的 PMIDs
            get_session_pmids(query_filter="BJA")  # 包含 "BJA" 的搜尋
        """
        try:
            session = session_manager.get_current_session()
            if not session:
                return json.dumps({
                    "success": False,
                    "error": "No active session",
                    "hint": "Run a search first to create a session"
                })
            
            if not session.search_history:
                return json.dumps({
                    "success": False,
                    "error": "No search history",
                    "hint": "Run search_literature first"
                })
            
            # Filter by query if specified
            if query_filter:
                matching = [
                    (i, s) for i, s in enumerate(session.search_history)
                    if query_filter.lower() in s.get("query", "").lower()
                ]
                if not matching:
                    return json.dumps({
                        "success": False,
                        "error": f"No searches matching '{query_filter}'",
                        "available_queries": [
                            s.get("query", "")[:50] 
                            for s in session.search_history[-5:]
                        ]
                    })
                index, search = matching[-1]  # Most recent matching
            else:
                # Use search_index
                try:
                    search = session.search_history[search_index]
                    index = search_index if search_index >= 0 else len(session.search_history) + search_index
                except IndexError:
                    return json.dumps({
                        "success": False,
                        "error": f"Invalid search_index: {search_index}",
                        "total_searches": len(session.search_history)
                    })
            
            pmids = search.get("pmids", [])
            
            return json.dumps({
                "success": True,
                "search_index": index,
                "query": search.get("query", ""),
                "timestamp": search.get("timestamp", ""),
                "total_pmids": len(pmids),
                "pmids": pmids,
                "pmids_csv": ",".join(pmids),  # 方便直接複製使用
                "hint": "Use pmids_csv with prepare_export or get_citation_metrics"
            }, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"get_session_pmids failed: {e}")
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def list_search_history(limit: int = 10) -> str:
        """
        列出搜尋歷史，方便回顧和取得特定搜尋的 PMIDs。
        
        Args:
            limit: 最多顯示幾筆歷史 (預設 10)
            
        Returns:
            搜尋歷史列表，包含查詢字串、時間、結果數量
        """
        try:
            session = session_manager.get_current_session()
            if not session:
                return json.dumps({
                    "success": False,
                    "error": "No active session"
                })
            
            history = session.search_history[-limit:]
            
            formatted = []
            total = len(session.search_history)
            for i, search in enumerate(history):
                actual_index = total - limit + i if total > limit else i
                formatted.append({
                    "index": actual_index,
                    "query": search.get("query", "")[:80],
                    "timestamp": search.get("timestamp", "")[:19],  # YYYY-MM-DDTHH:MM:SS
                    "result_count": search.get("result_count", 0),
                    "pmid_count": len(search.get("pmids", []))
                })
            
            return json.dumps({
                "success": True,
                "session_id": session.session_id,
                "total_searches": total,
                "total_cached_articles": len(session.article_cache),
                "history": formatted,
                "hint": "Use get_session_pmids(index) to get PMIDs for a specific search"
            }, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"list_search_history failed: {e}")
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def get_cached_article(pmid: str) -> str:
        """
        從 session 快取取得文章詳情。
        
        比重新呼叫 fetch_article_details 更快，
        且不消耗 NCBI API quota。
        
        Args:
            pmid: PubMed ID
            
        Returns:
            文章詳細資訊 (如果在快取中)
        """
        try:
            session = session_manager.get_current_session()
            if not session:
                return json.dumps({
                    "success": False,
                    "error": "No active session",
                    "hint": "Article not in cache, use fetch_article_details instead"
                })
            
            if pmid not in session.article_cache:
                return json.dumps({
                    "success": False,
                    "error": f"PMID {pmid} not in cache",
                    "cached_count": len(session.article_cache),
                    "hint": "Use fetch_article_details to get from PubMed"
                })
            
            article = session.article_cache[pmid]
            
            return json.dumps({
                "success": True,
                "source": "cache",
                "article": article
            }, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"get_cached_article failed: {e}")
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def get_session_summary() -> str:
        """
        取得當前 session 的摘要資訊。
        
        顯示快取狀態、搜尋歷史摘要，幫助 Agent 了解
        目前有哪些資料可用。
        
        Returns:
            Session 摘要，包含快取文章數、搜尋次數、最近搜尋等
        """
        try:
            session = session_manager.get_current_session()
            if not session:
                return json.dumps({
                    "success": False,
                    "has_session": False,
                    "message": "No active session. Run a search to create one."
                })
            
            # Get recent searches summary
            recent_searches = []
            for s in session.search_history[-5:]:
                recent_searches.append({
                    "query": s.get("query", "")[:60],
                    "count": len(s.get("pmids", []))
                })
            
            # Get some cached PMIDs sample
            cached_pmids = list(session.article_cache.keys())
            
            return json.dumps({
                "success": True,
                "has_session": True,
                "session_id": session.session_id,
                "topic": session.topic,
                "created_at": session.created_at,
                "stats": {
                    "cached_articles": len(session.article_cache),
                    "total_searches": len(session.search_history),
                    "reading_list_items": len(session.reading_list),
                    "excluded_articles": len(session.excluded_pmids)
                },
                "recent_searches": recent_searches,
                "cached_pmids_sample": cached_pmids[:20],
                "all_cached_pmids_csv": ",".join(cached_pmids[:100]),
                "hints": [
                    "Use get_session_pmids() to get PMIDs from a specific search",
                    "Use get_cached_article(pmid) to get article details from cache",
                    "Use pmids='last' with prepare_export or get_citation_metrics"
                ]
            }, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"get_session_summary failed: {e}")
            return json.dumps({"success": False, "error": str(e)})


def register_session_resources(mcp: FastMCP, session_manager: SessionManager):
    """
    Resources for debugging/monitoring only.
    Agent doesn't need to use these for normal operation.
    """
    
    @mcp.resource("session://context")
    def get_research_context() -> str:
        """Internal: Current research context (for debugging)."""
        import json
        session = session_manager.get_current_session()
        if not session:
            return json.dumps({"active": False})
        
        return json.dumps({
            "active": True,
            "session_id": session.session_id,
            "cached_articles": len(session.article_cache),
            "searches": len(session.search_history),
            "cached_pmids": list(session.article_cache.keys())[:50]
        })
