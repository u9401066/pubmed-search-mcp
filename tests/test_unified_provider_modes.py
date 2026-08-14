"""Provider-native retrieval stays behind the single unified_search facade."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.search.query_analyzer import (
    AnalyzedQuery,
    QueryComplexity,
    QueryIntent,
)
from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.infrastructure.sources.base_client import APIRequestError
from pubmed_search.infrastructure.sources.registry import SourceSelectionError
from pubmed_search.presentation.mcp_server.tools.unified_execution import _search_single_source
from pubmed_search.presentation.mcp_server.tools.unified_helpers import detect_and_expand_icd_codes
from pubmed_search.presentation.mcp_server.tools.unified_planning import build_unified_search_plan
from pubmed_search.presentation.mcp_server.tools.unified_request import normalize_unified_search_request
from pubmed_search.presentation.mcp_server.tools.unified_source_search import (
    _search_europe_pmc_adapter,
    _search_openalex_adapter,
    _search_scopus_adapter,
    _search_semantic_scholar_adapter,
    _search_web_of_science_adapter,
)


async def _ignore_progress(_current: float, _total: float, _message: str) -> None:
    return None


class _StaticAnalyzer:
    def __init__(self, analysis: AnalyzedQuery) -> None:
        self._analysis = analysis

    def analyze(self, _query: str) -> AnalyzedQuery:
        return self._analysis


def test_provider_native_options_are_exclusive_and_disable_expansion() -> None:
    semantic = normalize_unified_search_request(query="treatment resistance", options="native_semantic")
    systematic = normalize_unified_search_request(query="melanoma AND immunotherapy", options="systematic")

    assert semantic.retrieval_mode == "semantic"
    assert semantic.deep_search is False
    assert systematic.retrieval_mode == "systematic"
    assert systematic.deep_search is False
    assert systematic.auto_relax is False
    with pytest.raises(ValueError, match="mutually exclusive"):
        normalize_unified_search_request(
            query="treatment resistance",
            options="native_semantic, systematic",
        )


def test_icd_expansion_does_not_log_sensitive_query_values(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO"):
        expanded, matches = detect_and_expand_icd_codes("I10 private treatment details")

    assert matches
    assert "Essential Hypertension" in expanded
    log_text = caplog.text
    assert "I10" not in log_text
    assert "private treatment details" not in log_text


@pytest.mark.asyncio
async def test_auto_native_semantic_selects_capable_source_only() -> None:
    request = normalize_unified_search_request(query="treatment resistance", options="native_semantic")

    plan = await build_unified_search_plan(request, progress=_ignore_progress)

    assert plan.dispatch_sources == ["openalex"]


@pytest.mark.asyncio
@pytest.mark.parametrize("option", ["native_semantic", "systematic"])
async def test_explicit_provider_mode_never_calls_pubtator_enhancement(option: str) -> None:
    query = "complex melanoma immunotherapy outcome comparison"
    request = normalize_unified_search_request(query=query, options=option)
    analysis = AnalyzedQuery(
        original_query=query,
        normalized_query=query,
        complexity=QueryComplexity.COMPLEX,
        intent=QueryIntent.SYSTEMATIC,
    )
    enhancer = AsyncMock()

    await build_unified_search_plan(
        request,
        progress=_ignore_progress,
        analyzer_factory=lambda: _StaticAnalyzer(analysis),
        enhancer_factory=lambda: enhancer,
    )

    enhancer.enhance.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_unsupported_native_semantic_source_fails_closed() -> None:
    request = normalize_unified_search_request(
        query="treatment resistance",
        sources="pubmed",
        options="native_semantic",
    )

    with pytest.raises(SourceSelectionError, match="not supported by: pubmed"):
        await build_unified_search_plan(request, progress=_ignore_progress)


@pytest.mark.asyncio
async def test_europe_pmc_does_not_claim_unimplemented_systematic_traversal() -> None:
    request = normalize_unified_search_request(
        query="melanoma AND immunotherapy",
        sources="europe_pmc",
        options="systematic",
    )

    with pytest.raises(SourceSelectionError, match="not supported by: europe_pmc"):
        await build_unified_search_plan(request, progress=_ignore_progress)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "env"),
    [
        ("scopus", {"SCOPUS_ENABLED": "true", "SCOPUS_API_KEY": "licensed"}),
        (
            "web_of_science",
            {"WEB_OF_SCIENCE_ENABLED": "true", "WEB_OF_SCIENCE_API_KEY": "licensed"},
        ),
    ],
)
async def test_licensed_single_page_connectors_do_not_claim_systematic_mode(
    source: str,
    env: dict[str, str],
) -> None:
    request = normalize_unified_search_request(
        query="melanoma AND immunotherapy",
        sources=source,
        options="systematic",
    )

    with patch.dict("os.environ", env, clear=False):
        with pytest.raises(SourceSelectionError, match=f"not supported by: {source}"):
            await build_unified_search_plan(request, progress=_ignore_progress)


@pytest.mark.asyncio
async def test_europe_pmc_adapter_preserves_count_and_continuation() -> None:
    client = AsyncMock()
    client.search.return_value = {
        "results": [{"pmid": "123", "title": "Registry-aware evidence", "authors": ["Ada A"]}],
        "hit_count": 1_234,
        "next_cursor": "opaque-next-cursor",
    }

    with patch(
        "pubmed_search.presentation.mcp_server.tools.unified_source_search.get_europe_pmc_client",
        return_value=client,
    ):
        result = await _search_europe_pmc_adapter(
            "melanoma immunotherapy",
            100,
            2020,
            2026,
            {"_retrieval_mode": "auto"},
        )

    assert result.status == "ok"
    assert result.total_count == 1_234
    assert result.metadata["total_available"] == 1_234
    assert result.metadata["continuation_available"] is True
    assert result.metadata["next_cursor"] == "opaque-next-cursor"
    assert result.metadata["provider_mode"] == "keyword"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "adapter", "getter", "physical_query"),
    [
        (
            "scopus",
            _search_scopus_adapter,
            "pubmed_search.presentation.mcp_server.tools.unified_source_search.get_scopus_client",
            "TITLE-ABS-KEY(melanoma immunotherapy) AND PUBYEAR > 2019 AND PUBYEAR < 2027",
        ),
        (
            "web_of_science",
            _search_web_of_science_adapter,
            "pubmed_search.presentation.mcp_server.tools.unified_source_search.get_web_of_science_client",
            "TS=(melanoma immunotherapy) AND PY=(2020-2026)",
        ),
    ],
)
async def test_licensed_keyword_adapters_preserve_compiled_physical_query(
    source: str,
    adapter,
    getter: str,
    physical_query: str,
) -> None:
    client = MagicMock()
    client.compile_query.return_value = physical_query
    client.search = AsyncMock(return_value=[])

    with patch(getter, return_value=client):
        result = await adapter(
            "melanoma immunotherapy",
            25,
            2020,
            2026,
            {"_retrieval_mode": "auto"},
        )

    assert result.source == source
    assert result.status == "empty"
    assert result.metadata["logical_query"] == "melanoma immunotherapy"
    assert result.metadata["physical_query"] == physical_query
    assert result.metadata["provider_mode"] == "keyword"
    assert result.metadata["continuation_available"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "adapter", "getter", "physical_query"),
    [
        (
            "scopus",
            _search_scopus_adapter,
            "pubmed_search.presentation.mcp_server.tools.unified_source_search.get_scopus_client",
            "TITLE-ABS-KEY(private oncology)",
        ),
        (
            "web_of_science",
            _search_web_of_science_adapter,
            "pubmed_search.presentation.mcp_server.tools.unified_source_search.get_web_of_science_client",
            "TS=(private oncology)",
        ),
    ],
)
async def test_failed_licensed_keyword_adapter_preserves_attempted_physical_query(
    source: str,
    adapter,
    getter: str,
    physical_query: str,
) -> None:
    client = MagicMock()
    client.compile_query.return_value = physical_query
    client.search = AsyncMock(side_effect=APIRequestError(source))

    with patch(getter, return_value=client):
        result = await adapter(
            "private oncology",
            25,
            None,
            None,
            {"_retrieval_mode": "auto"},
        )

    assert result.status == "error"
    assert len(result.errors) == 1
    assert "private oncology" not in result.errors[0].message
    assert result.metadata["physical_query"] == physical_query
    assert result.metadata["query_executed"] is True


@pytest.mark.asyncio
async def test_icd_expansion_keeps_pubmed_syntax_out_of_provider_query() -> None:
    request = normalize_unified_search_request(
        query="I10 treatment",
        sources="semantic_scholar",
        options="systematic",
    )
    plan = await build_unified_search_plan(request, progress=_ignore_progress)
    runner = AsyncMock(return_value=([], 0))

    await _search_single_source("semantic_scholar", plan, {"semantic_scholar": runner})

    assert "[MeSH]" in plan.query
    assert plan.provider_neutral_query == '("Essential Hypertension" OR I10) treatment'
    assert runner.await_args.args[0] == plan.provider_neutral_query


@pytest.mark.asyncio
async def test_non_pubmed_filters_are_never_silently_discarded() -> None:
    request = normalize_unified_search_request(
        query="hypertension",
        sources="core",
        filters="lang:english, sex:female",
        options="shallow",
    )
    plan = await build_unified_search_plan(request, progress=_ignore_progress)
    runner = AsyncMock(return_value=([], 0))

    result = await _search_single_source("core", plan, {"core": runner})

    assert result.status == "empty"
    assert result.metadata["warnings"] == ["core does not apply PubMed-only filter(s): language, sex"]


@pytest.mark.asyncio
async def test_openalex_native_semantic_adapter_retains_mode_provenance() -> None:
    client = AsyncMock()
    client.search_semantic_page.return_value = SourceSearchPage(
        source="openalex",
        items=[
            {
                "id": "https://openalex.org/W1",
                "title": "Mechanistic evidence",
                "authorships": [{"author": {"display_name": "Ada Author"}}],
                "ids": {"doi": "https://doi.org/10.1000/example"},
            }
        ],
        total=12,
        query="title.search:mechanistic evidence",
        cost=0.001,
        mode="semantic",
    )

    with patch(
        "pubmed_search.presentation.mcp_server.tools.unified_source_search.get_openalex_client",
        return_value=client,
    ):
        result = await _search_openalex_adapter(
            "mechanistic evidence",
            10,
            None,
            None,
            {"_retrieval_mode": "semantic"},
        )

    assert result.total_count == 12
    assert result.items[0].openalex_id == "W1"
    assert result.metadata["requested_mode"] == "semantic"
    assert result.metadata["provider_mode"] == "semantic"
    assert result.metadata["canonical_query"] == "title.search:mechanistic evidence"
    assert result.metadata["cost_usd"] == 0.001
    client.search_semantic_page.assert_awaited_once()


@pytest.mark.asyncio
async def test_semantic_scholar_systematic_adapter_uses_bounded_bulk() -> None:
    client = AsyncMock()
    client.bulk_search.return_value = SourceSearchPage(
        source="semantic_scholar",
        items=[
            {
                "paperId": "s2-1",
                "title": "Systematic evidence",
                "authors": [{"name": "Grace Author"}],
                "externalIds": {"PubMed": "123"},
            }
        ],
        total=2_000,
        next_token="next",
        query="melanoma AND immunotherapy",
        mode="bulk",
        metadata={"pages_fetched": 1, "bounded": True, "sort": "paperId"},
    )

    with patch(
        "pubmed_search.presentation.mcp_server.tools.unified_source_search.get_semantic_scholar_client",
        return_value=client,
    ):
        result = await _search_semantic_scholar_adapter(
            "melanoma AND immunotherapy",
            100,
            2020,
            2026,
            {"_retrieval_mode": "systematic"},
        )

    assert result.total_count == 2_000
    assert result.items[0].s2_id == "s2-1"
    assert result.metadata["requested_mode"] == "systematic"
    assert result.metadata["provider_mode"] == "bulk"
    assert result.metadata["continuation_available"] is True
    assert result.metadata["logical_query"] == "melanoma AND immunotherapy"
    assert result.metadata["physical_query"] == "melanoma + immunotherapy"
    client.bulk_search.assert_awaited_once_with(
        "melanoma + immunotherapy",
        max_results=100,
        max_pages=1,
        min_year=2020,
        max_year=2026,
        sort="paperId",
    )


@pytest.mark.asyncio
async def test_s2_systematic_field_tags_fail_closed_before_network() -> None:
    client = AsyncMock()
    with patch(
        "pubmed_search.presentation.mcp_server.tools.unified_source_search.get_semantic_scholar_client",
        return_value=client,
    ):
        with pytest.raises(ValueError, match="field tags"):
            await _search_semantic_scholar_adapter(
                'cancer[MeSH Terms] OR "targeted therapy"',
                25,
                None,
                None,
                {"_retrieval_mode": "systematic"},
            )

    client.bulk_search.assert_not_awaited()
