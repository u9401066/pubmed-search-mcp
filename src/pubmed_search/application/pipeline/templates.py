"""
Built-in pipeline templates for common search workflows.

Templates generate PipelineConfig from minimal parameters, saving
agents from manually constructing multi-step pipeline JSON.

Available templates:
- **pico**: PICO clinical question → parallel element searches → RRF merge
- **comprehensive**: Multi-source + MeSH expansion → union merge + metrics
- **exploration**: Seed PMID → related + citing + refs → RRF merge
- **gene_drug**: Gene/drug term → expanded multi-source → merge + metrics
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


def build_pico_pipeline(params: dict[str, Any]) -> PipelineConfig:
    """PICO clinical question search pipeline.

    Required params:
        P: Population description
        I: Intervention description
    Optional params:
        C: Comparison (default: "")
        O: Outcome (default: "")
        sources: comma-separated sources (default: "pubmed")
        limit: result limit (default: 20)
    """
    p = params.get("P", "")
    i = params.get("I", "")
    c = params.get("C", "")
    o = params.get("O", "")
    sources = params.get("sources", "pubmed")
    limit = int(params.get("limit", 20))

    if not p or not i:
        msg = "PICO template requires at least 'P' (Population) and 'I' (Intervention)"
        raise ValueError(msg)

    steps: list[PipelineStep] = [
        PipelineStep(
            id="pico",
            action="pico",
            params={"P": p, "I": i, "C": c, "O": o},
        ),
        PipelineStep(
            id="search_p",
            action="search",
            inputs=["pico"],
            params={"element": "P", "sources": sources, "limit": limit * 3},
        ),
        PipelineStep(
            id="search_i",
            action="search",
            inputs=["pico"],
            params={"element": "I", "sources": sources, "limit": limit * 3},
        ),
    ]

    merge_inputs = ["search_p", "search_i"]

    if c:
        steps.append(
            PipelineStep(
                id="search_c",
                action="search",
                inputs=["pico"],
                params={"element": "C", "sources": sources, "limit": limit * 3},
            )
        )
        merge_inputs.append("search_c")

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
