"""Executable contracts for the bilingual public-tool quality audit."""

from __future__ import annotations

import re
from pathlib import Path

from pubmed_search.application.visualization.mermaid import validate_mermaid_source
from pubmed_search.presentation.mcp_server.tool_contracts import tool_annotations, tool_meta
from pubmed_search.presentation.mcp_server.tool_registry import TOOL_CATEGORIES

ROOT = Path(__file__).resolve().parents[1]
DOCS = (
    ROOT / "docs/TOOL_QUALITY_AUDIT.md",
    ROOT / "docs/TOOL_QUALITY_AUDIT.zh-TW.md",
)

TOOL_ROW_RE = re.compile(
    r"^\| `(?P<tool>[a-z0-9_]+)` \| (?P<role>[^|\n]+) \| "
    r"(?P<relations>[^|\n]+) \| (?P<contract>[^|\n]+) \|$",
    re.MULTILINE,
)
CATEGORY_HEADING_RE = re.compile(r"^### \d+\. `([a-z_]+)` — ", re.MULTILINE)
MERMAID_RE = re.compile(r"```mermaid\n(.*?)\n```", re.DOTALL)
MERMAID_NODE_ID_RE = re.compile(r'^    ([A-Za-z][A-Za-z0-9_]*)\["', re.MULTILINE)
MERMAID_RESERVED_NODE_IDS = frozenset({"end", "flowchart", "graph", "subgraph"})


def _runtime_tools() -> tuple[str, ...]:
    """Derive the expected public surface from the runtime source of truth."""
    return tuple(tool_name for metadata in TOOL_CATEGORIES.values() for tool_name in metadata["tools"])


def test_runtime_registry_still_has_the_audited_shape() -> None:
    expected_tools = _runtime_tools()

    assert len(TOOL_CATEGORIES) == 16
    assert len(expected_tools) == 41
    assert len(set(expected_tools)) == len(expected_tools)


def test_bilingual_inventories_match_the_runtime_registry_exactly() -> None:
    expected_tools = _runtime_tools()
    expected_categories = tuple(TOOL_CATEGORIES)

    for document in DOCS:
        content = document.read_text(encoding="utf-8")
        rows = list(TOOL_ROW_RE.finditer(content))

        assert tuple(row.group("tool") for row in rows) == expected_tools
        assert tuple(CATEGORY_HEADING_RE.findall(content)) == expected_categories
        for row in rows:
            for field in ("role", "relations", "contract"):
                assert len(row.group(field).strip()) >= 10, (
                    document.name,
                    row.group("tool"),
                    field,
                )


def test_inventory_contract_traits_match_runtime_annotations() -> None:
    for document in DOCS:
        content = document.read_text(encoding="utf-8")
        contracts = {row.group("tool"): row.group("contract").casefold() for row in TOOL_ROW_RE.finditer(content)}

        for tool_name in _runtime_tools():
            contract = contracts[tool_name]
            annotations = tool_annotations(tool_name)
            side_effect = tool_meta(tool_name)["pubmed-search"]["sideEffect"]

            assert contract.startswith(side_effect), (document.name, tool_name, contract)
            assert ("read-only" in contract) is bool(annotations.read_only_hint)
            assert ("non-idempotent" in contract) is not bool(annotations.idempotent_hint)
            if annotations.idempotent_hint:
                assert "idempotent" in contract
            expected_world = "open-world" if annotations.open_world_hint else "local-only"
            assert expected_world in contract, (document.name, tool_name, contract)


def test_bilingual_audits_cover_required_contract_topics() -> None:
    english = DOCS[0].read_text(encoding="utf-8")
    chinese = DOCS[1].read_text(encoding="utf-8")

    english_sections = (
        "# MCP Tool Quality Audit",
        "## Architecture and DDD boundaries",
        "## Routing flow and contract boundary",
        "### Discriminated requests and sources",
        "### Global output budget",
        "## Mermaid kernel and Research Chronicle",
        "## Breaking deduplication delivered",
    )
    chinese_sections = (
        "# MCP 工具品質稽核",
        "## 架構與 DDD 邊界",
        "## 路由流程與契約邊界",
        "### 判別式 request 與 source",
        "### 全域輸出預算",
        "## Mermaid 核心與 Research Chronicle",
        "## 本輪已完成的去重與 breaking 修正",
    )

    for heading in english_sections:
        assert heading in english
    for heading in chinese_sections:
        assert heading in chinese
    for content in (english, chinese):
        assert "contractVersion: 3" in content
        assert "500,000" in content
        assert "horizontal chronological spine" in content or "橫式時間主軸" in content
        assert "manage_pipeline" in content
        assert "unschedule_pipeline" in content
        assert "timeline_mermaid" in content


def test_all_audit_diagrams_use_the_shared_mermaid_subset() -> None:
    for document in DOCS:
        diagrams = MERMAID_RE.findall(document.read_text(encoding="utf-8"))

        assert len(diagrams) == 3
        assert diagrams[0].startswith("flowchart LR\n")
        assert diagrams[1].startswith("flowchart TD\n")
        assert diagrams[2].startswith("flowchart LR\n")
        for index, source in enumerate(diagrams, start=1):
            node_ids = MERMAID_NODE_ID_RE.findall(source)
            assert MERMAID_RESERVED_NODE_IDS.isdisjoint(node_ids), (
                document.name,
                index,
                node_ids,
            )
            valid, issues = validate_mermaid_source(source)
            assert valid, (document.name, index, issues)
