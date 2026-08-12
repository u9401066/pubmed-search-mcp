"""Additional regression tests for bounded Chronicle Mermaid repair."""

from __future__ import annotations

import random
import re
from typing import Any

from pubmed_search.application.chronicle import (
    mermaid_label,
    render_chronicle_mermaid_projection,
    validate_mermaid_source,
)


def _branch(
    branch_id: str,
    *,
    year: int = 2020,
    entries: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "branch_id": branch_id,
        "name": f"Branch {branch_id}",
        "parent_branch_id": None,
        "branch_point": {"year": year},
        "entries": list(entries or []),
    }


def _entry(entry_id: str, title: str, *, year: int = 2020) -> dict[str, Any]:
    return {
        "entry_id": entry_id,
        "time_start": str(year),
        "year": year,
        "title": title,
        "paper_title": title,
        "evidence_ids": [f"pmid:{entry_id}"],
    }


def _projection(*, anchors: list[Any], branches: list[Any]) -> dict[str, Any]:
    return {
        "projection": "chronicle_map",
        "topic": "repair test",
        "spine": {"year_anchors": anchors},
        "branches": branches,
        "unassigned_entry_ids": [],
    }


def _node_id_for_label(source: str, label: str) -> str:
    match = re.search(rf'^    ([A-Za-z][A-Za-z0-9_]*)\["{re.escape(label)}"\]$', source, re.MULTILINE)
    assert match is not None, f"missing Mermaid node label: {label}"
    return match.group(1)


def _correction_codes(result: Any) -> set[str]:
    return {item["code"] for item in result.corrections}


def test_anchor_cap_preserves_rendered_branch_point_years() -> None:
    anchors = [{"year": year} for year in range(1900, 1970)]
    projection = _projection(anchors=anchors, branches=[_branch("middle", year=1935)])

    result = render_chronicle_mermaid_projection(projection)
    year_id = _node_id_for_label(result.source, "1935")
    branch_id = _node_id_for_label(result.source, "Branch middle")

    assert f"    {year_id} -.-> {branch_id}" in result.source
    assert result.omitted_counts["year_anchors"] == 10
    assert "invalid_branch_year" not in _correction_codes(result)
    assert result.status == "fallback"
    assert any("year_anchors=10" in warning for warning in result.warnings)


def test_malformed_projection_rows_are_counted_and_disclosed() -> None:
    projection = _projection(
        anchors=["bad-anchor", None, {"year": 2020}],
        branches=[
            "bad-branch",
            None,
            _branch("valid", entries=["bad-entry", None, _entry("1", "Valid entry")]),
        ],
    )

    result = render_chronicle_mermaid_projection(projection)

    assert validate_mermaid_source(result.source)[0] is True
    assert result.status == "fallback"
    assert result.omitted_counts["malformed_year_anchor_rows"] == 2
    assert result.omitted_counts["malformed_branch_rows"] == 2
    assert result.omitted_counts["malformed_entry_rows"] == 2
    assert "malformed_projection_row" in _correction_codes(result)
    assert any("malformed_branch_rows=2" in warning for warning in result.warnings)


def test_minimal_fallback_records_all_hidden_graph_content() -> None:
    projection = _projection(
        anchors=[{"year": 2018}, {"year": 2020}],
        branches=[_branch("one", year=2018, entries=[_entry("1", "First", year=2018)])],
    )

    result = render_chronicle_mermaid_projection(projection, validator=lambda _source: False)

    assert result.tier == "minimal"
    assert result.omitted_counts["fallback_topic_nodes"] == 1
    assert result.omitted_counts["fallback_year_anchors"] == 2
    assert result.omitted_counts["fallback_branches"] == 1
    assert result.omitted_counts["fallback_entries"] == 1
    assert result.omitted_counts["fallback_edges"] == 4
    assert "minimal_fallback_omitted_graph" in _correction_codes(result)
    assert any("fallback_entries=1" in warning for warning in result.warnings)


def test_entry_budget_is_distributed_across_branches() -> None:
    branches = [
        _branch(
            str(branch_index),
            entries=[
                _entry(f"{branch_index}-{entry_index}", f"Event {branch_index}-{entry_index}")
                for entry_index in range(10)
            ],
        )
        for branch_index in range(24)
    ]
    projection = _projection(anchors=[{"year": 2020}], branches=branches)

    result = render_chronicle_mermaid_projection(projection)

    assert result.omitted_counts["entries"] == 120
    assert result.status == "fallback"
    for branch_index in range(24):
        assert f"Event {branch_index}-0" in result.source


