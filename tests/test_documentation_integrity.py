from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.10 CI job
    import tomli as tomllib
import yaml
from defusedxml import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_DOCS = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "README.zh-TW.md",
    REPO_ROOT / "ARCHITECTURE.md",
    REPO_ROOT / "DEPLOYMENT.md",
    REPO_ROOT / "ROADMAP.md",
    REPO_ROOT / "docs/INTEGRATIONS.md",
    REPO_ROOT / "docs/COPILOT_HOOKS_PIPELINE_ENFORCEMENT.md",
    REPO_ROOT / "docs/REPO_SEPARATION_PRINCIPLES.md",
    REPO_ROOT / "docs/TOOLS_USAGE_GUIDE.md",
    REPO_ROOT / "docs/TOOLS_USAGE_GUIDE.zh-TW.md",
    REPO_ROOT / "copilot-studio/README.md",
)
MERMAID_DOCS = (
    REPO_ROOT / "ARCHITECTURE.md",
    REPO_ROOT / "DEPLOYMENT.md",
    REPO_ROOT / "copilot-studio/README.md",
)
LINK_PATTERN = re.compile(r"!?(?:\[[^\]]*\])\(([^)]+)\)")
FENCED_CODE_PATTERN = re.compile(r"^```.*?^```\s*$", re.MULTILINE | re.DOTALL)
INLINE_CODE_PATTERN = re.compile(r"`[^`\n]*`")
MERMAID_PATTERN = re.compile(r"^```mermaid\s*\n(.*?)^```\s*$", re.MULTILINE | re.DOTALL)


def _prose(markdown: str) -> str:
    return INLINE_CODE_PATTERN.sub("", FENCED_CODE_PATTERN.sub("", markdown))


def test_active_documentation_local_links_resolve() -> None:
    missing: list[str] = []

    for document in ACTIVE_DOCS:
        markdown = _prose(document.read_text(encoding="utf-8"))
        for raw_target in LINK_PATTERN.findall(markdown):
            target = raw_target.strip().strip("<>")
            if target.startswith(("#", "http://", "https://", "mailto:", "data:")):
                continue
            path_text = unquote(target.split("#", 1)[0].split("?", 1)[0]).strip()
            if not path_text:
                continue
            candidate = (document.parent / path_text).resolve()
            if not candidate.is_relative_to(REPO_ROOT) or not candidate.exists():
                missing.append(f"{document.relative_to(REPO_ROOT)} -> {raw_target}")

    assert missing == []


def test_documentation_svgs_are_accessible_valid_xml() -> None:
    svg_files = sorted((REPO_ROOT / "docs/images").glob("*.svg"))
    assert svg_files

    for svg_file in svg_files:
        root = ElementTree.parse(svg_file).getroot()
        children = {child.tag.rsplit("}", 1)[-1]: child for child in root}
        ids = {element.get("id") for element in root.iter() if element.get("id")}

        assert root.tag.endswith("svg"), svg_file
        assert root.get("viewBox"), svg_file
        assert root.get("role") == "img", svg_file
        assert children.get("title") is not None, svg_file
        assert children.get("desc") is not None, svg_file
        assert set((root.get("aria-labelledby") or "").split()) <= ids, svg_file
        assert not any(element.tag.endswith("foreignObject") for element in root.iter()), svg_file


def test_active_mermaid_fences_have_supported_headers_and_current_tools() -> None:
    allowed_headers = (
        "flowchart ",
        "graph ",
        "sequenceDiagram",
        "classDiagram",
        "stateDiagram",
        "erDiagram",
        "gantt",
        "journey",
        "mindmap",
        "timeline",
    )

    for document in MERMAID_DOCS:
        markdown = document.read_text(encoding="utf-8")
        blocks = MERMAID_PATTERN.findall(markdown)
        assert markdown.count("```mermaid") == len(blocks), document
        for block in blocks:
            first_line = next(line.strip() for line in block.splitlines() if line.strip())
            assert first_line.startswith(allowed_headers), f"{document}: {first_line}"
            assert "compare_timelines" not in block
            assert "build_research_timeline" not in block
            assert "analyze_timeline_milestones" not in block


