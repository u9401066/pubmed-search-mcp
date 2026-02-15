#!/usr/bin/env python3
"""
MCP 工具統計腳本

統計並輸出所有已註冊的 MCP 工具（從 FastMCP runtime 取得）。
可用於：
1. 確認工具數量
2. 追蹤工具變化
3. 更新文檔（README.md, README.zh-TW.md, copilot-instructions.md, TOOLS_INDEX.md）

Usage:
    uv run python scripts/count_mcp_tools.py [--json] [--update-docs] [--verbose]

Notes:
    - 只統計透過 MCP 協議暴露的工具（等同 tools/list 響應）
    - 內部函數不會被計入
    - 工具描述從 FastMCP Tool.description 屬性取得
    - 建議在 git commit 前執行 --update-docs 確保文檔同步
"""

import argparse
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# Fix Windows cp950 encoding for emoji output
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pubmed_search.presentation.mcp_server.server import create_server
from src.pubmed_search.presentation.mcp_server.tool_registry import (
    TOOL_CATEGORIES,
    validate_tool_registry,
)


def get_registered_tools(mcp) -> list[str]:
    """取得所有已註冊的 MCP 工具名稱（透過 MCP 協議暴露的）"""
    return sorted(mcp._tool_manager._tools.keys())


def get_tool_details(mcp) -> dict[str, dict]:
    """
    從 FastMCP runtime 取得每個工具的詳細資訊。

    Returns:
        dict: {tool_name: {"description": str, "parameters": list[str]}}
    """
    details = {}
    for name, tool in mcp._tool_manager._tools.items():
        # 取得描述（第一行或前 100 字元）
        desc = tool.description.strip() if tool.description else ""
        # 取得第一行作為簡短描述
        first_line = desc.split("\n")[0].strip()
        # 移除開頭的 emoji 和空格
        first_line = re.sub(r"^[^\w\s]+\s*", "", first_line)

        details[name] = {
            "description": first_line[:100] if len(first_line) > 100 else first_line,
            "full_description": desc,
            "parameters": list(tool.parameters.keys()) if tool.parameters else [],
        }
    return details


def get_tools_by_category() -> dict[str, list[str]]:
    """取得按類別分組的工具"""
    return {cat: info["tools"] for cat, info in TOOL_CATEGORIES.items()}


def get_category_info() -> dict[str, dict]:
    """取得類別資訊"""
    return {cat: {"name": info["name"], "description": info["description"]} for cat, info in TOOL_CATEGORIES.items()}


def count_tools(include_details: bool = False):
    """
    統計工具數量。

    Args:
        include_details: 是否包含工具描述
    """
    # Suppress logging during server creation
    import logging

    logging.disable(logging.INFO)

    mcp = create_server()

    logging.disable(logging.NOTSET)

    tools = get_registered_tools(mcp)
    categories = get_tools_by_category()
    category_info = get_category_info()
    validation = validate_tool_registry(mcp)

    result = {
        "timestamp": datetime.now().isoformat(),
        "total_tools": len(tools),
        "total_categories": len(categories),
        "tools": tools,
        "categories": {
            cat: {
                "name": category_info[cat]["name"],
                "description": category_info[cat]["description"],
                "count": len(t),
                "tools": t,
            }
            for cat, t in categories.items()
        },
        "validation": {
            "valid": validation["valid"],
            "missing": validation["missing"],
            "extra": validation["extra"],
        },
    }

    if include_details:
        result["tool_details"] = get_tool_details(mcp)

    return result, mcp


def update_copilot_instructions(stats: dict, mcp) -> bool:
    """更新 copilot-instructions.md 中的工具數量和列表"""
    instructions_path = Path(__file__).parent.parent / ".github" / "copilot-instructions.md"

    if not instructions_path.exists():
        print(f"Warning: {instructions_path} not found")
        return False

    content = instructions_path.read_text(encoding="utf-8")
    updated = False

    # 1. 更新工具數量 "34+ MCP Tools"
    patterns = [
        (r"\*\*(\d+)\+ MCP Tools\*\*", f"**{stats['total_tools']}+ MCP Tools**"),
        (r"(\d+)\+ MCP Tools", f"{stats['total_tools']}+ MCP Tools"),
    ]

    for pattern, replacement in patterns:
        if re.search(pattern, content):
            new_content = re.sub(pattern, replacement, content)
            if new_content != content:
                content = new_content
                updated = True

    # 2. 生成工具列表區塊（按類別）
    tool_details = get_tool_details(mcp)

    # 生成 "## 📚 Tool Categories" 區塊的新內容
    tool_categories_section = generate_tool_categories_markdown(stats, tool_details)

    # 尋找並替換 Tool Categories 區塊
    # 從 "## 📚 Tool Categories" 到下一個 "## " 或 "---"
    pattern = r"(## 📚 Tool Categories\n)(.*?)((?=\n## )|(?=\n---)|$)"
    match = re.search(pattern, content, re.DOTALL)

    if match:
        new_section = match.group(1) + tool_categories_section
        new_content = content[: match.start()] + new_section + content[match.end() :]
        if new_content != content:
            content = new_content
            updated = True

    if updated:
        instructions_path.write_text(content, encoding="utf-8")
        print(f"✅ Updated {instructions_path}")
    else:
        print(f"ℹ️  No updates needed in {instructions_path}")

    return updated


