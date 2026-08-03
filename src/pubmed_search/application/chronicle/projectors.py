"""Projections derived from a chronicle snapshot.

The chronicle is the source of truth; timeline, lineage tree, and graph views
are read models generated here. Every projection references the same
``entry_id`` values so agents can cross-link between views.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pubmed_search.domain.entities.chronicle import ChronicleBranch, ChronicleSnapshot

#: Mermaid-safe replacements for characters that break node labels.
_MERMAID_UNSAFE = {'"': "'", "\n": " ", "[": "(", "]": ")", "{": "(", "}": ")"}


def _mermaid_safe(text: str) -> str:
    """Return *text* with characters that break Mermaid labels replaced."""
    for needle, replacement in _MERMAID_UNSAFE.items():
        text = text.replace(needle, replacement)
    return text


def project_timeline(snapshot: ChronicleSnapshot) -> dict[str, Any]:
    """Project the chronicle as a chronological timeline.

    Args:
        snapshot: The revision to project.

    Returns:
        A JSON-ready dict with ordered events and per-year counts.
    """
    events = sorted(
        (
            {
                "entry_id": entry.entry_id,
                "year": entry.year,
                "time_start": entry.time_start,
                "time_end": entry.time_end,
                "title": entry.title,
                "entry_type": entry.entry_type.value,
                "status": entry.status.value,
                "branch_id": entry.branch_id,
                "confidence": round(entry.confidence, 3),
                "summary_claim": entry.summary_claim,
                "evidence_ids": [a.evidence_id for a in entry.evidence.all_articles],
            }
            for entry in snapshot.entries
        ),
        key=lambda item: (item["year"] or 0, item["entry_id"]),
    )

    activity: dict[str, int] = {}
    for event in events:
        if event["year"] is not None:
            activity[str(event["year"])] = activity.get(str(event["year"]), 0) + 1

    year_range = snapshot.year_range
    return {
        "projection": "timeline",
        "chronicle_id": snapshot.chronicle_id,
        "revision": snapshot.revision,
        "topic": snapshot.topic,
        "year_range": list(year_range) if year_range else None,
        "total_events": len(events),
        "activity_by_year": activity,
        "events": events,
    }


def project_lineage_tree(snapshot: ChronicleSnapshot) -> dict[str, Any]:
    """Project the chronicle as a nested branch/lineage tree.

    Args:
        snapshot: The revision to project.

    Returns:
        A JSON-ready dict with root branches, nested children, and any entries
        that could not be assigned to a branch.
    """
    entry_index = snapshot.entry_index
    children: dict[str | None, list[ChronicleBranch]] = {}
    for branch in snapshot.branches:
        children.setdefault(branch.parent_branch_id, []).append(branch)

    def _node(branch: ChronicleBranch) -> dict[str, Any]:
        entries = [entry_index[entry_id] for entry_id in branch.entry_ids if entry_id in entry_index]
        entries.sort(key=lambda entry: (entry.year or 0, entry.entry_id))
        return {
            "branch_id": branch.branch_id,
            "name": branch.name,
            "description": branch.description,
            "entry_count": len(entries),
            "entries": [
                {
                    "entry_id": entry.entry_id,
                    "year": entry.year,
                    "title": entry.title,
                    "entry_type": entry.entry_type.value,
                    "status": entry.status.value,
                }
                for entry in entries
            ],
            "children": [_node(child) for child in children.get(branch.branch_id, [])],
        }

    unassigned = [entry.entry_id for entry in snapshot.entries if not entry.branch_id]
    return {
        "projection": "lineage_tree",
        "chronicle_id": snapshot.chronicle_id,
        "revision": snapshot.revision,
        "topic": snapshot.topic,
        "branches": [_node(branch) for branch in children.get(None, [])],
        "unassigned_entry_ids": unassigned,
    }


def project_graph(snapshot: ChronicleSnapshot) -> dict[str, Any]:
    """Project the typed provenance graph with invariant violations attached.

    Args:
        snapshot: The revision to project.

    Returns:
        A JSON-ready dict containing nodes, edges, and any invariant violations.
    """
    payload = snapshot.graph.to_dict()
    payload.update(
        {
            "projection": "graph",
            "chronicle_id": snapshot.chronicle_id,
            "revision": snapshot.revision,
            "topic": snapshot.topic,
            "violations": snapshot.graph.validate(),
        }
    )
    return payload


def project_evidence(snapshot: ChronicleSnapshot) -> dict[str, Any]:
    """Project the deduplicated evidence table backing the chronicle.

    Args:
        snapshot: The revision to project.

    Returns:
        A JSON-ready dict mapping every evidence article to the entries it backs.
    """
    backing: dict[str, list[str]] = {}
    for entry in snapshot.entries:
        for article in entry.evidence.all_articles:
            backing.setdefault(article.evidence_id, []).append(entry.entry_id)

    articles = [
        {**article.to_dict(), "backs_entry_ids": backing.get(article.evidence_id, [])}
        for article in snapshot.evidence_articles
    ]
    return {
        "projection": "evidence",
        "chronicle_id": snapshot.chronicle_id,
        "revision": snapshot.revision,
        "topic": snapshot.topic,
        "total_articles": len(articles),
        "articles": articles,
    }


def render_timeline_mermaid(snapshot: ChronicleSnapshot) -> str:
    """Render the timeline projection as a Mermaid ``timeline`` diagram."""
    lines = ["timeline", f"    title {_mermaid_safe(snapshot.topic)} Research Chronicle"]
    by_year: dict[int, list[str]] = {}
    for entry in snapshot.entries:
        if entry.year is None:
            continue
        by_year.setdefault(entry.year, []).append(_mermaid_safe(entry.title).replace(":", " -"))

    for year in sorted(by_year):
        lines.append(f"    section {year}")
        lines.extend(f"        {label}" for label in by_year[year])
    return "\n".join(lines)


def render_lineage_mindmap(snapshot: ChronicleSnapshot) -> str:
    """Render the lineage tree as a Mermaid ``mindmap`` diagram."""
    tree = project_lineage_tree(snapshot)
    lines = ["mindmap", f"  root(({_mermaid_safe(snapshot.topic)}))"]

    def _walk(node: dict[str, Any], depth: int) -> None:
        indent = "  " * (depth + 1)
        lines.append(f"{indent}{_mermaid_safe(node['name'])}")
        for entry in node["entries"]:
            lines.append(f"{indent}  {entry['year']} {_mermaid_safe(entry['title'])}")
        for child in node["children"]:
            _walk(child, depth + 1)

    for branch in tree["branches"]:
        _walk(branch, 1)
    return "\n".join(lines)


__all__ = [
    "project_evidence",
    "project_graph",
    "project_lineage_tree",
    "project_timeline",
    "render_lineage_mindmap",
    "render_timeline_mermaid",
]
