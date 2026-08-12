"""Deterministic Mermaid normalization, repair, and fallback rendering.

Mermaid is deliberately not invoked as a runtime dependency: MCP users may run
the Python server without Node.js or a browser.  Instead, this module builds a
small flowchart grammar from structured chronicle data, validates every node
and edge, and falls back through progressively simpler serializers.  A pinned
Mermaid parser/render smoke test in CI provides the external grammar check.
"""

from __future__ import annotations

import hashlib
import inspect
import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

MermaidValidator = Callable[[str], bool]

_MAX_LABEL_CHARS = 112
# Escaping can expand one source character into six ASCII bytes (for example
# ``"`` -> ``&quot;``), while CJK and emoji use multiple UTF-8 bytes. Bound the
# serialized label as well as its code-point count so a full-size graph does
# not collapse to the minimal fallback solely because of label encoding.
_MAX_ESCAPED_LABEL_BYTES = 160
# Mermaid 11 defaults ``maxTextSize`` to 50,000 JavaScript characters and may
# otherwise return an error SVG that looks like a successful render. Keep both
# byte and character counts below that boundary.
_MAX_SOURCE_BYTES = 49_000
_MAX_SOURCE_CHARS = 49_000
_MAX_YEAR_ANCHORS = 60
_MAX_BRANCHES = 24
_MAX_ENTRIES = 120
_MAX_NODES = 210
_MAX_EDGES = 260
_NODE_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_NODE_LINE_RE = re.compile(r'^\s{4}([A-Za-z][A-Za-z0-9_]{0,63})\["([^"\r\n]*)"\]$')
_EDGE_LINE_RE = re.compile(r"^\s{4}([A-Za-z][A-Za-z0-9_]{0,63})\s+(-->|==>|-\.->)\s+([A-Za-z][A-Za-z0-9_]{0,63})$")
_CLASS_LINE_RE = re.compile(
    r"^\s{4}class\s+([A-Za-z][A-Za-z0-9_]{0,63}(?:,[A-Za-z][A-Za-z0-9_]{0,63})*)\s+"
    r"(topic|spine|branch|event|notice)$"
)
_RICH_CLASS_DEFINITIONS = (
    "classDef topic fill:#0f172a,color:#ffffff,stroke:#0f172a,stroke-width:2px",
    "classDef spine fill:#dbeafe,color:#1e3a8a,stroke:#2563eb,stroke-width:2px",
    "classDef branch fill:#ecfeff,color:#164e63,stroke:#0891b2,stroke-width:2px",
    "classDef event fill:#ffffff,color:#111827,stroke:#94a3b8,stroke-width:1px",
    "classDef notice fill:#fff7ed,color:#9a3412,stroke:#f97316,stroke-width:1px",
)
_BIDI_AND_ZERO_WIDTH = frozenset(
    {
        "\u200b",
        "\u200e",
        "\u200f",
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2060",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
        "\ufeff",
    }
)

# Numeric entity syntax is supported by Mermaid and avoids accidentally
# introducing node delimiters, directives, comments, or edge-label syntax.
_LABEL_ENTITIES = {
    '"': "&quot;",
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "#": "#35;",
    "%": "#37;",
    "(": "#40;",
    ")": "#41;",
    ":": "#58;",
    ";": "#59;",
    "[": "#91;",
    "\\": "#92;",
    "]": "#93;",
    "`": "#96;",
    "{": "#123;",
    "|": "#124;",
    "}": "#125;",
}

_CORRECTION_MESSAGES = {
    "branch_cycle_removed": "Removed a cyclic or self-referential visual branch parent.",
    "duplicate_branch_id": "Separated duplicate branch identifiers into distinct visual nodes.",
    "duplicate_entry_id": "Rendered a repeated entry only once to avoid a misleading duplicate paper.",
    "empty_label_defaulted": "Replaced an empty visual label with a stable fallback label.",
    "invalid_branch_parent": "Attached a branch with an unknown parent to the topic root.",
    "invalid_branch_year": "Attached a branch with no usable year anchor to the topic root.",
    "invalid_year_anchor": "Skipped an invalid or duplicate year anchor on the visual spine.",
    "label_normalized": "Normalized unsafe Unicode, controls, or whitespace in a label.",
    "label_escaped": "Escaped Mermaid delimiter or directive characters inside a quoted label.",
    "label_truncated": "Truncated an oversized visual label; the full value remains in JSON artifacts.",
    "malformed_projection": "Replaced malformed projection data with a safe visual fallback.",
    "malformed_projection_row": "Skipped malformed projection rows while preserving valid visual data.",
    "minimal_fallback_omitted_graph": "Recorded graph content hidden by the minimal Mermaid fallback.",
    "rich_candidate_rejected": "The rich diagram failed validation and was rebuilt with safe syntax.",
    "safe_candidate_rejected": "The safe diagram failed validation and was rebuilt as a minimal notice.",
    "visual_size_capped": "Capped visual nodes or edges; omitted data remains in chronicle_map.json.",
}


