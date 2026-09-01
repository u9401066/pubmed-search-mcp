"""Pydantic schema parsing for pipeline configs.

This module owns strict structural parsing concerns only:
- raw mapping validation
- mode discrimination (template vs step pipeline)
- default values

Semantic validation remains in validator.py.

Maintenance:
    Keep defaults for omitted fields here, but reject explicit nulls, wrong
    types, retired aliases, and unknown fields without rewriting caller input.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from pubmed_search.application.pipeline.budgets import PIPELINE_OUTPUT_LIMIT
from pubmed_search.domain.entities.pipeline import (
    MAX_PIPELINE_STEPS,
    PipelineConfig,
    PipelineOutput,
    PipelineStep,
    ValidationResult,
)


class _PipelineSchemaModel(BaseModel):
    """Shared Pydantic settings for pipeline schema models."""

    model_config = ConfigDict(extra="forbid", strict=True)


class PipelineStepSchema(_PipelineSchemaModel):
    """Schema model for one pipeline step."""

    id: str = ""
    action: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    inputs: list[str] = Field(default_factory=list)
    on_error: Literal["skip", "abort"] = "skip"

    def to_domain(self) -> PipelineStep:
        """Convert schema model into the existing domain dataclass."""
        return PipelineStep(
            id=self.id,
            action=self.action,
            params=self.params,
            inputs=self.inputs,
            on_error=cast("Any", self.on_error),
        )


class PipelineOutputSchema(_PipelineSchemaModel):
    """Schema model for pipeline output settings."""

    format: Literal["markdown", "json"] = "markdown"
    limit: int = Field(
        default=PIPELINE_OUTPUT_LIMIT.default,
        ge=PIPELINE_OUTPUT_LIMIT.minimum,
        le=PIPELINE_OUTPUT_LIMIT.maximum,
    )
    ranking: Literal["balanced", "impact", "recency", "quality"] = "balanced"

    def to_domain(self) -> PipelineOutput:
        """Convert schema model into the existing domain dataclass."""
        return PipelineOutput(
            format=cast("Any", self.format),
            limit=self.limit,
            ranking=cast("Any", self.ranking),
        )


class _PipelineConfigBaseSchema(_PipelineSchemaModel):
    """Common fields shared by both pipeline config variants."""

    name: str = ""
    globals: dict[str, Any] = Field(default_factory=dict)
    variables: dict[str, Any] = Field(default_factory=dict)
    output: PipelineOutputSchema = Field(default_factory=PipelineOutputSchema)


class StepPipelineConfigSchema(_PipelineConfigBaseSchema):
    """Schema for explicit step DAG pipelines."""

    kind: Literal["steps"] = "steps"
    steps: list[PipelineStepSchema] = Field(min_length=1, max_length=MAX_PIPELINE_STEPS)

    def to_domain(self) -> PipelineConfig:
        """Convert schema model into the existing domain dataclass."""
        return PipelineConfig(
            name=self.name,
            steps=[step.to_domain() for step in self.steps],
            output=self.output.to_domain(),
            globals=self.globals,
            variables=self.variables,
        )


class TemplatePipelineConfigSchema(_PipelineConfigBaseSchema):
    """Schema for template-based pipelines."""

    kind: Literal["template"] = "template"
    template: str
    template_params: dict[str, Any] = Field(default_factory=dict)

    def to_domain(self) -> PipelineConfig:
        """Convert schema model into the existing domain dataclass."""
        return PipelineConfig(
            name=self.name,
            output=self.output.to_domain(),
            globals=self.globals,
            variables=self.variables,
            template=self.template,
            template_params=self.template_params,
        )


PipelineConfigSchema = Annotated[
    StepPipelineConfigSchema | TemplatePipelineConfigSchema,
    Field(discriminator="kind"),
]

_PIPELINE_CONFIG_ADAPTER: TypeAdapter[PipelineConfigSchema] = TypeAdapter(PipelineConfigSchema)


def _inject_pipeline_kind(raw: dict[str, Any]) -> dict[str, Any]:
    """Infer the config variant only when the discriminator is omitted.

    An explicitly supplied ``kind`` is caller intent and must reach Pydantic's
    strict discriminated-union validation unchanged. Overwriting it would let
    malformed or contradictory configurations bypass the canonical schema.
    """
    normalized = dict(raw)
    if "kind" in normalized:
        return normalized
    template = normalized.get("template")
    if isinstance(template, str) and template:
        normalized["kind"] = "template"
    else:
        normalized["kind"] = "steps"
    return normalized


def _format_validation_errors(exc: ValidationError) -> list[str]:
    """Convert Pydantic errors into user-facing pipeline validation errors."""
    errors: list[str] = []
    for error in exc.errors(include_url=False):
        loc_parts = [str(part) for part in error.get("loc", ()) if part != "kind"]
        loc = ".".join(loc_parts)
        msg = str(error.get("msg", "Invalid pipeline config"))

        if loc == "steps" and ("at least 1 item" in msg.lower() or "field required" in msg.lower()):
            errors.append("Pipeline must have at least one step (or use a template)")
            continue
        if loc == "steps" and "at most" in msg.lower():
            errors.append(f"Pipeline has too many steps, maximum is {MAX_PIPELINE_STEPS}")
            continue

        errors.append(f"{loc}: {msg}" if loc else msg)
    return errors


def parse_pipeline_schema(raw: dict[str, Any]) -> ValidationResult:
    """Parse raw pipeline input via Pydantic before semantic validation.

    Returns a ValidationResult carrying only schema-level errors and the
    converted domain PipelineConfig.
    """
    if not isinstance(raw, dict):
        return ValidationResult(valid=False, errors=["Pipeline config must be a YAML or JSON object (dict)"])

    try:
        model = _PIPELINE_CONFIG_ADAPTER.validate_python(_inject_pipeline_kind(raw))
    except ValidationError as exc:
        return ValidationResult(valid=False, errors=_format_validation_errors(exc))

    return ValidationResult(valid=True, config=model.to_domain())


__all__ = [
    "PipelineConfigSchema",
    "PipelineOutputSchema",
    "PipelineStepSchema",
    "StepPipelineConfigSchema",
    "TemplatePipelineConfigSchema",
    "parse_pipeline_schema",
]
