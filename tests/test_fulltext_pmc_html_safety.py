"""Regression tests for the v0.12.0 review of the server-fetched PMC page (``pmc_html``).

Built from the review's reproductions (scratchpad repro r5, r8, r10, r12):
linear-time HTML parsing on the provider path (H1), the per-process and
per-tenant hourly page budgets and the contact-address requirement (M6),
CAPTCHA detection and 403 handling (L1), the declared-article check without a
canonical tag (L2), off-NCBI redirects (L3), layout drift (L4), and a cooldown
applied while a read waits for the limiter (L6).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from pubmed_search.application.fulltext import FulltextRequest, FulltextService
from pubmed_search.application.fulltext.coverage import classify_source_failure
from pubmed_search.infrastructure.sources import pmc_html
from pubmed_search.infrastructure.sources.base_client import ProviderSchemaError
from pubmed_search.infrastructure.sources.fulltext_download import FulltextResult, PDFLinkDiscoveryResult
from pubmed_search.infrastructure.sources.pmc_html import (
    PageVolumeBudget,
    PMCArticlePageClient,
    is_bot_challenge,
    is_configured_contact,
    parse_article_html,
    parse_pmc_article_html,
)
from pubmed_search.shared.async_utils import get_rate_limiter
from pubmed_search.shared.exceptions import RateLimitError
from pubmed_search.shared.tenancy import TenantIdentity, bind_tenant
from tests.fixtures.pmc_html import (
    ABSTRACT_ONLY_BODY,
    FIXTURE_PMCID,
    PMC_ARTICLE_PAGE,
    pmc_article_page,
)

if TYPE_CHECKING:
    from collections.abc import Callable

PAGE_URL = f"https://pmc.ncbi.nlm.nih.gov/articles/{FIXTURE_PMCID}/"


async def _public_resolver(_host: str, _port: int) -> tuple[str, ...]:
    return ("130.14.29.110",)


def _client(
    handler: Callable[[httpx.Request], httpx.Response], *, budget: PageVolumeBudget | None = None
) -> tuple[PMCArticlePageClient, httpx.AsyncClient]:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = PMCArticlePageClient(
        email="ops@example.org",
        client=http,
        resolver=_public_resolver,
        clock=lambda: "2026-11-25T08:00:00Z",
        budget=budget or PageVolumeBudget(process_per_hour=1_000, tenant_per_hour=1_000),
    )
    return client, http


def _html_response(text: str = PMC_ARTICLE_PAGE, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=text, headers={"Content-Type": "text/html; charset=utf-8"})


# ----------------------------------------------------------------------------
# H1: the provider-path parser is linear and bounded
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "<div>" * 50_000 + "</b>" * 50_000,
        "<p>x</p>" + "</b>" * 200_000,
        "<section>" * 20_000,
        "<span>x</span>" * 120_000,
    ],
    ids=["deep-stray", "stray-only", "deep-sections", "node-flood"],
)
def test_crafted_pages_parse_or_fail_typed_in_well_under_a_second(body: str) -> None:
    html = f'<html><head><link rel="canonical" href="{PAGE_URL}"></head><body><article>{body}</article></body></html>'
    started = time.perf_counter()
    try:
        parse_pmc_article_html(html, pmcid=FIXTURE_PMCID)
    except ProviderSchemaError:
        pass
    assert time.perf_counter() - started < 1.0


# ----------------------------------------------------------------------------
# M6: hourly volume budgets and a real contact address
# ----------------------------------------------------------------------------


async def test_tenant_and_process_hourly_budgets_stop_page_reads_with_rate_limited() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _html_response()

    now = [0.0]
    budget = PageVolumeBudget(process_per_hour=3, tenant_per_hour=2, clock=lambda: now[0])
    client, http = _client(handler, budget=budget)
    outcomes: list[str] = []
    try:
        for tenant in ("alice", "alice", "alice", "bob", "carol"):
            with bind_tenant(TenantIdentity.for_principal(tenant)):
                try:
                    await client.fetch_article_document(FIXTURE_PMCID)
                    outcomes.append("read")
                except RateLimitError as exc:
                    failure = classify_source_failure("pmc_html", exc)
                    assert failure.code == "rate_limited"
                    assert failure.retry_after is not None and 0 < failure.retry_after <= 3_600
                    outcomes.append("budget")
                await asyncio.sleep(0)
            # Keep the 1 request/s limiter out of the way of this budget test.
            get_rate_limiter(pmc_html.PMC_HTML_RATE_LIMIT, rate=1.0, per=1.0).defer(0.0)
        now[0] = 3_601.0
        with bind_tenant(TenantIdentity.for_principal("alice")):
            await client.fetch_article_document(FIXTURE_PMCID)
    finally:
        await http.aclose()

    assert outcomes == ["read", "read", "budget", "read", "budget"]
    assert calls == 4


def test_placeholder_contact_addresses_are_not_a_configuration() -> None:
    assert not is_configured_contact(None)
    assert not is_configured_contact("")
    assert not is_configured_contact("pubmed-search@example.com")
    assert not is_configured_contact("pubmed-search-mcp@example.com")
    assert is_configured_contact("ops@university.edu")
    with pytest.raises(ValueError, match="contact"):
        PMCArticlePageClient(email="pubmed-search@example.com")


def _downloader() -> MagicMock:
    downloader = MagicMock()
    downloader.get_fulltext = AsyncMock(
        return_value=FulltextResult(link_discovery=PDFLinkDiscoveryResult(), error="No PDF links found")
    )
    downloader.close = AsyncMock()
    return downloader


async def test_without_a_contact_address_the_page_is_skipped_as_not_configured() -> None:
    service = FulltextService(
        europe_pmc_client_factory=MagicMock,
        unpaywall_client_factory=AsyncMock,
        core_client_factory=MagicMock,
        downloader_factory=_downloader,
        structured_xml_fetcher=AsyncMock(return_value=None),
        article_page_fetcher=None,
        article_page_unavailable="not_configured",
        deadline_seconds=30.0,
    )
    result = await service.retrieve(FulltextRequest(pmcid=FIXTURE_PMCID, explicit_article_read=True))

    assert "pmc_html" not in result.sources_tried
    assert [(row.source, row.reason) for row in result.sources_skipped] == [("pmc_html", "not_configured")]
    host_fetch = next(step for step in result.fulltext_plan if step["step"] == "host_fetch")
    assert "NCBI_EMAIL" in host_fetch["why"]


# ----------------------------------------------------------------------------
# L1: CAPTCHA detection and 403 handling
# ----------------------------------------------------------------------------


def test_a_real_page_with_a_large_head_and_a_marker_phrase_is_not_a_challenge() -> None:
    legit = PMC_ARTICLE_PAGE.replace(
        '<meta name="citation_title" content="Guided anesthesia fixture trial">',
        '<meta name="citation_title" content="Making sure you are heard: patient voice after anaesthesia">'
        "<script>" + ("/*pad*/" * 3_000) + "</script>",
    )
    assert legit.find("<article") > 20_000
    assert is_bot_challenge(legit) is False


async def test_a_403_block_applies_a_cooldown_so_later_reads_fail_fast() -> None:
    hits = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal hits
        hits += 1
        return _html_response("<html>Access denied</html>", status=403)

    client, http = _client(handler)
    try:
        with pytest.raises(Exception) as first:
            await client.fetch_article_document(FIXTURE_PMCID)
        with pytest.raises(RateLimitError):
            await client.fetch_article_document(FIXTURE_PMCID)
    finally:
        await http.aclose()

    assert classify_source_failure("pmc_html", first.value).code == "upstream_http_error"
    assert hits == 1


# ----------------------------------------------------------------------------
# L2: the page must declare which article it is
# ----------------------------------------------------------------------------


def _without_canonical(html: str) -> str:
    head, rest = html.split('<link rel="canonical"', 1)
    return head + rest.split(">", 1)[1]


def test_a_page_without_canonical_falls_back_to_declared_urls_and_is_still_checked() -> None:
    page = _without_canonical(PMC_ARTICLE_PAGE)
    assert parse_pmc_article_html(page, pmcid=FIXTURE_PMCID)["pmcid"] == FIXTURE_PMCID
    with pytest.raises(ProviderSchemaError):
        parse_pmc_article_html(page, pmcid="PMC9999999")


def test_a_page_declaring_nothing_is_only_accepted_by_its_final_url() -> None:
    page = _without_canonical(PMC_ARTICLE_PAGE).replace("citation_fulltext_html_url", "x-unrelated")
    with pytest.raises(ProviderSchemaError):
        parse_pmc_article_html(page, pmcid=FIXTURE_PMCID)
    assert parse_pmc_article_html(page, pmcid=FIXTURE_PMCID, page_url=PAGE_URL)["pmcid"] == FIXTURE_PMCID
    with pytest.raises(ProviderSchemaError):
        parse_pmc_article_html(page, pmcid="PMC9999999", page_url=PAGE_URL)


async def test_a_page_whose_pmid_contradicts_the_request_is_not_served() -> None:
    parsed = parse_pmc_article_html(PMC_ARTICLE_PAGE, pmcid=FIXTURE_PMCID)
    parsed.update({"source": "pmc_html", "url": PAGE_URL, "retrieved_at": "2026-11-25T08:00:00Z"})
    europe = MagicMock()
    europe.get_article = AsyncMock(return_value={"pmc_id": FIXTURE_PMCID})
    service = FulltextService(
        europe_pmc_client_factory=lambda: europe,
        unpaywall_client_factory=AsyncMock,
        core_client_factory=MagicMock,
        downloader_factory=_downloader,
        structured_xml_fetcher=AsyncMock(return_value=None),
        article_page_fetcher=AsyncMock(return_value=json.dumps(parsed)),
        deadline_seconds=30.0,
    )
    # The request names PMID 11111111, which resolves to the page's PMCID, but
    # the page itself declares citation_pmid 39000001.
    result = await service.retrieve(FulltextRequest(pmid="11111111", explicit_article_read=True))

    assert not result.has_retrieved_text
    assert ("pmc_html", "invalid_response") in [(error.source, error.code) for error in result.source_errors]


# ----------------------------------------------------------------------------
# L3: redirects stay on NCBI, checked before any status handling
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("status", [404, 429, 200])
async def test_a_redirect_off_ncbi_is_refused_before_its_status_is_used(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "pmc.ncbi.nlm.nih.gov":
            return httpx.Response(302, headers={"Location": "https://evilncbi.nlm.nih.gov.example.org/x"})
        return _html_response(status=status)

    client, http = _client(handler)
    try:
        with pytest.raises(ProviderSchemaError):
            await client.fetch_article_document(FIXTURE_PMCID)
    finally:
        await http.aclose()
    limiter = get_rate_limiter(pmc_html.PMC_HTML_RATE_LIMIT, rate=1.0, per=1.0, conservative=True)
    assert limiter.cooldown_remaining() == 0.0


# ----------------------------------------------------------------------------
# L4: layout drift is an error that keeps the host_fetch plan step
# ----------------------------------------------------------------------------


def test_layout_drift_is_reported_instead_of_silently_returning_no_body(caplog) -> None:
    drifted = PMC_ARTICLE_PAGE.replace("main-article-body", "article-body-v2").replace(
        'class="body ', 'class="content '
    )
    with pytest.raises(ProviderSchemaError):
        parse_pmc_article_html(drifted, pmcid=FIXTURE_PMCID)
    assert any("layout" in record.getMessage() for record in caplog.records)


async def test_plan_keeps_host_fetch_after_drift_and_offers_the_pdf_for_a_pdf_only_page() -> None:
    drift = AsyncMock(side_effect=ProviderSchemaError("PMC article page"))
    pdf_only = parse_pmc_article_html(
        pmc_article_page(body=ABSTRACT_ONLY_BODY, pdf_url=f"{PAGE_URL}pdf/scan.pdf"), pmcid=FIXTURE_PMCID
    )
    pdf_only.update({"source": "pmc_html", "url": PAGE_URL, "retrieved_at": "2026-11-25T08:00:00Z"})

    def service(fetcher: AsyncMock) -> FulltextService:
        return FulltextService(
            europe_pmc_client_factory=MagicMock,
            unpaywall_client_factory=AsyncMock,
            core_client_factory=MagicMock,
            downloader_factory=_downloader,
            structured_xml_fetcher=AsyncMock(return_value=None),
            article_page_fetcher=fetcher,
            deadline_seconds=30.0,
        )

    drifted = await service(drift).retrieve(FulltextRequest(pmcid=FIXTURE_PMCID, explicit_article_read=True))
    scanned = await service(AsyncMock(return_value=json.dumps(pdf_only))).retrieve(
        FulltextRequest(pmcid=FIXTURE_PMCID, explicit_article_read=True)
    )

    assert any(step["step"] == "host_fetch" and step["url"] == PAGE_URL for step in drifted.fulltext_plan)
    assert ("pmc_html", "pdf_only") in [(notice.source, notice.code) for notice in scanned.source_notices]
    assert not any(step["step"] == "host_fetch" and step.get("url") == PAGE_URL for step in scanned.fulltext_plan)
    pdf_step = next(step for step in scanned.fulltext_plan if step.get("url", "").endswith("scan.pdf"))
    assert pdf_step["step"] == "download_pdf"
    assert "Open-access" not in pdf_step["legal"]


# ----------------------------------------------------------------------------
# L6: a cooldown applied while waiting for the limiter surfaces as rate_limited
# ----------------------------------------------------------------------------


async def test_a_cooldown_applied_while_waiting_fails_fast_as_rate_limited() -> None:
    client, http = _client(lambda request: _html_response())
    limiter = get_rate_limiter(pmc_html.PMC_HTML_RATE_LIMIT, rate=1.0, per=1.0, conservative=True)
    try:
        await client.fetch_article_document(FIXTURE_PMCID)  # spends the only token
        waiting = asyncio.create_task(client.fetch_article_document(FIXTURE_PMCID))
        await asyncio.sleep(0.05)
        limiter.defer(300.0)
        started = time.perf_counter()
        with pytest.raises(RateLimitError) as caught:
            await asyncio.wait_for(waiting, timeout=10)
    finally:
        await http.aclose()

    assert time.perf_counter() - started < 6.0
    assert classify_source_failure("pmc_html", caught.value).code == "rate_limited"


# ----------------------------------------------------------------------------
# L14: generic HTML keeps sections whose class or id merely contains a chrome word
# ----------------------------------------------------------------------------


def test_generic_html_matches_chrome_words_as_whole_tokens() -> None:
    html = """<html><body><article><h1>T</h1>
