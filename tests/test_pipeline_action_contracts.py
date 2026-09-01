"""Regression tests for strict action- and template-specific pipeline params."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pubmed_search.application.pipeline.executor import PipelineExecutor
from pubmed_search.application.pipeline.templates import build_pipeline_from_template
from pubmed_search.application.pipeline.validator import parse_and_validate_config
from pubmed_search.domain.entities.pipeline import PipelineConfig, PipelineStep, StepResult

if TYPE_CHECKING:
    from typing import Any


VALID_ACTION_PARAMS: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        "search",
        {
            "query": "remimazolam",
            "sources": ["pubmed", "openalex"],
            "limit": 25,
            "min_year": 2020,
            "max_year": 2026,
            "age_group": "adult",
            "sex": "female",
            "species": "humans",
            "language": "english",
            "clinical_query": "therapy_narrow",
        },
    ),
    ("pico", {"P": "ICU patients", "I": "remimazolam", "C": "propofol", "O": "delirium"}),
    ("expand", {"topic": "remimazolam ICU sedation"}),
    ("details", {"pmids": ["33475315", "12345678"]}),
    ("related", {"pmid": "33475315", "limit": 20}),
    ("citing", {"pmid": "33475315", "limit": 20}),
    ("references", {"pmid": "33475315", "limit": 20}),
    ("metrics", {}),
    ("merge", {"method": "rrf"}),
    (
        "filter",
        {
            "min_year": 2020,
            "max_year": 2026,
            "article_types": ["randomized-controlled-trial", "systematic-review"],
            "min_citations": 5,
            "has_abstract": True,
        },
    ),
)


@pytest.mark.parametrize(("action", "params"), VALID_ACTION_PARAMS)
def test_every_action_accepts_its_canonical_typed_params(action: str, params: dict[str, Any]) -> None:
    result = parse_and_validate_config({"steps": [{"id": "step", "action": action, "params": params}]})

    assert result.valid is True, result.errors


@pytest.mark.parametrize(("action", "params"), VALID_ACTION_PARAMS)
def test_every_action_rejects_unknown_param_keys(action: str, params: dict[str, Any]) -> None:
    result = parse_and_validate_config(
        {"steps": [{"id": "step", "action": action, "params": {**params, "retired_alias": True}}]}
    )

    assert result.valid is False
    assert any("retired_alias" in error and "Extra inputs" in error for error in result.errors)


@pytest.mark.parametrize(
    ("action", "params"),
    [
        ("search", {"query": 123}),
        ("search", {"query": "cancer", "limit": "10"}),
        ("search", {"query": "cancer", "sources": "pubmed"}),
        ("search", {"query": "cancer", "sources": ["PubMed"]}),
        ("search", {"query": "cancer", "use_combined": "recalll"}),
        ("search", {"query": "cancer", "element": "p"}),
        ("search", {"query": "cancer", "clinical_query": "Therapy"}),
        ("pico", {"P": 123, "I": "drug"}),
        ("pico", {"P": "patients", "I": True}),
        ("expand", {"topic": ["cancer"]}),
        ("details", {"pmids": "33475315"}),
        ("details", {"pmids": [33475315]}),
        ("related", {"pmid": 33475315}),
        ("related", {"pmid": "33475315", "limit": "20"}),
        ("citing", {"pmid": "33475315", "limit": 20.0}),
        ("references", {"pmid": "PMID:33475315"}),
        ("metrics", {"limit": 20}),
        ("merge", {"method": "rrf_typo"}),
        ("filter", {"article_types": "randomized-controlled-trial"}),
        ("filter", {"article_types": ["RCT"]}),
        ("filter", {"min_year": "2020"}),
        ("filter", {"min_citations": 1.0}),
        ("filter", {"has_abstract": "false"}),
    ],
)
def test_action_contracts_reject_wrong_types_aliases_and_enum_typos(
    action: str,
    params: dict[str, Any],
) -> None:
    result = parse_and_validate_config({"steps": [{"id": "step", "action": action, "params": params}]})

    assert result.valid is False
    assert any(f"Invalid {action} params" in error for error in result.errors)


VALID_TEMPLATE_PARAMS: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        "pico",
        {
            "P": "ICU patients",
            "I": "remimazolam",
            "C": "propofol",
            "O": "delirium",
            "profile": "balanced",
            "question_type": "therapy_narrow",
            "sources": ["pubmed", "openalex"],
            "limit": 25,
        },
    ),
    (
        "comprehensive",
        {"query": "CRISPR therapy", "sources": ["pubmed", "europe_pmc"], "limit": 30, "min_year": 2020},
    ),
    ("exploration", {"pmid": "33475315", "limit": 20}),
    ("gene_drug", {"term": "BRCA1", "sources": ["pubmed", "openalex"], "limit": 20, "max_year": 2026}),
)


@pytest.mark.parametrize(("template", "params"), VALID_TEMPLATE_PARAMS)
def test_every_template_accepts_its_canonical_typed_params(template: str, params: dict[str, Any]) -> None:
    result = parse_and_validate_config({"template": template, "template_params": params})

    assert result.valid is True, result.errors
    build_pipeline_from_template(template, params)


@pytest.mark.parametrize(("template", "params"), VALID_TEMPLATE_PARAMS)
def test_every_template_rejects_unknown_param_keys(template: str, params: dict[str, Any]) -> None:
    result = parse_and_validate_config({"template": template, "template_params": {**params, "retired_alias": "value"}})

    assert result.valid is False
    assert any("retired_alias" in error and "Extra inputs" in error for error in result.errors)


@pytest.mark.parametrize(
    ("template", "params"),
    [
        ("pico", {"P": "ICU", "I": "drug", "profile": "Balanced"}),
        ("pico", {"P": "ICU", "I": "drug", "question_type": "Therapy"}),
        ("pico", {"P": "ICU", "I": "drug", "sources": ["oa"]}),
        ("comprehensive", {"query": 123}),
        ("comprehensive", {"query": "CRISPR", "min_year": "2020"}),
        ("exploration", {"pmid": 33475315}),
        ("gene_drug", {"term": "BRCA1", "sources": "pubmed"}),
    ],
)
def test_template_contracts_reject_wrong_types_aliases_and_enum_typos(
    template: str,
    params: dict[str, Any],
) -> None:
    result = parse_and_validate_config({"template": template, "template_params": params})

    assert result.valid is False
    assert any(f"Invalid {template} template_params" in error for error in result.errors)


def test_typed_variables_are_deferred_then_checked_after_resolution() -> None:
    config = PipelineConfig(
        globals={"sources": ["pubmed"], "limit": "${per_step_limit}"},
        variables={"per_step_limit": 25, "topic": "remimazolam"},
        steps=[PipelineStep(id="search", action="search", params={"query": "${topic}"})],
    )

    _articles, results = PipelineExecutor().dry_run(config)

    assert results["search"].metadata["resolved_params"] == {
        "sources": ["pubmed"],
        "limit": 25,
        "query": "remimazolam",
    }


def test_variable_with_wrong_resolved_type_fails_closed() -> None:
    config = PipelineConfig(
        variables={"per_step_limit": "25"},
        steps=[
            PipelineStep(
                id="search",
                action="search",
                params={"query": "remimazolam", "limit": "${per_step_limit}"},
            )
        ],
    )

    with pytest.raises(ValueError, match="limit must be an integer"):
        PipelineExecutor().dry_run(config)


def test_embedded_non_string_variable_is_not_string_coerced() -> None:
    config = PipelineConfig(
        variables={"year": 2026},
        steps=[PipelineStep(id="search", action="search", params={"query": "remimazolam ${year}"})],
    )

    with pytest.raises(TypeError, match="must resolve to a string"):
        PipelineExecutor().dry_run(config)


def test_unknown_global_param_is_rejected_instead_of_ignored() -> None:
    config = PipelineConfig(
        globals={"limt": 20},
        steps=[PipelineStep(id="search", action="search", params={"query": "remimazolam"})],
    )

    with pytest.raises(ValueError, match="unknown or unused"):
        PipelineExecutor().dry_run(config)


def test_unknown_expand_strategy_does_not_fall_back_to_another_query() -> None:
    step = PipelineStep(id="search", action="search", params={"strategy": "mesh_typo"}, inputs=["expand"])
    upstream = StepResult(
        step_id="expand",
        action="expand",
        metadata={
            "expanded_query": "fallback query",
            "strategies": [{"name": "mesh", "query": "mesh query"}],
        },
    )

    with pytest.raises(ValueError, match="was not produced"):
        PipelineExecutor._resolve_query(step, {"expand": upstream})


@pytest.mark.parametrize(
    ("action", "params", "expected_message"),
    [
        (
            "search",
            {"query": "remimazolam", "sources": ["pubmed"], "limit": "token=PRIVATE_SENTINEL"},
            "Invalid pipeline search limit",
        ),
        (
            "related",
            {"pmid": "33475315", "limit": "token=PRIVATE_SENTINEL"},
            "Invalid pipeline related-article limit",
        ),
        (
            "citing",
            {"pmid": "33475315", "limit": "token=PRIVATE_SENTINEL"},
            "Invalid pipeline citing-article limit",
        ),
        (
            "references",
            {"pmid": "33475315", "limit": "token=PRIVATE_SENTINEL"},
            "Invalid pipeline reference limit",
        ),
    ],
)
async def test_direct_action_limit_failures_are_query_safe_and_typed(
    action: str,
    params: dict[str, Any],
    expected_message: str,
) -> None:
    executor = PipelineExecutor()
    step = PipelineStep(id="step", action=action, params=params)

    result = await getattr(executor, f"_action_{action}")(step, {})

    assert result.error == expected_message
    assert "PRIVATE_SENTINEL" not in str(result.metadata)
    assert result.metadata["error_type"] == "ValueError"
    assert result.metadata["error_kind"] == "unexpected"
    assert result.metadata["retryable"] is False
