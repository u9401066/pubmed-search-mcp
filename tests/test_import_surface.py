from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"


def _probe(code: str) -> dict[str, Any]:
    env = os.environ.copy()
    pythonpath = str(SRC_ROOT)
    if env.get("PYTHONPATH"):
        pythonpath = f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
    env["PYTHONPATH"] = pythonpath

    output = subprocess.check_output(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        text=True,
    )
    return json.loads(output)


def test_root_import_keeps_heavy_surfaces_lazy() -> None:
    result = _probe(
        """
import json
import sys

import pubmed_search

watched = [
    "httpx",
    "mcp",
    "pylatexenc",
    "pubmed_search.presentation.mcp_server.server",
    "pubmed_search.presentation.mcp_server.tools.unified",
    "yaml",
]
print(json.dumps({
    "version": pubmed_search.__version__,
    "exports": list(pubmed_search.__all__),
    "loaded": {name: name in sys.modules for name in watched},
}))
"""
    )

    assert result["version"].count(".") >= 1
    assert "LiteratureSearcher" in result["exports"]
    assert not any(result["loaded"].values()), result["loaded"]


def test_core_search_export_does_not_import_mcp_surface() -> None:
    result = _probe(
        """
import json
import sys

from pubmed_search import LiteratureSearcher

watched = [
    "httpx",
    "mcp",
    "pydantic_settings",
    "pubmed_search.infrastructure.ncbi.citation_exporter",
    "pubmed_search.presentation.mcp_server.server",
    "pubmed_search.presentation.mcp_server.tools.unified",
    "pubmed_search.shared.settings",
    "yaml",
]
print(json.dumps({
    "callable": callable(LiteratureSearcher),
    "loaded": {name: name in sys.modules for name in watched},
}))
"""
    )

    assert result["callable"] is True
    assert not any(result["loaded"].values()), result["loaded"]


def test_import_surface_audit_scans_only_source_test_and_script_roots() -> None:
    audit_path = REPO_ROOT / "scripts" / "perf" / "import_surface_audit.py"
    spec = importlib.util.spec_from_file_location("import_surface_audit", audit_path)
    assert spec and spec.loader
    audit = importlib.util.module_from_spec(spec)
    sys.modules["import_surface_audit"] = audit
    spec.loader.exec_module(audit)

    paths = audit._iter_python_files()
    rels = [path.relative_to(REPO_ROOT).as_posix() for path in paths]

    assert paths
    assert len(paths) < 1000
    assert all(rel.startswith(("src/", "tests/", "scripts/")) for rel in rels)
    assert not any(rel.startswith(("data/", "dist/", "scripts/_tmp/")) or "/.uv-cache/" in rel for rel in rels)


def test_tool_package_import_does_not_import_all_tool_categories() -> None:
    result = _probe(
        """
import json
import sys

import pubmed_search.presentation.mcp_server.tools as tools

before = "pubmed_search.presentation.mcp_server.tools.unified" in sys.modules
registrar = tools.register_unified_search_tools
after = "pubmed_search.presentation.mcp_server.tools.unified" in sys.modules

print(json.dumps({
    "before": before,
    "after": after,
    "callable": callable(registrar),
}))
"""
    )

    assert result == {"before": False, "after": True, "callable": True}


def test_query_analyzer_import_stays_local() -> None:
    result = _probe(
        """
import json
import sys

from pubmed_search import QueryAnalyzer

watched = [
    "httpx",
    "pydantic_settings",
    "pubmed_search.application.search.semantic_enhancer",
    "pubmed_search.infrastructure.sources",
    "pubmed_search.shared.settings",
]
print(json.dumps({
    "callable": callable(QueryAnalyzer),
    "loaded": {name: name in sys.modules for name in watched},
}))
"""
    )

    assert result["callable"] is True
    assert not any(result["loaded"].values()), result["loaded"]


def test_source_factory_import_defers_settings_and_clients() -> None:
    result = _probe(
        """
import json
import sys

from pubmed_search import get_semantic_scholar_client

watched = [
    "httpx",
    "pydantic_settings",
    "pubmed_search.infrastructure.sources.core",
    "pubmed_search.infrastructure.sources.crossref",
    "pubmed_search.infrastructure.sources.europe_pmc",
    "pubmed_search.infrastructure.sources.openalex",
    "pubmed_search.infrastructure.sources.registry",
    "pubmed_search.infrastructure.sources.unpaywall",
    "pubmed_search.shared.settings",
]
print(json.dumps({
    "callable": callable(get_semantic_scholar_client),
    "loaded": {name: name in sys.modules for name in watched},
}))
"""
    )

    assert result["callable"] is True
    assert not any(result["loaded"].values()), result["loaded"]


def test_export_tool_import_defers_official_citation_and_settings() -> None:
    result = _probe(
        """
import json
import sys

import pubmed_search.presentation.mcp_server.tools.export as export_tool

watched = [
    "httpx",
    "pydantic_settings",
    "pubmed_search.application.search",
    "pubmed_search.infrastructure.ncbi.citation_exporter",
    "pubmed_search.shared.settings",
    "pylatexenc",
    "yaml",
]
print(json.dumps({
    "callable": callable(export_tool.register_export_tools),
    "loaded": {name: name in sys.modules for name in watched},
}))
"""
    )

    assert result["callable"] is True
    assert not any(result["loaded"].values()), result["loaded"]


def test_public_api_import_keeps_mcp_and_http_lazy() -> None:
    result = _probe(
        """
import json
import sys

from pubmed_search.api import PubMedSearchClient, PubMedSearchConfig

watched = [
    "httpx",
    "mcp",
    "pydantic_settings",
    "pubmed_search.presentation.mcp_server.server",
    "pubmed_search.presentation.mcp_server.tools.unified",
    "pubmed_search.presentation.mcp_server.tools.unified_runner",
    "pubmed_search.shared.settings",
    "yaml",
]
print(json.dumps({
    "client": PubMedSearchClient.__name__,
    "config": PubMedSearchConfig.__name__,
    "loaded": {name: name in sys.modules for name in watched},
}))
"""
    )

    assert result["client"] == "PubMedSearchClient"
    assert result["config"] == "PubMedSearchConfig"
    assert not any(result["loaded"].values()), result["loaded"]
