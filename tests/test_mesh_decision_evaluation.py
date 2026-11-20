"""Protect the masking boundary, ranked queue scoring and installed comparison reader."""

from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

import pytest
from scripts import evaluate_mesh_preflight as evaluation


def test_published_receipts_bind_queries_costs_and_rankings():
    protocol = evaluation.read(evaluation.DEFAULT / "protocol.json")
    run = evaluation.DEFAULT / "run"
    preview = evaluation.load_stage(run, "preview", protocol)
    decisions = evaluation.load_stage(run, "decisions", preview)
    records = evaluation.load_stage(run, "retrieval", decisions)
    score = evaluation.read(evaluation.DEFAULT / "score.json")
    assert score["retrieval_sha256"] == evaluation.digest(records)
    for case in protocol["cases"]:
        key = case["id"]
        observed = preview["cases"][key]
        assert "pmids" not in evaluation.compact(observed["visible"])
        assert observed["evidence"]["plan.json"]["seed_pmids"] == []
        for arm, choice in [("original", "keep"), ("reviewed", decisions["cases"][key]["choice"])]:
            row = records["cases"][key][arm]
            assert row["query"] == evaluation.chosen_query(case, protocol["cutoff"], choice)
            assert row["calls"] == 1 + (observed["calls"] if arm == "reviewed" else 0)
            assert row["calls"] <= protocol["call_cap_per_arm"]
            assert len(set(row["pmids"])) == min(row["count"], protocol["screen_cap"])


def test_scoring_counts_displacement_and_preserves_warnings(tmp_path):
    qrels = tmp_path / "gold"
    qrels.write_bytes(b"a 0 1 1\na 0 2 1\nb 0 7 1\n")
    protocol = {
        "cases": [{"id": k, "scope": "x", "blocks": {"y": "Y"}} for k in "ab"],
        "cutoff": "2016[dp]",
        "qrels_sha256": hashlib.sha256(qrels.read_bytes()).hexdigest(),
    }
    preview = {"parent_sha256": evaluation.digest(protocol), "cases": {k: {"visible": {"status": "ok"}} for k in "ab"}}
    decisions = {
        "parent_sha256": evaluation.digest(preview),
        "cases": {k: {"choice": "keep", "reason": "retain scope"} for k in "ab"},
    }
    first = {"status": "ok", "pmids": ["1", "8"], "count": 3, "calls": 1}
    records = {
        "parent_sha256": evaluation.digest(decisions),
        "status": "finished",
        "cases": {
            "a": {"original": first, "reviewed": {**first, "pmids": ["2", "8"], "calls": 4}},
            "b": {"original": first, "reviewed": {**first, "status": "warning", "calls": 4}},
        },
    }
    for name, data in [("preview", preview), ("decisions", decisions), ("retrieval", records)]:
        (tmp_path / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    rows = evaluation.score(protocol, tmp_path, qrels)["cases"]
    assert rows["a"]["recovered"] == [1, 1]
    assert rows["a"]["gained"] == ["2"] and rows["a"]["lost"] == ["1"]
    assert rows["a"]["added_to_queue"] == rows["a"]["displaced_from_queue"] == 1
    assert rows["b"]["status"] == "incomplete" and "recovered" not in rows["b"]
    decisions["cases"]["b"]["reason"] = "edited after retrieval"
    (tmp_path / "decisions.json").write_text(json.dumps(decisions), encoding="utf-8")
    with pytest.raises(ValueError, match="frozen inputs"):
        evaluation.score(protocol, tmp_path, qrels)
    qrels.write_bytes(b"changed")
    with pytest.raises(ValueError, match="Wrong qrels"):
        evaluation.verify_gold(protocol, qrels)


def test_partial_preview_cannot_change_query_or_restart_same_stage(tmp_path):
    case = {"id": "a", "scope": "x", "blocks": {"b": "Y"}}
    with pytest.raises(ValueError, match="Partial"):
        evaluation.validate_choices(
            {"cases": [case], "cutoff": "2016[dp]"},
            {"cases": {"a": {"visible": {"status": "partial"}}}},
            {"a": {"choice": "b", "reason": "expand"}},
        )
    evaluation.reserve(tmp_path, "preview")
    with pytest.raises(FileExistsError):
        evaluation.reserve(tmp_path, "preview")
    with pytest.raises(ValueError, match="interrupted"):
        evaluation.load_stage(tmp_path, "preview", {})


def test_packaged_reader_handles_missing_difference_and_records_exact_choice(tmp_path):
    root = Path(__file__).resolve().parents[1]
    render = runpy.run_path(
        str(root / "plugins/pubmed-search/skills/pubmed-systematic-search/scripts/render_comparison.py")
    )["render"]
    case = evaluation.read(evaluation.DEFAULT / "run/preview.json")["cases"]["CD008760"]["evidence"]
    for name, value in case.items():
        if name != "drop-varices.json":
            (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    table = render(tmp_path / "plan.json", "liver", "Keep the index test and finding.")
    assert "| varices | missing | unknown |" in table
    assert case["drop-liver.json"]["relaxed_query"] in table
    assert case["drop-liver.json"]["difference"]["pmids"][0] in table
    with pytest.raises(ValueError, match="missing"):
        render(tmp_path / "plan.json", "varices", "test")
