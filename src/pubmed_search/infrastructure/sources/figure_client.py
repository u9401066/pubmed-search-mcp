"""
Figure Client - Extract figures from PMC Open Access articles.

Multi-source figure extraction with automatic fallback:
1. Europe PMC fullTextXML (JATS XML → parse <fig> elements)
2. PMC efetch XML (NCBI E-utilities)
3. PMC BioC JSON (captions only, may lack image URLs)

Image URL resolution strategies:
- Europe PMC CDN: https://europepmc.org/articles/{PMCID}/bin/{href}.jpg
- PMC HTML scraping: parse <img> tags from article page
- PMC OA Web Service: file listing from tar.gz package

Security: All resolved URLs are validated against an allowed-domain whitelist
to prevent SSRF attacks.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from defusedxml import ElementTree

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

from pubmed_search.domain.entities.figure import ArticleFigure, ArticleFiguresResult
from pubmed_search.infrastructure.sources.base_client import _CONTINUE, BaseAPIClient

logger = logging.getLogger(__name__)

# SSRF protection: only allow known academic image CDN domains
ALLOWED_IMAGE_DOMAINS = frozenset(
    {
        "cdn.ncbi.nlm.nih.gov",
        "europepmc.org",
        "www.europepmc.org",
        "www.ncbi.nlm.nih.gov",
        "pmc.ncbi.nlm.nih.gov",
        "ncbi.nlm.nih.gov",
        "ftp.ncbi.nlm.nih.gov",
    }
)

# JATS XML namespace for xlink
XLINK_NS = "http://www.w3.org/1999/xlink"
XLINK_HREF = f"{{{XLINK_NS}}}"

# Europe PMC image URL patterns
EPMC_IMAGE_BASE = "https://europepmc.org/articles"
# PMC article page for HTML scraping fallback
PMC_ARTICLE_BASE = "https://pmc.ncbi.nlm.nih.gov/articles"

# Common image extensions to try
IMAGE_EXTENSIONS = ("jpg", "jpeg", "gif", "png", "svg", "tif", "tiff")


def validate_image_url(url: str) -> bool:
    """Validate image URL against allowed domains (SSRF protection)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        return parsed.hostname in ALLOWED_IMAGE_DOMAINS
    except Exception:
        return False


