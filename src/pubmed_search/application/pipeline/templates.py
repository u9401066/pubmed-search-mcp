"""
Built-in pipeline templates for common search workflows.

Templates generate PipelineConfig from minimal parameters, saving
agents from manually constructing multi-step pipeline JSON.

Available templates:
- **pico**: PICO clinical question → parallel element searches → RRF merge
- **comprehensive**: Multi-source + MeSH expansion → union merge + metrics
- **exploration**: Seed PMID → related + citing + refs → RRF merge
- **gene_drug**: Gene/drug term → expanded multi-source → merge + metrics

Maintenance:
    Template functions should stay declarative and return PipelineConfig only.
    Keep execution semantics in the pipeline runtime so template changes remain
    easy to review and safe to snapshot in tests.
"""

from __future__ import annotations

from typing import Any

from pubmed_search.application.pipeline.budgets import (
    PIPELINE_TEMPLATE_LIMITS,
    validate_pipeline_budgets,
)
from pubmed_search.application.pipeline.template_contracts import validate_pipeline_template_params
from pubmed_search.domain.entities.pipeline import (
    VALID_TEMPLATES,
    PipelineConfig,
    PipelineOutput,
    PipelineStep,
)

# =========================================================================
# Template Builders
# =========================================================================


PICO_PROFILES = {"precision", "balanced", "recall"}


def build_pico_pipeline(params: dict[str, Any]) -> PipelineConfig:
    """Agent-provided PICO clinical question search pipeline.

    Required params:
        P: Population description
        I: Intervention description
    Optional params:
        C: Comparison (default: "")
        O: Outcome (default: "")
        P_query/I_query/C_query/O_query: expanded query fragments to search
            instead of the human-readable labels
        question_type: therapy/diagnosis/prognosis/etiology clinical filter
        profile: precision/balanced/recall (default: balanced)
        sources: canonical source array (default: ["pubmed"])
        limit: result limit (default: 20)
    """
    validate_pipeline_template_params("pico", params)
    p = params["P"]
    i = params["I"]
    c = params.get("C")
    o = params.get("O")
    profile = params.get("profile", "balanced")
    question_type = params.get("question_type")
    sources = params.get("sources", ["pubmed"])
    limit = params.get("limit", PIPELINE_TEMPLATE_LIMITS["pico"].default)

    pico_params: dict[str, Any] = {"P": p, "I": i}
    for key in ("C", "O", "P_query", "I_query", "C_query", "O_query"):
        if params.get(key):
            pico_params[key] = params[key]

    def search_params(*, use_combined: str, step_limit: int) -> dict[str, Any]:
        search_step_params: dict[str, Any] = {
            "use_combined": use_combined,
            "sources": sources,
            "limit": step_limit,
        }
        if question_type:
            search_step_params["clinical_query"] = question_type
        return search_step_params

    steps: list[PipelineStep] = [
        PipelineStep(
            id="pico",
            action="pico",
            params=pico_params,
        ),
    ]

    merge_inputs: list[str] = []
    if profile in {"precision", "balanced"}:
        steps.append(
            PipelineStep(
                id="search_precision",
                action="search",
                inputs=["pico"],
                params=search_params(
                    use_combined="precision",
                    step_limit=limit * 3,
                ),
            )
        )
        merge_inputs.append("search_precision")

    if profile in {"balanced", "recall"}:
        steps.append(
            PipelineStep(
                id="search_recall",
                action="search",
                inputs=["pico"],
                params=search_params(
                    use_combined="recall",
                    step_limit=limit * 3,
                ),
            )
        )
        merge_inputs.append("search_recall")

    if profile in {"balanced", "recall"} and o:
        steps.append(
            PipelineStep(
                id="search_intervention_outcome",
                action="search",
                inputs=["pico"],
                params=search_params(
                    use_combined="intervention_outcome",
                    step_limit=limit * 2,
                ),
            )
        )
        merge_inputs.append("search_intervention_outcome")

    if profile == "balanced" and c and o:
        steps.append(
            PipelineStep(
                id="search_comparison_outcome",
                action="search",
                inputs=["pico"],
                params=search_params(
                    use_combined="comparison_outcome",
                    step_limit=limit * 2,
                ),
            )
        )
        merge_inputs.append("search_comparison_outcome")

    steps.append(
        PipelineStep(
            id="merged",
            action="merge",
            inputs=merge_inputs,
            params={"method": "rrf"},
        )
    )
    steps.append(PipelineStep(id="enriched", action="metrics", inputs=["merged"]))

    return PipelineConfig(
        name=f"PICO: {p[:30]} / {i[:30]}",
        steps=steps,
        output=PipelineOutput(format="markdown", limit=limit, ranking="balanced"),
    )


