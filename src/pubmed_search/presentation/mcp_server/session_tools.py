"""
Session Tools - PMID 持久化與 Session 管理

提供 Agent 存取 session 暫存資料的工具，解決記憶滿載問題。

Tools:
- read_session: 唯一的 session 讀取入口，透過明確 action 取得 PMID、文章、
  摘要、事件、artifact 與 durable search run。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field

from pubmed_search.domain.value_objects import normalize_pmid

if TYPE_CHECKING:
    from mcp.server.mcpserver import Context, MCPServer

    from pubmed_search.application.session.manager import SessionManager
    from pubmed_search.application.session.registry import SessionManagerRegistry

from pubmed_search.shared.settings import load_settings

from .tools.artifact_memory import artifact_locator
from .tools.tool_runtime import safe_send_resource_updated

logger = logging.getLogger(__name__)
_JSON_MIME_TYPE = "application/json"
DEFAULT_ARTIFACT_READ_MAX_CHARS = 200_000
DEFAULT_SESSION_EVENT_LIMIT = 50
DEFAULT_SESSION_HISTORY_LIMIT = 10
LAST_SEARCH_RESOURCE_ARTICLE_LIMIT = 20
MAX_SESSION_FILTER_CHARS = 500
MAX_SESSION_EVENT_LIMIT = 500
MAX_SESSION_HISTORY_LIMIT = 100
MAX_SESSION_OFFSET = 2_000_000_000
SearchRunStatus = Literal[
    "started",
    "planned",
    "running",
    "completed",
    "partial",
    "failed",
    "cancelled",
    "interrupted",
]
PMID = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$", max_length=20)]
SafeIdentifier = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,511}$", min_length=1, max_length=512),
]
SessionIdentifier = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$", min_length=1, max_length=80),
]
SessionFilter = Annotated[str, Field(min_length=1, max_length=MAX_SESSION_FILTER_CHARS)]
ArtifactUri = Annotated[
    str,
    Field(
        pattern=r"^artifact://[A-Za-z0-9][A-Za-z0-9_.-]{0,79}/[A-Za-z0-9][A-Za-z0-9_.-]{0,511}$",
        min_length=13,
        max_length=605,
    ),
]
ArtifactFile = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,511}$", min_length=1, max_length=512),
]
ArtifactReadSize = Annotated[int, Field(ge=1, le=DEFAULT_ARTIFACT_READ_MAX_CHARS)]
ArtifactOffset = Annotated[int, Field(ge=0, le=MAX_SESSION_OFFSET)]
SearchIndex = Annotated[int, Field(ge=-100_000, le=100_000)]
HistoryLimit = Annotated[int, Field(ge=1, le=MAX_SESSION_HISTORY_LIMIT)]
EventLimit = Annotated[int, Field(ge=1, le=MAX_SESSION_EVENT_LIMIT)]


class _StrictSessionRequest(BaseModel):
    """Base contract for one schema-exact session read operation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SessionPmidsRequest(_StrictSessionRequest):
    action: Literal["pmids"]
    search_index: SearchIndex = -1
    query_filter: SessionFilter | None = None


class SessionArticleRequest(_StrictSessionRequest):
    action: Literal["article"]
    pmid: PMID


class SessionSummaryRequest(_StrictSessionRequest):
    action: Literal["summary"]
    include_history: bool = False
    history_limit: HistoryLimit = DEFAULT_SESSION_HISTORY_LIMIT


class SessionLogRequest(_StrictSessionRequest):
    action: Literal["log"]
    event_limit: EventLimit = DEFAULT_SESSION_EVENT_LIMIT
    kind: SessionFilter | None = None
    include_history: bool = True
    history_limit: HistoryLimit = DEFAULT_SESSION_HISTORY_LIMIT


class SessionListArtifactsRequest(_StrictSessionRequest):
    action: Literal["list_artifacts"]
    session_id: SessionIdentifier | None = None
    tool: SessionFilter | None = None
    kind: SessionFilter | None = None
    include_local_paths: bool = False
    limit: HistoryLimit = DEFAULT_SESSION_HISTORY_LIMIT


class ArtifactIdLocator(_StrictSessionRequest):
    kind: Literal["artifact_id"]
    value: SafeIdentifier
    session_id: SessionIdentifier | None = None


class ArtifactUriLocator(_StrictSessionRequest):
    kind: Literal["artifact_uri"]
    value: ArtifactUri


