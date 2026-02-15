"""Tests for PipelineValidator — aggressive auto-fix validation.

Coverage targets:
- Action alias resolution + fuzzy matching
- Template alias resolution + fuzzy matching
- Step ID auto-generation + deduplication
- Dependency repair (broken refs, cycle removal, fuzzy match)
- on_error / output validation + auto-fix
- parse_and_validate_config (raw dict → validated PipelineConfig)
- config hash computation
- Pipeline name validation
- Edge cases and unfixable errors
"""

from __future__ import annotations

import pytest

from pubmed_search.application.pipeline.validator import (
    _fuzzy_match_action,
    _fuzzy_match_template,
    compute_config_hash,
    parse_and_validate_config,
    validate_and_fix,
    validate_pipeline_name,
)
from pubmed_search.domain.entities.pipeline import (
    FixSeverity,
    PipelineConfig,
    PipelineOutput,
    PipelineStep,
)

# =========================================================================
# Pipeline Name Validation
# =========================================================================


class TestValidatePipelineName:
    """Tests for validate_pipeline_name()."""

    def test_simple_valid_name(self):
        name, fixes = validate_pipeline_name("my_pipeline")
        assert name == "my_pipeline"
        assert fixes == []

    def test_uppercase_normalized(self):
        name, fixes = validate_pipeline_name("My Pipeline")
        assert name == "my_pipeline"
        assert len(fixes) == 1
        assert fixes[0].severity == FixSeverity.INFO

    def test_special_chars_removed(self):
        name, fixes = validate_pipeline_name("my.pipeline@v2!")
        assert name == "my_pipelinev2"
        assert len(fixes) == 1

    def test_spaces_to_underscores(self):
        name, fixes = validate_pipeline_name("my  cool  pipeline")
        assert name == "my_cool_pipeline"

    def test_max_length_64(self):
        long_name = "a" * 100
        name, fixes = validate_pipeline_name(long_name)
        assert len(name) == 64
        assert len(fixes) == 1

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_pipeline_name("")

    def test_all_invalid_chars_raises(self):
        with pytest.raises(ValueError, match="no valid characters"):
            validate_pipeline_name("!@#$%")

    def test_hyphens_preserved(self):
        name, fixes = validate_pipeline_name("my-pipeline")
        assert name == "my-pipeline"
        assert fixes == []

    def test_leading_trailing_whitespace_stripped(self):
        name, fixes = validate_pipeline_name("  hello  ")
        assert name == "hello"

    def test_multiple_consecutive_underscores_collapsed(self):
        name, fixes = validate_pipeline_name("a___b")
        assert name == "a_b"


# =========================================================================
# Action Fuzzy Matching
# =========================================================================


class TestFuzzyMatchAction:
    """Tests for _fuzzy_match_action()."""

    def test_direct_alias_find(self):
        action, fix = _fuzzy_match_action("find")
        assert action == "search"
        assert fix is not None
        assert fix.severity == FixSeverity.WARNING

    def test_direct_alias_cite(self):
        action, fix = _fuzzy_match_action("cite")
        assert action == "citing"
        assert fix is not None

    def test_direct_alias_refs(self):
        action, fix = _fuzzy_match_action("refs")
        assert action == "references"

    def test_direct_alias_get(self):
        action, fix = _fuzzy_match_action("get")
        assert action == "details"

    def test_direct_alias_combine(self):
        action, fix = _fuzzy_match_action("combine")
        assert action == "merge"

    def test_direct_alias_dedup(self):
        action, fix = _fuzzy_match_action("dedup")
        assert action == "filter"

    def test_direct_alias_synonym(self):
        action, fix = _fuzzy_match_action("synonym")
        assert action == "expand"

    def test_valid_action_no_match(self):
        """Valid actions should still be returned if passed through fuzzy."""
        # _fuzzy_match_action only handles INVALID actions
        # Valid ones don't appear in aliases, so shouldn't match
        action, fix = _fuzzy_match_action("totally_unknown_xyz")
        assert fix is None  # no match found

    def test_case_insensitive(self):
        action, fix = _fuzzy_match_action("FIND")
        assert action == "search"

    def test_fuzzy_close_match(self):
        """'searc' is close enough to 'search'."""
        action, fix = _fuzzy_match_action("searc")
        assert action == "search"
        assert fix is not None
        assert "fuzzy" in fix.reason.lower()

    def test_no_match_returns_original(self):
        action, fix = _fuzzy_match_action("zzzznotanaction")
        assert action == "zzzznotanaction"
        assert fix is None


