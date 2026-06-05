"""Tests for research artifact envelope and completeness audit."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING

from pubmed_search.application.session.artifact_envelope import (
    ARTIFACT_SCHEMA_VERSION,
    audit_unified_search_artifact,
    build_unified_search_artifact_envelope,
)
from pubmed_search.application.session.manager import SessionManager
from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.presentation.mcp_server.tools.artifact_memory import artifact_locator, artifact_markdown_note

if TYPE_CHECKING:
    from pathlib import Path


def _article(title: str, pmid: str = "", doi: str = "") -> UnifiedArticle:
    return UnifiedArticle(title=title, primary_source="pubmed", pmid=pmid, doi=doi, journal="J Test", year=2026)


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        query="remimazolam ICU sedation",
        limit=10,
        sources="pubmed,openalex",
        ranking="balanced",
        output_format="json",
        min_year=2020,
        max_year=2026,
        include_preprints=False,
        counts_first=False,
        compact_output=False,
        show_analysis=True,
        include_similarity_scores=True,
        include_next_tools=True,
        include_section_provenance=True,
        peer_reviewed_only=True,
        auto_relax=True,
        deep_search=True,
        advanced_filters={"language": "english"},
    )


def _plan(request: SimpleNamespace) -> SimpleNamespace:
    strategy = SimpleNamespace(
        name="mesh_expanded",
        query='"Remimazolam"[MeSH Terms] AND ICU',
        source="pubmed",
        priority=5,
        expected_precision=0.8,
        expected_recall=0.7,
    )
    enhanced_query = SimpleNamespace(
        to_dict=lambda: {
            "original_query": request.query,
            "strategies": [{"name": strategy.name, "query": strategy.query, "source": strategy.source}],
        },
        strategies=[strategy],
    )
    analysis = SimpleNamespace(
        original_query=request.query,
        normalized_query="remimazolam icu sedation",
        complexity=SimpleNamespace(value="complex"),
        intent=SimpleNamespace(value="systematic"),
        to_dict=lambda: {"query": request.query, "intent": "systematic"},
    )
    return SimpleNamespace(
        request=request,
        query='"Remimazolam"[MeSH Terms] ICU sedation',
        analysis=analysis,
        icd_matches=[],
        enhanced_query=enhanced_query,
        matched_entity_names=["Remimazolam"],
        user_sources=["pubmed", "openalex"],
        dispatch_sources=["pubmed", "openalex"],
        effective_min_year=2020,
        effective_max_year=2026,
    )


def _execution() -> SimpleNamespace:
    deep_strategy = SimpleNamespace(
        strategy_name="mesh_expanded",
        query='"Remimazolam"[MeSH Terms] AND ICU',
        source="pubmed",
        articles_count=1,
        execution_time_ms=12.5,
    )
    deep_metrics = SimpleNamespace(
        strategies_generated=2,
        strategies_executed=1,
        strategies_with_results=1,
        strategy_results=[deep_strategy],
        depth_score=70.0,
    )
    stats = SimpleNamespace(
        total_input=3,
        unique_articles=2,
        duplicates_removed=1,
        by_source={"pubmed": 1, "openalex": 1},
        to_dict=lambda: {
            "total_input": 3,
            "unique_articles": 2,
            "duplicates_removed": 1,
            "by_source": {"pubmed": 1, "openalex": 1},
        },
    )
    return SimpleNamespace(
        ranked=[_article("A", pmid="111"), _article("B")],
        stats=stats,
        source_api_counts={"pubmed": (1, 25), "openalex": (0, None)},
        source_errors=[
            {
                "source": "openalex",
                "status": "error",
                "message": "temporary upstream failure",
                "retryable": True,
            }
        ],
        deep_search_metrics=deep_metrics,
        relaxation_result=None,
        pubmed_total_count=25,
    )


def test_unified_search_envelope_writes_complete_artifact_files():
    request = _request()
    plan = _plan(request)
    execution = _execution()

    envelope = build_unified_search_artifact_envelope(
        request=request,
        plan=plan,
        execution=execution,
        structured_payload='{"tool":"unified_search","articles":[]}',
        markdown_response="## Unified Search Results",
        primary_format="json",
    )

    assert envelope.primary_file == "results.json"
    assert set(envelope.files) >= {"results.json", "query_strategy.json", "audit.json", "query.md", "response.md"}
    assert envelope.summary["schema_version"] == ARTIFACT_SCHEMA_VERSION
    assert envelope.summary["token_offload"] is True
    assert envelope.summary["read_order"][:3] == ["audit.json", "query_strategy.json", "results.json"]

    strategy = envelope.files["query_strategy.json"]
    assert strategy["original_query"] == "remimazolam ICU sedation"
    assert strategy["executed_query"] == '"Remimazolam"[MeSH Terms] ICU sedation'
    assert strategy["dispatch_sources"] == ["pubmed", "openalex"]
    assert strategy["deep_search"]["strategies_generated"] == 2
    assert strategy["deep_search"]["strategy_results"][0]["query"] == '"Remimazolam"[MeSH Terms] AND ICU'

    audit = envelope.files["audit.json"]
    assert audit["schema_version"] == ARTIFACT_SCHEMA_VERSION
    assert audit["mode"] == "source-counts"
    assert audit["status"] == "warn"
    assert any(check["check"] == "source_errors" and check["severity"] == "warn" for check in audit["checks"])
    assert any(check["check"] == "missing_identifiers" and check["severity"] == "warn" for check in audit["checks"])
    assert envelope.summary["audit"]["status"] == "warn"
    assert envelope.summary["audit"]["warnings"] >= 1


def test_limited_search_does_not_warn_when_unique_articles_exceed_returned_limit():
    request = _request()
    request.deep_search = False
    request.limit = 10
    plan = _plan(request)
    ranked = [_article(f"Article {index}", pmid=str(index), doi=f"10.1/{index}") for index in range(10)]
    stats = SimpleNamespace(
        total_input=25,
        unique_articles=25,
        duplicates_removed=0,
    )
    execution = SimpleNamespace(
        ranked=ranked,
        stats=stats,
        source_api_counts={"pubmed": (10, 25)},
        source_errors=[],
        deep_search_metrics=None,
        relaxation_result=None,
    )

    audit = audit_unified_search_artifact(request=request, plan=plan, execution=execution)

    assert audit["status"] == "pass"
    assert any(
        check["check"] == "result_count_consistency" and check["severity"] == "pass" for check in audit["checks"]
    )
    assert any(check["check"] == "result_limit_applied" and check["severity"] == "info" for check in audit["checks"])


def test_artifact_locator_exposes_remote_safe_read_hints(tmp_path: Path):
    request = _request()
    envelope = build_unified_search_artifact_envelope(
        request=request,
        plan=_plan(request),
        execution=_execution(),
        structured_payload='{"tool":"unified_search","articles":[]}',
        primary_format="json",
    )
    manager = SessionManager(data_dir=str(tmp_path))
    manifest = manager.save_artifact(
        tool="unified_search",
        kind="search_results",
        files=envelope.files,
        primary_file=envelope.primary_file,
        summary=envelope.summary,
        metadata=envelope.metadata,
    )

    locator = artifact_locator(manifest)

    assert locator is not None
    assert locator["schema_version"] == ARTIFACT_SCHEMA_VERSION
    assert locator["audit_status"] == "warn"
    assert locator["read_order"][:3] == ["audit.json", "query_strategy.json", "results.json"]
    assert locator["read_files"]["audit.json"].startswith('read_session(action="artifact"')
    assert "artifact_uri" in locator["remote_retrieval"]
    assert "artifact_uri=" in locator["read_files_by_uri"]["audit.json"]
    assert "artifact_uri=" in locator["remote_retrieval"]["read_via"]
    assert "artifact_uri=" in locator["read_via_uri"]
    assert locator["remote_retrieval"]["supports_paging"] is True

    note = artifact_markdown_note(locator)
    assert "Start with URI" in note
    assert "artifact_uri=" in note

    page = manager.read_artifact(manifest["artifact_id"], file_name="audit.json", max_chars=120)
    assert page["success"] is True
    assert page["file"]["name"] == "audit.json"
    assert page["available_files"]
    assert page["retrieval"]["supports_paging"] is True
    assert page["content"].startswith("{")
    assert page["truncated"] is True

    full_page = manager.read_artifact(manifest["artifact_id"], file_name="audit.json")
    assert json.loads(full_page["content"])["status"] == "warn"
