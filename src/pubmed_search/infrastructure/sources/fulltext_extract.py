"""Fulltext extract phase for turning retrieved payloads into usable text.

Design:
    This module is the terminal phase of the downloader pipeline. It converts
    retrieved PDF or XML content into normalized text and section structures
    without knowing how the content was discovered or fetched.

Maintenance:
    Keep extraction backends and XML parsing adapters isolated here. If a new
    parser is added, preserve the current best-effort fallback behavior rather
    than leaking parser-specific logic back into the facade.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class FulltextExtractPhase:
    """Extract phase for structured XML and PDF text content."""

    def __init__(self, europe_pmc_client_factory: Callable[[], Any] | None = None) -> None:
        self._europe_pmc_client_factory = europe_pmc_client_factory

    async def extract_pdf_text(self, pdf_bytes: bytes | None) -> str | None:
        if not pdf_bytes:
            return None

        try:
            import fitz

            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text_parts: list[str] = []
            for page in doc:
                text = page.get_text()
                if text.strip():
                    text_parts.append(text)
            doc.close()
            if text_parts:
                return "\n\n".join(text_parts)
        except ImportError:
            logger.debug("PyMuPDF not available, trying pdfplumber")
        except Exception as exc:
            logger.warning("PyMuPDF extraction failed: %s", exc)

        try:
            import io

            import pdfplumber

            text_parts = []
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
            if text_parts:
                return "\n\n".join(text_parts)
        except ImportError:
            logger.warning("No PDF extraction library available (install PyMuPDF or pdfplumber)")
        except Exception as exc:
            logger.warning("pdfplumber extraction failed: %s", exc)

        return None

    async def get_structured_fulltext(self, pmcid: str) -> dict[str, Any] | None:
        try:
            if self._europe_pmc_client_factory is None:
                from pubmed_search.infrastructure.sources import get_europe_pmc_client

                client = get_europe_pmc_client()
            else:
                client = self._europe_pmc_client_factory()

            xml = await client.get_fulltext_xml(pmcid)
            if not xml:
                return None

            parsed = client.parse_fulltext_xml(xml)
            if not parsed:
                return None

            text_parts: list[str] = []
            sections: dict[str, str] = {}
            if parsed.get("abstract"):
                text_parts.append(f"ABSTRACT\n{parsed['abstract']}")
                sections["abstract"] = parsed["abstract"]

            for section in parsed.get("sections", []):
                title = section.get("title", "")
                content = section.get("content", "")
                if not content:
                    continue
                text_parts.append(f"{title.upper()}\n{content}")
                sections[title.lower()] = content

            return {
                "text": "\n\n".join(text_parts),
                "sections": sections,
                "title": parsed.get("title"),
                "references": parsed.get("references"),
            }
        except Exception as exc:
            logger.debug("Structured fulltext failed: %s", exc)
            return None


__all__ = ["FulltextExtractPhase"]