ArtifactLocator = Annotated[ArtifactIdLocator | ArtifactUriLocator, Field(discriminator="kind")]


class SessionArtifactRequest(_StrictSessionRequest):
    action: Literal["artifact"]
    locator: ArtifactLocator
    artifact_file: ArtifactFile | None = None
    include_local_paths: bool = False
    max_chars: ArtifactReadSize = DEFAULT_ARTIFACT_READ_MAX_CHARS
    offset: ArtifactOffset = 0


class SessionSearchRunsRequest(_StrictSessionRequest):
    action: Literal["search_runs"]
    session_id: SessionIdentifier | None = None
    status: SearchRunStatus | None = None
    limit: HistoryLimit = DEFAULT_SESSION_HISTORY_LIMIT


class SessionSearchRunRequest(_StrictSessionRequest):
    action: Literal["search_run"]
    run_id: SafeIdentifier
    session_id: SessionIdentifier | None = None


class SessionReplaySearchRequest(_StrictSessionRequest):
    action: Literal["replay_search"]
    run_id: SafeIdentifier
    session_id: SessionIdentifier | None = None


SessionReadRequest = Annotated[
    SessionPmidsRequest
    | SessionArticleRequest
    | SessionSummaryRequest
    | SessionLogRequest
    | SessionListArtifactsRequest
    | SessionArtifactRequest
    | SessionSearchRunsRequest
    | SessionSearchRunRequest
    | SessionReplaySearchRequest,
    Field(discriminator="action"),
]
ResourceFunc = TypeVar("ResourceFunc", bound=Callable[..., str])
SESSION_RESOURCE_URIS = (
    "session://last-search",
    "session://last-search/pmids",
    "session://last-search/results",
    "session://activity",
    "session://context",
)


class _TenantScopedSessionManager:
    """Forward attributes through an installed tenant registry when present.

    Session tools and resources are registered once at startup, so capturing a
    manager in their closures must not pin multi-tenant callers to the startup
    tenant. A registry therefore resolves the current tenant at call time. In
    single-manager mode, the explicitly registered fallback remains authoritative
    instead of being replaced by unrelated process-global test or SDK state.
    """

    __slots__ = ("_fallback", "_registry")

    def __init__(
        self,
        fallback: SessionManager,
        registry: SessionManagerRegistry | None = None,
    ) -> None:
        self._fallback = fallback
        self._registry = registry

    def __getattr__(self, name: str) -> Any:
        target = self._registry.for_tenant() if self._registry is not None else self._fallback
        return getattr(target, name)


def _session_resource_kwargs(*, name: str, title: str, description: str) -> dict[str, object]:
    """Build consistent host-facing metadata for dynamic session resources."""
    return {
        "name": name,
        "title": title,
        "description": description,
        "mime_type": _JSON_MIME_TYPE,
        "meta": {"pubmedSearch": {"scope": "session", "dynamic": True, "format": "json"}},
    }


def _session_resource_decorator(mcp: MCPServer, uri: str, **kwargs: object) -> Callable[[ResourceFunc], ResourceFunc]:
    """Build one resource decorator against the canonical MCP SDK contract."""
    resource = cast("Any", mcp.resource)
    return cast("Callable[[ResourceFunc], ResourceFunc]", resource(uri, **kwargs))


async def notify_session_resources_updated(ctx: Context | None) -> None:
    """Best-effort session resource refresh notifications for hosts that support them."""
    if ctx is None:
        return

    session = getattr(ctx, "session", None)
    if session is None:
        return

    await asyncio.gather(*(safe_send_resource_updated(session, uri) for uri in SESSION_RESOURCE_URIS))


def _json_error(**payload: Any) -> str:
    """Serialize an error payload consistently for session tools."""
    payload.setdefault("success", False)
    return json.dumps(payload, ensure_ascii=False)


def _positive_limit(value: int, *, default: int) -> int:
    return value if value > 0 else default


def _allow_local_paths(requested: bool) -> bool:
    if not requested:
        return False
    return bool(load_settings().artifact_include_local_paths)


