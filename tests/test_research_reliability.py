"""Offline regressions for evidence identity, retrieval, and cache concurrency."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pubmed_search.application.fulltext.service import FulltextRequest, FulltextService
from pubmed_search.application.reference_verification import ReferenceVerificationService
from pubmed_search.application.search.result_aggregator import ResultAggregator
from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.shared.article_identity import canonical_article_key
from pubmed_search.shared.cache_substrate import CacheStore, MemoryCacheBackend


@pytest.fixture
def citation_article():
    return {
        "pmid": "12345678",
        "doi": "10.1056/example",
        "title": "Example trial results",
        "journal": "N Engl J Med",
        "year": "2024",
        "volume": "390",
        "pages": "12-18",
        "authors": ["Smith John"],
    }


@pytest.fixture
def reference_searcher():
    return MagicMock(
        fetch_details=AsyncMock(return_value=[]),
        search_page=AsyncMock(return_value=_reference_page([])),
        find_by_citation=AsyncMock(return_value=None),
        verify_references=AsyncMock(return_value=[]),
    )


def _reference_page(items):
    return SourceSearchPage(source="pubmed", items=items, total=len(items), query="reference lookup")


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [("doi", "10.1056/wrong"), ("title", "Different trial results"), ("year", "2022")],
)
async def test_reference_conflicts_require_review(reference_searcher, citation_article, field, wrong_value):
    reference_searcher.fetch_details.return_value = [{**citation_article, field: wrong_value}]
    report = await ReferenceVerificationService(reference_searcher).verify_reference_list(
        "Smith J. Example trial results. N Engl J Med. 2024;390:12-18. doi:10.1056/example PMID:12345678"
    )
    row = report["results"][0]
    assert row["status"] == "partial_match"
    assert row["review_required"] is True
    assert field in row["mismatched_fields"]
    assert report["summary"]["verified"] == 0


async def test_doi_resolution_cannot_be_outvoted_by_unrelated_metadata(reference_searcher, citation_article):
    unrelated = {**citation_article, "pmid": "99999999", "doi": "10.1056/wrong"}
    exact_doi = {"pmid": "12345678", "doi": "https://doi.org/10.1056/EXAMPLE"}
    reference_searcher.search_page.return_value = _reference_page([unrelated, exact_doi])
    row = await ReferenceVerificationService(reference_searcher).verify_reference(
        "Smith J. Example trial results. N Engl J Med. 2024;390:12-18. doi:10.1056/example", index=1
    )
    assert row["matched_article"]["pmid"] == "12345678"
    assert row["resolution_method"] == "doi_search"
    assert row["status"] == "partial_match"  # Supplied fields cannot be confirmed.


async def test_doi_search_does_not_accept_a_different_doi(reference_searcher):
    reference_searcher.search_page.return_value = _reference_page([{"pmid": "99999999", "doi": "10.1056/wrong"}])
    row = await ReferenceVerificationService(reference_searcher).verify_reference("doi:10.1056/example", index=1)
    assert row["status"] == "unresolved"


async def test_doi_only_reference_does_not_invent_author_or_publication_year(reference_searcher):
    reference_searcher.search_page.return_value = _reference_page([{"pmid": "12345678", "doi": "10.2024/example.2023"}])
    row = await ReferenceVerificationService(reference_searcher).verify_reference("doi:10.2024/example.2023", index=1)
    assert row["status"] == "verified"
    assert row["parsed_reference"]["first_author"] == ""
    assert row["parsed_reference"]["year"] == ""
    assert row["parsed_reference"]["journal"] == ""


@pytest.mark.parametrize("failing_path", ["pmid", "ecitmatch"])
async def test_unavailable_reference_does_not_discard_other_rows(reference_searcher, citation_article, failing_path):
    reference_searcher.fetch_details.side_effect = [
        [citation_article],
        RuntimeError("upstream unavailable"),
    ]
    reference_searcher.find_by_citation.side_effect = RuntimeError("upstream unavailable")
    failing_reference = "PMID:99999999" if failing_path == "pmid" else "Doe A. Another trial. JAMA. 2023;330:44-50."
    report = await ReferenceVerificationService(reference_searcher).verify_reference_list(
        f"PMID:12345678\n{failing_reference}"
    )
    assert report["results"][0]["status"] == "verified"
    assert report["results"][1]["status"] == "source_unavailable"
    assert report["summary"]["verified"] == 1
    assert report["results"][1]["source_errors"]


@pytest.mark.parametrize("include_requested", [False, True])
async def test_pmid_lookup_checks_returned_identity(reference_searcher, citation_article, include_requested):
    reference_searcher.fetch_details.return_value = [
        {**citation_article, "pmid": "99999999"},
        *([citation_article] if include_requested else []),
    ]
    row = await ReferenceVerificationService(reference_searcher).verify_reference("PMID:12345678", index=1)
    # v0.7.1 rejects malformed provider batches instead of accepting a later
    # valid row. Preserve that strict boundary when porting these regressions.
    assert row["status"] == "source_unavailable"
    assert row["matched_article"] is None


@pytest.mark.parametrize(
    ("field", "first_id", "second_id"),
    [
        ("doi", "DOI: https://doi.org/10.1000/Example", "10.1000/example"),
        ("pmid", " 12345678 ", "12345678"),
        ("pmc", "https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/", "PMC12345"),
    ],
)
def test_cross_source_identity_agrees_with_deduplication(field, first_id, second_id):
    first = UnifiedArticle(title="First metadata record", primary_source="pubmed", **{field: first_id})
    second = UnifiedArticle(title="Second metadata record", primary_source="europe_pmc", **{field: second_id})
    assert canonical_article_key(first) == canonical_article_key(second)
    assert first.matches_identifier(second)
    papers, stats = ResultAggregator().aggregate([[first], [second]])
    assert len(papers) == 1
    assert stats.duplicates_removed == 1


def test_empty_doi_prefix_does_not_merge_unrelated_papers():
    first = UnifiedArticle(title="First independent clinical trial", primary_source="pubmed", doi="doi:")
    second = UnifiedArticle(title="Second independent clinical trial", primary_source="pubmed", doi="doi:")
    assert not first.matches_identifier(second)
    papers, _ = ResultAggregator().aggregate([[first, second]])
    assert len(papers) == 2


def test_empty_identifiers_allow_title_fallback():
    first = UnifiedArticle(title="The same clinical trial report", primary_source="pubmed", doi="doi:")
    second = UnifiedArticle(title=first.title, primary_source="europe_pmc")
    papers, stats = ResultAggregator().aggregate([[first, second]])
    assert len(papers) == 1
    assert stats.dedup_by_title == 1


async def test_different_cache_keys_fetch_concurrently():
    store = CacheStore[str](MemoryCacheBackend())
    release = asyncio.Event()
    both_started = asyncio.Event()
    started = 0

    async def fetch():
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await release.wait()
        return "article"

    tasks = [asyncio.create_task(store.get_or_fetch(key, fetch)) for key in ["a", "b"]]
    try:
        await asyncio.wait_for(both_started.wait(), timeout=1)
    finally:
        release.set()
        values = await asyncio.gather(*tasks)
    assert values == ["article", "article"]


async def test_normalized_cache_keys_share_one_inflight_fetch():
    store = CacheStore[str](MemoryCacheBackend(), key_normalizer=lambda key: key.strip().lower())
    release = asyncio.Event()
    started = asyncio.Event()
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return "article"

    tasks = [asyncio.create_task(store.get_or_fetch(key, fetch)) for key in [" PMID:1 ", "pmid:1", "PMID:1"]]
    try:
        await started.wait()
    finally:
        release.set()
    assert await asyncio.gather(*tasks) == ["article"] * 3
    assert calls == 1


async def test_cancelled_cache_fetch_allows_waiter_to_retry():
    store = CacheStore[str](MemoryCacheBackend())
    started = asyncio.Event()

    async def interrupted_fetch():
        started.set()
        await asyncio.Event().wait()

    first = asyncio.create_task(store.get_or_fetch("paper", interrupted_fetch))
    await started.wait()
    fetch = AsyncMock(return_value="recovered")
    second = asyncio.create_task(store.get_or_fetch("paper", fetch))
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert await asyncio.wait_for(second, timeout=1) == "recovered"
    assert store.get("paper") == "recovered"
    fetch.assert_awaited_once()


def test_cache_can_be_reused_across_event_loops():
    store = CacheStore[str](MemoryCacheBackend())

    async def fetch():
        await asyncio.sleep(0)
        return "article"

    async def lookup():
        store.invalidate("paper")
        results = await asyncio.gather(store.get_or_fetch("paper", fetch), store.get_or_fetch("paper", fetch))
        assert results == ["article", "article"]

    asyncio.run(lookup())
    asyncio.run(lookup())


@pytest.mark.parametrize("failure", ["create", "close"])
async def test_extended_source_failure_preserves_successful_fulltext(failure):
    europe_pmc = MagicMock(
        get_fulltext_xml=AsyncMock(return_value="<xml/>"),
        parse_fulltext_xml=MagicMock(
            return_value={"sections": [{"title": "Results", "content": "Verified source text"}]}
        ),
    )
    downloader = MagicMock(get_fulltext=AsyncMock(side_effect=RuntimeError("source unavailable")))
    downloader.close = AsyncMock(side_effect=RuntimeError("cleanup unavailable"))
    factory = (
        MagicMock(side_effect=RuntimeError("initialization unavailable")) if failure == "create" else lambda: downloader
    )
    log = AsyncMock()
    service = FulltextService(
        europe_pmc_client_factory=lambda: europe_pmc,
        unpaywall_client_factory=MagicMock(),
        core_client_factory=MagicMock(),
        downloader_factory=factory,
    )
    result = await service.retrieve(FulltextRequest(pmcid="PMC12345", extended_sources=True), log=log)
    assert "Verified source text" in result.fulltext_content
    assert result.fulltext_source_name == "Europe PMC"
    assert result.extended_sources_attempted
    log.assert_awaited()
    if failure == "close":
        downloader.close.assert_awaited_once()


def test_section_filter_ignores_trailing_comma_and_untitled_sections():
    results = {"title": "Results", "content": "Requested findings"}
    parsed = {"sections": [results, {"title": "Methods", "content": "Not requested"}, {"content": "Untitled content"}]}
    assert FulltextService._select_sections(parsed, "results, ") == [results]