<section id="sec-results"><h2>Results</h2><p>Primary outcome 11 of 100.</p></section>
<section class="shared-decision-making"><h2>Shared decision making</h2><p>Body text A.</p></section>
<section id="data-unavailable"><h2>Missing data</h2><p>Body text B.</p></section>
<div class="share-tools"><p>Share this</p></div><nav class="site-nav"><p>Menu</p></nav>
</article></body></html>"""
    titles = [section["title"] for section in parse_article_html(html)["sections"]]
    assert titles == ["Results", "Shared decision making", "Missing data"]


# ----------------------------------------------------------------------------
# Architecture: only the explicit get_fulltext tool wires the article page
# ----------------------------------------------------------------------------


def test_only_get_fulltext_wires_the_article_page_and_the_explicit_flag() -> None:
    from pathlib import Path

    package = Path(pmc_html.__file__).resolve().parents[2]
    wiring = {
        marker: sorted(
            path.relative_to(package).as_posix()
            for path in package.rglob("*.py")
            if marker in path.read_text(encoding="utf-8")
        )
        for marker in ("article_page_fetcher=", "explicit_article_read=True", "fetch_article_document")
    }

    assert wiring["article_page_fetcher="] == ["presentation/mcp_server/tools/europe_pmc.py"]
    assert wiring["explicit_article_read=True"] == ["presentation/mcp_server/tools/europe_pmc.py"]
    assert wiring["fetch_article_document"] == [
        "infrastructure/sources/pmc_html.py",
        "presentation/mcp_server/tools/europe_pmc.py",
    ]
