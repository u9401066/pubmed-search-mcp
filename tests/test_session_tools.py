"""Tests for session_tools.py — PMID persistence and session management tools."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import TypeAdapter, ValidationError

from pubmed_search.application.session.manager import SessionManager
from pubmed_search.presentation.mcp_server.session_tools import (
    DEFAULT_ARTIFACT_READ_MAX_CHARS,
    LAST_SEARCH_RESOURCE_ARTICLE_LIMIT,
    SESSION_RESOURCE_URIS,
    SessionReadRequest,
    notify_session_resources_updated,
    register_session_resources,
    register_session_tools,
)

_SESSION_REQUEST_ADAPTER = TypeAdapter(SessionReadRequest)


def _read_request(action="summary", **kwargs):
    """Build the same discriminated request object that MCP validation supplies."""
    request = {"action": action, **kwargs}
    if action == "artifact":
        artifact_id = request.pop("artifact_id", None)
        artifact_uri = request.pop("artifact_uri", None)
        session_id = request.pop("session_id", None)
        if artifact_id is not None:
            request["locator"] = {
                "kind": "artifact_id",
                "value": artifact_id,
                **({"session_id": session_id} if session_id is not None else {}),
            }
        elif artifact_uri is not None:
            request["locator"] = {"kind": "artifact_uri", "value": artifact_uri}
    elif action == "list_artifacts":
        if "artifact_tool" in request:
            request["tool"] = request.pop("artifact_tool")
        if "artifact_kind" in request:
            request["kind"] = request.pop("artifact_kind")
        if "history_limit" in request:
            request["limit"] = request.pop("history_limit")
    elif action == "search_runs":
        if "run_status" in request:
            request["status"] = request.pop("run_status")
        if "history_limit" in request:
            request["limit"] = request.pop("history_limit")
    elif action == "log" and "query_filter" in request:
        request["kind"] = request.pop("query_filter")
    return _SESSION_REQUEST_ADAPTER.validate_python(request, strict=True)


def _read_session(fn, action="summary", **kwargs):
    return fn(request=_read_request(action, **kwargs))


def _capture_read_session(manager):
    fn = _capture_tools(register_session_tools, manager)["read_session"]
    return lambda action="summary", **kwargs: _read_session(fn, action, **kwargs)


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


def _make_session(search_history=None):
    session = MagicMock()
    session.search_history = search_history or []
    session.event_log = []
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
        assert set(tools) == {"read_session"}


# ============================================================
# read_session
# ============================================================


class TestReadSession:
    def setup_method(self):
        self.sm = MagicMock()
        self.tools = _capture_tools(register_session_tools, self.sm)
        self.fn = lambda action="summary", **kwargs: _read_session(self.tools["read_session"], action, **kwargs)

    async def test_summary_action(self):
        history = [{"query": "test", "pmids": ["111"]}]
        cache = {"111": {"title": "A"}}
        session = _make_session(search_history=history)
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
        session = _make_session()
        self.sm.get_current_session.return_value = session
        _configure_manager_cache(self.sm, {"12345": article})

        result = json.loads(self.fn(action="article", pmid="12345"))
        assert result["success"] is True
        assert result["article"]["title"] == "Test Article"

    async def test_unknown_action(self):
        with pytest.raises(ValidationError):
            self.fn(action="unknown")

    async def test_action_aliases_and_case_coercion_are_rejected(self):
        for action in ("PMIDS", "last_search", "cached_article"):
            with pytest.raises(ValidationError):
                self.fn(action=action)

    async def test_each_action_forbids_fields_owned_by_other_actions(self):
        with pytest.raises(ValidationError, match="extra_forbidden"):
            _read_request("summary", pmid="12345")
        with pytest.raises(ValidationError, match="extra_forbidden"):
            _read_request("pmids", include_history=True)
        with pytest.raises(ValidationError, match="extra_forbidden"):
            _read_request("search_run", run_id="run-1", status="failed")

    async def test_artifact_locator_is_exactly_one_typed_address(self):
        with pytest.raises(ValidationError):
            _read_request("artifact")
        with pytest.raises(ValidationError):
            _SESSION_REQUEST_ADAPTER.validate_python(
                {
                    "action": "artifact",
                    "locator": {
                        "kind": "artifact_uri",
                        "value": "artifact://session/id",
                        "session_id": "conflict",
                    },
                },
                strict=True,
            )

    async def test_log_action(self):
        session = _make_session(
            search_history=[{"query": "test", "pmids": ["111"], "timestamp": "2024-01-01T00:00:00Z"}]
        )
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

    async def test_artifact_action_reads_persisted_artifact(self, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        manifest = manager.save_artifact(
            tool="unified_search",
            kind="search_results",
            files={"results.json": {"tool": "unified_search", "articles": []}, "notes.md": "abcdef"},
            primary_file="results.json",
        )
        fn = _capture_read_session(manager)

        result = json.loads(fn(action="artifact", artifact_id=manifest["artifact_id"]))

        assert result["success"] is True
        assert result["artifact"]["artifact_id"] == manifest["artifact_id"]
        assert "local_path" not in result["artifact"]
        assert "path" not in result["file"]
        assert json.loads(result["content"])["tool"] == "unified_search"

        page = json.loads(
            fn(
                action="artifact",
                artifact_uri=manifest["artifact_uri"],
                artifact_file="notes.md",
                max_chars=3,
                offset=2,
            )
        )
        assert page["content"] == "cde"
        assert page["next_offset"] == 5

        local_page = json.loads(fn(action="artifact", artifact_id=manifest["artifact_id"], include_local_paths=True))
        assert "local_path" not in local_page["artifact"]
        assert "path" not in local_page["file"]

        with patch("pubmed_search.presentation.mcp_server.session_tools.load_settings") as mock_settings:
            mock_settings.return_value.artifact_include_local_paths = True
            local_page = json.loads(
                fn(action="artifact", artifact_id=manifest["artifact_id"], include_local_paths=True)
            )
        assert "local_path" in local_page["artifact"]
        assert "path" in local_page["file"]

    async def test_artifact_action_rejects_non_positive_max_chars(self, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        content = "a" * (DEFAULT_ARTIFACT_READ_MAX_CHARS + 10)
        manifest = manager.save_artifact(
            tool="unified_search",
            kind="search_results",
            files={"notes.md": content},
            primary_file="notes.md",
        )
        fn = _capture_read_session(manager)

        with pytest.raises(ValidationError):
            fn(action="artifact", artifact_id=manifest["artifact_id"], max_chars=0)
        with pytest.raises(ValidationError):
            fn(action="artifact", artifact_id=manifest["artifact_id"], max_chars=-1)

    async def test_log_action_history_limit_does_not_limit_events(self):
        session = _make_session(
            search_history=[{"query": f"q{i}", "pmids": [str(i)], "timestamp": "2024-01-01"} for i in range(10)]
        )
        session.event_log = [{"timestamp": "2024-01-01", "kind": "event", "message": f"event {i}"} for i in range(20)]
        self.sm.get_current_session.return_value = session

        def _get_events(*, limit=50, kind=None):
            del kind
            return session.event_log[-limit:]

        self.sm.get_session_event_log.side_effect = _get_events

        result = json.loads(self.fn(action="log", include_history=True, history_limit=5))

        assert result["returned_events"] == 20
        assert len(result["search_history"]) == 5

    async def test_list_artifacts_action(self, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        manager.save_artifact(
            tool="get_fulltext",
            kind="fulltext",
            files={"fulltext.md": "Body"},
            primary_file="fulltext.md",
        )
        fn = _capture_read_session(manager)

        result = json.loads(fn(action="list_artifacts"))

        assert result["success"] is True
        assert result["total_artifacts"] == 1
        assert result["artifacts"][0]["tool"] == "get_fulltext"
        assert "local_path" not in result["artifacts"][0]

        local_result = json.loads(fn(action="list_artifacts", include_local_paths=True))
        assert "local_path" not in local_result["artifacts"][0]

        with patch("pubmed_search.presentation.mcp_server.session_tools.load_settings") as mock_settings:
            mock_settings.return_value.artifact_include_local_paths = True
            local_result = json.loads(fn(action="list_artifacts", include_local_paths=True))
        assert "local_path" in local_result["artifacts"][0]

    async def test_artifact_read_error_redacts_local_paths(self, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        manifest = manager.save_artifact(
            tool="unified_search",
            kind="search_results",
            files={"results.json": {"tool": "unified_search"}},
            primary_file="results.json",
        )
        Path(manifest["local_path"]).unlink()
        fn = _capture_read_session(manager)

        result = json.loads(fn(action="artifact", artifact_id=manifest["artifact_id"]))

        assert result["success"] is False
        assert result["error"] == "Artifact file could not be read"
        assert "artifact" not in result

    async def test_list_artifacts_rejects_unsafe_session_id(self, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        fn = _capture_read_session(manager)

        with pytest.raises(ValidationError):
            fn(action="list_artifacts", session_id="../outside")

    async def test_search_run_actions_expose_recovery_and_explicit_replay(self, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        run = manager.start_search_run(
            "durable query",
            request={"query": "durable query", "limit": 30, "options": "systematic"},
        )
        manager.fail_search_run(str(run["run_id"]), "provider unavailable", stage="execution")
        assert manager.get_search_run_status_counts() == {"failed": 1}
        fn = _capture_read_session(manager)

        listing = json.loads(fn(action="search_runs", run_status="failed"))
        detail = json.loads(fn(action="search_run", run_id=run["run_id"]))
        replay = json.loads(fn(action="replay_search", run_id=run["run_id"]))

        assert listing["success"] is True
        assert listing["returned_runs"] == 1
        assert listing["runs"][0]["run_id"] == run["run_id"]
        assert detail["run"]["failure"]["stage"] == "execution"
        assert replay["automatic_execution"] is False
        assert replay["replay"]["tool"] == "unified_search"
        assert replay["replay"]["arguments"] == {
            "query": "durable query",
            "limit": 30,
            "options": "systematic",
        }

    async def test_search_run_actions_require_known_run_id(self, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        manager.get_or_create_session("empty")
        fn = _capture_read_session(manager)

        with pytest.raises(ValidationError):
            fn(action="search_run")
        unknown = json.loads(fn(action="replay_search", run_id="unknown"))

        assert unknown["success"] is False
        assert "not found" in unknown["error"].lower()


# ============================================================
# read_session(action="pmids")
# ============================================================


class TestReadSessionPmids:
    def setup_method(self):
        self.sm = MagicMock()
        self.tools = _capture_tools(register_session_tools, self.sm)
        self.fn = lambda **kwargs: _read_session(self.tools["read_session"], "pmids", **kwargs)

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
        assert "DB error" not in result["error"]


# ============================================================
# read_session(action="article")
# ============================================================


class TestReadSessionArticle:
    def setup_method(self):
        self.sm = MagicMock()
        self.tools = _capture_tools(register_session_tools, self.sm)
        self.fn = lambda **kwargs: _read_session(self.tools["read_session"], "article", **kwargs)

    async def test_no_session(self):
        self.sm.get_current_session.return_value = None
        result = json.loads(self.fn(pmid="12345"))
        assert result["success"] is False

    async def test_not_cached(self):
        session = _make_session()
        self.sm.get_current_session.return_value = session
        _configure_manager_cache(self.sm, {})
        result = json.loads(self.fn(pmid="12345"))
        assert result["success"] is False
        assert "not in cache" in result["error"]

    async def test_found_in_cache(self):
        article = {"pmid": "12345", "title": "Test Article"}
        session = _make_session()
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
        assert result["error"] == "Session read failed"


# ============================================================
# read_session(action="summary")
# ============================================================


class TestReadSessionSummary:
    def setup_method(self):
        self.sm = MagicMock()
        self.tools = _capture_tools(register_session_tools, self.sm)
        self.fn = lambda **kwargs: _read_session(self.tools["read_session"], "summary", **kwargs)

    async def test_no_session(self):
        self.sm.get_current_session.return_value = None
        result = json.loads(self.fn())
        assert result["success"] is False
        assert result["has_session"] is False

    async def test_with_session(self):
        history = [{"query": "test", "pmids": ["111", "222"]}]
        cache = {"111": {"title": "A"}, "222": {"title": "B"}}
        session = _make_session(search_history=history)
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
        session = _make_session(search_history=history)
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
        session = _make_session(search_history=history)
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
        session = _make_session(search_history=history)
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
        session = _make_session()
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
        )
        sm.get_current_session.return_value = session
        _configure_manager_cache(sm, {"111": {"pmid": "111", "title": "Cached"}})
        tools = _capture_tools(register_session_resources, sm)
        result = json.loads(tools["session://last-search/results"]())
        assert result["cached_count"] == 1
        assert result["cached_results"][0]["title"] == "Cached"
        assert result["missing_pmids"] == ["999"]

    async def test_last_search_results_resource_caps_cached_payloads(self):
        sm = MagicMock()
        pmids = [str(i) for i in range(30)]
        cache = {pmid: {"pmid": pmid, "title": f"Cached {pmid}"} for pmid in pmids}
        session = _make_session(search_history=[{"query": "covid", "pmids": pmids, "result_count": len(pmids)}])
        sm.get_current_session.return_value = session
        _configure_manager_cache(sm, cache)

        tools = _capture_tools(register_session_resources, sm)
        result = json.loads(tools["session://last-search/results"]())

        assert result["cached_count"] == LAST_SEARCH_RESOURCE_ARTICLE_LIMIT
        assert result["returned_pmid_count"] == LAST_SEARCH_RESOURCE_ARTICLE_LIMIT
        assert result["total_pmid_count"] == len(pmids)
        assert result["resource_limit"] == LAST_SEARCH_RESOURCE_ARTICLE_LIMIT
        assert result["truncated"] is True
        assert result["omitted_pmids"] == pmids[LAST_SEARCH_RESOURCE_ARTICLE_LIMIT:]
        assert result["cached_results"][-1]["pmid"] == pmids[LAST_SEARCH_RESOURCE_ARTICLE_LIMIT - 1]

    async def test_activity_resource(self):
        sm = MagicMock()
        session = _make_session(
            search_history=[{"query": "covid", "pmids": ["111", "222"], "timestamp": "2024-01-01", "result_count": 2}],
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
