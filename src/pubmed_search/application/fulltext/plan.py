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
    PMCID, PDF and landing-page steps need located links, institutional steps
    need a configured resolver, EZproxy or browser broker, and so on. Every
    step says why it applies and what use is permitted. Open-access wording is
    used only for links whose access is verified as open; free-to-read,
    licensed and unknown-access links get their own step kinds and notes. The
    plan never suggests bulk or systematic download, shadow libraries, or
    reuse beyond the user's rights, and it only offers registration routes the
    caller can actually use.

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
    "download_pdf",
    "check_access",
    "expand_discovery",
    "institutional",
    "zotero_attachment",
    "ask_user_for_pdf",
]
PlanReason = Literal["no_body", "unstructured_text"]
AccessClass = Literal["open", "free_to_read", "licensed", "unknown"]

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
# Access values that are verified open access (Unpaywall/OpenAlex vocabulary; "alternative"
# rows are further Unpaywall OA locations). Anything else never gets open-access wording.
_OPEN_ACCESS = frozenset(
    {
        "gold",
        "green",
        "hybrid",
        "bronze",
        "diamond",
        "open_access",
        "gold_oa",
        "green_oa",
        "hybrid_oa",
        "bronze_oa",
        "diamond_oa",
        "alternative",
    }
)
_FREE_TO_READ = frozenset({"free_to_read"})
_LICENSED_ACCESS = frozenset({"subscription", "institutional", "closed", "browser_session"})
_PMC_PAGE = "https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
_MAX_PDF_STEPS = 3
_MAX_LANDING_STEPS = 2

LEGAL_INDIVIDUAL_PAGE = (
    "Individual reading of one public article page for this request. Do not crawl, batch, mirror or "
    "systematically download PMC or publisher sites (NCBI prohibits bulk download from the PMC website)."
)
LEGAL_OA_COPY = "Open-access copy; keep its declared license and attribution with any quotation or reuse."
LEGAL_FREE_TO_READ = (
    "Free to read on the host site for individual use; this is not necessarily an open license, so keep it to "
    "the user's own research and do not redistribute it."
)
LEGAL_INSTITUTIONAL = (
    "Uses the user's or operator's own institutional entitlement in their own session; keep licensed text "
    "within that license and do not redistribute it."
)
LEGAL_USER_COPY = (
    "Use only a copy the user is entitled to (own library, institutional access, author-shared). Never use "
    "unauthorized copies such as shadow-library downloads."
)
_NO_REGISTRATION = "read it in the host; this server cannot keep supplied text for this caller (no durable storage)"


@dataclass(frozen=True)
class FulltextAccessContext:
    """Access routes configured for this server and what this caller may do (not secrets)."""

    article_page_enabled: bool = False
    openurl_configured: bool = False
    ezproxy_configured: bool = False
    browser_broker_configured: bool = False
    registration_allowed: bool = True
    """The caller can keep text with ``register_fulltext`` (durable tenant storage)."""
    file_intake_allowed: bool = True
    """The caller may register server files (local callers only); otherwise only ``content``."""


def access_class(access: object) -> AccessClass:
    """Classify a link's declared access for plan wording."""
    value = str(access or "").strip().lower()
    if value in _OPEN_ACCESS:
        return "open"
    if value in _FREE_TO_READ:
        return "free_to_read"
    if value in _LICENSED_ACCESS:
        return "licensed"
    return "unknown"


def _source_argument(request: FulltextRequest, result: FulltextServiceResult) -> dict[str, str]:
    for kind in ("pmcid", "pmid", "doi"):
        value = getattr(result, kind, None) or getattr(request, kind, None)
        if value:
            return {"kind": kind, "value": str(value)}
    return {"kind": "pmid", "value": ""}


def _source_literal(source: dict[str, str]) -> str:
    return f'{{"kind":"{source["kind"]}","value":"{source["value"]}"}}'


class _Skeletons:
    """``register_with`` skeletons limited to what this caller can use."""

    def __init__(self, source: dict[str, str], context: FulltextAccessContext) -> None:
        self._source = source
        self._context = context

    def build(
        self,
        *,
        retrieval_method: str,
        source_url: str | None = None,
        supplied_by: str = "agent",
        file_path: bool = False,
    ) -> dict[str, Any] | None:
        if not self._context.registration_allowed:
            return None
        provenance: dict[str, Any] = {
            "retrieval_method": retrieval_method,
            "retrieved_at": "<ISO-8601 time of your fetch>",
        }
        if source_url:
            provenance["source_url"] = source_url
        arguments: dict[str, Any] = {"source": dict(self._source), "supplied_by": supplied_by, "provenance": provenance}
        if file_path and self._context.file_intake_allowed:
            arguments["file_path"] = "<path to the file inside an allowed intake directory>"
        else:
            if file_path:
                provenance.setdefault("source_file", "<file name>")
            arguments["content"] = (
                "<verbatim text extracted in the host, e.g. by asset-aware-mcp>"
                if file_path
                else "<verbatim article text>"
            )
            arguments["content_format"] = "markdown"
        return {"tool": "register_fulltext", "arguments": arguments}

    def then(self, text: str) -> str:
        """Next-action text, or the no-registration fallback for this caller."""
        if not self._context.registration_allowed:
            return _NO_REGISTRATION
        if not self._context.file_intake_allowed:
            # Remote callers cannot name server files; they send the extracted text instead.
            return text.replace("file_path=", "content=<verbatim text extracted in the host from ")
        return text


