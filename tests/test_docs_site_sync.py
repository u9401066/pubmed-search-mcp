from __future__ import annotations

import json
import re
from urllib.parse import unquote

import pytest
from scripts.build_docs_site import (
    DOCS_ROOT,
    EMBEDDED_CONTENT_FILE,
    OUTPUT_DIR,
    PACKAGED_REFERENCES,
    PAGES,
    REPO_ROOT,
    _normalize_generated_text,
    _render_packaged_reference,
    _render_page,
    _rewrite_links,
    _route_map,
    _site_heading_ids,
)
from scripts.count_mcp_tools import count_tools

IMAGE_LINK_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
MARKDOWN_LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
FENCED_CODE_PATTERN = re.compile(r"^```.*?^```\s*$", re.MULTILINE | re.DOTALL)
INLINE_CODE_PATTERN = re.compile(r"`[^`\n]*`")
CACHE_KEY_PATTERN = re.compile(r"\?v=([a-z0-9-]+)")
FONT_SIZE_VIEWPORT_PATTERN = re.compile(r"font-size:[^;]*(?:vw|clamp\()", re.IGNORECASE)
LARGE_RADIUS_PATTERN = re.compile(r"border-radius:\s*(\d+)px", re.IGNORECASE)
DOC_PAGE_ENTRY_PATTERN = re.compile(
    r'slug:\s*"([^"]+)"[\s\S]*?file:\s*"site-content/([^"]+)"',
    re.MULTILINE,
)


def _load_embedded_pages() -> dict[str, str]:
    prefix = "window.DOC_PAGE_CONTENT = "
    raw = EMBEDDED_CONTENT_FILE.read_text(encoding="utf-8")
    assert raw.startswith(prefix)

    payload = raw.removeprefix(prefix).strip()
    payload = payload.removesuffix(";")

    return json.loads(payload)


def _site_nav_entries() -> list[tuple[str, str]]:
    site_js = (DOCS_ROOT / "site.js").read_text(encoding="utf-8")
    return DOC_PAGE_ENTRY_PATTERN.findall(site_js)


def test_docs_site_pages_match_generated_sources() -> None:
    route_map = _route_map()
    embedded_pages = _load_embedded_pages()

    for slug, title, source_path in PAGES:
        expected = _normalize_generated_text(_render_page(slug, title, source_path, route_map))
        generated = (OUTPUT_DIR / f"{slug}.md").read_text(encoding="utf-8")

        assert generated == expected
        assert embedded_pages[slug] == expected


def test_docs_site_router_references_generated_pages() -> None:
    site_js = (DOCS_ROOT / "site.js").read_text(encoding="utf-8")

    for slug, _title, _source_path in PAGES:
        assert f'slug: "{slug}"' in site_js
        assert f'file: "site-content/{slug}.md"' in site_js


def test_docs_site_navigation_entries_have_embedded_content() -> None:
    embedded_pages = _load_embedded_pages()
    nav_entries = _site_nav_entries()

    assert nav_entries
    for slug, filename in nav_entries:
        assert filename == f"{slug}.md"
        assert slug in embedded_pages
        assert (OUTPUT_DIR / filename).exists()


def test_docs_site_filter_indexes_keywords_and_page_body() -> None:
    site_js = (DOCS_ROOT / "site.js").read_text(encoding="utf-8")
    embedded_pages = _load_embedded_pages()

    search_haystack = re.search(r"function searchHaystack\(page\) \{(?P<body>[\s\S]*?)\n\}", site_js)
    assert search_haystack
    haystack_body = search_haystack.group("body")

    assert "page.keywords" in haystack_body
    assert "embeddedContent[page.slug]" in haystack_body
    assert "searchHaystack(page).includes(normalized)" in site_js
    assert "context_graph" in embedded_pages["advanced-workflows"]
    assert "context_graph" in site_js


def test_advanced_workflows_are_visible_in_docs_site_navigation() -> None:
    site_js = (DOCS_ROOT / "site.js").read_text(encoding="utf-8")

    assert 'slug: "advanced-workflows"' in site_js
    assert 'slug: "advanced-workflows-zh"' in site_js

    for term in [
        "Research chronicle",
        "Open-i image search",
        "uploaded-image handoff",
        "persistent query memory",
        "build_research_chronicle",
        "read_research_chronicle",
        "context_graph",
        "search_biomedical_images",
        "analyze_figure_for_search",
        "read_session artifact",
        "研究脈絡時間軸",
        "上傳圖片",
        "持久化 query memory",
    ]:
        assert term in site_js


def test_docs_site_shell_uses_current_assets_and_mobile_image_wrapping() -> None:
    index_html = (DOCS_ROOT / "index.html").read_text(encoding="utf-8")
    site_js = (DOCS_ROOT / "site.js").read_text(encoding="utf-8")

    cache_keys = set(CACHE_KEY_PATTERN.findall(index_html))

    assert cache_keys == {"20260814-provider-broker"}
    assert 'id="sidebar-backdrop"' in index_html
    assert index_html.count('data-page-group="') == 3
    assert "45</strong>" in index_html
    assert "runtime contracts" in index_html
    assert "function wrapLocalImages()" in site_js
    assert "sidebarBackdrop.addEventListener" in site_js