# =========================================================================
# Template Fuzzy Matching
# =========================================================================


class TestFuzzyMatchTemplate:
    """Tests for _fuzzy_match_template()."""

    def test_direct_alias_clinical(self):
        template, fix = _fuzzy_match_template("clinical")
        assert template == "pico"
        assert fix is not None

    def test_direct_alias_systematic(self):
        template, fix = _fuzzy_match_template("systematic")
        assert template == "comprehensive"

    def test_direct_alias_explore(self):
        template, fix = _fuzzy_match_template("explore")
        assert template == "exploration"

    def test_direct_alias_drug(self):
        template, fix = _fuzzy_match_template("drug")
        assert template == "gene_drug"

    def test_fuzzy_match_close(self):
        """'comprehensiv' is close enough to 'comprehensive'."""
        template, fix = _fuzzy_match_template("comprehensiv")
        assert template == "comprehensive"

    def test_no_match_returns_original(self):
        template, fix = _fuzzy_match_template("zzzznotatemplate")
        assert template == "zzzznotatemplate"
        assert fix is None


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
# validate_and_fix — Template Path
# =========================================================================


class TestValidateAndFixTemplate:
    """Tests for validate_and_fix() with template-based configs."""

    def test_valid_template(self):
        config = PipelineConfig(template="pico")
        result = validate_and_fix(config)
        assert result.valid is True
        assert not result.has_fixes
        assert not result.has_errors

    def test_template_alias_auto_fixed(self):
        config = PipelineConfig(template="clinical")
        result = validate_and_fix(config)
        assert result.valid is True
        assert result.has_fixes
        assert config.template == "pico"

    def test_unknown_template_error(self):
        config = PipelineConfig(template="zzz_unknown_template_zzz")
        result = validate_and_fix(config)
        assert result.valid is False
        assert result.has_errors
        assert "Unknown template" in result.errors[0]


# =========================================================================
# validate_and_fix — Step Path
# =========================================================================


class TestValidateAndFixSteps:
    """Tests for validate_and_fix() with step-based configs."""

    def test_valid_steps(self):
        config = PipelineConfig(
            steps=[
                PipelineStep(id="s1", action="search", params={"query": "test"}),
                PipelineStep(id="s2", action="details", inputs=["s1"]),
            ]
        )
        result = validate_and_fix(config)
        assert result.valid is True

    def test_empty_steps_error(self):
        config = PipelineConfig(steps=[])
        result = validate_and_fix(config)
        assert result.valid is False
        assert "at least one step" in result.errors[0]

    def test_too_many_steps_error(self):
        steps = [PipelineStep(id=f"s{i}", action="search") for i in range(25)]
        config = PipelineConfig(steps=steps)
        result = validate_and_fix(config)
        assert result.valid is False
        assert "maximum" in result.errors[0]

    def test_auto_generate_missing_ids(self):
        config = PipelineConfig(
            steps=[
                PipelineStep(id="", action="search"),
                PipelineStep(id="", action="details"),
            ]
        )
        result = validate_and_fix(config)
        assert result.valid is True
        assert config.steps[0].id == "step_1"
        assert config.steps[1].id == "step_2"
        assert len([f for f in result.fixes if "auto-generated" in f.reason.lower()]) == 2

    def test_deduplicate_step_ids(self):
        config = PipelineConfig(
            steps=[
                PipelineStep(id="search", action="search"),
                PipelineStep(id="search", action="details"),
            ]
        )
        result = validate_and_fix(config)
        assert result.valid is True
        # Second one should be renamed
        ids = [s.id for s in config.steps]
        assert len(set(ids)) == 2
        assert "search" in ids
        assert "search_2" in ids

    def test_fuzzy_fix_action(self):
        config = PipelineConfig(steps=[PipelineStep(id="s1", action="find")])
        result = validate_and_fix(config)
        assert result.valid is True
        assert config.steps[0].action == "search"
        assert result.has_fixes

    def test_unknown_action_error(self):
        config = PipelineConfig(steps=[PipelineStep(id="s1", action="zzz_invalid_zzz")])
        result = validate_and_fix(config)
        assert result.valid is False
        assert any("unknown action" in e.lower() for e in result.errors)


