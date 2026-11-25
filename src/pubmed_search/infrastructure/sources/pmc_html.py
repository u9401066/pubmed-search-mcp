"""PMC article-page (HTML) adapter for explicit single-article reads.

Some publishers deposit articles in PubMed Central but forbid XML reuse:
NCBI ``efetch db=pmc`` then returns front matter only, and Europe PMC may not
hold a body either. The same article is still public on its PMC article page
(``https://pmc.ncbi.nlm.nih.gov/articles/PMCxxxxxxx/``) for individual reading.

This adapter reads that one page and projects it onto the shared section model
used by the JATS adapters (title, abstract, body sections, figure captions,
references, declared license). Navigation, banners, side panels, citation
dialogs, supplementary boxes and the site footer are never treated as article
text.

Usage boundary (NCBI policy): PMC allows people to read individual articles but
prohibits systematic or bulk downloading of PMC content from its website. The
fulltext service therefore starts this source only for an explicit,
single-article ``get_fulltext`` request; search prefetch and batch paths never
reach it. Requests are fetched one page at a time through the fail-closed
outbound HTTP layer, carry the configured NCBI contact identity, and draw from
a dedicated, conservative process-wide rate budget.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any

from pubmed_search.domain.value_objects.article_identifiers import normalize_pmcid, try_normalize_doi
from pubmed_search.infrastructure.http.safe_outbound import (
    AddressResolver,
    DisallowedOutboundHostError,
    OutboundResponseTooLargeError,
    SafeFetchPolicy,
    SafeOutboundError,
    UnsafeOutboundURLError,
    fetch_public_url,
    resolve_host_addresses,
)
from pubmed_search.infrastructure.sources.base_client import (
    APIRequestError,
    APIRequestFailureReason,
    APIResponseTooLargeError,
    raise_provider_schema_error,
)
from pubmed_search.shared.async_utils import RetryableOperationError, get_rate_limiter, parse_retry_after
from pubmed_search.shared.exceptions import RateLimitError
from pubmed_search.shared.tenancy import current_tenant

from .contact import first_contact_email, get_source_contact_email
from .runtime import get_source_runtime

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

logger = logging.getLogger(__name__)

PMC_ARTICLE_PAGE = "https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
# Process-wide budget for PMC article pages (separate from E-utilities).
PMC_HTML_RATE_LIMIT = "ncbi-pmc-article-page"
PMC_HTML_REQUESTS_PER_SECOND = 1.0
MAX_PMC_PAGE_BYTES = 4 * 1024 * 1024
DEFAULT_PMC_PAGE_TIMEOUT_SECONDS = 20.0
_FALLBACK_COOLDOWN_SECONDS = 30.0
# Back-off after PMC serves a bot challenge instead of the article page.
_CHALLENGE_COOLDOWN_SECONDS = 300.0
# Markers specific to challenge interstitials (reCAPTCHA, Cloudflare).
_CHALLENGE_MARKERS = ("recaptcha/challengepage", "g-recaptcha", "challenge-platform", "cf-chl-")
# Generic phrases count only on a small page with no article markup at all.
_GENERIC_CHALLENGE_PHRASES = ("making sure you", "are you a robot", "verify you are human")
_FORBIDDEN_COOLDOWN_SECONDS = 60.0
# A read never waits longer than this for the 1 request/s budget; it is
# reported as rate_limited instead of running into the request deadline.
_MAX_LIMITER_WAIT_SECONDS = 3.0
_SERVICE_NAME = "PMC article page"
# Real PMC article pages have about 2,000 elements nested about 25 deep.
_MAX_NODES = 100_000
_MAX_DEPTH = 128
MAX_HTML_CHARS = 8_000_000
_MAX_SECTIONS = 5_000
_SHORT_SEARCH_DEPTH = 4
ALLOWED_PAGE_HOSTS = ("pmc.ncbi.nlm.nih.gov", ".ncbi.nlm.nih.gov")
# Built-in defaults that only look like a contact; NCBI must never receive them.
PLACEHOLDER_CONTACTS = frozenset({"pubmed-search@example.com", "pubmed-search-mcp@example.com"})
DEFAULT_PROCESS_PAGES_PER_HOUR = 60
DEFAULT_TENANT_PAGES_PER_HOUR = 20
_MAX_SECTION_TITLE_CHARS = 300
_MAX_LICENSE_CHARS = 500

_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)
_RAW_TEXT_SKIP = frozenset({"script", "style", "noscript", "template"})
_P_CLOSERS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "div",
        "dl",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hgroup",
        "hr",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "ul",
    }
)
# Never article text: site chrome, interactive controls and embedded media.
_DROP_TAGS = frozenset(
    {
        "button",
        "embed",
        "form",
        "iframe",
        "input",
        "map",
        "nav",
        "noscript",
        "object",
        "script",
        "select",
        "style",
        "svg",
        "template",
        "textarea",
    }
)
_BLOCK_TAGS = _P_CLOSERS | frozenset({"li", "tr", "td", "th", "dt", "dd", "caption", "figcaption", "br"})
_HEADING_TAGS = ("h2", "h3", "h4", "h5", "h6")
# Sections of the PMC body that are not article body text in the shared model
# (JATS keeps them in <back> or outside <body>).
_NON_BODY_SECTION_CLASSES = frozenset(
    {
        "abstract",
        "ack",
        "app-group",
        "associated-data",
        "fn-group",
        "glossary",
        "kwd-group",
        "ref-list",
        "sm",
        "supplementary-materials",
        "tw",
    }
)
_PARAGRAPH_TAGS = frozenset({"p", "ul", "ol", "dl", "blockquote", "pre"})
_PMCID_IN_URL_RE = re.compile(r"/articles/(PMC\d+)", re.IGNORECASE)
_PUBMED_LINK_RE = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")
_FIGURE_LABEL_RE = re.compile(r"^((?:Figure|Fig\.?|Scheme|Chart)\s*[\w.-]*\d+[A-Za-z]?\.?)\s*(.*)$", re.IGNORECASE)
# Whole tokens of a class or id (split at whitespace, "-" and "_"); substrings
# such as "shared-decision-making" or "data-unavailable" are article content.
_GENERIC_CHROME_WORDS = frozenset(
    {
        "nav",
        "navbar",
        "navigation",
        "menu",
        "breadcrumb",
        "breadcrumbs",
        "cookie",
        "cookies",
        "banner",
        "sidebar",
        "share",
        "sharing",
        "social",
        "advert",
        "advertisement",
        "ads",
    }
)
_TOKEN_SPLIT_RE = re.compile(r"[\s_-]+")
_GENERIC_CHROME_TAGS = frozenset({"header", "footer", "aside"})


class _Element:
    """Minimal DOM node built by the tolerant HTML tree builder."""

    __slots__ = ("attrs", "children", "parent", "tag")

    def __init__(self, tag: str, attrs: dict[str, str], parent: _Element | None) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[_Element | str] = []

    @property
    def classes(self) -> frozenset[str]:
        return frozenset(self.attrs.get("class", "").split())

    def elements(self) -> Iterator[_Element]:
        """Child elements in document order."""
        for child in self.children:
            if isinstance(child, _Element):
                yield child

    def iter(self) -> Iterator[_Element]:
        """This element and all descendants in document order (iterative)."""
        stack: list[_Element] = [self]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(list(node.elements())))

    def find(self, predicate: Callable[[_Element], bool]) -> _Element | None:
        return next((node for node in self.iter() if node is not self and predicate(node)), None)

    def find_all(self, predicate: Callable[[_Element], bool]) -> list[_Element]:
        return [node for node in self.iter() if node is not self and predicate(node)]


class HTMLParseLimitError(ValueError):
    """The HTML exceeded a hard parsing bound (size, elements or nesting depth)."""


class _TreeBuilder(HTMLParser):
    """Build a tolerant element tree in linear time; stray end tags are ignored.

    Each open element is counted per tag name, so an end tag with no open
    element of that name is dropped in O(1), and the walk up the open path for
    a matching end tag closes every element it passes: each element is walked
    past at most once. Element count and nesting depth are capped.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Element("#document", {}, None)
        self._current = self.root
        self._skip_depth = 0
        self._nodes = 0
        self._depth = 0
        self._open: dict[str, int] = {}

    def _push(self, node: _Element) -> None:
        self._depth += 1
        if self._depth > _MAX_DEPTH:
            raise HTMLParseLimitError("HTML nesting is too deep")
        self._open[node.tag] = self._open.get(node.tag, 0) + 1
        self._current = node

    def _pop(self) -> None:
        node = self._current
        self._open[node.tag] -= 1
        self._depth -= 1
        self._current = node.parent or self.root

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._skip_depth:
            if tag in _RAW_TEXT_SKIP:
                self._skip_depth += 1
            return
        if tag in _RAW_TEXT_SKIP:
            self._skip_depth = 1
            return
        if tag in _P_CLOSERS and self._current.tag == "p":
            self._pop()
        if tag == "li" and self._current.tag == "li":
            self._pop()
        node = _Element(tag, {key.lower(): value or "" for key, value in attrs if key}, self._current)
        self._current.children.append(node)
        self._nodes += 1
        if self._nodes > _MAX_NODES:
            raise HTMLParseLimitError("HTML has too many elements")
        if tag not in _VOID_TAGS:
            self._push(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip_depth:
            if tag in _RAW_TEXT_SKIP:
                self._skip_depth -= 1
            return
        if tag in _VOID_TAGS or not self._open.get(tag):
            return
        while self._current is not self.root and self._current.tag != tag:
            self._pop()
        if self._current is not self.root:
            self._pop()

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data:
            self._current.children.append(data)


def _build_tree(html: str) -> _Element:
    """Parse HTML into an element tree or raise :class:`HTMLParseLimitError`."""
    if len(html) > MAX_HTML_CHARS:
        raise HTMLParseLimitError("HTML is too large")
    builder = _TreeBuilder()
    try:
        builder.feed(html)
        builder.close()
    except HTMLParseLimitError:
        raise
    except (AssertionError, ValueError, RecursionError):
        raise HTMLParseLimitError("HTML could not be parsed") from None
    return builder.root


def _find_within(node: _Element, predicate: Callable[[_Element], bool], max_depth: int) -> _Element | None:
    """First matching descendant at most ``max_depth`` levels below ``node``."""
    stack: list[tuple[_Element, int]] = [(child, 1) for child in reversed(list(node.elements()))]
    while stack:
        current, depth = stack.pop()
        if predicate(current):
            return current
        if depth < max_depth:
            stack.extend((child, depth + 1) for child in reversed(list(current.elements())))
    return None


def _is_dropped(node: _Element) -> bool:
    return node.tag in _DROP_TAGS or "hidden" in node.attrs or node.attrs.get("aria-hidden") == "true"


def _collect_text(node: _Element, parts: list[str]) -> None:
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
            continue
        if _is_dropped(child):
            continue
        if child.tag == "br":
            parts.append("\n")
            continue
        block = child.tag in _BLOCK_TAGS
        if block:
            parts.append("\n")
        _collect_text(child, parts)
        if block:
            parts.append("\n")


def _text(node: _Element | None) -> str:
    """Visible text of one element with whitespace collapsed to single spaces."""
    if node is None:
        return ""
    parts: list[str] = []
    _collect_text(node, parts)
    return " ".join("".join(parts).split())


def _block_text(node: _Element) -> str:
    """Text of a paragraph-like block; list items keep one line each."""
    if node.tag in {"ul", "ol"}:
        items = [_text(item) for item in node.elements() if item.tag == "li"]
        return "\n".join(f"- {item}" for item in items if item)
    return _text(node)


def _has_class(node: _Element, *names: str) -> bool:
    return bool(node.classes.intersection(names))


def _meta_values(root: _Element) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for node in root.iter():
        if node.tag != "meta":
            continue
        name = (node.attrs.get("name") or node.attrs.get("property") or "").strip().lower()
        content = node.attrs.get("content", "").strip()
        if name and content:
            values.setdefault(name, []).append(content)
    return values


def _first_meta(meta: dict[str, list[str]], *names: str) -> str:
    for name in names:
        for value in meta.get(name, []):
            if value:
                return value
    return ""


def _canonical_url(root: _Element) -> str:
    for node in root.iter():
        if node.tag == "link" and "canonical" in node.attrs.get("rel", "").lower().split():
            return node.attrs.get("href", "").strip()
    return ""


def _section_title(section: _Element) -> str:
    for child in section.elements():
        if child.tag in _HEADING_TAGS:
            return _text(child)[:_MAX_SECTION_TITLE_CHARS]
        if child.tag in _PARAGRAPH_TAGS or child.tag == "section":
            break
    return ""


def _section_paragraphs(section: _Element) -> list[str]:
    paragraphs: list[str] = []
    for child in section.elements():
        if _is_dropped(child):
            continue
        if child.tag in _PARAGRAPH_TAGS or (child.tag == "div" and "p" in child.classes):
            text = _block_text(child)
            if text:
                paragraphs.append(text)
    return paragraphs


def _parse_abstract(body: _Element) -> str:
    """Prefer the section headed "Abstract"; otherwise join every abstract block."""
    blocks = [node for node in body.elements() if node.tag == "section" and "abstract" in node.classes]
    preferred = [block for block in blocks if _section_title(block).strip().lower() == "abstract"]
    parts: list[str] = []
    for block in preferred or blocks:
        heading = _section_title(block)
        lines = _section_paragraphs(block)
        for sub in block.elements():
            if sub.tag != "section":
                continue
            sub_title = _section_title(sub)
            sub_text = " ".join(_section_paragraphs(sub))
            if sub_text:
                lines.append(f"{sub_title}: {sub_text}" if sub_title else sub_text)
        if lines:
            if not preferred and heading and len(blocks) > 1:
                parts.append(f"{heading}: " + " ".join(lines))
            else:
                parts.append(" ".join(lines))
    return "\n\n".join(parts)


def _walk_body_sections(container: _Element, sections: list[dict[str, Any]]) -> None:
    for child in container.elements():
        if child.tag != "section" or _is_dropped(child) or child.classes & _NON_BODY_SECTION_CLASSES:
            continue
        title = _section_title(child)
        paragraphs = _section_paragraphs(child)
        if title or paragraphs:
            if len(sections) >= _MAX_SECTIONS:
                raise HTMLParseLimitError("HTML has too many sections")
            sections.append({"title": title, "content": "\n\n".join(paragraphs)})
        _walk_body_sections(child, sections)


def _parse_figures(body: _Element) -> list[dict[str, Any]]:
    figures: list[dict[str, Any]] = []
    seen: set[str] = set()
    for figure in body.find_all(lambda node: node.tag == "figure" or (node.tag == "div" and "fig" in node.classes)):
        figure_id = figure.attrs.get("id", "")
        if figure_id and figure_id in seen:
            continue
        if figure_id:
            seen.add(figure_id)
        head = _find_within(
            figure, lambda node: node.tag in _HEADING_TAGS or "obj_head" in node.classes, _SHORT_SEARCH_DEPTH
        )
        heading = _text(head)[:_MAX_SECTION_TITLE_CHARS]
        match = _FIGURE_LABEL_RE.match(heading)
        label, caption_title = (match.group(1).rstrip("."), match.group(2).strip()) if match else (heading, "")
        caption = _find_within(
            figure, lambda node: node.tag == "figcaption" or "caption" in node.classes, _SHORT_SEARCH_DEPTH
        )
        image = _find_within(figure, lambda node: node.tag == "img", _SHORT_SEARCH_DEPTH)
        caption_text = _text(caption)
        graphic_href = image.attrs.get("src", "") if image is not None else ""
        if not (label or caption_text or graphic_href):
            continue
        figures.append(
            {
                "figure_id": figure_id,
                "label": label,
                "caption_title": caption_title or None,
                "caption_text": caption_text,
                "graphic_href": graphic_href,
            }
        )
    return figures


def _parse_references(body: _Element) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for ref_list in body.find_all(lambda node: node.tag == "section" and "ref-list" in node.classes):
        for item in ref_list.find_all(lambda node: node.tag == "li"):
            if _find_within(item, lambda node: node.tag == "li", _SHORT_SEARCH_DEPTH) is not None:
                continue
            label_node = _find_within(
                item, lambda node: node.tag == "span" and "label" in node.classes, _SHORT_SEARCH_DEPTH
            )
            cite = _find_within(item, lambda node: node.tag == "cite", _SHORT_SEARCH_DEPTH)
            text = _text(cite) if cite is not None else _text(item)
            if not text:
                continue
            pmid = ""
            doi = ""
            links = [child for child in item.elements() if child.tag == "a"]
            for link in links:
                href = link.attrs.get("href", "")
                match = _PUBMED_LINK_RE.search(href)
                if match and not pmid:
                    pmid = match.group(1)
                if "doi.org/" in href and not doi:
                    doi = try_normalize_doi(href.split("doi.org/", 1)[1]) or ""
            references.append({"label": _text(label_node).rstrip("."), "text": text, "pmid": pmid, "doi": doi})
    return references


def _parse_license(article: _Element) -> dict[str, str] | None:
    """Return the copyright/license statement exactly as the page displays it."""
    panel = article.find(lambda node: node.attrs.get("id") == "clp_a")
    if panel is None:
        panel = article.find(lambda node: node.tag == "section" and "permissions" in node.classes)
    if panel is None:
        return None
    statements: list[str] = []
    url = ""
    for node in panel.iter():
        if node.tag == "a":
            href = node.attrs.get("href", "")
            if "creativecommons.org" in href and not url:
                url = href.strip()
    for child in panel.elements():
        text = _text(child)
        if not text or text.lower() == "pmc copyright notice":
            continue
        statements.append(text)
    declared = {"text": " ".join(statements)[:_MAX_LICENSE_CHARS], "url": url}
    cleaned = {key: value for key, value in declared.items() if value}
    return cleaned or None


def _title_from_front(article: _Element) -> str:
    front = article.find(lambda node: node.tag == "section" and "front-matter" in node.classes) or article
    hgroup = front.find(lambda node: node.tag == "hgroup")
    heading = (hgroup or front).find(lambda node: node.tag == "h1")
    title = _text(heading)
    if hgroup is not None:
        subtitle = _text(hgroup.find(lambda node: node.tag == "p"))
        if title and subtitle:
            title = f"{title}: {subtitle}"
    return title


def _declared_pmcid(canonical: str, meta: dict[str, list[str]], page_url: str | None) -> str | None:
    """The PMCID the page says it is: canonical link, citation URLs, then the URL read."""
    candidates = [
        canonical,
        _first_meta(meta, "citation_fulltext_html_url"),
        _first_meta(meta, "citation_abstract_html_url"),
        page_url or "",
    ]
    for candidate in candidates:
        match = _PMCID_IN_URL_RE.search(candidate or "")
        if match:
            return normalize_pmcid(match.group(1))
    return None


def parse_pmc_article_html(html: str, *, pmcid: str | None = None, page_url: str | None = None) -> dict[str, Any]:
    """Parse one PMC article page into the shared fulltext section model.

    Args:
        html: The article page HTML.
        pmcid: The requested PMCID. The page must declare which article it is
            (canonical link, citation URL meta, or ``page_url``), and a page
            that declares another article is rejected rather than returned as
            the requested article's text.
        page_url: The URL the page was actually read from (last redirect hop).

    Returns:
        ``title``, ``abstract``, ``sections`` (body only), ``figures``,
        ``references``, ``license`` (as displayed, or ``None``), plus page
        facts: ``canonical_url``, ``pmcid`` (declared, or ``""``), ``pmid``,
        ``doi``, ``pdf_url``, ``pdf_only`` and ``courtesy_note``.

    Raises:
        ProviderSchemaError: The page is not a PMC article page (for example an
            error, maintenance or challenge page), declares no or another
            article, lacks the article-body container PMC pages carry (layout
            drift), or exceeds a parsing bound.
    """
    try:
        root = _build_tree(html)
    except HTMLParseLimitError:
        logger.warning("PMC article page exceeded a parsing bound")
        raise_provider_schema_error(_SERVICE_NAME)

    article = root.find(lambda node: node.tag == "article")
    if article is None:
        logger.warning("PMC page did not contain an article element")
        raise_provider_schema_error(_SERVICE_NAME)

    meta = _meta_values(root)
    canonical = _canonical_url(root)
    declared_pmcid = _declared_pmcid(canonical, meta, page_url)
    requested = normalize_pmcid(pmcid) if pmcid else None
    if requested and declared_pmcid != requested:
        logger.warning("PMC page did not declare the requested article")
        raise_provider_schema_error(_SERVICE_NAME)

    body = article.find(lambda node: node.tag == "section" and "main-article-body" in node.classes)
    if body is None:
        body = article.find(lambda node: node.tag == "section" and "body" in node.classes)
    if body is None:
        # PMC pages always carry the body container, even for PDF-only records;
        # its absence means the page layout changed, not that there is no body.
        logger.warning("PMC page layout changed: no article body container was found")
        raise_provider_schema_error(_SERVICE_NAME)

    try:
        abstract = _parse_abstract(body)
        sections: list[dict[str, Any]] = []
        _walk_body_sections(body, sections)
        figures = _parse_figures(body)
        references = _parse_references(body)
    except HTMLParseLimitError:
        logger.warning("PMC article page exceeded a parsing bound")
        raise_provider_schema_error(_SERVICE_NAME)

    courtesy = article.find(lambda node: node.tag == "footer" and "courtesy-note" in node.classes)
    title = _title_from_front(article) or _first_meta(meta, "citation_title")
    pdf_url = _first_meta(meta, "citation_pdf_url")
    return {
        "title": title,
        "abstract": abstract,
        "sections": sections,
        "figures": figures,
        "references": references,
        "license": _parse_license(article),
        "canonical_url": canonical,
        "pmcid": declared_pmcid or "",
        "pmid": _first_meta(meta, "citation_pmid"),
        "doi": try_normalize_doi(_first_meta(meta, "citation_doi")) or "",
        "pdf_url": pdf_url,
        "pdf_only": bool(pdf_url) and not any(str(row.get("content") or "").strip() for row in sections),
        "courtesy_note": _text(courtesy),
    }


def _is_generic_chrome(node: _Element) -> bool:
    if node.tag in _GENERIC_CHROME_TAGS or node.attrs.get("role") in {"navigation", "banner", "contentinfo"}:
        return True
    marker = " ".join((node.attrs.get("class", ""), node.attrs.get("id", ""))).lower()
    return any(token in _GENERIC_CHROME_WORDS for token in _TOKEN_SPLIT_RE.split(marker) if token)


def parse_article_html(html: str) -> dict[str, Any]:
    """Parse article HTML supplied by a host agent or user into the section model.

    PMC-shaped pages use :func:`parse_pmc_article_html`. Other pages are read
    conservatively: the first ``<article>`` (else ``<main>``, else ``<body>``)
    is split at its headings, and site chrome (navigation, banners, side bars,
    cookie and share widgets) is skipped. Identifiers the page declares in its
    citation meta (``pmid``, ``doi``, and for PMC pages ``pmcid``) are returned
    so the caller can check them against the requested article.

    Raises:
        HTMLParseLimitError: The HTML exceeds a size, element or depth bound.
    """
    root = _build_tree(html)
    if "main-article-body" in html:
        try:
            return parse_pmc_article_html(html)
        except APIRequestError:
            logger.info("Supplied PMC-shaped HTML did not parse as a PMC page; using the generic reader")
    meta = _meta_values(root)
    container = (
        root.find(lambda node: node.tag == "article")
        or root.find(lambda node: node.tag == "main")
        or root.find(lambda node: node.tag == "body")
        or root
    )
    reader = _GenericArticleReader()
    reader.visit(container)
    reader.flush()
    declared_pmcid = _declared_pmcid(_canonical_url(root), meta, None)
    return {
        "title": _first_meta(meta, "citation_title", "dc.title", "og:title") or reader.first_h1,
        "abstract": "\n\n".join(reader.abstract),
        "sections": reader.sections,
        "figures": [],
        "references": [],
        "license": None,
        "pmcid": declared_pmcid or "",
        "pmid": _first_meta(meta, "citation_pmid"),
        "doi": try_normalize_doi(_first_meta(meta, "citation_doi", "dc.identifier")) or "",
    }


class _GenericArticleReader:
    """Split non-PMC article HTML at its headings, skipping site chrome."""

    def __init__(self) -> None:
        self.first_h1 = ""
        self.abstract: list[str] = []
        self.sections: list[dict[str, Any]] = []
        self._title = "Body"
        self._paragraphs: list[str] = []

    def flush(self) -> None:
        if not self._paragraphs:
            return
        if self._title.strip().lower().startswith("abstract"):
            self.abstract.extend(self._paragraphs)
        else:
            self.sections.append({"title": self._title, "content": "\n\n".join(self._paragraphs)})
        self._paragraphs = []

    def visit(self, node: _Element) -> None:
        for child in node.elements():
            if _is_dropped(child) or _is_generic_chrome(child):
                continue
            if child.tag == "h1":
                self.first_h1 = self.first_h1 or _text(child)
            elif child.tag in _HEADING_TAGS:
                self.flush()
                if len(self.sections) >= _MAX_SECTIONS:
                    raise HTMLParseLimitError("HTML has too many sections")
                self._title = _text(child)[:_MAX_SECTION_TITLE_CHARS] or "Body"
            elif child.tag in _PARAGRAPH_TAGS:
                text = _block_text(child)
                if text:
                    self._paragraphs.append(text)
            else:
                self.visit(child)


def is_bot_challenge(html: str) -> bool:
    """Whether a 200 answer is a CAPTCHA / bot-check interstitial, not a page.

    A document carrying article markup anywhere is never a challenge. Without
    it, a challenge-specific marker (reCAPTCHA challenge page, Cloudflare
    challenge platform) decides; generic phrases count only on a small page.
    """
    lowered = html.lower()
    if "<article" in lowered or "main-article-body" in lowered:
        return False
    if any(marker in lowered[:200_000] for marker in _CHALLENGE_MARKERS):
        return True
    return len(lowered) < 50_000 and any(phrase in lowered for phrase in _GENERIC_CHALLENGE_PHRASES)


def is_configured_contact(email: str | None) -> bool:
    """Whether ``email`` is an operator-configured contact (not empty, not a built-in placeholder)."""
    if not isinstance(email, str):
        return False
    cleaned = email.strip().lower()
    return bool(cleaned) and "@" in cleaned and cleaned not in PLACEHOLDER_CONTACTS


class PageVolumeBudget:
    """Rolling hourly caps on PMC page fetches, per process and per tenant.

    The 1 request/s limiter bounds bursts; this bounds volume, so an agent
    looping ``get_fulltext`` over a result list cannot turn individual reading
    into systematic download. Only real fetches count (cache hits do not).
    """

    def __init__(
        self,
        *,
        process_per_hour: int,
        tenant_per_hour: int,
        window_seconds: float = 3600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        for name, value in (("process_per_hour", process_per_hour), ("tenant_per_hour", tenant_per_hour)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self._process_cap = process_per_hour
        self._tenant_cap = tenant_per_hour
        self._window = window_seconds
        self._clock = clock
        self._process: deque[float] = deque()
        self._tenants: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, stamps: deque[float], now: float) -> None:
        while stamps and stamps[0] <= now - self._window:
            stamps.popleft()

    def try_consume(self, tenant: str) -> float | None:
        """Record one fetch for ``tenant``; return the wait in seconds when a cap is reached."""
        now = self._clock()
        with self._lock:
            self._prune(self._process, now)
            stamps = self._tenants.setdefault(tenant, deque())
            self._prune(stamps, now)
            if len(self._process) >= self._process_cap:
                return max(1.0, self._process[0] + self._window - now)
            if len(stamps) >= self._tenant_cap:
                return max(1.0, stamps[0] + self._window - now)
            self._process.append(now)
            stamps.append(now)
            if len(self._tenants) > 1_024:
                for key in [key for key, value in self._tenants.items() if not value]:
                    del self._tenants[key]
            return None


_BUDGET_LOCK = threading.Lock()
_PROCESS_BUDGET: PageVolumeBudget | None = None


def get_page_volume_budget() -> PageVolumeBudget:
    """The process-wide page budget, sized once from settings."""
    global _PROCESS_BUDGET
    with _BUDGET_LOCK:
        if _PROCESS_BUDGET is None:
            from pubmed_search.shared.settings import load_settings

            settings = load_settings()
            _PROCESS_BUDGET = PageVolumeBudget(
                process_per_hour=settings.fulltext_pmc_html_hourly_limit,
                tenant_per_hour=settings.fulltext_pmc_html_tenant_hourly_limit,
            )
        return _PROCESS_BUDGET


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class PMCArticlePageClient:
    """Fetch and parse one public PMC article page per call."""

    def __init__(
        self,
        email: str | None = None,
        *,
        timeout: float = DEFAULT_PMC_PAGE_TIMEOUT_SECONDS,
        max_bytes: int = MAX_PMC_PAGE_BYTES,
        client: Any | None = None,
        resolver: AddressResolver = resolve_host_addresses,
        clock: Callable[[], str] = _utc_now_iso,
        budget: PageVolumeBudget | None = None,
    ) -> None:
        if not is_configured_contact(email):
            raise ValueError("PMC page reads need the operator's NCBI contact address (NCBI_EMAIL)")
        self._email = str(email).strip()
        self._policy = SafeFetchPolicy(
            max_bytes=max_bytes, total_timeout=timeout, max_redirects=3, allowed_hosts=ALLOWED_PAGE_HOSTS
        )
        self._client = client
        self._resolver = resolver
        self._clock = clock
        self._budget = budget

    @staticmethod
    def article_page_url(pmcid: str) -> str:
        return PMC_ARTICLE_PAGE.format(pmcid=normalize_pmcid(pmcid))

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": f"pubmed-search-mcp/1.0 (mailto:{self._email})",
            "Accept": "text/html,application/xhtml+xml",
        }

    async def fetch_article_document(self, pmcid: str) -> str | None:
        """Fetch one article page and return its parsed document as JSON text.

        Returns:
            JSON of :func:`parse_pmc_article_html` plus ``url`` (the page that
            was read), ``retrieved_at`` (UTC) and ``source`` (``pmc_html``),
            or ``None`` when PMC states that no such article exists (404/410).

        Raises:
            RetryableOperationError: HTTP 429 (``retry_after`` when declared)
                or a 5xx answer; a shared cooldown is applied on 429.
            RateLimitError: PMC answered with a bot-challenge interstitial, a
                cooldown is active, the per-second limiter could not be
                acquired promptly, or an hourly page budget is spent.
            APIRequestError: Other HTTP errors (403 also applies a cooldown),
                timeouts or transport failures, with only a coarse reason.
            ProviderSchemaError: The answer was not a PMC article page, or a
                redirect left NCBI.
        """
        normalized = normalize_pmcid(pmcid)
        url = self.article_page_url(normalized)
        limiter = get_rate_limiter(PMC_HTML_RATE_LIMIT, rate=PMC_HTML_REQUESTS_PER_SECOND, per=1.0, conservative=True)
        self._raise_if_cooling(limiter)
        try:
            await asyncio.wait_for(limiter.acquire(), timeout=_MAX_LIMITER_WAIT_SECONDS)
        except (asyncio.TimeoutError, TimeoutError):
            raise RateLimitError(
                f"{_SERVICE_NAME} is busy", retry_after=round(max(limiter.cooldown_remaining(), 1.0), 1)
            ) from None
        # A cooldown applied while this read waited still wins.
        self._raise_if_cooling(limiter)
        wait = (self._budget or get_page_volume_budget()).try_consume(current_tenant().tenant_id)
        if wait is not None:
            logger.warning("PMC article page hourly budget reached; not fetching")
            raise RateLimitError(f"{_SERVICE_NAME} hourly budget reached", retry_after=round(wait, 1))
        try:
            fetched = await fetch_public_url(
                url,
                policy=self._policy,
                headers=self._headers(),
                resolver=self._resolver,
                client=self._client,
            )
        except DisallowedOutboundHostError:
            logger.warning("PMC article page redirected outside NCBI")
            raise_provider_schema_error(_SERVICE_NAME)
        except OutboundResponseTooLargeError:
            raise APIResponseTooLargeError(_SERVICE_NAME, max_bytes=self._policy.max_bytes) from None
        except UnsafeOutboundURLError:
            raise APIRequestError(_SERVICE_NAME, reason="transport") from None
        except SafeOutboundError as exc:
            reason: APIRequestFailureReason = "timeout" if "deadline" in str(exc) else "transport"
            logger.warning("PMC article page request failed (%s)", reason)
            raise APIRequestError(_SERVICE_NAME, reason=reason) from None
        response = fetched.response
        final_host = (response.request.url.host or "").lower()
        if not _allowed_host(final_host):
            logger.warning("PMC article page redirected outside NCBI")
            raise_provider_schema_error(_SERVICE_NAME)
        if response.status_code in {404, 410}:
            return None
        if response.status_code == 429:
            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            await limiter.apply_cooldown(retry_after if retry_after is not None else _FALLBACK_COOLDOWN_SECONDS)
            raise RetryableOperationError(f"{_SERVICE_NAME} request failed", retry_after=retry_after, status_code=429)
        if response.status_code == 403:
            # A common bot-block status: stop hammering the site for a while.
            await limiter.apply_cooldown(_FORBIDDEN_COOLDOWN_SECONDS)
            raise APIRequestError(_SERVICE_NAME, status_code=403)
        if response.status_code >= 500:
            raise RetryableOperationError(f"{_SERVICE_NAME} request failed", status_code=response.status_code)
        if response.status_code != 200:
            raise APIRequestError(_SERVICE_NAME, status_code=response.status_code)
        content_type = response.headers.get("content-type", "").lower()
        if content_type and "html" not in content_type:
            raise_provider_schema_error(_SERVICE_NAME)
        text = response.text
        if is_bot_challenge(text):
            # NCBI's web front end answers automated traffic it distrusts with a
            # CAPTCHA interstitial (HTTP 200). Treat it as throttling: back off
            # process-wide and let the host agent read the page in its own
            # client or the user's browser instead of retrying here.
            logger.warning("PMC article page answered with a bot challenge; backing off")
            await limiter.apply_cooldown(_CHALLENGE_COOLDOWN_SECONDS)
            raise RateLimitError(
                f"{_SERVICE_NAME} served a bot challenge instead of the article",
                retry_after=_CHALLENGE_COOLDOWN_SECONDS,
            )
        parsed = await asyncio.to_thread(
            parse_pmc_article_html, text, pmcid=normalized, page_url=str(response.request.url)
        )
        parsed.update(
            {
                "source": "pmc_html",
                "url": parsed.get("canonical_url") or url,
                "retrieved_at": self._clock(),
            }
        )
        return json.dumps(parsed, ensure_ascii=False)

    @staticmethod
    def _raise_if_cooling(limiter: Any) -> None:
        cooling = limiter.cooldown_remaining()
        if cooling > 0:
            # Never sit out a long back-off inside a get_fulltext deadline.
            raise RateLimitError(f"{_SERVICE_NAME} is cooling down", retry_after=round(cooling, 1))

    async def close(self) -> None:
        """The shared outbound client is owned by the source runtime."""


def _allowed_host(host: str) -> bool:
    return any(host == entry or (entry.startswith(".") and host.endswith(entry)) for entry in ALLOWED_PAGE_HOSTS)


def configured_page_contact(email: str | None = None) -> str | None:
    """The operator contact PMC page reads would send, or ``None`` when only a placeholder is set."""
    from pubmed_search.shared.settings import load_settings

    resolved = first_contact_email(email, get_source_contact_email(), load_settings().ncbi_email)
    return resolved if is_configured_contact(resolved) else None


def get_pmc_article_page_client(email: str | None = None) -> PMCArticlePageClient:
    """Return the runtime-owned PMC article-page client for the configured identity.

    Raises:
        ValueError: No operator contact address is configured (NCBI_EMAIL).
    """
    resolved_email = configured_page_contact(email)
    if resolved_email is None:
        raise ValueError("PMC page reads need the operator's NCBI contact address (NCBI_EMAIL)")

    def _factory() -> PMCArticlePageClient:
        return PMCArticlePageClient(email=resolved_email)

    return get_source_runtime().get_or_create_client(("pmc_html", resolved_email), _factory)


__all__ = [
    "ALLOWED_PAGE_HOSTS",
    "MAX_HTML_CHARS",
    "MAX_PMC_PAGE_BYTES",
    "PMC_ARTICLE_PAGE",
    "PMC_HTML_RATE_LIMIT",
    "HTMLParseLimitError",
    "PMCArticlePageClient",
    "PageVolumeBudget",
    "configured_page_contact",
    "get_page_volume_budget",
    "get_pmc_article_page_client",
    "is_bot_challenge",
    "is_configured_contact",
    "parse_article_html",
    "parse_pmc_article_html",
]
