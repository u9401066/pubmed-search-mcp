"""Machine-readable safety contracts for PubMed MCP tools."""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, Icon, InputRequiredResult, TextContent, ToolAnnotations
from pydantic import ValidationError

if TYPE_CHECKING:
    from mcp.server.mcpserver import Context

    from .tools.tool_session import ToolSessionRuntime

_CallableT = TypeVar("_CallableT", bound=Callable[..., Any])

_INVALID_ARGUMENTS_MESSAGE = (
    "Invalid tool arguments. Consult tools/list inputSchema and retry with exact field names and JSON value types."
)
_TOOL_EXECUTION_ERROR_MESSAGE = "Tool execution failed. Retry later or use a narrower request."
MAX_MCP_TEXT_RESPONSE_CHARS = 500_000
_RESPONSE_BUDGET_MESSAGE = (
    "Tool response exceeded the 500000-character transport budget. Narrow the request, request fewer records, "
    "or use the tool's artifact/session output when available."
)

_WRITE_TOOLS = {
    "build_research_chronicle",
    "configure_institutional_access",
    "delete_pipeline",
    "get_fulltext",
    "prepare_export",
    "save_literature_notes",
    "save_pipeline",
    "schedule_pipeline",
    "unified_search",
    "unschedule_pipeline",
}
_DESTRUCTIVE_TOOLS = {
    "configure_institutional_access",
    "delete_pipeline",
    "save_literature_notes",
    "save_pipeline",
    "schedule_pipeline",
    "unschedule_pipeline",
}
_NON_IDEMPOTENT_TOOLS = {
    "build_research_chronicle",
    "get_fulltext",
    "prepare_export",
    "save_literature_notes",
    "save_pipeline",
    "schedule_pipeline",
    "unified_search",
}
_LOCAL_ONLY_TOOLS = {
    "analyze_search_query",
    "configure_institutional_access",
    "convert_icd_mesh",
    "delete_pipeline",
    "get_pipeline_history",
    "list_pipelines",
    "list_resolver_presets",
    "load_pipeline",
    "validate_pico_plan",
    "read_research_chronicle",
    "read_session",
    "save_pipeline",
    "unschedule_pipeline",
}

logger = logging.getLogger(__name__)


