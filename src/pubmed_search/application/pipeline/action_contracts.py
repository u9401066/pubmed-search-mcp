"""Schema-exact parameter contracts for executable pipeline actions.

The outer pipeline schema deliberately keeps ``params`` as a mapping because
the valid fields depend on ``action``. This module is the second-stage typed
discriminator: every executable action has exactly one strict Pydantic model,
and both persistence validation and the executor use the same registry.
"""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator, model_validator

from pubmed_search.application.pipeline.budgets import PIPELINE_ACTION_LIMITS
from pubmed_search.domain.entities.article import ArticleType
from pubmed_search.domain.entities.pipeline import VALID_ACTIONS
from pubmed_search.domain.value_objects.ncbi_identifiers import normalize_ncbi_identifier

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pubmed_search.domain.entities.pipeline import PipelineConfig, PipelineStep

MAX_PIPELINE_DETAILS_PMIDS = 500

_VARIABLE_NAME = r"[A-Za-z_][A-Za-z0-9_.-]*"
_VARIABLE_REFERENCE_RE = re.compile(rf"^\$\{{{_VARIABLE_NAME}\}}$")
_VARIABLE_TOKEN_RE = re.compile(rf"\$\{{{_VARIABLE_NAME}\}}")

VariableReference = Annotated[str, StringConstraints(pattern=_VARIABLE_REFERENCE_RE.pattern)]
NonEmptyString = Annotated[str, StringConstraints(min_length=1)]
PipelineYear = Annotated[int, Field(ge=1000, le=9999)]
NonNegativeInteger = Annotated[int, Field(ge=0)]

SearchLimit = Annotated[
    int,
    Field(
        ge=PIPELINE_ACTION_LIMITS["search"].minimum,
        le=PIPELINE_ACTION_LIMITS["search"].maximum,
    ),
]
RelatedLimit = Annotated[
    int,
    Field(
        ge=PIPELINE_ACTION_LIMITS["related"].minimum,
        le=PIPELINE_ACTION_LIMITS["related"].maximum,
    ),
]
CitingLimit = Annotated[
    int,
    Field(
        ge=PIPELINE_ACTION_LIMITS["citing"].minimum,
        le=PIPELINE_ACTION_LIMITS["citing"].maximum,
    ),
]
ReferencesLimit = Annotated[
    int,
    Field(
        ge=PIPELINE_ACTION_LIMITS["references"].minimum,
        le=PIPELINE_ACTION_LIMITS["references"].maximum,
    ),
]

SearchElement = Literal["P", "I", "C", "O"]
CombinedQueryMode = Literal["precision", "recall", "intervention_outcome", "comparison_outcome"]
MergeMethod = Literal["union", "intersection", "rrf"]
AgeGroup = Literal[
    "newborn",
    "infant",
    "preschool",
    "child",
    "adolescent",
    "young_adult",
    "adult",
    "middle_aged",
    "aged",
    "aged_80",
]
Sex = Literal["male", "female"]
Species = Literal["humans", "animals"]
Language = Literal[
    "english",
    "chinese",
    "japanese",
    "german",
    "french",
    "spanish",
    "korean",
    "italian",
    "portuguese",
    "russian",
]
ClinicalQuery = Literal[
    "therapy",
    "therapy_narrow",
    "diagnosis",
    "diagnosis_narrow",
    "prognosis",
    "prognosis_narrow",
    "etiology",
    "etiology_narrow",
    "clinical_prediction",
    "clinical_prediction_narrow",
]
ArticleTypeValue = Literal[
    "journal-article",
    "review",
    "meta-analysis",
    "systematic-review",
    "clinical-trial",
    "randomized-controlled-trial",
    "case-report",
    "letter",
    "editorial",
    "comment",
    "preprint",
    "book-chapter",
    "conference-paper",
    "thesis",
    "dataset",
    "other",
    "unknown",
]

PIPELINE_SEARCH_SOURCES = frozenset(
    {
        "pubmed",
        "semantic_scholar",
        "openalex",
        "europe_pmc",
        "core",
        "scopus",
        "web_of_science",
    }
)


