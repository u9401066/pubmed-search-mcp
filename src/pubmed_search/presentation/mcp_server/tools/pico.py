"""MCP presentation wrapper for the agent-guided PICO application service."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from pubmed_search.application.search.pico_plan import (
    MAX_PICO_DESCRIPTION_CHARS,
    MAX_PICO_ELEMENT_CHARS,
    MAX_PICO_QUERY_CHARS,
    MAX_PICO_RESULTS,
    PICO_SOURCES,
    PicoPlanValidationError,
    PicoProfile,
    PicoSource,
    QuestionType,
    build_pico_search_plan,
)

from ._common import ResponseFormatter

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

logger = logging.getLogger(__name__)

PicoDescription = Annotated[str, Field(max_length=MAX_PICO_DESCRIPTION_CHARS)]
PicoElement = Annotated[str, Field(min_length=1, max_length=MAX_PICO_ELEMENT_CHARS)]
PicoQuery = Annotated[str, Field(min_length=1, max_length=MAX_PICO_QUERY_CHARS)]
PicoLimit = Annotated[int, Field(ge=1, le=MAX_PICO_RESULTS)]
PicoSources = Annotated[list[PicoSource], Field(min_length=1, max_length=len(PICO_SOURCES))]


def register_pico_tools(mcp: MCPServer) -> None:
    """Register the PICO handoff tool."""

    @mcp.tool()
    def validate_pico_plan(
        description: PicoDescription = "",
        p: PicoElement | None = None,
        i: PicoElement | None = None,
        c: PicoElement | None = None,
        o: PicoElement | None = None,
        p_query: PicoQuery | None = None,
        i_query: PicoQuery | None = None,
        c_query: PicoQuery | None = None,
        o_query: PicoQuery | None = None,
        question_type: QuestionType | None = None,
        profile: PicoProfile = "balanced",
        sources: PicoSources | None = None,
        limit: PicoLimit = 20,
    ) -> str:
        """Validate agent-provided P/I/C/O and return a runnable PICO pipeline.

        ``question_type`` and ``profile`` are closed enums. ``sources`` is an
        explicit array of supported unified-search providers; malformed values
        fail instead of being silently replaced. When ``question_type`` is
        omitted, the application service infers it from the clinical question.
        """

        try:
            result = build_pico_search_plan(
                description=description,
                p=p,
                i=i,
                c=c,
                o=o,
                p_query=p_query,
                i_query=i_query,
                c_query=c_query,
                o_query=o_query,
                question_type=question_type,
                profile=profile,
                sources=sources,
                limit=limit,
            )
        except PicoPlanValidationError as exc:
            return ResponseFormatter.error(
                exc,
                suggestion="Provide bounded PICO text and supported enum values",
                example='validate_pico_plan(description="...", p="...", i="...", sources=["pubmed"])',
                tool_name="validate_pico_plan",
                output_format="json",
            )

        logger.info("PICO handoff validated: complete=%s", not result["requires_agent_extraction"])
        return json.dumps(result, indent=2, ensure_ascii=False)


__all__ = ["register_pico_tools"]
