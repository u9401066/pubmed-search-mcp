"""
Session Tools - PMID 持久化與 Session 管理

提供 Agent 存取 session 暫存資料的工具，解決記憶滿載問題。

Tools:
- read_session: 統一 session 讀取 facade
- get_session_pmids: 取得指定搜尋的 PMID 列表
- get_cached_article: 從快取取得文章詳情
- get_session_summary: Session 摘要 (可選包含完整歷史)
- get_session_log: Session activity log for history review and debugging

Removed in v0.3.1:
- Legacy separate search-history tool → Merged into get_session_summary(include_history=True)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar, cast

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context, FastMCP

    from pubmed_search.application.session.manager import SessionManager

from .tools.tool_runtime import safe_send_resource_updated

logger = logging.getLogger(__name__)
_JSON_MIME_TYPE = "application/json"
ResourceFunc = TypeVar("ResourceFunc", bound=Callable[..., str])
SESSION_RESOURCE_URIS = (
    "session://last-search",
    "session://last-search/pmids",
    "session://last-search/results",
    "session://activity",
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


def _session_resource_decorator(
    mcp: FastMCP, uri: str, **kwargs: object
) -> Callable[[ResourceFunc], ResourceFunc]:
    """Build a resource decorator that falls back for test doubles without keyword support."""
    resource = cast("Any", mcp.resource)
    with contextlib.suppress(TypeError):
        return cast("Callable[[ResourceFunc], ResourceFunc]", resource(uri, **kwargs))
    return cast("Callable[[ResourceFunc], ResourceFunc]", resource(uri))


async def notify_session_resources_updated(ctx: Context | None) -> None:
    """Best-effort session resource refresh notifications for hosts that support them."""
    if ctx is None:
        return

    session = getattr(ctx, "session", None)
    if session is None:
        return

    await asyncio.gather(*(safe_send_resource_updated(session, uri) for uri in SESSION_RESOURCE_URIS))


def _json_error(**payload: Any) -> str:
    """Serialize an error payload consistently for session tools."""
    payload.setdefault("success", False)
    return json.dumps(payload, ensure_ascii=False)


def _read_session_pmids_impl(
    session_manager: SessionManager,
    *,
    search_index: int = -1,
    query_filter: str | None = None,
) -> str:
    session = session_manager.get_current_session()
    if not session:
        return _json_error(error="No active session", hint="Run a search first to create a session")

    if not session.search_history:
        return _json_error(error="No search history", hint="Run unified_search first")

    if query_filter:
        matching = [
            (index, search)
            for index, search in enumerate(session.search_history)
            if query_filter.lower() in search.get("query", "").lower()
        ]
        if not matching:
            return _json_error(
                error=f"No searches matching '{query_filter}'",
                available_queries=[search.get("query", "")[:50] for search in session.search_history[-5:]],
            )
        index, search = matching[-1]
    else:
        try:
            search = session.search_history[search_index]
            index = search_index if search_index >= 0 else len(session.search_history) + search_index
        except IndexError:
            return _json_error(error=f"Invalid search_index: {search_index}", total_searches=len(session.search_history))

    pmids = search.get("pmids", [])
    return json.dumps(
        {
            "success": True,
            "search_index": index,
            "query": search.get("query", ""),
            "timestamp": search.get("timestamp", ""),
            "total_pmids": len(pmids),
            "pmids": pmids,
            "pmids_csv": ",".join(pmids),
            "hint": "Use pmids_csv with prepare_export or get_citation_metrics",
        },
        ensure_ascii=False,
    )


def _read_cached_article_impl(session_manager: SessionManager, *, pmid: str) -> str:
    session = session_manager.get_current_session()
    if not session:
        return _json_error(
            error="No active session",
            hint="Article not in cache, use fetch_article_details instead",
        )

    article = session_manager.get_cached_article(pmid)
    if article is None:
        return _json_error(
            error=f"PMID {pmid} not in cache",
            cached_count=len(session_manager.get_session_cached_pmids()),
            hint="Use fetch_article_details to get from PubMed",
        )

    return json.dumps(
        {"success": True, "source": "cache", "article": article},
        ensure_ascii=False,
        indent=2,
    )


def _read_session_summary_impl(
    session_manager: SessionManager,
    *,
    include_history: bool = False,
    history_limit: int = 10,
) -> str:
    session = session_manager.get_current_session()
    if not session:
        return json.dumps(
            {
                "success": False,
                "has_session": False,
                "message": "No active session. Run a search to create one.",
            },
            ensure_ascii=False,
        )

    recent_searches = [
        {"query": search.get("query", "")[:60], "count": len(search.get("pmids", []))}
        for search in session.search_history[-5:]
    ]
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
            "event_entries": len(getattr(session, "event_log", [])),
            "reading_list_items": len(session.reading_list),
            "excluded_articles": len(session.excluded_pmids),
        },
        "recent_searches": recent_searches,
        "recent_events": [
            {
                "timestamp": event.get("timestamp", "")[:19],
                "kind": event.get("kind", ""),
                "message": event.get("message", ""),
            }
            for event in getattr(session, "event_log", [])[-5:]
        ],
        "cached_pmids_sample": cached_pmids[:20],
        "all_cached_pmids_csv": ",".join(cached_pmids[:100]),
        "hints": [
            "Use get_session_pmids() to get PMIDs from a specific search",
            "Use get_cached_article(pmid) to get article details from cache",
            "Use pmids='last' with prepare_export or get_citation_metrics",
            "Use get_session_log() to review session activity and debug history",
        ],
    }

    if include_history:
        history = session.search_history[-history_limit:]
        total = len(session.search_history)
        formatted_history: list[dict[str, Any]] = []
        for index, search in enumerate(history):
            actual_index = total - history_limit + index if total > history_limit else index
            formatted_history.append(
                {
                    "index": actual_index,
                    "query": search.get("query", "")[:80],
                    "timestamp": search.get("timestamp", "")[:19],
                    "result_count": search.get("result_count", 0),
                    "pmid_count": len(search.get("pmids", [])),
                }
            )
        result["search_history"] = formatted_history
        result["hints"].append("Use get_session_pmids(index) to get PMIDs for a specific search")

    return json.dumps(result, ensure_ascii=False, indent=2)


def _read_session_log_impl(
    session_manager: SessionManager,
    *,
    event_limit: int = 50,
    kind: str | None = None,
    include_history: bool = True,
    history_limit: int = 10,
) -> str:
    session = session_manager.get_current_session()
    if not session:
        return _json_error(error="No active session", hint="Run a search first to create a session")

    events = session_manager.get_session_event_log(limit=event_limit, kind=kind)
    history_rows: list[dict[str, Any]] = []
    if include_history:
        for search in session.search_history[-history_limit:]:
            history_rows.append(
                {
                    "query": search.get("query", "")[:80],
                    "timestamp": search.get("timestamp", "")[:19],
                    "result_count": search.get("result_count", 0),
                    "pmid_count": len(search.get("pmids", [])),
                }
            )

    available_kinds = sorted({str(event.get("kind", "")) for event in getattr(session, "event_log", []) if event})
    return json.dumps(
        {
            "success": True,
            "session_id": session.session_id,
            "topic": session.topic,
            "total_events": len(getattr(session, "event_log", [])),
            "returned_events": len(events),
            "event_kind_filter": kind,
            "available_event_kinds": available_kinds,
            "events": events,
            "search_history": history_rows,
            "hint": "Use kind='<event_kind>' to filter debug events by type",
        },
        ensure_ascii=False,
        indent=2,
    )


def _read_session_dispatch(
    session_manager: SessionManager,
    *,
    action: str,
    pmid: str = "",
    search_index: int = -1,
    query_filter: str | None = None,
    include_history: bool = False,
    history_limit: int = 10,
) -> str:
    normalized_action = action.strip().lower().replace("-", "_")
    if normalized_action in {"pmids", "get_pmids", "search_pmids"}:
        return _read_session_pmids_impl(session_manager, search_index=search_index, query_filter=query_filter)
    if normalized_action in {"article", "cached_article", "cache"}:
        if not pmid:
            return _json_error(error="PMID is required for article action", hint="Provide pmid='<pmid>'")
        return _read_cached_article_impl(session_manager, pmid=pmid)
    if normalized_action in {"log", "logs", "activity", "events"}:
        return _read_session_log_impl(
            session_manager,
            event_limit=history_limit if history_limit > 0 else 50,
            kind=query_filter,
            include_history=include_history,
            history_limit=history_limit,
        )
    if normalized_action in {"summary", "context"}:
        return _read_session_summary_impl(
            session_manager,
            include_history=include_history,
            history_limit=history_limit,
        )

    return _json_error(
        error=f"Unknown session action: {action}",
        hint="Use one of: pmids, article, summary, log",
    )


def register_session_tools(mcp: FastMCP, session_manager: SessionManager):
    """
    Register session tools for PMID persistence.

    These tools help Agent access cached data without
    relying on context memory.
    """

    @mcp.tool()
    def read_session(
        action: str = "summary",
        pmid: str = "",
        search_index: int = -1,
        query_filter: str | None = None,
        include_history: bool = False,
        history_limit: int = 10,
    ) -> str:
        """Read session data through a single facade.

        Actions:
        - pmids: return PMIDs for one recorded search
        - article: return one cached article payload
        - summary: return current session summary and optional history
        """
        try:
            return _read_session_dispatch(
                session_manager,
                action=action,
                pmid=pmid,
                search_index=search_index,
                query_filter=query_filter,
                include_history=include_history,
                history_limit=history_limit,
            )
        except Exception as exc:
            logger.exception(f"read_session failed: {exc}")
            return _json_error(error=str(exc))

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
            return _read_session_dispatch(
                session_manager,
                action="pmids",
                search_index=search_index,
                query_filter=query_filter,
            )
        except Exception as exc:
            logger.exception(f"get_session_pmids failed: {exc}")
            return _json_error(error=str(exc))

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
            return _read_session_dispatch(session_manager, action="article", pmid=pmid)
        except Exception as exc:
            logger.exception(f"get_cached_article failed: {exc}")
            return _json_error(error=str(exc))

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
            return _read_session_dispatch(
                session_manager,
                action="summary",
                include_history=include_history,
                history_limit=history_limit,
            )
        except Exception as exc:
            logger.exception(f"get_session_summary failed: {exc}")
            return _json_error(error=str(exc))

    @mcp.tool()
    def get_session_log(
        event_limit: int = 50,
        kind: str | None = None,
        include_history: bool = True,
        history_limit: int = 10,
    ) -> str:
        """
        取得當前 session 的 activity log 與搜尋歷史摘要。

        適合讓 user 回顧最近做過哪些搜尋、cache/reading-list/exclusion
        變化，以及作為 debug 時的 session-level 事件檢視。

        Args:
            event_limit: 回傳的 event 筆數上限 (預設 50)
            kind: 可選，僅回傳特定 event kind
            include_history: 是否一併包含搜尋歷史摘要 (預設 True)
            history_limit: 搜尋歷史摘要筆數上限 (預設 10)

        Returns:
            Session activity log 與搜尋歷史摘要
        """
        try:
            return _read_session_log_impl(
                session_manager,
                event_limit=event_limit,
                kind=kind,
                include_history=include_history,
                history_limit=history_limit,
            )
        except Exception as exc:
            logger.exception(f"get_session_log failed: {exc}")
            return _json_error(error=str(exc))


def register_session_resources(mcp: FastMCP, session_manager: SessionManager):
    """
    Resources for debugging/monitoring only.
    Agent doesn't need to use these for normal operation.
    """

    @_session_resource_decorator(
        mcp,
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

    @_session_resource_decorator(
        mcp,
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

    @_session_resource_decorator(
        mcp,
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

    @_session_resource_decorator(
        mcp,
        "session://activity",
        **cast(
            "Any",
            _session_resource_kwargs(
                name="session_activity",
                title="Session Activity Log",
                description="Recent session activity events plus search history for debugging and review.",
            ),
        ),
    )
    def get_session_activity() -> str:
        """Recent session activity and search history for user-facing review/debug."""
        session = session_manager.get_current_session()
        if not session:
            return json.dumps({"active": False, "events": [], "search_history": []})

        return json.dumps(
            {
                "active": True,
                "session_id": session.session_id,
                "topic": session.topic,
                "event_count": len(getattr(session, "event_log", [])),
                "events": session_manager.get_session_event_log(limit=25),
                "search_history": [
                    {
                        "query": search.get("query", "")[:80],
                        "timestamp": search.get("timestamp", "")[:19],
                        "result_count": search.get("result_count", 0),
                        "pmid_count": len(search.get("pmids", [])),
                    }
                    for search in session.search_history[-10:]
                ],
            },
            ensure_ascii=False,
        )

    @_session_resource_decorator(
        mcp,
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
                "event_count": len(getattr(session, "event_log", [])),
                "cached_pmids": session_manager.get_session_cached_pmids(limit=50),
            }
        )