def _is_error_payload(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("success") is False or value.get("status") in ("error", "failed"):
        return True
    search_status = value.get("search_status")
    return (
        value.get("tool") == "unified_search"
        and isinstance(search_status, dict)
        and search_status.get("state") == "failed"
    )


def _looks_like_tool_error(value: Any) -> bool:
    """Recognize canonical public error envelopes without treating no-results as failure."""
    if isinstance(value, CallToolResult):
        if value.is_error:
            return True
        structured = value.structured_content
        if _is_error_payload(structured):
            return True
        return bool(value.content) and _looks_like_tool_error(value.content)
    if isinstance(value, str):
        text = value.lstrip()
        if text.startswith(("❌", "Error:", "Error ", "success: false\n")):
            return True
        if text.startswith("{"):
            try:
                payload = json.loads(text)
            except (TypeError, ValueError):
                return False
            return _is_error_payload(payload)
        if text.startswith(("tool:", "type:", "status:", "success:")):
            import toons

            try:
                return _is_error_payload(toons.loads(text))
            except (TypeError, ValueError):
                return False
        return False
    if isinstance(value, list) and value:
        first = value[0]
        return isinstance(first, TextContent) and _looks_like_tool_error(first.text)
    return False


def _text_response_size(value: CallToolResult) -> int:
    """Return total Unicode characters carried by textual MCP content blocks."""
    return sum(len(block.text) for block in value.content if isinstance(block, TextContent))


def _category_for(tool_name: str) -> str:
    from .tool_registry import TOOL_CATEGORIES

    for category, metadata in TOOL_CATEGORIES.items():
        if tool_name in metadata["tools"]:
            return category
    raise ValueError(f"Unknown canonical MCP tool: {tool_name}")


def tool_annotations(tool_name: str) -> ToolAnnotations:
    """Return explicit MCP safety hints for one tool."""
    read_only = tool_name not in _WRITE_TOOLS
    return ToolAnnotations(
        title=tool_name.replace("_", " ").title(),
        read_only_hint=read_only,
        destructive_hint=tool_name in _DESTRUCTIVE_TOOLS,
        idempotent_hint=tool_name not in _NON_IDEMPOTENT_TOOLS,
        open_world_hint=tool_name not in _LOCAL_ONLY_TOOLS,
    )


def tool_meta(tool_name: str) -> dict[str, Any]:
    """Return namespaced contract metadata consumed by agent clients."""
    annotations = tool_annotations(tool_name)
    side_effect = "none"
    if annotations.destructive_hint:
        side_effect = "destructive"
    elif not annotations.read_only_hint:
        side_effect = "write"
    return {
        "pubmed-search": {
            "contractVersion": 3,
            "category": _category_for(tool_name),
            "sideEffect": side_effect,
        }
    }


class PubMedMCPServer(MCPServer[Any]):
    """MCP server that makes safety and side-effect contracts mandatory."""

    _pubmed_tool_session_runtime: ToolSessionRuntime | None = None

    def install_tool_session_runtime(self, runtime: ToolSessionRuntime) -> None:
        """Install dependencies owned exclusively by this server instance.

        Registration calls this before adding tools. The tool decorator reads
        the installed value at invocation time so direct calls through the SDK
        tool manager receive the same isolation as protocol calls.
        """
        from .tools.tool_session import ToolSessionRuntime

        if not isinstance(runtime, ToolSessionRuntime):
            raise TypeError("runtime must be a ToolSessionRuntime")
        self._pubmed_tool_session_runtime = runtime

    def get_tool_session_runtime(self) -> ToolSessionRuntime:
        """Return this server's installed runtime or fail closed."""
        runtime = getattr(self, "_pubmed_tool_session_runtime", None)
        if runtime is None:
            raise RuntimeError("Tool session runtime is not installed")
        return runtime

    def _scope_tool_callable(self, fn: _CallableT) -> _CallableT:
        """Wrap a registered callable in this server's context-local runtime."""
        from .tools.tool_session import bind_tool_session_runtime

        if inspect.iscoroutinefunction(fn):

            @wraps(fn)
            async def async_scoped(*args: Any, **kwargs: Any) -> Any:
                runtime = getattr(self, "_pubmed_tool_session_runtime", None)
                if runtime is None:
                    return await fn(*args, **kwargs)
                with bind_tool_session_runtime(runtime):
                    return await fn(*args, **kwargs)

            return async_scoped  # type: ignore[return-value]

        @wraps(fn)
        def sync_scoped(*args: Any, **kwargs: Any) -> Any:
            runtime = getattr(self, "_pubmed_tool_session_runtime", None)
            if runtime is None:
                return fn(*args, **kwargs)
            with bind_tool_session_runtime(runtime):
                return fn(*args, **kwargs)

        return sync_scoped  # type: ignore[return-value]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context[Any, Any] | None = None,
    ) -> CallToolResult | InputRequiredResult:
        """Execute a tool without exposing rejected values or exception details.

        Pydantic includes ``input_value`` in validation messages. Those values
        can contain credentials or other sensitive user input, so validation
        failures are replaced at the server boundary before the MCP transport
        can render or log the SDK's ``ToolError`` text. Unexpected tool
        failures use the same fail-closed policy because exception messages can
        carry upstream URLs, response bodies, credentials, or local paths.
        """
        try:
            result = await super().call_tool(name, arguments, context)
        except ToolError as exc:
            if not isinstance(exc.__cause__, ValidationError):
                cause = exc.__cause__
                logger.warning(
                    "MCP tool execution failed (%s)",
                    type(cause).__name__ if cause is not None else "ToolError",
                )
                return CallToolResult(
                    content=[TextContent(type="text", text=_TOOL_EXECUTION_ERROR_MESSAGE)],
                    is_error=True,
                )
            return CallToolResult(
                content=[TextContent(type="text", text=_INVALID_ARGUMENTS_MESSAGE)],
                is_error=True,
            )
        if isinstance(result, CallToolResult):
            if _text_response_size(result) > MAX_MCP_TEXT_RESPONSE_CHARS:
                return CallToolResult(
                    content=[TextContent(type="text", text=_RESPONSE_BUDGET_MESSAGE)],
                    is_error=True,
                )
            if not result.is_error and _looks_like_tool_error(result):
                return result.model_copy(update={"is_error": True})
        return result

    def tool(
        self,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
        meta: dict[str, Any] | None = None,
        structured_output: bool | None = None,
    ) -> Callable[[_CallableT], _CallableT]:
        if callable(name):
            raise TypeError("Use @tool() rather than @tool")

        def decorator(fn: _CallableT) -> _CallableT:
            tool_name = name or fn.__name__
            resolved_meta = tool_meta(tool_name)
            if meta:
                resolved_meta.update(meta)
            scoped_fn = self._scope_tool_callable(fn)
            registered = super(PubMedMCPServer, self).tool(
                name=name,
                title=title,
                description=description,
                annotations=annotations or tool_annotations(tool_name),
                icons=icons,
                meta=resolved_meta,
                # Canonical tools currently return Markdown or encoded JSON/
                # TOON strings (and one multimodal Content list), not typed
                # Python payloads. Do not advertise the SDK's misleading
                # auto-generated ``{result: string}`` output schema.
                structured_output=False if structured_output is None else structured_output,
            )(scoped_fn)

            # MCP SDK 2.x argument models otherwise use Pydantic's default
            # ``extra="ignore"`` behavior: misspelled fields disappear and a
            # call can appear to succeed with different intent. Apply one
            # server-wide fail-closed contract and publish it in JSON Schema.
            tool = self._tool_manager.get_tool(tool_name)
            if tool is None:  # pragma: no cover - registration invariant
                raise RuntimeError(f"Registered tool {tool_name!r} is unavailable")
            argument_model = tool.fn_metadata.arg_model
            argument_model.model_config["extra"] = "forbid"
            argument_model.model_config["strict"] = True
            argument_model.model_rebuild(force=True)
            tool.parameters = argument_model.model_json_schema(by_alias=True)
            # MCP SDK 2.x intentionally decodes JSON-looking string arguments
            # for legacy clients before Pydantic sees them. This server's v3
            # contract is schema-exact: arrays and objects must arrive as real
            # JSON values, so bypass that compatibility coercion centrally.
            object.__setattr__(tool.fn_metadata, "pre_parse_json", lambda data: data.copy())
            del registered
            return fn

        return decorator


__all__ = ["MAX_MCP_TEXT_RESPONSE_CHARS", "PubMedMCPServer", "tool_annotations", "tool_meta"]
