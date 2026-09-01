"""Strict parameter contracts for built-in pipeline templates."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator, model_validator

from pubmed_search.application.pipeline.action_contracts import PIPELINE_SEARCH_SOURCES
from pubmed_search.application.pipeline.budgets import PIPELINE_TEMPLATE_LIMITS
from pubmed_search.domain.entities.pipeline import VALID_TEMPLATES
from pubmed_search.domain.value_objects.ncbi_identifiers import normalize_ncbi_identifier

NonEmptyString = Annotated[str, StringConstraints(min_length=1)]
TemplateYear = Annotated[int, Field(ge=1000, le=9999)]
PicoProfile = Literal["precision", "balanced", "recall"]
PicoQuestionType = Literal[
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
PicoTemplateLimit = Annotated[
    int,
    Field(
        ge=PIPELINE_TEMPLATE_LIMITS["pico"].minimum,
        le=PIPELINE_TEMPLATE_LIMITS["pico"].maximum,
    ),
]
ComprehensiveTemplateLimit = Annotated[
    int,
    Field(
        ge=PIPELINE_TEMPLATE_LIMITS["comprehensive"].minimum,
        le=PIPELINE_TEMPLATE_LIMITS["comprehensive"].maximum,
    ),
]
ExplorationTemplateLimit = Annotated[
    int,
    Field(
        ge=PIPELINE_TEMPLATE_LIMITS["exploration"].minimum,
        le=PIPELINE_TEMPLATE_LIMITS["exploration"].maximum,
    ),
]
GeneDrugTemplateLimit = Annotated[
    int,
    Field(
        ge=PIPELINE_TEMPLATE_LIMITS["gene_drug"].minimum,
        le=PIPELINE_TEMPLATE_LIMITS["gene_drug"].maximum,
    ),
]


def _require_non_blank(value: str, *, field: str) -> str:
    if not value.strip():
        raise ValueError(f"{field} must not be blank")
    return value


def _validate_source_list(value: list[str]) -> list[str]:
    if not value:
        raise ValueError("sources must contain at least one canonical source")
    invalid = sorted({source for source in value if source not in PIPELINE_SEARCH_SOURCES})
    if invalid:
        raise ValueError(
            f"unknown source(s): {', '.join(invalid)}; valid sources: {', '.join(sorted(PIPELINE_SEARCH_SOURCES))}"
        )
    if len(value) != len(set(value)):
        raise ValueError("sources must not contain duplicates")
    return value


class _TemplateParamsModel(BaseModel):
    """Shared strict, closed-world template parameter settings."""

    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_nulls(cls, value: Any) -> Any:
        if isinstance(value, dict):
            null_fields = sorted(str(key) for key, item in value.items() if item is None)
            if null_fields:
                raise ValueError(f"explicit null is not allowed for: {', '.join(null_fields)}")
        return value


class PicoTemplateParams(_TemplateParamsModel):
    """Typed inputs for the PICO template."""

    population: NonEmptyString = Field(alias="P")
    intervention: NonEmptyString = Field(alias="I")
    comparison: NonEmptyString | None = Field(default=None, alias="C")
    outcome: NonEmptyString | None = Field(default=None, alias="O")
    population_query: NonEmptyString | None = Field(default=None, alias="P_query")
    intervention_query: NonEmptyString | None = Field(default=None, alias="I_query")
    comparison_query: NonEmptyString | None = Field(default=None, alias="C_query")
    outcome_query: NonEmptyString | None = Field(default=None, alias="O_query")
    question_type: PicoQuestionType | None = None
    profile: PicoProfile | None = None
    sources: list[str] | None = None
    limit: PicoTemplateLimit | None = None

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

    @field_validator("sources")
    @classmethod
    def _validate_sources(cls, value: list[str] | None) -> list[str] | None:
        return _validate_source_list(value) if value is not None else None


class _SearchTemplateParams(_TemplateParamsModel):
    """Shared query/source/year inputs for search templates."""

    sources: list[str] | None = None
    limit: int | None = None
    min_year: TemplateYear | None = None
    max_year: TemplateYear | None = None

    @field_validator("sources")
    @classmethod
    def _validate_sources(cls, value: list[str] | None) -> list[str] | None:
        return _validate_source_list(value) if value is not None else None

    @model_validator(mode="after")
    def _validate_year_range(self) -> _SearchTemplateParams:
        if self.min_year is not None and self.max_year is not None and self.min_year > self.max_year:
            raise ValueError("min_year must be less than or equal to max_year")
        return self


class ComprehensiveTemplateParams(_SearchTemplateParams):
    """Typed inputs for the comprehensive template."""

    query: NonEmptyString
    limit: ComprehensiveTemplateLimit | None = None

    @field_validator("query")
    @classmethod
    def _validate_query(cls, value: str) -> str:
        return _require_non_blank(value, field="query")


class ExplorationTemplateParams(_TemplateParamsModel):
    """Typed inputs for the seed-paper exploration template."""

    pmid: NonEmptyString
    limit: ExplorationTemplateLimit | None = None

    @field_validator("pmid")
    @classmethod
    def _validate_pmid(cls, value: str) -> str:
        normalize_ncbi_identifier(value, label="Exploration template PMID")
        return value


class GeneDrugTemplateParams(_SearchTemplateParams):
    """Typed inputs for the gene/drug template."""

    term: NonEmptyString
    limit: GeneDrugTemplateLimit | None = None

    @field_validator("term")
    @classmethod
    def _validate_term(cls, value: str) -> str:
        return _require_non_blank(value, field="term")


_TEMPLATE_PARAM_MODELS: dict[str, type[_TemplateParamsModel]] = {
    "pico": PicoTemplateParams,
    "comprehensive": ComprehensiveTemplateParams,
    "exploration": ExplorationTemplateParams,
    "gene_drug": GeneDrugTemplateParams,
}
if frozenset(_TEMPLATE_PARAM_MODELS) != VALID_TEMPLATES:  # pragma: no cover - import-time invariant
    missing = sorted(VALID_TEMPLATES - _TEMPLATE_PARAM_MODELS.keys())
    extra = sorted(_TEMPLATE_PARAM_MODELS.keys() - VALID_TEMPLATES)
    raise RuntimeError(f"Pipeline template contract registry mismatch; missing={missing}, extra={extra}")


def _format_template_validation_error(template: str, exc: ValidationError) -> str:
    messages: list[str] = []
    for error in exc.errors(include_input=False, include_url=False):
        location = ".".join(str(part) for part in error.get("loc", ()))
        message = str(error.get("msg", "Invalid value"))
        messages.append(f"{location}: {message}" if location else message)
    return f"Invalid {template} template_params: {'; '.join(messages)}"


def validate_pipeline_template_params(template: str, params: dict[str, Any]) -> None:
    """Validate one built-in template's complete parameter mapping."""

    model = _TEMPLATE_PARAM_MODELS.get(template)
    if model is None:
        return
    try:
        model.model_validate(params)
    except ValidationError as exc:
        raise ValueError(_format_template_validation_error(template, exc)) from None


__all__ = ["validate_pipeline_template_params"]
