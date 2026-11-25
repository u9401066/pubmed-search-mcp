"""Agent-sized structured unified_search records (summary by default, full on opt-in).

Regression for the 2026-11-25 Claude Code harness pilot (finding F6): for 30
PubMed records ``output_format="json"`` returned 165-254 KB (Markdown: 7-18 KB).
Per record, full abstracts were 53-71 % of the bytes (one conference-proceedings
record carried an 81,020-character abstract), followed by author objects, MeSH
terms, identifier maps, link maps and rank internals; the embedded artifact
summary repeated ``source_metadata``. The fixtures below mirror those records.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import toons

from pubmed_search.application.search.query_analyzer import AnalyzedQuery, QueryComplexity, QueryIntent
from pubmed_search.application.search.result_aggregator import AggregationStats
from pubmed_search.application.search.semantic_enhancer import SemanticEnhancer
from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.application.unified.request import normalize_unified_search_request
from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.domain.services.article_mapper import article_from_pubmed
from pubmed_search.presentation.mcp_server.tools.unified_formatting import ABSTRACT_SNIPPET_CHARS, _format_as_json
from pubmed_search.presentation.mcp_server.tools.unified_runner import run_unified_search

QUERY = (
    "(bispectral index OR processed EEG OR patient state index OR spectral entropy) AND "
    "(post-anesthesia care unit OR PACU OR emergence from general anesthesia)"
)
TYPICAL_ABSTRACT = (
    "Extubation in the post-anesthesia care unit (PACU) is a high-risk transition, frequently accompanied by "
    "hemodynamic fluctuations and respiratory events. Current practice relies mainly on subjective assessments "
    "and the bispectral index (BIS), which reflects cortical activity but not nociceptive responses. "
) * 8  # ~2,000 characters, the median PubMed abstract in the pilot payloads
PROCEEDINGS_ABSTRACT = "P001 Abstract of a symposium poster on sedation monitoring. " * 1_400  # ~81 KB
SUMMARY_KEYS = {
    "rank",
    "pmid",
    "doi",
    "pmc",
    "title",
    "year",
    "journal",
    "first_author",
    "author_count",
    "publication_types",
    "article_type",
    "abstract_snippet",
    "abstract_truncated",
    "source",
    "sources",
    "open_access",
    "oa_status",
    "pdf_available",
}
FULL_ONLY_KEYS = {"authors", "abstract", "mesh_terms", "keywords", "identifiers", "urls", "rank_percentile_details"}


def _pubmed_item(index: int, *, abstract: str = TYPICAL_ABSTRACT, authors: int = 9) -> dict[str, Any]:
    return {
        "pmid": str(41926003 + index),
        "title": (
            "Nociception index-monitored extubation is associated with improved hemodynamic stability and "
            f"recovery efficiency in the post-anesthesia care unit: a single-center randomized controlled trial {index}."
        ),
        "authors": [f"Investigator{n} Surname{n}" for n in range(authors)],
        "abstract": abstract,
        "journal": "Journal of clinical monitoring and computing",
        "year": "2026",
        "volume": "40",
        "issue": "4",
        "pages": "833-844",
        "doi": f"10.1007/s10877-026-{index:05d}-0",
        "keywords": ["Extubation", "Hemodynamic stability", "Nociception index (NOX)", "PACU"],
        "mesh_terms": ["Humans", "Adult", "Anesthesia Recovery Period", "Electroencephalography", "Monitoring"],
        "publication_types": ["Journal Article", "Randomized Controlled Trial"],
        "language": "eng",
    }


def _pilot_items() -> list[dict[str, Any]]:
    items = [_pubmed_item(index) for index in range(29)]
    items.append(_pubmed_item(29, abstract=PROCEEDINGS_ABSTRACT, authors=0))
    return items


class _ComparisonAnalyzer:
    def analyze(self, query: str) -> AnalyzedQuery:
        return AnalyzedQuery(
            original_query=query,
            normalized_query=query,
            complexity=QueryComplexity.MODERATE,
            intent=QueryIntent.COMPARISON,
        )


class _NullResolver:
    async def resolve_entity(self, _text: str) -> None:
        return None


async def _search(*, output_format: str = "json", options: str | None = None) -> str:
    items = _pilot_items()
    searcher = AsyncMock()
    searcher.search_page.return_value = SourceSearchPage(source="pubmed", items=items, total=106, query=QUERY)
    with patch(
        "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
        new_callable=AsyncMock,
        return_value=[],
    ):
        return await run_unified_search(
            searcher=searcher,
            query=QUERY,
            sources="pubmed",
            limit=30,
            output_format=output_format,  # type: ignore[arg-type]
            options=options,
            analyzer_factory=_ComparisonAnalyzer,
            enhancer_factory=lambda: SemanticEnhancer(entity_resolver=_NullResolver()),
        )


def _record_size(record: dict[str, Any]) -> int:
    return len(json.dumps(record, ensure_ascii=False, indent=2))


async def test_default_json_records_are_agent_sized_summaries() -> None:
    raw = await _search()
    payload = json.loads(raw)
    articles = payload["articles"]

    assert len(articles) == 30
    assert payload["record_detail"]["level"] == "summary"
    assert 'options="full_records"' in payload["record_detail"]["full_records"]
    for record in articles:
        assert SUMMARY_KEYS <= set(record)
        assert not FULL_ONLY_KEYS & set(record)
        assert _record_size(record) <= 1_500
    sizes = sorted(_record_size(record) for record in articles)
    # Populated article_type/pmc/OA fields included (the pilot payloads had them blank).
    assert sizes[len(sizes) // 2] <= 1_350

    lead = next(record for record in articles if record["pmid"] == "41926003")
    assert lead["first_author"] == "Investigator0 Surname0"
    assert lead["author_count"] == 9
    assert lead["publication_types"] == ["Journal Article", "Randomized Controlled Trial"]
    assert lead["abstract_truncated"] is True
    assert len(lead["abstract_snippet"]) <= ABSTRACT_SNIPPET_CHARS + 1
    assert TYPICAL_ABSTRACT.startswith(lead["abstract_snippet"].rstrip("…"))
    assert (lead["source"], lead["sources"]) == ("pubmed", ["pubmed"])
    assert lead["retrieval"] == {"tier": "exact", "broadened": False, "strategy": "original"}
    assert [record["rank"] for record in articles] == list(range(1, 31))

    proceedings = next(record for record in articles if record["pmid"] == "41926032")
    assert (proceedings["first_author"], proceedings["author_count"]) == (None, 0)
    assert _record_size(proceedings) <= 1_500

    # 30 records: the pilot measured 165-254 KB for the same shape.
    assert len(raw) < 60_000
    for block in ("statistics", "source_counts", "search_status", "broadening", "next_tools", "next_commands"):
        assert block in payload


async def test_full_records_option_restores_complete_records() -> None:
    payload = json.loads(await _search(options="full_records"))

    assert "record_detail" not in payload
    lead = next(record for record in payload["articles"] if record["identifiers"]["pmid"] == "41926003")
    assert lead["abstract"] == TYPICAL_ABSTRACT
    assert len(lead["authors"]) == 9
    assert lead["mesh_terms"][0] == "Humans"
    proceedings = next(record for record in payload["articles"] if record["identifiers"]["pmid"] == "41926032")
    assert proceedings["abstract"] == PROCEEDINGS_ABSTRACT


async def test_compact_option_keeps_its_minimal_preview() -> None:
    payload = json.loads(await _search(options="compact"))

    record = payload["articles"][0]
    assert "abstract_snippet" not in record
    assert "authors" not in record
    assert {"title", "pmid", "doi", "pdf_url"} <= set(record)


async def test_compact_and_full_records_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="'compact' and 'full_records' are mutually exclusive"):
        normalize_unified_search_request(query=QUERY, output_format="json", options="compact,full_records")

    payload = json.loads(await _search(options="compact,full_records"))
    assert payload["success"] is False
    assert "mutually exclusive" in payload["error"]


async def test_default_toon_records_are_summaries_too() -> None:
    payload = toons.loads(await _search(output_format="toon"))

    assert payload["record_detail"]["level"] == "summary"
    assert "abstract_snippet" in payload["articles"][0]
    assert "authors" not in payload["articles"][0]


def test_formatter_default_and_artifact_payload_stay_full() -> None:
    """Artifact results.json is rendered with the formatter default: complete records."""
    article = article_from_pubmed(_pubmed_item(0))
    analysis = _ComparisonAnalyzer().analyze(QUERY)
    stats = AggregationStats(total_input=1, unique_articles=1)
    manifest = {
        "artifact_id": "a1",
        "artifact_uri": "artifact://s1/a1",
        "primary_file": "results.json",
        "summary": {"source_metadata": {"pubmed": {"warnings": []}}},
    }

    full = json.loads(_format_as_json([article], analysis, stats, artifact_manifest=manifest))
    summary = json.loads(
        _format_as_json([article], analysis, stats, artifact_manifest=manifest, record_detail="summary")
    )

    assert full["articles"][0]["abstract"] == TYPICAL_ABSTRACT
    assert full["artifact"]["summary"] == manifest["summary"]
    assert summary["artifact"] == {key: value for key, value in manifest.items() if key != "summary"}
    assert summary["articles"][0]["abstract_truncated"] is True


def test_summary_record_keeps_non_pubmed_identifiers() -> None:
    article = UnifiedArticle(
        title="An OpenAlex-only preprint",
        primary_source="openalex",
        openalex_id="W4400000000",
        abstract="Short abstract.",
    )
    payload = json.loads(
        _format_as_json(
            [article],
            _ComparisonAnalyzer().analyze("preprint"),
            AggregationStats(total_input=1, unique_articles=1),
            record_detail="summary",
        )
    )

    record = payload["articles"][0]
    assert record["openalex_id"] == "W4400000000"
    assert (record["abstract_snippet"], record["abstract_truncated"]) == ("Short abstract.", False)
    assert record["publication_types"] == []
