"""The PubMed EFetch parser and the UnifiedArticle mapper agree on field names.

Regression: ``LiteratureSearcher`` emits ``publication_types`` and ``pmc_id``
while ``article_from_pubmed`` read ``article_type`` and ``pmc``, so every PubMed
record reaching ``unified_search`` or a pipeline had ``article_type="unknown"``,
``pmc=None`` and no open-access flag (all 30 records of the 2026-11-25 pilot
search). These tests run synthetic EFetch XML through Biopython and the real
parser, so the contract is checked end to end without network access.
"""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from Bio import Entrez

from pubmed_search.application.fulltext.cache import FulltextCache
from pubmed_search.application.pipeline.run_recorder import _article_record
from pubmed_search.application.search.query_analyzer import AnalyzedQuery, QueryComplexity, QueryIntent
from pubmed_search.application.search.result_aggregator import RankingConfig, ResultAggregator
from pubmed_search.application.search.semantic_enhancer import SemanticEnhancer
from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.domain.entities.article import ArticleType, OpenAccessStatus
from pubmed_search.domain.services.article_mapper import article_from_pubmed
from pubmed_search.infrastructure.ncbi import LiteratureSearcher
from pubmed_search.presentation.mcp_server.tools.unified_runner import run_unified_search

# PMID: (publication types, PMCID or None)
RECORDS: dict[str, tuple[tuple[str, ...], str | None]] = {
    "30721296": (
        ("Journal Article", "Randomized Controlled Trial", "Research Support, N.I.H., Extramural"),
        "PMC6383688",
    ),
    "31000002": (("Journal Article", "Meta-Analysis", "Systematic Review"), None),
    "31000003": (("Journal Article", "Clinical Trial Protocol", "Randomized Controlled Trial"), "PMC7000003"),
    "31000004": (("Published Erratum",), None),
    "31000005": (("Preprint",), None),
    "31000006": (("Journal Article", "Clinical Trial, Phase III"), None),
    "31000007": (("Journal Article", "Observational Study"), "PMC7000007"),
}
EXPECTED_TYPES = {
    "30721296": ArticleType.RANDOMIZED_CONTROLLED_TRIAL,
    "31000002": ArticleType.META_ANALYSIS,
    # A protocol reports no trial results even when also indexed as an RCT.
    "31000003": ArticleType.JOURNAL_ARTICLE,
    # A notice is not the design it corrects (OpenAlex maps "erratum" to OTHER too).
    "31000004": ArticleType.OTHER,
    "31000005": ArticleType.PREPRINT,
    "31000006": ArticleType.CLINICAL_TRIAL,
    "31000007": ArticleType.JOURNAL_ARTICLE,
}


def _article_xml(pmid: str, types: tuple[str, ...], pmcid: str | None) -> str:
    type_xml = "".join(f"<PublicationType>{value}</PublicationType>" for value in types)
    pmc_xml = f'<ArticleId IdType="pmc">{pmcid}</ArticleId>' if pmcid else ""
    return (
        '<PubmedArticle><MedlineCitation Status="MEDLINE" Owner="NLM">'
        f'<PMID Version="1">{pmid}</PMID><Article PubModel="Print">'
        '<Journal><JournalIssue CitedMedium="Print"><PubDate><Year>2019</Year></PubDate></JournalIssue>'
        "<Title>Anesthesiology journal</Title></Journal>"
        f"<ArticleTitle>Processed EEG guidance and postoperative delirium record {pmid}</ArticleTitle>"
        "<Abstract><AbstractText>Processed EEG guidance during anesthesia and postoperative delirium.</AbstractText>"
        '</Abstract><AuthorList><Author ValidYN="Y"><LastName>Wildes</LastName><ForeName>Troy</ForeName>'
        "<Initials>TS</Initials></Author></AuthorList><Language>eng</Language>"
        f"<PublicationTypeList>{type_xml}</PublicationTypeList></Article></MedlineCitation>"
        f'<PubmedData><ArticleIdList><ArticleId IdType="pubmed">{pmid}</ArticleId>'
        f'<ArticleId IdType="doi">10.1000/{pmid}</ArticleId>{pmc_xml}</ArticleIdList></PubmedData></PubmedArticle>'
    )


def _efetch_items() -> list[dict[str, Any]]:
    """Return exactly what ``LiteratureSearcher`` hands to the mapper for EFetch XML."""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE PubmedArticleSet SYSTEM "https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_190101.dtd">\n'
        "<PubmedArticleSet>"
        + "".join(_article_xml(pmid, types, pmcid) for pmid, (types, pmcid) in RECORDS.items())
        + "</PubmedArticleSet>"
    ).encode()
    papers = Entrez.read(io.BytesIO(xml))
    return LiteratureSearcher(email="test@example.invalid")._parse_fetch_results(papers, expected_pmids=list(RECORDS))


def test_parser_emits_publication_types_and_pmc_id_not_the_legacy_keys() -> None:
    item = next(row for row in _efetch_items() if row["pmid"] == "30721296")

    assert item["publication_types"][:2] == ["Journal Article", "Randomized Controlled Trial"]
    assert item["pmc_id"] == "PMC6383688"
    assert "article_type" not in item
    assert "pmc" not in item


@pytest.mark.parametrize("pmid", list(RECORDS))
def test_mapper_reads_the_parser_publication_types(pmid: str) -> None:
    item = next(row for row in _efetch_items() if row["pmid"] == pmid)

    article = article_from_pubmed(item)

    assert article.article_type == EXPECTED_TYPES[pmid]
    assert article.publication_types == list(RECORDS[pmid][0])


