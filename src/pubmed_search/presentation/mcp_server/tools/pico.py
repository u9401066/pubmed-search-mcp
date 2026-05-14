"""
PICO handoff tool for agent-guided clinical search workflows.

The MCP server does not semantically decompose natural-language clinical
questions. Agents provide structured P/I/C/O elements; this tool validates
that handoff and returns a ready-to-run PICO pipeline.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from ._common import InputNormalizer, ResponseFormatter

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

PICO_SCHEMA = {
    "P": "Population / patient group",
    "I": "Intervention / exposure / index test",
    "C": "Comparison / control / reference standard, optional",
    "O": "Outcome / endpoint / target condition, recommended",
}

QUESTION_FILTERS = {
    "therapy": "therapy[filter]",
    "diagnosis": "diagnosis[filter]",
    "prognosis": "prognosis[filter]",
    "etiology": "etiology[filter]",
}

PICO_PROFILES = {"precision", "balanced", "recall"}


def _clean(value: object | None) -> str:
    return InputNormalizer.normalize_query(str(value)) if value else ""


def _infer_question_type(description: str, elements: dict[str, str]) -> str:
    haystack = " ".join([description, *elements.values()]).lower()
    if any(token in haystack for token in ["diagnos", "detect", "sensitivity", "specificity", "accuracy", "診斷"]):
        return "diagnosis"
    if any(token in haystack for token in ["prognos", "survival", "mortality", "outcome", "預後", "存活"]):
        return "prognosis"
    if any(token in haystack for token in ["cause", "etiolog", "risk factor", "association", "危險因子", "原因"]):
        return "etiology"
    return "therapy"


def _normalize_question_type(
    question_type: str | None,
    description: str,
    elements: dict[str, str],
) -> tuple[str, list[str]]:
    warnings: list[str] = []
    inferred = _infer_question_type(description, elements)
    if not question_type:
        return inferred, warnings

    normalized = _clean(question_type).lower()
    if normalized in QUESTION_FILTERS:
        return normalized, warnings

    warnings.append(f"question_type '{question_type}' is not supported; inferred '{inferred}' instead.")
    return inferred, warnings


def _normalize_profile(profile: str | None) -> tuple[str, list[str]]:
    warnings: list[str] = []
    normalized = _clean(profile).lower() or "balanced"
    if normalized in PICO_PROFILES:
        return normalized, warnings

    warnings.append(f"profile '{profile}' is not supported; using 'balanced'.")
    return "balanced", warnings


def _yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _build_pipeline_yaml(
    *,
    elements: dict[str, str],
    query_elements: dict[str, str],
    question_type: str,
    profile: str,
    sources: str,
    limit: int,
) -> str:
    lines = [
        "template: pico",
        "params:",
    ]
    for key in ("P", "I", "C", "O"):
        if key in elements:
            lines.append(f"  {key}: {_yaml_scalar(elements[key])}")
        query_key = f"{key}_query"
        if key in query_elements and query_elements[key] != elements.get(key, ""):
            lines.append(f"  {query_key}: {_yaml_scalar(query_elements[key])}")
    lines.extend(
        [
            f"  question_type: {_yaml_scalar(question_type)}",
            f"  profile: {_yaml_scalar(profile)}",
            f"  sources: {_yaml_scalar(sources)}",
            f"  limit: {int(limit)}",
        ]
    )
    return "\n".join(lines)


def _validation(elements: dict[str, str]) -> dict[str, object]:
    missing_required = [key for key in ("P", "I") if not elements.get(key)]
    warnings: list[str] = []
    if not elements.get("C"):
        warnings.append("C is optional; omit it when no comparator is clinically appropriate.")
    if not elements.get("O"):
        warnings.append("O is recommended; add outcomes when the clinical question implies them.")
    return {
        "valid": not missing_required,
        "required": ["P", "I"],
        "recommended": ["O"],
        "optional": ["C"],
        "missing_required": missing_required,
        "warnings": warnings,
    }


def register_pico_tools(mcp: FastMCP):
    """Register the PICO handoff tool."""

    @mcp.tool()
    def parse_pico(
        description: str = "",
        p: str | None = None,
        i: str | None = None,
        c: str | None = None,
        o: str | None = None,
        p_query: str | None = None,
        i_query: str | None = None,
        c_query: str | None = None,
        o_query: str | None = None,
        question_type: str | None = None,
        profile: str = "balanced",
        sources: str = "pubmed",
        limit: int = 20,
    ) -> str:
        """
        Validate agent-provided PICO elements and return a runnable search plan.

        The agent, not this MCP server, extracts P/I/C/O from the user's natural
        language question. When only ``description`` is provided, this tool
        returns the schema the agent should fill and asks the agent to call this
        tool again with structured elements.

        Args:
            description: Original clinical question for provenance.
            p: Population / patient group extracted by the agent.
            i: Intervention / exposure / index test extracted by the agent.
            c: Comparator extracted by the agent, optional.
            o: Outcome extracted by the agent, recommended.
            p_query/i_query/c_query/o_query: Optional expanded PubMed-ready
                query fragments. When present, the PICO pipeline uses these for
                search while preserving the human-readable P/I/C/O labels.
            question_type: therapy, diagnosis, prognosis, or etiology. Inferred
                heuristically when omitted.
            profile: Search profile for the PICO template, default balanced.
            sources: Comma-separated sources for the pipeline.
            limit: Final result limit for the pipeline.

        Returns:
            JSON containing validation, PICO schema, query plan, and pipeline
            YAML that can be passed to ``unified_search(pipeline=...)``.
        """
        description = _clean(description)
        elements = {
            key: value
            for key, value in {
                "P": _clean(p),
                "I": _clean(i),
                "C": _clean(c),
                "O": _clean(o),
            }.items()
            if value
        }

        if not description and not elements:
            return ResponseFormatter.error(
                "Missing input",
                suggestion="Provide a clinical question or agent-extracted P/I/C/O elements.",
                example='parse_pico(description="remimazolam vs propofol for ICU sedation")',
                tool_name="parse_pico",
            )

        inferred_type, question_type_warnings = _normalize_question_type(question_type, description, elements)
        normalized_profile, profile_warnings = _normalize_profile(profile)
        normalized_sources = _clean(sources) or "pubmed"
        normalized_limit = InputNormalizer.normalize_limit(limit, default=20, max_val=100)  # type: ignore[arg-type]
        normalization_warnings = [*question_type_warnings, *profile_warnings]
        suggested_filter = QUESTION_FILTERS.get(inferred_type, f"{inferred_type}[filter]")

        if not elements:
            result = {
                "source": "requires_agent_extraction",
                "requires_agent_extraction": True,
                "original_description": description,
                "pico": {"P": "", "I": "", "C": "", "O": ""},
                "pico_schema": PICO_SCHEMA,
                "question_type": inferred_type,
                "suggested_filter": suggested_filter,
                "profile": normalized_profile,
                "normalization_warnings": normalization_warnings,
                "agent_instruction": (
                    "Extract P/I/C/O from original_description using clinical judgment. "
                    "Do not invent missing details; ask the user when P or I is unclear. "
                    "Call parse_pico again with structured p/i/c/o values."
                ),
                "next_tool_call": {
                    "tool": "parse_pico",
                    "args": {
                        "description": description,
                        "p": "<Population>",
                        "i": "<Intervention/exposure>",
                        "c": "<Comparator, optional>",
                        "o": "<Outcome, recommended>",
                    },
                },
            }
            return json.dumps(result, indent=2, ensure_ascii=False)

        query_elements = {
            key: value
            for key, value in {
                "P": _clean(p_query) or elements.get("P", ""),
                "I": _clean(i_query) or elements.get("I", ""),
                "C": _clean(c_query) or elements.get("C", ""),
                "O": _clean(o_query) or elements.get("O", ""),
            }.items()
            if value
        }
        validation = _validation(elements)
        if not validation["valid"]:
            result = {
                "source": "agent_provided",
                "requires_agent_extraction": True,
                "original_description": description,
                "pico": {key: elements.get(key, "") for key in ("P", "I", "C", "O")},
                "query_elements": {key: query_elements.get(key, "") for key in ("P", "I", "C", "O")},
                "pico_schema": PICO_SCHEMA,
                "validation": validation,
                "question_type": inferred_type,
                "suggested_filter": suggested_filter,
                "profile": normalized_profile,
                "normalization_warnings": normalization_warnings,
                "agent_instruction": (
                    "The structured PICO handoff is incomplete. Fill the missing required fields "
                    "before running unified_search."
                ),
                "next_tool_call": {
                    "tool": "parse_pico",
                    "args": {
                        "description": description,
                        "p": elements.get("P") or "<Population>",
                        "i": elements.get("I") or "<Intervention/exposure>",
                        "c": elements.get("C") or "<Comparator, optional>",
                        "o": elements.get("O") or "<Outcome, recommended>",
                    },
                },
            }
            return json.dumps(result, indent=2, ensure_ascii=False)

        pipeline_yaml = _build_pipeline_yaml(
            elements=elements,
            query_elements=query_elements,
            question_type=inferred_type,
            profile=normalized_profile,
            sources=normalized_sources,
            limit=normalized_limit,
        )

        result = {
            "source": "agent_provided",
            "requires_agent_extraction": False,
            "original_description": description,
            "pico": {key: elements.get(key, "") for key in ("P", "I", "C", "O")},
            "query_elements": {key: query_elements.get(key, "") for key in ("P", "I", "C", "O")},
            "pico_schema": PICO_SCHEMA,
            "validation": validation,
            "question_type": inferred_type,
            "suggested_filter": suggested_filter,
            "profile": normalized_profile,
            "normalization_warnings": normalization_warnings,
            "pipeline": pipeline_yaml,
            "next_tool": "unified_search",
            "next_tool_call": {
                "tool": "unified_search",
                "args": {
                    "query": description or " / ".join(elements.values()),
                    "pipeline": pipeline_yaml,
                },
            },
            "query_patterns": {
                "precision": "(P_query) AND (I_query) AND (C_query if present) AND (O_query if present)",
                "recall": "(P_query) AND (I_query OR C_query if present) AND (O_query if present)",
                "intervention_outcome": "(I_query) AND (O_query)",
                "comparison_outcome": "(C_query) AND (O_query)",
            },
        }

        logger.info("Accepted agent-provided PICO handoff: valid=%s", validation["valid"])
        return json.dumps(result, indent=2, ensure_ascii=False)
