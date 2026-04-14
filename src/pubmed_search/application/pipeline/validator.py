"""Pipeline semantic validator for pipeline configs.

Design philosophy: MCP server self-validates, self-corrects, only reports
to agent when truly unfixable. This validator is called automatically on
every load/save operation.

This module owns semantic auto-fix only:
- fuzzy alias/template matching
- dependency repair
- step ID repair
- output semantic correction

Raw schema parsing, type coercion, defaults, and pipeline mode discrimination
live in application.pipeline.schema.
"""

from __future__ import annotations

import hashlib
import logging
import re
from difflib import get_close_matches
from typing import Any

from pubmed_search.domain.entities.pipeline import (
    MAX_PIPELINE_STEPS,
    VALID_ACTIONS,
    VALID_TEMPLATES,
    FixSeverity,
    PipelineConfig,
    PipelineOutput,
    ValidationFix,
    ValidationResult,
)

from .schema import parse_pipeline_schema

logger = logging.getLogger(__name__)

# Fuzzy matching thresholds
_FUZZY_CUTOFF = 0.6

# Common misspellings / aliases for actions
_ACTION_ALIASES: dict[str, str] = {
    "find": "search",
    "lookup": "search",
    "query": "search",
    "fetch": "details",
    "get": "details",
    "enrich": "metrics",
    "citation": "citing",
    "cite": "citing",
    "cited": "citing",
    "ref": "references",
    "refs": "references",
    "reference": "references",
    "combine": "merge",
    "join": "merge",
    "union": "merge",
    "intersect": "merge",
    "similar": "related",
    "like": "related",
    "deduplicate": "filter",
    "dedup": "filter",
    "screen": "filter",
    "mesh": "expand",
    "expansion": "expand",
    "synonym": "expand",
}

# Common misspellings / aliases for templates
_TEMPLATE_ALIASES: dict[str, str] = {
    "clinical": "pico",
    "clinical_question": "pico",
    "full": "comprehensive",
    "complete": "comprehensive",
    "thorough": "comprehensive",
    "systematic": "comprehensive",
    "explore": "exploration",
    "seed": "exploration",
    "paper": "exploration",
    "gene": "gene_drug",
    "drug": "gene_drug",
    "compound": "gene_drug",
}


def compute_config_hash(config: PipelineConfig) -> str:
    """Compute a short hash of the pipeline config for change detection."""
    import json

    # Deterministic serialization for hashing
    data: dict[str, Any] = {
        "steps": [{"id": s.id, "action": s.action, "params": s.params, "inputs": s.inputs} for s in config.steps],
        "template": config.template,
        "template_params": config.template_params,
    }
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:8]


def validate_pipeline_name(name: str) -> tuple[str, list[ValidationFix]]:
    """Validate and normalize a pipeline name.

    Returns:
        (normalized_name, list_of_fixes)
    """
    fixes: list[ValidationFix] = []

    if not name:
        msg = "Pipeline name cannot be empty"
        raise ValueError(msg)

    original = name
    # Normalize: lowercase, replace spaces/dots with underscores
    name = name.strip().lower()
    name = re.sub(r"[\s.]+", "_", name)
    # Remove invalid characters
    name = re.sub(r"[^a-z0-9_-]", "", name)
    # Collapse multiple underscores/hyphens
    name = re.sub(r"[_-]{2,}", "_", name)
    # Trim to 64 chars
    name = name[:64]

    if not name:
        msg = f"Pipeline name '{original}' contains no valid characters after normalization"
        raise ValueError(msg)

    if name != original:
        fixes.append(
            ValidationFix(
                field="name",
                original=original,
                corrected=name,
                reason="Name normalized (lowercase, special chars removed)",
                severity=FixSeverity.INFO,
            )
        )

    return name, fixes


def _fuzzy_match_action(action: str) -> tuple[str, ValidationFix | None]:
    """Try to match an invalid action name to a valid one."""
    action_lower = action.lower().strip()

    # Direct alias
    if action_lower in _ACTION_ALIASES:
        matched = _ACTION_ALIASES[action_lower]
        return matched, ValidationFix(
            field="step.action",
            original=action,
            corrected=matched,
            reason=f"Action alias '{action}' resolved to '{matched}'",
            severity=FixSeverity.WARNING,
        )

    # Fuzzy match against valid actions
    matches = get_close_matches(action_lower, list(VALID_ACTIONS), n=1, cutoff=_FUZZY_CUTOFF)
    if matches:
        matched = matches[0]
        return matched, ValidationFix(
            field="step.action",
            original=action,
            corrected=matched,
            reason=f"Action '{action}' fuzzy-matched to '{matched}'",
            severity=FixSeverity.WARNING,
        )

    return action, None


