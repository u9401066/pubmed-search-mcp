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
from pathlib import Path
from typing import TypedDict

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
OUTPUT_DIR = DOCS_ROOT / "site-content"
EMBEDDED_CONTENT_FILE = DOCS_ROOT / "site-content.js"

PAGES = [
    ("overview", "Overview", REPO_ROOT / "README.md"),
    ("overview-zh", "Overview (zh-TW)", REPO_ROOT / "README.zh-TW.md"),
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
    ("troubleshooting", "Troubleshooting", DOCS_ROOT / "INTEGRATIONS.md"),
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
        },
    },
    {
        "source": DOCS_ROOT / "PIPELINE_MODE_TUTORIAL.md",
        "target": REPO_ROOT / ".claude/skills/pipeline-persistence/references/pipeline-tutorial.zh-TW.md",
        "replacements": {
            "PIPELINE_MODE_TUTORIAL.en.md": "pipeline-tutorial.md",
        },
    },
]

LINK_PATTERN = re.compile(r"(!?)\[([^\]]+)\]\(([^)]+)\)")


def _route_map() -> dict[str, str]:
    return {source.relative_to(REPO_ROOT).as_posix(): f"#/{slug}" for slug, _title, source in PAGES}


def _rewrite_target(target: str, source_path: Path, route_map: dict[str, str]) -> str:
    if target.startswith(("http://", "https://", "mailto:", "#")):
        return target

    clean_target = target.strip()
    resolved = (source_path.parent / clean_target).resolve()

    try:
        relative = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return target

    if relative in route_map:
        return route_map[relative]

    if relative.startswith("docs/"):
        return relative.removeprefix("docs/")

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
            "<!-- markdownlint-configure-file {\"MD051\": false} -->\n"
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


def _write_text(path: Path, content: str) -> None:
    """Write generated docs files with stable LF endings and trimmed lines."""
    clean_lines = [line.rstrip() for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    normalized = "\n".join(clean_lines).rstrip("\n") + "\n"
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(normalized)


def build_site() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    route_map = _route_map()
    embedded_content: dict[str, str] = {}

    for slug, title, source_path in PAGES:
        rendered = _render_page(slug, title, source_path, route_map)
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
        rendered = _render_packaged_reference(reference["source"], reference["replacements"])
        _write_text(target_path, rendered)


if __name__ == "__main__":
    build_site()
    print(f"Generated docs site content in {OUTPUT_DIR}")
