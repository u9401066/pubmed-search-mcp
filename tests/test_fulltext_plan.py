"""Contracts for ``fulltext_plan``: only applicable, permitted next steps, in order."""

from __future__ import annotations

import json
from typing import Any

import pytest

from pubmed_search.application.fulltext import FulltextRequest
from pubmed_search.application.fulltext.coverage import FulltextSourceError, make_notice
from pubmed_search.application.fulltext.plan import FulltextAccessContext, build_fulltext_plan
from pubmed_search.application.fulltext.sections import select_sections
from pubmed_search.application.fulltext.service import FulltextDownloadNotice, FulltextServiceResult

PMC_PAGE = "https://pmc.ncbi.nlm.nih.gov/articles/PMC6439616/"


def _result(**fields: Any) -> FulltextServiceResult:
    attempted = fields.pop("attempted", [])
    errors = fields.pop("errors", [])
    notices = fields.pop("notices", [])
    result = FulltextServiceResult(**fields)
    for source in attempted:
        result.record_source_attempted(source)
    for error in errors:
        result.record_source_error(error.source, error)
    for source, code in notices:
        result.record_source_notice(source, code)
    return result


def _steps(plan: list[dict[str, Any]]) -> list[str]:
    return [step["step"] for step in plan]


def test_engages_like_record_offers_the_public_pmc_page_then_user_routes() -> None:
    result = _result(
        pmid="30721296",
        pmcid="PMC6439616",
        doi="10.1001/jama.2018.22005",
        attempted=["europe_pmc", "ncbi_pmc", "pmc_html"],
        errors=[FulltextSourceError(source="pmc_html", code="invalid_response")],
        notices=[("ncbi_pmc", "front_matter_only")],
        pdf_links=[
            {
                "source": "PubMed Central (article page)",
                "url": PMC_PAGE,
                "type": "landing_page",
                "access": "free_to_read",
            }
        ],
    )

    plan, reason = build_fulltext_plan(result, FulltextRequest(pmid="30721296"), FulltextAccessContext(True))

    assert reason == "no_body"
    assert _steps(plan) == ["host_fetch", "expand_discovery", "zotero_attachment", "ask_user_for_pdf"]
    assert [step["order"] for step in plan] == [1, 2, 3, 4]
    host_fetch = plan[0]
    assert host_fetch["url"] == PMC_PAGE
    assert "front matter only" in host_fetch["why"]
    assert host_fetch["tool_hint"].startswith("WebFetch")
    arguments = host_fetch["register_with"]["arguments"]
    assert arguments["source"] == {"kind": "pmcid", "value": "PMC6439616"}
    assert arguments["provenance"]["source_url"] == PMC_PAGE
    assert "bulk" in host_fetch["legal"]
    assert plan[2]["lookup"] == {"doi": "10.1001/jama.2018.22005", "pmid": "30721296"}
    assert plan[2]["requires"] == "zotero-keeper MCP server"
    assert "shadow" in plan[3]["legal"]


def test_open_pdf_and_landing_pages_become_steps_but_licensed_links_do_not() -> None:
    result = _result(
        doi="10.1000/oa",
        attempted=["unpaywall"],
        pdf_links=[
            {
                "source": "Unpaywall (repository)",
                "url": "https://repo.example/a.pdf",
                "type": "pdf",
                "access": "green",
                "license": "cc-by",
            },
            {
                "source": "Unpaywall (publisher)",
                "url": "https://pub.example/a",
                "type": "landing_page",
                "access": "gold",
            },
            {
                "source": "Institutional",
                "url": "https://proxy.example/a",
                "type": "landing_page",
                "access": "institutional",
            },
            {
                "source": "Publisher",
                "url": "https://pub.example/paywalled.pdf",
                "type": "pdf",
                "access": "subscription",
            },
        ],
    )

    plan, _ = build_fulltext_plan(result, FulltextRequest(doi="10.1000/oa"), FulltextAccessContext())

    assert _steps(plan) == [
        "download_oa_pdf",
        "host_fetch",
        "expand_discovery",
        "zotero_attachment",
        "ask_user_for_pdf",
    ]
    assert plan[0]["url"] == "https://repo.example/a.pdf"
    assert plan[0]["license"] == "cc-by"
    assert "asset-aware-mcp ingest_documents" in plan[0]["then"]
    assert plan[0]["register_with"]["arguments"]["file_path"].startswith("<path")
    assert plan[1]["url"] == "https://pub.example/a"
    assert "proxy.example" not in json.dumps(plan)
    assert "paywalled" not in json.dumps(plan)


