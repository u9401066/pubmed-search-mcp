"""Strict ClinicalTrials.gov adjunct provenance regressions for unified_search."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from pubmed_search.application.search.query_analyzer import QueryAnalyzer
from pubmed_search.presentation.mcp_server.tools.unified_runner import run_unified_search
from pubmed_search.shared.source_contracts import SourceAdapterResult


async def _empty_pubmed(*_args: Any, **_kwargs: Any) -> SourceAdapterResult[Any]:
    return SourceAdapterResult.empty(source="pubmed", operation="search")


async def _run(*, output_format: str, options: str) -> str:
    return await run_unified_search(
        searcher=AsyncMock(),
        query="remimazolam sedation",
        sources="pubmed",
        output_format=output_format,
        options=options,
        analyzer_factory=QueryAnalyzer,
        search_functions={"pubmed": _empty_pubmed},
    )


def _trial() -> dict[str, Any]:
    return {
        "nct_id": "NCT00000001",
        "title": "Remimazolam sedation trial",
        "status": "RECRUITING",
        "phase": "PHASE2",
        "conditions": ["Sedation"],
        "interventions": [{"type": "DRUG", "name": "Remimazolam"}],
        "enrollment": 40,
    }


@pytest.mark.asyncio
async def test_unrequested_and_confirmed_empty_adjunct_are_distinct_in_markdown() -> None:
    trials = AsyncMock(return_value=[])
    with patch("pubmed_search.infrastructure.sources.clinical_trials.search_related_trials", trials):
        unrequested = await _run(
            output_format="markdown",
            options="shallow,no_relax,no_analysis,no_scores",
        )
        requested_empty = await _run(
            output_format="markdown",
            options="clinical_trials,shallow,no_relax,no_analysis,no_scores",
        )

    assert "ClinicalTrials.gov adjunct" not in unrequested
    assert "**ClinicalTrials.gov adjunct**: complete; 0 related trials" in requested_empty
    trials.assert_awaited_once()


@pytest.mark.asyncio
async def test_requested_structured_adjunct_returns_trials_and_complete_coverage() -> None:
    with patch(
        "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
        new=AsyncMock(return_value=[_trial()]),
    ):
        payload = json.loads(
            await _run(
                output_format="json",
                options="clinical_trials,shallow,no_relax,no_analysis,no_scores",
            )
        )

    adjunct = payload["clinical_trials"]
    assert adjunct["trials"][0]["nct_id"] == "NCT00000001"
    assert adjunct["coverage"]["status"] == "complete"
    assert adjunct["coverage"]["returned"] == 1
    assert adjunct["coverage"]["complete"] is True
    assert adjunct["coverage"]["error"] is None


@pytest.mark.asyncio
async def test_adjunct_outage_is_partial_and_never_exposes_raw_exception() -> None:
    secret = "token=private https://provider.invalid/?api_key=private /srv/private/key.json"
    with patch(
        "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
        new=AsyncMock(side_effect=RuntimeError(secret)),
    ):
        rendered = await _run(
            output_format="json",
            options="clinical_trials,shallow,no_relax,no_analysis,no_scores",
        )

    payload = json.loads(rendered)
    coverage = payload["clinical_trials"]["coverage"]
    assert coverage["status"] == "error"
    assert coverage["complete"] is False
    assert coverage["error"]["kind"] == "unexpected"
    assert coverage["error"]["exception_type"] == "RuntimeError"
    assert payload["source_errors"][0]["source"] == "clinical_trials"
    assert payload["search_status"]["state"] == "partial"
    assert secret not in rendered
    assert "provider.invalid" not in rendered
    assert "/srv/private" not in rendered


@pytest.mark.asyncio
async def test_adjunct_timeout_is_visible_in_markdown() -> None:
    async def _slow_trials(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        await asyncio.sleep(30)
        return []

    with (
        patch(
            "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
            side_effect=_slow_trials,
        ),
        patch(
            "pubmed_search.application.unified.execution.CLINICAL_TRIALS_PREFETCH_TIMEOUT_SECONDS",
            0.001,
        ),
    ):
        rendered = await _run(
            output_format="markdown",
            options="clinical_trials,shallow,no_relax,no_analysis,no_scores",
        )

    assert r"**Source warnings**: clinical\_trials timeout" in rendered
    assert "**ClinicalTrials.gov adjunct**: incomplete; request timed out" in rendered


@pytest.mark.asyncio
async def test_invalid_adjunct_shape_is_validation_failure_not_empty() -> None:
    with patch(
        "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
        new=AsyncMock(return_value=[{"title": "missing NCT identity"}]),
    ):
        payload = json.loads(
            await _run(
                output_format="json",
                options="clinical_trials,shallow,no_relax,no_analysis,no_scores",
            )
        )

    coverage = payload["clinical_trials"]["coverage"]
    assert coverage["status"] == "error"
    assert coverage["retrieval_status"] == "error"
    assert coverage["error"]["kind"] == "validation"
    assert payload["source_errors"][0]["kind"] == "validation"


@pytest.mark.asyncio
async def test_adjunct_format_failure_updates_markdown_and_artifact_handoff() -> None:
    secret = "format token=private https://private.invalid/clinical"
    captured: dict[str, Any] = {}

    async def _capture_artifact(**kwargs: Any) -> None:
        execution = kwargs["execution"]
        captured["coverage"] = execution.clinical_trials_coverage.to_dict()
        captured["source_errors"] = list(execution.source_errors)

    with (
        patch(
            "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
            new=AsyncMock(return_value=[_trial()]),
        ),
        patch(
            "pubmed_search.infrastructure.sources.clinical_trials.format_trials_section",
            side_effect=RuntimeError(secret),
        ),
        patch(
            "pubmed_search.presentation.mcp_server.tools.unified_runner.persist_unified_search_artifact",
            side_effect=_capture_artifact,
        ),
    ):
        rendered = await _run(
            output_format="markdown",
            options="clinical_trials,shallow,no_relax,no_analysis,no_scores",
        )

    assert r"**Source warnings**: clinical\_trials error" in rendered
    assert "retrieved but rendering failed" in rendered
    assert captured["coverage"]["status"] == "format_error"
    assert captured["coverage"]["format_status"] == "error"
    assert captured["source_errors"][0]["operation"] == "format_markdown"
    assert secret not in rendered
    assert secret not in json.dumps(captured)
