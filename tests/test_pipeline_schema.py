"""Tests for the Pydantic-backed pipeline schema layer."""

from __future__ import annotations

from pubmed_search.application.pipeline.schema import parse_pipeline_schema


class TestParsePipelineSchema:
    """Structural schema parsing should be separate from semantic autofix."""

    def test_schema_parses_step_pipeline(self):
        raw = {
            "steps": [
                {"id": "s1", "action": "search", "params": {"query": "test"}},
                {"id": "s2", "action": "details", "inputs": ["s1"]},
            ]
        }

        result = parse_pipeline_schema(raw)

        assert result.valid is True
        assert result.config is not None
        assert len(result.config.steps) == 2

    def test_schema_wraps_string_inputs(self):
        raw = {
            "steps": [
                {"id": "s1", "action": "search"},
                {"id": "s2", "action": "details", "inputs": "s1"},
            ]
        }

        result = parse_pipeline_schema(raw)

        assert result.valid is True
        assert result.config is not None
        assert result.config.steps[1].inputs == ["s1"]
        assert any("wrapped single string" in fix.reason.lower() for fix in result.fixes)

    def test_schema_fixes_non_dict_params(self):
        raw = {
            "steps": [
                {"id": "s1", "action": "search", "params": "invalid"},
            ]
        }

        result = parse_pipeline_schema(raw)

        assert result.valid is True
        assert result.config is not None
        assert result.config.steps[0].params == {}
        assert any("params must be a dict" in fix.reason.lower() for fix in result.fixes)

    def test_schema_supports_template_params_alias(self):
        raw = {"template": "pico", "params": {"P": "ICU", "I": "remimazolam"}}

        result = parse_pipeline_schema(raw)

        assert result.valid is True
        assert result.config is not None
        assert result.config.template == "pico"
        assert result.config.template_params == {"P": "ICU", "I": "remimazolam"}

    def test_schema_coerces_output_limit(self):
        raw = {
            "steps": [{"id": "s1", "action": "search"}],
            "output": {"limit": "50"},
        }

        result = parse_pipeline_schema(raw)

        assert result.valid is True
        assert result.config is not None
        assert result.config.output.limit == 50

    def test_schema_reports_step_shape_errors(self):
        raw = {"steps": ["not_a_dict"]}

        result = parse_pipeline_schema(raw)

        assert result.valid is False
        assert any("steps.0" in error.lower() for error in result.errors)

    def test_schema_does_not_apply_semantic_alias_fix(self):
        raw = {"steps": [{"id": "s1", "action": "find"}]}

        result = parse_pipeline_schema(raw)

        assert result.valid is True
        assert result.config is not None
        assert result.config.steps[0].action == "find"

    def test_schema_does_not_apply_template_alias_fix(self):
        raw = {"template": "clinical"}

        result = parse_pipeline_schema(raw)

        assert result.valid is True
        assert result.config is not None
        assert result.config.template == "clinical"
