"""MCP requests for an agent's durable, tenant-owned research workspace."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from pubmed_search.application.research_workspace import ResearchWorkspaceService
from pubmed_search.infrastructure.research_workspace import SQLiteResearchWorkspaceStore
from pubmed_search.presentation.mcp_server.tenancy import durable_storage_denied
from pubmed_search.presentation.mcp_server.tool_contracts import MAX_MCP_TEXT_RESPONSE_CHARS
from pubmed_search.shared.tenancy import current_tenant

from .tool_response import ResponseFormatter
from .tool_session import get_session_registry

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer


WorkspaceId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$", max_length=96)]
PageSize = Annotated[int, Field(ge=1, le=100)]
Cursor = Annotated[int, Field(ge=0, le=2**63 - 1)]
SourceRef = Annotated[str, Field(min_length=1, max_length=512)]
ShortText = Annotated[str, Field(min_length=1, max_length=1000)]
RecordIds = Annotated[list[WorkspaceId], Field(max_length=32)]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class _CreateWorkspace(_Request):
    action: Literal["create"]
    workspace_id: WorkspaceId
    question: Annotated[str, Field(min_length=1, max_length=2000)]


class _ReadWorkspace(_Request):
    action: Literal["read"]
    workspace_id: WorkspaceId
    after: Cursor | None = Field(default=None, description="Sequence cursor; omit for the most recent records.")
    open_offset: Cursor = Field(default=0, description="Offset into the list of open actions.")
    limit: PageSize = 25


class _ListWorkspaces(_Request):
    action: Literal["list"]
    offset: Cursor = 0
    limit: PageSize = 25


class _RecordActivity(_Request):
    action: Literal["record"]
    workspace_id: WorkspaceId
    record_id: WorkspaceId = Field(description="Stable ID for this observation; reuse the ID when retrying.")
    activity: Literal["explore", "expand", "examine", "explain"]
    note: Annotated[str, Field(min_length=1, max_length=4000)]
    source_refs: Annotated[list[SourceRef], Field(max_length=32)] | None = Field(
        default=None, description="Namespaced source or saved-object identifiers such as pmid:3878092."
    )
    evidence_scope: Literal["none", "metadata", "abstract", "fulltext"] = "none"
    locator: ShortText | None = Field(default=None, description="Passage or section actually inspected in a source.")
    parent_ids: RecordIds | None = None
    next_action: ShortText | None = None
    resolves: RecordIds | None = Field(default=None, description="Earlier records whose open actions this resolves.")
    actor: Literal["agent", "human"] = "agent"


WorkspaceRequest = Annotated[
    _CreateWorkspace | _ReadWorkspace | _ListWorkspaces | _RecordActivity,
    Field(discriminator="action"),
]


def _encode_page(request: _ReadWorkspace | _ListWorkspaces, page: dict[str, Any]) -> str:
    """Reduce large pages without splitting a record or skipping the next cursor."""
    limit = (
        len(page["workspaces"])
        if isinstance(request, _ListWorkspaces)
        else max(len(page["records"]), len(page["open_actions"]))
    )
    while True:
        encoded = json.dumps(page, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) <= MAX_MCP_TEXT_RESPONSE_CHARS or limit <= 1:
            return encoded
        limit = max(1, limit // 2)
        page["page_limited_by_transport"] = True
        if isinstance(request, _ListWorkspaces):
            if len(page["workspaces"]) > limit:
                page["workspaces"] = page["workspaces"][:limit]
                page["next_offset"] = request.offset + limit
            continue
        records = page["records"]
        if len(records) > limit:
            if request.after is None:
                page["records"] = records[-limit:]
            else:
                page["records"] = records[:limit]
                page["next_after"] = records[limit - 1]["sequence"]
        if len(page["open_actions"]) > limit:
            page["open_actions"] = page["open_actions"][:limit]
            page["next_open_offset"] = request.open_offset + limit


def _execute(root: str, request: WorkspaceRequest) -> str:
    service = ResearchWorkspaceService(SQLiteResearchWorkspaceStore(root))
    if isinstance(request, _CreateWorkspace):
        return json.dumps(service.create(request.workspace_id, request.question), ensure_ascii=False)
    if isinstance(request, _ListWorkspaces):
        return _encode_page(request, service.list_workspaces(offset=request.offset, limit=request.limit))
    if isinstance(request, _ReadWorkspace):
        page = service.read(
            request.workspace_id, after=request.after, limit=request.limit, open_offset=request.open_offset
        )
        return _encode_page(request, page)
    return json.dumps(service.record(**request.model_dump(exclude={"action"})), ensure_ascii=False)


def register_research_workspace_tools(mcp: MCPServer) -> None:
    """Register the local research journal without initializing storage at startup."""

    @mcp.tool()
    async def research_workspace(request: WorkspaceRequest) -> str:
        """Create, record, list or resume a research workspace across sessions.

        Use create with a stable workspace_id and question. Record explore,
        expand, examine or explain activities with source_refs, parent_ids
        and a next_action. Use resolves to close an earlier record's action.
        Every record remains an unverified observation. Set evidence_scope to
        what was inspected; fulltext requires source_refs and a passage locator.
        Read returns recent records and open actions. Set after=0 to page from
        the beginning. Follow next_after and next_open_offset for subsequent
        pages. Large responses may return fewer than the requested limit.
        """
        denied = durable_storage_denied("research_workspace", output_format="json")
        if denied:
            return denied
        registry = get_session_registry()
        root = registry.tenant_data_dir(current_tenant().tenant_id) if registry else None
        if not root:
            return ResponseFormatter.error(
                "Research workspace storage is unavailable", tool_name="research_workspace", output_format="json"
            )
        try:
            return await asyncio.to_thread(_execute, root, request)
        except ValueError as exc:
            return ResponseFormatter.error(exc, tool_name="research_workspace", output_format="json")
        except (OSError, sqlite3.Error):
            return ResponseFormatter.error(
                "Could not access research workspace storage",
                suggestion="Check data directory availability and retry with the same workspace and record IDs.",
                tool_name="research_workspace",
                output_format="json",
            )