@dataclass(frozen=True)
class MermaidNode:
    """One safe flowchart node."""

    node_id: str
    label: str
    role: str


@dataclass(frozen=True)
class MermaidEdge:
    """One edge whose endpoints are guaranteed to exist."""

    source: str
    target: str
    kind: str = "normal"


@dataclass
class MermaidGraph:
    """Bounded visual graph assembled before syntax serialization."""

    nodes: list[MermaidNode] = field(default_factory=list)
    edges: list[MermaidEdge] = field(default_factory=list)


@dataclass
class MermaidRenderResult:
    """Pure Mermaid source plus auditable normalization/fallback diagnostics."""

    source: str
    status: str
    tier: str
    corrections: list[dict[str, Any]] = field(default_factory=list)
    omitted_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    structural_valid: bool = True
    parser_validated: bool = False
    validator: str = "deterministic_structural_lint"

    @property
    def source_sha256(self) -> str:
        """Return a stable digest without duplicating source in diagnostics."""
        return hashlib.sha256(self.source.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON artifact describing validation and repairs."""
        return {
            "schema_version": "mermaid-validation/v1",
            "status": self.status,
            "tier": self.tier,
            "source_sha256": self.source_sha256,
            "source_chars": len(self.source),
            "source_bytes": len(self.source.encode("utf-8")),
            "structural_valid": self.structural_valid,
            "parser_validated": self.parser_validated,
            "validator": self.validator,
            "corrections": list(self.corrections),
            "omitted_counts": dict(self.omitted_counts),
            "warnings": list(self.warnings),
        }


class _RepairLog:
    """Aggregate deterministic repairs without flooding diagnostics."""

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()

    def add(self, code: str, count: int = 1) -> None:
        if count > 0:
            self.counts[code] += count

    def to_list(self) -> list[dict[str, Any]]:
        return [
            {
                "code": code,
                "count": count,
                "message": _CORRECTION_MESSAGES.get(code, code.replace("_", " ").capitalize()),
            }
            for code, count in sorted(self.counts.items())
        ]


def mermaid_label(value: Any, *, fallback: str = "Untitled", limit: int = _MAX_LABEL_CHARS) -> str:
    """Return a quoted-label-safe value for any Mermaid diagram family."""
    plain = _normalize_text(value, fallback=fallback, limit=limit, repairs=None)
    escaped, _truncated = _escape_label_with_byte_budget(plain)
    return escaped


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
    repairs = _RepairLog()
    omitted: Counter[str] = Counter()
    warnings: list[str] = []
    try:
        graph = _build_graph(projection, repairs=repairs, omitted=omitted)
        rich_source = _serialize_graph(graph, tier="rich")
    except Exception as exc:  # defensive boundary: visual output must never abort a chronicle
        repairs.add("malformed_projection")
        warnings.append(f"Projection repair failed safely: {type(exc).__name__}")
        return _minimal_result(
            repairs=repairs,
            omitted=omitted,
            warnings=warnings,
            validator=validator,
            validator_name=validator_name,
        )

    rich_ok, rich_issues = _validate_candidate(rich_source, validator)
    if rich_ok:
        _append_omission_warning(warnings, omitted)
        return MermaidRenderResult(
            source=rich_source,
            status="fallback" if omitted else "repaired" if repairs.counts else "valid",
            tier="rich",
            corrections=repairs.to_list(),
            omitted_counts=dict(omitted),
            warnings=warnings,
            parser_validated=validator is not None,
            validator=validator_name or ("external_validator" if validator else "deterministic_structural_lint"),
        )

    repairs.add("rich_candidate_rejected")
    warnings.extend(f"Rich candidate: {issue}" for issue in rich_issues[:3])
    safe_source = _serialize_graph(graph, tier="safe")
    safe_ok, safe_issues = _validate_candidate(safe_source, validator)
    if safe_ok:
        _append_omission_warning(warnings, omitted)
        return MermaidRenderResult(
            source=safe_source,
            status="fallback",
            tier="safe",
            corrections=repairs.to_list(),
            omitted_counts=dict(omitted),
            warnings=warnings,
            parser_validated=validator is not None,
            validator=validator_name or ("external_validator" if validator else "deterministic_structural_lint"),
        )

    repairs.add("safe_candidate_rejected")
    warnings.extend(f"Safe candidate: {issue}" for issue in safe_issues[:3])
    _record_minimal_fallback_omissions(graph, omitted=omitted, repairs=repairs)
    return _minimal_result(
        repairs=repairs,
        omitted=omitted,
        warnings=warnings,
        validator=validator,
        validator_name=validator_name,
    )


def validate_mermaid_source(source: str) -> tuple[bool, list[str]]:
    """Run a strict structural lint over generated Chronicle flowcharts."""
    issues: list[str] = []
    if not source.startswith("flowchart LR\n"):
        issues.append("source must start with 'flowchart LR'")
    if len(source) > _MAX_SOURCE_CHARS:
        issues.append(f"source exceeds {_MAX_SOURCE_CHARS} characters")
    if len(source.encode("utf-8", errors="replace")) > _MAX_SOURCE_BYTES:
        issues.append(f"source exceeds {_MAX_SOURCE_BYTES} bytes")
    if "%%{" in source or "```" in source:
        issues.append("source contains a directive or Markdown fence")
    if any(char != "\n" and unicodedata.category(char).startswith("C") for char in source):
        issues.append("source contains a control or surrogate character")

    node_ids: set[str] = set()
    edge_rows: list[tuple[str, str]] = []
    class_ids: list[str] = []
    for line_number, line in enumerate(source.splitlines()[1:], start=2):
        if not line.strip():
            continue
        node_match = _NODE_LINE_RE.fullmatch(line)
        if node_match:
            node_id, label = node_match.groups()
            if node_id in node_ids:
                issues.append(f"line {line_number}: duplicate node ID {node_id}")
            node_ids.add(node_id)
            if any(token in label for token in ("<script", "</", "%%{")):
                issues.append(f"line {line_number}: unsafe label token")
            continue
        edge_match = _EDGE_LINE_RE.fullmatch(line)
        if edge_match:
            source_id, _arrow, target_id = edge_match.groups()
            edge_rows.append((source_id, target_id))
            continue
        if line.removeprefix("    ") in _RICH_CLASS_DEFINITIONS:
            continue
        class_match = _CLASS_LINE_RE.fullmatch(line)
        if class_match:
            class_ids.extend(class_match.group(1).split(","))
            continue
        issues.append(f"line {line_number}: unsupported generated statement")

    if not node_ids:
        issues.append("diagram declares no nodes")
    if len(node_ids) > _MAX_NODES:
        issues.append(f"diagram exceeds {_MAX_NODES} nodes")
    if len(edge_rows) > _MAX_EDGES:
        issues.append(f"diagram exceeds {_MAX_EDGES} edges")
    for source_id, target_id in edge_rows:
        if source_id not in node_ids or target_id not in node_ids:
            issues.append(f"edge references unknown endpoint {source_id} -> {target_id}")
    missing_class_targets = sorted(set(class_ids) - node_ids)
    if missing_class_targets:
        issues.append(f"class assignment references unknown nodes: {', '.join(missing_class_targets[:3])}")
    return not issues, issues


def _build_graph(projection: dict[str, Any], *, repairs: _RepairLog, omitted: Counter[str]) -> MermaidGraph:
    if not isinstance(projection, dict):
        raise TypeError("chronicle projection must be a mapping")

    graph = MermaidGraph()
    used_ids: set[str] = set()
    edge_keys: set[tuple[str, str, str]] = set()

    def add_node(kind: str, identity: str, label: Any, role: str) -> str | None:
        if len(graph.nodes) >= _MAX_NODES:
            omitted["nodes"] += 1
            repairs.add("visual_size_capped")
            return None
        node_id = _stable_node_id(kind, identity)
        collision = 0
        while node_id in used_ids:
            collision += 1
            node_id = _stable_node_id(kind, f"{identity}\x1fcollision-{collision}")
        used_ids.add(node_id)
        normalized_label = _normalize_text(label, fallback=role.title(), limit=_MAX_LABEL_CHARS, repairs=repairs)
        if any(char in _LABEL_ENTITIES for char in normalized_label):
            repairs.add("label_escaped")
        safe_label, byte_truncated = _escape_label_with_byte_budget(normalized_label)
        if byte_truncated:
            repairs.add("label_truncated")
        graph.nodes.append(MermaidNode(node_id=node_id, label=safe_label, role=role))
        return node_id

    def add_edge(source: str | None, target: str | None, kind: str = "normal") -> None:
        if source is None or target is None or source == target:
            return
        key = (source, target, kind)
        if key in edge_keys:
            return
        if len(graph.edges) >= _MAX_EDGES:
            omitted["edges"] += 1
            repairs.add("visual_size_capped")
            return
        edge_keys.add(key)
        graph.edges.append(MermaidEdge(source=source, target=target, kind=kind))

    topic = projection.get("topic") or "Research Chronicle"
    topic_id = add_node("topic", str(topic), topic, "topic")
    if topic_id is None:  # unreachable with an initially empty graph
        raise ValueError("topic node could not be created")

    def mark_malformed(category: str, count: int = 1) -> None:
        omitted[category] += count
        repairs.add("malformed_projection_row", count)

    raw_branches = projection.get("branches")
    if raw_branches is None:
        candidate_branches: list[dict[str, Any]] = []
    elif isinstance(raw_branches, list):
        candidate_branches = [row for row in raw_branches if isinstance(row, dict)]
        malformed_count = len(raw_branches) - len(candidate_branches)
        if malformed_count:
            mark_malformed("malformed_branch_rows", malformed_count)
    else:
        candidate_branches = []
        mark_malformed("malformed_branch_collections")

    candidate_entries: list[list[dict[str, Any]]] = []
    candidate_points: list[dict[str, Any]] = []
    for row in candidate_branches:
        raw_entries = row.get("entries")
        if raw_entries is None:
            entries: list[dict[str, Any]] = []
        elif isinstance(raw_entries, list):
            entries = [entry for entry in raw_entries if isinstance(entry, dict)]
            malformed_count = len(raw_entries) - len(entries)
            if malformed_count:
                mark_malformed("malformed_entry_rows", malformed_count)
        else:
            entries = []
            mark_malformed("malformed_entry_collections")
        candidate_entries.append(entries)

        raw_point = row.get("branch_point")
        if raw_point is None:
            point: dict[str, Any] = {}
        elif isinstance(raw_point, dict):
            point = raw_point
        else:
            point = {}
            mark_malformed("malformed_branch_points")
        candidate_points.append(point)

    if len(candidate_branches) > _MAX_BRANCHES:
        discarded_entries = candidate_entries[_MAX_BRANCHES:]
        omitted["branches"] += len(candidate_branches) - _MAX_BRANCHES
        omitted["entries_in_capped_branches"] += sum(len(entries) for entries in discarded_entries)
        candidate_branches = candidate_branches[:_MAX_BRANCHES]
        candidate_entries = candidate_entries[:_MAX_BRANCHES]
        candidate_points = candidate_points[:_MAX_BRANCHES]
        repairs.add("visual_size_capped")

    branch_rows = candidate_branches
    priority_years = {year for point in candidate_points if (year := _coerce_year(point.get("year"))) is not None}

    raw_spine = projection.get("spine")
    if raw_spine is None:
        spine: dict[str, Any] = {}
    elif isinstance(raw_spine, dict):
        spine = raw_spine
    else:
        spine = {}
        mark_malformed("malformed_spine_collections")
    raw_anchors = spine.get("year_anchors")
    if raw_anchors is None:
        anchor_rows: list[dict[str, Any]] = []
    elif isinstance(raw_anchors, list):
        anchor_rows = [anchor for anchor in raw_anchors if isinstance(anchor, dict)]
        malformed_count = len(raw_anchors) - len(anchor_rows)
        if malformed_count:
            mark_malformed("malformed_year_anchor_rows", malformed_count)
    else:
        anchor_rows = []
        mark_malformed("malformed_year_anchor_collections")

    anchor_by_year: dict[int, dict[str, Any]] = {}
    for anchor in anchor_rows:
        year = _coerce_year(anchor.get("year"))
        if year is None:
            omitted["invalid_year_anchors"] += 1
            repairs.add("invalid_year_anchor")
            continue
        if year in anchor_by_year:
            omitted["duplicate_year_anchors"] += 1
            repairs.add("invalid_year_anchor")
            continue
        anchor_by_year[year] = anchor

    anchors = [anchor_by_year[year] for year in sorted(anchor_by_year)]
    if len(anchors) > _MAX_YEAR_ANCHORS:
        original_count = len(anchors)
        anchors = _select_year_anchors(anchors, priority_years=priority_years)
        omitted["year_anchors"] += original_count - len(anchors)
        repairs.add("visual_size_capped")

    year_nodes: dict[int, str] = {}
    previous_id = topic_id
    for anchor in anchors:
        year = _coerce_year(anchor.get("year"))
        if year is None:  # construction invariant after anchor normalization
            continue
        year_id = add_node("year", str(year), str(year), "spine")
        if year_id is None:
            continue
        year_nodes[year] = year_id
        add_edge(previous_id, year_id, "spine")
        previous_id = year_id

    branch_keys: list[str] = []
    branch_by_key: dict[str, dict[str, Any]] = {}
    branch_entries_by_key: dict[str, list[dict[str, Any]]] = {}
    branch_point_by_key: dict[str, dict[str, Any]] = {}
    first_key_by_raw_id: dict[str, str] = {}
    raw_id_counts: Counter[str] = Counter()
    for index, row in enumerate(branch_rows):
        raw_id = str(row.get("branch_id") or f"branch-{index + 1}")
        raw_id_counts[raw_id] += 1
        key = raw_id if raw_id_counts[raw_id] == 1 else f"{raw_id}#duplicate-{raw_id_counts[raw_id]}"
        if raw_id_counts[raw_id] > 1:
            repairs.add("duplicate_branch_id")
        first_key_by_raw_id.setdefault(raw_id, key)
        branch_keys.append(key)
        branch_by_key[key] = row
        branch_entries_by_key[key] = candidate_entries[index]
        branch_point_by_key[key] = candidate_points[index]

    parent_by_key: dict[str, str | None] = {}
    for key in branch_keys:
        raw_parent = branch_by_key[key].get("parent_branch_id")
        if not raw_parent:
            parent_by_key[key] = None
            continue
        parent = first_key_by_raw_id.get(str(raw_parent))
        if parent is None:
            repairs.add("invalid_branch_parent")
        parent_by_key[key] = parent
    _break_parent_cycles(parent_by_key, repairs=repairs)

    branch_node_by_key: dict[str, str] = {}
    for index, key in enumerate(branch_keys):
        row = branch_by_key[key]
        name = row.get("name") or f"Research line {index + 1}"
        basis = row.get("lineage_basis")
        label = f"{name} — {basis}" if basis else name
        node_id = add_node("branch", key, label, "branch")
        if node_id is not None:
            branch_node_by_key[key] = node_id

    for key, node_id in branch_node_by_key.items():
        parent = parent_by_key.get(key)
        if parent and parent in branch_node_by_key:
            add_edge(branch_node_by_key[parent], node_id, "branch")
            continue
        point = branch_point_by_key[key]
        year = _coerce_year(point.get("year"))
        if year is not None and year in year_nodes:
            add_edge(year_nodes[year], node_id, "branch")
        else:
            if year is not None or point:
                repairs.add("invalid_branch_year")
            add_edge(topic_id, node_id, "branch")

    rendered_entry_ids: set[str] = set()
    rendered_entries = 0
    previous_entry_by_key = dict(branch_node_by_key)
    entry_cap_omissions = 0
    maximum_branch_length = max((len(entries) for entries in branch_entries_by_key.values()), default=0)
    for entry_index in range(maximum_branch_length):
        for branch_index, key in enumerate(branch_keys):
            branch_node_id = branch_node_by_key.get(key)
            entries = branch_entries_by_key[key]
            if branch_node_id is None or entry_index >= len(entries):
                continue
            entry = entries[entry_index]
            raw_entry_id = str(entry.get("entry_id") or f"entry-{branch_index + 1}-{entry_index + 1}")
            if raw_entry_id in rendered_entry_ids:
                omitted["duplicate_entries"] += 1
                repairs.add("duplicate_entry_id")
                continue
            rendered_entry_ids.add(raw_entry_id)
            if rendered_entries >= _MAX_ENTRIES:
                omitted["entries"] += 1
                entry_cap_omissions += 1
                continue
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
            label = " — ".join(components)
            entry_node_id = add_node(
                "entry",
                f"{key}|{raw_entry_id}",
                label,
                "event",
            )
            if entry_node_id is None:
                omitted["entries"] += 1
                continue
            rendered_entries += 1
            add_edge(previous_entry_by_key[key], entry_node_id)
            previous_entry_by_key[key] = entry_node_id
    if entry_cap_omissions:
        repairs.add("visual_size_capped")

    raw_unassigned = projection.get("unassigned_entry_ids")
    if raw_unassigned is None:
        unassigned_count = 0
    elif isinstance(raw_unassigned, list):
        unassigned_count = len(raw_unassigned)
    else:
        unassigned_count = 0
        mark_malformed("malformed_unassigned_entry_collections")
    if unassigned_count:
        omitted["unassigned_entries"] += unassigned_count

    omitted_total = sum(omitted.values())
    if omitted_total:
        notice_id = add_node(
            "notice",
            "omitted",
            f"{omitted_total} visual items summarized — see chronicle_map.json",
            "notice",
        )
        add_edge(topic_id, notice_id)
    return graph


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


def _append_omission_warning(warnings: list[str], omitted: Counter[str]) -> None:
    """Expose every visual omission in the result as well as structured counts."""
    if not omitted or any(warning.startswith("Visual output omitted or summarized") for warning in warnings):
        return
    details = ", ".join(f"{key}={count}" for key, count in sorted(omitted.items()) if count > 0)
    warnings.append(f"Visual output omitted or summarized content: {details}.")


def _record_minimal_fallback_omissions(
    graph: MermaidGraph,
    *,
    omitted: Counter[str],
    repairs: _RepairLog,
) -> None:
    """Count the complete graph hidden when only the minimal notice is returned."""
    role_names = {
        "topic": "fallback_topic_nodes",
        "spine": "fallback_year_anchors",
        "branch": "fallback_branches",
        "event": "fallback_entries",
        "notice": "fallback_notice_nodes",
    }
    for node in graph.nodes:
        omitted[role_names.get(node.role, "fallback_other_nodes")] += 1
    omitted["fallback_edges"] += len(graph.edges)
    repairs.add("minimal_fallback_omitted_graph")


def _serialize_graph(graph: MermaidGraph, *, tier: str) -> str:
    lines = ["flowchart LR"]
    lines.extend(f'    {node.node_id}["{node.label}"]' for node in graph.nodes)
    for edge in graph.edges:
        arrow = "-->"
        if tier == "rich":
            arrow = "==>" if edge.kind == "spine" else "-.->" if edge.kind == "branch" else "-->"
        lines.append(f"    {edge.source} {arrow} {edge.target}")

    if tier == "rich":
        lines.extend(f"    {definition}" for definition in _RICH_CLASS_DEFINITIONS)
        for role in ("topic", "spine", "branch", "event", "notice"):
            role_ids = [node.node_id for node in graph.nodes if node.role == role]
            for offset in range(0, len(role_ids), 40):
                lines.append(f"    class {','.join(role_ids[offset : offset + 40])} {role}")
    return "\n".join(lines)


def _minimal_result(
    *,
    repairs: _RepairLog,
    omitted: Counter[str],
    warnings: list[str],
    validator: MermaidValidator | None,
    validator_name: str | None,
) -> MermaidRenderResult:
    _append_omission_warning(warnings, omitted)
    graph = MermaidGraph(
        nodes=[
            MermaidNode("n_chronicle", "Research Chronicle", "topic"),
            MermaidNode(
                "n_details",
                "Visualization simplified#59; see chronicle_map.json",
                "notice",
            ),
        ],
        edges=[MermaidEdge("n_chronicle", "n_details")],
    )
    source = _serialize_graph(graph, tier="safe")
    structural_ok, structural_issues = validate_mermaid_source(source)
    parser_ok = False
    if validator is not None:
        parser_ok, validator_issue = _run_external_validator(source, validator)
        if validator_issue:
            warnings.append(f"Minimal candidate {validator_issue}.")
        if not parser_ok:
            warnings.append(
                "External validator rejected the minimal candidate; returned the structurally safe fallback."
            )
    warnings.extend(structural_issues)
    return MermaidRenderResult(
        source=source,
        status="fallback",
        tier="minimal",
        corrections=repairs.to_list(),
        omitted_counts=dict(omitted),
        warnings=warnings,
        structural_valid=structural_ok,
        parser_validated=validator is not None and parser_ok,
        validator=validator_name or ("external_validator" if validator else "deterministic_structural_lint"),
    )


def _validate_candidate(source: str, validator: MermaidValidator | None) -> tuple[bool, list[str]]:
    structural_ok, issues = validate_mermaid_source(source)
    if not structural_ok:
        return False, issues
    if validator is None:
        return True, []
    valid, issue = _run_external_validator(source, validator)
    if valid:
        return True, []
    return False, [issue or "external Mermaid validator rejected the candidate"]


def _run_external_validator(source: str, validator: MermaidValidator) -> tuple[bool, str | None]:
    """Invoke a synchronous host validator without accepting awaitables as truthy."""
    try:
        outcome = validator(source)
        if inspect.isawaitable(outcome):
            close = getattr(outcome, "close", None)
            if callable(close):
                close()
            return False, "external Mermaid validator returned an awaitable; a synchronous validator is required"
        valid = bool(outcome)
        return valid, None if valid else "external Mermaid validator rejected the candidate"
    except Exception as exc:
        return False, f"external Mermaid validator raised {type(exc).__name__}"


def _normalize_text(
    value: Any,
    *,
    fallback: str,
    limit: int,
    repairs: _RepairLog | None,
) -> str:
    try:
        original = "" if value is None else str(value)
    except Exception:  # pragma: no cover - hostile objects are only possible through direct Python misuse
        original = ""
    encodable = original.encode("utf-8", errors="replace").decode("utf-8")
    normalized = unicodedata.normalize("NFC", encodable)
    characters: list[str] = []
    for char in normalized:
        category = unicodedata.category(char)
        if char in _BIDI_AND_ZERO_WIDTH or category.startswith("C") or char in {"\u2028", "\u2029"}:
            characters.append(" ")
        else:
            characters.append(char)
    cleaned = " ".join("".join(characters).split()).strip()
    if cleaned != original and repairs is not None:
        repairs.add("label_normalized")
    if not cleaned:
        cleaned = fallback
        if repairs is not None:
            repairs.add("empty_label_defaulted")
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
        if repairs is not None:
            repairs.add("label_truncated")
    return cleaned


def _escape_label_with_byte_budget(
    plain: str,
    *,
    byte_limit: int = _MAX_ESCAPED_LABEL_BYTES,
) -> tuple[str, bool]:
    """Escape one label without splitting Unicode or Mermaid entity tokens."""
    tokens = [_LABEL_ENTITIES.get(char, char) for char in plain]
    if sum(len(token.encode("utf-8")) for token in tokens) <= byte_limit:
        return "".join(tokens), False

    suffix = "…"
    available = max(0, byte_limit - len(suffix.encode("utf-8")))
    selected: list[str] = []
    used = 0
    for token in tokens:
        token_bytes = len(token.encode("utf-8"))
        if used + token_bytes > available:
            break
        selected.append(token)
        used += token_bytes
    return "".join(selected).rstrip() + suffix, True


def _stable_node_id(kind: str, identity: str) -> str:
    safe_kind = re.sub(r"[^A-Za-z0-9_]", "_", kind).strip("_")[:12] or "node"
    if not safe_kind[0].isalpha():
        safe_kind = f"n_{safe_kind}"
    digest_input = f"{kind}\x1f{identity}".encode("utf-8", errors="replace")
    digest = hashlib.sha256(digest_input).hexdigest()[:12]
    node_id = f"n_{safe_kind}_{digest}"
    if not _NODE_ID_RE.fullmatch(node_id):  # construction invariant
        raise ValueError("generated an invalid Mermaid node ID")
    return node_id


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


def _break_parent_cycles(parent_by_key: dict[str, str | None], *, repairs: _RepairLog) -> None:
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
