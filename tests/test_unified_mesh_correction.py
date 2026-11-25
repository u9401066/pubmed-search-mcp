"""unified_search corrects MeSH clauses PubMed cannot resolve, and says so.

The PubMed source runner is a provider-boundary double that answers like the
real adapter: a query containing ``"Post-Anesthesia Care Units"[Mesh]`` comes
back empty with PubMed's live-shaped ``QuotedPhraseNotFound`` diagnostics,
while the corrected query returns records. MeSH evidence comes from the
production ``NCBIMeshEvidenceGateway`` over ``tests.fixtures.mesh_entrez``.
The planner, semantic strategy generation, precision-first broker,
aggregation, formatting and artifact envelope all run for real.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.search.mesh_correction import MeshCorrectionService
from pubmed_search.application.search.query_analyzer import AnalyzedQuery, QueryComplexity, QueryIntent
from pubmed_search.application.search.semantic_enhancer import SemanticEnhancer
from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.domain.value_objects.query_diagnostics import PubMedQueryDiagnostics
from pubmed_search.presentation.mcp_server.tools.tool_session import ToolSessionRuntime, bind_tool_session_runtime
from pubmed_search.presentation.mcp_server.tools.unified_runner import run_unified_search
from pubmed_search.shared.source_contracts import SourceAdapterResult
from tests.fixtures.mesh_entrez import PACU, PACU_QUERY, FakeEntrez, make_service

if TYPE_CHECKING:
    from collections.abc import Iterator

CORRECTED_MARKER = '"Anesthesia Recovery Period"[Mesh]'
BROAD_MARKER = "[Title/Abstract]"
CORRECTED_TOTAL = 518
FLAGGED = PubMedQueryDiagnostics(
    query_translation=PACU_QUERY,
    quoted_phrases_not_found=(PACU,),
    output_messages=("No items found.",),
)


class _NullResolver:
    async def resolve_entity(self, _text: str) -> None:
        return None


class _ModerateAnalyzer:
    def analyze(self, query: str) -> AnalyzedQuery:
        return AnalyzedQuery(
            original_query=query,
            normalized_query=query,
            complexity=QueryComplexity.MODERATE,
            intent=QueryIntent.COMPARISON,
        )


def _enhancer() -> SemanticEnhancer:
    return SemanticEnhancer(entity_resolver=_NullResolver())


def _article(pmid: str) -> UnifiedArticle:
    return UnifiedArticle(
        title=f"Delirium in the recovery period {pmid}",
        primary_source="pubmed",
        pmid=pmid,
        year=2024,
        journal="Journal",
        abstract="post-anesthesia care unit delirium",
    )


class _FakePubMed:
    """PubMed runner double reporting PubMed's diagnostics like the real adapter."""

    def __init__(self, *, corrected_hits: int = 12, corrected_total: int = CORRECTED_TOTAL) -> None:
        self.corrected_hits = corrected_hits
        self.corrected_total = corrected_total
        self.calls: list[str] = []

    async def __call__(
        self, query: str, limit: int, _min_year: int | None, _max_year: int | None, _options: dict[str, Any]
    ) -> SourceAdapterResult[UnifiedArticle]:
        self.calls.append(query)
        diagnostics = PubMedQueryDiagnostics(query_translation=query)
        if PACU in query:
            items: list[UnifiedArticle] = []
            total = 0
            diagnostics = FLAGGED
        elif BROAD_MARKER in query:
            items = [_article(str(9000 + index)) for index in range(limit)]
            total = 9_999
        else:
            items = [_article(str(1000 + index)) for index in range(self.corrected_hits)][:limit]
            total = self.corrected_total
        return SourceAdapterResult(
            source="pubmed",
            operation="search",
            items=items,
            total_count=total,
            status="ok" if items else "empty",
            metadata={
                "total_available": total,
                "physical_query": query,
                "query_executed": True,
                "provider_metadata": {"query_diagnostics": diagnostics.to_dict()},
                "warnings": diagnostics.issue_messages(),
            },
        )


def _empty_searcher() -> Any:
    searcher = MagicMock()
    searcher.search_page = AsyncMock(return_value=SourceSearchPage(source="pubmed", items=[], total=0, query="x"))
    return searcher


@pytest.fixture
def fake_entrez() -> Iterator[FakeEntrez]:
    entrez = FakeEntrez()
    with entrez.installed():
        yield entrez


