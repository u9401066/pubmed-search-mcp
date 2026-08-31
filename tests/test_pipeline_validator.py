"""Tests for schema-exact, fail-closed pipeline validation.

Coverage targets:
- Canonical action and template validation
- Exact step and dependency identifiers
- on_error/output enum and limit validation
- parse_and_validate_config (raw dict → validated PipelineConfig)
- config hash computation
- Pipeline name validation
- Edge cases and invalid configurations
"""

from __future__ import annotations

import pytest

from pubmed_search.application.pipeline import (
    PipelineConfig,
    PipelineOutput,
    PipelineStep,
)
from pubmed_search.application.pipeline.validator import (
    MAX_PIPELINE_TAGS,
    compute_config_hash,
    parse_and_validate_config,
    validate_pipeline_config,
    validate_pipeline_name,
    validate_pipeline_tags,
)

# =========================================================================
# Pipeline Name Validation
# =========================================================================


class TestValidatePipelineName:
    """Tests for validate_pipeline_name()."""

    def test_simple_valid_name(self):
        name = validate_pipeline_name("my_pipeline")
        assert name == "my_pipeline"

    @pytest.mark.parametrize(
        "value",
        ["My Pipeline", "my.pipeline@v2!", "my  cool  pipeline", "a" * 65, "  hello  ", "a/b"],
    )
    def test_noncanonical_names_are_rejected_without_rewriting(self, value):
        with pytest.raises(ValueError, match="must match"):
            validate_pipeline_name(value)

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="must match"):
            validate_pipeline_name("")

    def test_all_invalid_chars_raises(self):
        with pytest.raises(ValueError, match="must match"):
            validate_pipeline_name("!@#$%")

    def test_hyphens_preserved(self):
        name = validate_pipeline_name("my-pipeline")
        assert name == "my-pipeline"

    def test_distinct_canonical_names_remain_distinct(self):
        first = validate_pipeline_name("a_b")
        second = validate_pipeline_name("a__b")
        assert first != second

    def test_pipeline_tags_are_a_bounded_array(self):
        assert validate_pipeline_tags(["anesthesia", "ICU-care"]) == ["anesthesia", "ICU-care"]
        with pytest.raises(TypeError, match="JSON array"):
            validate_pipeline_tags("anesthesia,ICU")
        with pytest.raises(ValueError, match="at most"):
            validate_pipeline_tags([f"tag-{index}" for index in range(MAX_PIPELINE_TAGS + 1)])
        with pytest.raises(ValueError, match="Duplicate"):
            validate_pipeline_tags(["ICU", "icu"])


# =========================================================================
# Config Hash
# =========================================================================


class TestComputeConfigHash:
    """Tests for compute_config_hash()."""

    def test_deterministic(self):
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search", params={"query": "test"})],
        )
        h1 = compute_config_hash(config)
        h2 = compute_config_hash(config)
        assert h1 == h2

    def test_hash_length_8(self):
        config = PipelineConfig(template="pico")
        h = compute_config_hash(config)
        assert len(h) == 8

    def test_different_configs_different_hashes(self):
        c1 = PipelineConfig(template="pico")
        c2 = PipelineConfig(template="comprehensive")
        assert compute_config_hash(c1) != compute_config_hash(c2)


# =========================================================================
# validate_pipeline_config — Template Path
# =========================================================================


class TestValidateAndFixTemplate:
    """Tests for validate_pipeline_config() with template-based configs."""

    def test_valid_template(self):
        config = PipelineConfig(template="pico", template_params={"P": "ICU", "I": "remimazolam"})
        result = validate_pipeline_config(config)
        assert result.valid is True
        assert not result.has_errors

    def test_template_alias_is_rejected(self):
        config = PipelineConfig(template="clinical")
        result = validate_pipeline_config(config)
        assert result.valid is False
        assert "Unknown template" in result.errors[0]

    def test_unknown_template_error(self):
        config = PipelineConfig(template="zzz_unknown_template_zzz")
        result = validate_pipeline_config(config)
        assert result.valid is False
        assert result.has_errors
        assert "Unknown template" in result.errors[0]

    def test_template_output_unknown_values_fail_closed(self):
        config = PipelineConfig(
            template="pico",
            template_params={"P": "ICU", "I": "remimazolam"},
            output=PipelineOutput(format="xml", limit=0, ranking="impac"),
        )

        result = validate_pipeline_config(config)

        assert result.valid is False
        assert config.output.format == "xml"
        assert config.output.limit == 0
        assert config.output.ranking == "impac"
        assert any("Unknown output format" in error for error in result.errors)
        assert any("Unknown output ranking" in error for error in result.errors)
        assert any("output limit" in error.lower() for error in result.errors)