def _read_session_pmids_impl(
    session_manager: SessionManager,
    *,
    search_index: int = -1,
    query_filter: str | None = None,
) -> str:
    session = session_manager.get_current_session()
    if not session:
        return _json_error(error="No active session", hint="Run a search first to create a session")

    if not session.search_history:
        return _json_error(error="No search history", hint="Run unified_search first")

    if query_filter:
        matching = [
            (index, search)
            for index, search in enumerate(session.search_history)
            if query_filter.lower() in search.get("query", "").lower()
        ]
        if not matching:
            return _json_error(
                error=f"No searches matching '{query_filter}'",
                available_queries=[search.get("query", "")[:50] for search in session.search_history[-5:]],
            )
        index, search = matching[-1]
    else:
        try:
            search = session.search_history[search_index]
            index = search_index if search_index >= 0 else len(session.search_history) + search_index
        except IndexError:
            return _json_error(
                error=f"Invalid search_index: {search_index}", total_searches=len(session.search_history)
            )

    pmids = search.get("pmids", [])
    return json.dumps(
        {
            "success": True,
            "search_index": index,
            "run_id": search.get("run_id"),
            "status": search.get("status", "completed"),
            "query": search.get("query", ""),
            "timestamp": search.get("timestamp", ""),
            "total_pmids": len(pmids),
            "pmids": pmids,
            "pmids_csv": ",".join(pmids),
            "hint": "Use pmids_csv with prepare_export or get_citation_metrics",
        },
        ensure_ascii=False,
    )


def _read_cached_article_impl(session_manager: SessionManager, *, pmid: str) -> str:
    session = session_manager.get_current_session()
    if not session:
        return _json_error(
            error="No active session",
            hint="Article not in cache, use fetch_article_details instead",
        )

    article = session_manager.get_cached_article(pmid)
    if article is None:
        return _json_error(
            error=f"PMID {pmid} not in cache",
            cached_count=len(session_manager.get_session_cached_pmids()),
            hint="Use fetch_article_details to get from PubMed",
        )

    return json.dumps(
        {"success": True, "source": "cache", "article": article},
        ensure_ascii=False,
        indent=2,
    )


def _read_session_summary_impl(
    session_manager: SessionManager,
    *,
    include_history: bool = False,
    history_limit: int = 10,
) -> str:
    session = session_manager.get_current_session()
    if not session:
        return json.dumps(
            {
                "success": False,
                "has_session": False,
                "message": "No active session. Run a search to create one.",
            },
            ensure_ascii=False,
        )

    recent_searches = [
        {"query": search.get("query", "")[:60], "count": len(search.get("pmids", []))}
        for search in session.search_history[-5:]
    ]
    recent_runs = session_manager.list_search_runs(limit=5)
    status_counts = session_manager.get_search_run_status_counts()
    run_statuses = status_counts if isinstance(status_counts, dict) else {}
    cached_pmids = session_manager.get_session_cached_pmids(limit=100)

    result: dict[str, Any] = {
        "success": True,
        "has_session": True,
        "session_id": session.session_id,
        "topic": session.topic,
        "created_at": session.created_at,
        "stats": {
            "cached_articles": len(session_manager.get_session_cached_pmids()),
            "total_searches": len(session.search_history),
            "total_search_runs": sum(run_statuses.values()),
            "search_run_statuses": run_statuses,
            "event_entries": len(getattr(session, "event_log", [])),
            "reading_list_items": len(session.reading_list),
            "excluded_articles": len(session.excluded_pmids),
        },
        "recent_searches": recent_searches,
        "recent_search_runs": [
            {
                "run_id": run.get("run_id"),
                "query": str(run.get("query") or "")[:80],
                "status": run.get("status"),
                "result_count": (run.get("result") or {}).get("count", 0),
                "artifact_uri": (run.get("artifact") or {}).get("artifact_uri"),
            }
            for run in recent_runs
        ],
        "recent_events": [
            {
                "timestamp": event.get("timestamp", "")[:19],
                "kind": event.get("kind", ""),
                "message": event.get("message", ""),
            }
            for event in getattr(session, "event_log", [])[-5:]
        ],
        "cached_pmids_sample": cached_pmids[:20],
        "all_cached_pmids_csv": ",".join(cached_pmids[:100]),
        "hints": [
            'Use read_session(request={"action":"pmids"}) to get PMIDs from a specific search',
            'Use read_session(request={"action":"article","pmid":"..."}) to get article details from cache',
            "Use pmids='last' with prepare_export or get_citation_metrics",
            'Use read_session(request={"action":"log"}) to review session activity and debug history',
            'Use read_session(request={"action":"search_runs"}) to inspect recoverable unified_search runs',
        ],
    }

    if include_history:
        history_limit = _positive_limit(history_limit, default=DEFAULT_SESSION_HISTORY_LIMIT)
        history = session.search_history[-history_limit:]
        total = len(session.search_history)
        formatted_history: list[dict[str, Any]] = []
        for index, search in enumerate(history):
            actual_index = max(total - history_limit, 0) + index
            formatted_history.append(
                {
                    "index": actual_index,
                    "run_id": search.get("run_id"),
                    "query": search.get("query", "")[:80],
                    "status": search.get("status", "completed"),
                    "timestamp": search.get("timestamp", "")[:19],
                    "result_count": search.get("result_count", 0),
                    "pmid_count": len(search.get("pmids", [])),
                }
            )
        result["search_history"] = formatted_history
        result["hints"].append('Use read_session(request={"action":"pmids","search_index":index}) for one search')

    return json.dumps(result, ensure_ascii=False, indent=2)


