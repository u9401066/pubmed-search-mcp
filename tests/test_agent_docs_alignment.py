from __future__ import annotations

import json
from pathlib import Path

from pubmed_search.presentation.mcp_server.tool_registry import TOOL_CATEGORIES

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_copilot_tool_policy_covers_registered_tool_categories() -> None:
    policy = json.loads(_read(".github/hooks/copilot-tool-policy.json"))

    expected_groups = {name: set(info["tools"]) for name, info in TOOL_CATEGORIES.items()}
    actual_groups = {name: set(tools) for name, tools in policy["toolGroups"].items()}

    assert actual_groups == expected_groups
    assert "save_literature_notes" in actual_groups["export"]
    assert "diagnose_institutional_access" in actual_groups["institutional"]


def test_agent_pico_guidance_preserves_structured_handoff_boundary() -> None:
    paths = [
        ".claude/skills/pubmed-pico-search/SKILL.md",
        ".clinerules/70-pubmed-mcp-tools.md",
        ".github/agents/research.agent.md",
        ".github/zotero-research-workflow.md",
    ]

    for path in paths:
        content = _read(path)
        assert "P/I/C/O" in content, path
        assert "parse_pico" in content, path

    skill = _read(".claude/skills/pubmed-pico-search/SKILL.md")
    assert "The MCP server does not" in skill
    assert "semantically parse natural-language clinical questions" in skill
    assert "Agent extracts P/I/C/O" in skill
    assert "template: pico" in skill
    assert "When only `description` is provided" in skill


def test_pico_guidance_has_no_backend_auto_parse_examples() -> None:
    critical_paths = [
        "src/pubmed_search/presentation/mcp_server/instructions.py",
        "docs/COPILOT_HOOKS_PIPELINE_ENFORCEMENT.md",
        "docs/images/pico-clinical-workflow.svg",
        "docs/arxiv-paper/main.tex",
    ]
    forbidden = [
        "template: pico\\ntopic:",
        "自動 PICO 分解",
        "How a clinical question is parsed into PICO elements",
        "PICO parsing",
    ]

    for path in critical_paths:
        content = _read(path)
        for term in forbidden:
            assert term not in content, f"{path} still contains stale PICO guidance: {term}"


def test_user_docs_cover_timeline_image_search_upload_and_artifact_memory() -> None:
    required = [
        "build_research_timeline",
        "analyze_timeline_milestones",
        "compare_timelines",
        "Research Chronicle",
        "Research Chronicle Rebuild Spec",
        "search_biomedical_images",
        "Open-i",
        "analyze_figure_for_search",
        "ImageContent",
        "base64/data-URI",
        'read_session(action="artifact"',
        "PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS",
        "persistent query memory",
    ]

    english_docs = _read("docs/USER_GUIDE.md") + "\n" + _read("docs/TOOLS_USAGE_GUIDE.md")
    for term in required:
        assert term in english_docs

    zh_required = [
        "build_research_timeline",
        "analyze_timeline_milestones",
        "compare_timelines",
        "Research Chronicle",
        "Research Chronicle Rebuild Spec",
        "search_biomedical_images",
        "Open-i",
        "analyze_figure_for_search",
        "ImageContent",
        "base64/data-URI",
        'read_session(action="artifact"',
        "PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS",
        "持久化 query memory",
    ]
    zh_docs = _read("docs/USER_GUIDE.zh-TW.md") + "\n" + _read("docs/TOOLS_USAGE_GUIDE.zh-TW.md")
    for term in zh_required:
        assert term in zh_docs