# =========================================================================
# validate_pipeline_config — Step Path
# =========================================================================


class TestValidateAndFixSteps:
    """Tests for validate_pipeline_config() with step-based configs."""

    def test_valid_steps(self):
        config = PipelineConfig(
            steps=[
                PipelineStep(id="s1", action="search", params={"query": "test"}),
                PipelineStep(id="s2", action="details", inputs=["s1"]),
            ]
        )
        result = validate_pipeline_config(config)
        assert result.valid is True

    def test_empty_steps_error(self):
        config = PipelineConfig(steps=[])
        result = validate_pipeline_config(config)
        assert result.valid is False
        assert "at least one step" in result.errors[0]

    def test_too_many_steps_error(self):
        steps = [PipelineStep(id=f"s{i}", action="search") for i in range(25)]
        config = PipelineConfig(steps=steps)
        result = validate_pipeline_config(config)
        assert result.valid is False
        assert "maximum" in result.errors[0]

    def test_missing_ids_fail_closed(self):
        config = PipelineConfig(
            steps=[
                PipelineStep(id="", action="search"),
                PipelineStep(id="", action="details"),
            ]
        )
        result = validate_pipeline_config(config)
        assert result.valid is False
        assert config.steps[0].id == ""
        assert config.steps[1].id == ""
        assert any("non-empty id" in error for error in result.errors)

    def test_duplicate_step_ids_fail_closed(self):
        config = PipelineConfig(
            steps=[
                PipelineStep(id="search", action="search"),
                PipelineStep(id="search", action="details"),
            ]
        )
        result = validate_pipeline_config(config)
        assert result.valid is False
        assert [step.id for step in config.steps] == ["search", "search"]
        assert any("Duplicate step id" in error for error in result.errors)

    def test_action_alias_is_rejected(self):
        config = PipelineConfig(steps=[PipelineStep(id="s1", action="find")])
        result = validate_pipeline_config(config)
        assert result.valid is False
        assert config.steps[0].action == "find"
        assert any("unknown action" in error.lower() for error in result.errors)

    def test_unknown_action_error(self):
        config = PipelineConfig(steps=[PipelineStep(id="s1", action="zzz_invalid_zzz")])
        result = validate_pipeline_config(config)
        assert result.valid is False
        assert any("unknown action" in e.lower() for e in result.errors)

    def test_details_requires_a_real_pmid_array(self):
        config = PipelineConfig(steps=[PipelineStep(id="details", action="details", params={"pmids": "33475315"})])

        result = validate_pipeline_config(config)

        assert result.valid is False
        assert any("Invalid details params" in error and "valid list" in error for error in result.errors)


# =========================================================================
# validate_pipeline_config — Dependency Repair
# =========================================================================


class TestValidateAndFixDependencies:
    """Tests for exact, fail-closed dependency validation."""

    def test_valid_dependencies(self):
        config = PipelineConfig(
            steps=[
                PipelineStep(id="s1", action="search"),
                PipelineStep(id="s2", action="details", inputs=["s1"]),
            ]
        )
        result = validate_pipeline_config(config)
        assert result.valid is True
        assert config.steps[1].inputs == ["s1"]

    def test_forward_reference_fails_closed(self):
        config = PipelineConfig(
            steps=[
                PipelineStep(id="s1", action="search", inputs=["s2"]),
                PipelineStep(id="s2", action="details"),
            ]
        )
        result = validate_pipeline_config(config)
        assert result.valid is False
        assert config.steps[0].inputs == ["s2"]
        assert any("references later step" in error for error in result.errors)

    def test_unknown_reference_fails_closed(self):
        config = PipelineConfig(
            steps=[
                PipelineStep(id="s1", action="search"),
                PipelineStep(id="s2", action="details", inputs=["nonexistent"]),
            ]
        )
        result = validate_pipeline_config(config)
        assert result.valid is False
        assert config.steps[1].inputs == ["nonexistent"]
        assert any("references unknown step" in error for error in result.errors)

    def test_close_dependency_name_is_not_guessed(self):
        config = PipelineConfig(
            steps=[
                PipelineStep(id="search_step", action="search"),
                PipelineStep(id="details_step", action="details", inputs=["search_ste"]),
            ]
        )
        result = validate_pipeline_config(config)
        assert result.valid is False
        assert config.steps[1].inputs == ["search_ste"]
        assert any("references unknown step" in error for error in result.errors)


# =========================================================================
# validate_pipeline_config — on_error / output
# =========================================================================