def test_transient_failures_come_first_with_the_longest_cooldown() -> None:
    result = _result(
        pmcid="PMC1",
        attempted=["europe_pmc", "ncbi_pmc"],
        errors=[
            FulltextSourceError(source="europe_pmc", code="rate_limited", retry_after=12.0),
            FulltextSourceError(source="ncbi_pmc", code="timeout"),
        ],
    )
    result.record_source_skipped("pdf_retrieval_fallback")

    plan, _ = build_fulltext_plan(result, FulltextRequest(pmcid="PMC1"), FulltextAccessContext(True))

    assert plan[0]["step"] == "retry_later"
    assert plan[0]["retry_after_seconds"] == 12.0
    assert plan[0]["sources"] == ["europe_pmc", "ncbi_pmc", "pdf_retrieval_fallback"]
    assert "no XML source returned a body" in plan[1]["why"]


@pytest.mark.parametrize(
    ("context", "request_kwargs", "via", "hint"),
    [
        (FulltextAccessContext(openurl_configured=True), {}, "configured OpenURL resolver", "get_institutional_link("),
        (
            FulltextAccessContext(browser_broker_configured=True),
            {},
            "browser broker",
            "allow_browser_session=true",
        ),
        (FulltextAccessContext(ezproxy_configured=True), {}, "EZproxy", None),
    ],
    ids=["openurl", "broker", "ezproxy"],
)
def test_institutional_step_only_when_access_is_configured(
    context: FulltextAccessContext, request_kwargs: dict[str, Any], via: str, hint: str | None
) -> None:
    result = _result(doi="10.1000/closed", attempted=["unpaywall"])

    plan, _ = build_fulltext_plan(result, FulltextRequest(doi="10.1000/closed", **request_kwargs), context)
    without, _ = build_fulltext_plan(result, FulltextRequest(doi="10.1000/closed"), FulltextAccessContext())

    institutional = next(step for step in plan if step["step"] == "institutional")
    assert via in institutional["via"]
    if hint:
        assert hint in institutional["tool_hint"]
    else:
        assert "tool_hint" not in institutional
    assert "institutional" not in _steps(without)


def test_records_without_a_pmcid_get_no_pmc_page_step() -> None:
    result = _result(doi="10.1000/x", attempted=["unpaywall"])

    plan, _ = build_fulltext_plan(result, FulltextRequest(doi="10.1000/x"), FulltextAccessContext(True))

    assert "pmc.ncbi" not in json.dumps(plan)


def test_extended_discovery_is_not_offered_twice() -> None:
    result = _result(doi="10.1000/x", attempted=["extended"], extended_sources_attempted=True)

    plan, _ = build_fulltext_plan(
        result, FulltextRequest(doi="10.1000/x", extended_sources=True), FulltextAccessContext()
    )

    assert "expand_discovery" not in _steps(plan)


def test_a_usable_body_needs_no_plan() -> None:
    parsed = {"sections": [{"title": "Results", "content": "Body."}]}
    result = _result(pmcid="PMC1", attempted=["europe_pmc"])
    result.section_selection = select_sections(parsed, None)
    result.fulltext_content = "### Results\n\nBody.\n\n"
    result.fulltext_provenance = "indirect"
    result.fulltext_origin = "provider"

    assert build_fulltext_plan(result, FulltextRequest(pmcid="PMC1"), FulltextAccessContext()) == ([], None)


def test_text_extracted_from_a_pdf_gets_a_citation_ready_ingest_step() -> None:
    result = _result(doi="10.1000/x", attempted=["pdf_retrieval_fallback"])
    result.fulltext_content = "flat pdf text"
    result.fulltext_provenance = "derived"
    result.fulltext_origin = "provider"
    result.fallback_notice = FulltextDownloadNotice(
        source="unpaywall",
        source_name="Unpaywall",
        retrieved_url="https://repo.example/a.pdf",
        has_text=True,
        error=False,
    )

    plan, reason = build_fulltext_plan(result, FulltextRequest(doi="10.1000/x"), FulltextAccessContext())

    assert reason == "unstructured_text"
    assert _steps(plan) == ["download_oa_pdf"]
    assert plan[0]["url"] == "https://repo.example/a.pdf"
    assert "asset-aware-mcp" in plan[0]["then"]


def test_supplied_text_is_never_planned_over() -> None:
    result = _result(
        pmid="1", attempted=["registered_fulltext"], notices=[("registered_fulltext", "supplied_not_verified")]
    )
    result.fulltext_content = "supplied"
    result.fulltext_provenance = "derived"
    result.fulltext_origin = "user_supplied"

    assert build_fulltext_plan(result, FulltextRequest(pmid="1"), FulltextAccessContext()) == ([], None)
    assert make_notice("registered_fulltext", "supplied_not_verified").message.startswith("Served text registered")
