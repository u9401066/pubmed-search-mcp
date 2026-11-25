"""Boundary tests for the NCBI PMC fallback, source-failure classification and deadline.

The NCBI adapter runs its production request, retry, byte-cap and parser code
against ``httpx.MockTransport`` with PMC-shaped JATS; the Europe PMC side uses
the production fulltext cache. Only network addresses are replaced.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs

import httpx
import pytest

from pubmed_search.application.fulltext import FulltextRequest, FulltextService
from pubmed_search.application.fulltext.cache import (
    FulltextCache,
    FulltextCacheError,
    FulltextFetchDeadlineError,
    FulltextInvalidResponseError,
)
from pubmed_search.application.fulltext.coverage import classify_link_discovery_error, classify_source_failure
from pubmed_search.infrastructure.sources.base_client import (
    APIRequestError,
    APIResponseTooLargeError,
    BaseAPIClient,
    ProviderSchemaError,
)
from pubmed_search.infrastructure.sources.fulltext_download import FulltextResult, PDFLinkDiscoveryResult
from pubmed_search.infrastructure.sources.jats import parse_jats_article
from pubmed_search.infrastructure.sources.ncbi_pmc import NCBI_EUTILS_RATE_LIMIT, NCBIPMCClient
from pubmed_search.presentation.mcp_server.tools.article_source import PMCIDSource
from pubmed_search.presentation.mcp_server.tools.europe_pmc import register_europe_pmc_tools
from pubmed_search.shared.async_utils import OperationBudgetExceeded, RetryableOperationError
from pubmed_search.shared.exceptions import ParseError, RateLimitError
from tests.fixtures.pmc_jats import (
    PMC_EFETCH_EMPTY_ARTICLESET,
    PMC_EFETCH_EMPTY_BODY,
    PMC_EFETCH_EUTILS_ERROR,
    PMC_EFETCH_FRONT_MATTER_ONLY_COMMENT,
    PMC_EFETCH_FRONT_MATTER_ONLY_PARAGRAPH,
    PMC_EFETCH_FULL_BODY,
    PMC_EFETCH_FULL_BODY_WITH_SUB_ARTICLE,
    PMC_EFETCH_NO_ARTICLE,
    PMC_EFETCH_RESTRICTED_WITH_SUB_ARTICLE,
    PUBMED_ESUMMARY_WITH_PMC,
)

if TYPE_CHECKING:
    from collections.abc import Callable

PMCID = "PMC7096777"


class _NCBIFixture:
    """Serve E-utilities paths from fixtures and record every request."""

    def __init__(self, *, efetch: str | None = PMC_EFETCH_FULL_BODY, efetch_status: int = 200) -> None:
        self.efetch = efetch
        self.efetch_status = efetch_status
        self.esummary: dict[str, Any] = PUBMED_ESUMMARY_WITH_PMC
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/efetch.fcgi"):
            if self.efetch is None:
                return httpx.Response(self.efetch_status, text="")
            return httpx.Response(self.efetch_status, text=self.efetch, headers={"Content-Type": "text/xml"})
        if request.url.path.endswith("/esummary.fcgi"):
            return httpx.Response(200, json=self.esummary)
        return httpx.Response(404, text="unexpected path")

    def params(self, index: int = -1) -> dict[str, list[str]]:
        return parse_qs(self.requests[index].url.query.decode())


async def _ncbi_client(fixture: _NCBIFixture, *, api_key: str | None = None) -> NCBIPMCClient:
    client = NCBIPMCClient(email="fixture@example.org", api_key=api_key)
    await client.close()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(fixture.handler))
    return client


def _no_text_downloader() -> MagicMock:
    downloader = MagicMock()
    downloader.get_fulltext = AsyncMock(
        return_value=FulltextResult(link_discovery=PDFLinkDiscoveryResult(), error="No PDF links found")
    )
    downloader.close = AsyncMock()
    return downloader


def _service(
    *,
    europe_pmc: Any,
    ncbi: NCBIPMCClient | None,
    structured_xml_fetcher: Callable[[str], Any] | None = None,
    downloader: Any = None,
    unpaywall: Any = None,
    figures: Any = None,
    deadline_seconds: float | None = 30.0,
    hedge_seconds: float = 30.0,
) -> FulltextService:
    return FulltextService(
        europe_pmc_client_factory=lambda: europe_pmc,
        unpaywall_client_factory=lambda: unpaywall or AsyncMock(),
        core_client_factory=MagicMock(side_effect=AssertionError("CORE must not run")),
        downloader_factory=lambda: downloader or _no_text_downloader(),
        figure_client_factory=(lambda: figures) if figures is not None else None,
        structured_xml_fetcher=structured_xml_fetcher,
        ncbi_pmc_client_factory=(lambda: ncbi) if ncbi is not None else None,
        deadline_seconds=deadline_seconds,
        structured_hedge_seconds=hedge_seconds,
    )


# ----------------------------------------------------------------------------
# Europe PMC failure -> NCBI PMC body
# ----------------------------------------------------------------------------


async def test_europe_pmc_retry_exhaustion_falls_back_to_ncbi_pmc_body_with_sections() -> None:
    cache = FulltextCache()
    upstream = AsyncMock(side_effect=RetryableOperationError("Europe PMC request failed", status_code=503))
    fixture = _NCBIFixture()
    ncbi = await _ncbi_client(fixture)
    try:
        service = _service(
            europe_pmc=MagicMock(),
            ncbi=ncbi,
            structured_xml_fetcher=lambda pmcid: cache.get(pmcid, tenant="t", fetch=upstream),
        )
        result = await service.retrieve(FulltextRequest(pmcid=PMCID, include_pdf_links=False))
    finally:
        await ncbi.close()
        await cache.aclose()

    assert result.sources_tried == ["europe_pmc", "ncbi_pmc"]
    assert result.sources_completed == ["ncbi_pmc"]
    [epmc_error] = [error.to_dict() for error in result.source_errors]
    # Root-cause regression: the cache used to rewrite this as FulltextCacheError.
    assert epmc_error["source"] == "europe_pmc"
    assert epmc_error["code"] == "upstream_retries_exhausted"
    assert epmc_error["status_code"] == 503
    assert result.coverage_status == "partial"
    titles = [section["title"] for section in result.content_sections]
    # A heading with only nested subsections has no text of its own and is not a section.
    assert titles == ["Introduction", "Trial Design", "Outcomes", "Results", "Discussion"]
    assert "11/100 patients versus 9/101" in (result.raw_fulltext_content or "")
    assert "Abstract-only result sentence" not in (result.raw_fulltext_content or "")
    assert result.fulltext_source_name == "NCBI PMC (E-utilities)"
    assert result.fulltext_canonical_host == "PubMed Central"
    assert result.fulltext_provenance == "direct"
    assert result.fulltext_license == {
        "type": "open-access",
        "url": "https://creativecommons.org/licenses/by/4.0/",
        "text": "Synthetic CC-BY license statement.",
    }
    params = fixture.params()
    assert params["db"] == ["pmc"]
    assert params["id"] == ["7096777"]
    assert params["retmode"] == ["xml"]
    assert params["tool"] == ["pubmed-search-mcp"]
    assert params["email"] == ["fixture@example.org"]
    assert "api_key" not in params
    upstream.assert_awaited_once_with(PMCID)


async def test_europe_pmc_without_body_uses_ncbi_immediately_and_reports_no_body() -> None:
    provider = MagicMock()
    provider.get_fulltext_xml = AsyncMock(return_value=None)
    fixture = _NCBIFixture()
    ncbi = await _ncbi_client(fixture)
    try:
        result = await _service(europe_pmc=provider, ncbi=ncbi, hedge_seconds=60).retrieve(
            FulltextRequest(pmcid=PMCID, sections="results", include_pdf_links=False)
        )
    finally:
        await ncbi.close()

    assert result.coverage_status == "complete"
    assert [notice.to_dict()["code"] for notice in result.source_notices] == ["no_body"]
    assert result.source_notices[0].source == "europe_pmc"
    assert [section["title"] for section in result.content_sections] == ["Results"]
    assert result.section_selection is not None and result.section_selection.status == "matched"


async def test_slow_europe_pmc_is_hedged_and_abandoned_when_ncbi_answers_first() -> None:
    cache = FulltextCache()
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def hanging_epmc(_: str) -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "<article/>"

    fixture = _NCBIFixture()
    ncbi = await _ncbi_client(fixture)
    try:
        service = _service(
            europe_pmc=MagicMock(),
            ncbi=ncbi,
            structured_xml_fetcher=lambda pmcid: cache.get(pmcid, tenant="t", fetch=hanging_epmc),
            hedge_seconds=0.01,
        )
        result = await asyncio.wait_for(
            service.retrieve(FulltextRequest(pmcid=PMCID, include_pdf_links=False)), timeout=5
        )
        # The abandoned foreground download is cancelled, not leaked.
        await asyncio.wait_for(cancelled.wait(), timeout=1)
    finally:
        await ncbi.close()
        await cache.aclose()

    assert started.is_set()
    assert result.sources_tried == ["europe_pmc", "ncbi_pmc"]
    assert result.sources_completed == ["ncbi_pmc"]
    assert result.source_errors == []
    assert [(notice.source, notice.code) for notice in result.source_notices] == [("europe_pmc", "superseded")]
    assert result.coverage_status == "complete"
    assert result.has_retrieved_text


async def test_europe_pmc_metadata_outage_resolves_pmcid_and_doi_through_ncbi() -> None:
    provider = MagicMock()
    provider.get_article = AsyncMock(side_effect=APIRequestError("Europe PMC", reason="transport"))
    provider.get_fulltext_xml = AsyncMock(side_effect=APIRequestError("Europe PMC", reason="transport"))
    unpaywall = AsyncMock()
    unpaywall.get_oa_status.return_value = None
    fixture = _NCBIFixture()
    ncbi = await _ncbi_client(fixture, api_key="fixture-key")
    try:
        result = await _service(europe_pmc=provider, ncbi=ncbi, unpaywall=unpaywall, hedge_seconds=60).retrieve(
            FulltextRequest(pmid="12345678")
        )
    finally:
        await ncbi.close()

    assert (result.pmcid, result.doi) == (PMCID, "10.1000/smoke")
    assert result.sources_tried[:4] == ["europe_pmc_metadata", "ncbi_metadata", "europe_pmc", "ncbi_pmc"]
    assert {error.source: error.code for error in result.source_errors} == {
        "europe_pmc_metadata": "upstream_connection_error",
        "europe_pmc": "upstream_connection_error",
    }
    assert "ncbi_metadata" in result.sources_completed
    assert result.fulltext_source_name == "NCBI PMC (E-utilities)"
    esummary = parse_qs(fixture.requests[0].url.query.decode())
    assert esummary["db"] == ["pubmed"] and esummary["id"] == ["12345678"]
    assert all(parse_qs(request.url.query.decode())["api_key"] == ["fixture-key"] for request in fixture.requests)
    unpaywall.get_oa_status.assert_awaited_once_with("10.1000/smoke")


# ----------------------------------------------------------------------------
# Front-matter-only PMC records
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [PMC_EFETCH_FRONT_MATTER_ONLY_COMMENT, PMC_EFETCH_FRONT_MATTER_ONLY_PARAGRAPH])
async def test_publisher_restricted_pmc_record_is_reported_not_presented_as_fulltext(payload: str) -> None:
    provider = MagicMock()
    provider.get_fulltext_xml = AsyncMock(return_value=None)
    downloader = _no_text_downloader()
    ncbi = await _ncbi_client(_NCBIFixture(efetch=payload))
    try:
        result = await _service(europe_pmc=provider, ncbi=ncbi, downloader=downloader).retrieve(
            FulltextRequest(pmcid=PMCID)
        )
    finally:
        await ncbi.close()

    assert not result.has_retrieved_text
    assert not result.fulltext_content
    assert result.content_sections == []
    assert result.section_selection is not None and result.section_selection.status == "unavailable"
    assert result.fulltext_source_name is None
    assert result.title == "Synthetic EEG-guided anesthesia trial – a fixture"
    assert [(notice.source, notice.code) for notice in result.source_notices] == [
        ("europe_pmc", "no_body"),
        ("ncbi_pmc", "front_matter_only"),
    ]
    assert result.pdf_links == [
        {
            "source": "PubMed Central (article page)",
            "url": f"https://pmc.ncbi.nlm.nih.gov/articles/{PMCID}/",
            "type": "landing_page",
            "access": "free_to_read",
        }
    ]
    # Absent text keeps the ordinary PDF fallback; nothing was rendered from front matter.
    assert downloader.get_fulltext.await_args.kwargs["strategy"] == "extract_text"
    assert result.sources_tried == ["europe_pmc", "ncbi_pmc", "pdf_retrieval_fallback"]


async def _race_slow_mirror_against_ncbi_restriction(
    mirror_answer: Callable[[], Any], *, deadline_seconds: float = 30.0
) -> Any:
    """Europe PMC (the mirror) answers only after NCBI has reported a publisher restriction."""
    cache = FulltextCache()
    ncbi_answered = asyncio.Event()
    ncbi = await _ncbi_client(_NCBIFixture(efetch=PMC_EFETCH_FRONT_MATTER_ONLY_COMMENT))
    parse_ncbi = ncbi.parse_article_xml

    def parse_and_signal(xml: str) -> dict[str, Any]:
        parsed = parse_ncbi(xml)
        ncbi_answered.set()
        return parsed

    ncbi.parse_article_xml = parse_and_signal  # type: ignore[method-assign]

    async def slow_mirror(_: str) -> str | None:
        await ncbi_answered.wait()
        await asyncio.sleep(0.05)  # the restricted answer is already in hand
        return await mirror_answer()

    provider = MagicMock()
    provider.parse_fulltext_xml.side_effect = lambda xml: parse_jats_article(xml, source="Europe PMC")
    try:
        return await asyncio.wait_for(
            _service(
                europe_pmc=provider,
                ncbi=ncbi,
                structured_xml_fetcher=lambda pmcid: cache.get(pmcid, tenant="t", fetch=slow_mirror),
                hedge_seconds=0.01,
                deadline_seconds=deadline_seconds,
            ).retrieve(FulltextRequest(pmcid=PMCID)),
            timeout=10,
        )
    finally:
        await ncbi.close()
        await cache.aclose()


async def test_pmc_publisher_restriction_does_not_cancel_a_mirror_that_still_returns_the_body() -> None:
    """NCBI's restriction says nothing about Europe PMC's own copy; its body still wins."""

    async def body() -> str:
        return PMC_EFETCH_FULL_BODY

    result = await _race_slow_mirror_against_ncbi_restriction(body)

    assert result.has_retrieved_text
    assert result.fulltext_source_name == "Europe PMC"
    assert "11/100 patients versus 9/101" in (result.raw_fulltext_content or "")
    assert result.sources_completed == ["europe_pmc", "ncbi_pmc"]
    assert result.source_errors == []
    assert [(notice.source, notice.code) for notice in result.source_notices] == [("ncbi_pmc", "front_matter_only")]
    assert result.coverage_status == "complete"


async def test_pmc_publisher_restriction_is_kept_when_the_mirror_has_no_body() -> None:
    async def abstract_only() -> str:
        return PMC_EFETCH_FRONT_MATTER_ONLY_COMMENT

    result = await _race_slow_mirror_against_ncbi_restriction(abstract_only)

    assert not result.has_retrieved_text
    assert [(notice.source, notice.code) for notice in result.source_notices] == [
        ("europe_pmc", "no_body"),
        ("ncbi_pmc", "front_matter_only"),
    ]
    # The restricted record decides the link: free to read on PMC, not an open-access PDF.
    assert [link["type"] for link in result.pdf_links if "PubMed Central" in link["source"]] == ["landing_page"]
    assert result.coverage_status == "complete"


@pytest.mark.parametrize("mirror_hangs", [False, True], ids=["mirror-fails-slowly", "mirror-hangs"])
async def test_pmc_publisher_restriction_waits_for_the_mirror_and_reports_its_failure(mirror_hangs: bool) -> None:
    """ENGAGES (PMC6439616) shape: NCBI restricts XML while Europe PMC keeps failing slowly."""

    async def failing() -> str:
        if mirror_hangs:
            await asyncio.Event().wait()
        raise RetryableOperationError("Europe PMC request failed", status_code=503)

    result = await _race_slow_mirror_against_ncbi_restriction(failing, deadline_seconds=1.0)

    expected_code = "deadline_exceeded" if mirror_hangs else "upstream_retries_exhausted"
    assert [(error.source, error.code) for error in result.source_errors] == [("europe_pmc", expected_code)]
    # A restriction on NCBI's copy is not a definitive answer for the mirror: never "superseded".
    assert [(notice.source, notice.code) for notice in result.source_notices] == [("ncbi_pmc", "front_matter_only")]
    assert not result.has_retrieved_text
    assert result.coverage_status == "partial"
    assert result.pdf_links[0]["type"] == "landing_page"


def test_service_and_settings_share_the_default_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    from pubmed_search.application.fulltext.service import DEFAULT_FULLTEXT_DEADLINE_SECONDS
    from pubmed_search.shared.settings import load_settings

    monkeypatch.delenv("PUBMED_FULLTEXT_DEADLINE_SECONDS", raising=False)
    monkeypatch.delenv("PUBMED_FULLTEXT_NCBI_PMC_FALLBACK", raising=False)
    settings = load_settings()
    assert settings.fulltext_deadline_seconds == DEFAULT_FULLTEXT_DEADLINE_SECONDS
    assert settings.fulltext_ncbi_pmc_fallback is True
    monkeypatch.setenv("PUBMED_FULLTEXT_DEADLINE_SECONDS", "5")
    with pytest.raises(ValueError, match="greater than or equal to 10"):
        load_settings()


async def test_ncbi_adapter_parses_restriction_and_missing_records_at_the_boundary() -> None:
    fixture = _NCBIFixture(efetch=PMC_EFETCH_NO_ARTICLE)
    client = await _ncbi_client(fixture)
    try:
        assert client._rate_limiter_name == NCBI_EUTILS_RATE_LIMIT
        assert await client.get_article_xml(PMCID) is None
        fixture.efetch, fixture.efetch_status = None, 404
        assert await client.get_article_xml(PMCID) is None
        restricted = client.parse_article_xml(PMC_EFETCH_FRONT_MATTER_ONLY_PARAGRAPH)
        assert restricted["access_restricted"] is True
        assert restricted["sections"] == []
        assert restricted["license"] is None
        full = client.parse_article_xml(PMC_EFETCH_FULL_BODY)
        assert full["access_restricted"] is False
        assert full["references"][0]["pmid"] == "11111111"
        with pytest.raises(ParseError) as error:
            client.parse_article_xml("<article><secret>token=hidden</article>")
        assert "token=hidden" not in str(error.value)
    finally:
        await client.close()


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(PMC_EFETCH_EUTILS_ERROR, id="eutils-error-envelope"),
        pytest.param(PMC_EFETCH_EMPTY_BODY, id="empty-body"),
        pytest.param(PMC_EFETCH_EMPTY_ARTICLESET, id="empty-articleset"),
        pytest.param("<pmc-articleset><ERROR>Backend failed</ERROR></pmc-articleset>", id="error-in-articleset"),
    ],
)
async def test_ncbi_efetch_200_without_an_answer_is_a_failure_not_complete_coverage(payload: str) -> None:
    """HTTP 200 with an E-utilities error or nothing at all says nothing about the article."""
    provider = MagicMock()
    provider.get_fulltext_xml = AsyncMock(return_value=None)
    ncbi = await _ncbi_client(_NCBIFixture(efetch=payload))
    try:
        with pytest.raises(ProviderSchemaError):
            await ncbi.get_article_xml(PMCID)
        result = await _service(europe_pmc=provider, ncbi=ncbi, hedge_seconds=60).retrieve(
            FulltextRequest(pmcid=PMCID, include_pdf_links=False)
        )
    finally:
        await ncbi.close()

    assert [(error.source, error.code) for error in result.source_errors] == [("ncbi_pmc", "invalid_response")]
    assert "ncbi_pmc" not in result.sources_completed
    # Only Europe PMC actually answered "no body"; NCBI's silence is not a second "no record".
    assert [(notice.source, notice.code) for notice in result.source_notices] == [("europe_pmc", "no_body")]
    assert result.coverage_status != "complete"
    assert not result.has_retrieved_text


# ----------------------------------------------------------------------------
# Nested <sub-article> records (decision letters, author replies)
# ----------------------------------------------------------------------------


async def test_restricted_main_article_is_not_replaced_by_a_sub_article_body() -> None:
    provider = MagicMock()
    provider.get_fulltext_xml = AsyncMock(return_value=None)
    ncbi = await _ncbi_client(_NCBIFixture(efetch=PMC_EFETCH_RESTRICTED_WITH_SUB_ARTICLE))
    try:
        parsed = ncbi.parse_article_xml(PMC_EFETCH_RESTRICTED_WITH_SUB_ARTICLE)
        result = await _service(europe_pmc=provider, ncbi=ncbi, hedge_seconds=60).retrieve(
            FulltextRequest(pmcid=PMCID, include_pdf_links=False)
        )
    finally:
        await ncbi.close()

    assert parsed["access_restricted"] is True
    assert parsed["sections"] == []
    assert parsed["references"] == []
    assert parsed["figures"] == []
    assert not result.has_retrieved_text
    assert "author response" not in (result.raw_fulltext_content or "").lower()
    assert [(notice.source, notice.code) for notice in result.source_notices] == [
        ("europe_pmc", "no_body"),
        ("ncbi_pmc", "front_matter_only"),
    ]
    assert result.fulltext_source_name is None


def test_jats_main_article_excludes_nested_sub_article_content() -> None:
    client = NCBIPMCClient(email="fixture@example.org")

    parsed = client.parse_article_xml(PMC_EFETCH_FULL_BODY_WITH_SUB_ARTICLE)

    assert parsed["access_restricted"] is False
    assert parsed["title"] == "Synthetic EEG-guided anesthesia trial – a fixture"
    assert "Reply-only abstract" not in parsed["abstract"]
    # Parser-level sections still include the title-only "Methods" heading.
    assert [section["title"] for section in parsed["sections"]] == [
        "Introduction",
        "Methods",
        "Trial Design",
        "Outcomes",
        "Results",
        "Discussion",
    ]
    rendered = " ".join(str(section["content"]) for section in parsed["sections"])
    assert "author response" not in rendered.lower()
    assert [reference["pmid"] for reference in parsed["references"]] == ["11111111"]
    assert all(figure["label"] != "Author response image 1" for figure in parsed["figures"])
    assert parsed["license"] is not None and parsed["license"]["type"] == "open-access"


# ----------------------------------------------------------------------------
# Failure classification: local cache vs upstream outage / rate limit / timeout
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "code", "status_code", "retry_after"),
    [
        (FulltextCacheError("Fulltext runtime is closed"), "cache_error", None, None),
        (RetryableOperationError("x", status_code=503), "upstream_retries_exhausted", 503, None),
        (RetryableOperationError("x", status_code=429, cooldown_seconds=30.0), "rate_limited", 429, 30.0),
        (RetryableOperationError("x", status_code=429, retry_after=12.0), "rate_limited", 429, 12.0),
        (RateLimitError("Circuit breaker is open", retry_after=60.0), "rate_limited", None, 60.0),
        (APIRequestError("Europe PMC", reason="timeout"), "timeout", None, None),
        (APIRequestError("Europe PMC", reason="transport"), "upstream_connection_error", None, None),
        (APIRequestError("Europe PMC", status_code=403), "upstream_http_error", 403, None),
        (ProviderSchemaError("Europe PMC"), "invalid_response", None, None),
        (APIResponseTooLargeError("Europe PMC", max_bytes=10), "invalid_response", None, None),
        (ParseError("bad XML", source="Europe PMC"), "invalid_response", None, None),
        (FulltextInvalidResponseError(), "invalid_response", None, None),
        (FulltextFetchDeadlineError("deadline"), "timeout", None, None),
        (OperationBudgetExceeded("budget"), "timeout", None, None),
        (RuntimeError("token=super-secret"), "source_unavailable", None, None),
    ],
)
def test_source_failures_are_classified_without_exposing_details(
    error: BaseException, code: str, status_code: int | None, retry_after: float | None
) -> None:
    failure = classify_source_failure("europe_pmc", error)

    assert (failure.code, failure.status_code, failure.retry_after) == (code, status_code, retry_after)
    assert "secret" not in failure.message
    if retry_after is not None:
        assert f"cooldown {retry_after:.0f}s" in failure.message
    if code == "cache_error":
        assert "upstream status is unknown" in failure.message


@pytest.mark.parametrize(
    ("kind", "status_code", "code"),
    [
        ("retryable", 429, "rate_limited"),
        ("retryable", 503, "upstream_retries_exhausted"),
        ("timeout", None, "timeout"),
        ("transport", None, "upstream_connection_error"),
        ("http", 401, "upstream_http_error"),
        ("validation", None, "invalid_response"),
        ("unexpected", None, "source_unavailable"),
    ],
)
def test_link_discovery_errors_share_the_vocabulary(kind: str, status_code: int | None, code: str) -> None:
    assert classify_link_discovery_error("semantic_scholar", kind=kind, status_code=status_code).code == code


async def test_exhausted_rate_limit_reports_the_shared_cooldown_it_applied() -> None:
    class _Probe(BaseAPIClient):
        _service_name = "Fulltext Probe 429"
        _MAX_RETRIES = 0

    client = _Probe()
    await client.close()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(429)))
    try:
        with pytest.raises(RetryableOperationError) as raised:
            await client._make_request("https://core.example.test/search")
    finally:
        await client.close()

    assert raised.value.retry_after is None  # retry scheduling semantics unchanged
    assert raised.value.cooldown_seconds == 30.0
    failure = classify_source_failure("core", raised.value)
    assert failure.code == "rate_limited"
    assert "cooldown 30s" in failure.message


async def test_cache_propagates_upstream_failures_and_reserves_cache_error_for_local_faults() -> None:
    cache = FulltextCache()
    upstream = AsyncMock(side_effect=RetryableOperationError("Europe PMC request failed", status_code=502))
    try:
        for _ in range(2):
            with pytest.raises(RetryableOperationError):
                await cache.get(PMCID, tenant="t", fetch=upstream)
        # A failed demand read is never served from cache; the next read retries.
        assert upstream.await_count == 2
    finally:
        await cache.aclose()

    ncbi = await _ncbi_client(_NCBIFixture())
    try:
        result = await _service(
            europe_pmc=MagicMock(),
            ncbi=ncbi,
            structured_xml_fetcher=lambda pmcid: cache.get(pmcid, tenant="t", fetch=upstream),
        ).retrieve(FulltextRequest(pmcid=PMCID, include_pdf_links=False))
    finally:
        await ncbi.close()

    assert [(error.source, error.code) for error in result.source_errors] == [("europe_pmc", "cache_error")]
    assert result.has_retrieved_text
    assert upstream.await_count == 2


# ----------------------------------------------------------------------------
# Overall deadline
# ----------------------------------------------------------------------------


async def test_deadline_cancels_slow_optional_source_and_reports_unstarted_ones_as_skipped() -> None:
    provider = MagicMock()
    provider.get_article = AsyncMock(return_value={"pmc_id": "PMC123", "doi": "10.1000/slow"})
    provider.get_fulltext_xml = AsyncMock(return_value="<article/>")
    provider.parse_fulltext_xml.return_value = {"title": "T", "sections": [{"title": "Results", "content": "Body"}]}
    hanging_unpaywall = AsyncMock()

    async def never(_: str) -> None:
        await asyncio.Event().wait()

    hanging_unpaywall.get_oa_status.side_effect = never
    figures = AsyncMock()
    service = FulltextService(
        europe_pmc_client_factory=lambda: provider,
        unpaywall_client_factory=lambda: hanging_unpaywall,
        core_client_factory=MagicMock(),
        downloader_factory=MagicMock(),
        figure_client_factory=lambda: figures,
        deadline_seconds=0.2,
    )

    result = await asyncio.wait_for(
        service.retrieve(FulltextRequest(pmid="123", include_figures=True)),
        timeout=5,
    )

    assert result.has_retrieved_text
    assert [(error.source, error.code) for error in result.source_errors] == [("unpaywall", "deadline_exceeded")]
    assert "get_fulltext deadline" in result.source_errors[0].message
    assert result.sources_completed == ["europe_pmc_metadata", "europe_pmc"]
    assert [skipped.to_dict() for skipped in result.sources_skipped] == [
        {
            "source": "pmc_figures",
            "reason": "deadline",
            "message": "Not attempted: the get_fulltext deadline elapsed before this source started.",
        }
    ]
    assert "pmc_figures" not in result.sources_tried
    assert result.coverage_status == "partial"
    figures.get_article_figures.assert_not_awaited()


async def test_deadline_inside_structured_stage_is_reported_as_deadline_not_outage() -> None:
    async def never(_: str) -> str:
        await asyncio.Event().wait()
        return ""

    ncbi = await _ncbi_client(_NCBIFixture())
    try:
        result = await asyncio.wait_for(
            _service(
                europe_pmc=MagicMock(),
                ncbi=ncbi,
                structured_xml_fetcher=never,
                deadline_seconds=0.1,
                hedge_seconds=60,
            ).retrieve(FulltextRequest(pmcid=PMCID)),
            timeout=5,
        )
    finally:
        await ncbi.close()

    assert [(error.source, error.code) for error in result.source_errors] == [("europe_pmc", "deadline_exceeded")]
    assert [skipped.source for skipped in result.sources_skipped] == ["ncbi_pmc", "pdf_retrieval_fallback"]
    assert all(error.code != "source_unavailable" for error in result.source_errors)
    assert result.coverage_status == "unavailable"


# ----------------------------------------------------------------------------
# Tool contract: the agent sees typed statuses
# ----------------------------------------------------------------------------


def _capture_tools() -> dict[str, Any]:
    tools: dict[str, Any] = {}
    mcp = MagicMock()
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
    register_europe_pmc_tools(mcp)
    return tools


@pytest.mark.parametrize("output_format", ["json", "markdown"])
async def test_get_fulltext_reports_typed_statuses_and_ncbi_body(
    monkeypatch: pytest.MonkeyPatch, output_format: str
) -> None:
    monkeypatch.setenv("PUBMED_FULLTEXT_NCBI_PMC_FALLBACK", "true")
    monkeypatch.setenv("INSTITUTIONAL_DIRECT_FETCH", "false")
    provider = MagicMock()
    provider.get_fulltext_xml = AsyncMock(
        side_effect=RetryableOperationError("Europe PMC request failed", status_code=503)
    )
    ncbi = await _ncbi_client(_NCBIFixture())
    tools = _capture_tools()
    try:
        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client", return_value=provider
            ),
            patch("pubmed_search.infrastructure.sources.ncbi_pmc.get_ncbi_pmc_client", return_value=ncbi),
        ):
            response = await tools["get_fulltext"](
                source=PMCIDSource(kind="pmcid", value=PMCID),
                include_pdf_links=False,
                output_format=output_format,
            )
    finally:
        await ncbi.close()

    if output_format == "json":
        payload = json.loads(response)
        assert payload["fulltext_available"] is True
        content_provenance = payload["section_provenance"]["content"]
        assert content_provenance["surfacing_source"] == "NCBI PMC (E-utilities)"
        assert content_provenance["canonical_host"] == "PubMed Central"
        assert content_provenance["provenance"] == "direct"
        assert payload["source_errors"] == [
            {
                "source": "europe_pmc",
                "code": "upstream_retries_exhausted",
                "message": "The upstream source kept failing after retries (HTTP 503).",
                "status_code": 503,
            }
        ]
        assert payload["source_notices"] == []
        assert payload["sources_skipped"] == []
        assert payload["fulltext_license"]["type"] == "open-access"
        assert payload["deadline_seconds"] == 90.0
        assert payload["content_sections"][0]["title"] == "Introduction"
    else:
        assert "europe\\_pmc (`upstream\\_retries\\_exhausted`)" in response or (
            "europe_pmc (`upstream_retries_exhausted`)" in response
        )
        assert "Declared article license: open-access" in response
        assert "Synthetic introduction" in response