def _get_category_order(stats: dict) -> list[str]:
    """動態取得類別順序。

    優先使用預定義的順序，自動附加新增的類別到尾端。
    這樣新增類別時不需要手動更新此列表。
    """
    preferred_order = [
        "search",
        "query_intelligence",
        "discovery",
        "fulltext",
        "ncbi_extended",
        "citation_network",
        "export",
        "session",
        "institutional",
        "vision",
        "icd",
        "timeline",
    ]
    # Append any categories not in the preferred order
    all_cats = list(stats["categories"].keys())
    for cat in all_cats:
        if cat not in preferred_order:
            preferred_order.append(cat)
    return preferred_order


def generate_tool_categories_markdown(stats: dict, tool_details: dict) -> str:
    """生成工具類別的 Markdown 內容"""
    lines = []

    # 動態取得類別順序（自動包含新增類別）
    category_order = _get_category_order(stats)

    for cat_key in category_order:
        if cat_key not in stats["categories"]:
            continue

        cat = stats["categories"][cat_key]
        lines.append(f"\n### {cat['name']}")
        lines.append(f"*{cat['description']}*\n")
        lines.append("| Tool | Purpose |")
        lines.append("|------|---------|")

        for tool_name in cat["tools"]:
            desc = tool_details.get(tool_name, {}).get("description", "")
            lines.append(f"| `{tool_name}` | {desc} |")
        lines.append("")

    return "\n".join(lines)


def update_tools_index(stats: dict, mcp) -> bool:
    """更新 TOOLS_INDEX.md 中的工具數量和列表"""
    index_path = (
        Path(__file__).parent.parent / "src" / "pubmed_search" / "presentation" / "mcp_server" / "TOOLS_INDEX.md"
    )

    if not index_path.exists():
        print(f"Warning: {index_path} not found")
        return False

    tool_details = get_tool_details(mcp)

    # 生成完整的 TOOLS_INDEX.md 內容
    content = generate_tools_index_markdown(stats, tool_details)

    old_content = index_path.read_text(encoding="utf-8")
    if content != old_content:
        index_path.write_text(content, encoding="utf-8")
        print(f"✅ Updated {index_path}")
        return True

    print(f"ℹ️  No updates needed in {index_path}")
    return False