class TestValidateAndFixOutputOnError:
    """Tests for on_error and output validation."""

    def test_invalid_on_error_fails_closed(self):
        config = PipelineConfig(steps=[PipelineStep(id="s1", action="search", on_error="continue")])
        result = validate_pipeline_config(config)
        assert result.valid is False
        assert config.steps[0].on_error == "continue"
        assert any("unknown on_error" in error for error in result.errors)

    def test_valid_on_error_abort(self):
        config = PipelineConfig(steps=[PipelineStep(id="s1", action="search", on_error="abort")])
        result = validate_pipeline_config(config)
        assert result.valid is True
        assert config.steps[0].on_error == "abort"

    def test_unknown_output_format_is_rejected(self):
        result = parse_and_validate_config(
            {
                "steps": [{"id": "s1", "action": "search"}],
                "output": {"format": "xml"},
            }
        )
        assert result.valid is False
        assert result.config is None
        assert any("output.format" in error for error in result.errors)

    def test_close_ranking_is_not_guessed(self):
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search")],
            output=PipelineOutput(ranking="impac"),  # close to "impact"
        )
        result = validate_pipeline_config(config)
        assert result.valid is False
        assert config.output.ranking == "impac"

    def test_unknown_ranking_fails_closed(self):
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search")],
            output=PipelineOutput(ranking="zzz_unknown"),
        )
        result = validate_pipeline_config(config)
        assert result.valid is False
        assert config.output.ranking == "zzz_unknown"

    def test_nonpositive_limit_is_rejected_without_rewrite(self):
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search")],
            output=PipelineOutput(limit=0),
        )
        result = validate_pipeline_config(config)
        assert result.valid is False
        assert config.output.limit == 0
        assert any("output limit" in error.lower() for error in result.errors)

    def test_valid_output_passes(self):
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search")],
            output=PipelineOutput(limit=50, ranking="recency"),
        )
        result = validate_pipeline_config(config)
        assert result.valid is True


# =========================================================================
# parse_and_validate_config — Raw Dict Parsing
# =========================================================================


class TestParseAndValidateConfig:
    """Tests for parse_and_validate_config() (dict → PipelineConfig)."""

    def test_simple_template(self):
        raw = {"template": "pico", "template_params": {"P": "ICU", "I": "remimazolam"}}
        result = parse_and_validate_config(raw)
        assert result.valid is True
        assert result.config is not None
        assert result.config.template == "pico"

    def test_noncanonical_config_name_is_rejected_without_rewriting(self):
        raw = {
            "name": "My Pipeline",
            "steps": [{"id": "s1", "action": "search", "params": {"query": "test"}}],
        }
        result = parse_and_validate_config(raw)

        assert result.valid is False
        assert result.config is None
        assert any("must match" in error for error in result.errors)

    def test_simple_steps(self):
        raw = {
            "steps": [
                {"id": "s1", "action": "search", "params": {"query": "test"}},
                {"id": "s2", "action": "details", "inputs": ["s1"]},
            ]
        }
        result = parse_and_validate_config(raw)
        assert result.valid is True
        assert result.config is not None
        assert len(result.config.steps) == 2

    def test_inputs_string_rejected(self):
        raw = {
            "steps": [
                {"id": "s1", "action": "search"},
                {"id": "s2", "action": "details", "inputs": "s1"},
            ]
        }
        result = parse_and_validate_config(raw)
        assert result.valid is False
        assert result.config is None
        assert any("inputs" in error and "valid list" in error for error in result.errors)

    def test_params_non_dict_rejected(self):
        raw = {
            "steps": [
                {"id": "s1", "action": "search", "params": "invalid"},
            ]
        }
        result = parse_and_validate_config(raw)
        assert result.valid is False
        assert result.config is None
        assert any("params" in error and "valid dictionary" in error for error in result.errors)

    def test_output_parsing(self):
        raw = {
            "steps": [{"id": "s1", "action": "search"}],
            "output": {"format": "json", "limit": 50, "ranking": "impact"},
        }
        result = parse_and_validate_config(raw)
        assert result.valid is True
        assert result.config.output.format == "json"
        assert result.config.output.limit == 50
        assert result.config.output.ranking == "impact"

    def test_output_defaults(self):
        raw = {"steps": [{"id": "s1", "action": "search"}]}
        result = parse_and_validate_config(raw)
        assert result.valid is True
        assert result.config.output.limit == 20
        assert result.config.output.ranking == "balanced"

    def test_step_not_dict_error(self):
        raw = {"steps": ["not_a_dict"]}
        result = parse_and_validate_config(raw)
        # The step is skipped, so we end up with no steps → error
        assert result.valid is False

    def test_missing_action(self):
        """Missing action should be empty string, then caught by validator."""
        raw = {"steps": [{"id": "s1"}]}  # no action
        result = parse_and_validate_config(raw)
        # Action '' is not in VALID_ACTIONS → error
        assert result.valid is False

    def test_on_error_invalid_in_raw(self):
        raw = {
            "steps": [{"id": "s1", "action": "search", "on_error": "retry"}],
        }
        result = parse_and_validate_config(raw)
        assert result.valid is False
        assert result.config is None
        assert any("on_error" in error for error in result.errors)

    def test_non_dict_output_rejected(self):
        raw = {
            "steps": [{"id": "s1", "action": "search"}],
            "output": "not_a_dict",
        }
        result = parse_and_validate_config(raw)
        assert result.valid is False
        assert result.config is None
        assert any("output" in error and "valid dictionary" in error for error in result.errors)

    def test_retired_execution_key_is_rejected(self):
        raw = {
            "steps": [{"id": "s1", "action": "search"}],
            "execution": {"limit": 15, "ranking": "quality"},
        }
        result = parse_and_validate_config(raw)
        assert result.valid is False
        assert result.config is None
        assert any("execution" in error and "Extra inputs" in error for error in result.errors)

    def test_action_alias_fails_closed_through_parse(self):
        raw = {"steps": [{"id": "s1", "action": "find"}]}
        result = parse_and_validate_config(raw)
        assert result.valid is False
        assert result.config is None
        assert any("unknown action" in error.lower() for error in result.errors)

    def test_template_alias_fails_closed_through_parse(self):
        raw = {"template": "clinical"}
        result = parse_and_validate_config(raw)
        assert result.valid is False
        assert result.config is None
        assert any("Unknown template" in error for error in result.errors)

    def test_template_unknown_values_fail_closed_through_parse(self):
        raw = {
            "template": "clinical",
            "output": {"format": "xml", "limit": 0, "ranking": "impac"},
        }

        result = parse_and_validate_config(raw)

        assert result.valid is False
        assert result.config is None
        assert any("template" in error.lower() or "output" in error.lower() for error in result.errors)

    def test_schema_error_precedes_unknown_action_validation(self):
        raw = {
            "steps": [
                {"id": "s1", "action": "find", "params": "invalid"},
            ]
        }
        result = parse_and_validate_config(raw)

        assert result.valid is False
        assert result.config is None
        assert any("params" in error and "valid dictionary" in error for error in result.errors)


