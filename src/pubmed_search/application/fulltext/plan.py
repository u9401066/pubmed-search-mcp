"""Machine-readable next steps when ``get_fulltext`` could not return a usable body.

Design:
    The server does not have every access route a host agent has. A host
    agent (Claude Code, Copilot, Cline, Codex) usually has its own web fetch
    tool, may drive a browser in the user's signed-in session, and may be
    connected to other MCP servers such as asset-aware-mcp (citation-ready PDF
    ingestion) or Zotero Keeper (the user's own library). Instead of returning
    only links, ``get_fulltext`` returns an ordered plan the agent can execute
    with those tools, ending with ``register_fulltext`` so later reads reuse
    the text.

    Only steps that apply to this record are emitted: a PMC page step needs a
    PMCID, an OA PDF step needs a located OA PDF, institutional steps need a
    configured resolver, EZproxy or browser broker, and so on. Every step says
    why it applies and what use is permitted. The plan never suggests bulk or
    systematic download, shadow libraries, or reuse beyond the user's rights.

Maintenance:
    Pure function of the service result; no I/O, no infrastructure imports.
    Step kinds are a closed vocabulary that skills and docs reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .service import FulltextRequest, FulltextServiceResult

PlanStepKind = Literal[
    "retry_later",
    "host_fetch",
    "download_oa_pdf",
    "expand_discovery",
    "institutional",
    "zotero_attachment",
    "ask_user_for_pdf",
]
PlanReason = Literal["no_body", "unstructured_text"]

_TRANSIENT_CODES = frozenset(
    {
        "rate_limited",
        "upstream_retries_exhausted",
        "upstream_connection_error",
        "timeout",
        "deadline_exceeded",
        "cache_error",
    }
)
_OA_ACCESS = frozenset({"gold", "green", "hybrid", "bronze", "open_access", "free_to_read", "alternative"})
_NOT_OA_ACCESS = frozenset({"subscription", "institutional", "closed"})
_PMC_PAGE = "https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
_MAX_PDF_STEPS = 3
_MAX_LANDING_STEPS = 2

LEGAL_INDIVIDUAL_PAGE = (
    "Individual reading of one public article page for this request. Do not crawl, batch, mirror or "
    "systematically download PMC or publisher sites (NCBI prohibits bulk download from the PMC website)."
)
LEGAL_OA_COPY = "Open-access copy; keep its declared license and attribution with any quotation or reuse."
LEGAL_INSTITUTIONAL = (
    "Uses the user's or operator's own institutional entitlement in their own session; keep licensed text "
    "within that license and do not redistribute it."
)
LEGAL_USER_COPY = (
    "Use only a copy the user is entitled to (own library, institutional access, author-shared). Never use "
    "unauthorized copies such as shadow-library downloads."
)


@dataclass(frozen=True)
class FulltextAccessContext:
    """Access routes configured for this server and request (not secrets)."""

    article_page_enabled: bool = False
    openurl_configured: bool = False
    ezproxy_configured: bool = False
    browser_broker_configured: bool = False


def _source_argument(request: FulltextRequest, result: FulltextServiceResult) -> dict[str, str]:
    for kind in ("pmcid", "pmid", "doi"):
        value = getattr(result, kind, None) or getattr(request, kind, None)
        if value:
            return {"kind": kind, "value": str(value)}
    return {"kind": "pmid", "value": ""}


def _source_literal(source: dict[str, str]) -> str:
    return f'{{"kind":"{source["kind"]}","value":"{source["value"]}"}}'


def _register_skeleton(
    source: dict[str, str],
    *,
    retrieval_method: str,
    source_url: str | None = None,
    supplied_by: str = "agent",
    content_format: str | None = "markdown",
    file_path: bool = False,
) -> dict[str, Any]:
    provenance: dict[str, Any] = {
        "retrieval_method": retrieval_method,
        "retrieved_at": "<ISO-8601 time of your fetch>",
    }
    if source_url:
        provenance["source_url"] = source_url
    arguments: dict[str, Any] = {"source": dict(source), "supplied_by": supplied_by, "provenance": provenance}
    if file_path:
        arguments["file_path"] = "<path to the PDF inside an allowed intake directory>"
    else:
        arguments["content"] = "<verbatim article text>"
        arguments["content_format"] = content_format
    return {"tool": "register_fulltext", "arguments": arguments}


def _transient_step(result: FulltextServiceResult, source: dict[str, str]) -> dict[str, Any] | None:
    transient = [error for error in result.source_errors if error.code in _TRANSIENT_CODES]
    if not transient and not result.sources_skipped:
        return None
    retry_after = max((error.retry_after for error in transient if error.retry_after is not None), default=None)
    affected = [error.source for error in transient] + [skipped.source for skipped in result.sources_skipped]
    step: dict[str, Any] = {
        "step": "retry_later",
        "why": (
            "Some sources failed transiently or were not reached before the deadline, so absence of "
            "fulltext is not established."
        ),
        "sources": list(dict.fromkeys(affected)),
        "tool_hint": f"get_fulltext(source={_source_literal(source)})",
        "legal": "Retry this one article only, after any cooldown; do not loop or batch retries.",
    }
    if retry_after is not None:
        step["retry_after_seconds"] = retry_after
    return step


def _pmc_page_step(
    result: FulltextServiceResult, source: dict[str, str], context: FulltextAccessContext
) -> dict[str, Any] | None:
    if not result.pmcid:
        return None
    notices = {(notice.source, notice.code) for notice in result.source_notices}
    page_errors = [error for error in result.source_errors if error.source == "pmc_html"]
    if ("pmc_html", "no_body") in notices:
        # The page itself has no body text (for example a scanned, PDF-only record).
        return None
    if ("ncbi_pmc", "front_matter_only") in notices:
        why = "The publisher restricts PMC XML reuse (front matter only), but the PMC article page is public."
    elif page_errors:
        why = f"The server could not read the PMC article page this time ({page_errors[0].code})."
    elif any(skipped.source == "pmc_html" for skipped in result.sources_skipped):
        why = "The PMC article page was not reached before the get_fulltext deadline."
    elif not context.article_page_enabled:
        why = "The article is in PMC; server-side reading of its public page is disabled on this server."
    else:
        why = "The article is in PMC, but no XML source returned a body; its public article page can be read."
    url = _PMC_PAGE.format(pmcid=result.pmcid)
    return {
        "step": "host_fetch",
        "url": url,
        "why": why,
        "access": "free_to_read",
        "tool_hint": "WebFetch (ask for the verbatim article text, not a summary)",
        "then": "register_fulltext with retrieval_method='host_fetch' so later reads reuse the text",
        "register_with": _register_skeleton(source, retrieval_method="host_fetch", source_url=url),
        "legal": LEGAL_INDIVIDUAL_PAGE,
    }


def _link_steps(result: FulltextServiceResult, source: dict[str, str]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    pdf_count = 0
    landing_count = 0
    pmc_page = _PMC_PAGE.format(pmcid=result.pmcid) if result.pmcid else None
    for link in result.pdf_links:
        url = str(link.get("url") or "")
        access = str(link.get("access") or "")
        if not url or access in _NOT_OA_ACCESS or url == pmc_page:
            continue
        label = str(link.get("source") or "a discovery source")
        license_value = link.get("license")
        if link.get("type") == "pdf" and pdf_count < _MAX_PDF_STEPS:
            pdf_count += 1
            step: dict[str, Any] = {
                "step": "download_oa_pdf",
                "url": url,
                "why": f"An open PDF was located by {label} ({access or 'access unspecified'}).",
                "access": access or None,
                "tool_hint": "the host's download tool (save inside an allowed intake directory)",
                "then": (
                    "asset-aware-mcp ingest_documents for citation-ready spans, then register_fulltext(file_path=...) "
                    "so get_fulltext, notes and Chronicle reuse it"
                ),
                "register_with": _register_skeleton(
                    source, retrieval_method="host_fetch", source_url=url, file_path=True
                ),
                "legal": LEGAL_OA_COPY,
            }
            if license_value:
                step["license"] = license_value
            steps.append({key: value for key, value in step.items() if value is not None})
        elif link.get("type") != "pdf" and access in _OA_ACCESS and landing_count < _MAX_LANDING_STEPS:
            landing_count += 1
            steps.append(
                {
                    "step": "host_fetch",
                    "url": url,
                    "why": f"An open landing page was located by {label} ({access}).",
                    "access": access,
                    "tool_hint": "WebFetch (ask for the verbatim article text, not a summary)",
                    "then": "register_fulltext with retrieval_method='host_fetch'",
                    "register_with": _register_skeleton(source, retrieval_method="host_fetch", source_url=url),
                    "legal": LEGAL_INDIVIDUAL_PAGE,
                }
            )
    return steps


def _institutional_step(
    result: FulltextServiceResult, request: FulltextRequest, source: dict[str, str], context: FulltextAccessContext
) -> dict[str, Any] | None:
    if not (result.doi or result.pmid):
        return None
    via: list[str] = []
    hints: list[str] = []
    if context.openurl_configured:
        via.append("configured OpenURL resolver")
        hints.append(f"get_institutional_link(source={_source_literal(source)})")
    if context.ezproxy_configured:
        via.append("EZproxy")
    if context.browser_broker_configured:
        via.append("browser broker (operator's signed-in session)")
        if request.allow_browser_session is not True:
            hints.append(f"get_fulltext(source={_source_literal(source)}, allow_browser_session=true)")
    if not via:
        return None
    return {
        "step": "institutional",
        "via": " / ".join(via),
        "why": "This server has institutional access configured; the library may license this article.",
        "tool_hint": "; ".join(hints) or None,
        "then": "If the host browser opens the licensed copy in the user's own session, register_fulltext "
        "with retrieval_method='host_browser'",
        "legal": LEGAL_INSTITUTIONAL,
    }


def build_fulltext_plan(
    result: FulltextServiceResult,
    request: FulltextRequest,
    context: FulltextAccessContext,
) -> tuple[list[dict[str, Any]], PlanReason | None]:
    """Return ordered next steps and the reason a plan was produced.

    A plan is produced when no usable body was obtained (``no_body``), or
    when the only body is text extracted from a PDF without structure or
    locators (``unstructured_text``). Otherwise the plan is empty.
    """
    source = _source_argument(request, result)
    if result.has_retrieved_text:
        if result.fulltext_provenance != "derived" or result.fulltext_origin != "provider":
            return [], None
        pdf_url = result.fallback_notice.retrieved_url if result.fallback_notice else None
        pdf_url = pdf_url or next((str(link["url"]) for link in result.pdf_links if link.get("type") == "pdf"), None)
        if not pdf_url:
            return [], None
        return [
            {
                "order": 1,
                "step": "download_oa_pdf",
                "url": pdf_url,
                "why": "The returned text was extracted from this PDF without sections or page locators.",
                "tool_hint": "the host's download tool",
                "then": "asset-aware-mcp ingest_documents (or parse_pdf_structure) for citation-ready spans",
                "legal": LEGAL_OA_COPY,
            }
        ], "unstructured_text"

    steps: list[dict[str, Any]] = []
    transient = _transient_step(result, source)
    if transient is not None:
        steps.append(transient)
    page = _pmc_page_step(result, source, context)
    if page is not None:
        steps.append(page)
    steps.extend(_link_steps(result, source))
    if not result.extended_sources_attempted and (result.doi or result.pmid):
        steps.append(
            {
                "step": "expand_discovery",
                "why": "Extended open-access discovery (CrossRef, DOAJ, Zenodo, OpenAlex, Semantic Scholar, "
                "preprint servers) was not run for this request.",
                "tool_hint": f"get_fulltext(source={_source_literal(source)}, extended_sources=true)",
                "legal": "Server-side discovery of open copies for this one article.",
            }
        )
    institutional = _institutional_step(result, request, source, context)
    if institutional is not None:
        steps.append({key: value for key, value in institutional.items() if value is not None})
    if result.doi or result.pmid:
        lookup = {kind: value for kind in ("doi", "pmid") if (value := getattr(result, kind, None))}
        steps.append(
            {
                "step": "zotero_attachment",
                "via": "zotero-keeper check_articles_owned",
                "requires": "zotero-keeper MCP server",
                "lookup": lookup,
                "why": "The user's own Zotero library may already hold a PDF of this article.",
                "then": "register_fulltext(file_path=<attachment>, supplied_by='user', "
                "provenance.retrieval_method='zotero_attachment')",
                "register_with": _register_skeleton(
                    source, retrieval_method="zotero_attachment", supplied_by="user", file_path=True
                ),
                "legal": LEGAL_USER_COPY,
            }
        )
    steps.append(
        {
            "step": "ask_user_for_pdf",
            "why": "If no route above yields the text, the user may have or obtain an entitled copy.",
            "then": "register_fulltext(file_path=<PDF>, supplied_by='user', provenance.retrieval_method='user_upload'); "
            "for citation-ready spans also ingest it with asset-aware-mcp",
            "register_with": _register_skeleton(
                source, retrieval_method="user_upload", supplied_by="user", file_path=True
            ),
            "legal": LEGAL_USER_COPY,
        }
    )
    return [{"order": index, **step} for index, step in enumerate(steps, start=1)], "no_body"


__all__ = [
    "FulltextAccessContext",
    "PlanReason",
    "PlanStepKind",
    "build_fulltext_plan",
]
