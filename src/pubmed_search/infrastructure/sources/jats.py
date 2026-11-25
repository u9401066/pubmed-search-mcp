"""Shared JATS article parsing for PMC-family structured fulltext adapters.

Europe PMC ``fullTextXML`` and NCBI E-utilities ``efetch db=pmc`` both return
JATS. Each adapter owns its transport, but section, reference, figure and
license extraction is one implementation so the two routes cannot drift.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from defusedxml import ElementTree  # Security: prevent XML attacks

from pubmed_search.shared.exceptions import ParseError

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

logger = logging.getLogger(__name__)

_XML_DECLARATION_RE = re.compile(r"<\?xml[^>]*\?>")
_DOCTYPE_RE = re.compile(r"<!DOCTYPE[^>]*>")
_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"


def parse_jats_article(xml_content: str, *, source: str) -> dict[str, Any]:
    """Parse one JATS article (optionally wrapped in a ``pmc-articleset``).

    Args:
        xml_content: Raw JATS XML.
        source: Provider label used only in the sanitized parse error.

    Returns:
        Dict with ``title``, ``abstract``, body ``sections``, ``references``,
        ``figures`` and ``license`` (``None`` when the article declares none).

    Raises:
        ParseError: The payload is not well-formed XML. The message never
            contains provider content.
    """
    try:
        cleaned = _DOCTYPE_RE.sub("", _XML_DECLARATION_RE.sub("", xml_content))
        root = ElementTree.fromstring(cleaned)

        # JATS may use a default namespace; preserve attribute namespaces
        # (notably xlink) while using local element names for extraction.
        for element in root.iter():
            if isinstance(element.tag, str):
                element.tag = element.tag.rsplit("}", 1)[-1]

        result: dict[str, Any] = {
            "title": "",
            "abstract": "",
            "sections": [],
            "references": [],
            "figures": [],
            "license": None,
        }

        title_elem = root.find(".//article-title")
        if title_elem is not None:
            result["title"] = element_text(title_elem)

        abstract_elem = root.find(".//abstract")
        if abstract_elem is not None:
            result["abstract"] = element_text(abstract_elem)

        body = root.find(".//body")
        if body is not None:
            body_paragraphs = [element_text(p) for p in body.findall("p")]
            if any(body_paragraphs):
                result["sections"].append({"title": "Body", "content": "\n\n".join(body_paragraphs)})
            for sec in body.findall(".//sec"):
                section = _parse_section(sec)
                if section:
                    result["sections"].append(section)

        result["figures"] = _parse_figures(root)
        result["license"] = _parse_license(root)

        ref_list = root.find(".//ref-list")
        if ref_list is not None:
            for ref in ref_list.findall(".//ref"):
                ref_data = _parse_reference(ref)
                if ref_data:
                    result["references"].append(ref_data)

        return result

    except Exception as exc:
        logger.warning("%s full-text XML parsing failed (%s)", source, type(exc).__name__)
        raise ParseError(
            f"{source} returned XML that could not be parsed",
            source=source,
        ) from exc


def element_text(elem: Element) -> str:
    """Recursively get all text from an element."""
    return "".join(elem.itertext()).strip()


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


def _parse_license(root: Element) -> dict[str, str] | None:
    """Return the article-level license statement exactly as declared.

    Only the ``<permissions>`` of the main article metadata are read; the
    adapter never infers reuse rights that the publisher did not declare.
    """
    permissions = root.find(".//article-meta/permissions")
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


def _parse_figures(root: Element) -> list[dict[str, Any]]:
    """Extract ``<fig>`` labels, captions and graphic references."""
    figures: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for fig_elem in root.iter("fig"):
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