def _read_session_log_impl(
    session_manager: SessionManager,
    *,
    event_limit: int = 50,
    kind: str | None = None,
    include_history: bool = True,
    history_limit: int = 10,
) -> str:
    session = session_manager.get_current_session()
    if not session:
        return _json_error(error="No active session", hint="Run a search first to create a session")

    events = session_manager.get_session_event_log(limit=event_limit, kind=kind)
    history_rows: list[dict[str, Any]] = []
    if include_history:
        history_limit = _positive_limit(history_limit, default=DEFAULT_SESSION_HISTORY_LIMIT)
        for search in session.search_history[-history_limit:]:
            history_rows.append(
                {
                    "query": search.get("query", "")[:80],
                    "run_id": search.get("run_id"),
                    "status": search.get("status", "completed"),
                    "timestamp": search.get("timestamp", "")[:19],
                    "result_count": search.get("result_count", 0),
                    "pmid_count": len(search.get("pmids", [])),
                }
            )

    available_kinds = sorted({str(event.get("kind", "")) for event in getattr(session, "event_log", []) if event})
    return json.dumps(
        {
            "success": True,
            "session_id": session.session_id,
            "topic": session.topic,
            "total_events": len(getattr(session, "event_log", [])),
            "returned_events": len(events),
            "event_kind_filter": kind,
            "available_event_kinds": available_kinds,
            "events": events,
            "search_history": history_rows,
            "hint": "Use kind='<event_kind>' to filter debug events by type",
        },
        ensure_ascii=False,
        indent=2,
    )


