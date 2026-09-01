"""Acceptance-test every public tool through real MCP transports."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE_SERVER = ROOT / "tests" / "fixtures" / "all_tools_mcp_server.py"
PRIMARY_PMID = "12345678"
SEARCH_PMID = "42424242"
PASSTHROUGH_ENV_KEYS = frozenset(
    {
        "COMSPEC",
        "DYLD_LIBRARY_PATH",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LD_LIBRARY_PATH",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "TZ",
        "USERPROFILE",
        "WINDIR",
    }
)

EXPECTED_TOOLS = frozenset(
    {
        "unified_search",
        "validate_pico_plan",
        "generate_search_queries",
        "analyze_search_query",
        "fetch_article_details",
        "find_related_articles",
        "find_citing_articles",
        "get_article_references",
        "get_citation_metrics",
        "verify_reference_list",
        "get_fulltext",
        "get_text_mined_terms",
        "get_article_figures",
        "search_gene",
        "get_gene_details",
        "get_gene_literature",
        "search_compound",
        "get_compound_details",
        "get_compound_literature",
        "search_clinvar",
        "build_citation_tree",
        "prepare_export",
        "save_literature_notes",
        "read_session",
        "configure_institutional_access",
        "get_institutional_link",
        "list_resolver_presets",
        "test_institutional_access",
        "diagnose_institutional_access",
        "prepare_figure_search",
        "convert_icd_mesh",
        "build_research_chronicle",
        "read_research_chronicle",
        "search_biomedical_images",
        "save_pipeline",
        "list_pipelines",
        "load_pipeline",
        "delete_pipeline",
        "get_pipeline_history",
        "schedule_pipeline",
        "unschedule_pipeline",
    }
)

PIPELINE_CONFIG = """\
steps:
  - id: search
    action: search
    params:
      query: offline pipeline
      sources: [pubmed]
      limit: 1
output:
  format: json
  limit: 1
  ranking: balanced
