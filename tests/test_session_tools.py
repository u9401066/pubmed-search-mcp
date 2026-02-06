"""Tests for session_tools.py — PMID persistence and session management tools."""

import json
from unittest.mock import MagicMock

import pytest

from pubmed_search.presentation.mcp_server.session_tools import (
    register_session_resources,
    register_session_tools,
)


def _capture_tools(register_fn, *args):
    """Utility to capture registered tool functions."""
    tools = {}
    mcp = MagicMock()
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
    mcp.resource = lambda uri: lambda func: (tools.__setitem__(uri, func), func)[1]
    register_fn(mcp, *args)
    return tools


def _make_session(search_history=None, article_cache=None):
    session = MagicMock()
    session.search_history = search_history or []
    session.article_cache = article_cache or {}
    session.session_id = "test-session-123"
    session.topic = "test topic"
    session.created_at = "2024-01-01T00:00:00"
    session.reading_list = []
    session.excluded_pmids = set()
    return session


# ============================================================
# get_session_pmids
# ============================================================

class TestGetSessionPmids:
    def setup_method(self):
        self.sm = MagicMock()
        self.tools = _capture_tools(register_session_tools, self.sm)
        self.fn = self.tools["get_session_pmids"]

    def test_no_session(self):
        self.sm.get_current_session.return_value = None
        result = json.loads(self.fn())
        assert result["success"] is False
        assert "No active session" in result["error"]

    def test_no_history(self):
        self.sm.get_current_session.return_value = _make_session()
        result = json.loads(self.fn())
        assert result["success"] is False
        assert "No search history" in result["error"]

    def test_last_search(self):
        history = [
            {"query": "covid", "pmids": ["111", "222"], "timestamp": "2024-01-01"},
            {"query": "cancer", "pmids": ["333", "444"], "timestamp": "2024-01-02"},
        ]
        self.sm.get_current_session.return_value = _make_session(search_history=history)
        result = json.loads(self.fn())
        assert result["success"] is True
        assert result["pmids"] == ["333", "444"]
        assert result["query"] == "cancer"

    def test_specific_index(self):
        history = [
            {"query": "covid", "pmids": ["111"], "timestamp": ""},
            {"query": "cancer", "pmids": ["222"], "timestamp": ""},
        ]
        self.sm.get_current_session.return_value = _make_session(search_history=history)
        result = json.loads(self.fn(search_index=0))
        assert result["success"] is True
        assert result["pmids"] == ["111"]

    def test_invalid_index(self):
        history = [{"query": "test", "pmids": [], "timestamp": ""}]
        self.sm.get_current_session.return_value = _make_session(search_history=history)
        result = json.loads(self.fn(search_index=99))
        assert result["success"] is False

    def test_query_filter_match(self):
        history = [
            {"query": "COVID treatment", "pmids": ["111"], "timestamp": ""},
            {"query": "cancer research", "pmids": ["222"], "timestamp": ""},
        ]
        self.sm.get_current_session.return_value = _make_session(search_history=history)
        result = json.loads(self.fn(query_filter="COVID"))
        assert result["success"] is True
        assert result["pmids"] == ["111"]

    def test_query_filter_no_match(self):
        history = [{"query": "cancer", "pmids": ["111"], "timestamp": ""}]
        self.sm.get_current_session.return_value = _make_session(search_history=history)
        result = json.loads(self.fn(query_filter="XXXXX"))
        assert result["success"] is False

    def test_pmids_csv_field(self):
        history = [{"query": "test", "pmids": ["111", "222"], "timestamp": ""}]
        self.sm.get_current_session.return_value = _make_session(search_history=history)
        result = json.loads(self.fn())
        assert result["pmids_csv"] == "111,222"

    def test_exception(self):
        self.sm.get_current_session.side_effect = RuntimeError("DB error")
        result = json.loads(self.fn())
        assert result["success"] is False


# ============================================================
# list_search_history
# ============================================================

