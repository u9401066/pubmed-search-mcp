"""Tests for session_tools.py — PMID persistence and session management tools."""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

from pubmed_search.presentation.mcp_server.session_tools import (
    SESSION_RESOURCE_URIS,
    notify_session_resources_updated,
    register_session_resources,
    register_session_tools,
)


class _CapturedRegistrations(dict):
    def __init__(self):
        super().__init__()
        self.resource_meta: dict[str, dict] = {}


def _capture_tools(register_fn, *args):
    """Utility to capture registered tool functions."""
    tools = _CapturedRegistrations()
    mcp = MagicMock()

    def _tool(*decorator_args, **decorator_kwargs):
        del decorator_args, decorator_kwargs

        def _decorator(func):
            tools[func.__name__] = func
            return func

        return _decorator

    def _resource(uri, **kwargs):
        def _decorator(func):
            tools[uri] = func
            tools.resource_meta[uri] = kwargs
            return func

        return _decorator

    mcp.tool = _tool
    mcp.resource = _resource
    register_fn(mcp, *args)
    return tools


def _make_session(search_history=None, article_cache=None):
    session = MagicMock()
    session.search_history = search_history or []
    session.event_log = []
    session.article_cache = article_cache or {}
    session.session_id = "test-session-123"
    session.topic = "test topic"
    session.created_at = "2024-01-01T00:00:00"
    session.reading_list = []
    session.excluded_pmids = set()
    return session


def _configure_manager_cache(sm, article_cache=None):
    cache = article_cache or {}

    def _get_cached_article(pmid):
        return cache.get(pmid)

    def _get_session_cached_pmids(limit=None):
        return list(cache.keys())[:limit]

    def _get_cached_article_map(pmids):
        return (
            {pmid: cache[pmid] for pmid in pmids if pmid in cache},
            [pmid for pmid in pmids if pmid not in cache],
        )

    sm.get_cached_article.side_effect = _get_cached_article
    sm.get_session_cached_pmids.side_effect = _get_session_cached_pmids
    sm.get_cached_article_map.side_effect = _get_cached_article_map


class TestSessionToolRegistration:
    def test_registers_read_session_facade(self):
        sm = MagicMock()
        tools = _capture_tools(register_session_tools, sm)
        assert {"read_session", "get_session_pmids", "get_cached_article", "get_session_summary", "get_session_log"} <= set(tools)


# ============================================================
# read_session
# ============================================================


class TestReadSession:
    def setup_method(self):
        self.sm = MagicMock()
        self.tools = _capture_tools(register_session_tools, self.sm)
        self.fn = self.tools["read_session"]

    async def test_summary_action(self):
        history = [{"query": "test", "pmids": ["111"]}]
        cache = {"111": {"title": "A"}}
        session = _make_session(search_history=history, article_cache=cache)
        self.sm.get_current_session.return_value = session
        _configure_manager_cache(self.sm, cache)

        result = json.loads(self.fn())
        assert result["success"] is True
        assert result["has_session"] is True

    async def test_pmids_action(self):
        history = [{"query": "covid", "pmids": ["111", "222"], "timestamp": "2024-01-01"}]
        self.sm.get_current_session.return_value = _make_session(search_history=history)

        result = json.loads(self.fn(action="pmids"))
        assert result["success"] is True
        assert result["pmids_csv"] == "111,222"

    async def test_article_action(self):
        article = {"pmid": "12345", "title": "Test Article"}
        session = _make_session(article_cache={"12345": article})
        self.sm.get_current_session.return_value = session
        _configure_manager_cache(self.sm, {"12345": article})

        result = json.loads(self.fn(action="article", pmid="12345"))
        assert result["success"] is True
        assert result["article"]["title"] == "Test Article"

    async def test_unknown_action(self):
        result = json.loads(self.fn(action="unknown"))
        assert result["success"] is False
        assert "Unknown session action" in result["error"]

    async def test_log_action(self):
        session = _make_session(search_history=[{"query": "test", "pmids": ["111"], "timestamp": "2024-01-01T00:00:00Z"}])
        session.event_log = [
            {
                "timestamp": "2024-01-01T00:00:00Z",
                "kind": "search_recorded",
                "level": "info",
                "message": "Recorded search query in session history",
                "details": {"query": "test", "result_count": 1, "pmid_count": 1},
            }
        ]
        self.sm.get_current_session.return_value = session
        self.sm.get_session_event_log.return_value = session.event_log

        result = json.loads(self.fn(action="log", include_history=True, history_limit=5))
        assert result["success"] is True
        assert result["events"][0]["kind"] == "search_recorded"
        assert result["search_history"][0]["query"] == "test"


