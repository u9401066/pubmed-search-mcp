"""MCP registration and JSON formatting for ICD/MeSH conversion."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field

from pubmed_search.application.search import icd as _icd_service

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

logger = logging.getLogger(__name__)


def register_icd_tools(mcp: MCPServer) -> None:
    """Register the ICD conversion tool."""

    @mcp.tool()
    def convert_icd_mesh(
        direction: Literal["icd_to_mesh", "mesh_to_icd"],
        value: Annotated[str, Field(min_length=1, max_length=500)],
    ) -> str:
        """Query the curated ICD/MeSH crosswalk in one explicit direction.

        Use ``icd_to_mesh`` with one complete ICD-9-CM or ICD-10-CM code, or
        ``mesh_to_icd`` with a MeSH term. The returned mapping is a limited
        convenience crosswalk, not a substitute for a current licensed UMLS
        terminology service.
        """
        result = (
            _icd_service.lookup_icd_to_mesh(value)
            if direction == "icd_to_mesh"
            else _icd_service.lookup_mesh_to_icd(value)
        )
        return json.dumps(result, indent=2, ensure_ascii=False)

    logger.info("Registered ICD conversion tools (1 tool)")


__all__ = ["register_icd_tools"]
