"""Tests for Copilot hook tool coverage policy."""

from __future__ import annotations

import json
from pathlib import Path

from pubmed_search.presentation.mcp_server.tool_registry import TOOL_CATEGORIES

POLICY_PATH = Path(".github/hooks/copilot-tool-policy.json")


def _all_registry_tools() -> set[str]:
    tools: set[str] = set()
    for category in TOOL_CATEGORIES.values():
        tools.update(category["tools"])
    return tools


def _flatten_mapping_values(mapping: dict[str, list[str]]) -> set[str]:
    values: set[str] = set()
    for items in mapping.values():
        values.update(items)
    return values


def _flatten_workflow_step_tools(workflow_steps: dict[str, dict[str, object]]) -> set[str]:
    values: set[str] = set()
    for metadata in workflow_steps.values():
        tools = metadata.get("tools", [])
        assert isinstance(tools, list)
        values.update(tools)
    return values


class TestCopilotHookPolicy:
    def test_policy_file_exists(self):
        assert POLICY_PATH.exists()

    def test_tool_groups_cover_all_registered_tools(self):
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

        assert _flatten_mapping_values(policy["toolGroups"]) == _all_registry_tools()

    def test_workflow_steps_cover_all_registered_tools(self):
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

        assert _flatten_workflow_step_tools(policy["workflowSteps"]) == _all_registry_tools()

    def test_workflow_steps_include_shared_instruction_metadata(self):
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

        for step_name, metadata in policy["workflowSteps"].items():
            assert metadata["label"], f"workflowSteps.{step_name} missing label"
            assert metadata["nextInstruction"], f"workflowSteps.{step_name} missing nextInstruction"
            assert isinstance(metadata["tools"], list), f"workflowSteps.{step_name}.tools must be a list"

    def test_quality_evaluation_is_not_search_only(self):
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        quality_tools = set(policy["rules"]["qualityEvaluation"])

        assert "unified_search" in quality_tools
        assert "find_related_articles" in quality_tools
        assert "get_fulltext" in quality_tools
        assert "prepare_export" in quality_tools
        assert "read_session" in quality_tools

    def test_requires_evidence_is_not_search_only(self):
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        guarded_tools = set(policy["rules"]["requiresEvidenceOrIdentifiers"])

        assert "get_fulltext" in guarded_tools
        assert "find_related_articles" in guarded_tools
        assert "prepare_export" in guarded_tools
        assert "get_session_summary" in guarded_tools
        assert "get_pipeline_history" in guarded_tools

    def test_policy_has_no_duplicate_tools_within_sections(self):
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

        for section_name in ("toolGroups", "rules"):
            section = policy[section_name]
            for key, items in section.items():
                assert len(items) == len(set(items)), f"Duplicate tool in {section_name}.{key}"

        for key, metadata in policy["workflowSteps"].items():
            items = metadata["tools"]
            assert len(items) == len(set(items)), f"Duplicate tool in workflowSteps.{key}.tools"