# ============================================================
# get_session_pmids
# ============================================================


class TestGetSessionPmids:
    def setup_method(self):
        self.sm = MagicMock()
        self.tools = _capture_tools(register_session_tools, self.sm)
        self.fn = self.tools["get_session_pmids"]

    async def test_no_session(self):
        self.sm.get_current_session.return_value = None
        result = json.loads(self.fn())
        assert result["success"] is False
        assert "No active session" in result["error"]

    async def test_no_history(self):
        self.sm.get_current_session.return_value = _make_session()
        result = json.loads(self.fn())
        assert result["success"] is False
        assert "No search history" in result["error"]

    async def test_last_search(self):
        history = [
            {"query": "covid", "pmids": ["111", "222"], "timestamp": "2024-01-01"},
            {"query": "cancer", "pmids": ["333", "444"], "timestamp": "2024-01-02"},
        ]
        self.sm.get_current_session.return_value = _make_session(search_history=history)
        result = json.loads(self.fn())
        assert result["success"] is True
        assert result["pmids"] == ["333", "444"]
        assert result["query"] == "cancer"

    async def test_specific_index(self):
        history = [
            {"query": "covid", "pmids": ["111"], "timestamp": ""},
            {"query": "cancer", "pmids": ["222"], "timestamp": ""},
        ]
        self.sm.get_current_session.return_value = _make_session(search_history=history)
        result = json.loads(self.fn(search_index=0))
        assert result["success"] is True
        assert result["pmids"] == ["111"]

    async def test_invalid_index(self):
        history = [{"query": "test", "pmids": [], "timestamp": ""}]
        self.sm.get_current_session.return_value = _make_session(search_history=history)
        result = json.loads(self.fn(search_index=99))
        assert result["success"] is False

    async def test_query_filter_match(self):
        history = [
            {"query": "COVID treatment", "pmids": ["111"], "timestamp": ""},
            {"query": "cancer research", "pmids": ["222"], "timestamp": ""},
        ]
        self.sm.get_current_session.return_value = _make_session(search_history=history)
        result = json.loads(self.fn(query_filter="COVID"))
        assert result["success"] is True
        assert result["pmids"] == ["111"]

    async def test_query_filter_no_match(self):
        history = [{"query": "cancer", "pmids": ["111"], "timestamp": ""}]
        self.sm.get_current_session.return_value = _make_session(search_history=history)
        result = json.loads(self.fn(query_filter="XXXXX"))
        assert result["success"] is False

    async def test_pmids_csv_field(self):
        history = [{"query": "test", "pmids": ["111", "222"], "timestamp": ""}]
        self.sm.get_current_session.return_value = _make_session(search_history=history)
        result = json.loads(self.fn())
        assert result["pmids_csv"] == "111,222"

    async def test_exception(self):
        self.sm.get_current_session.side_effect = RuntimeError("DB error")
        result = json.loads(self.fn())
        assert result["success"] is False


# TestListSearchHistory removed in v0.3.1 - merged into get_session_summary


# ============================================================
# get_cached_article
# ============================================================


class TestGetCachedArticle:
    def setup_method(self):
        self.sm = MagicMock()
        self.tools = _capture_tools(register_session_tools, self.sm)
        self.fn = self.tools["get_cached_article"]

    async def test_no_session(self):
        self.sm.get_current_session.return_value = None
        result = json.loads(self.fn(pmid="12345"))
        assert result["success"] is False

    async def test_not_cached(self):
        session = _make_session(article_cache={})
        self.sm.get_current_session.return_value = session
        _configure_manager_cache(self.sm, {})
        result = json.loads(self.fn(pmid="12345"))
        assert result["success"] is False
        assert "not in cache" in result["error"]

    async def test_found_in_cache(self):
        article = {"pmid": "12345", "title": "Test Article"}
        session = _make_session(article_cache={"12345": article})
        self.sm.get_current_session.return_value = session
        _configure_manager_cache(self.sm, {"12345": article})
        result = json.loads(self.fn(pmid="12345"))
        assert result["success"] is True
        assert result["source"] == "cache"
        assert result["article"]["title"] == "Test Article"

    async def test_exception(self):
        self.sm.get_current_session.side_effect = RuntimeError("fail")
        result = json.loads(self.fn(pmid="12345"))
        assert result["success"] is False


