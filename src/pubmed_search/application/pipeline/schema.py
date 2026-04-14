"""Pydantic schema parsing for pipeline configs.

This module owns structural parsing concerns only:
- raw mapping validation
- type coercion
- shape normalization
- mode discrimination (template vs step pipeline)
- default values

Semantic repair remains in validator.py.

Maintenance:
    Keep schema-level coercion and defaulting here, but move semantic recovery
    or execution behavior into validator.py and executor modules. This boundary
    is important because tools rely on deterministic parse-time fixes.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, cast

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from pubmed_search.domain.entities.pipeline import (
    MAX_PIPELINE_STEPS,
    FixSeverity,
    PipelineConfig,
    PipelineOutput,
    PipelineStep,
    ValidationFix,
    ValidationResult,
)


def _record_fix(info: ValidationInfo, fix: ValidationFix) -> None:
    """Append schema-level coercion fixes to the validation context when present."""
    context = info.context
    if not isinstance(context, dict):
        return
    fixes = context.get("fixes")
    if isinstance(fixes, list):
        fixes.append(fix)


class _PipelineSchemaModel(BaseModel):
    """Shared Pydantic settings for pipeline schema models."""

    model_config = ConfigDict(extra="ignore")


class PipelineStepSchema(_PipelineSchemaModel):
    """Schema model for one pipeline step."""

    id: str = ""
    action: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    inputs: list[str] = Field(default_factory=list)
    on_error: str = "skip"

    @field_validator("id", "action", mode="before")
    @classmethod
    def _coerce_text_fields(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value)

    @field_validator("params", mode="before")
    @classmethod
    def _coerce_params(cls, value: Any, info: ValidationInfo) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        _record_fix(
            info,
            ValidationFix(
                field="steps.params",
                original=value,
                corrected={},
                reason="params must be a dict, replaced with empty dict",
                severity=FixSeverity.WARNING,
            ),
        )
        return {}

    @field_validator("inputs", mode="before")
    @classmethod
    def _coerce_inputs(cls, value: Any, info: ValidationInfo) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            wrapped = [value]
            _record_fix(
                info,
                ValidationFix(
                    field="steps.inputs",
                    original=value,
                    corrected=wrapped,
                    reason="inputs should be a list, wrapped single string",
                    severity=FixSeverity.INFO,
                ),
            )
            return wrapped
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    @field_validator("on_error", mode="before")
    @classmethod
    def _coerce_on_error(cls, value: Any, info: ValidationInfo) -> str:
        if value is None:
            return "skip"
        normalized = str(value)
        if normalized not in {"skip", "abort"}:
            _record_fix(
                info,
                ValidationFix(
                    field="steps.on_error",
                    original=normalized,
                    corrected="skip",
                    reason=f"Invalid on_error value '{normalized}', defaulting to 'skip'",
                    severity=FixSeverity.INFO,
                ),
            )
            return "skip"
        return normalized

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

    format: str = "markdown"
    limit: int = 20
    ranking: str = "balanced"

    @field_validator("format", "ranking", mode="before")
    @classmethod
    def _coerce_output_text(cls, value: Any, info: ValidationInfo) -> str:
        del info
        if value is None:
            return ""
        return str(value)

    @field_validator("limit", mode="before")
    @classmethod
    def _coerce_limit(cls, value: Any, info: ValidationInfo) -> int:
        del info
        if value is None or value == "":
            return 20
        return int(value)

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
    output: PipelineOutputSchema = Field(
        default_factory=PipelineOutputSchema,
        validation_alias=AliasChoices("output", "execution"),
    )

    @field_validator("name", mode="before")
    @classmethod
    def _coerce_name(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value)

    @field_validator("output", mode="before")
    @classmethod
    def _coerce_output(cls, value: Any) -> dict[str, Any]:
        if value is None or not isinstance(value, dict):
            return {}
        return cast("dict[str, Any]", value)


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
        )


class TemplatePipelineConfigSchema(_PipelineConfigBaseSchema):
    """Schema for template-based pipelines."""

    kind: Literal["template"] = "template"
    template: str
    template_params: dict[str, Any] = Field(default_factory=dict, validation_alias=AliasChoices("template_params", "params"))

    @field_validator("template", mode="before")
    @classmethod
    def _coerce_template(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value)

    @field_validator("template_params", mode="before")
    @classmethod
    def _coerce_template_params(cls, value: Any, info: ValidationInfo) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        _record_fix(
            info,
            ValidationFix(
                field="template_params",
                original=value,
                corrected={},
                reason="template_params must be a dict, replaced with empty dict",
                severity=FixSeverity.WARNING,
            ),
        )
        return {}

    def to_domain(self) -> PipelineConfig:
        """Convert schema model into the existing domain dataclass."""
        return PipelineConfig(
            name=self.name,
            output=self.output.to_domain(),
            template=self.template,
            template_params=self.template_params,
        )


PipelineConfigSchema = Annotated[
    StepPipelineConfigSchema | TemplatePipelineConfigSchema,
    Field(discriminator="kind"),
]

_PIPELINE_CONFIG_ADAPTER: TypeAdapter[PipelineConfigSchema] = TypeAdapter(PipelineConfigSchema)


def _inject_pipeline_kind(raw: dict[str, Any]) -> dict[str, Any]:
    """Infer the config variant for the discriminated union without changing public schema."""
    normalized = dict(raw)
    template = normalized.get("template")
    if template is not None and str(template).strip():
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

    Returns a ValidationResult carrying only schema-level fixes/errors and the
    converted domain PipelineConfig.
    """
    fixes: list[ValidationFix] = []
    if not isinstance(raw, dict):
        return ValidationResult(valid=False, errors=["Pipeline config must be a YAML or JSON object (dict)"])

    try:
        model = _PIPELINE_CONFIG_ADAPTER.validate_python(_inject_pipeline_kind(raw), context={"fixes": fixes})
    except ValidationError as exc:
        return ValidationResult(valid=False, fixes=fixes, errors=_format_validation_errors(exc))

    return ValidationResult(valid=True, fixes=fixes, config=model.to_domain())


__all__ = [
    "PipelineConfigSchema",
    "PipelineOutputSchema",
    "PipelineStepSchema",
    "StepPipelineConfigSchema",
    "TemplatePipelineConfigSchema",
    "parse_pipeline_schema",
]
