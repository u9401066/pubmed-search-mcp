"""Projections derived from a chronicle snapshot.

The chronicle is the source of truth; timeline, lineage tree, and graph views
are read models generated here. Every projection references the same
``entry_id`` values so agents can cross-link between views.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pubmed_search.domain.entities.chronicle import resolve_chronicle_membership

from .mermaid import MermaidRenderResult, mermaid_label, render_chronicle_mermaid_projection
from .ordering import chronology_key

if TYPE_CHECKING:
    from pubmed_search.domain.entities.chronicle import ChronicleBranch, ChronicleSnapshot

_MAX_LINEAGE_TREE_DEPTH = 128
_MAX_LINEAGE_TREE_BRANCHES = 10_000
_LEGACY_MERMAID_MAX_BYTES = 48_000
_LEGACY_MERMAID_NOTICE_RESERVE_BYTES = 512
_LEGACY_TIMELINE_MAX_EVENTS = 240
_LEGACY_MINDMAP_MAX_BRANCHES = 64
_LEGACY_MINDMAP_MAX_EVENTS = 96
_LEGACY_MINDMAP_MAX_NODES = 160
_LEGACY_MINDMAP_MAX_DEPTH = 12


@dataclass(frozen=True)
class _LineageProjectionIndex:
    """Occurrence-aware, cycle-free branch hierarchy used by projections."""

    parent_indices: tuple[int | None, ...]
    child_indices: tuple[tuple[int, ...], ...]
    root_indices: tuple[int, ...]
    traversal_order: tuple[int, ...]
    depths: tuple[int, ...]
    diagnostics: dict[str, Any]


def _index_lineage(branches: list[ChronicleBranch]) -> _LineageProjectionIndex:
    """Resolve branch parents without collapsing duplicate branch IDs."""
    occurrences: dict[str, list[int]] = {}
    for index, branch in enumerate(branches):
        occurrences.setdefault(branch.branch_id, []).append(index)

    duplicate_ids = sorted(branch_id for branch_id, indices in occurrences.items() if len(indices) > 1)
    parent_indices: list[int | None] = [None] * len(branches)
    ambiguous_references: list[dict[str, Any]] = []
    orphan_references: list[dict[str, Any]] = []

    for index, branch in enumerate(branches):
        parent_id = branch.parent_branch_id
        if parent_id is None:
            continue
        candidates = occurrences.get(parent_id, [])
        if len(candidates) == 1:
            parent_indices[index] = candidates[0]
        elif candidates:
            ambiguous_references.append(
                {
                    "branch_index": index,
                    "branch_id": branch.branch_id,
                    "parent_branch_id": parent_id,
                    "candidate_branch_indices": list(candidates),
                }
            )
        else:
            orphan_references.append(
                {
                    "branch_index": index,
                    "branch_id": branch.branch_id,
                    "parent_branch_id": parent_id,
                }
            )

    cycles_broken: list[dict[str, Any]] = []
    resolved: set[int] = set()
    for start in range(len(branches)):
        if start in resolved:
            continue
        path: list[int] = []
        positions: dict[int, int] = {}
        current: int | None = start
        while current is not None and current not in resolved and current not in positions:
            positions[current] = len(path)
            path.append(current)
            current = parent_indices[current]

        if current is not None and current in positions:
            cycle = path[positions[current] :]
            detached = min(cycle)
            parent_indices[detached] = None
            cycles_broken.append(
                {
                    "branch_indices": list(cycle),
                    "branch_ids": [branches[index].branch_id for index in cycle],
                    "detached_branch_index": detached,
                }
            )
        resolved.update(path)

    child_lists: list[list[int]] = [[] for _branch in branches]
    root_indices: list[int] = []
    for index, parent_index in enumerate(parent_indices):
        if parent_index is None:
            root_indices.append(index)
        else:
            child_lists[parent_index].append(index)

    depths = [0] * len(branches)
    traversal_order: list[int] = []
    pending = list(reversed(root_indices))
    while pending:
        index = pending.pop()
        traversal_order.append(index)
        parent_index = parent_indices[index]
        depths[index] = 0 if parent_index is None else depths[parent_index] + 1
        pending.extend(reversed(child_lists[index]))

    max_depth = max(depths, default=0)
    diagnostics = {
        "branch_count": len(branches),
        "duplicate_branch_ids": duplicate_ids,
        "duplicate_branch_id_counts": {branch_id: len(occurrences[branch_id]) for branch_id in duplicate_ids},
        "ambiguous_parent_references": ambiguous_references,
        "orphan_parent_references": orphan_references,
        "cycles_broken": cycles_broken,
        "max_depth": max_depth,
        "depth_limit": _MAX_LINEAGE_TREE_DEPTH,
        "depth_limit_exceeded": max_depth > _MAX_LINEAGE_TREE_DEPTH,
    }
    return _LineageProjectionIndex(
        parent_indices=tuple(parent_indices),
        child_indices=tuple(tuple(indices) for indices in child_lists),
        root_indices=tuple(root_indices),
        traversal_order=tuple(traversal_order),
        depths=tuple(depths),
        diagnostics=diagnostics,
    )


def _entry_sort_key(entry: Any) -> tuple[int, int, int, int, int]:
    """Return the stable ordering shared by Chronicle map rows."""
    return chronology_key(entry)


def _map_entry_row(entry: Any, global_order: int, branch_order: int | None) -> dict[str, Any]:
    """Return one complete Chronicle map entry row."""
    articles = entry.evidence.all_articles
    return {
        "entry_id": entry.entry_id,
        "year": entry.year,
        "time_start": entry.time_start,
        "title": entry.title,
        "paper_title": articles[0].title if articles else entry.title,
        "entry_type": entry.entry_type.value,
        "status": entry.status.value,
        "global_order": global_order,
        "branch_order": branch_order,
        "evidence_ids": [article.evidence_id for article in articles],
    }


def project_timeline(snapshot: ChronicleSnapshot) -> dict[str, Any]:
    """Project the chronicle as a chronological timeline.

    Args:
        snapshot: The revision to project.

    Returns:
        A JSON-ready dict with ordered events and per-year counts.
    """
    membership = resolve_chronicle_membership(snapshot)
    ordered_indices = sorted(range(len(snapshot.entries)), key=lambda index: chronology_key(snapshot.entries[index]))
    events: list[dict[str, Any]] = []
    for entry_index in ordered_indices:
        entry = snapshot.entries[entry_index]
        branch_index = membership.branch_index_by_entry[entry_index]
        event = {
            "entry_id": entry.entry_id,
            "year": entry.year,
            "time_start": entry.time_start,
            "time_end": entry.time_end,
            "title": entry.title,
            "entry_type": entry.entry_type.value,
            "status": entry.status.value,
            "branch_id": snapshot.branches[branch_index].branch_id if branch_index is not None else None,
            "declared_branch_id": entry.branch_id,
            "confidence": round(entry.confidence, 3),
            "summary_claim": entry.summary_claim,
            "evidence_ids": [a.evidence_id for a in entry.evidence.all_articles],
        }
        reasons = membership.repair_reasons_by_entry[entry_index]
        if reasons:
            event["membership_repair_reasons"] = list(reasons)
        events.append(event)

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
    membership = resolve_chronicle_membership(snapshot)
    global_rank = {
        entry_index: order
        for order, entry_index in enumerate(
            sorted(range(len(snapshot.entries)), key=lambda index: chronology_key(snapshot.entries[index]))
        )
    }
    lineage = _index_lineage(snapshot.branches)

    def _node(branch_index: int) -> dict[str, Any]:
        branch = snapshot.branches[branch_index]
        entry_indices = list(membership.branch_entry_indices[branch_index])
        entry_indices.sort(key=lambda index: (chronology_key(snapshot.entries[index]), global_rank[index]))
        entries = [snapshot.entries[index] for index in entry_indices]
        return {
            "branch_id": branch.branch_id,
            "name": branch.name,
            "description": branch.description,
            "parent_branch_id": branch.parent_branch_id,
            "confidence": round(branch.confidence, 3),
            "tags": list(branch.tags),
            "lineage_basis": _tag_value(branch.tags, "lineage_basis"),
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
            "children": [],
        }

    roots: list[dict[str, Any]] = []
    projected_indices: set[int] = set()
    pending: list[tuple[int, list[dict[str, Any]], int]] = [
        (branch_index, roots, 0) for branch_index in reversed(lineage.root_indices)
    ]
    while pending and len(projected_indices) < _MAX_LINEAGE_TREE_BRANCHES:
        branch_index, target, depth = pending.pop()
        if depth > _MAX_LINEAGE_TREE_DEPTH:
            continue
        node = _node(branch_index)
        target.append(node)
        projected_indices.add(branch_index)
        if depth == _MAX_LINEAGE_TREE_DEPTH:
            continue
        pending.extend(
            (child_index, node["children"], depth + 1) for child_index in reversed(lineage.child_indices[branch_index])
        )

    projection_diagnostics = dict(lineage.diagnostics)
    truncated_count = len(snapshot.branches) - len(projected_indices)
    projection_diagnostics.update(
        {
            "projected_branch_count": len(projected_indices),
            "truncated_branch_count": truncated_count,
            "branch_limit": _MAX_LINEAGE_TREE_BRANCHES,
            "truncated": truncated_count > 0,
        }
    )
    unassigned_indices = sorted(membership.repaired_entry_indices, key=lambda index: global_rank[index])
    unassigned = [snapshot.entries[index].entry_id for index in unassigned_indices]
    return {
        "projection": "lineage_tree",
        "chronicle_id": snapshot.chronicle_id,
        "revision": snapshot.revision,
        "topic": snapshot.topic,
        "branches": roots,
        "unassigned_entry_ids": unassigned,
        "unassigned_entries": [
            {
                "entry_id": snapshot.entries[index].entry_id,
                "year": snapshot.entries[index].year,
                "time_start": snapshot.entries[index].time_start,
                "title": snapshot.entries[index].title,
                "entry_type": snapshot.entries[index].entry_type.value,
                "status": snapshot.entries[index].status.value,
                "global_order": global_rank[index] + 1,
                "repair_reasons": list(membership.repair_reasons_by_entry[index]),
            }
            for index in unassigned_indices
        ],
        "membership_diagnostics": _membership_diagnostics(snapshot, membership),
        "lineage_diagnostics": snapshot.metadata.get("lineage_diagnostics", {}),
        "projection_diagnostics": projection_diagnostics,
    }


def project_chronicle_map(snapshot: ChronicleSnapshot) -> dict[str, Any]:
    """Project one horizontal time spine with auditable lineage branches.

    Unlike the separate timeline and tree projections, this read model keeps
    both dimensions in one coordinate contract.  Year anchors form the primary
    horizontal spine.  Every branch records the year at which its first dated
    paper appears, and every paper records both global and within-branch order.
    Renderers can therefore show divergence without losing chronology.
    """
    membership = resolve_chronicle_membership(snapshot)
    ordered_entry_indices = sorted(
        range(len(snapshot.entries)), key=lambda index: _entry_sort_key(snapshot.entries[index])
    )
    ordered_entries = [snapshot.entries[index] for index in ordered_entry_indices]
    global_order = {entry_index: order for order, entry_index in enumerate(ordered_entry_indices, start=1)}
    year_entries: dict[int, list[str]] = {}
    for entry in ordered_entries:
        if entry.year is not None:
            year_entries.setdefault(entry.year, []).append(entry.entry_id)

    lineage = _index_lineage(snapshot.branches)
    branch_entry_indices: list[list[int]] = []
    earliest_descendant: list[tuple[int, Any] | None] = []
    for branch_index, _branch in enumerate(snapshot.branches):
        indices = list(membership.branch_entry_indices[branch_index])
        indices.sort(key=lambda index: (_entry_sort_key(snapshot.entries[index]), global_order[index]))
        branch_entry_indices.append(indices)
        earliest_descendant.append(
            min(
                ((index, snapshot.entries[index]) for index in indices if snapshot.entries[index].year is not None),
                key=lambda item: (_entry_sort_key(item[1]), global_order[item[0]]),
                default=None,
            )
        )

    for branch_index in reversed(lineage.traversal_order):
        parent_index = lineage.parent_indices[branch_index]
        candidate = earliest_descendant[branch_index]
        if parent_index is None or candidate is None:
            continue
        current = earliest_descendant[parent_index]
        if current is None or (_entry_sort_key(candidate[1]), global_order[candidate[0]]) < (
            _entry_sort_key(current[1]),
            global_order[current[0]],
        ):
            earliest_descendant[parent_index] = candidate

    branch_rows: list[dict[str, Any]] = []
    for branch_index, branch in enumerate(snapshot.branches):
        entry_indices = branch_entry_indices[branch_index]
        first_pair = earliest_descendant[branch_index]
        first_index = first_pair[0] if first_pair else None
        first_entry = first_pair[1] if first_pair else None
        branch_rows.append(
            {
                "branch_id": branch.branch_id,
                "name": branch.name,
                "description": branch.description,
                "parent_branch_id": branch.parent_branch_id,
                "lineage_basis": _tag_value(branch.tags, "lineage_basis"),
                "confidence": round(branch.confidence, 3),
                "branch_point": {
                    "year": first_entry.year if first_entry else None,
                    "entry_id": first_entry.entry_id if first_entry else None,
                    "global_order": global_order.get(first_index) if first_index is not None else None,
                },
                "entries": [
                    _map_entry_row(snapshot.entries[index], global_order[index], branch_order)
                    for branch_order, index in enumerate(entry_indices, start=1)
                ],
                "child_branch_ids": [
                    snapshot.branches[child_index].branch_id for child_index in lineage.child_indices[branch_index]
                ],
            }
        )

    repaired_indices = sorted(membership.repaired_entry_indices, key=lambda index: global_order[index])
    repaired_rows = [_map_entry_row(snapshot.entries[index], global_order[index], None) for index in repaired_indices]
    root_branch_ids = [snapshot.branches[index].branch_id for index in lineage.root_indices]
    if repaired_rows:
        first_repaired = next((row for row in repaired_rows if row["year"] is not None), None)
        repair_branch_id = "projection-repaired-unassigned"
        branch_rows.append(
            {
                "branch_id": repair_branch_id,
                "name": "Unassigned / Repaired",
                "description": "Entries whose redundant branch ownership could not be reconciled without guessing.",
                "parent_branch_id": None,
                "lineage_basis": "projection_repair",
                "confidence": 0.0,
                "branch_point": {
                    "year": first_repaired["year"] if first_repaired else None,
                    "entry_id": first_repaired["entry_id"] if first_repaired else None,
                    "global_order": first_repaired["global_order"] if first_repaired else None,
                },
                "entries": repaired_rows,
                "child_branch_ids": [],
                "synthetic": True,
            }
        )
        root_branch_ids.append(repair_branch_id)

    branch_rows.sort(
        key=lambda branch: (
            branch["branch_point"]["global_order"] or len(snapshot.entries) + 1,
            branch["name"].casefold(),
            branch["branch_id"],
        )
    )
    return {
        "projection": "chronicle_map",
        "layout": "horizontal_time_spine_with_lineage_branches",
        "chronicle_id": snapshot.chronicle_id,
        "revision": snapshot.revision,
        "topic": snapshot.topic,
        "year_range": list(snapshot.year_range) if snapshot.year_range else None,
        "spine": {
            "orientation": "horizontal",
            "ordered_entry_ids": [entry.entry_id for entry in ordered_entries],
            "year_anchors": [
                {"year": year, "entry_ids": entry_ids} for year, entry_ids in sorted(year_entries.items())
            ],
        },
        "root_branch_ids": root_branch_ids,
        "branches": branch_rows,
        "unassigned_entry_ids": [snapshot.entries[index].entry_id for index in repaired_indices],
        "unassigned_entries": repaired_rows,
        "membership_diagnostics": _membership_diagnostics(snapshot, membership),
        "lineage_diagnostics": snapshot.metadata.get("lineage_diagnostics", {}),
        "projection_diagnostics": lineage.diagnostics,
        "mermaid_validation": snapshot.metadata.get("mermaid_validation", {}),
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
    """Render a bounded, delimiter-safe Mermaid ``timeline`` diagram."""
    lines = [
        "timeline",
        f"    title {mermaid_label(snapshot.topic, fallback='Research topic', limit=96)} Research Chronicle",
    ]
    dated_entries = sorted(
        (entry for entry in snapshot.entries if entry.year is not None),
        key=chronology_key,
    )
    rendered = 0
    previous_year: int | None = None
    for entry in dated_entries:
        if rendered >= _LEGACY_TIMELINE_MAX_EVENTS:
            break
        year = entry.year
        if year is None:  # narrowed above; retain a defensive boundary
            continue
        period = str(year) if year != previous_year else ""
        label = mermaid_label(entry.title, fallback="Research event", limit=96)
        candidate = f"    {period:4} : {label}"
        if not _legacy_line_fits(lines, candidate, reserve=_LEGACY_MERMAID_NOTICE_RESERVE_BYTES):
            break
        lines.append(candidate)
        rendered += 1
        previous_year = year

    omitted = len(snapshot.entries) - rendered
    if omitted:
        notice = mermaid_label(
            f"{omitted} events omitted — see chronicle_map.json",
            fallback="Events omitted",
            limit=96,
        )
        _append_legacy_notice(lines, f"    Summary : {notice}")
    return "\n".join(lines)


def render_chronicle_mermaid(snapshot: ChronicleSnapshot) -> str:
    """Render a repaired horizontal time spine with branching research lines."""
    return render_chronicle_mermaid_result(snapshot).source


def render_chronicle_mermaid_result(snapshot: ChronicleSnapshot) -> MermaidRenderResult:
    """Return Mermaid source together with normalization and fallback diagnostics."""
    projection = project_chronicle_map(snapshot)
    # Repaired entries are represented by a visible synthetic branch. Prevent
    # the renderer from also counting them as hidden/unassigned content.
    projection["unassigned_entry_ids"] = []
    return render_chronicle_mermaid_projection(projection)


def render_lineage_mindmap(snapshot: ChronicleSnapshot) -> str:
    """Render a bounded, cycle-safe Mermaid ``mindmap`` diagram."""
    tree = project_lineage_tree(snapshot)
    lines = [
        "mindmap",
        f'  root["{mermaid_label(snapshot.topic, fallback="Research topic", limit=96)}"]',
    ]
    counter = 0
    rendered_branches = 0
    rendered_entries = 0
    seen_nodes: set[int] = set()
    seen_entry_ids: set[str] = set()
    roots = tree.get("branches")
    pending: list[tuple[dict[str, Any], int]] = [
        (node, 1) for node in reversed(roots if isinstance(roots, list) else []) if isinstance(node, dict)
    ]
    size_exhausted = False

    while pending:
        node, depth = pending.pop()
        identity = id(node)
        if identity in seen_nodes or depth > _LEGACY_MINDMAP_MAX_DEPTH:
            continue
        seen_nodes.add(identity)
        if (
            rendered_branches >= _LEGACY_MINDMAP_MAX_BRANCHES
            or rendered_branches + rendered_entries >= _LEGACY_MINDMAP_MAX_NODES
        ):
            break

        counter += 1
        indent = "  " * (depth + 1)
        branch_label = mermaid_label(node.get("name"), fallback="Research line", limit=96)
        branch_line = f'{indent}branch_{counter}["{branch_label}"]'
        if not _legacy_line_fits(lines, branch_line, reserve=_LEGACY_MERMAID_NOTICE_RESERVE_BYTES):
            size_exhausted = True
            break
        lines.append(branch_line)
        rendered_branches += 1

        entries = node.get("entries")
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            entry_key = str(entry.get("entry_id") or f"anonymous-{id(entry)}")
            if entry_key in seen_entry_ids:
                continue
            if (
                rendered_entries >= _LEGACY_MINDMAP_MAX_EVENTS
                or rendered_branches + rendered_entries >= _LEGACY_MINDMAP_MAX_NODES
            ):
                break
            year = entry.get("year") or "Undated"
            label = mermaid_label(
                f"{year} — {entry.get('title') or 'Research event'}",
                fallback="Research event",
                limit=96,
            )
            counter += 1
            entry_line = f'{indent}  entry_{counter}["{label}"]'
            if not _legacy_line_fits(lines, entry_line, reserve=_LEGACY_MERMAID_NOTICE_RESERVE_BYTES):
                size_exhausted = True
                break
            lines.append(entry_line)
            seen_entry_ids.add(entry_key)
            rendered_entries += 1
        if size_exhausted:
            break

        children = node.get("children")
        if isinstance(children, list):
            pending.extend((child, depth + 1) for child in reversed(children) if isinstance(child, dict))

    raw_unassigned = tree.get("unassigned_entries")
    unassigned = raw_unassigned if isinstance(raw_unassigned, list) else []
    if unassigned and rendered_branches + rendered_entries < _LEGACY_MINDMAP_MAX_NODES:
        counter += 1
        repair_line = f'    branch_{counter}["Unassigned / Repaired"]'
        if _legacy_line_fits(lines, repair_line, reserve=_LEGACY_MERMAID_NOTICE_RESERVE_BYTES):
            lines.append(repair_line)
            for entry in unassigned:
                if not isinstance(entry, dict) or rendered_entries >= _LEGACY_MINDMAP_MAX_EVENTS:
                    continue
                entry_key = str(entry.get("entry_id") or f"anonymous-{id(entry)}")
                if entry_key in seen_entry_ids:
                    continue
                counter += 1
                label = mermaid_label(
                    f"{entry.get('time_start') or 'Undated'} — {entry.get('title') or 'Research event'}",
                    fallback="Research event",
                    limit=96,
                )
                entry_line = f'      entry_{counter}["{label}"]'
                if not _legacy_line_fits(lines, entry_line, reserve=_LEGACY_MERMAID_NOTICE_RESERVE_BYTES):
                    size_exhausted = True
                    break
                lines.append(entry_line)
                seen_entry_ids.add(entry_key)
                rendered_entries += 1

    omitted = max(0, len(snapshot.branches) - rendered_branches) + max(0, len(snapshot.entries) - rendered_entries)
    projection_diagnostics = tree.get("projection_diagnostics")
    diagnostics = projection_diagnostics if isinstance(projection_diagnostics, dict) else {}
    repaired_structure = any(
        diagnostics.get(key)
        for key in (
            "duplicate_branch_ids",
            "ambiguous_parent_references",
            "orphan_parent_references",
            "cycles_broken",
            "truncated",
        )
    )
    if omitted or repaired_structure:
        if omitted and repaired_structure:
            message = f"{omitted} visual items omitted; branch structure repaired — see chronicle_map.json"
        elif omitted:
            message = f"{omitted} visual items omitted — see chronicle_map.json"
        else:
            message = "Branch structure repaired — see chronicle_map.json"
        counter += 1
        notice = mermaid_label(message, fallback="Visualization simplified", limit=112)
        _append_legacy_notice(lines, f'    summary_{counter}["{notice}"]')
    return "\n".join(lines)


def _legacy_line_fits(lines: list[str], candidate: str, *, reserve: int = 0) -> bool:
    """Return whether appending one line stays below the Mermaid runtime limit."""
    current_bytes = len("\n".join(lines).encode("utf-8"))
    candidate_bytes = len(candidate.encode("utf-8")) + 1
    return current_bytes + candidate_bytes + reserve < _LEGACY_MERMAID_MAX_BYTES


def _append_legacy_notice(lines: list[str], notice: str) -> None:
    """Append a short visible notice while preserving the hard byte bound."""
    if _legacy_line_fits(lines, notice):
        lines.append(notice)


def _tag_value(tags: list[str], prefix: str) -> str | None:
    marker = f"{prefix}:"
    return next((tag[len(marker) :] for tag in tags if tag.startswith(marker)), None)


def _membership_diagnostics(snapshot: ChronicleSnapshot, membership: Any) -> dict[str, Any]:
    """Return JSON-ready ownership repairs without dropping entry occurrences."""
    repaired = [
        {
            "entry_index": index,
            "entry_id": snapshot.entries[index].entry_id,
            "declared_branch_id": snapshot.entries[index].branch_id,
            "reasons": list(membership.repair_reasons_by_entry[index]),
        }
        for index in membership.repaired_entry_indices
    ]
    return {
        "status": "repaired" if repaired or membership.dangling_memberships else "valid",
        "repaired_entries": repaired,
        "dangling_branch_memberships": [
            {
                "branch_index": branch_index,
                "branch_id": snapshot.branches[branch_index].branch_id,
                "entry_id": entry_id,
            }
            for branch_index, entry_id in membership.dangling_memberships
        ],
    }


__all__ = [
    "project_chronicle_map",
    "project_evidence",
    "project_graph",
    "project_lineage_tree",
    "project_timeline",
    "render_chronicle_mermaid",
    "render_chronicle_mermaid_result",
    "render_lineage_mindmap",
    "render_timeline_mermaid",
]