def test_release_and_tool_metadata_stay_synchronized() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_version = pyproject["project"]["version"]
    uv_lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    citation = yaml.safe_load((REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    init_text = (REPO_ROOT / "src/pubmed_search/__init__.py").read_text(encoding="utf-8")
    init_version = re.search(r'^__version__\s*=\s*"([^"]+)"', init_text, re.MULTILINE)
    openapi = yaml.safe_load((REPO_ROOT / "copilot-studio/openapi-schema.yaml").read_text(encoding="utf-8"))
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert init_version
    assert init_version.group(1) == package_version == openapi["info"]["version"]
    root_package = next(package for package in uv_lock["package"] if package["name"] == "pubmed-search-mcp")
    assert root_package["version"] == package_version
    assert citation["version"] == package_version
    assert citation["preferred-citation"]["version"] == package_version
    assert f'org.opencontainers.image.version="{package_version}"' in dockerfile
    assert f"## [{package_version}]" in changelog
    assert "BearerAuth" in openapi["securityDefinitions"]

    current_surfaces = (
        *ACTIVE_DOCS[:4],
        REPO_ROOT / "docs/INTEGRATIONS.md",
        REPO_ROOT / "copilot-studio/README.md",
        REPO_ROOT / "docs/images/integration-deployment-workflow.svg",
        REPO_ROOT / "docs/images/copilot-studio-deployment-flow.svg",
    )
    stale_tool_count = re.compile(r"\b46(?: tools?|-tool)|46 \u500b")
    assert [path for path in current_surfaces if stale_tool_count.search(path.read_text(encoding="utf-8"))] == []

    skill_count = len(tuple((REPO_ROOT / ".claude/skills").glob("*/SKILL.md")))
    assert skill_count == 26
    assert f"**{skill_count} Claude Skills**" in (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert f"**{skill_count} 個 Claude Skills**" in (REPO_ROOT / "README.zh-TW.md").read_text(encoding="utf-8")

    ci_workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "run_live_integrations" in ci_workflow
    assert 'PUBMED_RUN_LIVE_TESTS: "1"' in ci_workflow
    assert "pytest -q -m integration -rs" in ci_workflow


def test_docs_site_dependencies_and_rendering_are_hardened() -> None:
    index_html = (REPO_ROOT / "docs/index.html").read_text(encoding="utf-8")
    site_js = (REPO_ROOT / "docs/site.js").read_text(encoding="utf-8")

    assert "marked@18.0.7" in index_html
    assert "dompurify@3.4.12" in index_html
    assert "mermaid@11.16.1" in index_html
    assert index_html.count('integrity="sha384-') == 3
    assert "Content-Security-Policy" in index_html
    assert "window.DOMPurify.sanitize" in site_js
    assert 'securityLevel: "strict"' in site_js
    assert 'securityLevel: "loose"' not in site_js


def test_compose_profiles_and_nginx_keep_runtime_boundaries_explicit() -> None:
    local_compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    service_compose = yaml.safe_load((REPO_ROOT / "docker-compose.service.yml").read_text(encoding="utf-8"))
    https_compose = yaml.safe_load((REPO_ROOT / "docker-compose.https.yml").read_text(encoding="utf-8"))
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    nginx = (REPO_ROOT / "nginx/nginx.conf").read_text(encoding="utf-8")

    local = local_compose["services"]["pubmed-mcp"]
    service = service_compose["services"]["pubmed-mcp"]
    assert local["ports"] == ["127.0.0.1:${PUBMED_LOCAL_PORT:-8765}:8765"]
    assert local["environment"]["PUBMED_SERVER_MODE"] == "local"
    assert local["environment"]["PUBMED_LOCAL_ALLOW_CONTAINER_BIND"] == "1"
    assert service["environment"]["PUBMED_SERVER_MODE"] == "service"
    assert "PUBMED_AUTH_TOKENS" in service["environment"]
    assert service["deploy"]["replicas"] == 1
    assert "/var/lib/pubmed-search-mcp" in service["volumes"][0]
    service_probe = " ".join(service["healthcheck"]["test"])
    assert "Host: $$health_host" in service_probe
    assert "PUBMED_ALLOWED_HOSTS%%,*" in service_probe
    assert https_compose["services"]["nginx"]["image"].startswith("nginx:1.31.3-alpine@sha256:")
    assert "python:3.11.15-slim-trixie@sha256:" in dockerfile
    assert "ghcr.io/astral-sh/uv:0.11.24" in dockerfile
    assert "USER pubmed" in dockerfile
    assert "PUBMED_DATA_DIR=/var/lib/pubmed-search-mcp" in dockerfile
    assert "location = /ready" in nginx
    assert "proxy_buffering off" in nginx
    assert "proxy_request_buffering off" in nginx


def test_runtime_docs_keep_local_http_durable_and_service_fail_closed() -> None:
    snippets_by_path = {
        REPO_ROOT / "README.md": [
            "Trusted single-user",
            "durable `default` tenant",
            "fails closed without a bearer principal",
        ],
        REPO_ROOT / "README.zh-TW.md": [
            "可信單使用者",
            "durable `default` tenant",
            "fail closed",
        ],
        REPO_ROOT / "ARCHITECTURE.md": [
            "跨 request 共用 durable `default` tenant",
            "匿名 service request 會 fail closed",
        ],
        REPO_ROOT / "DEPLOYMENT.md": [
            "單使用者 durable `default` tenant",
            "| service anonymous |",
        ],
        REPO_ROOT / "docs/INTEGRATIONS.md": [
            "trusted single-user contract",
            "anonymous request is always rejected",
        ],
    }

    for path, snippets in snippets_by_path.items():
        content = path.read_text(encoding="utf-8")
        assert "anonymous_http" not in content
        assert "request-scoped" not in content
        for snippet in snippets:
            assert snippet in content, f"{path} is missing {snippet!r}"

    deployment = (REPO_ROOT / "DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "可完成 MCP initialize" not in deployment
    assert "不再送 `initialize` 或 `Mcp-Session-Id`" in deployment

    paper_draft = (REPO_ROOT / "docs/paper-draft.md").read_text(encoding="utf-8")
    assert "35+ MCP" not in paper_draft
    assert "45 MCP tools" in paper_draft


def test_runtime_docs_explain_mcp_v2_and_service_filesystem_boundaries() -> None:
    snippets_by_path = {
        REPO_ROOT / "README.md": [
            "Modern 2026-07-28 clients",
            "cannot load `file:` pipelines",
            "service Compose scheduler is",
        ],
        REPO_ROOT / "README.zh-TW.md": [
            "現代 2026-07-28 client",
            "不能載入 `file:` pipeline",
            "service Compose",
        ],
        REPO_ROOT / "DEPLOYMENT.md": [
            "不使用 `initialize` handshake",
            "拒絕 server-host `file:` read",
            "Service Compose 停用",
        ],
        REPO_ROOT / "docs/INTEGRATIONS.md": [
            "MCP SDK v2 Protocol Baseline",
            "Authenticated service callers cannot read `file:` paths",
            "cannot choose `output_dir` or `template_file`",
        ],
        REPO_ROOT / "docs/USER_GUIDE.md": [
            "authenticated service caller cannot select a server-host path",
            "tenant-derived saved-pipeline store",
            "single external leader/lease",
        ],
        REPO_ROOT / "docs/USER_GUIDE.zh-TW.md": [
            "caller 不能選擇 server host path",
            "process-wide workspace path",
            "單一 external leader/lease",
        ],
    }

    for path, snippets in snippets_by_path.items():
        content = path.read_text(encoding="utf-8")
        for snippet in snippets:
            assert snippet in content, f"{path} is missing {snippet!r}"

    sdk_design = (REPO_ROOT / "docs/PYTHON_SDK_AND_HTTP_CLI_DESIGN.md").read_text(encoding="utf-8")
    assert "MCP SDK v2 `MCPServer`" in sdk_design
    assert "FastMCP" not in sdk_design

    paper = (REPO_ROOT / "docs/arxiv-paper/main.tex").read_text(encoding="utf-8")
    assert "45 MCP tools organized into 16 registry categories" in paper
    assert "MCP SDK v2 \\texttt{MCPServer}" in paper
    assert "With 40 MCP tools" not in paper


def test_public_copilot_docs_require_service_auth_and_keep_simplified_mode_local() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    readme_zh = (REPO_ROOT / "README.zh-TW.md").read_text(encoding="utf-8")
    integrations = (REPO_ROOT / "docs/INTEGRATIONS.md").read_text(encoding="utf-8")
    copilot = (REPO_ROOT / "copilot-studio/README.md").read_text(encoding="utf-8")
    openapi = (REPO_ROOT / "copilot-studio/openapi-schema.yaml").read_text(encoding="utf-8")
    architecture = (REPO_ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    deployment = (REPO_ROOT / "DEPLOYMENT.md").read_text(encoding="utf-8")

    for content in (readme, readme_zh, integrations, copilot):
        assert "PUBMED_AUTH_TOKENS" in content
        assert "NGROK_DOMAIN" in content
        assert "start-copilot-studio.sh --with-ngrok" in content

    assert "Both tunnel scripts converge on the same fail-closed `--mode service` launcher" in integrations
    assert "must not be tunneled" in integrations
    assert "temporary ngrok URL" not in integrations
    assert "禁止放到 ngrok" in copilot
    assert "Simple --> Tunnel" not in copilot
    assert "--mode service" in architecture
    assert "loopback-only and is not a\n        valid deployment target" in openapi
    assert "ghcr.io/u9401066/pubmed-search-mcp" not in deployment