# ============================================================
# get_session_summary
# ============================================================


class TestGetSessionSummary:
    def setup_method(self):
        self.sm = MagicMock()
        self.tools = _capture_tools(register_session_tools, self.sm)
        self.fn = self.tools["get_session_summary"]

    async def test_no_session(self):
        self.sm.get_current_session.return_value = None
        result = json.loads(self.fn())
        assert result["success"] is False
        assert result["has_session"] is False

    async def test_with_session(self):
        history = [{"query": "test", "pmids": ["111", "222"]}]
        cache = {"111": {"title": "A"}, "222": {"title": "B"}}
        session = _make_session(search_history=history, article_cache=cache)
        self.sm.get_current_session.return_value = session
        _configure_manager_cache(self.sm, cache)
        result = json.loads(self.fn())
        assert result["success"] is True
        assert result["has_session"] is True
        assert result["stats"]["cached_articles"] == 2
        assert result["stats"]["total_searches"] == 1
        assert result["stats"]["event_entries"] == 0

    async def test_includes_recent_events(self):
        history = [{"query": "test", "pmids": ["111"], "timestamp": "2024-01-01T00:00:00Z", "result_count": 1}]
        cache = {"111": {"title": "A"}}
        session = _make_session(search_history=history, article_cache=cache)
        session.event_log = [
            {
                "timestamp": "2024-01-01T00:00:00Z",
                "kind": "search_recorded",
                "level": "info",
                "message": "Recorded search query in session history",
                "details": {"query": "test"},
            }
        ]
        self.sm.get_current_session.return_value = session
        _configure_manager_cache(self.sm, cache)

        result = json.loads(self.fn())
        assert result["recent_events"][0]["kind"] == "search_recorded"

    async def test_with_include_history(self):
        """Test include_history=True (merged from list_search_history in v0.3.1)."""
        history = [
            {
                "query": "test1",
                "pmids": ["1"],
                "timestamp": "2024-01-01T12:00:00Z",
                "result_count": 1,
            },
            {
                "query": "test2",
                "pmids": ["2", "3"],
                "timestamp": "2024-01-02T12:00:00Z",
                "result_count": 2,
            },
        ]
        cache = {"1": {}, "2": {}, "3": {}}
        session = _make_session(search_history=history, article_cache=cache)
        self.sm.get_current_session.return_value = session
        _configure_manager_cache(self.sm, cache)
        result = json.loads(self.fn(include_history=True))
        assert result["success"] is True
        assert "search_history" in result
        assert len(result["search_history"]) == 2
        assert result["search_history"][0]["query"] == "test1"
        assert result["search_history"][1]["pmid_count"] == 2

    async def test_include_history_with_limit(self):
        """Test include_history with history_limit parameter."""
        history = [{"query": f"q{i}", "pmids": [], "timestamp": "", "result_count": 0} for i in range(20)]
        session = _make_session(search_history=history, article_cache={})
        self.sm.get_current_session.return_value = session
        _configure_manager_cache(self.sm, {})
        result = json.loads(self.fn(include_history=True, history_limit=5))
        assert result["success"] is True
        assert len(result["search_history"]) == 5

    async def test_exception(self):
        self.sm.get_current_session.side_effect = RuntimeError("fail")
        result = json.loads(self.fn())
        assert result["success"] is False


# ============================================================
# register_session_resources
# ============================================================