# =========================================================================
# validate_and_fix — Dependency Repair
# =========================================================================


class TestValidateAndFixDependencies:
    """Tests for dependency validation and repair."""

    def test_valid_dependencies(self):
        config = PipelineConfig(
            steps=[
                PipelineStep(id="s1", action="search"),
                PipelineStep(id="s2", action="details", inputs=["s1"]),
            ]
        )
        result = validate_and_fix(config)
        assert result.valid is True
        assert config.steps[1].inputs == ["s1"]

    def test_remove_forward_reference(self):
        """Step referencing a later step should be removed (cycle prevention)."""
        config = PipelineConfig(
            steps=[
                PipelineStep(id="s1", action="search", inputs=["s2"]),
                PipelineStep(id="s2", action="details"),
            ]
        )
        result = validate_and_fix(config)
        assert result.valid is True
        assert config.steps[0].inputs == []  # s2 reference removed
        assert any("cycle" in f.reason.lower() for f in result.fixes)

    def test_remove_unknown_reference(self):
        config = PipelineConfig(
            steps=[
                PipelineStep(id="s1", action="search"),
                PipelineStep(id="s2", action="details", inputs=["nonexistent"]),
            ]
        )
        result = validate_and_fix(config)
        assert result.valid is True
        assert config.steps[1].inputs == []

    def test_fuzzy_match_dependency(self):
        """'s_1' close enough to 's1' should be matched."""
        config = PipelineConfig(
            steps=[
                PipelineStep(id="search_step", action="search"),
                PipelineStep(id="details_step", action="details", inputs=["search_ste"]),
            ]
        )
        result = validate_and_fix(config)
        assert result.valid is True
        # The fuzzy match should fix 'search_ste' → 'search_step'
        assert config.steps[1].inputs == ["search_step"]


# =========================================================================
# validate_and_fix — on_error / output
# =========================================================================


class TestValidateAndFixOutputOnError:
    """Tests for on_error and output validation."""

    def test_invalid_on_error_fixed(self):
        config = PipelineConfig(steps=[PipelineStep(id="s1", action="search", on_error="continue")])
        result = validate_and_fix(config)
        assert result.valid is True
        assert config.steps[0].on_error == "skip"
        assert result.has_fixes

    def test_valid_on_error_abort(self):
        config = PipelineConfig(steps=[PipelineStep(id="s1", action="search", on_error="abort")])
        result = validate_and_fix(config)
        assert result.valid is True
        assert config.steps[0].on_error == "abort"

    def test_invalid_output_format_fixed(self):
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search")],
            output=PipelineOutput(format="xml"),
        )
        result = validate_and_fix(config)
        assert result.valid is True
        assert config.output.format == "markdown"

    def test_invalid_ranking_fuzzy_fixed(self):
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search")],
            output=PipelineOutput(ranking="impac"),  # close to "impact"
        )
        result = validate_and_fix(config)
        assert result.valid is True
        assert config.output.ranking == "impact"

    def test_invalid_ranking_defaults_to_balanced(self):
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search")],
            output=PipelineOutput(ranking="zzz_unknown"),
        )
        result = validate_and_fix(config)
        assert result.valid is True
        assert config.output.ranking == "balanced"

    def test_negative_limit_fixed(self):
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search")],
            output=PipelineOutput(limit=0),
        )
        result = validate_and_fix(config)
        assert result.valid is True
        assert config.output.limit == 20

    def test_valid_output_passes(self):
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search")],
            output=PipelineOutput(format="json", limit=50, ranking="recency"),
        )
        result = validate_and_fix(config)
        assert result.valid is True
        assert not result.has_fixes


# =========================================================================
# parse_and_validate_config — Raw Dict Parsing
# =========================================================================