def test_docs_site_quick_paths_follow_the_active_language() -> None:
    index_html = (DOCS_ROOT / "index.html").read_text(encoding="utf-8")
    site_js = (DOCS_ROOT / "site.js").read_text(encoding="utf-8")

    for group in ("overview", "user-guide", "deployment"):
        assert f'data-page-group="{group}"' in index_html

    assert 'document.querySelectorAll("[data-page-group]")' in site_js
    assert "page.group === group && page.lang === activeLang" in site_js
    assert 'link.setAttribute("href", `#/${target.slug}`)' in site_js
    assert 'journeyLabel: "Documentation quick paths"' in site_js
    assert 'journeyLabel: "文件快速路徑"' in site_js


def test_docs_site_navigation_exposes_the_current_operating_handbook() -> None:
    site_js = (DOCS_ROOT / "site.js").read_text(encoding="utf-8")
    embedded_pages = _load_embedded_pages()

    for term in [
        "MCP SDK v2",
        "Integrations & Operations",
        "整合與維運",
        "Multi-source broker stages",
        "authenticated multi-user contracts",
        "45 MCP tools across 16 registry categories",
        "Semantic Scholar Data Plane",
        "OpenAlex Search And Data Plane",
        "ClinicalKey AI Boundary",
        "BioMCP Architecture Analysis",
    ]:
        assert term in site_js

    integrations = embedded_pages["troubleshooting"]
    for term in [
        "MCP SDK v2 Protocol Baseline",
        "does **not** begin with `initialize`",
        "Authenticated service callers cannot read `file:` paths",
        "service Compose profile forces it off",
        "Running the local browser broker",
        "same unified runner",
        "Verification & Troubleshooting",
    ]:
        assert term in integrations

    assert "12-tool primitive-schema smoke tests" in embedded_pages["overview"]
    assert "primitive-schema `read_session`" in embedded_pages["overview"]
    assert "12-tool schema" in embedded_pages["user-guide"]
    assert "search-run, replay-argument" in embedded_pages["user-guide"]
    assert "12-tool primitive-schema smoke" in embedded_pages["troubleshooting"]
    assert "generic literature search 名稱為 `unified_search`" in embedded_pages["deployment"]

    source_contracts = embedded_pages["source-contracts"]
    for term in ["Unified Search Broker", "Scopus", "Web of Science", "process-wide conservative rate budget"]:
        assert term in source_contracts

    assert "dataset partition" in embedded_pages["semantic-scholar-api"]
    assert 'options="systematic"' in embedded_pages["semantic-scholar-api"]
    assert "search.semantic" in embedded_pages["openalex-api"]
    assert 'options="native_semantic"' in embedded_pages["openalex-api"]
    assert "not an MCP source/tool" in embedded_pages["clinicalkey-ai"]
    assert "HTTP 2xx" in embedded_pages["clinicalkey-ai"]
    assert "unified_search" in embedded_pages["biomcp-analysis"]
    assert "本輪已落地與後續邊界" in embedded_pages["biomcp-analysis"]


def test_docs_site_exposes_recoverable_bounded_unified_search_contract() -> None:
    embedded_pages = _load_embedded_pages()

    overview = embedded_pages["overview"]
    for term in [
        "exactly one MCP",
        "divided across that source's query strategies",
        "search-run/v1",
        'read_session(action="replay_search"',
        "no public cursor-resume parameter yet",
        "inline, `saved:<name>`, or `dry_run=true` pipeline execution",
        'search_run.status="history_unavailable"',
    ]:
        assert term in overview

    overview_zh = embedded_pages["overview-zh"]
    for term in [
        "固定只有一個 MCP tool",
        "所有 query strategies 的**總額度**",
        "可回復的 search runs",
        "`replay_search` 只回傳原本、已移除 credential",
    ]:
        assert term in overview_zh

    tools = embedded_pages["tools-usage-guide"]
    for term in [
        "`search_status` object over rendered text length",
        "credential-free",
        "PipelineStore history and the invocation journal are complementary",
        "contains credentials is rejected as a failed run",
    ]:
        assert term in tools

    source_contracts = embedded_pages["source-contracts"]
    for term in [
        "Structured outcome and durable recovery contract",
        "bounded=true",
        "automatic_execution=false",
        "ArtifactStore.discover()",
        "every `unified_search` invocation",
        'status="history_unavailable"',
    ]:
        assert term in source_contracts

    architecture = embedded_pages["architecture"]
    for term in [
        "Start tenant search-run journal",
        "search_status + search_run handoff + results",
        "published orphan",
        "Inline / saved / dry-run pipeline mode",
        "history_available=false",
    ]:
        assert term in architecture