def _fuzzy_match_template(template: str) -> tuple[str, ValidationFix | None]:
    """Try to match an invalid template name to a valid one."""
    template_lower = template.lower().strip()

    # Direct alias
    if template_lower in _TEMPLATE_ALIASES:
        matched = _TEMPLATE_ALIASES[template_lower]
        return matched, ValidationFix(
            field="template",
            original=template,
            corrected=matched,
            reason=f"Template alias '{template}' resolved to '{matched}'",
            severity=FixSeverity.WARNING,
        )

    # Fuzzy match against valid templates
    matches = get_close_matches(template_lower, list(VALID_TEMPLATES), n=1, cutoff=_FUZZY_CUTOFF)
    if matches:
        matched = matches[0]
        return matched, ValidationFix(
            field="template",
            original=template,
            corrected=matched,
            reason=f"Template '{template}' fuzzy-matched to '{matched}'",
            severity=FixSeverity.WARNING,
        )

    return template, None


def _validate_and_fix_output(config: PipelineConfig, fixes: list[ValidationFix]) -> None:
    """Apply semantic output auto-fixes shared by template and step pipelines."""
    output = config.output

    if output.format != "markdown":
        fixes.append(
            ValidationFix(
                field="output.format",
                original=output.format,
                corrected="markdown",
                reason=f"Legacy or invalid output format '{output.format}' is ignored; defaulting to 'markdown'",
                severity=FixSeverity.INFO,
            )
        )
        config.output = PipelineOutput(
            format="markdown",
            limit=config.output.limit,
            ranking=config.output.ranking,
        )

    valid_rankings = ("balanced", "impact", "recency", "quality")
    if config.output.ranking not in valid_rankings:
        close = get_close_matches(config.output.ranking, list(valid_rankings), n=1, cutoff=_FUZZY_CUTOFF)
        corrected_ranking = close[0] if close else "balanced"
        fixes.append(
            ValidationFix(
                field="output.ranking",
                original=config.output.ranking,
                corrected=corrected_ranking,
                reason=f"Invalid ranking '{config.output.ranking}', corrected to '{corrected_ranking}'",
                severity=FixSeverity.WARNING,
            )
        )
        config.output = PipelineOutput(
            format=config.output.format,
            limit=config.output.limit,
            ranking=corrected_ranking,  # type: ignore[arg-type]
        )

    if config.output.limit < 1:
        fixes.append(
            ValidationFix(
                field="output.limit",
                original=config.output.limit,
                corrected=20,
                reason="Output limit must be positive, defaulting to 20",
                severity=FixSeverity.INFO,
            )
        )
        config.output = PipelineOutput(
            format=config.output.format,
            limit=20,
            ranking=config.output.ranking,
        )


