"""Build the typed chronicle provenance graph.

The graph is deliberately narrow: it connects the topic, its branches, its
entries, and the evidence behind each entry, plus optional session/pipeline/
artifact provenance nodes. Every edge is validated against the invariants
declared in the domain layer, so an unusable graph fails the audit instead of
silently producing a misleading picture.
"""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING

from pubmed_search.domain.entities.chronicle import (
    ChronicleEdgeType,
    ChronicleGraph,
    ChronicleGraphEdge,
    ChronicleGraphNode,
    ChronicleNodeType,
    resolve_chronicle_membership,
)

from .ordering import chronology_key, definitely_precedes

if TYPE_CHECKING:
    from pubmed_search.domain.entities.chronicle import ChronicleSnapshot


def topic_node_id(chronicle_id: str) -> str:
    """Return the graph node ID for a chronicle's topic node."""
    return f"topic:{chronicle_id}"


def branch_node_id(branch_id: str) -> str:
    """Return the graph node ID for a branch."""
    return f"branch:{branch_id}"


def build_chronicle_graph(snapshot: ChronicleSnapshot) -> ChronicleGraph:
    """Build the provenance graph for *snapshot*.

    Args:
        snapshot: A snapshot with entries and branches already assembled.

    Returns:
        A deduplicated :class:`ChronicleGraph`. Endpoint and edge-type
        invariants are guaranteed by construction; call ``graph.validate()`` to
        re-check after any manual edit.
    """
    graph = ChronicleGraph()

    topic_id = topic_node_id(snapshot.chronicle_id)
    graph.add_node(
        ChronicleGraphNode(
            node_id=topic_id,
            node_type=ChronicleNodeType.TOPIC,
            label=snapshot.topic,
            attributes=(("chronicle_id", snapshot.chronicle_id), ("revision", snapshot.revision)),
        )
    )

    for branch in snapshot.branches:
        node_id = branch_node_id(branch.branch_id)
        lineage_basis = next(
            (tag.split(":", 1)[1] for tag in branch.tags if tag.startswith("lineage_basis:")),
            None,
        )
        graph.add_node(
            ChronicleGraphNode(
                node_id=node_id,
                node_type=ChronicleNodeType.BRANCH,
                label=branch.name,
                attributes=(
                    ("entry_count", len(branch.entry_ids)),
                    ("confidence", round(branch.confidence, 3)),
                    ("lineage_basis", lineage_basis),
                ),
            )
        )
        if branch.parent_branch_id:
            graph.add_edge(
                ChronicleGraphEdge(
                    source=node_id,
                    target=branch_node_id(branch.parent_branch_id),
                    edge_type=ChronicleEdgeType.BRANCHES_FROM,
                )
            )
        else:
            graph.add_edge(
                ChronicleGraphEdge(
                    source=topic_id,
                    target=node_id,
                    edge_type=ChronicleEdgeType.CONTAINS,
                )
            )

    membership = resolve_chronicle_membership(snapshot)
    for entry_index, entry in enumerate(snapshot.entries):
        graph.add_node(
            ChronicleGraphNode(
                node_id=entry.entry_id,
                node_type=ChronicleNodeType.ENTRY,
                label=entry.title,
                attributes=(
                    ("entry_type", entry.entry_type.value),
                    ("time_start", entry.time_start),
                    ("status", entry.status.value),
                    ("confidence", round(entry.confidence, 3)),
                ),
            )
        )
        branch_index = membership.branch_index_by_entry[entry_index]
        if branch_index is not None:
            graph.add_edge(
                ChronicleGraphEdge(
                    source=branch_node_id(snapshot.branches[branch_index].branch_id),
                    target=entry.entry_id,
                    edge_type=ChronicleEdgeType.CONTAINS,
                )
            )

        _add_evidence_edges(graph, entry)

    _add_chronological_edges(graph, snapshot, membership.branch_index_by_entry)
    _add_provenance_edges(graph, snapshot, topic_id)
    return graph


def _add_evidence_edges(graph: ChronicleGraph, entry: object) -> None:
    """Attach evidence nodes and their typed edges for one entry."""
    evidence = getattr(entry, "evidence", None)
    if evidence is None:
        return

    entry_id = str(getattr(entry, "entry_id", ""))
    roles = (
        (evidence.supporting_articles, ChronicleEdgeType.SUPPORTS),
        (evidence.contradicting_articles, ChronicleEdgeType.CONTRADICTS),
        (evidence.updating_articles, ChronicleEdgeType.UPDATES),
    )
    for articles, edge_type in roles:
        for article in articles:
            graph.add_node(
                ChronicleGraphNode(
                    node_id=article.evidence_id,
                    node_type=ChronicleNodeType.EVIDENCE,
                    label=article.title,
                    attributes=(
                        ("year", article.year),
                        ("source", article.source),
                        ("journal", article.journal),
                        ("citation_count", article.citation_count),
                    ),
                )
            )
            graph.add_edge(
                ChronicleGraphEdge(
                    source=article.evidence_id,
                    target=entry_id,
                    edge_type=edge_type,
                )
            )


def _add_chronological_edges(
    graph: ChronicleGraph,
    snapshot: ChronicleSnapshot,
    branch_index_by_entry: tuple[int | None, ...],
) -> None:
    """Link only provably ordered consecutive entries within valid branches."""
    by_branch: dict[int, list[object]] = {}
    for entry_index, entry in enumerate(snapshot.entries):
        branch_index = branch_index_by_entry[entry_index]
        if branch_index is not None:
            by_branch.setdefault(branch_index, []).append(entry)

    for ordered in by_branch.values():
        ordered.sort(key=chronology_key)
        for previous, current in pairwise(ordered):
            if not definitely_precedes(previous, current):
                continue
            graph.add_edge(
                ChronicleGraphEdge(
                    source=str(getattr(previous, "entry_id", "")),
                    target=str(getattr(current, "entry_id", "")),
                    edge_type=ChronicleEdgeType.PRECEDES,
                )
            )


def _add_provenance_edges(graph: ChronicleGraph, snapshot: ChronicleSnapshot, topic_id: str) -> None:
    """Attach pipeline-run and upstream-artifact provenance nodes."""
    for run_id in snapshot.input_scope.pipeline_run_ids:
        node_id = f"pipeline_run:{run_id}"
        graph.add_node(ChronicleGraphNode(node_id=node_id, node_type=ChronicleNodeType.PIPELINE_RUN, label=run_id))
        graph.add_edge(
            ChronicleGraphEdge(
                source=topic_id,
                target=node_id,
                edge_type=ChronicleEdgeType.DERIVED_FROM_PIPELINE_RUN,
            )
        )

    for artifact_uri in snapshot.input_scope.source_artifact_uris:
        node_id = f"artifact:{artifact_uri}"
        graph.add_node(ChronicleGraphNode(node_id=node_id, node_type=ChronicleNodeType.ARTIFACT, label=artifact_uri))
        graph.add_edge(
            ChronicleGraphEdge(
                source=topic_id,
                target=node_id,
                edge_type=ChronicleEdgeType.PERSISTED_AS_ARTIFACT,
            )
        )


__all__ = ["branch_node_id", "build_chronicle_graph", "topic_node_id"]