def build_comprehensive_pipeline(params: dict[str, Any]) -> PipelineConfig:
    """Comprehensive multi-source search with MeSH expansion.

    Required params:
        query: search topic
    Optional params:
        sources: canonical source array (default: ["pubmed", "openalex", "europe_pmc"])
        limit: result limit (default: 30)
        min_year / max_year: year filter
    """
    validate_pipeline_template_params("comprehensive", params)
    query = params["query"]
    sources = params.get("sources", ["pubmed", "openalex", "europe_pmc"])
    limit = params.get("limit", PIPELINE_TEMPLATE_LIMITS["comprehensive"].default)
    year_params: dict[str, Any] = {}
    if "min_year" in params:
        year_params["min_year"] = params["min_year"]
    if "max_year" in params:
        year_params["max_year"] = params["max_year"]

    return PipelineConfig(
        name=f"Comprehensive: {query[:50]}",
        steps=[
            PipelineStep(id="expand", action="expand", params={"topic": query}),
            PipelineStep(
                id="search_original",
                action="search",
                params={
                    "query": query,
                    "sources": sources,
                    "limit": limit * 2,
                    **year_params,
                },
            ),
            PipelineStep(
                id="search_expanded",
                action="search",
                inputs=["expand"],
                params={
                    "sources": sources,
                    "limit": limit * 2,
                    **year_params,
                },
            ),
            PipelineStep(
                id="merged",
                action="merge",
                inputs=["search_original", "search_expanded"],
                params={"method": "union"},
            ),
            PipelineStep(id="enriched", action="metrics", inputs=["merged"]),
        ],
        output=PipelineOutput(format="markdown", limit=limit, ranking="quality"),
    )


def build_exploration_pipeline(params: dict[str, Any]) -> PipelineConfig:
    """Exploration from a seed paper (related + citing + references).

    Required params:
        pmid: seed paper PMID
    Optional params:
        limit: result limit per direction (default: 20)
    """
    validate_pipeline_template_params("exploration", params)
    pmid = params["pmid"]
    limit = params.get("limit", PIPELINE_TEMPLATE_LIMITS["exploration"].default)

    return PipelineConfig(
        name=f"Exploration: PMID {pmid}",
        steps=[
            PipelineStep(
                id="related",
                action="related",
                params={"pmid": pmid, "limit": limit},
            ),
            PipelineStep(
                id="citing",
                action="citing",
                params={"pmid": pmid, "limit": limit},
            ),
            PipelineStep(
                id="refs",
                action="references",
                params={"pmid": pmid, "limit": limit},
            ),
            PipelineStep(
                id="merged",
                action="merge",
                inputs=["related", "citing", "refs"],
                params={"method": "rrf"},
            ),
            PipelineStep(id="enriched", action="metrics", inputs=["merged"]),
        ],
        output=PipelineOutput(format="markdown", limit=limit, ranking="impact"),
    )


