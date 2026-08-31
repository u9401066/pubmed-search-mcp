"""Reference verification MCP tools.

This module provides the first-stage MCP-native reference verification entry
point: verify a structured reference list that a client has already extracted
from a file or clipboard.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from pubmed_search.application.reference_verification import (
    MAX_REFERENCE_TEXT_CHARS,
    MAX_REFERENCES,
    MAX_SOURCE_NAME_CHARS,
    ReferenceVerificationInputError,
    ReferenceVerificationService,
)

from .tool_response import ResponseFormatter

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)

ReferenceText = Annotated[
    str,
    Field(min_length=1, max_length=MAX_REFERENCE_TEXT_CHARS),
]
ReferenceSourceName = Annotated[str, Field(max_length=MAX_SOURCE_NAME_CHARS)]
ReferenceLimit = Annotated[int, Field(ge=1, le=MAX_REFERENCES)]


def register_reference_verification_tools(mcp: MCPServer, searcher: LiteratureSearcher) -> None:
    """Register MCP tools for evidence-first reference verification."""

    service = ReferenceVerificationService(searcher)

    @mcp.tool()
    async def verify_reference_list(
        reference_text: ReferenceText,
        source_name: ReferenceSourceName = "",
        max_references: ReferenceLimit = 100,
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
                numbered reference list extracted from a file. Limited to
                200,000 characters / 400,000 UTF-8 bytes; each entry is limited
                to 4,000 characters / 8,000 UTF-8 bytes.
            source_name: Optional single-line file label for reporting (up to
                255 characters / 512 UTF-8 bytes).
            max_references: Hard input-entry limit from 1 through 200. Inputs
                above the selected limit are rejected instead of truncated.

        Returns:
            JSON verification report with parsed fields, matched PubMed evidence,
            per-reference verification status, and explicit
            ``source_unavailable`` / ``not_checked`` rows when evidence could
            not be assessed.
        """
        if not reference_text.strip():
            return ResponseFormatter.error(
                error="Empty reference_text",
                suggestion="Pass a plain-text reference list extracted from the user file",
                tool_name="verify_reference_list",
                output_format="json",
            )

        try:
            report = await service.verify_reference_list(
                reference_text,
                source_name=source_name,
                limit=max_references,
            )
            return json.dumps(report, ensure_ascii=False, indent=2)
        except ReferenceVerificationInputError as exc:
            return ResponseFormatter.error(
                error=exc,
                suggestion="Check the reference-list boundaries and source label",
                tool_name="verify_reference_list",
                output_format="json",
            )
        except Exception as exc:
            logger.warning("verify_reference_list failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                error="Reference verification could not be completed",
                suggestion="Check the reference-list boundaries and retry unavailable sources later",
                tool_name="verify_reference_list",
                output_format="json",
            )
