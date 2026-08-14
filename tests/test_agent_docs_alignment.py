from __future__ import annotations

import json
import re
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


def test_bundled_search_skills_preserve_bounded_provider_aware_contract() -> None:
    systematic = _read(".claude/skills/pubmed-systematic-search/SKILL.md")
    multi_source = _read(".claude/skills/pubmed-multi-source-search/SKILL.md")

    assert 'unified_search(options="systematic")' in systematic
    assert 'sources="pubmed,openalex,semantic_scholar"' in systematic
    assert "每個來源最多取回 100 筆" in systematic
    assert "不代表 exhaustive systematic-review coverage" in systematic
    assert 'sources="pubmed,europe_pmc,openalex"' not in systematic

    python_examples = re.findall(r"```python\s+(.*?)```", systematic, flags=re.DOTALL)
    fielded_search_examples = [
        example for example in python_examples if "[Title/Abstract]" in example and "unified_search(" in example
    ]
    assert fielded_search_examples
    for example in fielded_search_examples:
        assert 'sources="pubmed"' in example
        assert 'sources="pubmed,' not in example

    assert "唯一的 generic literature search 入口是 `unified_search`" in multi_source
    assert "bounded coverage expansion" in multi_source
    assert "不代表完整或 exhaustive coverage" in multi_source
    assert "Crossref 是以文章識別資料執行的 enrichment leg" in multi_source
    assert "不能作為唯一 primary source" in multi_source
    assert "跨來源找完整 coverage" not in multi_source


def test_user_docs_cover_timeline_image_search_upload_and_artifact_memory() -> None:
    required = [
        "build_research_chronicle",
        "read_research_chronicle",
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
        "build_research_chronicle",
        "read_research_chronicle",
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
