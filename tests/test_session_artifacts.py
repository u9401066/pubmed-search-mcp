"""Tests for persistent MCP output artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from pubmed_search.application.session.manager import SessionManager
from pubmed_search.presentation.mcp_server.tools._common import set_session_manager
from pubmed_search.presentation.mcp_server.tools.artifact_memory import persist_tool_artifact


def test_session_manager_saves_artifact_files_and_manifest(tmp_path: Path):
    manager = SessionManager(data_dir=str(tmp_path))

    manifest = manager.save_artifact(
        tool="unified_search",
        kind="search_results",
        files={
            "results.json": {"tool": "unified_search", "articles": [{"pmid": "123"}]},
            "query.md": "# Query\n\nremimazolam sedation\n",
        },
        primary_file="results.json",
        summary={"query": "remimazolam sedation", "returned": 1},
    )

    assert manifest is not None
    assert manifest["tool"] == "unified_search"
    assert manifest["kind"] == "search_results"
    assert manifest["artifact_uri"].startswith("artifact://")
    assert Path(manifest["local_path"]).is_file()
    assert Path(manifest["manifest_path"]).is_file()

    stored = json.loads(Path(manifest["local_path"]).read_text(encoding="utf-8"))
    assert stored["articles"][0]["pmid"] == "123"

    reloaded = SessionManager(data_dir=str(tmp_path))
    artifacts = reloaded.list_artifacts()
    assert len(artifacts) == 1
    assert artifacts[0]["artifact_id"] == manifest["artifact_id"]


def test_session_manager_reads_artifact_content_by_id(tmp_path: Path):
    manager = SessionManager(data_dir=str(tmp_path))
    manifest = manager.save_artifact(
        tool="get_fulltext",
        kind="fulltext",
        files={"fulltext.md": "Full text body", "links.json": [{"url": "https://example.test/paper.pdf"}]},
        primary_file="fulltext.md",
    )

    result = manager.read_artifact(manifest["artifact_id"])

    assert result["success"] is True
    assert result["artifact"]["artifact_id"] == manifest["artifact_id"]
    assert result["file"]["name"] == "fulltext.md"
    assert result["content"] == "Full text body"


def test_session_manager_reads_artifact_by_uri_with_offset(tmp_path: Path):
    manager = SessionManager(data_dir=str(tmp_path))
    manifest = manager.save_artifact(
        tool="unified_search",
        kind="search_results",
        files={"results.json": "0123456789"},
        primary_file="results.json",
    )

    result = manager.read_artifact(
        artifact_uri=manifest["artifact_uri"],
        max_chars=4,
        offset=3,
    )

    assert result["success"] is True
    assert result["content"] == "3456"
    assert result["offset"] == 3
    assert result["next_offset"] == 7
    assert result["truncated"] is True


def test_artifact_read_rejects_checksum_mismatch(tmp_path: Path):
    manager = SessionManager(data_dir=str(tmp_path))
    manifest = manager.save_artifact(
        tool="unified_search",
        kind="search_results",
        files={"results.json": {"ok": True}},
        primary_file="results.json",
    )
    Path(manifest["local_path"]).write_text('{"ok": false}', encoding="utf-8")

    result = manager.read_artifact(manifest["artifact_id"])

    assert result["success"] is False
    assert "checksum mismatch" in result["error"].lower()


def test_artifact_read_rejects_missing_checksum(tmp_path: Path):
    manager = SessionManager(data_dir=str(tmp_path))
    manifest = manager.save_artifact(
        tool="unified_search",
        kind="search_results",
        files={"results.json": {"ok": True}},
        primary_file="results.json",
    )
    manifest["files"]["results.json"].pop("sha256")

    result = manager.read_artifact(manifest["artifact_id"])

    assert result["success"] is False
    assert "checksum missing or invalid" in result["error"].lower()


def test_session_manager_rejects_tampered_artifact_root_path(tmp_path: Path):
    manager = SessionManager(data_dir=str(tmp_path))
    manifest = manager.save_artifact(
        tool="unified_search",
        kind="search_results",
        files={"results.json": "body"},
        primary_file="results.json",
    )
    manifest["root_path"] = str(tmp_path.parent)

    result = manager.read_artifact(manifest["artifact_id"])

    assert result["success"] is False
    assert "escapes root" in result["error"]


def test_session_manager_rejects_unsafe_session_id(tmp_path: Path):
    manager = SessionManager(data_dir=str(tmp_path))

    result = manager.read_artifact("anything", session_id="../outside")

    assert result["success"] is False
    assert "unsafe session id" in result["error"].lower()


def test_persist_tool_artifact_returns_none_without_data_dir():
    manager = SessionManager()
    set_session_manager(manager)
    try:
        result = persist_tool_artifact(
            tool="unified_search",
            kind="search_results",
            files={"results.json": "{}"},
            primary_file="results.json",
        )
    finally:
        set_session_manager(None)

    assert result is None


def test_persist_tool_artifact_redacts_local_paths_by_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS", raising=False)
    manager = SessionManager(data_dir=str(tmp_path))
    set_session_manager(manager)
    try:
        result = persist_tool_artifact(
            tool="unified_search",
            kind="search_results",
            files={"results.json": "{}"},
            primary_file="results.json",
        )
    finally:
        set_session_manager(None)

    assert result is not None
    assert "local_path" not in result
    assert "manifest_path" not in result


def test_persist_tool_artifact_can_include_local_paths_for_local_workflows(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS", "true")
    manager = SessionManager(data_dir=str(tmp_path))
    set_session_manager(manager)
    try:
        result = persist_tool_artifact(
            tool="unified_search",
            kind="search_results",
            files={"results.json": "{}"},
            primary_file="results.json",
        )
    finally:
        set_session_manager(None)

    assert result is not None
    assert Path(result["local_path"]).is_file()
    assert Path(result["manifest_path"]).is_file()
