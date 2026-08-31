"""Pipeline-mode structured output, security, and recovery regressions."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.domain.entities.pipeline import PipelineConfig, PipelineStep, StepResult
from pubmed_search.presentation.mcp_server.tools.unified_pipeline import (
    _auto_save_pipeline_report,
    _execute_pipeline_mode_outcome,
)

if TYPE_CHECKING:
    from pubmed_search.application.pipeline.executor import PipelineOutcomeStatus

PIPELINE_MARKDOWN = """
name: offline
steps:
  - id: search
    action: search
    params:
      query: remimazolam
output:
  format: markdown
"""

PIPELINE_JSON = PIPELINE_MARKDOWN.replace("format: markdown", "format: json")


@pytest.mark.asyncio
async def test_toon_request_returns_typed_json_pipeline_outcome() -> None:
    outcome = await _execute_pipeline_mode_outcome(
        PIPELINE_MARKDOWN,
        "toon",
        MagicMock(),
        pipeline_store=None,
        dry_run=True,
    )

    assert outcome.status == "completed"
    assert outcome.response_format == "json"
    payload = json.loads(outcome.response)
    assert payload["type"] == "pipeline_result"
    assert payload["pipeline"]["dry_run"] is True


@pytest.mark.asyncio
async def test_pipeline_json_config_stays_json_when_tool_default_is_markdown() -> None:
    outcome = await _execute_pipeline_mode_outcome(
        PIPELINE_JSON,
        "markdown",
        MagicMock(),
        pipeline_store=None,
        dry_run=True,
    )

    assert outcome.response_format == "json"
    payload = json.loads(outcome.response)
    assert payload["type"] == "pipeline_result"


@pytest.mark.asyncio
async def test_legacy_saved_pipeline_with_credential_is_rejected_without_echoing_secret() -> None:
    sentinel = "SAVED_PIPELINE_TOPSECRET"
    config = PipelineConfig(
        name="legacy-secret",
        steps=[PipelineStep(id="search", action="search", params={"query": f"cancer S2_API_KEY={sentinel}"})],
    )
    fake_store = SimpleNamespace(load=lambda _name: (config, SimpleNamespace(name="legacy-secret")))

    outcome = await _execute_pipeline_mode_outcome(
        "saved:legacy-secret",
        "json",
        MagicMock(),
        pipeline_store=fake_store,  # type: ignore[arg-type]
        dry_run=True,
    )

    assert outcome.status == "failed"
    assert sentinel not in outcome.response
    assert "credential material" in outcome.response


@pytest.mark.asyncio
async def test_saved_pipeline_load_error_never_echoes_legacy_secret() -> None:
    sentinel = "LEGACY_SAVED_TOPSECRET"
    fake_store = SimpleNamespace(
        load=lambda _name: (_ for _ in ()).throw(ValueError(f"Unknown template S2_API_KEY={sentinel}"))
    )

    outcome = await _execute_pipeline_mode_outcome(
        "saved:legacy-invalid",
        "json",
        MagicMock(),
        pipeline_store=fake_store,  # type: ignore[arg-type]
        dry_run=True,
    )

    assert outcome.status == "failed"
    assert sentinel not in outcome.response
    assert "invalid or unsafe" in outcome.response


@pytest.mark.asyncio
async def test_saved_pipeline_name_with_credential_is_rejected_before_lookup() -> None:
    sentinel = "SAVED_NAME_TOPSECRET"
    fake_store = SimpleNamespace(load=MagicMock(side_effect=AssertionError("must not load")))

    outcome = await _execute_pipeline_mode_outcome(
        f"saved:S2_API_KEY={sentinel}",
        "json",
        MagicMock(),
        pipeline_store=fake_store,  # type: ignore[arg-type]
        dry_run=True,
    )

    assert outcome.status == "failed"
    assert sentinel not in outcome.response
    assert "credential material" in outcome.response
    fake_store.load.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "public_message"),
    [
        (ValueError, "Pipeline validation failed"),
        (RuntimeError, "Pipeline execution failed"),
    ],
)
async def test_pipeline_execution_exception_detail_is_not_returned(
    failure: type[Exception],
    public_message: str,
) -> None:
    sentinel = "PRIVATE_PIPELINE_EXCEPTION_DETAIL"

    with patch("pubmed_search.application.pipeline.executor.PipelineExecutor") as executor_cls:
        executor_cls.return_value.execute = AsyncMock(side_effect=failure(sentinel))
        outcome = await _execute_pipeline_mode_outcome(
            PIPELINE_JSON,
            "json",
            MagicMock(),
            pipeline_store=None,
        )

    assert outcome.status == "failed"
    assert public_message in outcome.response
    assert sentinel not in outcome.response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("step_result", "expected_status"),
    [
        (
            StepResult(
                step_id="search",
                action="search",
                error="All selected search sources failed",
                metadata={"source_errors": [{"source": "openalex", "status": "error"}]},
            ),
            "failed",
        ),
        (
            StepResult(
                step_id="search",
                action="search",
                metadata={
                    "source_api_counts": {"pubmed": 0, "openalex": 0},
                    "source_errors": [{"source": "openalex", "status": "error"}],
                },
            ),
            "partial",
        ),
    ],
)
async def test_pipeline_outcome_distinguishes_all_failed_from_empty_plus_failed(
    step_result: StepResult,
    expected_status: str,
) -> None:
    with patch("pubmed_search.application.pipeline.executor.PipelineExecutor") as executor_cls:
        executor_cls.return_value.execute = AsyncMock(return_value=([], {"search": step_result}))
        outcome = await _execute_pipeline_mode_outcome(
            PIPELINE_JSON,
            "json",
            MagicMock(),
            pipeline_store=None,
        )

    assert outcome.status == expected_status


@pytest.mark.parametrize(
    ("status", "expected_run_status"),
    [("completed", "success"), ("partial", "partial"), ("failed", "error")],
)
def test_pipeline_auto_save_persists_terminal_outcome(
    status: PipelineOutcomeStatus,
    expected_run_status: str,
) -> None:
    store = MagicMock()
    store.create_run_id.return_value = "run-status"
    store.save_report.return_value = "report.md"
    store.exists.return_value = True
    config = PipelineConfig(
        name="saved_status",
        steps=[PipelineStep(id="search", action="search", params={"query": "remimazolam"})],
    )

    _auto_save_pipeline_report(
        config,
        [],
        "report",
        pipeline_store=store,
        status=status,
    )

    persisted_run = store.save_run.call_args.args[1]
    assert persisted_run.status == expected_run_status
    if status == "completed":
        assert persisted_run.error_message is None
    else:
        assert persisted_run.error_message
