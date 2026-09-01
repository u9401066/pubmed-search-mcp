"""Shared Mermaid safety-kernel regression tests."""

from __future__ import annotations

from pubmed_search.application.visualization import (
    MermaidGraph,
    MermaidGraphBuilder,
    MermaidLimits,
    MermaidNode,
    MermaidRepairLog,
    render_mermaid_graph,
    validate_mermaid_source,
)


def _codes(result) -> set[str]:
    return {row["code"] for row in result.corrections}


def test_builder_normalizes_crlf_bidi_directives_and_markdown_fences() -> None:
    builder = MermaidGraphBuilder()
    builder.add_node(
        "paper",
        "1",
        'Title\r\n    attack["x"] %%{init: {}}%% ``` \u202e',
        "event",
    )

    result = render_mermaid_graph(
        builder.graph,
        repairs=builder.repairs,
        omitted=builder.omitted,
        style_roles=("event",),
    )

    valid, issues = validate_mermaid_source(result.source)
    assert valid, issues
    assert "\r" not in result.source
    assert "%%{" not in result.source
    assert "```" not in result.source
    assert "\u202e" not in result.source
    assert "label_normalized" in _codes(result)
    assert "label_escaped" in _codes(result)


def test_invalid_manual_graph_falls_back_to_deterministic_minimal_source() -> None:
    graph = MermaidGraph(nodes=[MermaidNode('bad"]\nattack', 'x"]\nattack', "event")])

    first = render_mermaid_graph(graph, fallback_title="Safe", fallback_details="Use JSON")
    second = render_mermaid_graph(graph, fallback_title="Safe", fallback_details="Use JSON")

    assert first.tier == "minimal"
    assert first.source == second.source
    assert first.source_sha256 == second.source_sha256
    assert validate_mermaid_source(first.source)[0] is True
    assert {"rich_candidate_rejected", "safe_candidate_rejected"} <= _codes(first)


def test_node_and_edge_budgets_are_enforced_before_serialization() -> None:
    limits = MermaidLimits(max_nodes=2, max_edges=1)
    repairs = MermaidRepairLog()
    builder = MermaidGraphBuilder(repairs=repairs, limits=limits)
    first = builder.add_node("paper", "1", "One", "event")
    second = builder.add_node("paper", "2", "Two", "event")
    assert builder.add_node("paper", "3", "Three", "event") is None
    assert builder.add_edge(first, second) is True
    assert builder.add_edge(second, first) is False

    result = render_mermaid_graph(
        builder.graph,
        repairs=builder.repairs,
        omitted=builder.omitted,
        limits=limits,
    )

    assert result.status == "fallback"
    assert result.tier == "rich"
    assert result.omitted_counts == {"nodes": 1, "edges": 1}
    assert validate_mermaid_source(result.source, limits=limits)[0] is True


def test_validator_accepts_only_generated_lr_or_td_subset() -> None:
    assert validate_mermaid_source('flowchart TD\n    n_a["A"]')[0] is True
    assert validate_mermaid_source('graph TD\n    n_a["A"]')[0] is False
    assert validate_mermaid_source('flowchart LR\r\n    n_a["A"]')[0] is False
