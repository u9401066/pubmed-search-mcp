from __future__ import annotations

from pathlib import Path

import tomllib


def test_package_exposes_http_server_entrypoint() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    scripts = pyproject["project"]["scripts"]

    assert scripts["pubmed-search-mcp"] == "pubmed_search.presentation.mcp_server:main"
    assert scripts["pubmed-search-mcp-http"] == "pubmed_search.presentation.mcp_server.http_cli:main"


def test_dockerfile_uses_packaged_http_entrypoint() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert '"pubmed-search-mcp-http"' in dockerfile
    assert '"run_server.py"' not in dockerfile