def generate_tools_index_markdown(stats: dict, tool_details: dict) -> str:
    """生成完整的 TOOLS_INDEX.md 內容"""
    lines = [
        "# PubMed Search MCP - Tools Index",
        "",
        f"Quick reference for all {stats['total_tools']} available MCP tools. Auto-generated from `tool_registry.py`.",
        "",
        "---",
    ]

    # 動態取得類別順序（自動包含新增類別）
    category_order = _get_category_order(stats)

    for cat_key in category_order:
        if cat_key not in stats["categories"]:
            continue

        cat = stats["categories"][cat_key]
        lines.append(f"\n## {cat['name']}")
        lines.append(f"*{cat['description']}*\n")
        lines.append("| Tool | Description |")
        lines.append("|------|-------------|")

        for tool_name in cat["tools"]:
            desc = tool_details.get(tool_name, {}).get("description", "")
            lines.append(f"| `{tool_name}` | {desc} |")

    # 檔案結構
    lines.extend(
        [
            "",
            "---",
            "",
            "## 檔案結構",
            "",
            "```",
            "mcp_server/",
            "├── server.py           # Server 創建與配置",
            "├── instructions.py     # AI Agent 使用說明",
            "├── tool_registry.py    # 工具註冊中心",
            "├── session_tools.py    # Session 管理工具",
            "├── resources.py        # MCP Resources",
            "├── prompts.py          # MCP Prompts",
            "├── TOOLS_INDEX.md      # 本檔案 (工具索引)",
            "└── tools/              # 工具實作",
            "    ├── __init__.py     # 統一入口",
            "    ├── _common.py      # 共用工具函數",
            "    ├── unified.py      # unified_search",
            "    ├── discovery.py    # 搜尋與探索",
            "    ├── strategy.py     # MeSH/查詢策略",
            "    ├── pico.py         # PICO 解析",
            "    ├── export.py       # 匯出工具",
            "    ├── europe_pmc.py   # Europe PMC 全文",
            "    ├── core.py         # CORE 開放取用",
            "    ├── ncbi_extended.py # Gene/PubChem/ClinVar",
            "    ├── citation_tree.py # 引用網路",
            "    ├── openurl.py      # 機構訂閱",
            "    ├── vision_search.py # 視覺搜索",
            "    └── icd.py          # ICD 轉換工具",
            "```",
            "",
            "---",
            "",
            f"*Total: {stats['total_tools']} tools in {stats['total_categories']} categories*",
            f"*Last updated: {stats['timestamp'][:10]} (auto-generated by scripts/count_mcp_tools.py)*",
        ]
    )

    return "\n".join(lines) + "\n"


def update_readme(stats: dict, readme_path: Path, is_chinese: bool = False) -> bool:
    """
    更新 README.md 或 README.zh-TW.md 中的工具數量。

    Args:
        stats: 工具統計資訊
        readme_path: README 檔案路徑
        is_chinese: 是否為中文版
    """
    if not readme_path.exists():
        print(f"Warning: {readme_path} not found")
        return False

    content = readme_path.read_text(encoding="utf-8")
    updated = False
    tool_count = stats["total_tools"]

    # 更新工具數量的各種模式
    patterns = [
        # English: "21 MCP Tools" or "**21 MCP Tools**"
        (r"\*\*(\d+) MCP Tools\*\*", f"**{tool_count} MCP Tools**"),
        (r"(\d+) MCP Tools", f"{tool_count} MCP Tools"),
        # Chinese: "21 個 MCP 工具" or "**21 個 MCP 工具**"
        (r"\*\*(\d+) 個 MCP 工具\*\*", f"**{tool_count} 個 MCP 工具**"),
        (r"(\d+) 個 MCP 工具", f"{tool_count} 個 MCP 工具"),
    ]

    for pattern, replacement in patterns:
        if re.search(pattern, content):
            new_content = re.sub(pattern, replacement, content)
            if new_content != content:
                content = new_content
                updated = True

    if updated:
        readme_path.write_text(content, encoding="utf-8")
        print(f"✅ Updated {readme_path.name}: {tool_count} tools")
    else:
        print(f"ℹ️  No updates needed in {readme_path.name}")

    return updated


def update_all_readmes(stats: dict) -> int:
    """更新所有 README 檔案，返回更新數量"""
    root = Path(__file__).parent.parent
    updated_count = 0

    # README.md (English)
    if update_readme(stats, root / "README.md", is_chinese=False):
        updated_count += 1

    # README.zh-TW.md (Chinese)
    if update_readme(stats, root / "README.zh-TW.md", is_chinese=True):
        updated_count += 1

    # copilot-studio/README.md
    copilot_readme = root / "copilot-studio" / "README.md"
    if copilot_readme.exists():
        if update_readme(stats, copilot_readme, is_chinese=True):
            updated_count += 1

    return updated_count


def update_instructions_py(stats: dict, mcp) -> bool:
    """
    更新 instructions.py 中的「所有可用工具」區塊。

    只替換最後的工具列表區塊，保留搜尋策略說明等手寫內容。
    """
    instructions_path = (
        Path(__file__).parent.parent / "src" / "pubmed_search" / "presentation" / "mcp_server" / "instructions.py"
    )

    if not instructions_path.exists():
        print(f"Warning: {instructions_path} not found")
        return False

    content = instructions_path.read_text(encoding="utf-8")
    tool_details = get_tool_details(mcp)

    # 生成新的工具列表區塊
    new_tool_section = _generate_instructions_tool_list(stats, tool_details)

    # 尋找並替換 "所有可用工具" 區塊（從標題到 NOTE 結尾）
    pattern = (
        r"(═{10,}\n🔧 所有可用工具\n═{10,}\n)"
        r"(.*?)"
        r"(NOTE: 搜尋結果自動暫存.*?不需依賴 Agent 記憶。)"
    )
    match = re.search(pattern, content, re.DOTALL)

    if not match:
        print(f"Warning: Could not find '所有可用工具' section in {instructions_path}")
        return False

    # 替換工具列表內容
    new_content = content[: match.start(2)] + new_tool_section + "\n" + match.group(3) + content[match.end() :]

    if new_content != content:
        instructions_path.write_text(new_content, encoding="utf-8")
        print(f"✅ Updated {instructions_path.name}: {stats['total_tools']} tools")
        return True

    print(f"ℹ️  No updates needed in {instructions_path.name}")
    return False