class TestListSearchHistory:
    def setup_method(self):
        self.sm = MagicMock()
        self.tools = _capture_tools(register_session_tools, self.sm)
        self.fn = self.tools["list_search_history"]

    def test_no_session(self):
        self.sm.get_current_session.return_value = None
        result = json.loads(self.fn())
        assert result["success"] is False

    def test_with_history(self):
        history = [
            {"query": "test1", "pmids": ["1"], "timestamp": "2024-01-01T12:00:00Z", "result_count": 1},
            {"query": "test2", "pmids": ["2", "3"], "timestamp": "2024-01-02T12:00:00Z", "result_count": 2},
        ]
        session = _make_session(search_history=history)
        self.sm.get_current_session.return_value = session
        result = json.loads(self.fn())
        assert result["success"] is True
        assert result["total_searches"] == 2
        assert len(result["history"]) == 2

    def test_limit(self):
        history = [{"query": f"q{i}", "pmids": [], "timestamp": "", "result_count": 0} for i in range(20)]
        self.sm.get_current_session.return_value = _make_session(search_history=history)
        result = json.loads(self.fn(limit=5))
        assert len(result["history"]) == 5

    def test_exception(self):
        self.sm.get_current_session.side_effect = RuntimeError("fail")
        result = json.loads(self.fn())
        assert result["success"] is False


# ============================================================
# get_cached_article
# ============================================================

class TestGetCachedArticle:
    def setup_method(self):
        self.sm = MagicMock()
        self.tools = _capture_tools(register_session_tools, self.sm)
        self.fn = self.tools["get_cached_article"]

    def test_no_session(self):
        self.sm.get_current_session.return_value = None
        result = json.loads(self.fn(pmid="12345"))
        assert result["success"] is False

    def test_not_cached(self):
        session = _make_session(article_cache={})
        self.sm.get_current_session.return_value = session
        result = json.loads(self.fn(pmid="12345"))
        assert result["success"] is False
        assert "not in cache" in result["error"]

    def test_found_in_cache(self):
        article = {"pmid": "12345", "title": "Test Article"}
        session = _make_session(article_cache={"12345": article})
        self.sm.get_current_session.return_value = session
        result = json.loads(self.fn(pmid="12345"))
        assert result["success"] is True
        assert result["source"] == "cache"
        assert result["article"]["title"] == "Test Article"

    def test_exception(self):
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

    def test_no_session(self):
        self.sm.get_current_session.return_value = None
        result = json.loads(self.fn())
        assert result["success"] is False
        assert result["has_session"] is False

    def test_with_session(self):
        history = [{"query": "test", "pmids": ["111", "222"]}]
        cache = {"111": {"title": "A"}, "222": {"title": "B"}}
        session = _make_session(search_history=history, article_cache=cache)
        self.sm.get_current_session.return_value = session
        result = json.loads(self.fn())
        assert result["success"] is True
        assert result["has_session"] is True
        assert result["stats"]["cached_articles"] == 2
        assert result["stats"]["total_searches"] == 1

    def test_exception(self):
        self.sm.get_current_session.side_effect = RuntimeError("fail")
        result = json.loads(self.fn())
        assert result["success"] is False


# ============================================================
# register_session_resources
# ============================================================

class TestSessionResources:
    def test_context_with_session(self):
        sm = MagicMock()
        session = _make_session(article_cache={"111": {}})
        session.search_history = [{"q": "test"}]
        sm.get_current_session.return_value = session
        tools = _capture_tools(register_session_resources, sm)
        fn = tools["session://context"]
        result = json.loads(fn())
        assert result["active"] is True
        assert result["cached_articles"] == 1

    def test_context_no_session(self):
        sm = MagicMock()
        sm.get_current_session.return_value = None
        tools = _capture_tools(register_session_resources, sm)
        fn = tools["session://context"]
        result = json.loads(fn())
        assert result["active"] is False
