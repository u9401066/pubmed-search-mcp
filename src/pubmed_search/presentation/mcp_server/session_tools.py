"""
Session Tools - PMID 持久化與 Session 管理

提供 Agent 存取 session 暫存資料的工具，解決記憶滿載問題。

Tools:
- get_session_pmids: 取得指定搜尋的 PMID 列表
- get_cached_article: 從快取取得文章詳情
- get_session_summary: Session 摘要 (可選包含完整歷史)

Removed in v0.3.1:
- Legacy separate search-history tool → Merged into get_session_summary(include_history=True)
"""

from __future__ import annotations

import contextlib
import json
import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context, FastMCP

    from pubmed_search.application.session.manager import SessionManager

logger = logging.getLogger(__name__)
_JSON_MIME_TYPE = "application/json"
SESSION_RESOURCE_URIS = (
    "session://last-search",
    "session://last-search/pmids",
    "session://last-search/results",
    "session://context",
)


def _session_resource_kwargs(*, name: str, title: str, description: str) -> dict[str, object]:
    """Build consistent host-facing metadata for dynamic session resources."""
    return {
        "name": name,
        "title": title,
        "description": description,
        "mime_type": _JSON_MIME_TYPE,
        "meta": {"pubmedSearch": {"scope": "session", "dynamic": True, "format": "json"}},
    }


async def notify_session_resources_updated(ctx: Context | None) -> None:
    """Best-effort session resource refresh notifications for hosts that support them."""
    if ctx is None:
        return

    session = getattr(ctx, "session", None)
    if session is None:
        return

    for uri in SESSION_RESOURCE_URIS:
        with contextlib.suppress(Exception):
            await session.send_resource_updated(uri)


def register_session_tools(mcp: FastMCP, session_manager: SessionManager):
    """
    Register session tools for PMID persistence.

    These tools help Agent access cached data without
    relying on context memory.
    """

    @mcp.tool()
    def get_session_pmids(search_index: int = -1, query_filter: str | None = None) -> str:
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
                return json.dumps(
                    {
                        "success": False,
                        "error": "No active session",
                        "hint": "Run a search first to create a session",
                    }
                )

            if not session.search_history:
                return json.dumps(
                    {
                        "success": False,
                        "error": "No search history",
                        "hint": "Run unified_search first",
                    }
                )

            # Filter by query if specified
            if query_filter:
                matching = [
                    (i, s)
                    for i, s in enumerate(session.search_history)
                    if query_filter.lower() in s.get("query", "").lower()
                ]
                if not matching:
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"No searches matching '{query_filter}'",
                            "available_queries": [s.get("query", "")[:50] for s in session.search_history[-5:]],
                        }
                    )
                index, search = matching[-1]  # Most recent matching
            else:
                # Use search_index
                try:
                    search = session.search_history[search_index]
                    index = search_index if search_index >= 0 else len(session.search_history) + search_index
                except IndexError:
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"Invalid search_index: {search_index}",
                            "total_searches": len(session.search_history),
                        }
                    )

            pmids = search.get("pmids", [])

            return json.dumps(
                {
                    "success": True,
                    "search_index": index,
                    "query": search.get("query", ""),
                    "timestamp": search.get("timestamp", ""),
                    "total_pmids": len(pmids),
                    "pmids": pmids,
                    "pmids_csv": ",".join(pmids),  # 方便直接複製使用
                    "hint": "Use pmids_csv with prepare_export or get_citation_metrics",
                },
                ensure_ascii=False,
            )

        except Exception as e:
            logger.exception(f"get_session_pmids failed: {e}")
            return json.dumps({"success": False, "error": str(e)})

    # Legacy separate history tool removed in v0.3.1 and merged into get_session_summary(include_history=True)

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
                return json.dumps(
                    {
                        "success": False,
                        "error": "No active session",
                        "hint": "Article not in cache, use fetch_article_details instead",
                    }
                )

            article = session_manager.get_cached_article(pmid)
            if article is None:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"PMID {pmid} not in cache",
                        "cached_count": len(session_manager.get_session_cached_pmids()),
                        "hint": "Use fetch_article_details to get from PubMed",
                    }
                )

            return json.dumps(
                {"success": True, "source": "cache", "article": article},
                ensure_ascii=False,
                indent=2,
            )

        except Exception as e:
            logger.exception(f"get_cached_article failed: {e}")
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def get_session_summary(include_history: bool = False, history_limit: int = 10) -> str:
        """
        取得當前 session 的摘要資訊。

        顯示快取狀態、搜尋歷史摘要，幫助 Agent 了解
        目前有哪些資料可用。

        Args:
            include_history: 是否包含完整搜尋歷史 (預設 False)
            history_limit: 歷史筆數上限，僅當 include_history=True 時有效 (預設 10)

        Returns:
            Session 摘要，包含快取文章數、搜尋次數、最近搜尋等

        Examples:
            get_session_summary()  # 基本摘要
            get_session_summary(include_history=True)  # 含完整搜尋歷史
            get_session_summary(include_history=True, history_limit=20)  # 更多歷史
        """
        try:
            session = session_manager.get_current_session()
            if not session:
                return json.dumps(
                    {
                        "success": False,
                        "has_session": False,
                        "message": "No active session. Run a search to create one.",
                    }
                )

            # Get recent searches summary (always included, brief)
            recent_searches = []
            for s in session.search_history[-5:]:
                recent_searches.append({"query": s.get("query", "")[:60], "count": len(s.get("pmids", []))})

            # Get some cached PMIDs sample
            cached_pmids = session_manager.get_session_cached_pmids(limit=100)

            result: dict[str, Any] = {
                "success": True,
                "has_session": True,
                "session_id": session.session_id,
                "topic": session.topic,
                "created_at": session.created_at,
                "stats": {
                    "cached_articles": len(session_manager.get_session_cached_pmids()),
                    "total_searches": len(session.search_history),
                    "reading_list_items": len(session.reading_list),
                    "excluded_articles": len(session.excluded_pmids),
                },
                "recent_searches": recent_searches,
                "cached_pmids_sample": cached_pmids[:20],
                "all_cached_pmids_csv": ",".join(cached_pmids[:100]),
                "hints": [
                    "Use get_session_pmids() to get PMIDs from a specific search",
                    "Use get_cached_article(pmid) to get article details from cache",
                    "Use pmids='last' with prepare_export or get_citation_metrics",
                ],
            }

            # Include detailed search history if requested
            if include_history:
                history = session.search_history[-history_limit:]
                total = len(session.search_history)
                formatted_history: list[dict[str, Any]] = []
                for i, search in enumerate(history):
                    actual_index = total - history_limit + i if total > history_limit else i
                    formatted_history.append(
                        {
                            "index": actual_index,
                            "query": search.get("query", "")[:80],
                            "timestamp": search.get("timestamp", "")[:19],  # YYYY-MM-DDTHH:MM:SS
                            "result_count": search.get("result_count", 0),
                            "pmid_count": len(search.get("pmids", [])),
                        }
                    )
                result["search_history"] = formatted_history
                result["hints"].append("Use get_session_pmids(index) to get PMIDs for a specific search")

            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.exception(f"get_session_summary failed: {e}")
            return json.dumps({"success": False, "error": str(e)})


