"""Build GitHub Wiki Markdown pages from canonical repository docs.

The GitHub Wiki is a separate git repository. This script renders a curated
subset of canonical docs into wiki-friendly filenames and rewrites repository
relative links so the wiki remains useful outside the static docs site.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "build" / "github-wiki"
REPO_BLOB_BASE = "https://github.com/u9401066/pubmed-search-mcp/blob/master"
REPO_RAW_BASE = "https://raw.githubusercontent.com/u9401066/pubmed-search-mcp/master"
DOCS_SITE_URL = "https://u9401066.github.io/pubmed-search-mcp/"

LINK_PATTERN = re.compile(r"(!?)\[([^\]]+)\]\(([^)]+)\)")


@dataclass(frozen=True)
class WikiPage:
    """Canonical source rendered as one GitHub Wiki page."""

    slug: str
    title: str
    source: Path


PAGES: tuple[WikiPage, ...] = (
    WikiPage("User-Guide", "User Guide", DOCS_ROOT / "USER_GUIDE.md"),
    WikiPage("User-Guide.zh-TW", "使用者指南", DOCS_ROOT / "USER_GUIDE.zh-TW.md"),
    WikiPage(
        "Advanced-Research-Workflows", "Advanced Research Workflows", DOCS_ROOT / "ADVANCED_RESEARCH_WORKFLOWS.md"
    ),
    WikiPage(
        "Advanced-Research-Workflows.zh-TW",
        "進階研究工作流",
        DOCS_ROOT / "ADVANCED_RESEARCH_WORKFLOWS.zh-TW.md",
    ),
    WikiPage("Developer-Guide", "Developer Guide", DOCS_ROOT / "DEVELOPER_GUIDE.md"),
    WikiPage("Developer-Guide.zh-TW", "開發者指南", DOCS_ROOT / "DEVELOPER_GUIDE.zh-TW.md"),
    WikiPage("Tools-Usage-Guide", "Tools Usage Guide", DOCS_ROOT / "TOOLS_USAGE_GUIDE.md"),
    WikiPage("Tools-Usage-Guide.zh-TW", "工具使用指南", DOCS_ROOT / "TOOLS_USAGE_GUIDE.zh-TW.md"),
    WikiPage("Pipeline-Tutorial", "Pipeline Tutorial", DOCS_ROOT / "PIPELINE_MODE_TUTORIAL.en.md"),
    WikiPage("Pipeline-Tutorial.zh-TW", "Pipeline 教學", DOCS_ROOT / "PIPELINE_MODE_TUTORIAL.md"),
    WikiPage("Architecture", "Architecture", REPO_ROOT / "ARCHITECTURE.md"),
    WikiPage(
        "Quick-Reference", "Quick Reference", REPO_ROOT / "src/pubmed_search/presentation/mcp_server/TOOLS_INDEX.md"
    ),
    WikiPage("Source-Contracts", "Source Contracts", DOCS_ROOT / "SOURCE_CONTRACTS.md"),
    WikiPage("Troubleshooting", "Troubleshooting", DOCS_ROOT / "INTEGRATIONS.md"),
    WikiPage("Deployment", "Deployment", REPO_ROOT / "DEPLOYMENT.md"),
)


def _source_route_map() -> dict[str, str]:
    routes = {page.source.relative_to(REPO_ROOT).as_posix(): page.slug for page in PAGES}
    routes.update(
        {
            "README.md": f"{REPO_BLOB_BASE}/README.md",
            "README.zh-TW.md": f"{REPO_BLOB_BASE}/README.zh-TW.md",
            "docs/index.html": DOCS_SITE_URL,
        },
    )
    return routes


def _split_target(target: str) -> tuple[str, str]:
    if "#" not in target:
        return target, ""
    path, anchor = target.split("#", 1)
    return path, f"#{anchor}"


def _is_external_target(target: str) -> bool:
    return target.startswith(("http://", "https://", "mailto:", "#"))


def _rewrite_target(target: str, source_path: Path, route_map: dict[str, str], *, is_image: bool) -> str:
    if _is_external_target(target):
        return target

    clean_target, anchor = _split_target(target.strip())
    if not clean_target:
        return target

    resolved = (source_path.parent / clean_target).resolve()

    try:
        relative = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return target

    if relative in route_map:
        return route_map[relative] + anchor

    base_url = REPO_RAW_BASE if is_image else REPO_BLOB_BASE
    return f"{base_url}/{relative}{anchor}"


def _rewrite_links(markdown: str, source_path: Path, route_map: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        bang, label, target = match.groups()
        rewritten = _rewrite_target(target, source_path, route_map, is_image=bool(bang))
        return f"{bang}[{label}]({rewritten})"

    return LINK_PATTERN.sub(replace, markdown)


def _render_source_page(page: WikiPage, route_map: dict[str, str]) -> str:
    markdown = page.source.read_text(encoding="utf-8")
    rendered = _rewrite_links(markdown, page.source, route_map)
    header = (
        f"<!-- Generated from {page.source.relative_to(REPO_ROOT).as_posix()} by scripts/build_github_wiki.py -->\n"
        "<!-- Edit the canonical source doc, then regenerate this wiki page. -->\n\n"
    )
    return header + rendered


def _render_home() -> str:
    return f"""# PubMed Search MCP Wiki