"""

PNG_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
EXPECTED_PROTOCOL_CALLS_PER_RUN = 60
RETIRED_TOOLS = frozenset(
    {
        "analyze_figure_for_search",
        "build_research_timeline",
        "get_cached_article",
        "get_session_log",
        "get_session_pmids",
        "get_session_summary",
        "manage_pipeline",
        "merge_search_results",
        "parse_pico",
    }
)


def _acceptance_env(root: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key in PASSTHROUGH_ENV_KEYS}
    env.update(
        {
            "NCBI_EMAIL": "offline-acceptance@example.com",
            "PUBMED_DATA_DIR": str(root / "data"),
            "PUBMED_WORKSPACE_DIR": str(root / "workspace"),
            "PUBMED_NOTES_DIR": str(root / "notes"),
            "PUBMED_SCHEDULER_ENABLED": "true",
            "PUBMED_SCHEDULER_TIMEZONE": "UTC",
            "PUBMED_AUTH_REQUIRED": "false",
            "PUBMED_AUTH_TOKENS": "",
            "PUBMED_SERVER_MODE": "local",
            "INSTITUTIONAL_DIRECT_FETCH": "false",
            "MCP_ACCEPTANCE_NETWORK_SENTINEL": str(root / "unexpected-external-network.txt"),
            "MCP_ACCEPTANCE_NETWORK_GUARD_MARKER": str(root / "network-guard-armed.txt"),
            "OPENURL_RESOLVER": "",
            "OPENURL_PRESET": "",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )
    return env


def test_acceptance_child_environment_is_hermetic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    polluted = {
        "CLINICALKEY_AI_ENABLED": "definitely-not-a-bool",
        "HTTP_PROXY": "http://invalid.example:9999",
        "PUBMED_ALLOWED_HOSTS": "example.com",
        "PUBMED_SEARCH_DISABLED_SOURCES": "pubmed",
        "PYTHONPATH": str(tmp_path / "shadow-imports"),
    }
    for key, value in polluted.items():
        monkeypatch.setenv(key, value)

    child_env = _acceptance_env(tmp_path / "child")

    assert not polluted.keys() & child_env.keys()
    assert child_env["PUBMED_AUTH_REQUIRED"] == "false"
    assert child_env["NO_PROXY"] == "127.0.0.1,localhost"


def _result_text(result: Any) -> str:
    return "\n".join(block.text for block in result.content if hasattr(block, "text"))


def _assert_no_external_network(root: Path) -> None:
    marker = root / "network-guard-armed.txt"
    assert marker.read_text(encoding="utf-8") == "dns-connect-connect_ex-guard-armed"
    sentinel = root / "unexpected-external-network.txt"
    assert not sentinel.exists(), sentinel.read_text(encoding="utf-8", errors="replace") if sentinel.exists() else ""


def _json_document(text: str) -> Any:
    marker = "\n---\n## Persistent Artifact\n"
    document, separator, artifact_note = text.partition(marker)
    if separator:
        assert "- Artifact ID: `" in artifact_note
        assert "- URI: `artifact://" in artifact_note
    try:
        return json.loads(document.strip())
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Response was not one complete JSON document: {text[:500]}") from exc


def _path_value(payload: Any, path: str) -> Any:
    value = payload
    for component in path.split("."):
        value = value[int(component)] if isinstance(value, list) else value[component]
    return value


def _expect_json(expected: dict[str, Any]) -> Callable[[Any], None]:
    def validate(result: Any) -> None:
        payload = _json_document(_result_text(result))
        for path, expected_value in expected.items():
            assert _path_value(payload, path) == expected_value, path

    return validate


def _contains(*markers: str) -> Callable[[Any], None]:
    def validate(result: Any) -> None:
        text = _result_text(result)
        for marker in markers:
            assert marker in text

    return validate


def _render_with_pinned_mermaid_if_configured(source: str, scratch: Path, label: str) -> None:
    node_modules = os.environ.get("MERMAID_NODE_MODULES", "").strip()
    required = os.environ.get("MCP_ACCEPTANCE_REQUIRE_MERMAID_RENDER") == "1"
    if not node_modules:
        assert not required, "MERMAID_NODE_MODULES is required for the MCP Mermaid render gate"
        return
    node = shutil.which("node")
    assert node is not None, "node is required for the MCP Mermaid render gate"
    render_dir = scratch / "actual-mcp-mermaid"
    render_dir.mkdir(parents=True, exist_ok=True)
    source_path = render_dir / f"{label}.mmd"
    source_path.write_text(source, encoding="utf-8")
    node_env = {key: value for key, value in os.environ.items() if key in PASSTHROUGH_ENV_KEYS}
    node_env["MERMAID_NODE_MODULES"] = node_modules
    completed = subprocess.run(
        [node, str(ROOT / "scripts" / "check_mermaid_rendering.mjs"), str(source_path)],
        cwd=ROOT,
        env=node_env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "rendered to SVG" in completed.stdout


@dataclass
class AcceptanceDriver:
    client: Client[Any]
    called_tools: set[str] = field(default_factory=set)
    failures: list[str] = field(default_factory=list)
    call_count: int = 0

    async def call(
        self,
        name: str,
        arguments: dict[str, Any],
        validate: Callable[[Any], None],
    ) -> Any | None:
        self.called_tools.add(name)
        self.call_count += 1
        try:
            result = await self.client.call_tool(name, arguments)
            assert result.is_error is False, _result_text(result)
            assert result.content, "MCP result contained no content blocks"
            validate(result)
        except Exception as exc:
            self.failures.append(f"{name}: {type(exc).__name__}: {exc}")
            return None
        return result

    def finish(self, listed_tools: set[str]) -> None:
        if self.call_count != EXPECTED_PROTOCOL_CALLS_PER_RUN:
            self.failures.append(
                f"protocol call-count mismatch: expected={EXPECTED_PROTOCOL_CALLS_PER_RUN}, actual={self.call_count}"
            )
        if self.called_tools != EXPECTED_TOOLS:
            self.failures.append(
                "acceptance manifest mismatch: "
                f"missing={sorted(EXPECTED_TOOLS - self.called_tools)}, "
                f"extra={sorted(self.called_tools - EXPECTED_TOOLS)}"
            )
        if listed_tools != EXPECTED_TOOLS:
            self.failures.append(
                "runtime registry mismatch: "
                f"missing={sorted(EXPECTED_TOOLS - listed_tools)}, "
                f"extra={sorted(listed_tools - EXPECTED_TOOLS)}"
            )
        assert not self.failures, "MCP acceptance failures:\n- " + "\n- ".join(self.failures)


async def _exercise_all_tools(client: Client[Any], scratch: Path) -> None:
    listed = await client.list_tools()
    listed_tools = {tool.name for tool in listed.tools}
    driver = AcceptanceDriver(client)
    assert len(listed.tools) == len(EXPECTED_TOOLS)
    assert all(tool.description for tool in listed.tools)
    assert all(tool.annotations is not None for tool in listed.tools)
    assert all(tool.input_schema.get("additionalProperties") is False for tool in listed.tools)
    assert all((tool.meta or {}).get("pubmed-search", {}).get("contractVersion") == 3 for tool in listed.tools)

    unified = await driver.call(
        "unified_search",
        {
            "query": "offline acceptance",
            "sources": "pubmed",
            "limit": 1,
            "output_format": "json",
            "options": "shallow,no_oa,no_relax,no_analysis,no_scores,no_next",
        },
        _expect_json(
            {
                "articles.0.identifiers.pmid": SEARCH_PMID,
                "source_counts.0.source": "pubmed",
                "source_counts.0.returned": 1,
            }
        ),
    )
    run_id = ""
    artifact_uri = ""
    if unified is not None:
        payload = _json_document(_result_text(unified))
        run_id = str(payload.get("search_run", {}).get("run_id") or "")
        artifact_uri = str(payload.get("artifact_summary", {}).get("artifact_uri") or "")
    if not run_id:
        driver.failures.append("unified_search: response omitted durable search_run.run_id")
    if not artifact_uri.startswith("artifact://"):
        driver.failures.append("unified_search: response omitted a valid artifact_summary.artifact_uri")

    def validate_pico_handoff(result: Any) -> None:
        payload = _json_document(_result_text(result))
        assert payload["source"] == "agent_provided"
        assert payload["requires_agent_extraction"] is False
        assert payload["validation"]["valid"] is True
        assert payload["pico"] == {
            "P": "ICU adults",
            "I": "remimazolam",
            "C": "propofol",
            "O": "sedation quality",
        }
        assert payload["question_type"] == "therapy"
        assert payload["profile"] == "balanced"
        assert payload["sources"] == ["pubmed"]
        assert payload["next_tool"] == "unified_search"
        assert payload["next_tool_call"]["tool"] == "unified_search"
        assert payload["next_tool_call"]["args"]["query"] == "ICU sedation comparison"
        pipeline = payload["pipeline"]
        assert payload["next_tool_call"]["args"]["pipeline"] == pipeline
        for marker in (
            "template: pico",
            'P: "ICU adults"',
            'I: "remimazolam"',
            'C: "propofol"',
            'O: "sedation quality"',
            'question_type: "therapy"',
            'profile: "balanced"',
            'sources: ["pubmed"]',
            "limit: 10",
        ):
            assert marker in pipeline

    await driver.call(
        "validate_pico_plan",
        {
            "description": "ICU sedation comparison",
            "p": "ICU adults",
            "i": "remimazolam",
            "c": "propofol",
            "o": "sedation quality",
            "question_type": "therapy",
            "profile": "balanced",
            "sources": ["pubmed"],
            "limit": 10,
        },
        validate_pico_handoff,
    )
    await driver.call(
        "generate_search_queries",
        {
            "topic": "remimazolam",
            "strategy": "comprehensive",
            "check_spelling": True,
            "include_suggestions": True,
        },
        _expect_json({"status": "success", "topic": "remimazolam", "mesh_terms.0.preferred": "Remimazolam"}),
    )
    await driver.call(
        "analyze_search_query",
        {"query": "remimazolam ICU sedation"},
        _contains("Query Analysis", "Classification", "Dispatch Strategy", "remimazolam ICU sedation"),
    )

    await driver.call(
        "fetch_article_details",
        {"pmids": PRIMARY_PMID, "output_format": "json"},
        _expect_json(
            {
                "tool": "fetch_article_details",
                "article_count": 1,
                "articles.0.pmid": PRIMARY_PMID,
                "source_counts.0.returned": 1,
            }
        ),
    )
    await driver.call(
        "find_related_articles",
        {"pmid": PRIMARY_PMID, "limit": 1},
        _contains(f"Related Articles for PMID {PRIMARY_PMID}", "Related Paper", "23456789"),
    )
    await driver.call(
        "find_citing_articles",
        {"pmid": PRIMARY_PMID, "limit": 1},
        _contains(f"Articles Citing PMID {PRIMARY_PMID}", "Citing Paper 2", "34567890"),
    )
    await driver.call(
        "get_article_references",
        {"pmid": PRIMARY_PMID, "limit": 1},
        _contains(f"References of PMID {PRIMARY_PMID}", "Reference Paper 2", "45678901"),
    )
    await driver.call(
        "get_citation_metrics",
        {"pmids": PRIMARY_PMID, "sort_by": "citation_count", "output_format": "json"},
        _expect_json(
            {
                "tool": "get_citation_metrics",
                "article_count": 1,
                "articles.0.pmid": PRIMARY_PMID,
                "articles.0.citation_count": 100,
                "source_counts.0.source": "nih-icite",
            }
        ),
    )
    await driver.call(
        "verify_reference_list",
        {
            "reference_text": "Smith J. Example title. N Engl J Med. 2024;390(1):12-18.",
            "source_name": "references.txt",
            "max_references": 1,
        },
        _expect_json(
            {
                "success": True,
                "status": "ok",
                "source_name": "references.txt",
                "summary.verified": 1,
                "results.0.status": "verified",
                "results.0.resolution_method": "ecitmatch",
                "results.0.matched_article.pmid": PRIMARY_PMID,
            }
        ),
    )

    await driver.call(
        "get_fulltext",
        {
            "source": {"kind": "pmcid", "value": "PMC7096777"},
            "include_pdf_links": True,
            "include_figures": False,
            "extended_sources": False,
            "output_format": "json",
            "allow_browser_session": False,
        },
        _expect_json(
            {
                "tool": "get_fulltext",
                "identifiers.requested.kind": "pmcid",
                "identifiers.pmcid": "PMC7096777",
                "title": "Offline Fulltext",
                "fulltext_available": True,
                "coverage_status": "complete",
                "content_sections.0.content": "Deterministic content.",
                "pdf_links.0.source": "PubMed Central",
                "pdf_links.0.url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7096777/pdf/",
                "pdf_links.0.type": "pdf",
                "pdf_links.0.access": "open_access",
                "source_errors": [],
            }
        ),
    )
    await driver.call(
        "get_text_mined_terms",
        {
            "source": {"kind": "pmcid", "value": "PMC7096777"},
            "semantic_type": "GENE_PROTEIN",
            "output_format": "json",
        },
        _expect_json(
            {
                "tool": "get_text_mined_terms",
                "identifiers.pmcid": "PMC7096777",
                "annotation_count": 1,
                "annotations.0.term": "BRCA1",
                "source_counts.0.returned": 1,
            }
        ),
    )
    await driver.call(
        "get_article_figures",
        {
            "source": {"kind": "pmcid", "value": "PMC12086443"},
            "include_subfigures": False,
            "include_tables": False,
            "output_format": "json",
        },
        _expect_json(
            {
                "tool": "get_article_figures",
                "identifiers.requested.kind": "pmcid",
                "figure_count": 1,
                "total_figures": 1,
                "figures.0.label": "Figure 1",
                "figures.0.caption_text": "Acceptance figure",
                "figures.0.image_url": "https://example.test/fig1.png",
            }
        ),
    )

    await driver.call(
        "search_gene",
        {"query": "BRCA1", "organism": "human", "limit": 1},
        _expect_json({"status": "success", "source": "ncbi_gene", "count": 1, "genes.0.symbol": "BRCA1"}),
    )
    await driver.call(
        "get_gene_details",
        {"gene_id": "672"},
        _expect_json({"status": "success", "source": "ncbi_gene", "gene.gene_id": "672", "gene.symbol": "BRCA1"}),
    )
    await driver.call(
        "get_gene_literature",
        {"gene_id": "672", "limit": 2},
        _expect_json({"gene_id": "672", "pubmed_count": 2, "pmids.0": PRIMARY_PMID, "pmids.1": "23456789"}),
    )
    await driver.call(
        "search_compound",
        {"query": "aspirin", "limit": 1},
        _expect_json({"status": "success", "source": "pubchem", "count": 1, "compounds.0.cid": "2244"}),
    )
    await driver.call(
        "get_compound_details",
        {"cid": "2244"},
        _expect_json({"status": "success", "source": "pubchem", "compound.cid": "2244", "compound.name": "Aspirin"}),
    )
    await driver.call(
        "get_compound_literature",
        {"cid": "2244", "limit": 2},
        _expect_json(
            {
                "compound_cid": "2244",
                "pubmed_count": 2,
                "pmids.0": PRIMARY_PMID,
                "pmids.1": "34567890",
            }
        ),
    )
    await driver.call(
        "search_clinvar",
        {"query": "BRCA1", "limit": 1},
        _expect_json({"status": "success", "source": "clinvar", "count": 1, "variants.0.significance": "Pathogenic"}),
    )

    def validate_citation_tree(result: Any) -> None:
        summary, separator, document = _result_text(result).rpartition("\n---\n\n")
        assert separator
        assert summary.startswith("🌳 **Citation Tree Built with complete source coverage**")
        payload = json.loads(document)
        assert payload["status"] == "complete"
        assert payload["format"] == "cytoscape"
        assert payload["metadata"]["root_pmid"] == "111"
        assert payload["metadata"]["statistics"]["total_nodes"] == 3
        assert payload["metadata"]["statistics"]["total_edges"] == 2
        assert {node["data"]["id"] for node in payload["graph"]["nodes"]} == {
            "pmid_111",
            "pmid_222",
            "pmid_333",
        }
        assert {edge["data"]["id"] for edge in payload["graph"]["edges"]} == {
            "e_222_111",
            "e_111_333",
        }

    await driver.call(
        "build_citation_tree",
        {"pmid": "111", "depth": 1, "direction": "both", "limit_per_level": 2, "output_format": "cytoscape"},
        validate_citation_tree,
    )

    def validate_citation_mermaid(result: Any) -> None:
        _summary, separator, document = _result_text(result).rpartition("\n---\n\n")
        assert separator
        payload = json.loads(document)
        assert payload["status"] == "complete"
        assert payload["format"] == "mermaid"
        source = payload["graph"]
        validation = payload["mermaid_validation"]
        assert source.startswith("flowchart TD\n")
        assert hashlib.sha256(source.encode("utf-8")).hexdigest() == validation["source_sha256"]
        assert len(source) == validation["source_chars"]
        assert len(source.encode("utf-8")) == validation["source_bytes"]
        assert validation["structural_valid"] is True
        _render_with_pinned_mermaid_if_configured(source, scratch, "citation-tree")

    await driver.call(
        "build_citation_tree",
        {"pmid": "111", "depth": 1, "direction": "both", "limit_per_level": 2, "output_format": "mermaid"},
        validate_citation_mermaid,
    )

    def validate_bibtex_export(result: Any) -> None:
        payload = _json_document(_result_text(result))
        assert payload["status"] == "success"
        assert payload["article_count"] == 1
        assert payload["format"] == "bibtex"
        assert payload["source"] == "local"
        export_text = payload["export_text"]
        assert export_text.startswith("@article{")
        assert SEARCH_PMID in export_text
        assert "Deterministic Acceptance Article" in export_text
        assert "10.1000/offline-acceptance" in export_text

    await driver.call(
        "prepare_export",
        {"pmids": SEARCH_PMID, "format": "bibtex", "source": "local", "include_abstract": True},
        validate_bibtex_export,
    )
    notes_dir = scratch / "notes"
    await driver.call(
        "save_literature_notes",
        {
            "pmids": SEARCH_PMID,
            "output_dir": str(notes_dir),
            "note_format": "wiki",
            "create_index": False,
            "include_csl_json": True,
            "overwrite": True,
        },
        _expect_json(
            {
                "status": "success",
                "note_format": "wiki",
                "index_file": None,
                "wiki_validation.status": "passed",
            }
        ),
    )
    note_path = notes_dir / f"{SEARCH_PMID}.md"
    try:
        note_text = note_path.read_text(encoding="utf-8")
        assert "Deterministic Acceptance Article" in note_text
        assert f'pmid: "{SEARCH_PMID}"' in note_text
        csl_payload = json.loads((notes_dir / "references.csl.json").read_text(encoding="utf-8"))
        assert csl_payload[0]["PMID"] == SEARCH_PMID
        assert csl_payload[0]["title"] == "Deterministic Acceptance Article"
        assert csl_payload[0]["DOI"] == "10.1000/offline-acceptance"
        assert sorted(path.name for path in notes_dir.iterdir()) == [f"{SEARCH_PMID}.md", "references.csl.json"]
    except Exception as exc:
        driver.failures.append(f"save_literature_notes persistence: {type(exc).__name__}: {exc}")

    await driver.call(
        "read_session",
        {"request": {"action": "summary", "include_history": True, "history_limit": 10}},
        _expect_json({"success": True, "has_session": True}),
    )
    await driver.call(
        "read_session",
        {"request": {"action": "pmids"}},
        _expect_json({"success": True, "pmids.0": SEARCH_PMID}),
    )
    await driver.call(
        "read_session",
        {"request": {"action": "article", "pmid": SEARCH_PMID}},
        _expect_json(
            {
                "success": True,
                "source": "cache",
                "article.title": "Deterministic Acceptance Article",
                "article.pmid": SEARCH_PMID,
            }
        ),
    )
    await driver.call(
        "read_session",
        {"request": {"action": "log", "include_history": True, "history_limit": 10}},
        _expect_json({"success": True, "search_history.0.query": "offline acceptance"}),
    )

    def validate_artifact_listing(result: Any) -> None:
        payload = _json_document(_result_text(result))
        assert payload["success"] is True
        assert payload["total_artifacts"] >= 2
        tools = {artifact["tool"] for artifact in payload["artifacts"]}
        assert {"unified_search", "get_fulltext"} <= tools

    await driver.call(
        "read_session",
        {"request": {"action": "list_artifacts", "limit": 10}},
        validate_artifact_listing,
    )
    await driver.call(
        "read_session",
        {"request": {"action": "search_runs", "limit": 10}},
        _expect_json(
            {
                "success": True,
                "returned_runs": 1,
                "runs.0.run_id": run_id,
                "runs.0.status": "completed",
                "runs.0.result_count": 1,
            }
        ),
    )
    await driver.call(
        "read_session",
        {"request": {"action": "search_run", "run_id": run_id}},
        _expect_json(
            {
                "success": True,
                "run.run_id": run_id,
                "run.query": "offline acceptance",
                "run.status": "completed",
                "run.result.count": 1,
                "run.result.pmids.0": SEARCH_PMID,
                "replay_available": True,
            }
        ),
    )
    await driver.call(
        "read_session",
        {"request": {"action": "replay_search", "run_id": run_id}},
        _expect_json(
            {
                "success": True,
                "automatic_execution": False,
                "replay.tool": "unified_search",
                "replay.arguments.query": "offline acceptance",
                "replay.arguments.sources": "pubmed",
                "replay.arguments.limit": 1,
                "replay.arguments.output_format": "json",
                "replay.arguments.options": "shallow,no_oa,no_relax,no_analysis,no_scores,no_next",
            }
        ),
    )

    def validate_audit_artifact(result: Any) -> None:
        payload = _json_document(_result_text(result))
        assert payload["success"] is True
        assert payload["file"]["name"] == "audit.json"
        assert payload["truncated"] is False
        audit = json.loads(payload["content"])
        assert audit["tool"] == "unified_search"
        assert audit["status"] == "pass"
        assert audit["counts"]["ranked_articles"] == 1
        assert audit["counts"]["source_counts"]["pubmed"]["returned"] == 1

    await driver.call(
        "read_session",
        {
            "request": {
                "action": "artifact",
                "locator": {"kind": "artifact_uri", "value": artifact_uri},
                "artifact_file": "audit.json",
            }
        },
        validate_audit_artifact,
    )

    await driver.call("list_resolver_presets", {}, _contains("ntu", "test_free"))
    await driver.call(
        "configure_institutional_access",
        {"preset": "test_free"},
        _contains("Institutional access configured", "resolver.ebscohost.com"),
    )
    await driver.call(
        "get_institutional_link",
        {
            "source": {
                "kind": "metadata",
                "title": "Deterministic Acceptance Article",
                "journal": "MCP Medicine",
                "year": 2026,
            }
        },
        _contains("Library Access Link", "resolver.ebscohost.com", "Deterministic Acceptance Article"),
    )
    await driver.call(
        "test_institutional_access",
        {"pmid": SEARCH_PMID},
        _contains("Configured", "URL Generated", "Reachable", "HTTP Status: 200"),
    )
    await driver.call(
        "diagnose_institutional_access",
        {
            "source": {"kind": "doi", "value": "10.1000/offline-acceptance"},
            "try_direct": True,
            "try_ezproxy": False,
        },
        _contains("10.1000/offline-acceptance", "Recommended path", "direct", "fulltext_html"),
    )

    def validate_vision(result: Any) -> None:
        assert len(result.content) == 2
        assert result.content[0].type == "image"
        assert result.content[0].mime_type == "image/png"
        assert result.content[0].data == PNG_DATA_URI.split(",", 1)[1]
        assert result.content[1].type == "text"
        assert "Medical Image Analysis" in result.content[1].text
        assert "Offline acceptance fixture" in result.content[1].text
        assert "IMMEDIATELY search for related literature" in result.content[1].text
        assert "search_biomedical_images()" in result.content[1].text
        assert "unified_search()" in result.content[1].text

    await driver.call(
        "prepare_figure_search",
        {
            "source": {"kind": "base64", "data": PNG_DATA_URI},
            "context": "Offline acceptance fixture",
            "search_type": "medical",
        },
        validate_vision,
    )
    await driver.call(
        "convert_icd_mesh",
        {"direction": "icd_to_mesh", "value": "E11"},
        _expect_json(
            {
                "success": True,
                "match_type": "exact",
                "icd_version": "ICD-10-CM",
                "mesh_term": "Diabetes Mellitus, Type 2",
                "mapping_scope": "curated_subset",
            }
        ),
    )
    await driver.call(
        "search_biomedical_images",
        {"query": "chest pneumonia", "image_type": "x", "collection": "cxr", "limit": 2, "sort_by": "d"},
        _contains("Image Search Results", "completed", "42", PRIMARY_PMID, "Chest X-ray"),
    )

    await driver.call(
        "build_research_chronicle",
        {
            "topic": "Offline Chronicle",
            "chronicle_id": "offline-chronicle",
            "max_events": 5,
            "output": "json",
        },
        _expect_json(
            {
                "schema_version": "research-chronicle/v1",
                "chronicle_id": "offline-chronicle",
                "revision": 1,
                "metadata.timeline_metadata.retrieval.returned_limit": 15,
                "metadata.timeline_metadata.retrieval.ranking": "icite_citation_count_then_pubmed_relevance",
                "metadata.timeline_metadata.retrieval.citation_metrics.status": "complete",
                "metadata.timeline_metadata.retrieval.citation_metrics.requested": 3,
                "metadata.timeline_metadata.retrieval.citation_metrics.applied": 3,
            }
        ),
    )
    await driver.call(
        "build_research_chronicle",
        {"chronicle_id": "offline-chronicle", "output": "json"},
        _expect_json(
            {
                "chronicle_id": "offline-chronicle",
                "revision": 2,
                "metadata.timeline_metadata.retrieval.returned_limit": 15,
                "metadata.timeline_metadata.retrieval.citation_metrics.requested": 5,
                "metadata.timeline_metadata.retrieval.citation_metrics.applied": 5,
            }
        ),
    )
    await driver.call(
        "build_research_chronicle",
        {"topic": "Offline Comparator", "chronicle_id": "offline-comparator", "output": "json"},
        _expect_json(
            {
                "chronicle_id": "offline-comparator",
                "revision": 1,
                "metadata.timeline_metadata.retrieval.returned_limit": 90,
                "metadata.timeline_metadata.retrieval.citation_metrics.requested": 2,
                "metadata.timeline_metadata.retrieval.citation_metrics.applied": 2,
            }
        ),
    )
    await driver.call(
        "read_research_chronicle",
        {"request": {"action": "list", "limit": 20}},
        _expect_json({"total": 2}),
    )

    chronicle_mermaid_contract: dict[str, Any] = {}

    def validate_chronicle_map(result: Any) -> None:
        payload = _json_document(_result_text(result))
        assert payload["projection"] == "chronicle_map"
        assert payload["layout"] == "horizontal_time_spine_with_lineage_branches"
        assert payload["spine"]["orientation"] == "horizontal"
        assert [anchor["year"] for anchor in payload["spine"]["year_anchors"]] == [
            1998,
            2005,
            2012,
            2019,
            2025,
        ]
        assert payload["lineage_diagnostics"]["basis"] == "topic_signals"
        assert payload["lineage_diagnostics"]["semantic_coverage_ratio"] >= 0.8
        assert {"Mechanistic Pathways", "Precision Therapeutics"} <= {branch["name"] for branch in payload["branches"]}
        ordered_entries = sorted(
            (entry for branch in payload["branches"] for entry in branch["entries"]),
            key=lambda entry: entry["global_order"],
        )
        assert [entry["year"] for entry in ordered_entries] == [1998, 2005, 2012, 2019, 2025]
        assert [entry["evidence_ids"][0] for entry in ordered_entries] == [
            "pmid:50000001",
            "pmid:50000002",
            "pmid:50000003",
            "pmid:50000004",
            "pmid:50000005",
        ]
        assert payload["mermaid_validation"]["structural_valid"] is True
        assert payload["mermaid_validation"]["tier"] == "rich"
        assert payload["mermaid_validation"]["corrections"]
        chronicle_mermaid_contract.update(payload["mermaid_validation"])

    await driver.call(
        "read_research_chronicle",
        {
            "request": {
                "action": "load",
                "chronicle_id": "offline-chronicle",
                "output": "chronicle_map",
            }
        },
        validate_chronicle_map,
    )

    def validate_chronicle_mermaid(result: Any) -> None:
        text = _result_text(result)
        match = re.fullmatch(r"```mermaid\n(?P<source>.+)\n```", text, re.DOTALL)
        assert match is not None, "Chronicle Mermaid response was not one complete fenced diagram"
        source = match.group("source")
        assert source.startswith("flowchart LR\n")
        assert "Mechanistic Pathways" in source
        assert "Precision Therapeutics" in source
        assert "%%{init" not in source
        assert "```" not in source
        assert "\u202e" not in source
        assert hashlib.sha256(source.encode("utf-8")).hexdigest() == chronicle_mermaid_contract["source_sha256"]
        assert len(source) == chronicle_mermaid_contract["source_chars"]
        assert len(source.encode("utf-8")) == chronicle_mermaid_contract["source_bytes"]
        branch_nodes = set(re.findall(r"^\s*(n_branch_[A-Za-z0-9_]+)\[", source, re.MULTILINE))
        assert len(branch_nodes) >= 2
        assert source.count("-.->") >= 2
        _render_with_pinned_mermaid_if_configured(source, scratch, "research-chronicle")

    await driver.call(
        "read_research_chronicle",
        {"request": {"action": "load", "chronicle_id": "offline-chronicle", "output": "mermaid"}},
        validate_chronicle_mermaid,
    )
    await driver.call(
        "read_research_chronicle",
        {"request": {"action": "diff", "chronicle_id": "offline-chronicle", "from_revision": 1}},
        _expect_json(
            {
                "chronicle_id": "offline-chronicle",
                "from_revision": 1,
                "to_revision": 2,
                "entries.added.0.year": 2019,
                "entries.added.1.year": 2025,
                "evidence.total_before": 3,
                "evidence.total_after": 5,
            }
        ),
    )
    await driver.call(
        "read_research_chronicle",
        {"request": {"action": "narrate", "chronicle_id": "offline-chronicle", "mode": "full"}},
        _contains("Offline Chronicle", "entry-", "1998", "2025", "PMID:50000001", "PMID:50000005"),
    )
    await driver.call(
        "read_research_chronicle",
        {"request": {"action": "milestones", "chronicle_id": "offline-chronicle"}},
        _expect_json(
            {
                "projection": "milestones",
                "chronicle_id": "offline-chronicle",
                "revision": 2,
                "topic": "Offline Chronicle",
                "total_entries": 5,
                "year_range.0": 1998,
                "year_range.1": 2025,
                "evidence_quality.total_articles": 5,
                "evidence_quality.with_identifier": 5,
                "evidence_quality.with_citation_count": 5,
                "evidence_quality.max_citations": 100,
            }
        ),
    )
    await driver.call(
        "read_research_chronicle",
        {
            "request": {
                "action": "compare",
                "selection": {
                    "kind": "chronicle_ids",
                    "values": ["offline-chronicle", "offline-comparator"],
                },
            }
        },
        _expect_json(
            {
                "projection": "comparison",
                "chronicles.0.chronicle_id": "offline-chronicle",
                "chronicles.0.topic": "Offline Chronicle",
                "chronicles.0.total_entries": 5,
                "chronicles.1.chronicle_id": "offline-comparator",
                "chronicles.1.topic": "Offline Comparator",
                "chronicles.1.total_entries": 2,
                "summary.earliest_research": 1998,
                "summary.latest_research": 2025,
                "summary.most_entries": "Offline Chronicle",
                "summary.shared_evidence_count": 0,
                "shared_evidence": [],
            }
        ),
    )

    await driver.call(
        "save_pipeline",
        {
            "name": "acceptance-pipeline",
            "config": PIPELINE_CONFIG,
            "tags": ["acceptance", "offline"],
            "description": "Deterministic MCP acceptance pipeline",
            "scope": "global",
        },
        _contains("saved successfully", "acceptance-pipeline", "Scope: global", "Config hash"),
    )
    await driver.call(
        "list_pipelines",
        {"tag": "acceptance", "scope": "global"},
        _contains("1 total", "acceptance-pipeline", "acceptance, offline"),
    )
    await driver.call(
        "load_pipeline",
        {"source": "saved:acceptance-pipeline"},
        _contains("Pipeline: acceptance-pipeline", "action: search", "query: offline pipeline"),
    )
    await driver.call(
        "unified_search",
        {"pipeline": "saved:acceptance-pipeline", "output_format": "json"},
        _expect_json(
            {
                "type": "pipeline_result",
                "pipeline.name": "acceptance-pipeline",
                "summary.article_count": 1,
                "summary.steps_executed": 1,
                "summary.steps_failed": 0,
                "steps.0.id": "search",
                "steps.0.action": "search",
                "steps.0.status": "ok",
                "steps.0.pmids.0": SEARCH_PMID,
                "articles.0.identifiers.pmid": SEARCH_PMID,
            }
        ),
    )
    await driver.call(
        "get_pipeline_history",
        {"name": "acceptance-pipeline", "limit": 10},
        _contains('Execution History for "acceptance-pipeline"', "| 1 |", "✅ OK"),
    )
    await driver.call(
        "schedule_pipeline",
        {
            "name": "acceptance-pipeline",
            "cron": "0 0 1 1 *",
            "diff_mode": True,
            "notify": False,
        },
        _contains("Schedule set", "0 0 1 1 *", "Timezone: UTC", "Diff mode: on", "Notify: off"),
    )
    await driver.call(
        "unschedule_pipeline",
        {"name": "acceptance-pipeline"},
        _contains("Schedule removed", "Previous cron: 0 0 1 1 *"),
    )
    await driver.call(
        "delete_pipeline",
        {"name": "acceptance-pipeline"},
        _contains('Pipeline "acceptance-pipeline" deleted', "global scope", "execution history record"),
    )

    def validate_deleted_pipeline_listing(result: Any) -> None:
        text = _result_text(result)
        assert "No saved pipelines found" in text
        assert "acceptance-pipeline" not in text

    await driver.call(
        "list_pipelines",
        {"tag": "acceptance", "scope": "global"},
        validate_deleted_pipeline_listing,
    )

    driver.finish(listed_tools)


@pytest.mark.asyncio
@pytest.mark.timeout(120)
async def test_all_tools_through_real_stdio_mcp(tmp_path: Path) -> None:
    scratch = tmp_path / "stdio"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(ACCEPTANCE_SERVER)],
        cwd=ROOT,
        env=_acceptance_env(scratch),
    )
    async with Client(stdio_client(parameters), read_timeout_seconds=30) as client:
        await _exercise_all_tools(client, scratch)
    _assert_no_external_network(scratch)


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_breaking_contract_rejections_through_real_stdio_mcp(tmp_path: Path) -> None:
    scratch = tmp_path / "stdio-strict-rejections"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(ACCEPTANCE_SERVER)],
        cwd=ROOT,
        env=_acceptance_env(scratch),
    )
    async with Client(stdio_client(parameters), read_timeout_seconds=30) as client:
        listed = {tool.name for tool in (await client.list_tools()).tools}
        assert listed.isdisjoint(RETIRED_TOOLS)
        invalid_calls = [
            ("unified_search", {"query": "offline acceptance", "limit": "1"}),
            ("read_session", {"action": "summary"}),
            ("read_research_chronicle", {"action": "list"}),
            ("get_institutional_link", {"pmid": PRIMARY_PMID}),
            ("prepare_figure_search", {"source": '{"kind":"base64","data":"YWJj"}'}),
            ("validate_pico_plan", {"description": "ICU sedation", "sources": '["pubmed"]'}),
        ]
        for tool_name, arguments in invalid_calls:
            result = await client.call_tool(tool_name, arguments)
            assert result.is_error is True, f"{tool_name} accepted retired/coerced arguments: {_result_text(result)}"
        for retired_tool in sorted(RETIRED_TOOLS):
            result = await client.call_tool(retired_tool, {})
            assert result.is_error is True, f"retired tool became callable: {retired_tool}"
    _assert_no_external_network(scratch)


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _running_acceptance_http_server(python: Path, root: Path) -> Iterator[str]:
    port = _unused_loopback_port()
    log_path = root / "streamable-http.log"
    root.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                str(python),
                str(ACCEPTANCE_SERVER),
                "--transport",
                "http",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=_acceptance_env(root),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(200):
                if process.poll() is not None:
                    break
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        pass
                except OSError:
                    time.sleep(0.05)
                    continue
                yield f"http://127.0.0.1:{port}/mcp"
                return
            log.flush()
            details = log_path.read_text(encoding="utf-8", errors="replace")
            raise AssertionError(f"Acceptance HTTP server did not become ready:\n{details}")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


@pytest.mark.asyncio
@pytest.mark.timeout(120)
async def test_all_tools_through_real_streamable_http_mcp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "all_proxy", "https_proxy", "http_proxy"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    scratch = tmp_path / "http"
    with _running_acceptance_http_server(Path(sys.executable), scratch) as endpoint:
        async with Client(endpoint, read_timeout_seconds=30) as client:
            await _exercise_all_tools(client, scratch)
    _assert_no_external_network(scratch)


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.timeout(240)
async def test_all_tools_from_freshly_installed_wheel_through_stdio_mcp(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is required for the wheel acceptance test")

    dist_dir = tmp_path / "dist"
    venv_dir = tmp_path / "venv"
    subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(dist_dir)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(dist_dir.glob("pubmed_search_mcp-*.whl"))
    subprocess.run(
        [uv, "venv", str(venv_dir), "--python", sys.executable],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    venv_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [uv, "pip", "install", "--python", str(venv_python), str(wheel)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    imported = subprocess.run(
        [
            str(venv_python),
            "-c",
            "from pathlib import Path; import pubmed_search; print(Path(pubmed_search.__file__).resolve())",
        ],
        cwd=tmp_path,
        env=_acceptance_env(tmp_path / "wheel-import"),
        check=True,
        capture_output=True,
        text=True,
    )
    imported_path = Path(imported.stdout.strip()).resolve()
    assert imported_path.is_relative_to(venv_dir.resolve())

    scratch = tmp_path / "wheel"
    parameters = StdioServerParameters(
        command=str(venv_python),
        args=[str(ACCEPTANCE_SERVER)],
        cwd=tmp_path,
        env=_acceptance_env(scratch),
    )
    async with Client(stdio_client(parameters), read_timeout_seconds=30) as client:
        await _exercise_all_tools(client, scratch)
    _assert_no_external_network(scratch)