def test_capped_branches_disclose_their_nested_entries() -> None:
    branches = [_branch(str(index)) for index in range(24)]
    branches.append(
        _branch(
            "omitted",
            entries=[_entry(str(index), f"Omitted {index}") for index in range(3)],
        )
    )

    result = render_chronicle_mermaid_projection(_projection(anchors=[{"year": 2020}], branches=branches))

    assert result.omitted_counts["branches"] == 1
    assert result.omitted_counts["entries_in_capped_branches"] == 3
    assert result.status == "fallback"


def test_nfc_normalization_preserves_scientific_super_and_subscripts() -> None:
    label = mermaid_label("m²; H₂O; Ca²⁺")

    assert "m²" in label
    assert "H₂O" in label
    assert "Ca²⁺" in label
    assert "m2" not in label


def test_year_strings_use_the_same_range_rules_as_integers() -> None:
    projection = _projection(
        anchors=[
            {"year": "0000"},
            {"year": "0001"},
            {"year": "9999"},
            {"year": "10000"},
            {"year": True},
            {"year": "²⁰²⁴"},
        ],
        branches=[],
    )

    result = render_chronicle_mermaid_projection(projection)

    _node_id_for_label(result.source, "1")
    _node_id_for_label(result.source, "9999")
    assert result.omitted_counts["invalid_year_anchors"] == 4
    assert "invalid_year_anchor" in _correction_codes(result)
    assert result.status == "fallback"


def test_full_size_multibyte_labels_keep_the_graph_instead_of_forcing_minimal_fallback() -> None:
    label = "研究脈絡🧬免疫療法臨床轉譯" * 20
    branches = [
        {
            **_branch(
                str(branch_index),
                year=1900 + branch_index,
                entries=[
                    _entry(
                        f"{branch_index}-{entry_index}",
                        label,
                        year=1900 + branch_index + entry_index,
                    )
                    for entry_index in range(5)
                ],
            ),
            "name": label,
            "lineage_basis": "mesh_terms",
        }
        for branch_index in range(24)
    ]
    projection = _projection(
        anchors=[{"year": 1900 + index} for index in range(60)],
        branches=branches,
    )
    projection["topic"] = label

    result = render_chronicle_mermaid_projection(projection)

    assert result.tier == "rich"
    assert validate_mermaid_source(result.source)[0] is True
    assert len(result.source.encode("utf-8")) <= 49_000
    assert result.source.count("n_entry_") > 100
    assert "label_truncated" in _correction_codes(result)


def test_seeded_hostile_projections_are_deterministic_bounded_and_renderable() -> None:
    """Keep a small property-style repair corpus in the normal test suite."""
    rng = random.Random(20260812)
    hostile_labels = [
        'quoted "label" [x] (y) --> z',
        "研究脈絡🧬\n第二行",
        "%%{init: {'theme':'dark'}}%% <script>alert(1)</script>",
        "bidi\u202e zero\u200b control\x00 surrogate\ud800",
        "A & B < C > D # semicolon; colon:",
    ]
    year_values: list[Any] = [None, True, -1, 0, 1999, 2024, 10000, "2020", "not-a-year"]

    for case_index in range(75):
        branch_count = rng.randrange(0, 32)
        branches: list[Any] = []
        branch_ids = [f"branch-{rng.randrange(0, max(1, branch_count // 2 + 1))}" for _ in range(branch_count)]
        for branch_index, branch_id in enumerate(branch_ids):
            if rng.random() < 0.08:
                branches.append("malformed branch")
                continue
            entries: list[Any] = []
            for entry_index in range(rng.randrange(0, 9)):
                if rng.random() < 0.08:
                    entries.append(None)
                    continue
                title = rng.choice(hostile_labels) * rng.randrange(1, 5)
                entries.append(
                    {
                        "entry_id": f"entry-{rng.randrange(0, 12)}",
                        "time_start": str(rng.choice(year_values)),
                        "title": title,
                        "paper_title": rng.choice(hostile_labels),
                        "evidence_ids": [f"pmid:{case_index}{branch_index}{entry_index}"],
                    }
                )
            parent = rng.choice([None, branch_id, "missing", *branch_ids]) if branch_ids else None
            branches.append(
                {
                    "branch_id": branch_id,
                    "name": rng.choice(hostile_labels),
                    "parent_branch_id": parent,
                    "branch_point": {"year": rng.choice(year_values)},
                    "entries": entries,
                }
            )

        projection = _projection(
            anchors=[{"year": rng.choice(year_values)} for _ in range(rng.randrange(0, 70))],
            branches=branches,
        )
        projection["topic"] = rng.choice(hostile_labels)

        first = render_chronicle_mermaid_projection(projection)
        second = render_chronicle_mermaid_projection(projection)

        assert first.source == second.source
        assert first.corrections == second.corrections
        assert first.omitted_counts == second.omitted_counts
        assert len(first.source.encode("utf-8")) <= 49_000
        valid, issues = validate_mermaid_source(first.source)
        assert valid, (case_index, issues, first.source)
