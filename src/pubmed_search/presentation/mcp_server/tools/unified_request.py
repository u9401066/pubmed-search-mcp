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

from .tool_input import InputNormalizer
from .unified_helpers import _parse_filters, _parse_options


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
    counts_first: bool
    peer_reviewed_only: bool
    auto_relax: bool
    deep_search: bool

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

    normalized_limit = InputNormalizer.normalize_limit(limit, default=10, max_val=100)
    parsed_filters = _parse_filters(filters)
    parsed_options = _parse_options(options)

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
        counts_first=parsed_options.get("counts_first", False),
        peer_reviewed_only=parsed_options.get("peer_reviewed_only", True),
        auto_relax=parsed_options.get("auto_relax", True),
        deep_search=parsed_options.get("deep_search", True),
    )


__all__ = ["UnifiedSearchRequest", "normalize_unified_search_request"]
