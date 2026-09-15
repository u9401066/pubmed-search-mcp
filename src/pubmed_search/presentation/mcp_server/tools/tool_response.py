"""Response formatting helpers for MCP tool outputs.

Design:
    This module owns consistent success, error, and no-result rendering across
    markdown and structured output modes. It keeps formatting concerns separate
    from tool business logic.

Maintenance:
    Extend formatter behavior here when new output formats or shared response
    conventions are introduced. Avoid embedding tool-specific branching so the
    formatting surface remains reusable across the MCP server.
"""

from __future__ import annotations

import re
from typing import Any, Union
from urllib.parse import urlsplit, urlunsplit

from pubmed_search.shared import PubMedSearchError, get_retry_delay, is_retryable_error
from pubmed_search.shared import markdown as safe_markdown
from pubmed_search.shared.credential_sanitizer import redact_credential_assignments

_URL_RE = re.compile(r"https?://[^\s<>()\[\]{}]+", re.IGNORECASE)
_UNIX_PATH_RE = re.compile(r"(?<![\w:/])/(?:[^/\s]+/)*[^/\s]+")
_WINDOWS_PATH_RE = re.compile(r"(?i)(?<![\w])\b[A-Z]:\\(?:[^\\\r\n]+\\)*[^\\\r\n]+")
_HOME_PATH_RE = re.compile(r"(?<!\w)~/(?:[^/\s]+/)*[^/\s]+")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]")
_MAX_PUBLIC_ERROR_CHARS = 600


