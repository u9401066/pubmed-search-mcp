"""Shared JATS article parsing for PMC-family structured fulltext adapters.

Europe PMC ``fullTextXML`` and NCBI E-utilities ``efetch db=pmc`` both return
JATS. Each adapter owns its transport, but section, reference, figure and
license extraction is one implementation so the two routes cannot drift.

Only the main article is extracted. JATS nests decision letters, author
replies and other reviews as ``<sub-article>`` / ``<response>`` elements with
their own ``<body>``, figures and references; none of that is the article's
fulltext, so it never becomes a section, figure or reference here.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

# TreeBuilder only assembles elements; parsing stays inside defusedxml.
from xml.etree.ElementTree import TreeBuilder

from defusedxml import ElementTree  # Security: prevent XML attacks

from pubmed_search.domain.value_objects.article_identifiers import (
    try_normalize_doi,
    try_normalize_pmcid,
    try_normalize_pmid,
)
from pubmed_search.shared.exceptions import ParseError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from xml.etree.ElementTree import Element

logger = logging.getLogger(__name__)

_XML_DECLARATION_RE = re.compile(r"<\?xml[^>]*\?>")
_DOCTYPE_RE = re.compile(r"<!DOCTYPE[^>]*>")
_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
_NESTED_ARTICLE_TAGS = frozenset({"sub-article", "response"})


def parse_jats_article(
    xml_content: str,
    *,
    source: str,
    notice_pattern: re.Pattern[str] | None = None,
) -> dict[str, Any]:
    """Parse the main JATS article (optionally wrapped in a ``pmc-articleset``).

    Args:
        xml_content: Raw JATS XML.
        source: Provider label used only in the sanitized parse error.
        notice_pattern: Optional provider notice to look for in the main
            article only (its text and XML comments, never a nested
            ``<sub-article>``); the outcome is returned as ``notice_found``.

    Returns:
        Dict with ``title``, ``abstract``, body ``sections``, ``references``,
        ``figures``, ``license`` (``None`` when the article declares none) and
        ``article_ids`` (the main article's declared ``pmid``/``pmcid``/``doi``),
        plus ``notice_found`` when ``notice_pattern`` is given.

    Raises:
        ParseError: The payload is not well-formed XML. The message never
            contains provider content.
    """
    try:
        cleaned = _DOCTYPE_RE.sub("", _XML_DECLARATION_RE.sub("", xml_content))
        # Comments are kept so provider notices written as comments can be
        # detected; element_text() never renders them.
        parser = ElementTree.XMLParser(target=TreeBuilder(insert_comments=True))
        parser.feed(cleaned)
        root = parser.close()

        # JATS may use a default namespace; preserve attribute namespaces
        # (notably xlink) while using local element names for extraction.
        for element in root.iter():
            if isinstance(element.tag, str):
                element.tag = element.tag.rsplit("}", 1)[-1]

        article = _main_article(root)
        front = article.find("front")
        front_scope = front if front is not None else article

        result: dict[str, Any] = {
            "title": "",
            "abstract": "",
            "sections": [],
            "references": [],
            "figures": [],
            "license": None,
        }

        title_elem = _first_in_main(front_scope, "article-title")
        if title_elem is not None:
            result["title"] = element_text(title_elem)

        abstract_elem = _first_in_main(front_scope, "abstract")
        if abstract_elem is not None:
            result["abstract"] = element_text(abstract_elem)

        body = article.find("body")
        if body is not None:
            body_paragraphs = [element_text(p) for p in body.findall("p")]
            if any(body_paragraphs):
                result["sections"].append({"title": "Body", "content": "\n\n".join(body_paragraphs)})
            for sec in body.findall(".//sec"):
                section = _parse_section(sec)
                if section:
                    result["sections"].append(section)

        result["figures"] = _parse_figures(article)
        result["license"] = _parse_license(front_scope)
        result["article_ids"] = _parse_article_ids(front_scope)

        ref_list = _first_in_main(article, "ref-list")
        if ref_list is not None:
            for ref in ref_list.findall(".//ref"):
                ref_data = _parse_reference(ref)
                if ref_data:
                    result["references"].append(ref_data)

        if notice_pattern is not None:
            result["notice_found"] = _main_article_mentions(article, notice_pattern)

        return result

    except Exception as exc:
        logger.warning("%s full-text XML parsing failed (%s)", source, type(exc).__name__)
        raise ParseError(
            f"{source} returned XML that could not be parsed",
            source=source,
        ) from exc


def element_text(elem: Element) -> str:
    """Recursively get all text from an element (comments are not text)."""
    return "".join(_iter_text(elem)).strip()


def _iter_text(elem: Element, *, skip_nested: bool = False) -> Iterator[str]:
    if not isinstance(elem.tag, str):
        # A comment or processing instruction; its tail belongs to the parent.
        return
    if elem.text:
        yield elem.text
    for child in elem:
        if not (skip_nested and child.tag in _NESTED_ARTICLE_TAGS):
            yield from _iter_text(child, skip_nested=skip_nested)
        if child.tail:
            yield child.tail


def _main_article(root: Element) -> Element:
    """Return the outermost ``<article>`` (the root, or a ``pmc-articleset`` child)."""
    if root.tag == "article":
        return root
    article = root.find("article")
    if article is None:
        article = root.find(".//article")
    return article if article is not None else root


def _iter_main(element: Element) -> Iterator[Element]:
    """Walk one article in document order without entering nested articles."""
    stack = [element]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed([child for child in node if child.tag not in _NESTED_ARTICLE_TAGS]))


def _first_in_main(element: Element, tag: str) -> Element | None:
    return next((node for node in _iter_main(element) if node.tag == tag), None)


def _main_article_mentions(article: Element, pattern: re.Pattern[str]) -> bool:
    """Whether the main article's text or one of its comments matches ``pattern``."""
    if pattern.search("".join(_iter_text(article, skip_nested=True))):
        return True
    return any(pattern.search(node.text or "") for node in _iter_main(article) if not isinstance(node.tag, str))


def _parse_section(sec_elem: Element) -> dict[str, Any] | None:
    title_elem = sec_elem.find("title")
    title = element_text(title_elem) if title_elem is not None else ""

    paragraphs = []
    for p in sec_elem.findall("p"):
        text = element_text(p)
        if text:
            paragraphs.append(text)

    if not title and not paragraphs:
        return None

    return {
        "title": title,
        "content": "\n\n".join(paragraphs),
    }


def _parse_reference(ref_elem: Element) -> dict[str, Any] | None:
    label = ref_elem.find("label")
    mixed_citation = ref_elem.find(".//mixed-citation")

    if mixed_citation is None:
        mixed_citation = ref_elem.find(".//element-citation")
    if mixed_citation is None:
        return None

    return {
        "label": element_text(label) if label is not None else "",
        "text": element_text(mixed_citation),
        "pmid": mixed_citation.findtext(".//pub-id[@pub-id-type='pmid']", ""),
        "doi": mixed_citation.findtext(".//pub-id[@pub-id-type='doi']", ""),
    }


def _parse_article_ids(scope: Element) -> dict[str, str]:
    """Identifiers the main article declares in ``<article-meta>``, normalized."""
    article_meta = _first_in_main(scope, "article-meta")
    if article_meta is None:
        return {}
    declared: dict[str, str] = {}
    for article_id in article_meta.findall("article-id"):
        kind = (article_id.get("pub-id-type") or "").strip().lower()
        value = element_text(article_id)
        if kind == "pmid" and "pmid" not in declared:
            normalized = try_normalize_pmid(value)
        elif kind in {"pmc", "pmcid"} and "pmcid" not in declared:
            normalized = try_normalize_pmcid(value if value.upper().startswith("PMC") else f"PMC{value}")
            kind = "pmcid"
        elif kind == "doi" and "doi" not in declared:
            normalized = try_normalize_doi(value)
        else:
            continue
        if normalized:
            declared[kind] = normalized
    return declared


def _parse_license(scope: Element) -> dict[str, str] | None:
    """Return the article-level license statement exactly as declared.

    Only the ``<permissions>`` of the main article metadata are read; the
    adapter never infers reuse rights that the publisher did not declare.
    """
    article_meta = _first_in_main(scope, "article-meta")
    permissions = article_meta.find("permissions") if article_meta is not None else None
    if permissions is None:
        return None
    license_elem = permissions.find("license")
    if license_elem is None:
        return None
    license_ref = license_elem.find(".//license_ref")
    ref_text = element_text(license_ref) if license_ref is not None else ""
    url = license_elem.get(_XLINK_HREF) or license_elem.get("href") or ref_text
    declared = {
        "type": (license_elem.get("license-type") or "").strip(),
        "url": url.strip(),
        "text": " ".join(element_text(license_elem).split())[:500],
    }
    cleaned = {key: value for key, value in declared.items() if value}
    return cleaned or None


def _parse_figures(article: Element) -> list[dict[str, Any]]:
    """Extract the main article's ``<fig>`` labels, captions and graphic references."""
    figures: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for fig_elem in (node for node in _iter_main(article) if node.tag == "fig"):
        fig_id = fig_elem.get("id", "")
        if fig_id:
            if fig_id in seen_ids:
                continue
            seen_ids.add(fig_id)

        label_elem = fig_elem.find("label")
        label = element_text(label_elem) if label_elem is not None else ""

        caption_elem = fig_elem.find("caption")
        caption_title = ""
        caption_text = ""
        if caption_elem is not None:
            title_elem = caption_elem.find("title")
            if title_elem is not None:
                caption_title = element_text(title_elem)
            p_parts = []
            for p in caption_elem.findall("p"):
                text = element_text(p)
                if text:
                    p_parts.append(text)
            caption_text = " ".join(p_parts)

        graphic_href = ""
        graphic = fig_elem.find("graphic")
        if graphic is not None:
            graphic_href = graphic.get(_XLINK_HREF, "") or graphic.get("href", "")

        if not label and not graphic_href and not caption_text:
            continue

        figures.append(
            {
                "figure_id": fig_id,
                "label": label,
                "caption_title": caption_title or None,
                "caption_text": caption_text,
                "graphic_href": graphic_href,
            }
        )

    return figures


__all__ = ["element_text", "parse_jats_article"]