def _clean(step: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in step.items() if value is not None}


def _transient_step(result: FulltextServiceResult, source: dict[str, str]) -> dict[str, Any] | None:
    transient = [error for error in result.source_errors if error.code in _TRANSIENT_CODES]
    skipped = [row.source for row in result.sources_skipped if row.reason == "deadline"]
    if not transient and not skipped:
        return None
    retry_after = max((error.retry_after for error in transient if error.retry_after is not None), default=None)
    affected = [error.source for error in transient] + skipped
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
    result: FulltextServiceResult, context: FulltextAccessContext, skeletons: _Skeletons
) -> dict[str, Any] | None:
    if not result.pmcid:
        return None
    notices = {(notice.source, notice.code) for notice in result.source_notices}
    if ("pmc_html", "pdf_only") in notices:
        # The page itself positively shows a PDF-only record; the PDF step covers it.
        return None
    page_errors = [error for error in result.source_errors if error.source == "pmc_html"]
    skipped = {row.reason for row in result.sources_skipped if row.source == "pmc_html"}
    if ("ncbi_pmc", "front_matter_only") in notices:
        why = "The publisher restricts PMC XML reuse (front matter only), but the PMC article page is public."
    else:
        why = "The article is in PMC, but no XML source returned a body; its public article page can be read."
    if page_errors:
        why += f" The server could not read the page this time ({page_errors[0].code})."
    elif ("pmc_html", "no_body") in notices:
        why += " The server read the page but found no body text; check it in the host before concluding."
    elif "not_configured" in skipped:
        why += " Server-side page reading needs the operator's NCBI contact address (NCBI_EMAIL)."
    elif "deadline" in skipped:
        why += " The server did not reach the page before the get_fulltext deadline."
    elif not context.article_page_enabled:
        why += " Server-side reading of the page is disabled on this server."
    url = _PMC_PAGE.format(pmcid=result.pmcid)
    return _clean(
        {
            "step": "host_fetch",
            "url": url,
            "why": why,
            "access": "free_to_read",
            "tool_hint": "WebFetch (ask for the verbatim article text, not a summary)",
            "then": skeletons.then(
                "register_fulltext with retrieval_method='host_fetch' so later reads reuse the text"
            ),
            "register_with": skeletons.build(retrieval_method="host_fetch", source_url=url),
            "legal": LEGAL_INDIVIDUAL_PAGE,
        }
    )


def _pdf_step(
    *, url: str, label: str, access: str, license_value: object, skeletons: _Skeletons
) -> dict[str, Any] | None:
    kind = access_class(access)
    then = skeletons.then(
        "asset-aware-mcp ingest_documents for citation-ready spans, then register_fulltext(file_path=...) "
        "so get_fulltext, notes and Chronicle reuse it"
    )
    register_with = skeletons.build(retrieval_method="host_fetch", source_url=url, file_path=True)
    if kind == "open":
        step: dict[str, Any] = {
            "step": "download_oa_pdf",
            "why": f"An open-access PDF was located by {label} ({access}).",
            "legal": LEGAL_OA_COPY,
        }
    elif kind == "free_to_read":
        step = {
            "step": "download_pdf",
            "why": f"A free-to-read PDF was located by {label}.",
            "legal": LEGAL_FREE_TO_READ,
        }
    elif kind == "unknown":
        step = {
            "step": "check_access",
            "why": f"A PDF link of unknown access was located by {label}; confirm the user may use it first.",
            "legal": LEGAL_USER_COPY,
        }
    else:
        return None  # Licensed copies are reached through the institutional step.
    step.update(
        {
            "url": url,
            "access": access or None,
            "tool_hint": "the host's download tool (save inside an allowed intake directory)",
            "then": then,
            "register_with": register_with,
            "license": license_value or None,
        }
    )
    return _clean(step)