def test_docs_site_isolates_mermaid_rendering_and_preserves_failed_source() -> None:
    index_html = (DOCS_ROOT / "index.html").read_text(encoding="utf-8")
    site_js = (DOCS_ROOT / "site.js").read_text(encoding="utf-8")

    assert "mermaid@11.16.1/dist/mermaid.min.js" in index_html
    assert 'securityLevel: "strict"' in site_js
    assert "suppressErrorRendering: true" in site_js
    assert "for (const [index, block] of blocks.entries())" in site_js
    assert "await renderMermaidBlock(block, index, generation)" in site_js
    assert "await window.mermaid.parse(renderTarget.source)" in site_js
    assert "await window.mermaid.run({ nodes: [renderTarget.diagram], suppressErrors: false })" in site_js
    assert "sourceCode.textContent = source" in site_js
    assert 'shell.dataset.mermaidStatus = "error"' in site_js
    assert "generation !== pageRenderGeneration" in site_js
    assert 'svg.setAttribute("aria-label"' in site_js
    assert 'notice.setAttribute("role", "status")' in site_js
    assert "error.message || error.str || error.error?.message" in site_js
    assert "if (window.marked)" in site_js
    assert "docContent.replaceChildren(notice, sourceContainer)" in site_js
    assert 'securityLevel: "loose"' not in site_js


def test_docs_site_css_stays_readable_and_tool_like() -> None:
    site_css = (DOCS_ROOT / "site.css").read_text(encoding="utf-8")

    assert "radial-gradient" not in site_css
    assert "linear-gradient" not in site_css
    assert not FONT_SIZE_VIEWPORT_PATTERN.search(site_css)

    large_radii = [int(match.group(1)) for match in LARGE_RADIUS_PATTERN.finditer(site_css) if int(match.group(1)) > 8]
    assert large_radii == []


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


def test_docs_site_links_preserve_fragments_and_route_repo_files() -> None:
    route_map = _route_map()

    assert (
        _rewrite_links(
            "[README section](../README.md#-configuration)",
            DOCS_ROOT / "INTEGRATIONS.md",
            route_map,
        )
        == "[README section](#/overview#configuration)"
    )
    assert (
        _rewrite_links(
            "[Deployment check](../DEPLOYMENT.md#10-驗證清單)",
            DOCS_ROOT / "INTEGRATIONS.md",
            route_map,
        )
        == "[Deployment check](#/deployment#10-%E9%A9%97%E8%AD%89%E6%B8%85%E5%96%AE)"
    )
    assert (
        _rewrite_links(
            "[Citation](CITATION.cff)",
            REPO_ROOT / "README.md",
            route_map,
        )
        == "[Citation](https://github.com/u9401066/pubmed-search-mcp/blob/master/CITATION.cff)"
    )


def test_docs_site_link_rewrite_rejects_missing_routed_heading() -> None:
    with pytest.raises(ValueError, match=r"DEPLOYMENT\.md#9-驗證清單"):
        _rewrite_links(
            "[Stale deployment check](../DEPLOYMENT.md#9-驗證清單)",
            DOCS_ROOT / "INTEGRATIONS.md",
            _route_map(),
        )


def test_generated_docs_site_has_no_broken_repo_relative_links() -> None:
    embedded_pages = _load_embedded_pages()
    valid_slugs = {slug for slug, _title, _source in PAGES}
    heading_ids_by_slug = {slug: set(_site_heading_ids(source_path)) for slug, _title, source_path in PAGES}
    broken: list[str] = []

    for slug, markdown in embedded_pages.items():
        prose = INLINE_CODE_PATTERN.sub("", FENCED_CODE_PATTERN.sub("", markdown))
        for target in MARKDOWN_LINK_PATTERN.findall(prose):
            if target.startswith("#/"):
                routed_target = target.removeprefix("#/")
                target_slug, separator, fragment = routed_target.partition("#")
                if target_slug not in valid_slugs:
                    broken.append(f"{slug}: unknown route {target}")
                elif separator and unquote(fragment) not in heading_ids_by_slug[target_slug]:
                    broken.append(f"{slug}: missing route heading {target}")
                continue
            if target.startswith(("#", "http://", "https://", "mailto:")):
                continue

            local_target = target.split("#", 1)[0]
            if not (DOCS_ROOT / local_target).exists():
                broken.append(f"{slug}: missing published target {target}")

    assert broken == []


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
        expected = _normalize_generated_text(_render_packaged_reference(reference["source"], reference["replacements"]))
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
    from pubmed_search.presentation.mcp_server.tool_registry import TOOL_CATEGORIES

    stats, _mcp = count_tools(include_details=False)
    total = stats["total_tools"]
    categories = len(TOOL_CATEGORIES)

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
            f"{total} tools / {categories} categories",
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
