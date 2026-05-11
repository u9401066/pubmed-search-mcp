from __future__ import annotations

import json
import re

from scripts.build_docs_site import (
    DOCS_ROOT,
    EMBEDDED_CONTENT_FILE,
    OUTPUT_DIR,
    PACKAGED_REFERENCES,
    PAGES,
    REPO_ROOT,
    _render_packaged_reference,
    _render_page,
    _rewrite_links,
    _route_map,
)
from scripts.count_mcp_tools import count_tools

IMAGE_LINK_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _load_embedded_pages() -> dict[str, str]:
    prefix = "window.DOC_PAGE_CONTENT = "
    raw = EMBEDDED_CONTENT_FILE.read_text(encoding="utf-8")
    assert raw.startswith(prefix)

    payload = raw.removeprefix(prefix).strip()
    payload = payload.removesuffix(";")

    return json.loads(payload)


def test_docs_site_pages_match_generated_sources() -> None:
    route_map = _route_map()
    embedded_pages = _load_embedded_pages()

    for slug, title, source_path in PAGES:
        expected = _render_page(slug, title, source_path, route_map)
        generated = (OUTPUT_DIR / f"{slug}.md").read_text(encoding="utf-8")

        assert generated == expected
        assert embedded_pages[slug] == expected


def test_docs_site_router_references_generated_pages() -> None:
    site_js = (DOCS_ROOT / "site.js").read_text(encoding="utf-8")

    for slug, _title, _source_path in PAGES:
        assert f'slug: "{slug}"' in site_js
        assert f'file: "site-content/{slug}.md"' in site_js


def test_docs_site_image_links_rewrite_to_published_assets() -> None:
    route_map = _route_map()

    readme_markdown = "![Workflow](docs/images/research-workflow.svg)"
    docs_markdown = "![Workflow](images/research-workflow.svg)"

    assert _rewrite_links(readme_markdown, REPO_ROOT / "README.md", route_map) == (
        "![Workflow](images/research-workflow.svg)"
    )
    assert _rewrite_links(docs_markdown, DOCS_ROOT / "USER_GUIDE.md", route_map) == (
        "![Workflow](images/research-workflow.svg)"
    )


def test_generated_docs_site_image_assets_exist() -> None:
    embedded_pages = _load_embedded_pages()

    missing: list[str] = []
    for slug, markdown in embedded_pages.items():
        for target in IMAGE_LINK_PATTERN.findall(markdown):
            if not target.startswith("images/"):
                continue
            asset = DOCS_ROOT / target
            if not asset.exists():
                missing.append(f"{slug}: {target}")

    assert missing == []


def test_packaged_references_match_generated_sources_and_images_exist() -> None:
    missing_assets: list[str] = []

    for reference in PACKAGED_REFERENCES:
        expected = _render_packaged_reference(reference["source"], reference["replacements"])
        target_path = reference["target"]

        assert target_path.read_text(encoding="utf-8") == expected

        for image_target in IMAGE_LINK_PATTERN.findall(expected):
            if image_target.startswith(("http://", "https://")):
                continue
            asset = (target_path.parent / image_target).resolve()
            if not asset.exists():
                missing_assets.append(f"{target_path}: {image_target}")

    assert missing_assets == []


def test_primary_tool_count_mentions_match_runtime_surface() -> None:
    stats, _mcp = count_tools(include_details=False)
    total = stats["total_tools"]

    snippets_by_path = {
        REPO_ROOT / "README.md": [
            f"**{total} MCP Tools**",
            f"memorizing {total} tool names",
            "diagnose_institutional_access",
        ],
        REPO_ROOT / "README.zh-TW.md": [
            f"**{total} 個 MCP 工具**",
            f"理解這 {total} 個工具",
            "diagnose_institutional_access",
        ],
        DOCS_ROOT / "TOOLS_USAGE_GUIDE.md": [f"{total}-tool PubMed Search MCP surface"],
        DOCS_ROOT / "TOOLS_USAGE_GUIDE.zh-TW.md": [f"不用死背 {total} 個 MCP tool"],
        REPO_ROOT / "ARCHITECTURE.md": [
            f"提供 {total} 個 MCP tools",
            f"{total} tools / 16 categories",
            "引用驗證 | 1 | `verify_reference_list`",
        ],
        DOCS_ROOT / "INTEGRATIONS.md": [
            f"Full {total}-tool primary MCP surface",
            f"enumerate {total} tools in the primary MCP surface",
        ],
        REPO_ROOT / "DEPLOYMENT.md": [f"完整 {total}-tool primary MCP surface"],
        REPO_ROOT / "copilot-studio/README.md": [f"完整 {total}-tool primary MCP surface"],
        REPO_ROOT / ".github/copilot-instructions.md": [f"**{total} MCP Tools**"],
    }

    for path, snippets in snippets_by_path.items():
        content = path.read_text(encoding="utf-8")
        for snippet in snippets:
            assert snippet in content, f"{path} is missing {snippet!r}"