async def _search(
    pubmed: _FakePubMed,
    *,
    service: MeshCorrectionService | None,
    query: str = PACU_QUERY,
    output_format: str = "json",
    options: str = "no_oa",
    limit: int = 10,
) -> str:
    runners: dict[str, Any] = {"pubmed": pubmed}
    with (
        bind_tool_session_runtime(ToolSessionRuntime(mesh_correction=service)),
        patch(
            "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        return await run_unified_search(
            searcher=_empty_searcher(),
            query=query,
            limit=limit,
            sources=",".join(runners),
            output_format=output_format,  # type: ignore[arg-type]
            options=options,
            analyzer_factory=_ModerateAnalyzer,
            enhancer_factory=_enhancer,
            search_functions=runners,
        )


async def test_deep_search_reruns_the_exact_tier_with_the_corrected_query(fake_entrez: FakeEntrez) -> None:
    pubmed = _FakePubMed()

    payload = json.loads(await _search(pubmed, service=make_service()))

    assert pubmed.calls[0] == PACU_QUERY
    assert CORRECTED_MARKER in pubmed.calls[1] and PACU not in pubmed.calls[1]
    assert not [call for call in pubmed.calls if BROAD_MARKER in call]  # limit filled by the corrected exact tier

    correction = payload["mesh_correction"]
    assert (correction["status"], correction["applied"], correction["mode"]) == ("corrected", True, "automatic")
    assert correction["opt_out"] == 'options="no_mesh_correction"'
    (term,) = correction["corrections"]
    assert term["original"] == PACU
    assert term["reason"] == f"NCBI WarningList.QuotedPhraseNotFound: {PACU}"
    assert (term["tier"], term["replacement_mesh"], term["confidence"]) == (
        "co_occurrence",
        "Anesthesia Recovery Period",
        "low",
    )
    assert term["evidence"]["candidates"][0]["descriptor"] == "Anesthesia Recovery Period"
    assert correction["hit_counts"]["before"] == 0 and correction["hit_counts"]["after"] == CORRECTED_TOTAL
    assert "request filters applied" in correction["hit_counts"]["method"]

    broadening = payload["broadening"]
    assert broadening["mechanisms"] == ["mesh_correction"]
    assert (broadening["applied"], broadening["needed"], broadening["broadened_records"]) == (True, False, 0)
    assert broadening["summary"].startswith(f"PubMed MeSH correction: {PACU} not found in MeSH → text words OR")
    assert "hits 0 → 518" in broadening["summary"]
    phases = {row["strategy"]: row["phase"] for row in broadening["attempts"] if row["executed"]}
    assert phases == {"original": "superseded", "original:mesh_corrected": "exact"}

    assert {article["retrieval"]["strategy"] for article in payload["articles"]} == {"original:mesh_corrected"}
    assert {article["retrieval"]["tier"] for article in payload["articles"]} == {"exact"}
    pubmed_meta = payload["source_metadata"]["pubmed"]
    assert pubmed_meta["mesh_correction"]["applied"] is True
    assert any("Post-Anesthesia Care Units" in warning for warning in pubmed_meta["warnings"])
    assert "mesh_correction" in payload["section_provenance"]
    assert payload["source_counts"][0]["total_available"] == CORRECTED_TOTAL


async def test_precision_first_fill_decides_on_the_corrected_results(fake_entrez: FakeEntrez) -> None:
    pubmed = _FakePubMed(corrected_hits=3, corrected_total=3)

    payload = json.loads(await _search(pubmed, service=make_service()))

    broadening = payload["broadening"]
    assert broadening["mechanisms"] == ["mesh_correction", "deep_strategy_tiers"]
    assert broadening["exact_eligible_unique"] == 3  # the corrected exact tier, not the original 0
    assert broadening["broadened_records"] == 7
    assert "original:mesh_corrected returned 3 of requested 10" in broadening["summary"]
    assert "broadened with" in broadening["summary"]
    tiers = [article["retrieval"]["tier"] for article in payload["articles"]]
    assert tiers[:3] == ["exact"] * 3 and set(tiers[3:]) == {"broad"}
    assert all(PACU not in call for call in pubmed.calls[1:])


async def test_shallow_markdown_discloses_the_correction(fake_entrez: FakeEntrez) -> None:
    markdown = await _search(_FakePubMed(), service=make_service(), output_format="markdown", options="shallow,no_oa")

    assert (
        f"**MeSH correction**: 🔧 PubMed MeSH correction: {PACU} not found in MeSH → text words OR "
        '"Anesthesia Recovery Period" (related heading) (low confidence, co-occurrence evidence); hits 0 → 518'
    ) in markdown.replace("\\", "")
    assert "Corrected PubMed query: `" in markdown
    assert "**Broadening**: ⚠️ PubMed MeSH correction" in markdown.replace("\\", "")


async def test_toon_carries_the_correction(fake_entrez: FakeEntrez) -> None:
    toon = await _search(_FakePubMed(), service=make_service(), output_format="toon", options="shallow,no_oa")

    assert "mesh_correction" in toon and "Anesthesia Recovery Period" in toon


async def test_opt_out_keeps_the_original_query_and_still_shows_pubmed_warnings(fake_entrez: FakeEntrez) -> None:
    pubmed = _FakePubMed()

    payload = json.loads(await _search(pubmed, service=make_service(), options="no_oa,no_mesh_correction"))

    assert "mesh_correction" not in payload
    assert all(PACU in call or BROAD_MARKER in call for call in pubmed.calls)
    assert fake_entrez.calls == []  # no MeSH evidence was gathered
    assert any("Post-Anesthesia Care Units" in warning for warning in payload["source_metadata"]["pubmed"]["warnings"])


async def test_no_relax_does_not_disable_mesh_correction(fake_entrez: FakeEntrez) -> None:
    payload = json.loads(await _search(_FakePubMed(), service=make_service(), options="no_oa,no_relax"))

    assert payload["mesh_correction"]["applied"] is True
    assert payload["broadening"]["enabled"] is False


async def test_valid_mesh_query_is_not_touched(fake_entrez: FakeEntrez) -> None:
    pubmed = _FakePubMed()

    payload = json.loads(await _search(pubmed, service=make_service(), query='"Delirium"[Mesh] AND recovery[tiab]'))

    assert "mesh_correction" not in payload
    assert pubmed.calls[0] == '"Delirium"[Mesh] AND recovery[tiab]'
    assert fake_entrez.calls == []


async def test_evidence_outage_falls_back_to_text_words() -> None:
    gateway = MagicMock()
    gateway.lookup_exact = AsyncMock(side_effect=RuntimeError("down"))
    gateway.sample = AsyncMock(side_effect=RuntimeError("down"))
    pubmed = _FakePubMed()

    markdown = await _search(
        pubmed, service=MeshCorrectionService(gateway), output_format="markdown", options="shallow,no_oa,no_relax"
    )

    assert (
        f"{PACU} not found in MeSH → title/abstract text words (low confidence, no MeSH heading found)"
        in markdown.replace("\\", "")
    )
    assert '"Post-Anesthesia Care Units"[tiab]' in pubmed.calls[1] and "[Mesh]" not in pubmed.calls[1]


async def test_unavailable_correction_surfaces_the_attempt() -> None:
    service = MagicMock()
    service.correct_query = AsyncMock(side_effect=RuntimeError("down"))
    service.unavailable_result = MeshCorrectionService(MagicMock()).unavailable_result
    pubmed = _FakePubMed()

    markdown = await _search(pubmed, service=service, output_format="markdown", options="shallow,no_oa,no_relax")
    payload = json.loads(await _search(pubmed, service=service, options="shallow,no_oa,no_relax"))

    assert "**MeSH correction**: ⚠️ PubMed could not resolve a MeSH clause; no correction was applied" in markdown
    assert payload["mesh_correction"]["status"] == "unavailable"
    assert payload["mesh_correction"]["applied"] is False
    assert "broadening" not in payload
    assert all(PACU in call for call in pubmed.calls)


async def test_artifact_query_strategy_and_audit_record_the_correction(fake_entrez: FakeEntrez) -> None:
    persisted: dict[str, Any] = {}

    async def capture(**kwargs: Any) -> dict[str, Any]:
        persisted.update(kwargs)
        return {"artifact_id": "a1", "artifact_uri": "artifact://a1"}

    runner = "pubmed_search.presentation.mcp_server.tools.unified_runner"
    with (
        patch(f"{runner}.artifact_persistence_enabled", return_value=True),
        patch(f"{runner}.persist_tool_artifact", side_effect=capture),
    ):
        await _search(_FakePubMed(), service=make_service(), options="shallow,no_oa")

    files = persisted["files"]
    strategy = files["query_strategy.json"]
    assert strategy["mesh_correction"]["applied"] is True
    assert strategy["mesh_correction"]["corrections"][0]["replacement_mesh"] == "Anesthesia Recovery Period"
    assert strategy["broadening"]["mechanisms"] == ["mesh_correction"]
    checks = {check["check"]: check for check in files["audit.json"]["checks"]}
    assert checks["mesh_correction"]["severity"] == "info"
    assert checks["search_broadening"]["message"].startswith("The PubMed query was corrected automatically")
    assert "hits 0 → 518" in checks["mesh_correction"]["message"]
    assert persisted["summary"]["mesh_correction"]["corrected_query"].endswith("AND delirium[tiab]")