def validate_and_fix(config: PipelineConfig) -> ValidationResult:
    """Validate a PipelineConfig with aggressive auto-fix.

    This is the main entry point - called on every load/save.

    Returns:
        ValidationResult with corrected config (or errors if unfixable).
    """
    fixes: list[ValidationFix] = []
    errors: list[str] = []

    # ── Template validation ──────────────────────────────────────────────
    if config.template:
        if config.template not in VALID_TEMPLATES:
            corrected, fix = _fuzzy_match_template(config.template)
            if fix:
                config.template = corrected
                fixes.append(fix)
            else:
                errors.append(f"Unknown template '{config.template}'. Valid templates: {sorted(VALID_TEMPLATES)}")
                return ValidationResult(valid=False, fixes=fixes, errors=errors)

        _validate_and_fix_output(config, fixes)

        # Template-based configs don't need step validation
        return ValidationResult(valid=True, fixes=fixes, config=config)

    # ── Step-based validation ────────────────────────────────────────────
    if not config.steps:
        errors.append("Pipeline must have at least one step (or use a template)")
        return ValidationResult(valid=False, fixes=fixes, errors=errors)

    if len(config.steps) > MAX_PIPELINE_STEPS:
        errors.append(f"Pipeline has {len(config.steps)} steps, maximum is {MAX_PIPELINE_STEPS}")
        return ValidationResult(valid=False, fixes=fixes, errors=errors)

    # ── Auto-generate missing step IDs ───────────────────────────────────
    seen_ids: set[str] = set()
    for i, step in enumerate(config.steps):
        if not step.id:
            generated_id = f"step_{i + 1}"
            # Avoid collision
            while generated_id in seen_ids:
                generated_id = f"step_{i + 1}_{id(step) % 1000}"
            fixes.append(
                ValidationFix(
                    field=f"steps[{i}].id",
                    original="",
                    corrected=generated_id,
                    reason="Missing step ID auto-generated",
                    severity=FixSeverity.WARNING,
                )
            )
            step.id = generated_id
        seen_ids.add(step.id)

    # ── Deduplicate step IDs ─────────────────────────────────────────────
    id_counts: dict[str, int] = {}
    for step in config.steps:
        id_counts[step.id] = id_counts.get(step.id, 0) + 1

    if any(c > 1 for c in id_counts.values()):
        seen_ids_dedup: set[str] = set()
        for step in config.steps:
            if step.id in seen_ids_dedup:
                original_id = step.id
                counter = 2
                new_id = f"{step.id}_{counter}"
                while new_id in seen_ids_dedup:
                    counter += 1
                    new_id = f"{step.id}_{counter}"
                fixes.append(
                    ValidationFix(
                        field="step.id",
                        original=original_id,
                        corrected=new_id,
                        reason=f"Duplicate step ID '{original_id}' renamed to '{new_id}'",
                        severity=FixSeverity.WARNING,
                    )
                )
                step.id = new_id
            seen_ids_dedup.add(step.id)

    # ── Validate + fix actions ───────────────────────────────────────────
    for i, step in enumerate(config.steps):
        if step.action not in VALID_ACTIONS:
            corrected, fix = _fuzzy_match_action(step.action)
            if fix:
                step.action = corrected
                fix.field = f"steps[{i}].action"
                fixes.append(fix)
            else:
                errors.append(f"Step '{step.id}': unknown action '{step.action}'. Valid: {sorted(VALID_ACTIONS)}")

    # ── Validate + repair dependencies ───────────────────────────────────
    valid_step_ids = {s.id for s in config.steps}
    for i, step in enumerate(config.steps):
        # Steps can only reference earlier steps
        earlier_ids = {config.steps[j].id for j in range(i)}
        repaired_inputs: list[str] = []
        for inp in step.inputs:
            if inp in earlier_ids:
                repaired_inputs.append(inp)
            elif inp in valid_step_ids:
                # Reference to a later step - can't auto-fix ordering easily
                # but we can warn and remove the circular dep
                fixes.append(
                    ValidationFix(
                        field=f"steps[{i}].inputs",
                        original=inp,
                        corrected="(removed)",
                        reason=f"Step '{step.id}' references later step '{inp}' (would create cycle). Removed.",
                        severity=FixSeverity.WARNING,
                    )
                )
            else:
                # Fuzzy match against valid step ids
                close = get_close_matches(inp, list(valid_step_ids), n=1, cutoff=_FUZZY_CUTOFF)
                if close and close[0] in earlier_ids:
                    fixes.append(
                        ValidationFix(
                            field=f"steps[{i}].inputs",
                            original=inp,
                            corrected=close[0],
                            reason=f"Step '{step.id}' input '{inp}' fuzzy-matched to '{close[0]}'",
                            severity=FixSeverity.WARNING,
                        )
                    )
                    repaired_inputs.append(close[0])
                else:
                    fixes.append(
                        ValidationFix(
                            field=f"steps[{i}].inputs",
                            original=inp,
                            corrected="(removed)",
                            reason=f"Step '{step.id}' references unknown step '{inp}'. Removed.",
                            severity=FixSeverity.WARNING,
                        )
                    )
        step.inputs = repaired_inputs

    # ── Validate on_error field ──────────────────────────────────────────
    for i, step in enumerate(config.steps):
        if step.on_error not in ("skip", "abort"):
            fixes.append(
                ValidationFix(
                    field=f"steps[{i}].on_error",
                    original=step.on_error,
                    corrected="skip",
                    reason=f"Invalid on_error value '{step.on_error}', defaulting to 'skip'",
                    severity=FixSeverity.INFO,
                )
            )
            object.__setattr__(step, "on_error", "skip")

    # ── Validate output config ───────────────────────────────────────────
    _validate_and_fix_output(config, fixes)

    # ── Final decision ───────────────────────────────────────────────────
    has_unfixable = len(errors) > 0
    if has_unfixable:
        return ValidationResult(valid=False, fixes=fixes, errors=errors)

    return ValidationResult(valid=True, fixes=fixes, config=config)


def parse_and_validate_config(raw: dict[str, Any]) -> ValidationResult:
    """Parse a raw dict (from YAML/JSON) into a validated PipelineConfig.

    This is the full pipeline: raw dict -> Pydantic schema parse -> semantic auto-fix.
    Called by PipelineStore on load/save.
    """
    schema_result = parse_pipeline_schema(raw)
    if not schema_result.valid:
        return schema_result

    config = schema_result.config
    if config is None:
        return ValidationResult(valid=False, fixes=schema_result.fixes, errors=["Failed to parse pipeline config"])

    result = validate_and_fix(config)
    result.fixes = schema_result.fixes + result.fixes
    return result
