"""Tests for the Pydantic-backed pipeline schema layer."""

from __future__ import annotations

import pytest

from pubmed_search.application.pipeline.schema import parse_pipeline_schema


class TestParsePipelineSchema:
    """Structural schema parsing should be separate from semantic validation."""

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

    def test_schema_rejects_string_inputs(self):
        raw = {
            "steps": [
                {"id": "s1", "action": "search"},
                {"id": "s2", "action": "details", "inputs": "s1"},
            ]
        }

        result = parse_pipeline_schema(raw)

        assert result.valid is False
        assert result.config is None
        assert any("inputs" in error and "valid list" in error for error in result.errors)

    def test_schema_rejects_non_dict_params(self):
        raw = {
            "steps": [
                {"id": "s1", "action": "search", "params": "invalid"},
            ]
        }

        result = parse_pipeline_schema(raw)

        assert result.valid is False
        assert result.config is None
        assert any("params" in error and "valid dictionary" in error for error in result.errors)

    def test_schema_rejects_retired_template_params_alias(self):
        raw = {"template": "pico", "params": {"P": "ICU", "I": "remimazolam"}}

        result = parse_pipeline_schema(raw)

        assert result.valid is False
        assert result.config is None
        assert any("params" in error and "Extra inputs" in error for error in result.errors)

    def test_schema_accepts_canonical_template_params(self):
        raw = {"template": "pico", "template_params": {"P": "ICU", "I": "remimazolam"}}

        result = parse_pipeline_schema(raw)

        assert result.valid is True
        assert result.config is not None
        assert result.config.template_params == {"P": "ICU", "I": "remimazolam"}

    @pytest.mark.parametrize(
        "raw",
        [
            {"steps": [{"id": 1, "action": "search"}]},
            {"steps": [{"id": "s1", "action": 1}]},
            {"steps": [{"id": "s1", "action": "search", "inputs": [1]}]},
            {"name": 1, "steps": [{"id": "s1", "action": "search"}]},
            {"globals": [], "steps": [{"id": "s1", "action": "search"}]},
            {"variables": None, "steps": [{"id": "s1", "action": "search"}]},
            {"output": None, "steps": [{"id": "s1", "action": "search"}]},
            {"template": 1, "template_params": {}},
            {"template": "pico", "template_params": []},
            {"steps": [{"id": "s1", "action": "search"}], "output": {"format": "JSON"}},
        ],
    )
    def test_schema_rejects_wrong_types_nulls_and_case_variants(self, raw):
        result = parse_pipeline_schema(raw)

        assert result.valid is False
        assert result.config is None
        assert result.errors

    def test_schema_rejects_string_output_limit(self):
        raw = {
            "steps": [{"id": "s1", "action": "search"}],
            "output": {"limit": "50"},
        }

        result = parse_pipeline_schema(raw)

        assert result.valid is False
        assert result.config is None
        assert any("output.limit" in error and "valid integer" in error for error in result.errors)

    def test_schema_parses_globals_and_variables(self):
        raw = {
            "globals": {"sources": ["pubmed"], "limit": "${limit}"},
            "variables": {"limit": 25, "topic": "remimazolam"},
            "steps": [{"id": "s1", "action": "search", "params": {"query": "${topic}"}}],
        }

        result = parse_pipeline_schema(raw)

        assert result.valid is True
        assert result.config is not None
        assert result.config.globals == {"sources": ["pubmed"], "limit": "${limit}"}
        assert result.config.variables == {"limit": 25, "topic": "remimazolam"}

    def test_schema_reports_step_shape_errors(self):
        raw = {"steps": ["not_a_dict"]}

        result = parse_pipeline_schema(raw)

        assert result.valid is False
        assert any("steps.0" in error.lower() for error in result.errors)

    def test_schema_leaves_unknown_action_for_semantic_validation(self):
        raw = {"steps": [{"id": "s1", "action": "find"}]}

        result = parse_pipeline_schema(raw)

        assert result.valid is True
        assert result.config is not None
        assert result.config.steps[0].action == "find"

    def test_schema_leaves_unknown_template_for_semantic_validation(self):
        raw = {"template": "clinical"}

        result = parse_pipeline_schema(raw)

        assert result.valid is True
        assert result.config is not None
        assert result.config.template == "clinical"

    @pytest.mark.parametrize("kind", ["garbage", 123, None])
    def test_schema_rejects_explicit_invalid_discriminator(self, kind):
        result = parse_pipeline_schema(
            {
                "kind": kind,
                "steps": [{"id": "search", "action": "search"}],
            }
        )

        assert result.valid is False
        assert result.config is None

    def test_schema_rejects_explicit_contradictory_discriminator(self):
        result = parse_pipeline_schema(
            {
                "kind": "template",
                "steps": [{"id": "search", "action": "search"}],
            }
        )

        assert result.valid is False
        assert result.config is None