def register_session_resources(mcp: FastMCP, session_manager: SessionManager):
    """
    Resources for debugging/monitoring only.
    Agent doesn't need to use these for normal operation.
    """

    @mcp.resource(
        "session://last-search",
        **cast(
            "Any",
            _session_resource_kwargs(
                name="session_last_search",
                title="Last Search Summary",
                description="Latest session search metadata and reusable PMID summary.",
            ),
        ),
    )
    def get_last_search() -> str:
        """Latest search metadata and quick agent-facing summary."""
        session = session_manager.get_current_session()
        if not session or not session.search_history:
            return json.dumps({"active": False, "has_last_search": False})

        last_search = session.search_history[-1]
        pmids = last_search.get("pmids", [])
        return json.dumps(
            {
                "active": True,
                "has_last_search": True,
                "query": last_search.get("query", ""),
                "timestamp": last_search.get("timestamp", ""),
                "result_count": last_search.get("result_count", 0),
                "pmid_count": len(pmids),
                "pmids": pmids,
            },
            ensure_ascii=False,
        )

    @mcp.resource(
        "session://last-search/pmids",
        **cast(
            "Any",
            _session_resource_kwargs(
                name="session_last_search_pmids",
                title="Last Search PMIDs",
                description="PMID list from the latest recorded search for immediate reuse.",
            ),
        ),
    )
    def get_last_search_pmids() -> str:
        """PMIDs from the latest search for direct agent reuse."""
        session = session_manager.get_current_session()
        if not session or not session.search_history:
            return json.dumps({"active": False, "pmids": []})

        last_search = session.search_history[-1]
        pmids = last_search.get("pmids", [])
        return json.dumps(
            {
                "active": True,
                "query": last_search.get("query", ""),
                "pmids": pmids,
                "pmids_csv": ",".join(pmids),
            },
            ensure_ascii=False,
        )

    @mcp.resource(
        "session://last-search/results",
        **cast(
            "Any",
            _session_resource_kwargs(
                name="session_last_search_results",
                title="Last Search Cached Results",
                description="Cached article payloads for the latest search PMIDs.",
            ),
        ),
    )
    def get_last_search_results() -> str:
        """Cached article payloads corresponding to the latest search PMIDs."""
        session = session_manager.get_current_session()
        if not session or not session.search_history:
            return json.dumps({"active": False, "results": []})

        last_search = session.search_history[-1]
        pmids = last_search.get("pmids", [])
        cached_map, missing_pmids = session_manager.get_cached_article_map(pmids)
        cached_articles = [cached_map[pmid] for pmid in pmids if pmid in cached_map]
        return json.dumps(
            {
                "active": True,
                "query": last_search.get("query", ""),
                "result_count": last_search.get("result_count", 0),
                "cached_results": cached_articles,
                "cached_count": len(cached_articles),
                "missing_pmids": missing_pmids,
            },
            ensure_ascii=False,
        )

    @mcp.resource(
        "session://context",
        **cast(
            "Any",
            _session_resource_kwargs(
                name="session_context",
                title="Session Context",
                description="Current research session context and cache summary.",
            ),
        ),
    )
    def get_research_context() -> str:
        """Internal: Current research context (for debugging)."""
        import json

        session = session_manager.get_current_session()
        if not session:
            return json.dumps({"active": False})

        return json.dumps(
            {
                "active": True,
                "session_id": session.session_id,
                "cached_articles": len(session_manager.get_session_cached_pmids()),
                "searches": len(session.search_history),
                "cached_pmids": session_manager.get_session_cached_pmids(limit=50),
            }
        )
