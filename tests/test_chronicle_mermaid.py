"""Adversarial tests for Research Chronicle Mermaid repair and fallback."""

from __future__ import annotations

import copy
import re
from typing import Any

import pytest

from pubmed_search.application.chronicle import (
    render_chronicle_mermaid_projection,
    validate_mermaid_source,
)


def _projection(*, topic: Any = "IL-6 response") -> dict[str, Any]:
    return {
        "projection": "chronicle_map",
        "topic": topic,
        "spine": {
            "year_anchors": [
                {"year": 2018, "entry_ids": ["entry-1"]},
                {"year": 2021, "entry_ids": ["entry-2"]},
            ]
        },
        "branches": [
            {
                "branch_id": "mechanism",
                "name": "Mechanism",
                "lineage_basis": "mesh",
                "parent_branch_id": None,
                "branch_point": {"year": 2018},
                "entries": [
                    {
                        "entry_id": "entry-1",
                        "time_start": "2018",
                        "title": "First signal",
                        "paper_title": "Discovery study",
                        "evidence_ids": ["pmid:1"],
                    },
                    {
                        "entry_id": "entry-2",
                        "time_start": "2021",
                        "title": "Replication",
                        "paper_title": "Validation study",
                        "evidence_ids": ["doi:10.1/example"],
                    },
                ],
            }
        ],
        "unassigned_entry_ids": [],
    }


def _correction_codes(result: Any) -> set[str]:
    return {item["code"] for item in result.corrections}


@pytest.mark.parametrize(
    "hostile_label",
    [
        '"[]{}():;|#&<>` --> -.-> ==> %%{init: {}}%% <script>alert(1)</script>',
        "line one\r\nline two\t\f\0\u2028\u2029\u202e\u200b" + chr(0xD800),
        "IL-6 [95% CI]; p<0.001; CD4+/CD8+; β-catenin; BRAF(V600E)",
        "細胞訊號與免疫療法 🧬 → 臨床轉譯",
    ],
)
def test_hostile_biomedical_labels_are_normalized_without_breaking_flowchart(hostile_label: str) -> None:
    projection = _projection(topic=hostile_label)
    projection["branches"][0]["name"] = hostile_label
    projection["branches"][0]["entries"][0]["title"] = hostile_label
    projection["branches"][0]["entries"][0]["time_start"] = hostile_label

    result = render_chronicle_mermaid_projection(projection)
    valid, issues = validate_mermaid_source(result.source)

    assert valid, issues
    assert result.tier == "rich"
    assert result.status == "repaired"
    assert "label_escaped" in _correction_codes(result) or "label_normalized" in _correction_codes(result)
    assert "%%{" not in result.source
    assert "<script" not in result.source.casefold()
    assert "\r" not in result.source
    assert "\0" not in result.source
    result.source.encode("utf-8")


def test_opaque_ids_prevent_lossy_identifier_collisions() -> None:
    projection = _projection()
    projection["branches"] = [
        {
            "branch_id": branch_id,
            "name": branch_id,
            "branch_point": {"year": 2018},
            "entries": [],
        }
        for branch_id in ("a-b", "a b", "a/b")
    ]

    first = render_chronicle_mermaid_projection(projection)
    second = render_chronicle_mermaid_projection(copy.deepcopy(projection))
    node_ids = re.findall(r'^    ([A-Za-z][A-Za-z0-9_]*)\["', first.source, flags=re.MULTILINE)

    assert first.source == second.source
    assert len(node_ids) == len(set(node_ids))
    assert len([node_id for node_id in node_ids if node_id.startswith("n_branch_")]) == 3
    assert all(len(node_id) <= 64 for node_id in node_ids)


def test_visual_ids_stay_stable_when_unrelated_earlier_items_are_inserted() -> None:
    baseline = _projection()
    expanded = copy.deepcopy(baseline)
    expanded["spine"]["year_anchors"].insert(0, {"year": 2010, "entry_ids": []})
    expanded["branches"].insert(
        0,
        {
            "branch_id": "earlier",
            "name": "Earlier work",
            "branch_point": {"year": 2010},
            "entries": [],
        },
    )

    baseline_source = render_chronicle_mermaid_projection(baseline).source
    expanded_source = render_chronicle_mermaid_projection(expanded).source

    def id_for_label(source: str, label: str) -> str:
        match = re.search(rf'^    ([A-Za-z][A-Za-z0-9_]*)\["{re.escape(label)}"\]$', source, re.MULTILINE)
        assert match
        return match.group(1)

    assert id_for_label(baseline_source, "2018") == id_for_label(expanded_source, "2018")
    assert id_for_label(baseline_source, "Mechanism — mesh") == id_for_label(expanded_source, "Mechanism — mesh")


def test_async_external_validator_is_rejected_instead_of_treated_as_truthy() -> None:
    async def invalid_async_validator(_source: str) -> bool:
        return True

    result = render_chronicle_mermaid_projection(
        _projection(),
        validator=invalid_async_validator,  # type: ignore[arg-type]
    )

    assert result.tier == "minimal"
    assert result.parser_validated is False
    assert any("awaitable" in warning for warning in result.warnings)


