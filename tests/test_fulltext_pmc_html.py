"""Boundary tests for the PMC article-page source (``pmc_html``).

The adapter runs its production fetch (fail-closed outbound layer, identity
headers, status mapping) against ``httpx.MockTransport`` and its production
parser against synthetic PMC-shaped pages. The service tests use the real NCBI
adapter for the ``front_matter_only`` record. Only network addresses and
provider payloads are replaced.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from pubmed_search.application.fulltext import FulltextRequest, FulltextService
from pubmed_search.application.fulltext.coverage import classify_source_failure
from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.infrastructure.sources.base_client import APIResponseTooLargeError, ProviderSchemaError
from pubmed_search.infrastructure.sources.fulltext_download import FulltextResult, PDFLinkDiscoveryResult
from pubmed_search.infrastructure.sources.jats import parse_jats_article
from pubmed_search.infrastructure.sources.ncbi_pmc import NCBIPMCClient
from pubmed_search.infrastructure.sources.pmc_html import (
    PMCArticlePageClient,
    parse_article_html,
    parse_pmc_article_html,
)
from pubmed_search.presentation.mcp_server.tools import fulltext_runtime
from pubmed_search.presentation.mcp_server.tools.article_source import PMCIDSource, PMIDSource
from pubmed_search.presentation.mcp_server.tools.europe_pmc import register_europe_pmc_tools
from pubmed_search.presentation.mcp_server.tools.tool_session import ToolSessionRuntime, bind_tool_session_runtime
from pubmed_search.shared.async_utils import RetryableOperationError
from pubmed_search.shared.exceptions import RateLimitError
from tests.fixtures.pmc_html import (
    FIXTURE_DOI,
    FIXTURE_PMCID,
    FIXTURE_PMID,
    GENERIC_ARTICLE_HTML,
    PMC_ARTICLE_PAGE,
    PMC_ARTICLE_PAGE_WITHOUT_BODY,
    PMC_CHALLENGE_PAGE,
    PMC_ERROR_PAGE,
    pmc_article_page,
)
from tests.fixtures.pmc_jats import PMC_EFETCH_FRONT_MATTER_ONLY_PARAGRAPH

if TYPE_CHECKING:
    from collections.abc import Callable

_CHROME_MARKERS = (
    "An official website",
    "Search in PMC",
    "PERMALINK",
    "ACTIONS",
    "Cite dialog",
    "footer text",
    "Find articles by",
    "Open in a new tab",
    "Table-only cell",
    "Figure caption text",
    "Supplement 1",
    "Click here for additional data file",
    "Corresponding Author",
    "Copyright 2024",
    "A related fixture editorial",
    "Key-point question",
    "Associated Data",
    "This section collects",
)


async def _public_resolver(_host: str, _port: int) -> tuple[str, ...]:
    return ("93.184.216.34",)


def _page_client(
    handler: Callable[[httpx.Request], httpx.Response], **kwargs: Any
) -> tuple[PMCArticlePageClient, httpx.AsyncClient]:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = PMCArticlePageClient(
        email="fixture@example.org",
        client=http,
        resolver=_public_resolver,
        clock=lambda: "2026-11-25T08:00:00Z",
        **kwargs,
    )
    return client, http


def _page_document(html: str = PMC_ARTICLE_PAGE, *, pmcid: str = FIXTURE_PMCID) -> str:
    parsed = parse_pmc_article_html(html, pmcid=pmcid)
    parsed.update({"source": "pmc_html", "url": parsed["canonical_url"], "retrieved_at": "2026-11-25T08:00:00Z"})
    return json.dumps(parsed)


async def _ncbi_restricted() -> NCBIPMCClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=PMC_EFETCH_FRONT_MATTER_ONLY_PARAGRAPH, headers={"Content-Type": "text/xml"})

    client = NCBIPMCClient(email="fixture@example.org")
    await client.close()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def _no_text_downloader() -> MagicMock:
    downloader = MagicMock()
    downloader.get_fulltext = AsyncMock(
        return_value=FulltextResult(link_discovery=PDFLinkDiscoveryResult(), error="No PDF links found")
    )
    downloader.close = AsyncMock()
    return downloader


def _failing_europe_pmc() -> AsyncMock:
    return AsyncMock(side_effect=RetryableOperationError("Europe PMC request failed", status_code=503))


def _service(
    *,
    structured_xml_fetcher: Any,
    ncbi: NCBIPMCClient | None,
    page_fetcher: Any,
    hedge_seconds: float = 30.0,
) -> FulltextService:
    return FulltextService(
        europe_pmc_client_factory=MagicMock,
        unpaywall_client_factory=AsyncMock,
        core_client_factory=MagicMock(side_effect=AssertionError("CORE must not run")),
        downloader_factory=_no_text_downloader,
        structured_xml_fetcher=structured_xml_fetcher,
        ncbi_pmc_client_factory=(lambda: ncbi) if ncbi is not None else None,
        article_page_fetcher=page_fetcher,
        deadline_seconds=30.0,
        structured_hedge_seconds=hedge_seconds,
    )


# ----------------------------------------------------------------------------
# Parser
# ----------------------------------------------------------------------------


def test_parser_projects_a_pmc_page_onto_the_shared_section_model() -> None:
    parsed = parse_pmc_article_html(PMC_ARTICLE_PAGE, pmcid=FIXTURE_PMCID)

    assert parsed["title"] == "Guided anesthesia fixture trial: A Synthetic Randomized Fixture"
    assert "Synthetic abstract importance." in parsed["abstract"]
    assert "Key-point question" not in parsed["abstract"]
    assert [section["title"] for section in parsed["sections"]] == [
        "Introduction",
        "Methods",
        "Trial Design",
        "Outcomes",
        "Results",
        "Primary Outcome",
        "Discussion",
        "Conclusions",
    ]
    sections = {section["title"]: section["content"] for section in parsed["sections"]}
    assert sections["Methods"] == ""
    assert "- Inclusion item one." in sections["Trial Design"]
    assert "11 of 100 patients" in sections["Primary Outcome"]
    assert "Abstract-only result" not in json.dumps(parsed["sections"])
    body_text = json.dumps(parsed["sections"])
    for marker in _CHROME_MARKERS:
        assert marker not in body_text, marker

    assert parsed["figures"] == [
        {
            "figure_id": "f1",
            "label": "Figure 1",
            "caption_title": "Fixture Flow Diagram.",
            "caption_text": "Figure caption text describing the synthetic flow.",
            "graphic_href": "https://cdn.ncbi.nlm.nih.gov/pmc/blobs/fixture/f1.jpg",
        }
    ]
    assert parsed["references"][0] == {
        "label": "1",
        "text": "Fixture A, Example B. A synthetic reference. Fixture J. 2020;1:1-2. doi: 10.5555/ref.one",
        "pmid": "31000001",
        "doi": "10.5555/ref.one",
    }
    assert parsed["references"][1]["pmid"] == "" and parsed["references"][1]["doi"] == ""
    assert parsed["license"] == {"text": "Copyright 2024 Fixture Press. All Rights Reserved."}
    assert parsed["pmcid"] == FIXTURE_PMCID
    assert parsed["pmid"] == FIXTURE_PMID
    assert parsed["doi"] == FIXTURE_DOI.lower()
    assert parsed["courtesy_note"].endswith("courtesy of Fixture Press")
    assert parsed["pdf_url"] == ""


def test_parser_keeps_a_declared_open_license_verbatim_with_its_link() -> None:
    parsed = parse_pmc_article_html(
        pmc_article_page(open_access=True, pdf_url="https://pmc.ncbi.nlm.nih.gov/articles/PMC7000001/pdf/f.pdf"),
        pmcid=FIXTURE_PMCID,
    )

    assert parsed["license"]["url"] == "https://creativecommons.org/licenses/by/4.0/"
    assert "Creative Commons Attribution (CC BY 4.0)" in parsed["license"]["text"]
    assert "PMC Copyright notice" not in parsed["license"]["text"]
    assert parsed["pdf_url"].endswith("/pdf/f.pdf")


@pytest.mark.parametrize(
    "html",
    [PMC_CHALLENGE_PAGE, PMC_ERROR_PAGE, ""],
    ids=["challenge", "error-page", "empty"],
)
def test_parser_rejects_pages_that_are_not_pmc_articles(html: str) -> None:
    with pytest.raises(ProviderSchemaError):
        parse_pmc_article_html(html, pmcid=FIXTURE_PMCID)


def test_parser_rejects_a_page_that_declares_a_different_article() -> None:
    with pytest.raises(ProviderSchemaError):
        parse_pmc_article_html(pmc_article_page(canonical="PMC7999999"), pmcid=FIXTURE_PMCID)


def test_page_with_only_an_abstract_has_no_body_sections() -> None:
    parsed = parse_pmc_article_html(PMC_ARTICLE_PAGE_WITHOUT_BODY, pmcid=FIXTURE_PMCID)

    assert parsed["sections"] == []
    assert "Only an abstract" in parsed["abstract"]


def test_generic_article_html_skips_site_chrome_and_splits_at_headings() -> None:
    parsed = parse_article_html(GENERIC_ARTICLE_HTML)

    assert parsed["title"] == "Generic publisher fixture"
    assert parsed["abstract"] == "Generic abstract sentence."
    assert parsed["sections"] == [
        {"title": "Methods", "content": "Generic methods paragraph."},
        {"title": "Results", "content": "Generic results paragraph with 3 of 30 events."},
    ]
    text = json.dumps(parsed)
    for marker in ("navigation", "cookies", "sidebar", "social media", "footer"):
        assert marker not in text


# ----------------------------------------------------------------------------
# Client: one page, identity, typed failures
# ----------------------------------------------------------------------------


async def test_client_reads_one_page_with_ncbi_identity_and_records_provenance() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=PMC_ARTICLE_PAGE, headers={"Content-Type": "text/html; charset=utf-8"})

    client, http = _page_client(handler)
    try:
        document = json.loads(await client.fetch_article_document(FIXTURE_PMCID.lower()) or "null")
    finally:
        await http.aclose()

    assert len(requests) == 1
    assert requests[0].headers["host"] == "pmc.ncbi.nlm.nih.gov"
    assert requests[0].url.path == f"/articles/{FIXTURE_PMCID}/"
    assert "mailto:fixture@example.org" in requests[0].headers["user-agent"]
    assert requests[0].headers["accept"].startswith("text/html")
    assert document["source"] == "pmc_html"
    assert document["url"] == f"https://pmc.ncbi.nlm.nih.gov/articles/{FIXTURE_PMCID}/"
    assert document["retrieved_at"] == "2026-11-25T08:00:00Z"
    assert any("11 of 100" in section["content"] for section in document["sections"])


async def test_missing_article_page_is_an_absence_not_an_error() -> None:
    client, http = _page_client(lambda request: httpx.Response(404, text="Page not found"))
    try:
        assert await client.fetch_article_document(FIXTURE_PMCID) is None
    finally:
        await http.aclose()


@pytest.mark.parametrize(
    ("response", "code", "retry_after"),
    [
        (httpx.Response(429, text="slow down", headers={"Retry-After": "7"}), "rate_limited", 7.0),
        (httpx.Response(503, text="maintenance"), "upstream_retries_exhausted", None),
        (httpx.Response(403, text="forbidden"), "upstream_http_error", None),
        (
            httpx.Response(200, text='{"not":"html"}', headers={"Content-Type": "application/json"}),
            "invalid_response",
            None,
        ),
        (httpx.Response(200, text=PMC_ERROR_PAGE, headers={"Content-Type": "text/html"}), "invalid_response", None),
        (httpx.Response(200, text=PMC_CHALLENGE_PAGE, headers={"Content-Type": "text/html"}), "rate_limited", 300.0),
    ],
    ids=["429", "503", "403", "json", "error-page", "bot-challenge"],
)
async def test_page_failures_are_typed_like_other_sources(
    response: httpx.Response, code: str, retry_after: float | None
) -> None:
    client, http = _page_client(lambda request: response)
    try:
        with pytest.raises(Exception) as caught:
            await client.fetch_article_document(FIXTURE_PMCID)
    finally:
        await http.aclose()

    failure = classify_source_failure("pmc_html", caught.value)
    assert failure.code == code
    assert failure.retry_after == retry_after
    assert "pmc.ncbi" not in failure.message


async def test_a_bot_challenge_backs_off_and_later_reads_fail_fast_without_traffic() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=PMC_CHALLENGE_PAGE, headers={"Content-Type": "text/html"})

    client, http = _page_client(handler)
    try:
        with pytest.raises(RateLimitError):
            await client.fetch_article_document(FIXTURE_PMCID)
        started = asyncio.get_running_loop().time()
        with pytest.raises(RateLimitError) as cooling:
            await client.fetch_article_document("PMC7000002")
        elapsed = asyncio.get_running_loop().time() - started
    finally:
        await http.aclose()

    assert len(requests) == 1
    assert elapsed < 1.0
    failure = classify_source_failure("pmc_html", cooling.value)
    assert failure.code == "rate_limited"
    assert failure.retry_after is not None
    assert 0 < failure.retry_after <= 300


async def test_redirect_away_from_ncbi_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "pmc.ncbi.nlm.nih.gov":
            return httpx.Response(302, headers={"Location": "https://mirror.example.org/copy"})
        return httpx.Response(200, text=PMC_ARTICLE_PAGE, headers={"Content-Type": "text/html"})

    client, http = _page_client(handler)
    try:
        with pytest.raises(ProviderSchemaError):
            await client.fetch_article_document(FIXTURE_PMCID)
    finally:
        await http.aclose()


async def test_oversized_page_stops_at_the_byte_cap() -> None:
    client, http = _page_client(
        lambda request: httpx.Response(200, text=PMC_ARTICLE_PAGE, headers={"Content-Type": "text/html"}),
        max_bytes=1_024,
    )
    try:
        with pytest.raises(APIResponseTooLargeError):
            await client.fetch_article_document(FIXTURE_PMCID)
    finally:
        await http.aclose()


# ----------------------------------------------------------------------------
# Service: when the page runs, and when it never runs
# ----------------------------------------------------------------------------


async def test_front_matter_only_record_is_read_from_the_public_pmc_page() -> None:
    page_fetcher = AsyncMock(return_value=_page_document())
    ncbi = await _ncbi_restricted()
    try:
        service = _service(structured_xml_fetcher=_failing_europe_pmc(), ncbi=ncbi, page_fetcher=page_fetcher)
        result = await service.retrieve(
            FulltextRequest(pmcid=FIXTURE_PMCID, sections="primary outcome", explicit_article_read=True)
        )
    finally:
        await ncbi.close()

    page_fetcher.assert_awaited_once_with(FIXTURE_PMCID)
    assert result.sources_tried[:3] == ["europe_pmc", "ncbi_pmc", "pmc_html"]
    assert {"ncbi_pmc", "pmc_html"} <= set(result.sources_completed)
    assert [(notice.source, notice.code) for notice in result.source_notices] == [("ncbi_pmc", "front_matter_only")]
    assert [section["title"] for section in result.content_sections] == ["Primary Outcome"]
    assert "11 of 100 patients" in (result.fulltext_content or "")
    assert result.fulltext_source_name == "PMC article page (HTML)"
    assert result.fulltext_provenance == "direct"
    assert result.fulltext_origin == "provider"
    assert result.fulltext_retrieval == {
        "source": "pmc_html",
        "method": "server_fetch",
        "url": f"https://pmc.ncbi.nlm.nih.gov/articles/{FIXTURE_PMCID}/",
        "retrieved_at": "2026-11-25T08:00:00Z",
        "license_text": "Copyright 2024 Fixture Press. All Rights Reserved.",
        "courtesy_note": "Articles from Synthetic Journal of Fixtures are provided here courtesy of Fixture Press",
        "access": "free_to_read",
        "usage": "individual_reading",
    }
    assert result.fulltext_plan == []
    # A body was found, so the PDF retrieval fallback never ran.
    assert "pdf_retrieval_fallback" not in result.sources_tried


async def test_article_page_is_never_read_without_an_explicit_single_article_request() -> None:
    """Batch, prefetch and every other caller keep the default flag and must not reach PMC pages."""
    page_fetcher = AsyncMock(side_effect=AssertionError("PMC article page read outside an explicit request"))
    ncbi = await _ncbi_restricted()
    try:
        service = _service(structured_xml_fetcher=_failing_europe_pmc(), ncbi=ncbi, page_fetcher=page_fetcher)
        default_request = FulltextRequest(pmcid=FIXTURE_PMCID)
        assert default_request.explicit_article_read is False
        result = await service.retrieve(default_request)
    finally:
        await ncbi.close()

    page_fetcher.assert_not_awaited()
    assert "pmc_html" not in result.sources_tried
    assert not result.has_retrieved_text
    host_fetch = next(step for step in result.fulltext_plan if step["step"] == "host_fetch")
    assert host_fetch["url"] == f"https://pmc.ncbi.nlm.nih.gov/articles/{FIXTURE_PMCID}/"
    assert "front matter only" in host_fetch["why"]


async def test_search_prefetch_never_reads_article_pages() -> None:
    """unified_search(fulltext="prefetch") schedules public XML only, never the PMC page."""
    prefetched: list[str] = []
    page_reads = AsyncMock(side_effect=AssertionError("prefetch must not read PMC article pages"))

    async def xml_only(pmcid: str) -> str | None:
        prefetched.append(pmcid)
        return None

    runtime = ToolSessionRuntime()
    articles = [UnifiedArticle(title="Fixture", pmc=f"PMC70000{index}", primary_source="pubmed") for index in range(3)]
    with (
        bind_tool_session_runtime(runtime),
        patch.object(fulltext_runtime, "fetch_prefetch_xml", xml_only),
        patch.object(PMCArticlePageClient, "fetch_article_document", page_reads),
    ):
        snapshot = fulltext_runtime.prefetch_search_fulltext(articles)
        for _ in range(200):
            if len(prefetched) == 3:
                break
            await asyncio.sleep(0.01)
        await runtime.fulltext_cache.aclose()
        await runtime.article_page_cache.aclose()

    assert [row["status"] for row in snapshot["articles"]] == ["scheduled"] * 3
    assert sorted(prefetched) == ["PMC700000", "PMC700001", "PMC700002"]
    page_reads.assert_not_awaited()


async def test_article_page_waits_for_an_xml_failure_rather_than_the_hedge_delay() -> None:
    async def slow_body(_: str) -> str:
        await asyncio.sleep(0.2)
        return (
            '<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta><title-group>'
            "<article-title>Slow but fine</article-title></title-group></article-meta></front>"
            "<body><sec><title>Results</title><p>Europe PMC body.</p></sec></body></article>"
        )

    page_fetcher = AsyncMock(side_effect=AssertionError("must not start while Europe PMC is still working"))
    europe = MagicMock()
    europe.parse_fulltext_xml = lambda xml: parse_jats_article(xml, source="Europe PMC")
    service = FulltextService(
        europe_pmc_client_factory=lambda: europe,
        unpaywall_client_factory=AsyncMock,
        core_client_factory=MagicMock(side_effect=AssertionError("CORE must not run")),
        downloader_factory=_no_text_downloader,
        structured_xml_fetcher=slow_body,
        article_page_fetcher=page_fetcher,
        deadline_seconds=30.0,
        structured_hedge_seconds=0.01,
    )
    result = await service.retrieve(FulltextRequest(pmcid=FIXTURE_PMCID, explicit_article_read=True))

    page_fetcher.assert_not_awaited()
    assert result.sources_tried[0] == "europe_pmc"
    assert "pmc_html" not in result.sources_tried
    assert result.fulltext_source_name == "Europe PMC"


async def test_front_matter_answer_starts_the_page_without_waiting_for_a_slow_europe_pmc() -> None:
    europe_cancelled = asyncio.Event()

    async def hanging(_: str) -> str:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            europe_cancelled.set()
            raise
        return ""

    page_fetcher = AsyncMock(return_value=_page_document())
    ncbi = await _ncbi_restricted()
    try:
        service = _service(structured_xml_fetcher=hanging, ncbi=ncbi, page_fetcher=page_fetcher, hedge_seconds=0.01)
        result = await asyncio.wait_for(
            service.retrieve(FulltextRequest(pmcid=FIXTURE_PMCID, explicit_article_read=True)), timeout=10
        )
    finally:
        await ncbi.close()

    assert europe_cancelled.is_set()
    assert ("europe_pmc", "superseded") in [(notice.source, notice.code) for notice in result.source_notices]
    assert result.fulltext_source_name == "PMC article page (HTML)"


async def test_article_page_failure_is_reported_and_the_plan_offers_a_host_fetch() -> None:
    page_fetcher = AsyncMock(
        side_effect=RetryableOperationError("PMC article page request failed", status_code=429, retry_after=5)
    )
    ncbi = await _ncbi_restricted()
    try:
        service = _service(structured_xml_fetcher=_failing_europe_pmc(), ncbi=ncbi, page_fetcher=page_fetcher)
        result = await service.retrieve(FulltextRequest(pmcid=FIXTURE_PMCID, explicit_article_read=True))
    finally:
        await ncbi.close()

    page_error = next(error for error in result.source_errors if error.source == "pmc_html")
    assert (page_error.code, page_error.retry_after) == ("rate_limited", 5.0)
    steps = [step["step"] for step in result.fulltext_plan]
    assert steps[0] == "retry_later"
    assert result.fulltext_plan[0]["retry_after_seconds"] == 5.0
    host_fetch = result.fulltext_plan[1]
    assert host_fetch["step"] == "host_fetch"
    assert "front matter only" in host_fetch["why"]
    assert host_fetch["register_with"]["tool"] == "register_fulltext"
    assert "bulk" in host_fetch["legal"]


async def test_page_without_body_is_a_notice_not_fulltext() -> None:
    page_fetcher = AsyncMock(return_value=_page_document(PMC_ARTICLE_PAGE_WITHOUT_BODY))
    service = _service(structured_xml_fetcher=_failing_europe_pmc(), ncbi=None, page_fetcher=page_fetcher)
    result = await service.retrieve(FulltextRequest(pmcid=FIXTURE_PMCID, explicit_article_read=True))

    assert ("pmc_html", "no_body") in [(notice.source, notice.code) for notice in result.source_notices]
    assert not result.has_retrieved_text
    # The page itself has no body, so the plan does not send the agent back to it.
    assert all(
        step.get("url") != f"https://pmc.ncbi.nlm.nih.gov/articles/{FIXTURE_PMCID}/" for step in result.fulltext_plan
    )


# ----------------------------------------------------------------------------
# Tool: env switch and per-tenant cache
# ----------------------------------------------------------------------------


def _capture_tools() -> dict[str, Any]:
    tools: dict[str, Any] = {}
    mcp = MagicMock()
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
    register_europe_pmc_tools(mcp)
    return tools


@pytest.fixture
def hermetic_tool_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INSTITUTIONAL_DIRECT_FETCH", "false")
    monkeypatch.setenv("PUBMED_FULLTEXT_NCBI_PMC_FALLBACK", "false")
    europe = MagicMock()
    europe.get_fulltext_xml = AsyncMock(return_value=None)
    with (
        patch("pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client", return_value=europe),
        patch(
            "pubmed_search.infrastructure.sources.fulltext_download.FulltextDownloader",
            side_effect=_no_text_downloader,
        ),
        bind_tool_session_runtime(ToolSessionRuntime()),
    ):
        yield monkeypatch


async def test_tool_reads_the_page_once_and_reuses_it_from_the_tenant_cache(hermetic_tool_env) -> None:
    hermetic_tool_env.setenv("PUBMED_FULLTEXT_PMC_HTML", "true")
    page_client = MagicMock()
    page_client.fetch_article_document = AsyncMock(return_value=_page_document())
    get_fulltext = _capture_tools()["get_fulltext"]
    with patch("pubmed_search.infrastructure.sources.pmc_html.get_pmc_article_page_client", return_value=page_client):
        first = json.loads(
            await get_fulltext(source=PMCIDSource(kind="pmcid", value=FIXTURE_PMCID), output_format="json")
        )
        second = json.loads(
            await get_fulltext(
                source=PMCIDSource(kind="pmcid", value=FIXTURE_PMCID), sections="discussion", output_format="json"
            )
        )

    page_client.fetch_article_document.assert_awaited_once_with(FIXTURE_PMCID)
    assert first["fulltext_retrieval"]["source"] == "pmc_html"
    assert first["fulltext_origin"] == "provider"
    assert first["section_provenance"]["content"]["surfacing_source"] == "PMC article page (HTML)"
    assert first["fulltext_plan"] == []
    assert second["content_sections"] == [{"title": "Discussion", "content": "Synthetic discussion paragraph."}]


async def test_operator_can_disable_the_article_page(hermetic_tool_env) -> None:
    hermetic_tool_env.setenv("PUBMED_FULLTEXT_PMC_HTML", "false")
    page_client = MagicMock()
    page_client.fetch_article_document = AsyncMock(side_effect=AssertionError("disabled source ran"))
    get_fulltext = _capture_tools()["get_fulltext"]
    with patch("pubmed_search.infrastructure.sources.pmc_html.get_pmc_article_page_client", return_value=page_client):
        payload = json.loads(
            await get_fulltext(source=PMCIDSource(kind="pmcid", value=FIXTURE_PMCID), output_format="json")
        )
        markdown = await get_fulltext(source=PMCIDSource(kind="pmcid", value=FIXTURE_PMCID))

    page_client.fetch_article_document.assert_not_awaited()
    assert "pmc_html" not in payload["sources_tried"]
    host_fetch = next(step for step in payload["fulltext_plan"] if step["step"] == "host_fetch")
    assert "disabled on this server" in host_fetch["why"]
    assert host_fetch["tool_hint"].startswith("WebFetch")
    assert "## 🧭 Fulltext plan" in markdown
    assert "host\\_fetch" in markdown or "host_fetch" in markdown


@pytest.mark.integration
@pytest.mark.timeout(180)
async def test_live_engages_trial_body_is_read_from_the_pmc_article_page() -> None:
    """Opt-in: PMID 30721296 (ENGAGES, PMC6439616); NCBI XML is front matter only."""
    if not os.environ.get("NCBI_EMAIL"):
        pytest.skip("Set NCBI_EMAIL to the operator's NCBI contact address for live NCBI requests")
    tools = _capture_tools()
    with bind_tool_session_runtime(ToolSessionRuntime()):
        payload = json.loads(
            await tools["get_fulltext"](
                source=PMIDSource(kind="pmid", value="30721296"),
                # Body sections are flat (as in JATS): the primary outcome is its own subsection.
                sections="primary outcome",
                include_pdf_links=False,
                output_format="json",
            )
        )
    text = json.dumps(payload["content_sections"])
    surfacing = payload["section_provenance"].get("content", {}).get("surfacing_source")
    print(
        "live ENGAGES:",
        {
            "surfacing_source": surfacing,
            "sources_tried": payload["sources_tried"],
            "source_notices": [(row["source"], row["code"]) for row in payload["source_notices"]],
            "source_errors": [(row["source"], row["code"]) for row in payload["source_errors"]],
            "retrieval": payload["fulltext_retrieval"],
        },
    )
    assert payload["fulltext_available"] is True, payload["source_errors"]
    assert "157 of 604" in text
    assert "140 of 609" in text
