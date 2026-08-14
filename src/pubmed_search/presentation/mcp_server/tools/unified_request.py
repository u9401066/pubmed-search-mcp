"""Request normalization for unified search.

Design:
    This module converts raw tool parameters into a stable request object used
    by planning and execution stages. It is the boundary where parsing of
    filters, options, and user-friendly coercions becomes explicit state.

Maintenance:
    Keep parameter normalization here rather than scattering it across planner
    and executor modules. When adding new unified_search options, extend the
    request dataclass and normalization path together.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union

from pubmed_search.shared.credential_sanitizer import contains_credential_material

from .tool_input import InputNormalizer
from .unified_helpers import _parse_filters_detailed, _parse_options_detailed


@dataclass(frozen=True)
class UnifiedSearchRequest:
    """Normalized request parameters for the unified search tool."""

    query: str
    limit: int
    sources: str | None
    ranking: Literal["balanced", "impact", "recency", "quality"]
    output_format: Literal["markdown", "json", "toon"]
    pipeline: str | None
    min_year: int | None
    max_year: int | None
    age_group: str | None
    sex: str | None
    species: str | None
    language: str | None
    clinical_query: str | None
    include_oa_links: bool
    show_analysis: bool
    include_similarity_scores: bool
    include_preprints: bool
    include_research_context: bool
    include_clinical_trials: bool
    counts_first: bool
    native_semantic: bool
    systematic_search: bool
    compact_output: bool
    include_next_tools: bool
    include_section_provenance: bool
    peer_reviewed_only: bool
    auto_relax: bool
    deep_search: bool

    @property
    def retrieval_mode(self) -> Literal["auto", "semantic", "systematic"]:
        """Return the provider-neutral retrieval policy for source adapters."""

        if self.native_semantic:
            return "semantic"
        if self.systematic_search:
            return "systematic"
        return "auto"

    @property
    def advanced_filters(self) -> dict[str, str]:
        return {
            key: value
            for key, value in {
                "age_group": self.age_group,
                "sex": self.sex,
                "species": self.species,
                "language": self.language,
                "clinical_query": self.clinical_query,
            }.items()
            if value is not None
        }


def normalize_unified_search_request(
    *,
    query: str,
    limit: Union[int, str] = 10,
    sources: str | None = None,
    ranking: Literal["balanced", "impact", "recency", "quality"] = "balanced",
    output_format: Literal["markdown", "json", "toon"] = "markdown",
    filters: str | None = None,
    options: str | None = None,
    pipeline: str | None = None,
) -> UnifiedSearchRequest:
    """Normalize raw tool parameters into a request object."""
    normalized_query = InputNormalizer.normalize_query(query)
    if not normalized_query:
        msg = "Empty query"
        raise ValueError(msg)
    if contains_credential_material(normalized_query):
        msg = "query appears to contain credential material; remove secrets and use server environment configuration"
        raise ValueError(msg)

    if isinstance(limit, bool):
        msg = "limit must be an integer from 1 to 100"
        raise ValueError(msg)  # noqa: TRY004 - one stable validation exception for the tool boundary
    try:
        normalized_limit = int(limit)
    except (TypeError, ValueError) as exc:
        msg = "limit must be an integer from 1 to 100"
        raise ValueError(msg) from exc
    if not 1 <= normalized_limit <= 100:
        msg = "limit must be between 1 and 100"
        raise ValueError(msg)

    if ranking not in {"balanced", "impact", "recency", "quality"}:
        msg = f"unsupported ranking mode: {ranking}"
        raise ValueError(msg)
    if output_format not in {"markdown", "json", "toon"}:
        msg = f"unsupported output format: {output_format}"
        raise ValueError(msg)

    parsed_filters, filter_diagnostics = _parse_filters_detailed(filters)
    parsed_options, option_diagnostics = _parse_options_detailed(options)
    diagnostics = (*filter_diagnostics, *option_diagnostics)
    if diagnostics:
        msg = "Invalid unified_search input: " + "; ".join(diagnostics)
        raise ValueError(msg)
    native_semantic = parsed_options.get("native_semantic", False)
    systematic_search = parsed_options.get("systematic_search", False)
    if native_semantic and systematic_search:
        msg = "options 'native_semantic' and 'systematic' are mutually exclusive"
        raise ValueError(msg)

    # Explicit provider-native retrieval is already a complete retrieval plan;
    # do not silently multiply it through semantic-expansion strategies.
    explicit_provider_mode = native_semantic or systematic_search

    return UnifiedSearchRequest(
        query=normalized_query,
        limit=normalized_limit,
        sources=sources.strip() if isinstance(sources, str) and sources.strip() else None,
        ranking=ranking,
        output_format=output_format,
        pipeline=pipeline,
        min_year=parsed_filters.get("min_year"),
        max_year=parsed_filters.get("max_year"),
        age_group=parsed_filters.get("age_group"),
        sex=parsed_filters.get("sex"),
        species=parsed_filters.get("species"),
        language=parsed_filters.get("language"),
        clinical_query=parsed_filters.get("clinical_query"),
        include_oa_links=parsed_options.get("include_oa_links", True),
        show_analysis=parsed_options.get("show_analysis", True),
        include_similarity_scores=parsed_options.get("include_similarity_scores", True),
        include_preprints=parsed_options.get("include_preprints", False),
        include_research_context=parsed_options.get("include_research_context", False),
        include_clinical_trials=parsed_options.get("include_clinical_trials", False),
        counts_first=parsed_options.get("counts_first", False),
        native_semantic=native_semantic,
        systematic_search=systematic_search,
        compact_output=parsed_options.get("compact_output", False),
        include_next_tools=parsed_options.get("include_next_tools", True),
        include_section_provenance=parsed_options.get("include_section_provenance", True),
        peer_reviewed_only=parsed_options.get("peer_reviewed_only", True),
        # A systematic plan is a reproducibility contract.  Replacing an empty
        # Boolean federation with a broader PubMed-only query would silently
        # change both recall semantics and source provenance.
        auto_relax=False if systematic_search else parsed_options.get("auto_relax", True),
        deep_search=False if explicit_provider_mode else parsed_options.get("deep_search", True),
    )


__all__ = ["UnifiedSearchRequest", "normalize_unified_search_request"]
