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


def _normalize_template_limit(value: Any, *, default: int = 20, min_value: int = 1, max_value: int = 100) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default
    return max(min_value, min(limit, max_value))


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
        sources: comma-separated sources (default: "pubmed")
        limit: result limit (default: 20)
    """
    p = params.get("P", "")
    i = params.get("I", "")
    c = params.get("C", "")
    o = params.get("O", "")
    profile = str(params.get("profile", "balanced")).strip().lower()
    if profile not in PICO_PROFILES:
        msg = "PICO template profile must be one of: precision, balanced, recall"
        raise ValueError(msg)
    question_type = str(params.get("question_type", "")).strip()
    sources = str(params.get("sources", "pubmed")).strip() or "pubmed"
    limit = _normalize_template_limit(params.get("limit", 20))

    if not p or not i:
        msg = "PICO template requires at least 'P' (Population) and 'I' (Intervention)"
        raise ValueError(msg)

    pico_params: dict[str, Any] = {"P": p, "I": i, "C": c, "O": o}
    for key in ("P_query", "I_query", "C_query", "O_query"):
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
                params=search_params(use_combined="precision", step_limit=limit * 3),
            )
        )
        merge_inputs.append("search_precision")

    if profile in {"balanced", "recall"}:
        steps.append(
            PipelineStep(
                id="search_recall",
                action="search",
                inputs=["pico"],
                params=search_params(use_combined="recall", step_limit=limit * 3),
            )
        )
        merge_inputs.append("search_recall")

    if profile in {"balanced", "recall"} and o:
        steps.append(
            PipelineStep(
                id="search_intervention_outcome",
                action="search",
                inputs=["pico"],
                params=search_params(use_combined="intervention_outcome", step_limit=limit * 2),
            )
        )
        merge_inputs.append("search_intervention_outcome")

    if profile == "balanced" and c and o:
        steps.append(
            PipelineStep(
                id="search_comparison_outcome",
                action="search",
                inputs=["pico"],
                params=search_params(use_combined="comparison_outcome", step_limit=limit * 2),
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
        sources: comma-separated sources (default: "pubmed,openalex,europe_pmc")
        limit: result limit (default: 30)
        min_year / max_year: year filter
    """
    query = params.get("query", "")
    if not query:
        msg = "Comprehensive template requires 'query'"
        raise ValueError(msg)

    sources = params.get("sources", "pubmed,openalex,europe_pmc")
    limit = int(params.get("limit", 30))
    year_params: dict[str, Any] = {}
    if params.get("min_year"):
        year_params["min_year"] = int(params["min_year"])
    if params.get("max_year"):
        year_params["max_year"] = int(params["max_year"])

    return PipelineConfig(
        name=f"Comprehensive: {query[:50]}",
        steps=[
            PipelineStep(id="expand", action="expand", params={"topic": query}),
            PipelineStep(
                id="search_original",
                action="search",
                params={"query": query, "sources": sources, "limit": limit * 2, **year_params},
            ),
            PipelineStep(
                id="search_expanded",
                action="search",
                inputs=["expand"],
                params={"strategy": "mesh", "sources": sources, "limit": limit * 2, **year_params},
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
    pmid = str(params.get("pmid", ""))
    if not pmid:
        msg = "Exploration template requires 'pmid'"
        raise ValueError(msg)

    limit = int(params.get("limit", 20))

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
        sources: comma-separated (default: "pubmed,openalex")
        limit: result limit (default: 20)
        min_year / max_year: year filter
    """
    term = params.get("term", "")
    if not term:
        msg = "Gene/Drug template requires 'term'"
        raise ValueError(msg)

    sources = params.get("sources", "pubmed,openalex")
    limit = int(params.get("limit", 20))
    year_params: dict[str, Any] = {}
    if params.get("min_year"):
        year_params["min_year"] = int(params["min_year"])
    if params.get("max_year"):
        year_params["max_year"] = int(params["max_year"])

    return PipelineConfig(
        name=f"Gene/Drug: {term[:50]}",
        steps=[
            PipelineStep(id="expand", action="expand", params={"topic": term}),
            PipelineStep(
                id="search_direct",
                action="search",
                params={"query": term, "sources": sources, "limit": limit * 2, **year_params},
            ),
            PipelineStep(
                id="search_expanded",
                action="search",
                inputs=["expand"],
                params={"strategy": "mesh", "sources": sources, "limit": limit * 2, **year_params},
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
        "optional_params": ["C", "O", "sources", "limit"],
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

    materialized = build_pipeline_from_template(str(config.template), config.template_params)
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
    return materialized
