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

    def test_search_group_keeps_one_generic_literature_search_entry(self):
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

        assert TOOL_CATEGORIES["search"]["tools"] == ["unified_search"]
        assert policy["toolGroups"]["search"] == ["unified_search"]

    def test_runtime_contract_is_privacy_safe_advisory_and_recoverable(self):
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        contract = policy["runtimeContract"]

        assert contract["stateSchemaVersion"] == 2
        assert contract["decisionMode"] == "advisory_allow"
        assert contract["privacy"] == {
            "persistRawPrompt": False,
            "persistRawQuery": False,
            "persistRenderedToolResult": False,
            "identifier": "session-keyed-hmac-sha256",
        }
        assert contract["evaluationPriority"][:2] == ["structuredContent", "jsonTextContent"]
        assert contract["recovery"]["artifactReader"] == "read_session"

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

    def test_chronicle_topic_build_and_persisted_reads_are_not_pre_search_guarded(self):
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        guarded_tools = set(policy["rules"]["requiresEvidenceOrIdentifiers"])

        assert guarded_tools.isdisjoint({"build_research_chronicle", "read_research_chronicle"})
        assert {"build_research_chronicle", "read_research_chronicle"} <= set(policy["rules"]["feedbackRemediation"])

    def test_chronicle_hook_contracts_cover_intent_context_and_audit_failure(self):
        runtime = Path("scripts/hooks/copilot/hook_runtime.py").read_text(encoding="utf-8")

        assert 'return "chronicle", "moderate", "comprehensive"' in runtime
        assert r"\u7814\u7a76\u7de8\u5e74\u53f2" in runtime
        assert "chronicle_id" in runtime
        assert "topic" in runtime
        assert "audit_status" in runtime

        for phase in (
            "analyze-prompt",
            "enforce-pipeline",
            "evaluate-results",
            "session-init",
            "session-cleanup",
        ):
            bash = Path(f"scripts/hooks/copilot/{phase}.sh").read_text(encoding="utf-8")
            powershell = Path(f"scripts/hooks/copilot/{phase}.ps1").read_text(encoding="utf-8")
            assert "hook_runtime.py" in bash
            assert "hook_runtime.py" in powershell
            assert powershell.isascii(), "Windows PowerShell 5.1 wrappers must remain ASCII"
            assert "[Console]::InputEncoding = $utf8" in powershell
            assert "[Console]::OutputEncoding = $utf8" in powershell
            assert "$OutputEncoding = $utf8" in powershell

    def test_policy_has_no_duplicate_tools_within_sections(self):
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

        for section_name in ("toolGroups", "rules"):
            section = policy[section_name]
            for key, items in section.items():
                assert len(items) == len(set(items)), f"Duplicate tool in {section_name}.{key}"

        for key, metadata in policy["workflowSteps"].items():
            items = metadata["tools"]
            assert len(items) == len(set(items)), f"Duplicate tool in workflowSteps.{key}.tools"