def test_malformed_structure_is_repaired_without_mutating_projection() -> None:
    projection = _projection()
    projection["spine"]["year_anchors"].extend(
        [
            {"year": 2018, "entry_ids": []},
            {"year": "not-a-year", "entry_ids": []},
        ]
    )
    projection["branches"] = [
        {
            "branch_id": "duplicate",
            "name": "First duplicate",
            "parent_branch_id": "missing",
            "branch_point": {"year": "unknown"},
            "entries": [{"entry_id": "same-entry", "title": "First"}],
        },
        {
            "branch_id": "duplicate",
            "name": "Second duplicate",
            "parent_branch_id": None,
            "branch_point": {},
            "entries": [{"entry_id": "same-entry", "title": "Repeated"}],
        },
        {
            "branch_id": "cycle-a",
            "name": "Cycle A",
            "parent_branch_id": "cycle-b",
            "branch_point": {"year": 2021},
            "entries": [],
        },
        {
            "branch_id": "cycle-b",
            "name": "Cycle B",
            "parent_branch_id": "cycle-a",
            "branch_point": {"year": 2021},
            "entries": [],
        },
        {
            "branch_id": "self",
            "name": "Self cycle",
            "parent_branch_id": "self",
            "branch_point": {"year": 2021},
            "entries": [],
        },
    ]
    original = copy.deepcopy(projection)

    result = render_chronicle_mermaid_projection(projection)
    valid, issues = validate_mermaid_source(result.source)
    codes = _correction_codes(result)

    assert valid, issues
    assert projection == original
    assert {
        "branch_cycle_removed",
        "duplicate_branch_id",
        "duplicate_entry_id",
        "invalid_branch_parent",
        "invalid_branch_year",
    } <= codes
    assert result.omitted_counts["duplicate_entries"] == 1


def test_external_validator_rebuilds_rich_diagram_with_safe_syntax() -> None:
    calls: list[str] = []

    def reject_rich(source: str) -> bool:
        calls.append(source)
        return len(calls) > 1

    result = render_chronicle_mermaid_projection(
        _projection(),
        validator=reject_rich,
        validator_name="test-validator",
    )

    assert result.status == "fallback"
    assert result.tier == "safe"
    assert result.parser_validated is True
    assert result.validator == "test-validator"
    assert "rich_candidate_rejected" in _correction_codes(result)
    assert "==>" not in result.source
    assert "-.->" not in result.source
    assert "classDef" not in result.source
    assert len(calls) == 2


@pytest.mark.parametrize("validator", [lambda _source: False, lambda _source: (_ for _ in ()).throw(RuntimeError)])
def test_validator_failure_returns_guaranteed_minimal_source(validator: Any) -> None:
    result = render_chronicle_mermaid_projection(_projection(), validator=validator)
    valid, issues = validate_mermaid_source(result.source)

    assert valid, issues
    assert result.status == "fallback"
    assert result.tier == "minimal"
    assert result.parser_validated is False
    assert result.source.count("[") == 2
    assert {"rich_candidate_rejected", "safe_candidate_rejected"} <= _correction_codes(result)


def test_non_mapping_projection_returns_minimal_source_instead_of_raising() -> None:
    result = render_chronicle_mermaid_projection(["not", "a", "mapping"])  # type: ignore[arg-type]

    assert result.tier == "minimal"
    assert "malformed_projection" in _correction_codes(result)
    assert validate_mermaid_source(result.source)[0] is True


def test_visual_size_is_bounded_and_omissions_are_disclosed() -> None:
    projection = _projection(topic="T" * 10_000)
    projection["branches"][0]["entries"] = [
        {
            "entry_id": f"entry-{index}",
            "time_start": f"20{index % 100:02d}",
            "title": "Very long title " + "X" * 2_000,
            "paper_title": "Paper " + "Y" * 2_000,
            "evidence_ids": [f"pmid:{index}"],
        }
        for index in range(500)
    ]

    result = render_chronicle_mermaid_projection(projection)
    valid, issues = validate_mermaid_source(result.source)

    assert valid, issues
    assert len(result.source) <= 49_000
    assert len(result.source.encode("utf-8")) <= 49_000
    assert result.omitted_counts["entries"] == 380
    assert "visual_size_capped" in _correction_codes(result)
    assert "label_truncated" in _correction_codes(result)
    assert "see chronicle_map.json" in result.source


@pytest.mark.parametrize(
    "source",
    [
        '```mermaid\nflowchart LR\n    a["A"]\n```',
        'flowchart LR\n    %%{init: {}}%%\n    a["A"]',
        'flowchart LR\n    a["A"]\n    a --> missing',
        'flowchart LR\n    a["A"]\n    a["Again"]',
        'flowchart LR\n    a["A"]\n    click a href "https://example.test"',
        'flowchart LR\n    a["A"]\n    classDef custom fill:red',
    ],
)
def test_structural_lint_rejects_wrappers_directives_and_dangling_statements(source: str) -> None:
    valid, issues = validate_mermaid_source(source)

    assert valid is False
    assert issues