def _read_session_artifacts_impl(
    session_manager: SessionManager,
    *,
    session_id: str = "",
    tool: str | None = None,
    kind: str | None = None,
    include_local_paths: bool = False,
    limit: int = 20,
) -> str:
    try:
        session = session_manager.get_session(session_id) if session_id else session_manager.get_current_session()
    except ValueError as exc:
        logger.info("Rejected invalid session identifier: %s", type(exc).__name__)
        return _json_error(error="Unsafe or invalid session identifier")
    if not session:
        return _json_error(error="No active session", hint="Run a tool that creates artifacts first")

    limit = _positive_limit(limit, default=20)
    include_local_paths = _allow_local_paths(include_local_paths)
    artifacts = session_manager.list_artifacts(session_id=session_id or None, tool=tool, kind=kind, limit=limit)
    return json.dumps(
        {
            "success": True,
            "session_id": session.session_id,
            "total_artifacts": len(artifacts),
            "artifacts": [
                artifact_locator(artifact, include_local_paths=include_local_paths) for artifact in artifacts
            ],
            "hint": (
                'Use read_session(request={"action":"artifact","locator":'
                '{"kind":"artifact_id","value":"artifact-123"}}) to read one artifact.'
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


def _read_session_artifact_impl(
    session_manager: SessionManager,
    *,
    artifact_id: str,
    artifact_uri: str = "",
    session_id: str = "",
    artifact_file: str = "",
    include_local_paths: bool = False,
    max_chars: int = 200_000,
    offset: int = 0,
) -> str:
    if not artifact_id and not artifact_uri:
        return _json_error(
            error="artifact_id or artifact_uri is required for artifact action",
            hint='Use read_session(request={"action":"list_artifacts"}) first.',
        )
    include_local_paths = _allow_local_paths(include_local_paths)
    max_chars = _positive_limit(max_chars, default=DEFAULT_ARTIFACT_READ_MAX_CHARS)
    result = session_manager.read_artifact(
        artifact_id,
        artifact_uri=artifact_uri or None,
        session_id=session_id or None,
        file_name=artifact_file or None,
        max_chars=max_chars,
        offset=offset,
    )
    if isinstance(result.get("artifact"), dict):
        result["artifact"] = artifact_locator(result["artifact"], include_local_paths=include_local_paths)
    if not include_local_paths and isinstance(result.get("file"), dict):
        result["file"].pop("path", None)
    return json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
    )


def _read_search_runs_impl(
    session_manager: SessionManager,
    *,
    session_id: str = "",
    status: str = "",
    limit: int = 20,
) -> str:
    """List compact durable search-run envelopes for agent recovery."""
    session = session_manager.get_session(session_id) if session_id else session_manager.get_current_session()
    if session is None:
        return _json_error(error="No active session", hint="Run unified_search first")
    runs = session_manager.list_search_runs(
        session_id=session_id or None,
        status=status or None,
        limit=_positive_limit(limit, default=20),
    )
    return json.dumps(
        {
            "success": True,
            "session_id": session.session_id,
            "status_filter": status or None,
            "returned_runs": len(runs),
            "runs": [
                {
                    "run_id": run.get("run_id"),
                    "query": run.get("query"),
                    "status": run.get("status"),
                    "created_at": run.get("created_at"),
                    "updated_at": run.get("updated_at"),
                    "source_attempts": len(run.get("source_attempts") or []),
                    "result_count": (run.get("result") or {}).get("count", 0),
                    "artifact_uri": (run.get("artifact") or {}).get("artifact_uri"),
                    "recoverable": bool(run.get("recoverable")),
                }
                for run in runs
            ],
            "next_step": ('Use read_session(request={"action":"search_run","run_id":"..."}) for the full envelope.'),
        },
        ensure_ascii=False,
        indent=2,
    )


def _read_search_run_impl(
    session_manager: SessionManager,
    *,
    run_id: str,
    session_id: str = "",
) -> str:
    if not run_id:
        return _json_error(
            error="run_id is required",
            hint='Use read_session(request={"action":"search_runs"}) first',
        )
    session = session_manager.get_session(session_id) if session_id else session_manager.get_current_session()
    if session is None:
        return _json_error(error="No active session", hint="Run unified_search first")
    run = session_manager.get_search_run(run_id, session_id=session_id or None)
    if run is None:
        return _json_error(error=f"Search run not found: {run_id}")
    return json.dumps(
        {
            "success": True,
            "session_id": session.session_id,
            "run": run,
            "replay_available": bool(run.get("request")),
            "next_step": (
                'Use read_session(request={"action":"replay_search","run_id":"..."}) '
                "to obtain exact unified_search kwargs."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


def _read_search_replay_impl(
    session_manager: SessionManager,
    *,
    run_id: str,
    session_id: str = "",
) -> str:
    """Return replay instructions; replay remains an explicit agent decision."""
    if not run_id:
        return _json_error(
            error="run_id is required",
            hint='Use read_session(request={"action":"search_runs"}) first',
        )
    session = session_manager.get_session(session_id) if session_id else session_manager.get_current_session()
    if session is None:
        return _json_error(error="No active session", hint="Run unified_search first")
    replay = session_manager.get_search_run_replay(run_id, session_id=session_id or None)
    if replay is None:
        return _json_error(error=f"Search run not found: {run_id}")
    return json.dumps(
        {
            "success": True,
            "run_id": run_id,
            "replay": replay,
            "automatic_execution": False,
            "hint": "Call unified_search with replay.arguments to create a new, independently journaled run.",
        },
        ensure_ascii=False,
        indent=2,
    )


def _read_session_dispatch(
    session_manager: SessionManager,
    *,
    request: SessionReadRequest,
) -> str:
    if isinstance(request, SessionPmidsRequest):
        return _read_session_pmids_impl(
            session_manager,
            search_index=request.search_index,
            query_filter=request.query_filter,
        )
    if isinstance(request, SessionArticleRequest):
        return _read_cached_article_impl(session_manager, pmid=normalize_pmid(request.pmid))
    if isinstance(request, SessionLogRequest):
        return _read_session_log_impl(
            session_manager,
            event_limit=request.event_limit,
            kind=request.kind,
            include_history=request.include_history,
            history_limit=request.history_limit,
        )
    if isinstance(request, SessionListArtifactsRequest):
        return _read_session_artifacts_impl(
            session_manager,
            session_id=request.session_id or "",
            tool=request.tool,
            kind=request.kind,
            include_local_paths=request.include_local_paths,
            limit=request.limit,
        )
    if isinstance(request, SessionArtifactRequest):
        artifact_id = request.locator.value if isinstance(request.locator, ArtifactIdLocator) else ""
        artifact_uri = request.locator.value if isinstance(request.locator, ArtifactUriLocator) else ""
        session_id = request.locator.session_id if isinstance(request.locator, ArtifactIdLocator) else None
        return _read_session_artifact_impl(
            session_manager,
            artifact_id=artifact_id,
            artifact_uri=artifact_uri,
            session_id=session_id or "",
            artifact_file=request.artifact_file or "",
            include_local_paths=request.include_local_paths,
            max_chars=request.max_chars,
            offset=request.offset,
        )
    if isinstance(request, SessionSearchRunsRequest):
        return _read_search_runs_impl(
            session_manager,
            session_id=request.session_id or "",
            status=request.status or "",
            limit=request.limit,
        )
    if isinstance(request, SessionSearchRunRequest):
        return _read_search_run_impl(
            session_manager,
            run_id=request.run_id,
            session_id=request.session_id or "",
        )
    if isinstance(request, SessionReplaySearchRequest):
        return _read_search_replay_impl(
            session_manager,
            run_id=request.run_id,
            session_id=request.session_id or "",
        )
    if isinstance(request, SessionSummaryRequest):
        return _read_session_summary_impl(
            session_manager,
            include_history=request.include_history,
            history_limit=request.history_limit,
        )
    raise AssertionError(f"Unhandled session request model: {type(request).__name__}")


def register_session_tools(
    mcp: MCPServer,
    session_manager: SessionManager,
    *,
    session_registry: SessionManagerRegistry | None = None,
):
    """
    Register session tools for PMID persistence.

    These tools help Agent access cached data without
    relying on context memory.
    """
    session_manager = cast("SessionManager", _TenantScopedSessionManager(session_manager, session_registry))

    @mcp.tool()
    def read_session(request: SessionReadRequest) -> str:
        """Read session data through one schema-exact discriminated request.

        Actions:
        - pmids: return PMIDs for one recorded search
        - article: return one cached article payload
        - summary: return current session summary and optional history
        - list_artifacts: list persistent MCP output artifact manifests
        - artifact: read one persistent artifact by artifact_id or artifact_uri
        - search_runs: list durable unified_search run envelopes
        - search_run: read one run by stable run_id
        - replay_search: return credential-free unified_search replay arguments

        Each action accepts only its own fields. For remote artifact reads, select
        an artifact_id or artifact_uri locator and use artifact_file plus
        offset/max_chars to page through large files. Local paths remain redacted
        unless both include_local_paths and the server setting allow them.
        """
        try:
            return _read_session_dispatch(session_manager, request=request)
        except Exception as exc:
            logger.warning("read_session failed (%s)", type(exc).__name__)
            return _json_error(error="Session read failed")


def register_session_resources(
    mcp: MCPServer,
    session_manager: SessionManager,
    *,
    session_registry: SessionManagerRegistry | None = None,
):
    """
    Resources for debugging/monitoring only.
    Agent doesn't need to use these for normal operation.
    """
    session_manager = cast("SessionManager", _TenantScopedSessionManager(session_manager, session_registry))

    @_session_resource_decorator(
        mcp,
        "session://last-search",
        **cast(
            "Any",
            _session_resource_kwargs(
                name="session_last_search",
                title="Last Search Summary",
                description="Latest session search metadata and reusable PMID summary.",
            ),
        ),
    )
    def get_last_search() -> str:
        """Latest search metadata and quick agent-facing summary."""
        session = session_manager.get_current_session()
        if not session or not session.search_history:
            return json.dumps({"active": False, "has_last_search": False})

        last_search = session.search_history[-1]
        pmids = last_search.get("pmids", [])
        return json.dumps(
            {
                "active": True,
                "has_last_search": True,
                "query": last_search.get("query", ""),
                "timestamp": last_search.get("timestamp", ""),
                "result_count": last_search.get("result_count", 0),
                "pmid_count": len(pmids),
                "pmids": pmids,
            },
            ensure_ascii=False,
        )

    @_session_resource_decorator(
        mcp,
        "session://last-search/pmids",
        **cast(
            "Any",
            _session_resource_kwargs(
                name="session_last_search_pmids",
                title="Last Search PMIDs",
                description="PMID list from the latest recorded search for immediate reuse.",
            ),
        ),
    )
    def get_last_search_pmids() -> str:
        """PMIDs from the latest search for direct agent reuse."""
        session = session_manager.get_current_session()
        if not session or not session.search_history:
            return json.dumps({"active": False, "pmids": []})

        last_search = session.search_history[-1]
        pmids = last_search.get("pmids", [])
        return json.dumps(
            {
                "active": True,
                "query": last_search.get("query", ""),
                "pmids": pmids,
                "pmids_csv": ",".join(pmids),
            },
            ensure_ascii=False,
        )

    @_session_resource_decorator(
        mcp,
        "session://last-search/results",
        **cast(
            "Any",
            _session_resource_kwargs(
                name="session_last_search_results",
                title="Last Search Cached Results",
                description="Cached article payloads for the latest search PMIDs.",
            ),
        ),
    )
    def get_last_search_results() -> str:
        """Cached article payloads corresponding to the latest search PMIDs."""
        session = session_manager.get_current_session()
        if not session or not session.search_history:
            return json.dumps({"active": False, "results": []})

        last_search = session.search_history[-1]
        pmids = last_search.get("pmids", [])
        returned_pmids = pmids[:LAST_SEARCH_RESOURCE_ARTICLE_LIMIT]
        omitted_pmids = pmids[LAST_SEARCH_RESOURCE_ARTICLE_LIMIT:]
        cached_map, missing_pmids = session_manager.get_cached_article_map(returned_pmids)
        cached_articles = [cached_map[pmid] for pmid in returned_pmids if pmid in cached_map]
        return json.dumps(
            {
                "active": True,
                "query": last_search.get("query", ""),
                "result_count": last_search.get("result_count", 0),
                "total_pmid_count": len(pmids),
                "returned_pmid_count": len(returned_pmids),
                "resource_limit": LAST_SEARCH_RESOURCE_ARTICLE_LIMIT,
                "truncated": bool(omitted_pmids),
                "cached_results": cached_articles,
                "cached_count": len(cached_articles),
                "missing_pmids": missing_pmids,
                "omitted_pmids": omitted_pmids,
                "next_step": (
                    'Use read_session(request={"action":"pmids"}) then '
                    'read_session(request={"action":"article","pmid":"..."}) for more results.'
                ),
            },
            ensure_ascii=False,
        )

    @_session_resource_decorator(
        mcp,
        "session://activity",
        **cast(
            "Any",
            _session_resource_kwargs(
                name="session_activity",
                title="Session Activity Log",
                description="Recent session activity events plus search history for debugging and review.",
            ),
        ),
    )
    def get_session_activity() -> str:
        """Recent session activity and search history for user-facing review/debug."""
        session = session_manager.get_current_session()
        if not session:
            return json.dumps({"active": False, "events": [], "search_history": []})

        return json.dumps(
            {
                "active": True,
                "session_id": session.session_id,
                "topic": session.topic,
                "event_count": len(getattr(session, "event_log", [])),
                "events": session_manager.get_session_event_log(limit=25),
                "search_history": [
                    {
                        "query": search.get("query", "")[:80],
                        "timestamp": search.get("timestamp", "")[:19],
                        "result_count": search.get("result_count", 0),
                        "pmid_count": len(search.get("pmids", [])),
                    }
                    for search in session.search_history[-10:]
                ],
            },
            ensure_ascii=False,
        )

    @_session_resource_decorator(
        mcp,
        "session://context",
        **cast(
            "Any",
            _session_resource_kwargs(
                name="session_context",
                title="Session Context",
                description="Current research session context and cache summary.",
            ),
        ),
    )
    def get_session_context() -> str:
        """Internal: current session/cache context for debugging."""
        import json

        session = session_manager.get_current_session()
        if not session:
            return json.dumps({"active": False})

        return json.dumps(
            {
                "active": True,
                "session_id": session.session_id,
                "cached_articles": len(session_manager.get_session_cached_pmids()),
                "searches": len(session.search_history),
                "event_count": len(getattr(session, "event_log", [])),
                "cached_pmids": session_manager.get_session_cached_pmids(limit=50),
            }
        )
