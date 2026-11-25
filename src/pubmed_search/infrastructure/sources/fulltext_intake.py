"""Format adapters for fulltext supplied by a host agent or user.

The application intake service owns validation, bounds and storage; this
module only turns JATS, HTML and PDF payloads into the shared section model
with the same parsers the provider routes use, so supplied and retrieved text
cannot drift apart structurally.
"""

from __future__ import annotations

from typing import Any

from .fulltext_extract import FulltextExtractPhase
from .jats import parse_jats_article
from .pmc_html import parse_article_html


class IntakeContentParsers:
    """Implements ``application.fulltext.intake.FulltextContentParser``."""

    def __init__(self, extractor: FulltextExtractPhase | None = None) -> None:
        self._extractor = extractor or FulltextExtractPhase()

    def parse_jats(self, xml: str) -> dict[str, Any]:
        """Parse supplied JATS with the shared PMC-family parser (main article only)."""
        return parse_jats_article(xml, source="Supplied JATS")

    def parse_html(self, html: str) -> dict[str, Any]:
        """Parse supplied article HTML; PMC-shaped pages keep their full structure."""
        return parse_article_html(html)

    async def extract_pdf_text(self, data: bytes) -> str | None:
        """Extract PDF text off the event loop with the downloader's extractor."""
        return await self._extractor.extract_pdf_text(data)


__all__ = ["IntakeContentParsers"]
