"""Exercise the optional plugin executable with real read projections, independent of chat history."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from pubmed_search.application.research_workspace import ResearchWorkspaceService
from pubmed_search.infrastructure.research_workspace import SQLiteResearchWorkspaceStore

SCRIPT = Path(__file__).resolve().parents[1] / ".claude/skills/pubmed-research-workspace/scripts/render_handoff.py"


def invoke(payload: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-S", str(SCRIPT)],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        encoding="utf-8",
        check=False,
    )


def test_executable_renders_a_paged_mcp_handoff_and_preserves_evidence(tmp_path: Path) -> None:
    service = ResearchWorkspaceService(SQLiteResearchWorkspaceStore(tmp_path))
    service.create("history", "人工耳蝸研究有哪些比較方法？")
    service.record("history", "seed", "explore", "Read the abstract.", next_action="Look up the device design.")
    service.record(
        "history",
        "methods",
        "examine",
        "已讀原文",
        source_refs=["pmid:3878092"],
        evidence_scope="fulltext",
        locator="Methods, 表一",
        parent_ids=["seed"],
        next_action="Compare eligibility criteria.",
        actor="human",
    )
    service.record("history", "counter", "expand", "Look for a counterexample.", next_action="Read its abstract.")
    page = service.read("history", after=1, limit=1)
    response = {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(page)}]}}

    result = invoke(response)
    assert result.returncode == 0, result.stderr
    assert "人工耳蝸研究有哪些比較方法？" in result.stdout
    assert "[methods] examine / fulltext / human" in result.stdout
    assert "已讀原文" in result.stdout and "Methods, 表一" in result.stdout and "pmid:3878092" in result.stdout
    assert "unverified" in result.stdout and "[seed] Look up the device design." in result.stdout
    assert "Records (1 of 3)" in result.stdout and "after=0" in result.stdout and "after=2" in result.stdout
    assert "Open actions (1 of 3)" in result.stdout and "open_offset=1" in result.stdout

    latest = invoke(service.read("history", limit=1))
    assert "Records (1 of 3)" in latest.stdout and "after=0" in latest.stdout
    assert "Continue this history page" not in latest.stdout


def test_executable_accepts_an_empty_read_file_without_modifying_it(tmp_path: Path) -> None:
    service = ResearchWorkspaceService(SQLiteResearchWorkspaceStore(tmp_path))
    service.create("empty", "Which papers should we read?")
    path = tmp_path / "workspace.json"
    original = json.dumps(service.read("empty")).encode("utf-8-sig")
    path.write_bytes(original)
    result = subprocess.run([sys.executable, "-I", "-S", str(SCRIPT), str(path)], capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert b"Open actions (0 of 0)" in result.stdout and b"Partial" not in result.stdout
    assert path.read_bytes() == original


def test_handoff_preserves_a_resolved_question_as_history(tmp_path: Path) -> None:
    service = ResearchWorkspaceService(SQLiteResearchWorkspaceStore(tmp_path))
    service.create("history", "How were devices selected?")
    service.record("history", "seed", "explore", "Found a comparison.", next_action="Which year did recruitment start?")
    service.record(
        "history",
        "follow-up",
        "examine",
        "A reader checked the dates.",
        resolves=["seed"],
        next_action="Find the table.",
    )
    result = invoke(service.read("history"))
    assert result.returncode == 0, result.stderr
    history, open_actions = result.stdout.split("Open actions (1 of 1)")
    assert "Originally requested  Which year did recruitment start?" in history
    assert "Closes  seed" in history
    assert "Which year did recruitment start?" not in open_actions
    assert "[follow-up] Find the table." in open_actions


@pytest.mark.parametrize(
    "invalid",
    [
        {"workspace_id": "created", "replayed": False},
        {"content": [{"type": "text", "text": "not JSON"}]},
        {"isError": True, "content": [{"type": "text", "text": "failed"}]},
        {"records": [], "open_actions": [], "record_count": True, "open_action_count": 0},
    ],
)
def test_invalid_payload_fails_without_emitting_a_partial_handoff(invalid: dict[str, Any]) -> None:
    result = invoke(invalid)
    assert result.returncode != 0 and result.stdout == ""
    assert "Cannot render research handoff" in result.stderr and "Traceback" not in result.stderr
