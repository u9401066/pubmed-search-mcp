"""Build the embedded documentation site payload from repository Markdown.

Design:
    This script generates the docs/site-content/*.md files and the embedded
    JavaScript payload consumed by the lightweight docs site. It rewrites
    internal links so repository Markdown can be browsed through the static
    client-side router. It also syncs selected documentation into skill
    reference folders for external agent bundles that do not ship docs/site-content.

Maintenance:
    Update the PAGES table when documentation surfaces are added, renamed, or
    removed. Keep link-rewrite behavior centralized here so generated docs stay
    consistent with README and docs navigation.
"""

from __future__ import annotations

import json
import re
from functools import cache
from html import unescape as html_unescape
from pathlib import Path
from typing import TypedDict
from urllib.parse import quote, unquote

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
OUTPUT_DIR = DOCS_ROOT / "site-content"
EMBEDDED_CONTENT_FILE = DOCS_ROOT / "site-content.js"
REPO_BLOB_BASE = "https://github.com/u9401066/pubmed-search-mcp/blob/master"
REPO_TREE_BASE = "https://github.com/u9401066/pubmed-search-mcp/tree/master"

PAGES = [
    ("overview", "Overview", REPO_ROOT / "README.md"),
    ("overview-zh", "Overview (zh-TW)", REPO_ROOT / "README.zh-TW.md"),
    ("user-guide", "User Guide", DOCS_ROOT / "USER_GUIDE.md"),
    ("user-guide-zh", "User Guide (zh-TW)", DOCS_ROOT / "USER_GUIDE.zh-TW.md"),
    ("advanced-workflows", "Advanced Research Workflows", DOCS_ROOT / "ADVANCED_RESEARCH_WORKFLOWS.md"),
    (
        "advanced-workflows-zh",
        "Advanced Research Workflows (zh-TW)",
        DOCS_ROOT / "ADVANCED_RESEARCH_WORKFLOWS.zh-TW.md",
    ),
    (
        "research-chronicle-rebuild-spec",
        "Research Chronicle Rebuild Spec",
        DOCS_ROOT / "RESEARCH_CHRONICLE_REFACTOR_SPEC.md",
    ),
    ("developer-guide", "Developer Guide", DOCS_ROOT / "DEVELOPER_GUIDE.md"),
    ("developer-guide-zh", "Developer Guide (zh-TW)", DOCS_ROOT / "DEVELOPER_GUIDE.zh-TW.md"),
    ("python-sdk-http-cli-design", "Python SDK And HTTP CLI Design", DOCS_ROOT / "PYTHON_SDK_AND_HTTP_CLI_DESIGN.md"),
    ("architecture", "Architecture", REPO_ROOT / "ARCHITECTURE.md"),
    ("pipeline-tutorial", "Pipeline Tutorial", DOCS_ROOT / "PIPELINE_MODE_TUTORIAL.en.md"),
    ("pipeline-tutorial-zh", "Pipeline Tutorial (zh-TW)", DOCS_ROOT / "PIPELINE_MODE_TUTORIAL.md"),
    ("tools-usage-guide", "Tools Usage Guide", DOCS_ROOT / "TOOLS_USAGE_GUIDE.md"),
    ("tools-usage-guide-zh", "Tools Usage Guide (zh-TW)", DOCS_ROOT / "TOOLS_USAGE_GUIDE.zh-TW.md"),
    (
        "quick-reference",
        "Quick Reference",
        REPO_ROOT / "src" / "pubmed_search" / "presentation" / "mcp_server" / "TOOLS_INDEX.md",
    ),
    ("source-contracts", "Source Contracts", DOCS_ROOT / "SOURCE_CONTRACTS.md"),
    ("troubleshooting", "Integrations & Operations", DOCS_ROOT / "INTEGRATIONS.md"),
    ("deployment", "Deployment", REPO_ROOT / "DEPLOYMENT.md"),
]


