"""MCP SDK v2 worker-thread and pipeline persistence regressions."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest
from mcp.server import MCPServer

from pubmed_search.application.pipeline.store import PipelineStore
from pubmed_search.domain.entities.pipeline import PipelineConfig, PipelineRun, PipelineStep, ScheduleEntry
from pubmed_search.presentation.mcp_server.tools.pipeline_tools import (
    register_pipeline_tools,
    set_pipeline_scheduler,
    set_pipeline_store,
)

if TYPE_CHECKING:
    from pathlib import Path

_CONFIG = "steps:\n  - id: search\n    action: search\n    params:\n      query: safety"


@pytest.fixture(autouse=True)
def _reset_pipeline_globals():
    set_pipeline_store(None)
    set_pipeline_scheduler(None)
    yield
    set_pipeline_store(None)
    set_pipeline_scheduler(None)


@pytest.mark.asyncio
async def test_mcp_v2_concurrent_sync_saves_keep_every_index_entry(tmp_path: Path) -> None:
    """Exercise the public SDK call path that offloads sync tools to workers."""
    store = PipelineStore(global_data_dir=tmp_path)
    set_pipeline_store(store)
    server = MCPServer("pipeline-concurrency-test")
    register_pipeline_tools(server)

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

    with pytest.raises(ValueError, match="Unsafe pipeline name"):
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