class TestSessionResources:
    async def test_session_resource_metadata(self):
        sm = MagicMock()
        tools = _capture_tools(register_session_resources, sm)
        metadata = tools.resource_meta["session://last-search"]

        assert metadata["mime_type"] == "application/json"
        assert metadata["title"] == "Last Search Summary"
        assert metadata["meta"]["pubmedSearch"]["dynamic"] is True

    async def test_context_with_session(self):
        sm = MagicMock()
        session = _make_session(article_cache={"111": {}})
        session.search_history = [{"q": "test"}]
        sm.get_current_session.return_value = session
        _configure_manager_cache(sm, {"111": {}})
        tools = _capture_tools(register_session_resources, sm)
        fn = tools["session://context"]
        result = json.loads(fn())
        assert result["active"] is True
        assert result["cached_articles"] == 1

    async def test_context_no_session(self):
        sm = MagicMock()
        sm.get_current_session.return_value = None
        tools = _capture_tools(register_session_resources, sm)
        fn = tools["session://context"]
        result = json.loads(fn())
        assert result["active"] is False

    async def test_last_search_resource(self):
        sm = MagicMock()
        session = _make_session(
            search_history=[{"query": "covid", "pmids": ["111", "222"], "timestamp": "2024-01-01", "result_count": 2}],
            article_cache={"111": {"pmid": "111"}, "222": {"pmid": "222"}},
        )
        sm.get_current_session.return_value = session
        _configure_manager_cache(sm, {"111": {"pmid": "111"}, "222": {"pmid": "222"}})
        tools = _capture_tools(register_session_resources, sm)
        result = json.loads(tools["session://last-search"]())
        assert result["active"] is True
        assert result["query"] == "covid"
        assert result["pmid_count"] == 2

    async def test_last_search_pmids_resource(self):
        sm = MagicMock()
        session = _make_session(search_history=[{"query": "covid", "pmids": ["111", "222"]}])
        sm.get_current_session.return_value = session
        tools = _capture_tools(register_session_resources, sm)
        result = json.loads(tools["session://last-search/pmids"]())
        assert result["pmids"] == ["111", "222"]
        assert result["pmids_csv"] == "111,222"

    async def test_last_search_results_resource(self):
        sm = MagicMock()
        session = _make_session(
            search_history=[{"query": "covid", "pmids": ["111", "999"], "result_count": 2}],
            article_cache={"111": {"pmid": "111", "title": "Cached"}},
        )
        sm.get_current_session.return_value = session
        _configure_manager_cache(sm, {"111": {"pmid": "111", "title": "Cached"}})
        tools = _capture_tools(register_session_resources, sm)
        result = json.loads(tools["session://last-search/results"]())
        assert result["cached_count"] == 1
        assert result["cached_results"][0]["title"] == "Cached"
        assert result["missing_pmids"] == ["999"]

    async def test_activity_resource(self):
        sm = MagicMock()
        session = _make_session(
            search_history=[{"query": "covid", "pmids": ["111", "222"], "timestamp": "2024-01-01", "result_count": 2}],
            article_cache={"111": {"pmid": "111"}},
        )
        session.event_log = [
            {
                "timestamp": "2024-01-01T00:00:00Z",
                "kind": "search_recorded",
                "level": "info",
                "message": "Recorded search query in session history",
                "details": {"query": "covid"},
            }
        ]
        sm.get_current_session.return_value = session
        sm.get_session_event_log.return_value = session.event_log
        tools = _capture_tools(register_session_resources, sm)

        result = json.loads(tools["session://activity"]())
        assert result["active"] is True
        assert result["event_count"] == 1
        assert result["events"][0]["kind"] == "search_recorded"
        assert result["search_history"][0]["query"] == "covid"


class TestSessionResourceNotifications:
    async def test_notify_session_resources_updated_sends_all_known_uris(self):
        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_resource_updated = AsyncMock()

        await notify_session_resources_updated(ctx)

        observed_uris = [call.args[0] for call in ctx.session.send_resource_updated.await_args_list]
        assert observed_uris == list(SESSION_RESOURCE_URIS)

    async def test_notify_session_resources_updated_swallows_host_errors(self):
        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_resource_updated = AsyncMock(side_effect=RuntimeError("unsupported"))

        await notify_session_resources_updated(ctx)

        assert ctx.session.send_resource_updated.await_count == len(SESSION_RESOURCE_URIS)

    async def test_notify_session_resources_updated_does_not_block_on_hanging_host(self):
        ctx = MagicMock()
        ctx.session = MagicMock()

        async def _hang(*args, **kwargs):
            await asyncio.Event().wait()

        ctx.session.send_resource_updated = AsyncMock(side_effect=_hang)

        await asyncio.wait_for(notify_session_resources_updated(ctx), timeout=0.5)
        assert ctx.session.send_resource_updated.await_count == len(SESSION_RESOURCE_URIS)

    async def test_notify_session_resources_updated_does_not_wait_for_cancellation_resistant_host(self):
        ctx = MagicMock()
        ctx.session = MagicMock()

        async def _ignore_cancel(*args, **kwargs):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await asyncio.sleep(0.2)

        ctx.session.send_resource_updated = AsyncMock(side_effect=_ignore_cancel)

        started = time.monotonic()
        await asyncio.wait_for(notify_session_resources_updated(ctx), timeout=0.5)
        assert time.monotonic() - started < 0.2
        assert ctx.session.send_resource_updated.await_count == len(SESSION_RESOURCE_URIS)
        await asyncio.sleep(0.25)
