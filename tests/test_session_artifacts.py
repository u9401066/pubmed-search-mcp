"""Tests for persistent MCP output artifacts."""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from pubmed_search.application.session import artifacts as artifact_module
from pubmed_search.application.session.artifacts import ArtifactStore
from pubmed_search.application.session.manager import SessionManager
from pubmed_search.presentation.mcp_server.tools import artifact_memory as artifact_memory_module
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


def test_artifact_ids_stay_unique_and_readable_with_frozen_clock(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(artifact_module, "_utcnow_iso", lambda: "2026-08-09T00:00:00+00:00")
    store = ArtifactStore(tmp_path / "artifacts")

    def _save(index: int) -> dict[str, object]:
        return store.save(
            session_id="concurrent-session",
            tool="unified_search",
            kind="search_results",
            files={"results.json": {"index": index}},
            primary_file="results.json",
        )

    with ThreadPoolExecutor(max_workers=16) as executor:
        manifests = list(executor.map(_save, range(16)))

    artifact_ids = [str(manifest["artifact_id"]) for manifest in manifests]
    assert len(set(artifact_ids)) == 16
    assert all(len(artifact_id) == 32 for artifact_id in artifact_ids)
    for index, manifest in enumerate(manifests):
        _file_info, content = store.read_file(manifest)
        assert json.loads(content) == {"index": index}
    assert not list((tmp_path / "artifacts").rglob("*.staging"))


def test_failed_artifact_publish_cleans_private_staging_tree(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")

    with pytest.raises(TypeError):
        store.save(
            session_id="session",
            tool="unified_search",
            kind="search_results",
            files={"ok.txt": "complete", "bad.json": object()},
            primary_file="ok.txt",
        )

    assert not list((tmp_path / "artifacts").rglob("*.staging"))
    assert not list((tmp_path / "artifacts").rglob("manifest.json"))


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
    assert result["error"] == "Artifact file could not be read"


def test_artifact_read_rejects_missing_checksum(tmp_path: Path):
    manager = SessionManager(data_dir=str(tmp_path))
    manifest = manager.save_artifact(
        tool="unified_search",
        kind="search_results",
        files={"results.json": {"ok": True}},
        primary_file="results.json",
    )
    session_path = tmp_path / f"session_{manifest['session_id']}.json"
    session_payload = json.loads(session_path.read_text(encoding="utf-8"))
    session_payload["artifacts"][0]["files"]["results.json"].pop("sha256")
    session_path.write_text(json.dumps(session_payload), encoding="utf-8")
    manager = SessionManager(data_dir=str(tmp_path))

    result = manager.read_artifact(manifest["artifact_id"])

    assert result["success"] is False
    assert result["error"] == "Artifact file could not be read"


def test_session_manager_rejects_tampered_artifact_root_path(tmp_path: Path):
    manager = SessionManager(data_dir=str(tmp_path))
    manifest = manager.save_artifact(
        tool="unified_search",
        kind="search_results",
        files={"results.json": "body"},
        primary_file="results.json",
    )
    session_path = tmp_path / f"session_{manifest['session_id']}.json"
    session_payload = json.loads(session_path.read_text(encoding="utf-8"))
    session_payload["artifacts"][0]["root_path"] = str(tmp_path.parent)
    session_path.write_text(json.dumps(session_payload), encoding="utf-8")
    manager = SessionManager(data_dir=str(tmp_path))

    result = manager.read_artifact(manifest["artifact_id"])

    assert result["success"] is False
    assert result["error"] == "Artifact file could not be read"


def test_session_manager_rejects_unsafe_session_id(tmp_path: Path):
    manager = SessionManager(data_dir=str(tmp_path))

    result = manager.read_artifact("anything", session_id="../outside")

    assert result["success"] is False
    assert result["error"] == "Artifact lookup failed"


@pytest.mark.asyncio
async def test_persist_tool_artifact_returns_none_without_data_dir():
    manager = SessionManager()
    set_session_manager(manager)
    try:
        result = await persist_tool_artifact(
            tool="unified_search",
            kind="search_results",
            files={"results.json": "{}"},
            primary_file="results.json",
        )
    finally:
        set_session_manager(None)

    assert result is None


@pytest.mark.asyncio
async def test_persist_tool_artifact_redacts_local_paths_by_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS", raising=False)
    manager = SessionManager(data_dir=str(tmp_path))
    set_session_manager(manager)
    try:
        result = await persist_tool_artifact(
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


@pytest.mark.asyncio
async def test_persist_tool_artifact_can_include_local_paths_for_local_workflows(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS", "true")
    manager = SessionManager(data_dir=str(tmp_path))
    set_session_manager(manager)
    try:
        result = await persist_tool_artifact(
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


@pytest.mark.asyncio
async def test_persist_tool_artifact_offloads_save_and_settings_without_blocking_loop(tmp_path: Path, monkeypatch):
    manager = SessionManager(data_dir=str(tmp_path))
    original_save = manager.save_artifact
    original_load_settings = artifact_memory_module.load_settings
    save_started = threading.Event()
    release_save = threading.Event()
    heartbeat_ran = asyncio.Event()
    main_thread = threading.get_ident()
    worker_threads: dict[str, int] = {}

    def blocking_save(**kwargs):
        worker_threads["save"] = threading.get_ident()
        save_started.set()
        if not release_save.wait(timeout=1.0):
            raise RuntimeError("event loop did not release artifact save")
        return original_save(**kwargs)

    def tracked_load_settings():
        worker_threads["settings"] = threading.get_ident()
        return original_load_settings()

    async def heartbeat() -> None:
        while not save_started.is_set():
            await asyncio.sleep(0)
        heartbeat_ran.set()
        release_save.set()

    monkeypatch.setattr(manager, "save_artifact", blocking_save)
    monkeypatch.setattr(artifact_memory_module, "load_settings", tracked_load_settings)
    set_session_manager(manager)
    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        result = await asyncio.wait_for(
            persist_tool_artifact(
                tool="get_fulltext",
                kind="fulltext",
                files={"fulltext.md": "body"},
                primary_file="fulltext.md",
            ),
            timeout=0.5,
        )
        await heartbeat_task
    finally:
        release_save.set()
        set_session_manager(None)

    assert result is not None
    assert heartbeat_ran.is_set()
    assert worker_threads["save"] != main_thread
    assert worker_threads["settings"] != main_thread


def test_read_artifact_lookup_failure_does_not_leak_path_or_credentials(tmp_path: Path, caplog):
    manager = SessionManager(data_dir=str(tmp_path))
    secret = "api_key=private-lookup"

    result = manager.read_artifact("artifact", session_id=f"../{secret}")

    rendered = json.dumps(result)
    assert result == {"success": False, "error": "Artifact lookup failed"}
    assert secret not in rendered
    assert str(tmp_path) not in rendered
    assert secret not in caplog.text
    assert str(tmp_path) not in caplog.text


def test_read_artifact_file_failure_does_not_leak_host_path_or_credentials(tmp_path: Path, caplog):
    private_dir = tmp_path / "api_key=private-read"
    manager = SessionManager(data_dir=str(private_dir))
    manifest = manager.save_artifact(
        tool="get_fulltext",
        kind="fulltext",
        files={"fulltext.md": "body"},
        primary_file="fulltext.md",
    )
    Path(manifest["local_path"]).unlink()

    result = manager.read_artifact(manifest["artifact_id"])

    rendered = json.dumps(result)
    assert result == {"success": False, "error": "Artifact file could not be read"}
    assert "private-read" not in rendered
    assert str(private_dir) not in rendered
    assert "private-read" not in caplog.text
    assert str(private_dir) not in caplog.text
