"""Format adapters for fulltext supplied by a host agent or user.

The application intake service owns validation, bounds and storage; this
module only turns JATS, HTML and PDF payloads into the shared section model
with the same parsers the provider routes use, so supplied and retrieved text
cannot drift apart structurally. The parsers return the identifiers the
document declares about itself so the service can refuse another article.
"""

from __future__ import annotations

from typing import Any

from pubmed_search.application.fulltext.intake import MAX_PARSE_TEXT_CHARS
from pubmed_search.application.fulltext.supplied import SuppliedFulltextError

from .fulltext_extract import FulltextExtractPhase
from .jats import parse_jats_article
from .pmc_html import HTMLParseLimitError, parse_article_html


class IntakeContentParsers:
    """Implements ``application.fulltext.intake.FulltextContentParser``."""

    def __init__(self, extractor: FulltextExtractPhase | None = None) -> None:
        self._extractor = extractor or FulltextExtractPhase()

    def parse_jats(self, xml: str) -> dict[str, Any]:
        """Parse supplied JATS with the shared PMC-family parser (main article only)."""
        if len(xml) > MAX_PARSE_TEXT_CHARS:
            raise SuppliedFulltextError("invalid_input", f"JATS must be at most {MAX_PARSE_TEXT_CHARS} characters")
        return parse_jats_article(xml, source="Supplied JATS")

    def parse_html(self, html: str) -> dict[str, Any]:
        """Parse supplied article HTML; PMC-shaped pages keep their full structure.

        Raises:
            SuppliedFulltextError: ``invalid_input`` when the HTML exceeds the
                size, element, section or nesting-depth bounds.
        """
        try:
            return parse_article_html(html)
        except HTMLParseLimitError as exc:
            raise SuppliedFulltextError("invalid_input", f"The HTML exceeds a parsing limit: {exc}") from None

    async def extract_pdf_text(self, data: bytes) -> str | None:
        """Extract PDF text off the event loop with the downloader's extractor."""
        return await self._extractor.extract_pdf_text(data)


__all__ = ["IntakeContentParsers"]