def build_gene_drug_pipeline(params: dict[str, Any]) -> PipelineConfig:
    """Gene / drug compound multi-source search with expansion.

    Required params:
        term: gene or drug name
    Optional params:
        sources: canonical source array (default: ["pubmed", "openalex"])
        limit: result limit (default: 20)
        min_year / max_year: year filter
    """
    validate_pipeline_template_params("gene_drug", params)
    term = params["term"]
    sources = params.get("sources", ["pubmed", "openalex"])
    limit = params.get("limit", PIPELINE_TEMPLATE_LIMITS["gene_drug"].default)
    year_params: dict[str, Any] = {}
    if "min_year" in params:
        year_params["min_year"] = params["min_year"]
    if "max_year" in params:
        year_params["max_year"] = params["max_year"]

    return PipelineConfig(
        name=f"Gene/Drug: {term[:50]}",
        steps=[
            PipelineStep(id="expand", action="expand", params={"topic": term}),
            PipelineStep(
                id="search_direct",
                action="search",
                params={
                    "query": term,
                    "sources": sources,
                    "limit": limit * 2,
                    **year_params,
                },
            ),
            PipelineStep(
                id="search_expanded",
                action="search",
                inputs=["expand"],
                params={
                    "sources": sources,
                    "limit": limit * 2,
                    **year_params,
                },
            ),
            PipelineStep(
                id="merged",
                action="merge",
                inputs=["search_direct", "search_expanded"],
                params={"method": "union"},
            ),
            PipelineStep(id="enriched", action="metrics", inputs=["merged"]),
        ],
        output=PipelineOutput(format="markdown", limit=limit, ranking="impact"),
    )


# =========================================================================
# Registry
# =========================================================================

PIPELINE_TEMPLATES: dict[str, dict[str, Any]] = {
    "pico": {
        "builder": build_pico_pipeline,
        "description": "PICO clinical question → parallel element searches → RRF merge",
        "required_params": ["P", "I"],
        "optional_params": [
            "C",
            "O",
            "P_query",
            "I_query",
            "C_query",
            "O_query",
            "question_type",
            "profile",
            "sources",
            "limit",
        ],
    },
    "comprehensive": {
        "builder": build_comprehensive_pipeline,
        "description": "Multi-source + MeSH expansion → union merge + metrics",
        "required_params": ["query"],
        "optional_params": ["sources", "limit", "min_year", "max_year"],
    },
    "exploration": {
        "builder": build_exploration_pipeline,
        "description": "Seed PMID → related + citing + references → RRF merge",
        "required_params": ["pmid"],
        "optional_params": ["limit"],
    },
    "gene_drug": {
        "builder": build_gene_drug_pipeline,
        "description": "Gene/drug term → expanded multi-source → merge + metrics",
        "required_params": ["term"],
        "optional_params": ["sources", "limit", "min_year", "max_year"],
    },
}


def build_pipeline_from_template(template_name: str, params: dict[str, Any]) -> PipelineConfig:
    """Build a PipelineConfig from a named template.

    Raises:
        ValueError: If template_name is not recognised.
    """
    entry = PIPELINE_TEMPLATES.get(template_name)
    if entry is None:
        msg = f"Unknown template '{template_name}'. Available: {sorted(VALID_TEMPLATES)}"
        raise ValueError(msg)
    builder = entry["builder"]
    result: PipelineConfig = builder(params)
    validate_pipeline_budgets(result)
    return result


def materialize_pipeline_config(
    config: PipelineConfig,
    *,
    default_name: str = "",
) -> PipelineConfig:
    """Expand a template config into executable steps while preserving user output settings.

    Step-based configs are returned unchanged except for an optional default name.
    Template-based configs are rebuilt through the template registry so downstream
    execution paths always receive a step DAG.
    """
    if not config.template:
        if default_name and not config.name:
            config.name = default_name
        return config

    materialized = build_pipeline_from_template(config.template, config.template_params)
    materialized.name = config.name or default_name or materialized.name
    materialized.output = PipelineOutput(
        format=config.output.format,
        limit=config.output.limit,
        ranking=config.output.ranking,
    )
    materialized.globals = dict(config.globals)
    materialized.variables = dict(config.variables)
    materialized.template = config.template
    materialized.template_params = dict(config.template_params)
    validate_pipeline_budgets(materialized)
    return materialized
