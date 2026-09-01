"""Pipeline semantic validator for pipeline configs.

This validator is called automatically on every load/save operation. Public
identifiers and enum-like values are schema-exact: unknown values fail closed
instead of being guessed or rewritten.

This module owns fail-closed semantic validation:
- canonical action, template, step, and dependency validation
- action/output budget enforcement

Raw schema parsing, type coercion, defaults, and pipeline mode discrimination
live in application.pipeline.schema.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from pubmed_search.application.pipeline.action_contracts import (
    is_pipeline_variable_reference,
    validate_pipeline_globals,
    validate_pipeline_step_action_contract,
)
from pubmed_search.application.pipeline.budgets import (
    PIPELINE_ACTION_LIMITS,
    PIPELINE_OUTPUT_LIMIT,
    action_limit,
)
from pubmed_search.domain.entities.pipeline import (
    MAX_PIPELINE_STEPS,
    VALID_ACTIONS,
    VALID_TEMPLATES,
    PipelineConfig,
    ValidationResult,
)

from .schema import parse_pipeline_schema
from .template_contracts import validate_pipeline_template_params

logger = logging.getLogger(__name__)


def compute_config_hash(config: PipelineConfig) -> str:
    """Compute a short hash of the pipeline config for change detection."""
    import json

    # Deterministic serialization for hashing
    data: dict[str, Any] = {
        "steps": [{"id": s.id, "action": s.action, "params": s.params, "inputs": s.inputs} for s in config.steps],
        "globals": config.globals,
        "variables": config.variables,
        "template": config.template,
        "template_params": config.template_params,
    }
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:8]


PIPELINE_NAME_PATTERN = r"^[a-z0-9](?:[a-z0-9_-]{0,63})$"
PIPELINE_TAG_PATTERN = r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,63})$"
MAX_PIPELINE_TAGS = 20

_PIPELINE_NAME_RE = re.compile(PIPELINE_NAME_PATTERN)
_PIPELINE_TAG_RE = re.compile(PIPELINE_TAG_PATTERN)


def validate_pipeline_name(name: str) -> str:
    """Validate one canonical pipeline name without rewriting caller intent.

    Distinct caller inputs must never collapse onto the same persisted key:
    ``save_pipeline`` has upsert semantics, so silent case folding or character
    removal could overwrite an unrelated pipeline.
    """
    if not isinstance(name, str) or _PIPELINE_NAME_RE.fullmatch(name) is None:
        msg = (
            f"Pipeline name must match {PIPELINE_NAME_PATTERN}: 1-64 lowercase letters, digits, underscores, or hyphens"
        )
        raise ValueError(msg)
    return name


def validate_pipeline_tags(tags: object | None) -> list[str]:
    """Validate a bounded JSON-array tag contract without CSV coercion."""
    if tags is None:
        return []
    if not isinstance(tags, list):
        msg = "Pipeline tags must be a JSON array of canonical tag strings"
        raise TypeError(msg)
    if len(tags) > MAX_PIPELINE_TAGS:
        msg = f"Pipeline tags may contain at most {MAX_PIPELINE_TAGS} items"
        raise ValueError(msg)

    validated: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        if not isinstance(tag, str) or _PIPELINE_TAG_RE.fullmatch(tag) is None:
            msg = (
                "Each pipeline tag must contain 1-64 letters, digits, dots, underscores, or hyphens "
                "and start with a letter or digit"
            )
            raise ValueError(msg)
        folded = tag.casefold()
        if folded in seen:
            msg = f"Duplicate pipeline tag: {tag}"
            raise ValueError(msg)
        seen.add(folded)
        validated.append(tag)
    return validated


def _validate_output(config: PipelineConfig, errors: list[str]) -> None:
    """Validate output enums and budgets without rewriting caller input."""
    output = config.output

    valid_formats = {"markdown", "json"}
    if output.format not in valid_formats:
        errors.append(f"Unknown output format '{output.format}'. Valid formats: {sorted(valid_formats)}")

    valid_rankings = ("balanced", "impact", "recency", "quality")
    if config.output.ranking not in valid_rankings:
        errors.append(f"Unknown output ranking '{config.output.ranking}'. Valid rankings: {list(valid_rankings)}")

    if isinstance(config.output.limit, bool) or not isinstance(config.output.limit, int):
        errors.append("Pipeline output limit must be an integer")
    elif not PIPELINE_OUTPUT_LIMIT.minimum <= config.output.limit <= PIPELINE_OUTPUT_LIMIT.maximum:
        errors.append(
            f"Pipeline output limit must be between {PIPELINE_OUTPUT_LIMIT.minimum} and {PIPELINE_OUTPUT_LIMIT.maximum}"
        )


def validate_pipeline_config(config: PipelineConfig) -> ValidationResult:
    """Validate a PipelineConfig without changing caller-provided values.

    This is the main entry point - called on every load/save.

    Returns:
        ValidationResult containing the original config when valid.
    """
    errors: list[str] = []

    # A configured name is persistent identity, not display text. Keep the
    # application boundary aligned with the MCP and store contracts so a YAML
    # config cannot re-introduce the collisions those boundaries reject.
    if config.name:
        try:
            validate_pipeline_name(config.name)
        except ValueError as exc:
            errors.append(str(exc))
            return ValidationResult(valid=False, errors=errors)

    # ── Template validation ──────────────────────────────────────────────
    if config.template:
        if config.template not in VALID_TEMPLATES:
            errors.append(f"Unknown template '{config.template}'. Valid templates: {sorted(VALID_TEMPLATES)}")
            return ValidationResult(valid=False, errors=errors)

        try:
            validate_pipeline_template_params(config.template, config.template_params)
        except ValueError as exc:
            errors.append(str(exc))
            return ValidationResult(valid=False, errors=errors)

        _validate_output(config, errors)
        if errors:
            return ValidationResult(valid=False, errors=errors)

        # Template-based configs don't need step validation
        return ValidationResult(valid=True, config=config)

    # ── Step-based validation ────────────────────────────────────────────
    if not config.steps:
        errors.append("Pipeline must have at least one step (or use a template)")
        return ValidationResult(valid=False, errors=errors)

    if len(config.steps) > MAX_PIPELINE_STEPS:
        errors.append(f"Pipeline has {len(config.steps)} steps, maximum is {MAX_PIPELINE_STEPS}")
        return ValidationResult(valid=False, errors=errors)

    # ── Validate step IDs ─────────────────────────────────────────────────
    seen_ids: set[str] = set()
    for step in config.steps:
        if not step.id:
            errors.append("Every pipeline step must have a non-empty id")
            continue
        if step.id in seen_ids:
            errors.append(f"Duplicate step id '{step.id}'")
            continue
        seen_ids.add(step.id)

    # ── Validate actions ──────────────────────────────────────────────────
    for step in config.steps:
        if step.action not in VALID_ACTIONS:
            errors.append(f"Step '{step.id}': unknown action '{step.action}'. Valid: {sorted(VALID_ACTIONS)}")

    # ── Reject malformed action-specific params and globals ─────────────
    try:
        validate_pipeline_globals(config)
    except ValueError as exc:
        errors.append(str(exc))

    for step in config.steps:
        try:
            validate_pipeline_step_action_contract(
                step,
                global_params=config.globals,
                allow_variable_references=True,
            )
        except (TypeError, ValueError) as exc:
            errors.append(f"Step '{step.id}': {exc}")

    # ── Enforce the same action budgets used by templates and executor ──
    for step in config.steps:
        if (
            step.action not in PIPELINE_ACTION_LIMITS
            or "limit" not in step.params
            or is_pipeline_variable_reference(step.params["limit"])
        ):
            continue
        try:
            action_limit(step.action, step.params["limit"])
        except ValueError as exc:
            errors.append(f"Step '{step.id}': {exc}")

    # ── Validate dependencies ─────────────────────────────────────────────
    valid_step_ids = {s.id for s in config.steps}
    for i, step in enumerate(config.steps):
        # Steps can only reference earlier steps
        earlier_ids = {config.steps[j].id for j in range(i)}
        for inp in step.inputs:
            if inp in earlier_ids:
                continue
            if inp in valid_step_ids:
                errors.append(f"Step '{step.id}' references later step '{inp}'. Inputs must reference earlier steps.")
            else:
                errors.append(f"Step '{step.id}' references unknown step '{inp}'")

    # ── Validate on_error field ──────────────────────────────────────────
    for step in config.steps:
        if step.on_error not in ("skip", "abort"):
            errors.append(
                f"Step '{step.id}': unknown on_error value '{step.on_error}'. Valid values: ['abort', 'skip']"
            )

    # ── Validate output config ───────────────────────────────────────────
    _validate_output(config, errors)

    # ── Final decision ───────────────────────────────────────────────────
    if errors:
        return ValidationResult(valid=False, errors=errors)

    return ValidationResult(valid=True, config=config)


def parse_and_validate_config(raw: dict[str, Any]) -> ValidationResult:
    """Parse a raw dict (from YAML/JSON) into a validated PipelineConfig.

    This is the full pipeline: raw dict -> Pydantic schema parse -> semantic validation.
    Called by PipelineStore on load/save.
    """
    schema_result = parse_pipeline_schema(raw)
    if not schema_result.valid:
        return schema_result

    config = schema_result.config
    if config is None:
        return ValidationResult(valid=False, errors=["Failed to parse pipeline config"])

    return validate_pipeline_config(config)
