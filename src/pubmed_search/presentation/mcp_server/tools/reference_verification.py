"""Reference verification MCP tools.

This module provides the first-stage MCP-native reference verification entry
point: verify a structured reference list that a client has already extracted
from a file or clipboard.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from pubmed_search.application.reference_verification import ReferenceVerificationService

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)


def register_reference_verification_tools(mcp: FastMCP, searcher: LiteratureSearcher) -> None:
    """Register MCP tools for evidence-first reference verification."""

    service = ReferenceVerificationService(searcher)

    @mcp.tool()
    async def verify_reference_list(
        reference_text: str,
        source_name: str = "",
        max_references: int = 100,
    ) -> str:
        """Verify a plain-text reference list against PubMed evidence.

        First version scope:
            - Reference-list verification only
            - Client supplies the extracted reference list text
            - Backend parses entries and resolves them via PMID / DOI / ECitMatch

        Second version scope:
            - Adds unresolved review workflow for ``partial_match`` and ``unresolved`` rows
            - Returns a manual-review queue with retry queries and review checklist
            - Supports human-in-the-loop acceptance/rejection in client-side workflows

        Args:
            reference_text: Plain-text references, ideally one per line or a
                numbered reference list extracted from a file.
            source_name: Optional file label for reporting.
            max_references: Maximum number of references to process.

        Returns:
            JSON verification report with parsed fields, matched PubMed evidence,
            and per-reference verification status.
        """
        if not reference_text.strip():
            return json.dumps(
                {
                    "success": False,
                    "error": "Empty reference_text",
                    "hint": "Pass a plain-text reference list extracted from the user file",
                },
                ensure_ascii=False,
                indent=2,
            )

        try:
            report = await service.verify_reference_list(
                reference_text,
                source_name=source_name,
                limit=max_references,
            )
            return json.dumps(report, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.exception("verify_reference_list failed: %s", exc)
            return json.dumps(
                {
                    "success": False,
                    "error": str(exc),
                    "hint": "Check the reference list format and try again with fewer entries if needed",
                },
                ensure_ascii=False,
                indent=2,
            )