def test_mapper_reads_the_parser_pmcid_and_applies_the_existing_pmc_open_access_convention() -> None:
    by_pmid = {row["pmid"]: article_from_pubmed(row) for row in _efetch_items()}

    with_pmc = by_pmid["30721296"]
    assert with_pmc.pmc == "PMC6383688"
    assert with_pmc.is_open_access is True
    assert with_pmc.oa_status == OpenAccessStatus.GREEN
    assert with_pmc.best_oa_link is not None
    assert with_pmc.best_oa_link.url == "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6383688/"
    assert with_pmc.best_oa_link.is_pdf is False

    without_pmc = by_pmid["31000002"]
    assert without_pmc.pmc is None
    assert without_pmc.has_open_access is False


@pytest.mark.parametrize("raw", ["PMC6383688", "6383688", "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6383688/"])
def test_mapper_normalizes_pmcid_forms(raw: str) -> None:
    article = article_from_pubmed({"pmid": "30721296", "title": "ENGAGES", "pmc_id": raw})

    assert article.pmc == "PMC6383688"


def test_empty_pmc_id_is_not_an_identifier() -> None:
    article = article_from_pubmed({"pmid": "30721296", "title": "ENGAGES", "pmc_id": "", "publication_types": []})

    assert (article.pmc, article.has_open_access, article.article_type) == (None, False, ArticleType.UNKNOWN)


def test_quality_score_uses_the_indexed_design() -> None:
    articles = {row["pmid"]: article_from_pubmed(row) for row in _efetch_items()}
    aggregator = ResultAggregator()
    config = RankingConfig()
    quality = {pmid: aggregator._calculate_quality(article, config) for pmid, article in articles.items()}

    assert quality["31000002"] > quality["30721296"] > quality["31000007"]
    # The protocol indexed as an RCT gets no trial weight.
    assert quality["31000003"] < quality["30721296"]


def test_pipeline_run_records_keep_pubmed_vocabulary_and_pmcid() -> None:
    article = article_from_pubmed(next(row for row in _efetch_items() if row["pmid"] == "30721296"))

    record = _article_record(article)

    assert record["publication_types"] == list(RECORDS["30721296"][0])
    assert record["pmc_id"] == "PMC6383688"


async def test_prefetch_of_pubmed_results_stays_bounded_to_three_xml_jobs() -> None:
    articles = [article_from_pubmed(row) for row in _efetch_items() if row["pmc_id"]]
    articles += [
        article_from_pubmed({"pmid": f"4000000{n}", "title": f"T{n}", "pmc_id": f"PMC800000{n}"}) for n in range(3)
    ]
    cache = FulltextCache()
    fetch = AsyncMock(return_value="<article/>")
    try:
        snapshot = cache.prefetch(articles, tenant="t", fetch=fetch)
    finally:
        await cache.aclose()

    assert snapshot["max_articles"] == 3
    assert [row["source"] for row in snapshot["articles"]] == [
        {"kind": "pmcid", "value": "PMC6383688"},
        {"kind": "pmcid", "value": "PMC7000003"},
        {"kind": "pmcid", "value": "PMC7000007"},
    ]
    assert all(call.args[0].startswith("PMC") for call in fetch.await_args_list)


class _NullResolver:
    async def resolve_entity(self, _text: str) -> None:
        return None


class _ComparisonAnalyzer:
    def analyze(self, query: str) -> AnalyzedQuery:
        return AnalyzedQuery(
            original_query=query,
            normalized_query=query,
            complexity=QueryComplexity.MODERATE,
            intent=QueryIntent.COMPARISON,
        )


async def _search(output_format: str, options: str = "shallow,no_oa,no_relax,include_detected_preprints") -> str:
    searcher = AsyncMock()
    searcher.search_page.return_value = SourceSearchPage(
        source="pubmed", items=_efetch_items(), total=len(RECORDS), query="processed EEG delirium"
    )
    with patch(
        "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
        new_callable=AsyncMock,
        return_value=[],
    ):
        return await run_unified_search(
            searcher=searcher,
            query="processed EEG delirium",
            sources="pubmed",
            limit=10,
            output_format=output_format,  # type: ignore[arg-type]
            options=options,
            analyzer_factory=_ComparisonAnalyzer,
            enhancer_factory=lambda: SemanticEnhancer(entity_resolver=_NullResolver()),
        )


async def test_unified_search_summary_records_carry_type_pmcid_and_open_access() -> None:
    payload = json.loads(await _search("json"))
    records = {record["pmid"]: record for record in payload["articles"]}

    engages = records["30721296"]
    assert engages["article_type"] == "randomized-controlled-trial"
    assert engages["pmc"] == "PMC6383688"
    assert (engages["open_access"], engages["oa_status"]) == (True, "green")
    assert engages["publication_types"] == list(RECORDS["30721296"][0])
    assert records["31000002"]["article_type"] == "meta-analysis"
    assert records["31000002"]["open_access"] is False
    assert sum(record["article_type"] != "unknown" for record in records.values()) == len(RECORDS)
    assert sum(bool(record["pmc"]) for record in records.values()) == 3


async def test_unified_search_markdown_shows_study_type_and_pmc_open_access() -> None:
    markdown = await _search("markdown")

    assert "**Type**: 🟢 RCT" in markdown
    assert "**Type**: 🟢 Meta-Analysis" in markdown
    assert "**OA**: ✅ [green](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6383688/)" in markdown


async def test_pubmed_indexed_preprint_is_excluded_by_default_like_other_detected_preprints() -> None:
    payload = json.loads(await _search("json", options="shallow,no_oa,no_relax"))

    assert "31000005" not in {record["pmid"] for record in payload["articles"]}
    assert payload["result_filter_counts"]["excluded_detected_preprints"] == 1