class TestParseAndValidateConfig:
    """Tests for parse_and_validate_config() (dict → PipelineConfig)."""

    def test_simple_template(self):
        raw = {"template": "pico", "template_params": {"query": "test"}}
        result = parse_and_validate_config(raw)
        assert result.valid is True
        assert result.config is not None
        assert result.config.template == "pico"

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

    def test_inputs_string_wrapped(self):
        """Single string input should be wrapped in a list."""
        raw = {
            "steps": [
                {"id": "s1", "action": "search"},
                {"id": "s2", "action": "details", "inputs": "s1"},
            ]
        }
        result = parse_and_validate_config(raw)
        assert result.valid is True
        assert result.config.steps[1].inputs == ["s1"]
        assert any("wrapped" in f.reason.lower() for f in result.fixes)

    def test_params_non_dict_fixed(self):
        raw = {
            "steps": [
                {"id": "s1", "action": "search", "params": "invalid"},
            ]
        }
        result = parse_and_validate_config(raw)
        assert result.valid is True
        assert result.config.steps[0].params == {}
        assert any("params must be a dict" in f.reason.lower() for f in result.fixes)

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
        assert result.config.output.format == "markdown"
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
        assert result.valid is True
        # 'retry' is normalized to 'skip' during parsing
        assert result.config.steps[0].on_error == "skip"

    def test_non_dict_output_ignored(self):
        raw = {
            "steps": [{"id": "s1", "action": "search"}],
            "output": "not_a_dict",
        }
        result = parse_and_validate_config(raw)
        assert result.valid is True
        assert result.config.output.format == "markdown"

    def test_action_alias_auto_fix_through_parse(self):
        """'find' alias should be resolved to 'search' through full parse path."""
        raw = {"steps": [{"id": "s1", "action": "find"}]}
        result = parse_and_validate_config(raw)
        assert result.valid is True
        assert result.config.steps[0].action == "search"

    def test_template_alias_auto_fix_through_parse(self):
        """'clinical' alias should be resolved to 'pico'."""
        raw = {"template": "clinical"}
        result = parse_and_validate_config(raw)
        assert result.valid is True
        assert result.config.template == "pico"


# =========================================================================
# ValidationResult summary
# =========================================================================


class TestValidationResultSummary:
    """Tests for ValidationResult.summary() output."""

    def test_valid_no_fixes(self):
        config = PipelineConfig(template="pico")
        result = validate_and_fix(config)
        summary = result.summary()
        assert "valid" in summary.lower() or "✅" in summary

    def test_with_fixes_shows_details(self):
        config = PipelineConfig(template="clinical")
        result = validate_and_fix(config)
        summary = result.summary()
        assert "Auto-fixed" in summary
        assert "clinical" in summary

    def test_with_errors_shows_details(self):
        config = PipelineConfig(template="zzz_unknown_zzz")
        result = validate_and_fix(config)
        summary = result.summary()
        assert "❌" in summary
        assert "Unfixable" in summary


# =========================================================================
# Edge Cases
# =========================================================================


class TestValidatorEdgeCases:
    """Edge cases and combined scenarios."""

    def test_multiple_fixes_combined(self):
        """Template alias + output fix combined."""
        config = PipelineConfig(
            template="clinical",  # → pico
            output=PipelineOutput(limit=-5),  # → 20
        )
        result = validate_and_fix(config)
        assert result.valid is True
        # Template-based configs return early before output validation
        # So only template fix is applied
        assert result.has_fixes

    def test_complex_step_pipeline(self):
        """A realistic multi-step pipeline with some fixes needed."""
        config = PipelineConfig(
            steps=[
                PipelineStep(id="", action="find", params={"query": "test"}),  # id + action fix
                PipelineStep(id="merge1", action="combine", inputs=["step_1"]),  # action fix
                PipelineStep(id="output", action="filter", inputs=["merge1"]),
            ]
        )
        result = validate_and_fix(config)
        assert result.valid is True
        assert config.steps[0].id == "step_1"
        assert config.steps[0].action == "search"
        assert config.steps[1].action == "merge"

    def test_no_template_no_steps(self):
        """Config with neither template nor steps should fail."""
        config = PipelineConfig()
        result = validate_and_fix(config)
        assert result.valid is False
