"""Chronicle-specific assembly over the shared safe Mermaid renderer.

Mermaid is deliberately not invoked as a runtime dependency: MCP users may run
the Python server without Node.js or a browser. This module preserves Chronicle
branch and timeline semantics; generic escaping, budgets, structural lint, and
fallback rendering live in :mod:`pubmed_search.application.visualization`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from pubmed_search.application.visualization.mermaid import (
    MermaidGraph,
    MermaidGraphBuilder,
    MermaidRenderResult,
    MermaidRepairLog,
    MermaidValidator,
    mermaid_label,
    render_mermaid_graph,
    validate_mermaid_source,
)

_MAX_YEAR_ANCHORS = 60
_MAX_BRANCHES = 24
_MAX_ENTRIES = 120


@dataclass(frozen=True)
class _BranchRows:
    rows: list[dict[str, Any]]
    entries: list[list[dict[str, Any]]]
    points: list[dict[str, Any]]


@dataclass(frozen=True)
class _BranchIndex:
    keys: list[str]
    rows_by_key: dict[str, dict[str, Any]]
    entries_by_key: dict[str, list[dict[str, Any]]]
    points_by_key: dict[str, dict[str, Any]]
    first_key_by_raw_id: dict[str, str]


def render_chronicle_mermaid_projection(
    projection: dict[str, Any],
    *,
    validator: MermaidValidator | None = None,
    validator_name: str | None = None,
) -> MermaidRenderResult:
    """Normalize, validate, and render a chronicle-map projection.

    The optional validator is intended for tests or hosts that already embed a
    Mermaid parser. Runtime correctness never depends on it.
    """
    repairs = MermaidRepairLog()
    omitted: Counter[str] = Counter()
    warnings: list[str] = []
    try:
        graph = _build_graph(projection, repairs=repairs, omitted=omitted)
    except Exception as exc:  # defensive boundary: visual output must never abort a chronicle
        repairs.add("malformed_projection")
        warnings.append(f"Projection repair failed safely: {type(exc).__name__}")
        graph = MermaidGraph()

    return render_mermaid_graph(
        graph,
        direction="LR",
        style_roles=("topic", "spine", "branch", "event", "notice"),
        repairs=repairs,
        omitted=omitted,
        warnings=warnings,
        fallback_title="Research Chronicle",
        fallback_details="Visualization simplified; see chronicle_map.json",
        validator=validator,
        validator_name=validator_name,
    )


def _build_graph(
    projection: dict[str, Any],
    *,
    repairs: MermaidRepairLog,
    omitted: Counter[str],
) -> MermaidGraph:
    if not isinstance(projection, dict):
        raise TypeError("chronicle projection must be a mapping")

    builder = MermaidGraphBuilder(repairs=repairs, omitted=omitted)
    topic = projection.get("topic") or "Research Chronicle"
    topic_id = builder.add_node("topic", str(topic), topic, "topic")
    if topic_id is None:  # unreachable with an initially empty graph
        raise ValueError("topic node could not be created")

    branch_rows = _normalize_branch_rows(projection.get("branches"), repairs=repairs, omitted=omitted)
    priority_years = {year for point in branch_rows.points if (year := _coerce_year(point.get("year"))) is not None}
    year_nodes = _build_year_spine(
        projection.get("spine"),
        builder=builder,
        topic_id=topic_id,
        priority_years=priority_years,
    )
    branch_index = _index_branches(branch_rows, repairs=repairs)
    branch_nodes = _render_branches(
        branch_index,
        builder=builder,
        topic_id=topic_id,
        year_nodes=year_nodes,
        repairs=repairs,
    )
    _render_entries(branch_index, branch_nodes=branch_nodes, builder=builder)
    _record_unassigned(projection.get("unassigned_entry_ids"), repairs=repairs, omitted=omitted)
    _append_visual_notice(builder, topic_id=topic_id)
    return builder.graph


def _mark_malformed(
    category: str,
    *,
    repairs: MermaidRepairLog,
    omitted: Counter[str],
    count: int = 1,
) -> None:
    omitted[category] += count
    repairs.add("malformed_projection_row", count)


def _mapping_rows(
    raw: Any,
    *,
    row_category: str,
    collection_category: str,
    repairs: MermaidRepairLog,
    omitted: Counter[str],
) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        _mark_malformed(collection_category, repairs=repairs, omitted=omitted)
        return []
    rows = [row for row in raw if isinstance(row, dict)]
    malformed_count = len(raw) - len(rows)
    if malformed_count:
        _mark_malformed(row_category, repairs=repairs, omitted=omitted, count=malformed_count)
    return rows


def _normalize_branch_rows(
    raw_branches: Any,
    *,
    repairs: MermaidRepairLog,
    omitted: Counter[str],
) -> _BranchRows:
    rows = _mapping_rows(
        raw_branches,
        row_category="malformed_branch_rows",
        collection_category="malformed_branch_collections",
        repairs=repairs,
        omitted=omitted,
    )
    entries: list[list[dict[str, Any]]] = []
    points: list[dict[str, Any]] = []
    for row in rows:
        entries.append(
            _mapping_rows(
                row.get("entries"),
                row_category="malformed_entry_rows",
                collection_category="malformed_entry_collections",
                repairs=repairs,
                omitted=omitted,
            )
        )
        raw_point = row.get("branch_point")
        if raw_point is None:
            points.append({})
        elif isinstance(raw_point, dict):
            points.append(raw_point)
        else:
            points.append({})
            _mark_malformed("malformed_branch_points", repairs=repairs, omitted=omitted)

    if len(rows) <= _MAX_BRANCHES:
        return _BranchRows(rows, entries, points)
    omitted["branches"] += len(rows) - _MAX_BRANCHES
    omitted["entries_in_capped_branches"] += sum(len(branch_entries) for branch_entries in entries[_MAX_BRANCHES:])
    repairs.add("visual_size_capped")
    return _BranchRows(rows[:_MAX_BRANCHES], entries[:_MAX_BRANCHES], points[:_MAX_BRANCHES])


def _build_year_spine(
    raw_spine: Any,
    *,
    builder: MermaidGraphBuilder,
    topic_id: str,
    priority_years: set[int],
) -> dict[int, str]:
    if raw_spine is None:
        spine: dict[str, Any] = {}
    elif isinstance(raw_spine, dict):
        spine = raw_spine
    else:
        spine = {}
        _mark_malformed(
            "malformed_spine_collections",
            repairs=builder.repairs,
            omitted=builder.omitted,
        )
    anchor_rows = _mapping_rows(
        spine.get("year_anchors"),
        row_category="malformed_year_anchor_rows",
        collection_category="malformed_year_anchor_collections",
        repairs=builder.repairs,
        omitted=builder.omitted,
    )
    anchors = _deduplicate_year_anchors(anchor_rows, builder=builder)
    if len(anchors) > _MAX_YEAR_ANCHORS:
        original_count = len(anchors)
        anchors = _select_year_anchors(anchors, priority_years=priority_years)
        builder.omitted["year_anchors"] += original_count - len(anchors)
        builder.repairs.add("visual_size_capped")

    year_nodes: dict[int, str] = {}
    previous_id = topic_id
    for anchor in anchors:
        year = _coerce_year(anchor.get("year"))
        if year is None:  # construction invariant after anchor normalization
            continue
        year_id = builder.add_node("year", str(year), str(year), "spine")
        if year_id is None:
            continue
        year_nodes[year] = year_id
        builder.add_edge(previous_id, year_id, "spine")
        previous_id = year_id
    return year_nodes


def _deduplicate_year_anchors(
    anchor_rows: list[dict[str, Any]],
    *,
    builder: MermaidGraphBuilder,
) -> list[dict[str, Any]]:
    anchor_by_year: dict[int, dict[str, Any]] = {}
    for anchor in anchor_rows:
        year = _coerce_year(anchor.get("year"))
        if year is None:
            builder.omitted["invalid_year_anchors"] += 1
            builder.repairs.add("invalid_year_anchor")
        elif year in anchor_by_year:
            builder.omitted["duplicate_year_anchors"] += 1
            builder.repairs.add("invalid_year_anchor")
        else:
            anchor_by_year[year] = anchor
    return [anchor_by_year[year] for year in sorted(anchor_by_year)]


def _index_branches(branch_rows: _BranchRows, *, repairs: MermaidRepairLog) -> _BranchIndex:
    keys: list[str] = []
    rows_by_key: dict[str, dict[str, Any]] = {}
    entries_by_key: dict[str, list[dict[str, Any]]] = {}
    points_by_key: dict[str, dict[str, Any]] = {}
    first_key_by_raw_id: dict[str, str] = {}
    raw_id_counts: Counter[str] = Counter()
    for index, row in enumerate(branch_rows.rows):
        raw_id = str(row.get("branch_id") or f"branch-{index + 1}")
        raw_id_counts[raw_id] += 1
        key = raw_id if raw_id_counts[raw_id] == 1 else f"{raw_id}#duplicate-{raw_id_counts[raw_id]}"
        if raw_id_counts[raw_id] > 1:
            repairs.add("duplicate_branch_id")
        first_key_by_raw_id.setdefault(raw_id, key)
        keys.append(key)
        rows_by_key[key] = row
        entries_by_key[key] = branch_rows.entries[index]
        points_by_key[key] = branch_rows.points[index]
    return _BranchIndex(keys, rows_by_key, entries_by_key, points_by_key, first_key_by_raw_id)


def _render_branches(
    index: _BranchIndex,
    *,
    builder: MermaidGraphBuilder,
    topic_id: str,
    year_nodes: dict[int, str],
    repairs: MermaidRepairLog,
) -> dict[str, str]:
    parent_by_key = _resolve_branch_parents(index, repairs=repairs)
    branch_nodes: dict[str, str] = {}
    for position, key in enumerate(index.keys):
        row = index.rows_by_key[key]
        name = row.get("name") or f"Research line {position + 1}"
        basis = row.get("lineage_basis")
        label = f"{name} — {basis}" if basis else name
        node_id = builder.add_node("branch", key, label, "branch")
        if node_id is not None:
            branch_nodes[key] = node_id

    for key, node_id in branch_nodes.items():
        parent = parent_by_key.get(key)
        if parent and parent in branch_nodes:
            # Lineage and chronology are independent claims. Preserve the
            # parent-child relationship without replacing this branch's own
            # evidence-backed year anchor.
            builder.add_edge(branch_nodes[parent], node_id, "lineage")
        point = index.points_by_key[key]
        year = _coerce_year(point.get("year"))
        if year is not None and year in year_nodes:
            builder.add_edge(year_nodes[year], node_id, "branch")
        elif not parent or parent not in branch_nodes:
            if year is not None or point:
                repairs.add("invalid_branch_year")
            builder.add_edge(topic_id, node_id, "branch")
        elif year is not None or point:
            repairs.add("invalid_branch_year")
    return branch_nodes


def _resolve_branch_parents(index: _BranchIndex, *, repairs: MermaidRepairLog) -> dict[str, str | None]:
    parent_by_key: dict[str, str | None] = {}
    for key in index.keys:
        raw_parent = index.rows_by_key[key].get("parent_branch_id")
        if not raw_parent:
            parent_by_key[key] = None
            continue
        parent = index.first_key_by_raw_id.get(str(raw_parent))
        if parent is None:
            repairs.add("invalid_branch_parent")
        parent_by_key[key] = parent
    _break_parent_cycles(parent_by_key, repairs=repairs)
    return parent_by_key


def _render_entries(
    index: _BranchIndex,
    *,
    branch_nodes: dict[str, str],
    builder: MermaidGraphBuilder,
) -> None:
    rendered_ids: set[str] = set()
    rendered_count = 0
    previous_by_key = dict(branch_nodes)
    cap_omissions = 0
    maximum_length = max((len(entries) for entries in index.entries_by_key.values()), default=0)
    for entry_position in range(maximum_length):
        for branch_position, key in enumerate(index.keys):
            entries = index.entries_by_key[key]
            if key not in branch_nodes or entry_position >= len(entries):
                continue
            entry = entries[entry_position]
            raw_id = str(entry.get("entry_id") or f"entry-{branch_position + 1}-{entry_position + 1}")
            if raw_id in rendered_ids:
                builder.omitted["duplicate_entries"] += 1
                builder.repairs.add("duplicate_entry_id")
                continue
            rendered_ids.add(raw_id)
            if rendered_count >= _MAX_ENTRIES:
                builder.omitted["entries"] += 1
                cap_omissions += 1
                continue
            entry_id = builder.add_node("entry", f"{key}|{raw_id}", _entry_label(entry), "event")
            if entry_id is None:
                builder.omitted["entries"] += 1
                continue
            rendered_count += 1
            builder.add_edge(previous_by_key[key], entry_id)
            previous_by_key[key] = entry_id
    if cap_omissions:
        builder.repairs.add("visual_size_capped")


def _entry_label(entry: dict[str, Any]) -> str:
    time_start = entry.get("time_start") or entry.get("year") or "Undated"
    title = entry.get("title") or "Research event"
    paper_title = entry.get("paper_title") or ""
    evidence_ids = entry.get("evidence_ids")
    evidence = evidence_ids[0] if isinstance(evidence_ids, list) and evidence_ids else ""
    components = [str(time_start), str(title)]
    if paper_title and str(paper_title).casefold() != str(title).casefold():
        components.append(str(paper_title))
    if evidence:
        components.append(str(evidence))
    return " — ".join(components)


def _record_unassigned(
    raw_unassigned: Any,
    *,
    repairs: MermaidRepairLog,
    omitted: Counter[str],
) -> None:
    if raw_unassigned is None:
        return
    if isinstance(raw_unassigned, list):
        if raw_unassigned:
            omitted["unassigned_entries"] += len(raw_unassigned)
        return
    _mark_malformed("malformed_unassigned_entry_collections", repairs=repairs, omitted=omitted)


def _append_visual_notice(builder: MermaidGraphBuilder, *, topic_id: str) -> None:
    omitted_total = sum(builder.omitted.values())
    if not omitted_total:
        return
    notice_id = builder.add_node(
        "notice",
        "omitted",
        f"{omitted_total} visual items summarized — see chronicle_map.json",
        "notice",
    )
    builder.add_edge(topic_id, notice_id)


def _select_year_anchors(
    anchors: list[dict[str, Any]],
    *,
    priority_years: set[int],
) -> list[dict[str, Any]]:
    """Cap year anchors while retaining every rendered branch-point year."""
    by_year = {year: anchor for anchor in anchors if (year := _coerce_year(anchor.get("year"))) is not None}
    mandatory_years = sorted(priority_years & by_year.keys())
    remaining_years = sorted(by_year.keys() - set(mandatory_years))
    available_slots = max(0, _MAX_YEAR_ANCHORS - len(mandatory_years))
    if len(remaining_years) > available_slots:
        leading_count = (available_slots + 1) // 2
        trailing_count = available_slots - leading_count
        selected_remaining = remaining_years[:leading_count]
        if trailing_count:
            selected_remaining.extend(remaining_years[-trailing_count:])
    else:
        selected_remaining = remaining_years
    selected_years = sorted([*mandatory_years, *selected_remaining])
    return [by_year[year] for year in selected_years]


def _coerce_year(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1 <= value <= 9999 else None
    text = str(value or "").strip()
    if len(text) != 4 or not text.isdecimal():
        return None
    try:
        year = int(text)
    except ValueError:
        return None
    return year if 1 <= year <= 9999 else None


def _break_parent_cycles(parent_by_key: dict[str, str | None], *, repairs: MermaidRepairLog) -> None:
    for start in list(parent_by_key):
        visited: set[str] = set()
        cursor: str | None = start
        while cursor is not None:
            if cursor in visited:
                parent_by_key[cursor] = None
                repairs.add("branch_cycle_removed")
                break
            visited.add(cursor)
            cursor = parent_by_key.get(cursor)


__all__ = [
    "MermaidRenderResult",
    "MermaidValidator",
    "mermaid_label",
    "render_chronicle_mermaid_projection",
    "validate_mermaid_source",
]