def is_pipeline_variable_reference(value: object) -> bool:
    """Return whether ``value`` is one complete typed variable reference."""
    return isinstance(value, str) and _VARIABLE_REFERENCE_RE.fullmatch(value) is not None


def _contains_variable_token(value: object) -> bool:
    if isinstance(value, str):
        return _VARIABLE_TOKEN_RE.search(value) is not None
    if isinstance(value, list):
        return any(_contains_variable_token(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_variable_token(item) for item in value.values())
    return False


def _require_non_blank(value: str, *, field: str) -> str:
    if not value.strip():
        raise ValueError(f"{field} must not be blank")
    return value


class _ActionParamsModel(BaseModel):
    """Shared strict, closed-world action parameter settings."""

    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_nulls(cls, value: Any) -> Any:
        if isinstance(value, dict):
            null_fields = sorted(str(key) for key, item in value.items() if item is None)
            if null_fields:
                raise ValueError(f"explicit null is not allowed for: {', '.join(null_fields)}")
        return value


class SearchParams(_ActionParamsModel):
    """Typed parameters for a literature-search step."""

    query: NonEmptyString | None = None
    sources: list[str] | VariableReference | None = None
    limit: SearchLimit | VariableReference | None = None
    min_year: PipelineYear | VariableReference | None = None
    max_year: PipelineYear | VariableReference | None = None
    element: SearchElement | VariableReference | None = None
    use_combined: CombinedQueryMode | VariableReference | None = None
    strategy: NonEmptyString | None = None
    age_group: AgeGroup | VariableReference | None = None
    sex: Sex | VariableReference | None = None
    species: Species | VariableReference | None = None
    language: Language | VariableReference | None = None
    clinical_query: ClinicalQuery | VariableReference | None = None

    @field_validator("query", "strategy")
    @classmethod
    def _validate_non_blank_strings(cls, value: str | None, info: Any) -> str | None:
        if value is not None:
            _require_non_blank(value, field=info.field_name)
        return value

    @field_validator("sources")
    @classmethod
    def _validate_sources(cls, value: list[str] | str | None) -> list[str] | str | None:
        if value is None or is_pipeline_variable_reference(value):
            return value
        if not value:
            raise ValueError("sources must contain at least one canonical source")
        invalid = sorted(
            {
                source
                for source in value
                if source not in PIPELINE_SEARCH_SOURCES and not is_pipeline_variable_reference(source)
            }
        )
        if invalid:
            raise ValueError(
                f"unknown source(s): {', '.join(invalid)}; valid sources: {', '.join(sorted(PIPELINE_SEARCH_SOURCES))}"
            )
        concrete_sources = [source for source in value if not is_pipeline_variable_reference(source)]
        if len(concrete_sources) != len(set(concrete_sources)):
            raise ValueError("sources must not contain duplicates")
        return value

    @model_validator(mode="after")
    def _validate_year_range(self) -> SearchParams:
        if isinstance(self.min_year, int) and isinstance(self.max_year, int) and self.min_year > self.max_year:
            raise ValueError("min_year must be less than or equal to max_year")
        return self


class PicoParams(_ActionParamsModel):
    """Typed PICO handoff parameters."""

    population: NonEmptyString = Field(alias="P")
    intervention: NonEmptyString = Field(alias="I")
    comparison: NonEmptyString | None = Field(default=None, alias="C")
    outcome: NonEmptyString | None = Field(default=None, alias="O")
    population_query: NonEmptyString | None = Field(default=None, alias="P_query")
    intervention_query: NonEmptyString | None = Field(default=None, alias="I_query")
    comparison_query: NonEmptyString | None = Field(default=None, alias="C_query")
    outcome_query: NonEmptyString | None = Field(default=None, alias="O_query")

    @field_validator(
        "population",
        "intervention",
        "comparison",
        "outcome",
        "population_query",
        "intervention_query",
        "comparison_query",
        "outcome_query",
    )
    @classmethod
    def _validate_non_blank_strings(cls, value: str | None, info: Any) -> str | None:
        if value is not None:
            _require_non_blank(value, field=info.field_name)
        return value


class ExpandParams(_ActionParamsModel):
    """Typed semantic-expansion parameters."""

    topic: NonEmptyString

    @field_validator("topic")
    @classmethod
    def _validate_topic(cls, value: str) -> str:
        return _require_non_blank(value, field="topic")


class DetailsParams(_ActionParamsModel):
    """Typed batch-detail parameters."""

    pmids: list[NonEmptyString | VariableReference] | VariableReference | None = None

    @field_validator("pmids")
    @classmethod
    def _validate_pmids(cls, value: list[str] | str | None) -> list[str] | str | None:
        if value is None or is_pipeline_variable_reference(value):
            return value
        if len(value) > MAX_PIPELINE_DETAILS_PMIDS:
            raise ValueError(f"pmids may contain at most {MAX_PIPELINE_DETAILS_PMIDS} values")
        concrete_pmids: list[str] = []
        for item in value:
            if not is_pipeline_variable_reference(item):
                concrete_pmids.append(normalize_ncbi_identifier(item, label="Pipeline details PMID"))
        if len(concrete_pmids) != len(set(concrete_pmids)):
            raise ValueError("pmids must not contain duplicates")
        return value


class RelatedParams(_ActionParamsModel):
    """Typed related-article discovery parameters."""

    pmid: NonEmptyString | VariableReference
    limit: RelatedLimit | VariableReference | None = None

    @field_validator("pmid")
    @classmethod
    def _validate_pmid(cls, value: str) -> str:
        if not is_pipeline_variable_reference(value):
            normalize_ncbi_identifier(value, label="Pipeline related PMID")
        return value


class CitingParams(_ActionParamsModel):
    """Typed citing-article discovery parameters."""

    pmid: NonEmptyString | VariableReference
    limit: CitingLimit | VariableReference | None = None

    @field_validator("pmid")
    @classmethod
    def _validate_pmid(cls, value: str) -> str:
        if not is_pipeline_variable_reference(value):
            normalize_ncbi_identifier(value, label="Pipeline citing PMID")
        return value


class ReferencesParams(_ActionParamsModel):
    """Typed reference discovery parameters."""

    pmid: NonEmptyString | VariableReference
    limit: ReferencesLimit | VariableReference | None = None

    @field_validator("pmid")
    @classmethod
    def _validate_pmid(cls, value: str) -> str:
        if not is_pipeline_variable_reference(value):
            normalize_ncbi_identifier(value, label="Pipeline references PMID")
        return value


class MetricsParams(_ActionParamsModel):
    """Metrics has no action-specific parameters."""


class MergeParams(_ActionParamsModel):
    """Typed result-set merge parameters."""

    method: MergeMethod | VariableReference = "union"


class FilterParams(_ActionParamsModel):
    """Typed post-retrieval filter parameters."""

    min_year: PipelineYear | VariableReference | None = None
    max_year: PipelineYear | VariableReference | None = None
    article_types: list[ArticleTypeValue | VariableReference] | VariableReference | None = None
    min_citations: NonNegativeInteger | VariableReference | None = None
    has_abstract: bool | VariableReference | None = None

    @model_validator(mode="after")
    def _validate_year_range(self) -> FilterParams:
        if isinstance(self.min_year, int) and isinstance(self.max_year, int) and self.min_year > self.max_year:
            raise ValueError("min_year must be less than or equal to max_year")
        return self


_ACTION_PARAM_MODELS: Mapping[str, type[_ActionParamsModel]] = MappingProxyType(
    {
        "search": SearchParams,
        "pico": PicoParams,
        "expand": ExpandParams,
        "details": DetailsParams,
        "related": RelatedParams,
        "citing": CitingParams,
        "references": ReferencesParams,
        "metrics": MetricsParams,
        "merge": MergeParams,
        "filter": FilterParams,
    }
)
if frozenset(_ACTION_PARAM_MODELS) != VALID_ACTIONS:  # pragma: no cover - import-time invariant
    missing = sorted(VALID_ACTIONS - _ACTION_PARAM_MODELS.keys())
    extra = sorted(_ACTION_PARAM_MODELS.keys() - VALID_ACTIONS)
    raise RuntimeError(f"Pipeline action contract registry mismatch; missing={missing}, extra={extra}")

_ACTION_PARAM_KEYS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        action: frozenset(field.alias or name for name, field in model.model_fields.items())
        for action, model in _ACTION_PARAM_MODELS.items()
    }
)