def _generate_instructions_tool_list(stats: dict, tool_details: dict) -> str:
    """生成 instructions.py 的工具列表內容"""
    lines = []

    # 動態取得類別順序（自動包含新增類別）
    category_order = _get_category_order(stats)

    for cat_key in category_order:
        if cat_key not in stats["categories"]:
            continue

        cat = stats["categories"][cat_key]
        lines.append(f"\n### {cat['name']}")

        for tool_name in cat["tools"]:
            desc = tool_details.get(tool_name, {}).get("description", "")
            lines.append(f"- {tool_name}: {desc}")

    lines.append("")
    return "\n".join(lines)


def update_skill_tools_reference(stats: dict, mcp) -> bool:
    """
    更新 .claude/skills/pubmed-mcp-tools-reference/SKILL.md。

    從 FastMCP runtime 自動生成完整的工具參考。
    """
    skill_path = Path(__file__).parent.parent / ".claude" / "skills" / "pubmed-mcp-tools-reference" / "SKILL.md"

    if not skill_path.exists():
        print(f"Warning: {skill_path} not found")
        return False

    tool_details = get_tool_details(mcp)
    new_content = _generate_skill_tools_reference(stats, tool_details)

    old_content = skill_path.read_text(encoding="utf-8")
    if new_content != old_content:
        skill_path.write_text(new_content, encoding="utf-8")
        print(f"✅ Updated {skill_path.name}: {stats['total_tools']} tools")
        return True

    print(f"ℹ️  No updates needed in {skill_path.name}")
    return False