def _link_steps(result: FulltextServiceResult, skeletons: _Skeletons) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    pdf_count = 0
    landing_count = 0
    pmc_page = _PMC_PAGE.format(pmcid=result.pmcid) if result.pmcid else None
    for link in result.pdf_links:
        url = str(link.get("url") or "")
        access = str(link.get("access") or "")
        if not url or url == pmc_page:
            continue
        label = str(link.get("source") or "a discovery source")
        if link.get("type") == "pdf":
            if pdf_count >= _MAX_PDF_STEPS:
                continue
            step = _pdf_step(
                url=url, label=label, access=access, license_value=link.get("license"), skeletons=skeletons
            )
            if step is not None:
                pdf_count += 1
                steps.append(step)
        elif access_class(access) in {"open", "free_to_read"} and landing_count < _MAX_LANDING_STEPS:
            landing_count += 1
            open_access = access_class(access) == "open"
            steps.append(
                _clean(
                    {
                        "step": "host_fetch",
                        "url": url,
                        "why": f"An {'open-access' if open_access else 'free-to-read'} landing page was located "
                        f"by {label} ({access}).",
                        "access": access,
                        "tool_hint": "WebFetch (ask for the verbatim article text, not a summary)",
                        "then": skeletons.then("register_fulltext with retrieval_method='host_fetch'"),
                        "register_with": skeletons.build(retrieval_method="host_fetch", source_url=url),
                        "legal": LEGAL_INDIVIDUAL_PAGE,
                    }
                )
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
    then = (
        "If the host browser opens the licensed copy in the user's own session, register_fulltext "
        "with retrieval_method='host_browser'"
        if context.registration_allowed
        else _NO_REGISTRATION
    )
    return _clean(
        {
            "step": "institutional",
            "via": " / ".join(via),
            "why": "This server has institutional access configured; the library may license this article.",
            "tool_hint": "; ".join(hints) or None,
            "then": then,
            "legal": LEGAL_INSTITUTIONAL,
        }
    )


def _unstructured_step(result: FulltextServiceResult) -> dict[str, Any] | None:
    notice = result.fallback_notice
    pdf_url = notice.retrieved_url if notice else None
    link = next((row for row in result.pdf_links if row.get("type") == "pdf" and row.get("url") == pdf_url), None)
    if link is None and not pdf_url:
        link = next((row for row in result.pdf_links if row.get("type") == "pdf"), None)
        pdf_url = str(link["url"]) if link else None
    if not pdf_url:
        return None
    access = (
        "browser_session" if notice and notice.source == "browser_session" else str((link or {}).get("access") or "")
    )
    kind = access_class(access)
    step_kind, legal = {
        "open": ("download_oa_pdf", LEGAL_OA_COPY),
        "free_to_read": ("download_pdf", LEGAL_FREE_TO_READ),
        "licensed": ("download_pdf", LEGAL_INSTITUTIONAL),
        "unknown": ("check_access", LEGAL_USER_COPY),
    }[kind]
    return _clean(
        {
            "order": 1,
            "step": step_kind,
            "url": pdf_url,
            "access": access or None,
            "why": "The returned text was extracted from this PDF without sections or page locators.",
            "tool_hint": "the host's download tool",
            "then": "asset-aware-mcp ingest_documents (or parse_pdf_structure) for citation-ready spans",
            "legal": legal,
        }
    )


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
    skeletons = _Skeletons(source, context)
    if result.has_retrieved_text:
        if result.fulltext_provenance != "derived" or result.fulltext_origin != "provider":
            return [], None
        step = _unstructured_step(result)
        return ([step], "unstructured_text") if step is not None else ([], None)

    steps: list[dict[str, Any]] = []
    transient = _transient_step(result, source)
    if transient is not None:
        steps.append(transient)
    page = _pmc_page_step(result, context, skeletons)
    if page is not None:
        steps.append(page)
    steps.extend(_link_steps(result, skeletons))
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
        steps.append(institutional)
    if result.doi or result.pmid:
        lookup = {kind: value for kind in ("doi", "pmid") if (value := getattr(result, kind, None))}
        steps.append(
            _clean(
                {
                    "step": "zotero_attachment",
                    "via": "zotero-keeper check_articles_owned",
                    "requires": "zotero-keeper MCP server",
                    "lookup": lookup,
                    "why": "The user's own Zotero library may already hold a PDF of this article.",
                    "then": skeletons.then(
                        "register_fulltext(file_path=<attachment>, supplied_by='user', "
                        "provenance.retrieval_method='zotero_attachment')"
                    ),
                    "register_with": skeletons.build(
                        retrieval_method="zotero_attachment", supplied_by="user", file_path=True
                    ),
                    "legal": LEGAL_USER_COPY,
                }
            )
        )
    steps.append(
        _clean(
            {
                "step": "ask_user_for_pdf",
                "why": "If no route above yields the text, the user may have or obtain an entitled copy.",
                "then": skeletons.then(
                    "register_fulltext(file_path=<PDF>, supplied_by='user', "
                    "provenance.retrieval_method='user_upload'); for citation-ready spans also ingest it with "
                    "asset-aware-mcp"
                ),
                "register_with": skeletons.build(retrieval_method="user_upload", supplied_by="user", file_path=True),
                "legal": LEGAL_USER_COPY,
            }
        )
    )
    return [{"order": index, **step} for index, step in enumerate(steps, start=1)], "no_body"


__all__ = [
    "LEGAL_FREE_TO_READ",
    "LEGAL_INSTITUTIONAL",
    "LEGAL_OA_COPY",
    "LEGAL_USER_COPY",
    "AccessClass",
    "FulltextAccessContext",
    "PlanReason",
    "PlanStepKind",
    "access_class",
    "build_fulltext_plan",
]