def allowed_pipeline_action_param_keys(action: str) -> frozenset[str]:
    """Return the closed set of canonical parameter keys for ``action``."""
    return _ACTION_PARAM_KEYS.get(action, frozenset())


def validate_pipeline_globals(config: PipelineConfig) -> None:
    """Reject global parameter keys that no step in this pipeline can consume."""
    applicable_keys = frozenset().union(*(allowed_pipeline_action_param_keys(step.action) for step in config.steps))
    invalid_keys = sorted(str(key) for key in config.globals if not isinstance(key, str) or key not in applicable_keys)
    if invalid_keys:
        raise ValueError(f"Pipeline globals contain unknown or unused parameter(s): {', '.join(invalid_keys)}")


def _effective_step_params(step: PipelineStep, global_params: Mapping[str, Any] | None) -> dict[str, Any]:
    applicable_globals = {
        key: value
        for key, value in (global_params or {}).items()
        if key in allowed_pipeline_action_param_keys(step.action)
    }
    return {**applicable_globals, **step.params}


def _format_action_validation_error(action: str, exc: ValidationError) -> str:
    messages: list[str] = []
    for error in exc.errors(include_input=False, include_url=False):
        location = ".".join(str(part) for part in error.get("loc", ()))
        message = str(error.get("msg", "Invalid value"))
        messages.append(f"{location}: {message}" if location else message)
    return f"Invalid {action} params: {'; '.join(messages)}"