class PackagedReference(TypedDict):
    """A documentation source copied into an agent-bundled reference path."""

    source: Path
    target: Path
    replacements: dict[str, str]


PACKAGED_REFERENCES: list[PackagedReference] = [
    {
        "source": DOCS_ROOT / "PIPELINE_MODE_TUTORIAL.en.md",
        "target": REPO_ROOT / ".claude/skills/pipeline-persistence/references/pipeline-tutorial.md",
        "replacements": {
            "PIPELINE_MODE_TUTORIAL.md": "pipeline-tutorial.zh-TW.md",
            "](images/": "](../../../../docs/images/",
        },
    },
    {
        "source": DOCS_ROOT / "PIPELINE_MODE_TUTORIAL.md",
        "target": REPO_ROOT / ".claude/skills/pipeline-persistence/references/pipeline-tutorial.zh-TW.md",
        "replacements": {
            "PIPELINE_MODE_TUTORIAL.en.md": "pipeline-tutorial.md",
            "](images/": "](../../../../docs/images/",
        },
    },
]

LINK_PATTERN = re.compile(r"(!?)\[([^\]]+)\]\(([^)]+)\)")
FENCED_CODE_PATTERN = re.compile(r"^(?:```|~~~).*?^(?:```|~~~)\s*$", re.MULTILINE | re.DOTALL)
ATX_HEADING_PATTERN = re.compile(r"^#{1,4}\s+(.+?)\s*#*\s*$", re.MULTILINE)
INLINE_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
INLINE_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]+\)")
INLINE_CODE_PATTERN = re.compile(r"`([^`\n]*)`")
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


def _route_map() -> dict[str, str]:
    return {source.relative_to(REPO_ROOT).as_posix(): f"#/{slug}" for slug, _title, source in PAGES}


def _site_heading_slug(text: str) -> str:
    """Mirror ``slugifyHeading`` in docs/site.js for generated route anchors."""
    rendered_text = INLINE_IMAGE_PATTERN.sub("", text)
    rendered_text = INLINE_LINK_PATTERN.sub(r"\1", rendered_text)
    rendered_text = INLINE_CODE_PATTERN.sub(r"\1", rendered_text)
    rendered_text = HTML_TAG_PATTERN.sub("", rendered_text)
    rendered_text = html_unescape(rendered_text).replace("\\", "")
    rendered_text = re.sub(r"[*_~]", "", rendered_text).strip().lower()
    slug = "".join(
        character
        for character in rendered_text
        if character.isalpha() or character.isdigit() or character.isspace() or character == "-"
    )
    slug = re.sub(r"\s", "-", slug)
    return re.sub(r"^-+", "", slug) or "section"


@cache
def _site_heading_ids(source_path: Path) -> tuple[str, ...]:
    """Return the heading IDs that the browser will assign to one source page."""
    markdown = source_path.read_text(encoding="utf-8")
    prose = FENCED_CODE_PATTERN.sub("", markdown)
    seen: dict[str, int] = {}
    heading_ids: list[str] = []

    for heading_text in ATX_HEADING_PATTERN.findall(prose):
        base_id = _site_heading_slug(heading_text)
        occurrence = seen.get(base_id, 0) + 1
        seen[base_id] = occurrence
        heading_ids.append(base_id if occurrence == 1 else f"{base_id}-{occurrence}")

    return tuple(heading_ids)


def _route_source_map() -> dict[str, Path]:
    return {source.relative_to(REPO_ROOT).as_posix(): source for _slug, _title, source in PAGES}


def _resolve_route_fragment(relative: str, fragment: str, source_path: Path) -> str:
    """Map a repository fragment to a real client-side heading ID or fail."""
    target_source = _route_source_map().get(relative)
    if target_source is None:
        raise ValueError(f"No documentation source registered for routed target {relative}")

    decoded_fragment = unquote(fragment)
    heading_ids = set(_site_heading_ids(target_source))
    for candidate in (decoded_fragment, _site_heading_slug(decoded_fragment)):
        if candidate in heading_ids:
            return candidate

    source_relative = source_path.relative_to(REPO_ROOT).as_posix()
    raise ValueError(
        f"{source_relative} links to missing heading {relative}#{decoded_fragment}; "
        "update the canonical target fragment"
    )


