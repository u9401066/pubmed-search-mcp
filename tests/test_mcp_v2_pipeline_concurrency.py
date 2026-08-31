"""MCP SDK v2 worker-thread and pipeline persistence regressions."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.server import MCPServer

from pubmed_search.application.pipeline.store import PipelineStore
from pubmed_search.domain.entities.pipeline import PipelineConfig, PipelineRun, PipelineStep, ScheduleEntry
from pubmed_search.presentation.mcp_server.tools.pipeline_tools import (
    PipelineToolRuntime,
    register_pipeline_tools,
)
from pubmed_search.presentation.mcp_server.tools.unified import register_unified_search_tools

if TYPE_CHECKING:
    from pathlib import Path

_CONFIG = "steps:\n  - id: search\n    action: search\n    params:\n      query: safety"


@pytest.mark.asyncio
async def test_mcp_v2_concurrent_sync_saves_keep_every_index_entry(tmp_path: Path) -> None:
    """Exercise the public SDK call path that offloads sync tools to workers."""
    store = PipelineStore(global_data_dir=tmp_path)
    server = MCPServer("pipeline-concurrency-test")
    register_pipeline_tools(server, runtime=PipelineToolRuntime(base_store=store))

    results = await asyncio.gather(
        *(
            server.call_tool(
                "save_pipeline",
                {"name": f"parallel_{index}", "config": _CONFIG, "scope": "global"},
            )
            for index in range(8)
        )
    )

    assert all(not result.is_error for result in results)
    yaml_files = sorted((tmp_path / "pipelines").glob("parallel_*.yaml"))
    index = json.loads((tmp_path / "pipelines" / "_index.json").read_text(encoding="utf-8"))
    assert len(yaml_files) == 8
    assert set(index) == {f"parallel_{number}" for number in range(8)}


@pytest.mark.asyncio
async def test_two_servers_keep_pipeline_tool_stores_isolated_when_calls_interleave(tmp_path: Path) -> None:
    """Registering server B must never redirect server A's later writes."""
    store_a = PipelineStore(global_data_dir=tmp_path / "server-a")
    store_b = PipelineStore(global_data_dir=tmp_path / "server-b")
    server_a = MCPServer("pipeline-server-a")
    server_b = MCPServer("pipeline-server-b")
    register_pipeline_tools(server_a, runtime=PipelineToolRuntime(base_store=store_a))
    register_pipeline_tools(server_b, runtime=PipelineToolRuntime(base_store=store_b))

    result_a, result_b = await asyncio.gather(
        server_a.call_tool(
            "save_pipeline",
            {"name": "owned_by_a", "config": _CONFIG, "scope": "global"},
        ),
        server_b.call_tool(
            "save_pipeline",
            {"name": "owned_by_b", "config": _CONFIG, "scope": "global"},
        ),
    )

    assert result_a.is_error is False
    assert result_b.is_error is False
    assert store_a.exists("owned_by_a") is True
    assert store_a.exists("owned_by_b") is False
    assert store_b.exists("owned_by_b") is True
    assert store_b.exists("owned_by_a") is False


@pytest.mark.asyncio
async def test_two_create_server_instances_keep_distinct_pipeline_roots(tmp_path: Path) -> None:
    """Exercise the production registry path after both servers are constructed."""
    from pubmed_search.presentation.mcp_server.server import create_server

    root_a = tmp_path / "created-a"
    root_b = tmp_path / "created-b"
    server_a = create_server(
        email="test@example.com",
        name="created-server-a",
        data_dir=str(root_a),
        mode="local",
    )
    server_b = create_server(
        email="test@example.com",
        name="created-server-b",
        data_dir=str(root_b),
        mode="local",
    )

    result_a, result_b = await asyncio.gather(
        server_a.call_tool(
            "save_pipeline",
            {"name": "created_a_only", "config": _CONFIG, "scope": "global"},
        ),
        server_b.call_tool(
            "save_pipeline",
            {"name": "created_b_only", "config": _CONFIG, "scope": "global"},
        ),
    )

    assert result_a.is_error is False
    assert result_b.is_error is False
    assert (root_a / "pipelines" / "created_a_only.yaml").is_file()
    assert not (root_a / "pipelines" / "created_b_only.yaml").exists()
    assert (root_b / "pipelines" / "created_b_only.yaml").is_file()
    assert not (root_b / "pipelines" / "created_a_only.yaml").exists()


@pytest.mark.asyncio
async def test_two_create_server_tool_managers_bind_their_own_session_and_strategy_runtime(tmp_path: Path) -> None:
    """Constructing B must not redirect direct tool-manager invocations made on A."""
    from pubmed_search.presentation.mcp_server.server import create_server, get_container

    root_a = tmp_path / "runtime-a"
    root_b = tmp_path / "runtime-b"
    server_a = create_server(email="test@example.com", name="runtime-a", data_dir=str(root_a), mode="local")
    server_b = create_server(email="test@example.com", name="runtime-b", data_dir=str(root_b), mode="local")

    runtime_a = server_a.get_tool_session_runtime()
    runtime_b = server_b.get_tool_session_runtime()
    assert get_container(server_a) is not get_container(server_b)
    assert runtime_a.session_manager is not runtime_b.session_manager
    assert runtime_a.session_registry is not runtime_b.session_registry
    generate_a = AsyncMock(return_value={"runtime_owner": "a"})
    generate_b = AsyncMock(return_value={"runtime_owner": "b"})
    runtime_a.strategy_generator.generate_strategies = generate_a
    runtime_b.strategy_generator.generate_strategies = generate_b

    strategy_a = server_a._tool_manager._tools["generate_search_queries"].fn
    strategy_b = server_b._tool_manager._tools["generate_search_queries"].fn
    result_strategy_a, result_strategy_b = await asyncio.gather(
        strategy_a(topic="alpha"),
        strategy_b(topic="beta"),
    )

    assert json.loads(result_strategy_a)["runtime_owner"] == "a"
    assert json.loads(result_strategy_b)["runtime_owner"] == "b"
    generate_a.assert_awaited_once()
    generate_b.assert_awaited_once()


