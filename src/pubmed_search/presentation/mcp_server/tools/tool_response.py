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

from typing import Any, Union

from pubmed_search.shared import PubMedSearchError, get_retry_delay, is_retryable_error


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

        if isinstance(error, PubMedSearchError):
            if is_structured_output_format(output_format):
                return serialize_structured_payload(error.to_dict(), output_format)
            return error.to_agent_message()

        error_msg = str(error)
        retryable = is_retryable_error(error) if isinstance(error, Exception) else False
        retry_delay = get_retry_delay(error, 0) if retryable and isinstance(error, Exception) else None

        if is_structured_output_format(output_format):
            result = {"success": False, "error": error_msg}
            if tool_name:
                result["tool"] = tool_name
            if suggestion:
                result["suggestion"] = suggestion
            if example:
                result["example"] = example
            if retryable:
                result["retryable"] = True
                if retry_delay:
                    result["retry_after"] = retry_delay
            return serialize_structured_payload(result, output_format)

        parts = [f"❌ **Error in {tool_name}**: {error_msg}" if tool_name else f"❌ **Error**: {error_msg}"]

        if suggestion:
            parts.append(f"\n💡 **Suggestion**: {suggestion}")
        if example:
            parts.append(f"\n📝 **Example**: `{example}`")
        if retryable:
            if retry_delay:
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
                payload["query"] = query
            if suggestions:
                payload["suggestions"] = suggestions
            if alternative_tools:
                payload["alternative_tools"] = alternative_tools
            return serialize_structured_payload(payload, output_format)

        parts = ["🔍 **No results found**"]
        if query:
            parts.append(f"\nQuery: `{query}`")
        if suggestions:
            parts.append("\n\n💡 **Suggestions**:")
            for suggestion in suggestions:
                parts.append(f"- {suggestion}")
        if alternative_tools:
            parts.append("\n\n🔧 **Alternative tools to try**:")
            for tool in alternative_tools:
                parts.append(f"- `{tool}`")
        return "\n".join(parts)

    @staticmethod
    def partial_success(successful: list[Any], failed: list[dict], message: str | None = None) -> str:
        parts = []
        if message:
            parts.append(f"⚠️ {message}")
        else:
            parts.append(f"⚠️ **Partial success**: {len(successful)} succeeded, {len(failed)} failed")

        if failed:
            parts.append("\n\n**Failed items**:")
            for item in failed[:5]:
                parts.append(f"- {item.get('id', 'unknown')}: {item.get('error', 'unknown error')}")
            if len(failed) > 5:
                parts.append(f"- ... and {len(failed) - 5} more")

        return "\n".join(parts)


def format_search_results(results: list, include_doi: bool = True) -> str:
    if not results:
        return "No results found."

    if "error" in results[0]:
        return f"Error searching PubMed: {results[0]['error']}"

    formatted_output = f"Found {len(results)} results:\n\n"
    for i, paper in enumerate(results, 1):
        formatted_output += f"{i}. **{paper['title']}**\n"
        authors = paper.get("authors", [])
        formatted_output += f"   Authors: {', '.join(authors[:3])}{' et al.' if len(authors) > 3 else ''}\n"
        journal = paper.get("journal", "Unknown Journal")
        year = paper.get("year", "")
        volume = paper.get("volume", "")
        pages = paper.get("pages", "")

        journal_info = f"{journal} ({year})"
        if volume:
            journal_info += f"; {volume}"
            if pages:
                journal_info += f": {pages}"
        formatted_output += f"   Journal: {journal_info}\n"
        formatted_output += f"   PMID: {paper.get('pmid', '')}"

        if include_doi and paper.get("doi"):
            formatted_output += f" | DOI: {paper['doi']}"
        if paper.get("pmc_id"):
            formatted_output += f" | PMC: {paper['pmc_id']} 📄"

        formatted_output += "\n"

        abstract = paper.get("abstract", "")
        if abstract:
            formatted_output += f"   Abstract: {abstract[:200]}...\n"
        formatted_output += "\n"

    return formatted_output


__all__ = ["ResponseFormatter", "format_search_results"]