def _rewrite_target(target: str, source_path: Path, route_map: dict[str, str]) -> str:
    if target.startswith(("http://", "https://", "mailto:", "#")):
        return target

    clean_target = target.strip()
    target_path, separator, fragment = clean_target.partition("#")
    if not target_path:
        return target

    anchor = f"#{fragment}" if separator else ""
    resolved = (source_path.parent / unquote(target_path)).resolve()

    try:
        relative = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return target

    if relative in route_map:
        if not separator:
            return route_map[relative]
        route_fragment = _resolve_route_fragment(relative, fragment, source_path)
        return f"{route_map[relative]}#{quote(route_fragment, safe='-._~')}"

    if relative.startswith("docs/"):
        published_target = quote(relative.removeprefix("docs/"), safe="/")
        return published_target + anchor

    if resolved.exists():
        base_url = REPO_TREE_BASE if resolved.is_dir() else REPO_BLOB_BASE
        return f"{base_url}/{quote(relative, safe='/')}{anchor}"

    return target


def _rewrite_links(markdown: str, source_path: Path, route_map: dict[str, str]) -> str:
    def _replace(match: re.Match[str]) -> str:
        bang, label, target = match.groups()
        new_target = _rewrite_target(target, source_path, route_map)
        return f"{bang}[{label}]({new_target})"

    return LINK_PATTERN.sub(_replace, markdown)


def _render_page(slug: str, title: str, source_path: Path, route_map: dict[str, str]) -> str:
    raw = source_path.read_text(encoding="utf-8")
    rewritten = _rewrite_links(raw, source_path, route_map)
    header = (
        (
            f"<!-- Generated from {source_path.relative_to(REPO_ROOT).as_posix()} by scripts/build_docs_site.py -->\n"
            '<!-- markdownlint-configure-file {"MD051": false} -->\n'
            "<!-- markdownlint-disable MD051 -->\n\n"
        )
        if not rewritten.startswith("<!-- Generated")
        else ""
    )
    return header + rewritten


def _render_packaged_reference(source_path: Path, replacements: dict[str, str]) -> str:
    raw = source_path.read_text(encoding="utf-8")
    for old, new in replacements.items():
        raw = raw.replace(old, new)
    header = f"<!-- Synced from {source_path.relative_to(REPO_ROOT).as_posix()} by scripts/build_docs_site.py -->\n\n"
    return header + raw


def _normalize_generated_text(content: str) -> str:
    """Normalize generated docs content with stable LF endings and trimmed lines."""
    clean_lines = [line.rstrip() for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(clean_lines).rstrip("\n") + "\n"


def _write_text(path: Path, content: str) -> None:
    normalized = _normalize_generated_text(content)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(normalized)


def build_site() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    route_map = _route_map()
    embedded_content: dict[str, str] = {}

    for slug, title, source_path in PAGES:
        rendered = _normalize_generated_text(_render_page(slug, title, source_path, route_map))
        output_path = OUTPUT_DIR / f"{slug}.md"
        _write_text(output_path, rendered)
        embedded_content[slug] = rendered

    _write_text(
        EMBEDDED_CONTENT_FILE,
        "window.DOC_PAGE_CONTENT = " + json.dumps(embedded_content, ensure_ascii=False, indent=2) + ";\n",
    )

    for reference in PACKAGED_REFERENCES:
        target_path = reference["target"]
        target_path.parent.mkdir(parents=True, exist_ok=True)
        rendered = _normalize_generated_text(_render_packaged_reference(reference["source"], reference["replacements"]))
        _write_text(target_path, rendered)


if __name__ == "__main__":
    build_site()
    print(f"Generated docs site content in {OUTPUT_DIR}")