# =========================================================================
# ValidationResult summary
# =========================================================================


class TestValidationResultSummary:
    """Tests for ValidationResult.summary() output."""

    def test_valid_summary(self):
        config = PipelineConfig(template="pico", template_params={"P": "ICU", "I": "drug"})
        result = validate_pipeline_config(config)
        summary = result.summary()
        assert "valid" in summary.lower() or "✅" in summary

    def test_invalid_limit_summary_shows_validation_error(self):
        config = PipelineConfig(
            template="pico",
            template_params={"P": "ICU", "I": "remimazolam"},
            output=PipelineOutput(limit=0),
        )
        result = validate_pipeline_config(config)
        summary = result.summary()
        assert "Validation error" in summary
        assert "output limit" in summary.lower()

    def test_with_errors_shows_details(self):
        config = PipelineConfig(template="zzz_unknown_zzz")
        result = validate_pipeline_config(config)
        summary = result.summary()
        assert "❌" in summary
        assert "Validation" in summary


# =========================================================================
# Edge Cases
# =========================================================================


class TestValidatorEdgeCases:
    """Edge cases and combined scenarios."""

    def test_unknown_template_is_not_masked_by_invalid_limit(self):
        config = PipelineConfig(
            template="clinical",
            output=PipelineOutput(limit=-5),
        )
        result = validate_pipeline_config(config)
        assert result.valid is False
        assert config.template == "clinical"

    def test_complex_noncanonical_pipeline_fails_without_rewrite(self):
        config = PipelineConfig(
            steps=[
                PipelineStep(id="", action="find", params={"query": "test"}),
                PipelineStep(id="merge1", action="combine", inputs=["step_1"]),
                PipelineStep(id="output", action="filter", inputs=["merge1"]),
            ]
        )
        result = validate_pipeline_config(config)
        assert result.valid is False
        assert config.steps[0].id == ""
        assert config.steps[0].action == "find"
        assert config.steps[1].action == "combine"

    def test_no_template_no_steps(self):
        """Config with neither template nor steps should fail."""
        config = PipelineConfig()
        result = validate_pipeline_config(config)
        assert result.valid is False