This wiki is a GitHub-native mirror of the main documentation set. The full
interactive documentation site remains the preferred reading surface:

- **Docs Site**: {DOCS_SITE_URL}
- **Repository**: {REPO_BLOB_BASE.rsplit("/blob/master", maxsplit=1)[0]}

## Start Here

- [User Guide](User-Guide): practical workflows for search, PICO, full text, exports, local notes, and pipelines
- [使用者指南](User-Guide.zh-TW): 繁體中文使用者工作流
- [Advanced Research Workflows](Advanced-Research-Workflows): research timeline/chronicle, Open-i image search, uploaded-image handoff, and persistent query memory
- [進階研究工作流](Advanced-Research-Workflows.zh-TW): 研究脈絡時間軸、Open-i 圖片搜尋、上傳圖片 handoff、持久化 query memory
- [Developer Guide](Developer-Guide): DDD boundaries, tool registration, docs generation, validation, and release hygiene
- [開發者指南](Developer-Guide.zh-TW): 繁體中文開發者指南

## Reference Pages

- [Tools Usage Guide](Tools-Usage-Guide) / [工具使用指南](Tools-Usage-Guide.zh-TW)
- [Pipeline Tutorial](Pipeline-Tutorial) / [Pipeline 教學](Pipeline-Tutorial.zh-TW)
- [Architecture](Architecture)
- [Quick Reference](Quick-Reference)
- [Source Contracts](Source-Contracts)
- [Troubleshooting](Troubleshooting)
- [Deployment](Deployment)

## Maintenance

These pages are generated from canonical Markdown files in the repository.
Update the source docs first, then run:

```bash
uv run python scripts/build_github_wiki.py --output /path/to/wiki
```
"""


def _render_sidebar() -> str:
    return f"""# PubMed Search MCP

- [Home](Home)
- [Docs Site]({DOCS_SITE_URL})

## Users

- [User Guide](User-Guide)
- [使用者指南](User-Guide.zh-TW)
- [Advanced Research Workflows](Advanced-Research-Workflows)
- [進階研究工作流](Advanced-Research-Workflows.zh-TW)
- [Tools Usage Guide](Tools-Usage-Guide)
- [工具使用指南](Tools-Usage-Guide.zh-TW)
- [Pipeline Tutorial](Pipeline-Tutorial)
- [Pipeline 教學](Pipeline-Tutorial.zh-TW)

## Developers

- [Developer Guide](Developer-Guide)
- [開發者指南](Developer-Guide.zh-TW)
- [Architecture](Architecture)
- [Source Contracts](Source-Contracts)
- [Quick Reference](Quick-Reference)

## Operations

- [Troubleshooting](Troubleshooting)
- [Deployment](Deployment)
"""


def _write_text(path: Path, content: str) -> None:
    clean_lines = [line.rstrip() for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    normalized = "\n".join(clean_lines).rstrip("\n") + "\n"
    path.write_text(normalized, encoding="utf-8", newline="")


def build_wiki(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    route_map = _source_route_map()

    _write_text(output_dir / "Home.md", _render_home())
    _write_text(output_dir / "_Sidebar.md", _render_sidebar())

    for page in PAGES:
        _write_text(output_dir / f"{page.slug}.md", _render_source_page(page, route_map))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build GitHub Wiki pages from canonical docs.")
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory to write wiki markdown files."
    )
    args = parser.parse_args()

    build_wiki(args.output)
    print(f"Generated GitHub Wiki pages in {args.output}")


if __name__ == "__main__":
    main()
