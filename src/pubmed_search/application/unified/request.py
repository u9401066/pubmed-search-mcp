"""Request normalization for unified search.

Design:
    This module converts raw tool parameters into a stable request object used
    by planning and execution stages. It is the boundary where parsing of
    filters and options becomes explicit state.

Maintenance:
    Keep parameter normalization here rather than scattering it across planner
    and executor modules. When adding new unified_search options, extend the
    request dataclass and normalization path together.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pubmed_search.application.pipeline.config_parser import MAX_PIPELINE_CONFIG_CHARS
from pubmed_search.shared.credential_sanitizer import contains_credential_material

from .helpers import _parse_filters_detailed, _parse_options_detailed

MAX_UNIFIED_QUERY_CHARS = 4_096
MAX_UNIFIED_SOURCES_CHARS = 1_024
MAX_UNIFIED_FILTERS_CHARS = 4_096
MAX_UNIFIED_OPTIONS_CHARS = 2_048
MAX_UNIFIED_PIPELINE_CHARS = MAX_PIPELINE_CONFIG_CHARS
MAX_UNIFIED_STOP_AT_CHARS = 200

_INPUT_CHAR_LIMITS = {
    "query": MAX_UNIFIED_QUERY_CHARS,
    "sources": MAX_UNIFIED_SOURCES_CHARS,
    "filters": MAX_UNIFIED_FILTERS_CHARS,
    "options": MAX_UNIFIED_OPTIONS_CHARS,
    "pipeline": MAX_UNIFIED_PIPELINE_CHARS,
    "stop_at": MAX_UNIFIED_STOP_AT_CHARS,
}


def validate_unified_search_input_envelope(
    *,
    query: str,
    limit: int = 10,
    sources: str | None = None,
    ranking: str = "balanced",
    output_format: str = "markdown",
    filters: str | None = None,
    options: str | None = None,
    pipeline: str | None = None,
    stop_at: str = "",
) -> None:
    """Reject unsafe or unbounded raw values before journaling and parsing.

    Normalization still owns semantic validation.  This preflight is the
    resource and credential boundary shared by normal and pipeline modes, so
    oversized YAML and credential-bearing composite parameters never reach a
    parser, provider, or durable replay record in raw form.
    """

    if isinstance(limit, bool) or not isinstance(limit, int):
        msg = "limit must be an integer from 1 to 100"
        raise ValueError(msg)  # noqa: TRY004 - stable tool-boundary validation contract
    if not 1 <= limit <= 100:
        msg = "limit must be between 1 and 100"
        raise ValueError(msg)

    values = {
        "query": query,
        "sources": sources,
        "ranking": ranking,
        "output_format": output_format,
        "filters": filters,
        "options": options,
        "pipeline": pipeline,
        "stop_at": stop_at,
    }
    for field_name, value in values.items():
        if value is None:
            continue
        if not isinstance(value, str):
            msg = f"{field_name} must be a string"
            raise ValueError(msg)  # noqa: TRY004 - stable tool-boundary validation contract
        char_limit = _INPUT_CHAR_LIMITS.get(field_name, 64)
        if len(value) > char_limit:
            msg = f"{field_name} exceeds the maximum length of {char_limit} characters"
            raise ValueError(msg)
        if contains_credential_material(value):
            msg = (
                f"{field_name} appears to contain credential material; "
                "remove secrets and use server environment configuration"
            )
            raise ValueError(msg)

    if ranking not in {"balanced", "impact", "recency", "quality"}:
        msg = f"unsupported ranking mode: {ranking}"
        raise ValueError(msg)
    if output_format not in {"markdown", "json", "toon"}:
        msg = f"unsupported output format: {output_format}"
        raise ValueError(msg)


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
    include_rank_scores: bool
    include_preprints: bool
    include_clinical_trials: bool
    counts_first: bool
    native_semantic: bool
    systematic_search: bool
    compact_output: bool
    include_next_tools: bool
    include_section_provenance: bool
    exclude_detected_preprints: bool
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
    limit: int = 10,
    sources: str | None = None,
    ranking: Literal["balanced", "impact", "recency", "quality"] = "balanced",
    output_format: Literal["markdown", "json", "toon"] = "markdown",
    filters: str | None = None,
    options: str | None = None,
    pipeline: str | None = None,
) -> UnifiedSearchRequest:
    """Normalize raw tool parameters into a request object."""
    validate_unified_search_input_envelope(
        query=query,
        limit=limit,
        sources=sources,
        ranking=ranking,
        output_format=output_format,
        filters=filters,
        options=options,
        pipeline=pipeline,
    )
    normalized_query = (
        query.strip().replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    )
    if not normalized_query:
        msg = "Empty query"
        raise ValueError(msg)
    if contains_credential_material(normalized_query):
        msg = "query appears to contain credential material; remove secrets and use server environment configuration"
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

    include_preprints = parsed_options.get("include_preprints", False)
    source_tokens = () if sources is None else sources.split(",")
    explicit_sources = {token for token in source_tokens if token and not token.startswith("-")}
    explicitly_selected_preprints = bool(explicit_sources & {"arxiv", "medrxiv", "biorxiv"})
    return UnifiedSearchRequest(
        query=normalized_query,
        limit=limit,
        sources=sources,
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
        include_rank_scores=parsed_options.get("include_rank_scores", True),
        include_preprints=include_preprints,
        include_clinical_trials=parsed_options.get("include_clinical_trials", False),
        counts_first=parsed_options.get("counts_first", False),
        native_semantic=native_semantic,
        systematic_search=systematic_search,
        compact_output=parsed_options.get("compact_output", False),
        include_next_tools=parsed_options.get("include_next_tools", True),
        include_section_provenance=parsed_options.get("include_section_provenance", True),
        exclude_detected_preprints=not (
            include_preprints
            or explicitly_selected_preprints
            or parsed_options.get("include_detected_preprints", False)
        ),
        # A systematic plan is a reproducibility contract.  Replacing an empty
        # Boolean federation with a broader PubMed-only query would silently
        # change both recall semantics and source provenance.
        auto_relax=False if systematic_search else parsed_options.get("auto_relax", True),
        deep_search=False if explicit_provider_mode else parsed_options.get("deep_search", True),
    )


__all__ = [
    "MAX_UNIFIED_PIPELINE_CHARS",
    "MAX_UNIFIED_QUERY_CHARS",
    "UnifiedSearchRequest",
    "normalize_unified_search_request",
    "validate_unified_search_input_envelope",
]