class FigureClient(BaseAPIClient):
    """Extract article figures from PMC Open Access articles.

    Inherits BaseAPIClient for automatic retry, rate limiting,
    and circuit breaker protection.
    """

    _service_name = "PMC_Figures"

    def __init__(self, timeout: float = 30.0) -> None:
        super().__init__(
            base_url="",  # Multiple base URLs used
            timeout=timeout,
            min_interval=0.2,  # 5 req/sec max
        )

    async def get_article_figures(
        self,
        pmcid: str,
        pmid: str | None = None,
        include_subfigures: bool = False,
        include_tables: bool = False,
    ) -> ArticleFiguresResult:
        """Extract all figures from a PMC article.

        Tries multiple sources in order:
        1. Europe PMC fullTextXML
        2. PMC efetch XML (NCBI)
        3. PMC BioC JSON

        Args:
            pmcid: PMC ID (e.g., "PMC12086443")
            pmid: Optional PubMed ID
            include_subfigures: Parse sub-figures (A, B, C) separately
            include_tables: Also extract table images

        Returns:
            ArticleFiguresResult with figures and metadata
        """
        pmcid = _normalize_pmcid(pmcid)
        pmcid_numeric = pmcid.replace("PMC", "")

        result = ArticleFiguresResult(
            pmcid=pmcid,
            pmid=pmid,
        )

        # === Source 1: Europe PMC fullTextXML ===
        try:
            xml = await self._fetch_epmc_xml(pmcid)
            if xml:
                figures, title = self._parse_jats_figures(xml, pmcid, include_subfigures, include_tables)
                if figures is not None:
                    figures = await self._resolve_exact_image_urls_if_needed(pmcid, figures)
                    result.figures = figures
                    result.total_figures = len(figures)
                    result.article_title = title or ""
                    result.source = "europepmc"
                    # Add PDF link
                    result.pdf_links.append(
                        {
                            "source": "PubMed Central",
                            "url": f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/",
                            "type": "pdf",
                        }
                    )
                    result.pdf_links.append(
                        {
                            "source": "Europe PMC",
                            "url": f"https://europepmc.org/article/pmc/{pmcid}",
                            "type": "landing_page",
                        }
                    )
                    return result
        except Exception as e:
            logger.warning("Europe PMC figure extraction failed for %s: %s", pmcid, e)

        # === Source 2: PMC efetch XML (NCBI) ===
        try:
            xml = await self._fetch_pmc_efetch_xml(pmcid_numeric)
            if xml:
                figures, title = self._parse_jats_figures(xml, pmcid, include_subfigures, include_tables)
                if figures is not None:
                    figures = await self._resolve_exact_image_urls_if_needed(pmcid, figures)
                    result.figures = figures
                    result.total_figures = len(figures)
                    result.article_title = title or ""
                    result.source = "pmc_efetch"
                    result.pdf_links.append(
                        {
                            "source": "PubMed Central",
                            "url": f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/",
                            "type": "pdf",
                        }
                    )
                    return result
        except Exception as e:
            logger.warning("PMC efetch figure extraction failed for %s: %s", pmcid, e)

        # === Source 3: PMC BioC JSON (captions only) ===
        try:
            figures = await self._fetch_bioc_figures(pmcid)
            if figures:
                result.figures = figures
                result.total_figures = len(figures)
                result.source = "bioc"
                return result
        except Exception as e:
            logger.warning("BioC figure extraction failed for %s: %s", pmcid, e)

        # All sources failed
        result.error = "source_unavailable"
        result.error_detail = "All figure extraction sources failed"
        return result

    # =========================================================================
    # Source fetchers
    # =========================================================================

    async def _fetch_epmc_xml(self, pmcid: str) -> str | None:
        """Fetch JATS XML from Europe PMC REST API."""
        url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
        try:
            result = await self._make_request(
                url,
                headers={"Accept": "application/xml"},
                expect_json=False,
            )
            return result if isinstance(result, str) else None
        except Exception:
            return None

    async def _fetch_pmc_efetch_xml(self, pmcid_numeric: str) -> str | None:
        """Fetch JATS XML from NCBI PMC efetch."""
        url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={pmcid_numeric}&rettype=xml"
        try:
            result = await self._make_request(
                url,
                headers={"Accept": "application/xml"},
                expect_json=False,
            )
            return result if isinstance(result, str) else None
        except Exception:
            return None

    async def _fetch_bioc_figures(self, pmcid: str) -> list[ArticleFigure]:
        """Fetch figure captions from PMC BioC API (JSON)."""
        url = f"https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/{pmcid}/unicode"
        try:
            data = await self._make_request(url)
            if not isinstance(data, dict):
                return []
            return self._parse_bioc_figures(data)
        except Exception:
            return []

    # =========================================================================
    # JATS XML figure parsing
    # =========================================================================

    def _parse_jats_figures(
        self,
        xml_content: str,
        pmcid: str,
        include_subfigures: bool = False,
        include_tables: bool = False,
    ) -> tuple[list[ArticleFigure] | None, str | None]:
        """Parse <fig> elements from JATS XML.

        Returns:
            Tuple of (figures list or None on parse error, article title)
        """
        try:
            # Clean XML
            xml_content = re.sub(r"<\?xml[^>]*\?>", "", xml_content)
            xml_content = re.sub(r"<!DOCTYPE[^>]*>", "", xml_content)
            root = ElementTree.fromstring(xml_content)
        except Exception as e:
            logger.warning("Failed to parse JATS XML: %s", e)
            return None, None

        title_elem = root.find(".//article-title")
        title = self._get_element_text(title_elem) if title_elem is not None else None

        figures: list[ArticleFigure] = []

        # Parse <fig> elements (standard figures)
        for fig_elem in root.iter("fig"):
            fig = self._parse_fig_element(fig_elem, pmcid)
            if fig:
                figures.append(fig)

        # Parse <fig-group> elements (subfigure groups)
        if include_subfigures:
            for fig_group in root.iter("fig-group"):
                group_fig = self._parse_fig_group(fig_group, pmcid)
                if group_fig:
                    figures.append(group_fig)

        # Parse table images if requested
        if include_tables:
            for table_wrap in root.iter("table-wrap"):
                graphic = table_wrap.find(".//graphic")
                if graphic is not None:
                    table_fig = self._parse_fig_element(table_wrap, pmcid)
                    if table_fig:
                        figures.append(table_fig)

        # Deduplicate by figure_id (fig-group children may overlap with standalone fig)
        seen_ids: set[str] = set()
        unique_figures: list[ArticleFigure] = []
        for fig in figures:
            if fig.figure_id not in seen_ids:
                seen_ids.add(fig.figure_id)
                unique_figures.append(fig)

        # Find section references for each figure
        body = root.find(".//body")
        if body is not None:
            self._resolve_figure_references(unique_figures, body)

        return unique_figures, title

    def _parse_fig_element(self, fig_elem: Element, pmcid: str) -> ArticleFigure | None:
        """Parse a single <fig> element into ArticleFigure."""
        figure_id = fig_elem.get("id", "")
        label_elem = fig_elem.find("label")
        label = self._get_element_text(label_elem) if label_elem is not None else ""

        # Caption: <caption><title> and <caption><p>
        caption_elem = fig_elem.find("caption")
        caption_title = None
        caption_text = ""
        if caption_elem is not None:
            title_elem = caption_elem.find("title")
            if title_elem is not None:
                caption_title = self._get_element_text(title_elem)
            # Combine all <p> in caption
            caption_parts = []
            for p_elem in caption_elem.findall("p"):
                text = self._get_element_text(p_elem)
                if text:
                    caption_parts.append(text)
            caption_text = " ".join(caption_parts)

        # Graphic href
        graphic_href = self._extract_graphic_href(fig_elem)

        if not label and not graphic_href and not caption_text:
            return None

        # Resolve image URL
        image_url = self._resolve_image_url(pmcid, graphic_href)

        return ArticleFigure(
            figure_id=figure_id,
            label=label,
            caption_title=caption_title,
            caption_text=caption_text,
            image_url=image_url,
            graphic_href=graphic_href,
        )

    def _parse_fig_group(self, fig_group: Element, pmcid: str) -> ArticleFigure | None:
        """Parse a <fig-group> element with its sub-figures."""
        parent_fig = self._parse_fig_element(fig_group, pmcid)
        if not parent_fig:
            return None

        subfigures = []
        for child_fig in fig_group.findall("fig"):
            sub = self._parse_fig_element(child_fig, pmcid)
            if sub:
                subfigures.append(sub)

        if subfigures:
            parent_fig.subfigures = subfigures

        return parent_fig

    def _extract_graphic_href(self, elem: Element) -> str:
        """Extract xlink:href from <graphic> element."""
        graphic = elem.find("graphic")
        if graphic is not None:
            href = graphic.get(f"{XLINK_HREF}href", "")
            if href:
                return href
            # Try without namespace
            href = graphic.get("href", "")
            if href:
                return href
        # Try <alternatives><graphic>
        alternatives = elem.find("alternatives")
        if alternatives is not None:
            for g in alternatives.findall("graphic"):
                href = g.get(f"{XLINK_HREF}href", "")
                if href:
                    return href
        return ""

    def _resolve_image_url(self, pmcid: str, graphic_href: str) -> str | None:
        """Resolve graphic_href to an actual image URL.

        Strategy: Europe PMC CDN (deterministic, no extra HTTP request needed).
        """
        if not graphic_href:
            return None

        # Europe PMC CDN pattern (most reliable, deterministic)
        # Try common extensions
        for ext in ("jpg", "gif", "png"):
            url = f"{EPMC_IMAGE_BASE}/{pmcid}/bin/{graphic_href}.{ext}"
            if validate_image_url(url):
                return url

        # Fallback: PMC figure page URL (always valid as landing page)
        figure_page = f"{PMC_ARTICLE_BASE}/{pmcid}/"
        if validate_image_url(figure_page):
            return figure_page

        return None

    async def resolve_image_urls_from_html(self, pmcid: str, figures: list[ArticleFigure]) -> list[ArticleFigure]:
        """Resolve accurate image URLs by scraping the PMC article page.

        This is a more reliable fallback that gets the exact CDN URLs
        from the article HTML page.
        """
        url = f"{PMC_ARTICLE_BASE}/{pmcid}/"
        try:
            html = await self._make_request(
                url,
                headers={"Accept": "text/html"},
                expect_json=False,
            )
            if not isinstance(html, str):
                return figures

            # Parse <img> tags to extract CDN URLs
            img_pattern = re.compile(
                r'<img[^>]+src="(https://cdn\.ncbi\.nlm\.nih\.gov/pmc/blobs/[^"]+)"',
                re.IGNORECASE,
            )
            cdn_urls = img_pattern.findall(html)

            # Match CDN URLs to figures by graphic_href
            for fig in figures:
                if not fig.graphic_href:
                    continue
                for cdn_url in cdn_urls:
                    if fig.graphic_href in cdn_url:
                        if validate_image_url(cdn_url):
                            fig.image_url = cdn_url
                        break

            return figures
        except Exception as e:
            logger.warning("HTML scraping fallback failed for %s: %s", pmcid, e)
            return figures

    async def _resolve_exact_image_urls_if_needed(
        self, pmcid: str, figures: list[ArticleFigure]
    ) -> list[ArticleFigure]:
        """Upgrade guessed figure URLs to exact CDN image URLs when possible."""
        if not any(fig.graphic_href for fig in figures):
            return figures

        return await self.resolve_image_urls_from_html(pmcid, figures)

    def _resolve_figure_references(self, figures: list[ArticleFigure], body: Element) -> None:
        """Find which sections reference each figure."""
        for sec in body.findall(".//sec"):
            sec_title_elem = sec.find("title")
            sec_title = self._get_element_text(sec_title_elem) if sec_title_elem is not None else ""
            if not sec_title:
                continue

            sec_text = self._get_element_text(sec)
            for fig in figures:
                if fig.label and fig.label.lower() in sec_text.lower() and sec_title not in fig.mentioned_in_sections:
                    fig.mentioned_in_sections.append(sec_title)

    # =========================================================================
    # BioC JSON parsing
    # =========================================================================

    def _parse_bioc_figures(self, data: dict[str, Any]) -> list[ArticleFigure]:
        """Parse figure data from BioC JSON format."""
        figures: list[ArticleFigure] = []
        documents = data.get("documents", [])
        for doc in documents:
            for passage in doc.get("passages", []):
                infons = passage.get("infons", {})
                if infons.get("type") == "fig_title_caption" or infons.get("section_type") == "FIG":
                    fig_id = infons.get("id", "")
                    text = passage.get("text", "")
                    # Try to extract label from text
                    label_match = re.match(r"(Figure\s+\d+[A-Za-z]?)", text, re.IGNORECASE)
                    label = label_match.group(1) if label_match else ""
                    caption = text[len(label) :].strip(". ") if label else text

                    figures.append(
                        ArticleFigure(
                            figure_id=fig_id or f"bioc_fig_{len(figures)}",
                            label=label,
                            caption_text=caption,
                            # BioC doesn't provide image URLs
                            image_url=None,
                        )
                    )
        return figures

    # =========================================================================
    # Utility methods
    # =========================================================================

    @staticmethod
    def _get_element_text(elem: Element) -> str:
        """Recursively extract all text from an XML element."""
        text = elem.text or ""
        for child in elem:
            text += FigureClient._get_element_text(child)
            if child.tail:
                text += child.tail
        return text.strip()

    def _handle_expected_status(self, response: Any, url: str) -> dict[str, Any] | str | None:
        """Handle 404 (article not found) as expected."""
        if hasattr(response, "status_code") and response.status_code == 404:
            return {"error": "not_found"}
        return _CONTINUE  # type: ignore[return-value]


def _normalize_pmcid(pmcid: str) -> str:
    """Normalize PMCID to 'PMC{numbers}' format."""
    pmcid = str(pmcid).strip()
    if not pmcid.upper().startswith("PMC"):
        pmcid = f"PMC{pmcid}"
    return pmcid.upper()


# Singleton management
_figure_client: FigureClient | None = None


def get_figure_client() -> FigureClient:
    """Get or create FigureClient singleton."""
    global _figure_client
    if _figure_client is None:
        _figure_client = FigureClient()
    return _figure_client