def validate_pipeline_details_pmids(value: object) -> list[str]:
    """Return a bounded canonical PMID array without scalar/CSV coercion."""
    if not isinstance(value, list):
        raise TypeError("Pipeline details pmids must be a JSON/YAML array of PMID strings")
    if len(value) > MAX_PIPELINE_DETAILS_PMIDS:
        raise ValueError(f"Pipeline details pmids may contain at most {MAX_PIPELINE_DETAILS_PMIDS} values")

    pmids: list[str] = []
    for item in value:
        pmid = normalize_ncbi_identifier(item, label="Pipeline details PMID")
        pmids.append(pmid)
    if len(pmids) != len(set(pmids)):
        raise ValueError("Pipeline details pmids must not contain duplicates")
    return pmids


def validate_pipeline_discovery_pmid(value: object, *, action: str) -> str:
    """Return the canonical PMID for a single-record discovery action."""
    return normalize_ncbi_identifier(value, label=f"Pipeline {action} PMID")


def validate_pipeline_step_action_contract(
    step: PipelineStep,
    *,
    global_params: Mapping[str, Any] | None = None,
    allow_variable_references: bool = False,
) -> None:
    """Validate one step against its action-discriminated typed contract."""
    model = _ACTION_PARAM_MODELS.get(step.action)
    if model is None:
        return
    params = _effective_step_params(step, global_params)
    if not allow_variable_references and _contains_variable_token(params):
        raise ValueError(f"Invalid {step.action} params: unresolved variable reference")
    try:
        model.model_validate(params)
    except ValidationError as exc:
        raise ValueError(_format_action_validation_error(step.action, exc)) from None


def validate_pipeline_action_contracts(
    config: PipelineConfig,
    *,
    allow_variable_references: bool = False,
) -> None:
    """Apply executable action contracts to every step in one config."""
    validate_pipeline_globals(config)
    for step in config.steps:
        try:
            validate_pipeline_step_action_contract(
                step,
                global_params=config.globals,
                allow_variable_references=allow_variable_references,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Step '{step.id}': {exc}") from None


def canonical_article_type_values() -> frozenset[str]:
    """Return the domain's canonical article-type enum values."""
    return frozenset(article_type.value for article_type in ArticleType)


__all__ = [
    "MAX_PIPELINE_DETAILS_PMIDS",
    "PIPELINE_SEARCH_SOURCES",
    "allowed_pipeline_action_param_keys",
    "canonical_article_type_values",
    "is_pipeline_variable_reference",
    "validate_pipeline_action_contracts",
    "validate_pipeline_details_pmids",
    "validate_pipeline_discovery_pmid",
    "validate_pipeline_globals",
    "validate_pipeline_step_action_contract",
]