def _generate_skill_tools_reference(stats: dict, tool_details: dict) -> str:
    """生成 pubmed-mcp-tools-reference SKILL.md 的完整內容"""
    total = stats["total_tools"]
    categories = stats["categories"]

    lines = [
        "---",
        "name: pubmed-mcp-tools-reference",
        f"description: Complete reference for all {total} PubMed Search MCP tools. Triggers: 工具列表, all tools, 完整功能, tool reference, 有哪些工具",
        "---",
        "",
        "# PubMed Search MCP 工具完整參考",
        "",
        "## 描述",
        f"所有 {total} 個 MCP 工具的完整參考，包含參數說明和使用範例。",
        "",
        "> **⚠️ 注意**：此文件由 `scripts/count_mcp_tools.py --update-docs` 自動生成。",
        "> 手動修改會在下次執行時被覆蓋。",
        "",
        "---",
        "",
        "## 工具分類總覽",
        "",
        "| 類別 | 工具數 | 主要用途 |",
        "|------|--------|----------|",
    ]

    # 動態取得類別順序（自動包含新增類別）
    category_order = _get_category_order(stats)

    for cat_key in category_order:
        if cat_key not in categories:
            continue
        cat = categories[cat_key]
        lines.append(f"| {cat['name']} | {cat['count']} | {cat['description']} |")

    lines.append("")
    lines.append("---")

    # 每個類別的工具詳情
    for cat_key in category_order:
        if cat_key not in categories:
            continue
        cat = categories[cat_key]
        lines.append("")
        lines.append(f"## {cat['name']}")
        lines.append(f"*{cat['description']}*")
        lines.append("")
        lines.append("| 工具 | 說明 |")
        lines.append("|------|------|")

        for tool_name in cat["tools"]:
            desc = tool_details.get(tool_name, {}).get("description", "")
            lines.append(f"| `{tool_name}` | {desc} |")

    # 常用工作流程
    lines.extend(
        [
            "",
            "---",
            "",
            "## 常用工作流程",
            "",
            "### 快速搜尋",
            "```",
            "unified_search → fetch_article_details → prepare_export",
            "```",
            "",
            "### 系統性搜尋",
            "```",
            "generate_search_queries → unified_search × N → merge results",
            "```",
            "",
            "### PICO 搜尋",
            "```",
            "parse_pico → generate_search_queries × 4 → unified_search → merge results",
            "```",
            "",
            "### 論文探索",
            "```",
            "fetch_article_details → find_related_articles + find_citing_articles + build_citation_tree",
            "```",
            "",
            "### 全文取得",
            "```",
            "get_fulltext (自動嘗試 Europe PMC / CORE / CrossRef)",
            "```",
            "",
            "---",
            "",
            f"*Total: {total} tools in {len(categories)} categories*",
            "*Auto-generated by `scripts/count_mcp_tools.py --update-docs`*",
        ]
    )

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="Count and document MCP tools (from FastMCP runtime)",
        epilog="Examples:\n"
        "  uv run python scripts/count_mcp_tools.py           # Basic stats\n"
        "  uv run python scripts/count_mcp_tools.py --json    # JSON output\n"
        "  uv run python scripts/count_mcp_tools.py --update-docs  # Update docs\n"
        "  uv run python scripts/count_mcp_tools.py --verbose # With descriptions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON (includes tool details)")
    parser.add_argument("--update-docs", action="store_true", help="Update documentation files")
    parser.add_argument("--quiet", "-q", action="store_true", help="Minimal output (just count)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show tool descriptions")
    args = parser.parse_args()

    include_details = args.json or args.update_docs or args.verbose
    stats, mcp = count_tools(include_details=include_details)

    if args.json:
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return

    if args.quiet:
        print(stats["total_tools"])
        return

    # 標準輸出
    print("=" * 60)
    print("  PubMed Search MCP - Tool Statistics")
    print(f"  Generated: {stats['timestamp'][:19]}")
    print("  Source: FastMCP runtime (MCP tools/list equivalent)")
    print("=" * 60)
    print()
    print(f"  📊 Total MCP Tools: {stats['total_tools']}")
    print(f"  📁 Categories: {stats['total_categories']}")
    print()

    print("  By Category:")
    for cat_key, cat in stats["categories"].items():
        print(f"    - {cat['name']}: {cat['count']}")
    print()

    if stats["validation"]["valid"]:
        print("  ✅ Validation: PASSED (TOOL_CATEGORIES in sync)")
    else:
        print("  ❌ Validation: FAILED")
        if stats["validation"]["missing"]:
            print(f"     Missing: {stats['validation']['missing']}")
        if stats["validation"]["extra"]:
            print(f"     Extra: {stats['validation']['extra']}")
    print()

    if args.verbose and "tool_details" in stats:
        print("  All Tools (with descriptions):")
        for i, tool in enumerate(stats["tools"], 1):
            desc = stats["tool_details"].get(tool, {}).get("description", "")
            print(f"    {i:2}. {tool}")
            if desc:
                print(f"        └─ {desc[:60]}{'...' if len(desc) > 60 else ''}")
    else:
        print("  All Tools:")
        for i, tool in enumerate(stats["tools"], 1):
            print(f"    {i:2}. {tool}")

    print()
    print("=" * 60)

    if args.update_docs:
        print()
        print("Updating documentation...")
        print()

        # 統計更新
        updated_files = 0

        # 1. README 檔案（工具數量）
        print("📄 README files:")
        updated_files += update_all_readmes(stats)
        print()

        # 2. Copilot Instructions（工具數量 + 列表）
        print("📋 Copilot Instructions:")
        if update_copilot_instructions(stats, mcp):
            updated_files += 1
        print()

        # 3. TOOLS_INDEX.md（完整工具索引）
        print("📚 Tools Index:")
        if update_tools_index(stats, mcp):
            updated_files += 1
        print()

        # 4. instructions.py（MCP Server 內嵌指南的工具列表）
        print("🤖 MCP Server Instructions:")
        if update_instructions_py(stats, mcp):
            updated_files += 1
        print()

        # 5. Claude Skill: pubmed-mcp-tools-reference（完整工具參考）
        print("📖 Skill: pubmed-mcp-tools-reference:")
        if update_skill_tools_reference(stats, mcp):
            updated_files += 1

        print()
        print(f"📊 Summary: {updated_files} file(s) updated")
        print(f"   Total MCP Tools: {stats['total_tools']}")
        print(f"   Categories: {stats['total_categories']}")
        print()
        print("💡 Tip: Run 'git diff' to review changes")


if __name__ == "__main__":
    main()
