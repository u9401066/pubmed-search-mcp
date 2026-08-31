"""Export runtime-generated Mermaid diagrams for the pinned CI renderer."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from pubmed_search.application.chronicle import render_chronicle_mermaid_projection
from pubmed_search.application.visualization import MermaidGraphBuilder, render_mermaid_graph


def _base_projection() -> dict[str, Any]:
    return {
        "projection": "chronicle_map",
        "topic": "IL-6 / JAK–STAT translational research",
        "spine": {
            "year_anchors": [
                {"year": 1994, "entry_ids": ["entry-1"]},
                {"year": 2001, "entry_ids": ["entry-2"]},
                {"year": 2024, "entry_ids": ["entry-3"]},
            ]
        },
        "branches": [
            {
                "branch_id": "mechanism",
                "name": "Mechanism",
                "lineage_basis": "mesh",
                "parent_branch_id": None,
                "branch_point": {"year": 1994},
                "entries": [
                    {
                        "entry_id": "entry-1",
                        "time_start": "1994",
                        "title": "Pathway discovery",
                        "paper_title": "JAK–STAT signaling",
                        "evidence_ids": ["pmid:1"],
                    }
                ],
            },
            {
                "branch_id": "clinical",
                "name": "Clinical translation",
                "lineage_basis": "keyword",
                "parent_branch_id": "mechanism",
                "branch_point": {"year": 2001},
                "entries": [
                    {
                        "entry_id": "entry-2",
                        "time_start": "2001",
                        "title": "Proof of concept",
                        "paper_title": "First clinical cohort",
                        "evidence_ids": ["doi:10.1/example"],
                    },
                    {
                        "entry_id": "entry-3",
                        "time_start": "2024",
                        "title": "Meta-analysis",
                        "paper_title": "Long-term outcomes",
                        "evidence_ids": ["pmcid:PMC3"],
                    },
                ],
            },
        ],
        "unassigned_entry_ids": [],
    }


def build_smoke_fixtures() -> dict[str, str]:
    """Return every Mermaid tier emitted by canonical public tools."""
    rich = render_chronicle_mermaid_projection(_base_projection()).source

    citation_builder = MermaidGraphBuilder()
    citation_root = citation_builder.add_node(
        "pmid",
        "1",
        "Root [trial]\r\n%%{init: {}}%% ``` \u202e — PMID 1",
        "root",
    )
    citing = citation_builder.add_node("pmid", "2", "Citing paper — PMID 2", "citing")
    reference = citation_builder.add_node("pmid", "3", "Reference paper — PMID 3", "reference")
    shared = citation_builder.add_node("pmid", "4", "Convergent paper — PMID 4", "shared")
    citation_builder.add_edge(citing, citation_root)
    citation_builder.add_edge(citation_root, reference)
    citation_builder.add_edge(shared, citing)
    citation_builder.add_edge(shared, reference)
    citation = render_mermaid_graph(
        citation_builder.graph,
        direction="TD",
        style_roles=("root", "citing", "reference", "shared", "notice"),
        repairs=citation_builder.repairs,
        omitted=citation_builder.omitted,
    ).source

    multibyte_label = "研究脈絡🧬免疫療法臨床轉譯" * 20
    byte_budget_projection: dict[str, Any] = {
        "projection": "chronicle_map",
        "topic": multibyte_label,
        "spine": {"year_anchors": [{"year": 1900 + index} for index in range(60)]},
        "branches": [
            {
                "branch_id": f"branch-{branch_index}",
                "name": multibyte_label,
                "lineage_basis": "mesh_terms",
                "parent_branch_id": None,
                "branch_point": {"year": 1900 + branch_index},
                "entries": [
                    {
                        "entry_id": f"entry-{branch_index}-{entry_index}",
                        "time_start": str(1900 + branch_index + entry_index),
                        "title": multibyte_label,
                        "paper_title": multibyte_label,
                        "evidence_ids": [f"pmid:{branch_index}{entry_index}"],
                    }
                    for entry_index in range(5)
                ],
            }
            for branch_index in range(24)
        ],
        "unassigned_entry_ids": [],
    }
    byte_budget_result = render_chronicle_mermaid_projection(byte_budget_projection)
    if byte_budget_result.tier != "rich" or len(byte_budget_result.source.encode("utf-8")) >= 49_000:
        raise RuntimeError("multibyte label Mermaid byte-budget fixture contract failed")
    byte_budget = byte_budget_result.source

    adversarial_projection = _base_projection()
    hostile = 'IL-6 [95% CI] p<0.001 "quoted" %%{init}%% <script> 🧬\nline two'
    adversarial_projection["topic"] = hostile
    adversarial_projection["branches"][0]["name"] = hostile
    adversarial_projection["branches"][0]["entries"][0]["title"] = hostile
    repaired = render_chronicle_mermaid_projection(adversarial_projection).source

    validation_calls = 0

    def accept_safe(source: str) -> bool:
        nonlocal validation_calls
        del source
        validation_calls += 1
        return validation_calls > 1

    safe = render_chronicle_mermaid_projection(_base_projection(), validator=accept_safe).source
    minimal = render_chronicle_mermaid_projection(_base_projection(), validator=lambda _source: False).source

    return {
        "citation-rich.mmd": citation,
        "chronicle-byte-budget.mmd": byte_budget,
        "chronicle-rich.mmd": rich,
        "chronicle-repaired.mmd": repaired,
        "chronicle-safe.mmd": safe,
        "chronicle-minimal.mmd": minimal,
    }


def export_smoke_fixtures(output_dir: Path) -> list[Path]:
    """Write smoke fixtures and return their paths in deterministic order."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for filename, source in sorted(build_smoke_fixtures().items()):
        target = output_dir / filename
        target.write_text(source.rstrip() + "\n", encoding="utf-8")
        written.append(target)
    return written


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path, help="Directory that receives generated .mmd fixtures")
    args = parser.parse_args()
    written = export_smoke_fixtures(args.output_dir)
    print(f"Exported {len(written)} Mermaid smoke fixtures to {args.output_dir}")


if __name__ == "__main__":
    main()