@pytest.mark.asyncio
async def test_two_unified_search_registrations_resolve_saved_pipeline_from_own_server(tmp_path: Path) -> None:
    """Saved-pipeline resolution is closure-injected, not process-global."""
    store_a = PipelineStore(global_data_dir=tmp_path / "unified-a")
    store_b = PipelineStore(global_data_dir=tmp_path / "unified-b")
    store_a.save(
        "shared",
        PipelineConfig(
            steps=[PipelineStep(id="server_a_step", action="search", params={"query": "alpha"})],
        ),
        scope="global",
    )
    store_b.save(
        "shared",
        PipelineConfig(
            steps=[PipelineStep(id="server_b_step", action="search", params={"query": "beta"})],
        ),
        scope="global",
    )

    server_a = MCPServer("unified-server-a")
    server_b = MCPServer("unified-server-b")
    register_unified_search_tools(
        server_a,
        MagicMock(),
        pipeline_runtime=PipelineToolRuntime(base_store=store_a),
    )
    register_unified_search_tools(
        server_b,
        MagicMock(),
        pipeline_runtime=PipelineToolRuntime(base_store=store_b),
    )

    unified_a = server_a._tool_manager._tools["unified_search"].fn
    unified_b = server_b._tool_manager._tools["unified_search"].fn
    result_a, result_b = await asyncio.gather(
        unified_a(pipeline="saved:shared", output_format="json", dry_run=True),
        unified_b(pipeline="saved:shared", output_format="json", dry_run=True),
    )
    payload_a = json.loads(result_a)
    payload_b = json.loads(result_b)

    assert [step["id"] for step in payload_a["steps"]] == ["server_a_step"]
    assert [step["id"] for step in payload_b["steps"]] == ["server_b_step"]


def test_concurrent_schedule_transactions_do_not_lose_entries(tmp_path: Path) -> None:
    store = PipelineStore(global_data_dir=tmp_path)

    def save(index: int) -> None:
        store.save_schedule(ScheduleEntry(pipeline_name=f"scheduled_{index}", cron="0 6 * * *"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(save, range(24)))

    persisted = json.loads((tmp_path / "schedules.json").read_text(encoding="utf-8"))
    assert set(persisted) == {f"scheduled_{number}" for number in range(24)}


def test_run_ids_remain_unique_when_timestamp_is_identical(tmp_path: Path) -> None:
    store = PipelineStore(global_data_dir=tmp_path)
    started = datetime(2026, 8, 9, 1, 2, 3, 456789, tzinfo=timezone.utc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        run_ids = list(pool.map(lambda _index: store.create_run_id("same", started), range(100)))

    assert len(run_ids) == len(set(run_ids)) == 100
    assert all(run_id.startswith("20260809_010203_456789_") for run_id in run_ids)


def test_concurrent_run_transactions_keep_files_and_index_count_equal(tmp_path: Path) -> None:
    store = PipelineStore(global_data_dir=tmp_path)
    store.save(
        "tracked",
        PipelineConfig(steps=[PipelineStep(id="search", action="search")]),
        scope="global",
    )

    def save(index: int) -> None:
        store.save_run("tracked", PipelineRun(run_id=f"run_{index:03d}", pipeline_name="tracked"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(save, range(40)))

    _config, metadata = store.load("tracked")
    assert store.count_history("tracked") == metadata.run_count == 40


@pytest.mark.parametrize(
    "operation",
    [
        lambda store: store.save(
            "../victim",
            PipelineConfig(steps=[PipelineStep(id="search", action="search")]),
            scope="global",
        ),
        lambda store: store.load("../victim"),
        lambda store: store.delete("../victim"),
        lambda store: store.get_history("../victim"),
        lambda store: store.exists("../victim"),
        lambda store: store.save_schedule(ScheduleEntry(pipeline_name="../victim", cron="0 6 * * *")),
        lambda store: store.save_report("../victim", "run_1", "secret"),
        lambda store: store.create_run_id("../victim"),
    ],
)
def test_all_name_based_paths_reject_directory_traversal(tmp_path: Path, operation) -> None:
    store = PipelineStore(global_data_dir=tmp_path / "tenant")
    victim = tmp_path / "victim.yaml"
    victim.write_text(_CONFIG, encoding="utf-8")

    with pytest.raises(ValueError, match="Pipeline name"):
        operation(store)

    assert victim.read_text(encoding="utf-8") == _CONFIG


def test_tenant_rebased_store_drops_shared_workspace_scope(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    base = PipelineStore(global_data_dir=tmp_path / "base", workspace_dir=workspace)
    tenant = base.rebased(tmp_path / "tenant")

    assert tenant._resolve_scope("auto").value == "global"
    with pytest.raises(ValueError, match="workspace directory"):
        tenant._resolve_scope("workspace")


def test_corrupt_index_is_rebuilt_from_complete_pipeline_files(tmp_path: Path) -> None:
    store = PipelineStore(global_data_dir=tmp_path)
    store.save(
        "recoverable",
        PipelineConfig(steps=[PipelineStep(id="search", action="search")]),
        scope="global",
    )
    index_path = tmp_path / "pipelines" / "_index.json"
    index_path.write_text('{"recoverable":', encoding="utf-8")

    recovered = store.list_pipelines(scope="global")

    assert [meta.name for meta in recovered] == ["recoverable"]
    assert set(json.loads(index_path.read_text(encoding="utf-8"))) == {"recoverable"}
