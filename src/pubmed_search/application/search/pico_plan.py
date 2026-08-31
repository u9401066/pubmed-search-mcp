"""Application service for validating an agent-provided PICO handoff."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal, cast

from pubmed_search.application.pipeline.budgets import PIPELINE_TEMPLATE_LIMITS

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

QuestionType = Literal["therapy", "diagnosis", "prognosis", "etiology"]
PicoProfile = Literal["precision", "balanced", "recall"]
PicoSource = Literal["pubmed", "europe_pmc", "openalex", "semantic_scholar", "core"]

MAX_PICO_DESCRIPTION_CHARS = 5_000
MAX_PICO_ELEMENT_CHARS = 2_000
MAX_PICO_QUERY_CHARS = 5_000
MAX_PICO_RESULTS = PIPELINE_TEMPLATE_LIMITS["pico"].maximum

PICO_SCHEMA = {
    "P": "Population / patient group",
    "I": "Intervention / exposure / index test",
    "C": "Comparison / control / reference standard, optional",
    "O": "Outcome / endpoint / target condition, recommended",
}
QUESTION_FILTERS: dict[QuestionType, str] = {
    "therapy": "therapy[filter]",
    "diagnosis": "diagnosis[filter]",
    "prognosis": "prognosis[filter]",
    "etiology": "etiology[filter]",
}
PICO_PROFILES = frozenset({"precision", "balanced", "recall"})
PICO_SOURCES = frozenset({"pubmed", "europe_pmc", "openalex", "semantic_scholar", "core"})


class PicoPlanValidationError(ValueError):
    """Raised when a PICO handoff would produce an ambiguous pipeline."""


def _bounded_text(value: object | None, *, label: str, max_chars: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PicoPlanValidationError(f"{label} must be a string")
    text = value.strip()
    if len(text) > max_chars:
        raise PicoPlanValidationError(f"{label} exceeds {max_chars} characters")
    if "\x00" in text:
        raise PicoPlanValidationError(f"{label} contains a null character")
    return text


def infer_question_type(description: str, elements: Mapping[str, str]) -> QuestionType:
    """Infer a clinical query filter only when the caller omitted it."""

    haystack = " ".join([description, *elements.values()]).lower()
    if any(token in haystack for token in ["diagnos", "detect", "sensitivity", "specificity", "accuracy", "診斷"]):
        return "diagnosis"
    if any(token in haystack for token in ["prognos", "survival", "mortality", "outcome", "預後", "存活"]):
        return "prognosis"
    if any(token in haystack for token in ["cause", "etiolog", "risk factor", "association", "危險因子", "原因"]):
        return "etiology"
    return "therapy"


def _yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _build_pipeline_yaml(
    *,
    elements: Mapping[str, str],
    query_elements: Mapping[str, str],
    question_type: QuestionType,
    profile: PicoProfile,
    sources: Sequence[PicoSource],
    limit: int,
) -> str:
    lines = ["template: pico", "template_params:"]
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
            f"  sources: {json.dumps(list(sources), ensure_ascii=False)}",
            f"  limit: {limit}",
        ]
    )
    return "\n".join(lines)


def _validation(elements: Mapping[str, str]) -> dict[str, object]:
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


def build_pico_search_plan(
    *,
    description: str = "",
    p: str | None = None,
    i: str | None = None,
    c: str | None = None,
    o: str | None = None,
    p_query: str | None = None,
    i_query: str | None = None,
    c_query: str | None = None,
    o_query: str | None = None,
    question_type: QuestionType | None = None,
    profile: PicoProfile = "balanced",
    sources: Sequence[PicoSource] | None = None,
    limit: int = 20,
) -> dict[str, object]:
    """Validate PICO elements and build a deterministic pipeline handoff."""

    description = _bounded_text(description, label="description", max_chars=MAX_PICO_DESCRIPTION_CHARS)
    elements = {
        key: value
        for key, value in {
            "P": _bounded_text(p, label="P", max_chars=MAX_PICO_ELEMENT_CHARS),
            "I": _bounded_text(i, label="I", max_chars=MAX_PICO_ELEMENT_CHARS),
            "C": _bounded_text(c, label="C", max_chars=MAX_PICO_ELEMENT_CHARS),
            "O": _bounded_text(o, label="O", max_chars=MAX_PICO_ELEMENT_CHARS),
        }.items()
        if value
    }
    if not description and not elements:
        raise PicoPlanValidationError("Provide a clinical question or agent-extracted P/I/C/O elements")

    if question_type is not None and question_type not in QUESTION_FILTERS:
        raise PicoPlanValidationError("question_type must be therapy, diagnosis, prognosis, or etiology")
    resolved_type = question_type or infer_question_type(description, elements)
    if profile not in PICO_PROFILES:
        raise PicoPlanValidationError("profile must be precision, balanced, or recall")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_PICO_RESULTS:
        raise PicoPlanValidationError(f"limit must be an integer from 1 to {MAX_PICO_RESULTS}")

    resolved_sources = list(sources) if sources is not None else ["pubmed"]
    if not resolved_sources:
        raise PicoPlanValidationError("sources must contain at least one supported source")
    if len(resolved_sources) > len(PICO_SOURCES):
        raise PicoPlanValidationError("sources contains too many entries")
    unknown_sources = sorted(set(resolved_sources) - PICO_SOURCES)
    if unknown_sources:
        raise PicoPlanValidationError(f"Unsupported PICO sources: {', '.join(unknown_sources)}")
    if len(resolved_sources) != len(set(resolved_sources)):
        raise PicoPlanValidationError("sources must not contain duplicates")
    resolved_sources = cast("list[PicoSource]", resolved_sources)

    suggested_filter = QUESTION_FILTERS[resolved_type]
    if not elements:
        return {
            "source": "requires_agent_extraction",
            "requires_agent_extraction": True,
            "original_description": description,
            "pico": {"P": "", "I": "", "C": "", "O": ""},
            "pico_schema": PICO_SCHEMA,
            "question_type": resolved_type,
            "suggested_filter": suggested_filter,
            "profile": profile,
            "sources": resolved_sources,
            "agent_instruction": (
                "Extract P/I/C/O from original_description using clinical judgment. "
                "Do not invent missing details; ask the user when P or I is unclear. "
                "Call validate_pico_plan again with structured p/i/c/o values."
            ),
            "next_tool_call": {
                "tool": "validate_pico_plan",
                "args": {
                    "description": description,
                    "p": "<Population>",
                    "i": "<Intervention/exposure>",
                    "c": "<Comparator, optional>",
                    "o": "<Outcome, recommended>",
                },
            },
        }

    raw_queries = {"P": p_query, "I": i_query, "C": c_query, "O": o_query}
    query_elements: dict[str, str] = {}
    for key, value in raw_queries.items():
        expanded = _bounded_text(value, label=f"{key}_query", max_chars=MAX_PICO_QUERY_CHARS)
        resolved = expanded or elements.get(key, "")
        if resolved:
            query_elements[key] = resolved

    validation = _validation(elements)
    common: dict[str, object] = {
        "source": "agent_provided",
        "requires_agent_extraction": not bool(validation["valid"]),
        "original_description": description,
        "pico": {key: elements.get(key, "") for key in ("P", "I", "C", "O")},
        "query_elements": {key: query_elements.get(key, "") for key in ("P", "I", "C", "O")},
        "pico_schema": PICO_SCHEMA,
        "validation": validation,
        "question_type": resolved_type,
        "suggested_filter": suggested_filter,
        "profile": profile,
        "sources": resolved_sources,
    }
    if not validation["valid"]:
        common.update(
            {
                "agent_instruction": (
                    "The structured PICO handoff is incomplete. Fill the missing required fields "
                    "before running unified_search."
                ),
                "next_tool_call": {
                    "tool": "validate_pico_plan",
                    "args": {
                        "description": description,
                        "p": elements.get("P") or "<Population>",
                        "i": elements.get("I") or "<Intervention/exposure>",
                        "c": elements.get("C") or "<Comparator, optional>",
                        "o": elements.get("O") or "<Outcome, recommended>",
                    },
                },
            }
        )
        return common

    pipeline_yaml = _build_pipeline_yaml(
        elements=elements,
        query_elements=query_elements,
        question_type=resolved_type,
        profile=profile,
        sources=resolved_sources,
        limit=limit,
    )
    common.update(
        {
            "pipeline": pipeline_yaml,
            "next_tool": "unified_search",
            "next_tool_call": {
                "tool": "unified_search",
                "args": {"query": description or " / ".join(elements.values()), "pipeline": pipeline_yaml},
            },
            "query_patterns": {
                "precision": "(P_query) AND (I_query) AND (C_query if present) AND (O_query if present)",
                "recall": "(P_query) AND (I_query OR C_query if present) AND (O_query if present)",
                "intervention_outcome": "(I_query) AND (O_query)",
                "comparison_outcome": "(C_query) AND (O_query)",
            },
        }
    )
    return common


__all__ = [
    "MAX_PICO_DESCRIPTION_CHARS",
    "MAX_PICO_ELEMENT_CHARS",
    "MAX_PICO_QUERY_CHARS",
    "MAX_PICO_RESULTS",
    "PICO_PROFILES",
    "PICO_SCHEMA",
    "PICO_SOURCES",
    "PicoPlanValidationError",
    "PicoProfile",
    "PicoSource",
    "QuestionType",
    "build_pico_search_plan",
    "infer_question_type",
]