def _redact_url(url: str) -> str:
    """Keep only network origin for URL diagnostics; paths may contain secrets."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        redacted = urlunsplit((parsed.scheme, host, "", "", ""))
        return (
            f"{redacted}?[REDACTED]" if parsed.path or parsed.query or parsed.fragment or parsed.username else redacted
        )
    except (TypeError, ValueError):
        return "[REDACTED URL]"


def _safe_public_message(value: object) -> str:
    """Create a bounded, credential-safe public diagnostic string."""
    if isinstance(value, Exception):
        module_root = type(value).__module__.partition(".")[0]
        if module_root in {"aiohttp", "httpcore", "httpx", "requests", "urllib3"}:
            return f"{type(value).__name__}: external request failed"
    text = redact_credential_assignments(str(value or "Unknown error"))
    text = _URL_RE.sub(lambda match: _redact_url(match.group(0)), text)
    text = _WINDOWS_PATH_RE.sub("[LOCAL PATH REDACTED]", text)
    text = _UNIX_PATH_RE.sub("[LOCAL PATH REDACTED]", text)
    text = _HOME_PATH_RE.sub("[LOCAL PATH REDACTED]", text)
    text = _CONTROL_RE.sub("", text)
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if len(text) > _MAX_PUBLIC_ERROR_CHARS:
        text = text[: _MAX_PUBLIC_ERROR_CHARS - 1] + "…"
    return text or "Unknown error"


class ResponseFormatter:
    """Unified response formatter for consistent MCP tool outputs."""

    @staticmethod
    def success(
        data: Any,
        message: str | None = None,
        metadata: dict | None = None,
        output_format: str = "markdown",
    ) -> str:
        import json

        from .agent_output import is_structured_output_format, serialize_structured_payload

        if is_structured_output_format(output_format):
            result = {"success": True, "data": data}
            if message:
                result["message"] = message
            if metadata:
                result["metadata"] = metadata
            return serialize_structured_payload(result, output_format)

        parts = []
        if message:
            parts.append(f"✅ {message}\n")

        if isinstance(data, str):
            parts.append(data)
        elif isinstance(data, (list, dict)):
            parts.append(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            parts.append(str(data))

        if metadata:
            parts.append(f"\n---\n*Metadata: {metadata}*")

        return "\n".join(parts)

    @staticmethod
    def error(
        error: Union[Exception, str],
        suggestion: str | None = None,
        example: str | None = None,
        tool_name: str | None = None,
        output_format: str = "markdown",
    ) -> str:
        from .agent_output import is_structured_output_format, serialize_structured_payload

        error_msg = _safe_public_message(error)
        retryable = is_retryable_error(error) if isinstance(error, Exception) else False
        if isinstance(error, PubMedSearchError):
            retryable = error.retryable
        retry_delay = get_retry_delay(error, 0) if retryable and isinstance(error, Exception) else None

        if is_structured_output_format(output_format):
            result: dict[str, Any] = {"success": False, "error": error_msg}
            if isinstance(error, PubMedSearchError):
                result["category"] = error.category.value
                result["severity"] = error.severity.name.lower()
            if tool_name:
                result["tool"] = tool_name
            if suggestion:
                result["suggestion"] = _safe_public_message(suggestion)
            if example:
                result["example"] = _safe_public_message(example)
            if retryable:
                result["retryable"] = True
                if retry_delay is not None:
                    result["retry_after"] = retry_delay
            return serialize_structured_payload(result, output_format)

        safe_tool_name = safe_markdown.escape_markdown_text(tool_name) if tool_name else ""
        safe_error = safe_markdown.escape_markdown_text(error_msg)
        parts = [f"❌ **Error in {safe_tool_name}**: {safe_error}" if safe_tool_name else f"❌ **Error**: {safe_error}"]

        if suggestion:
            parts.append(f"\n💡 **Suggestion**: {safe_markdown.escape_markdown_text(_safe_public_message(suggestion))}")
        if example:
            parts.append(f"\n📝 **Example**: `{safe_markdown.escape_markdown_code(_safe_public_message(example))}`")
        if retryable:
            if retry_delay is not None:
                parts.append(f"\n🔄 Retryable: Wait {retry_delay:.1f}s and try again")
            else:
                parts.append("\n🔄 Retryable: This error may be transient")

        return "\n".join(parts)

    @staticmethod
    def no_results(
        query: str | None = None,
        suggestions: list[str] | None = None,
        alternative_tools: list[str] | None = None,
        output_format: str = "markdown",
        tool_name: str | None = None,
    ) -> str:
        from .agent_output import is_structured_output_format, serialize_structured_payload

        if is_structured_output_format(output_format):
            payload: dict[str, Any] = {"success": True, "no_results": True, "count": 0}
            if tool_name:
                payload["tool"] = tool_name
            if query:
                payload["query"] = _safe_public_message(query)
            if suggestions:
                payload["suggestions"] = suggestions
            if alternative_tools:
                payload["alternative_tools"] = alternative_tools
            return serialize_structured_payload(payload, output_format)

        parts = ["🔍 **No results found**"]
        if query:
            parts.append(f"\nQuery: `{safe_markdown.escape_markdown_code(_safe_public_message(query))}`")
        if suggestions:
            parts.append("\n\n💡 **Suggestions**:")
            for suggestion in suggestions:
                parts.append(f"- {safe_markdown.escape_markdown_text(_safe_public_message(suggestion))}")
        if alternative_tools:
            parts.append("\n\n🔧 **Alternative tools to try**:")
            for tool in alternative_tools:
                parts.append(f"- `{tool}`")
        return "\n".join(parts)

    @staticmethod
    def partial_success(successful: list[Any], failed: list[dict], message: str | None = None) -> str:
        parts = []
        if message:
            parts.append(f"⚠️ {safe_markdown.escape_markdown_text(_safe_public_message(message))}")
        else:
            parts.append(f"⚠️ **Partial success**: {len(successful)} succeeded, {len(failed)} failed")

        if failed:
            parts.append("\n\n**Failed items**:")
            for item in failed[:5]:
                parts.append(
                    f"- {safe_markdown.escape_markdown_text(item.get('id', 'unknown'))}: "
                    f"{safe_markdown.escape_markdown_text(_safe_public_message(item.get('error', 'unknown error')))}"
                )
            if len(failed) > 5:
                parts.append(f"- ... and {len(failed) - 5} more")

        return "\n".join(parts)


def format_search_results(results: list, include_doi: bool = True) -> str:
    if not results:
        return "No results found."

    formatted_output = f"Found {len(results)} results:\n\n"
    for i, paper in enumerate(results, 1):
        formatted_output += f"{i}. **{safe_markdown.escape_markdown_text(paper.get('title', 'Untitled'))}**\n"
        authors = [str(author) for author in paper.get("authors", [])]
        formatted_output += (
            f"   Authors: {safe_markdown.escape_markdown_text(', '.join(authors[:3]))}"
            f"{' et al.' if len(authors) > 3 else ''}\n"
        )
        journal = safe_markdown.escape_markdown_text(paper.get("journal", "Unknown Journal"))
        year = safe_markdown.escape_markdown_text(paper.get("year", ""))
        volume = safe_markdown.escape_markdown_text(paper.get("volume", ""))
        pages = safe_markdown.escape_markdown_text(paper.get("pages", ""))

        journal_info = f"{journal} ({year})"
        if volume:
            journal_info += f"; {volume}"
            if pages:
                journal_info += f": {pages}"
        formatted_output += f"   Journal: {journal_info}\n"
        formatted_output += f"   PMID: {safe_markdown.escape_markdown_text(paper.get('pmid', ''))}"

        if include_doi and paper.get("doi"):
            formatted_output += f" | DOI: {safe_markdown.escape_markdown_text(paper['doi'])}"
        if paper.get("pmc_id"):
            formatted_output += f" | PMC: {safe_markdown.escape_markdown_text(paper['pmc_id'])} 📄"

        formatted_output += "\n"

        abstract = paper.get("abstract", "")
        if abstract:
            formatted_output += f"   Abstract: {safe_markdown.escape_markdown_text(str(abstract)[:200])}...\n"
        formatted_output += "\n"

    return formatted_output


__all__ = [
    "ResponseFormatter",
    "format_search_results",
]
