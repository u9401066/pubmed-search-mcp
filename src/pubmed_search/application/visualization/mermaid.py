"""Safe, bounded Mermaid flowchart rendering shared by application features.

The server cannot assume that Node.js or a browser-side Mermaid parser exists,
so generated diagrams use a deliberately small grammar.  All untrusted labels
are normalized and escaped, graph sizes are bounded before serialization, and
rendering falls back from a styled graph to plain syntax and finally to a
minimal deterministic notice.  An optional synchronous parser validator may be
supplied by hosts or tests without becoming a runtime dependency.
"""

from __future__ import annotations

import hashlib
import inspect
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

MermaidValidator = Callable[[str], bool]


@dataclass(frozen=True)
class MermaidLimits:
    """Hard serialization budgets for one Mermaid flowchart."""

    max_label_chars: int = 112
    max_escaped_label_bytes: int = 160
    max_source_bytes: int = 49_000
    max_source_chars: int = 49_000
    max_nodes: int = 210
    max_edges: int = 260


DEFAULT_MERMAID_LIMITS = MermaidLimits()

_NODE_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_NODE_LINE_RE = re.compile(r'^\s{4}([A-Za-z][A-Za-z0-9_]{0,63})\["([^"\r\n]*)"\]$')
_EDGE_LINE_RE = re.compile(r"^\s{4}([A-Za-z][A-Za-z0-9_]{0,63})\s+(-->|==>|-\.->)\s+([A-Za-z][A-Za-z0-9_]{0,63})$")

_ROLE_STYLES = {
    "topic": "classDef topic fill:#0f172a,color:#ffffff,stroke:#0f172a,stroke-width:2px",
    "spine": "classDef spine fill:#dbeafe,color:#1e3a8a,stroke:#2563eb,stroke-width:2px",
    "branch": "classDef branch fill:#ecfeff,color:#164e63,stroke:#0891b2,stroke-width:2px",
    "event": "classDef event fill:#ffffff,color:#111827,stroke:#94a3b8,stroke-width:1px",
    "root": "classDef root fill:#dc2626,color:#ffffff,stroke:#991b1b,stroke-width:3px",
    "citing": "classDef citing fill:#0f766e,color:#ffffff,stroke:#115e59,stroke-width:2px",
    "reference": "classDef reference fill:#d1fae5,color:#064e3b,stroke:#059669,stroke-width:2px",
    "shared": "classDef shared fill:#ede9fe,color:#4c1d95,stroke:#7c3aed,stroke-width:2px",
    "notice": "classDef notice fill:#fff7ed,color:#9a3412,stroke:#f97316,stroke-width:1px",
}
_CLASS_LINE_RE = re.compile(
    r"^\s{4}class\s+([A-Za-z][A-Za-z0-9_]{0,63}(?:,[A-Za-z][A-Za-z0-9_]{0,63})*)\s+"
    rf"({'|'.join(re.escape(role) for role in _ROLE_STYLES)})$"
)
_STYLE_DEFINITIONS = frozenset(_ROLE_STYLES.values())

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

# Mermaid numeric entity syntax avoids introducing delimiters, directives,
# comments, Markdown fences, or edge-label syntax from untrusted metadata.
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
    "duplicate_edge": "Removed a duplicate visual edge.",
    "duplicate_entry_id": "Rendered a repeated entry only once to avoid a misleading duplicate paper.",
    "empty_label_defaulted": "Replaced an empty visual label with a stable fallback label.",
    "invalid_branch_parent": "Attached a branch with an unknown parent to the topic root.",
    "invalid_branch_year": "Attached a branch with no usable year anchor to the topic root.",
    "invalid_edge_endpoint": "Omitted an edge whose endpoint was not present in the bounded graph.",
    "invalid_role": "Replaced an unknown visual role with the notice style.",
    "invalid_year_anchor": "Skipped an invalid or duplicate year anchor on the visual spine.",
    "label_normalized": "Normalized unsafe Unicode, controls, or whitespace in a label.",
    "label_escaped": "Escaped Mermaid delimiter or directive characters inside a quoted label.",
    "label_truncated": "Truncated an oversized visual label; the full value remains in structured data.",
    "malformed_projection": "Replaced malformed projection data with a safe visual fallback.",
    "malformed_projection_row": "Skipped malformed projection rows while preserving valid visual data.",
    "minimal_fallback_omitted_graph": "Recorded graph content hidden by the minimal Mermaid fallback.",
    "rich_candidate_rejected": "The rich diagram failed validation and was rebuilt with safe syntax.",
    "safe_candidate_rejected": "The safe diagram failed validation and was rebuilt as a minimal notice.",
    "self_edge_removed": "Removed a self-referential visual edge.",
    "visual_size_capped": "Capped visual nodes or edges; omitted data remains in structured artifacts.",
}


@dataclass(frozen=True)
class MermaidNode:
    """One normalized, quoted-label-safe flowchart node."""

    node_id: str
    label: str
    role: str


@dataclass(frozen=True)
class MermaidEdge:
    """One flowchart edge whose endpoints are present in the graph."""

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
    """Pure Mermaid source plus auditable repair and fallback diagnostics."""

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
        """Return JSON-ready validation and repair metadata."""
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


class MermaidRepairLog:
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


class MermaidGraphBuilder:
    """Construct a bounded graph while normalizing all untrusted fields."""

    def __init__(
        self,
        *,
        repairs: MermaidRepairLog | None = None,
        omitted: Counter[str] | None = None,
        limits: MermaidLimits = DEFAULT_MERMAID_LIMITS,
    ) -> None:
        self.graph = MermaidGraph()
        self.repairs = repairs if repairs is not None else MermaidRepairLog()
        self.omitted = omitted if omitted is not None else Counter()
        self.limits = limits
        self._node_ids: set[str] = set()
        self._edge_keys: set[tuple[str, str, str]] = set()

    def add_node(
        self,
        kind: str,
        identity: str,
        label: Any,
        role: str,
        *,
        fallback: str | None = None,
    ) -> str | None:
        """Add one stable node or count it as omitted when the budget is full."""
        if len(self.graph.nodes) >= self.limits.max_nodes:
            self.omitted["nodes"] += 1
            self.repairs.add("visual_size_capped")
            return None

        node_id = stable_mermaid_node_id(kind, identity)
        collision = 0
        while node_id in self._node_ids:
            collision += 1
            node_id = stable_mermaid_node_id(kind, f"{identity}\x1fcollision-{collision}")
        self._node_ids.add(node_id)

        normalized_role = role if role in _ROLE_STYLES else "notice"
        if normalized_role != role:
            self.repairs.add("invalid_role")
        normalized = _normalize_text(
            label,
            fallback=fallback or normalized_role.title(),
            limit=self.limits.max_label_chars,
            repairs=self.repairs,
        )
        if any(char in _LABEL_ENTITIES for char in normalized):
            self.repairs.add("label_escaped")
        escaped, byte_truncated = _escape_label_with_byte_budget(
            normalized,
            byte_limit=self.limits.max_escaped_label_bytes,
        )
        if byte_truncated:
            self.repairs.add("label_truncated")
        self.graph.nodes.append(MermaidNode(node_id=node_id, label=escaped, role=normalized_role))
        return node_id

    def add_edge(self, source: str | None, target: str | None, kind: str = "normal") -> bool:
        """Add one valid, unique edge and return whether it was retained."""
        if source is None or target is None or source not in self._node_ids or target not in self._node_ids:
            self.omitted["invalid_edges"] += 1
            self.repairs.add("invalid_edge_endpoint")
            return False
        if source == target:
            self.repairs.add("self_edge_removed")
            return False
        normalized_kind = kind if kind in {"normal", "spine", "branch", "lineage"} else "normal"
        key = (source, target, normalized_kind)
        if key in self._edge_keys:
            self.repairs.add("duplicate_edge")
            return False
        if len(self.graph.edges) >= self.limits.max_edges:
            self.omitted["edges"] += 1
            self.repairs.add("visual_size_capped")
            return False
        self._edge_keys.add(key)
        self.graph.edges.append(MermaidEdge(source=source, target=target, kind=normalized_kind))
        return True


def mermaid_label(
    value: Any,
    *,
    fallback: str = "Untitled",
    limit: int = DEFAULT_MERMAID_LIMITS.max_label_chars,
) -> str:
    """Return a quoted-label-safe value for any Mermaid diagram family."""
    plain = _normalize_text(value, fallback=fallback, limit=limit, repairs=None)
    escaped, _truncated = _escape_label_with_byte_budget(
        plain,
        byte_limit=DEFAULT_MERMAID_LIMITS.max_escaped_label_bytes,
    )
    return escaped


def stable_mermaid_node_id(kind: str, identity: str) -> str:
    """Return a deterministic grammar-safe node identifier."""
    safe_kind = re.sub(r"[^A-Za-z0-9_]", "_", kind).strip("_")[:12] or "node"
    if not safe_kind[0].isalpha():
        safe_kind = f"n_{safe_kind}"
    digest_input = f"{kind}\x1f{identity}".encode("utf-8", errors="replace")
    digest = hashlib.sha256(digest_input).hexdigest()[:12]
    node_id = f"n_{safe_kind}_{digest}"
    if not _NODE_ID_RE.fullmatch(node_id):  # construction invariant
        raise ValueError("generated an invalid Mermaid node ID")
    return node_id


def render_mermaid_graph(
    graph: MermaidGraph,
    *,
    direction: str = "LR",
    style_roles: Iterable[str] = (),
    repairs: MermaidRepairLog | None = None,
    omitted: Counter[str] | None = None,
    warnings: list[str] | None = None,
    fallback_title: str = "Visualization",
    fallback_details: str = "Visualization simplified; see structured data",
    validator: MermaidValidator | None = None,
    validator_name: str | None = None,
    limits: MermaidLimits = DEFAULT_MERMAID_LIMITS,
) -> MermaidRenderResult:
    """Validate a graph and deterministically repair/fallback its serialization."""
    repair_log = repairs if repairs is not None else MermaidRepairLog()
    omitted_counts = omitted if omitted is not None else Counter()
    warning_rows = warnings if warnings is not None else []
    orientation = direction if direction in {"LR", "TD"} else "LR"
    normalized_roles = tuple(dict.fromkeys(role for role in style_roles if role in _ROLE_STYLES))

    rich_source = _serialize_graph(graph, direction=orientation, tier="rich", style_roles=normalized_roles)
    rich_ok, rich_issues = _validate_candidate(rich_source, validator, limits=limits)
    if rich_ok:
        _append_omission_warning(warning_rows, omitted_counts)
        return MermaidRenderResult(
            source=rich_source,
            status="fallback" if omitted_counts else "repaired" if repair_log.counts else "valid",
            tier="rich",
            corrections=repair_log.to_list(),
            omitted_counts=dict(omitted_counts),
            warnings=warning_rows,
            parser_validated=validator is not None,
            validator=validator_name or ("external_validator" if validator else "deterministic_structural_lint"),
        )

    repair_log.add("rich_candidate_rejected")
    warning_rows.extend(f"Rich candidate: {issue}" for issue in rich_issues[:3])
    safe_source = _serialize_graph(graph, direction=orientation, tier="safe", style_roles=())
    safe_ok, safe_issues = _validate_candidate(safe_source, validator, limits=limits)
    if safe_ok:
        _append_omission_warning(warning_rows, omitted_counts)
        return MermaidRenderResult(
            source=safe_source,
            status="fallback",
            tier="safe",
            corrections=repair_log.to_list(),
            omitted_counts=dict(omitted_counts),
            warnings=warning_rows,
            parser_validated=validator is not None,
            validator=validator_name or ("external_validator" if validator else "deterministic_structural_lint"),
        )

    repair_log.add("safe_candidate_rejected")
    warning_rows.extend(f"Safe candidate: {issue}" for issue in safe_issues[:3])
    _record_minimal_fallback_omissions(graph, omitted=omitted_counts, repairs=repair_log)
    return _minimal_result(
        direction=orientation,
        fallback_title=fallback_title,
        fallback_details=fallback_details,
        repairs=repair_log,
        omitted=omitted_counts,
        warnings=warning_rows,
        validator=validator,
        validator_name=validator_name,
        limits=limits,
    )


def validate_mermaid_source(
    source: str,
    *,
    limits: MermaidLimits = DEFAULT_MERMAID_LIMITS,
) -> tuple[bool, list[str]]:
    """Run strict structural lint over generated LR or TD flowcharts."""
    issues = _source_level_issues(source, limits)
    node_ids, edge_rows, class_ids, statement_issues = _parse_generated_statements(source)
    issues.extend(statement_issues)
    issues.extend(_graph_level_issues(node_ids, edge_rows, class_ids, limits))
    return not issues, issues


def _source_level_issues(source: str, limits: MermaidLimits) -> list[str]:
    issues: list[str] = []
    first_line = source.partition("\n")[0]
    if first_line not in {"flowchart LR", "flowchart TD"}:
        issues.append("source must start with 'flowchart LR' or 'flowchart TD'")
    if len(source) > limits.max_source_chars:
        issues.append(f"source exceeds {limits.max_source_chars} characters")
    if len(source.encode("utf-8", errors="replace")) > limits.max_source_bytes:
        issues.append(f"source exceeds {limits.max_source_bytes} bytes")
    if "%%{" in source or "```" in source:
        issues.append("source contains a directive or Markdown fence")
    if "\r" in source:
        issues.append("source contains a carriage return")
    if any(char != "\n" and unicodedata.category(char).startswith("C") for char in source):
        issues.append("source contains a control or surrogate character")
    return issues


def _parse_generated_statements(
    source: str,
) -> tuple[set[str], list[tuple[str, str]], list[str], list[str]]:
    node_ids: set[str] = set()
    edge_rows: list[tuple[str, str]] = []
    class_ids: list[str] = []
    issues: list[str] = []
    for line_number, line in enumerate(source.splitlines()[1:], start=2):
        if not line.strip():
            continue
        node_match = _NODE_LINE_RE.fullmatch(line)
        if node_match:
            node_id, label = node_match.groups()
            if node_id in node_ids:
                issues.append(f"line {line_number}: duplicate node ID {node_id}")
            node_ids.add(node_id)
            if any(token in label.casefold() for token in ("<script", "</", "%%{")):
                issues.append(f"line {line_number}: unsafe label token")
            continue
        edge_match = _EDGE_LINE_RE.fullmatch(line)
        if edge_match:
            source_id, _arrow, target_id = edge_match.groups()
            edge_rows.append((source_id, target_id))
            continue
        if line.removeprefix("    ") in _STYLE_DEFINITIONS:
            continue
        class_match = _CLASS_LINE_RE.fullmatch(line)
        if class_match:
            class_ids.extend(class_match.group(1).split(","))
            continue
        issues.append(f"line {line_number}: unsupported generated statement")
    return node_ids, edge_rows, class_ids, issues


def _graph_level_issues(
    node_ids: set[str],
    edge_rows: list[tuple[str, str]],
    class_ids: list[str],
    limits: MermaidLimits,
) -> list[str]:
    issues: list[str] = []
    if not node_ids:
        issues.append("diagram declares no nodes")
    if len(node_ids) > limits.max_nodes:
        issues.append(f"diagram exceeds {limits.max_nodes} nodes")
    if len(edge_rows) > limits.max_edges:
        issues.append(f"diagram exceeds {limits.max_edges} edges")
    for source_id, target_id in edge_rows:
        if source_id not in node_ids or target_id not in node_ids:
            issues.append(f"edge references unknown endpoint {source_id} -> {target_id}")
    missing_class_targets = sorted(set(class_ids) - node_ids)
    if missing_class_targets:
        issues.append(f"class assignment references unknown nodes: {', '.join(missing_class_targets[:3])}")
    return issues


def _serialize_graph(
    graph: MermaidGraph,
    *,
    direction: str,
    tier: str,
    style_roles: tuple[str, ...],
) -> str:
    lines = [f"flowchart {direction}"]
    lines.extend(f'    {node.node_id}["{node.label}"]' for node in graph.nodes)
    for edge in graph.edges:
        arrow = "-->"
        if tier == "rich":
            arrow = "==>" if edge.kind == "spine" else "-.->" if edge.kind == "branch" else "-->"
        lines.append(f"    {edge.source} {arrow} {edge.target}")

    if tier == "rich":
        lines.extend(f"    {_ROLE_STYLES[role]}" for role in style_roles)
        for role in style_roles:
            role_ids = [node.node_id for node in graph.nodes if node.role == role]
            for offset in range(0, len(role_ids), 40):
                lines.append(f"    class {','.join(role_ids[offset : offset + 40])} {role}")
    return "\n".join(lines)


def _minimal_result(
    *,
    direction: str,
    fallback_title: str,
    fallback_details: str,
    repairs: MermaidRepairLog,
    omitted: Counter[str],
    warnings: list[str],
    validator: MermaidValidator | None,
    validator_name: str | None,
    limits: MermaidLimits,
) -> MermaidRenderResult:
    _append_omission_warning(warnings, omitted)
    builder = MermaidGraphBuilder(limits=limits)
    title_id = builder.add_node("fallback", "title", fallback_title, "topic", fallback="Visualization")
    details_id = builder.add_node(
        "fallback",
        "details",
        fallback_details,
        "notice",
        fallback="Visualization simplified",
    )
    builder.add_edge(title_id, details_id)
    source = _serialize_graph(builder.graph, direction=direction, tier="safe", style_roles=())
    structural_ok, structural_issues = validate_mermaid_source(source, limits=limits)
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


def _validate_candidate(
    source: str,
    validator: MermaidValidator | None,
    *,
    limits: MermaidLimits,
) -> tuple[bool, list[str]]:
    structural_ok, issues = validate_mermaid_source(source, limits=limits)
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
    repairs: MermaidRepairLog | None,
) -> str:
    try:
        original = "" if value is None else str(value)
    except Exception:  # pragma: no cover - direct Python callers can supply hostile objects
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
    byte_limit: int,
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


def _append_omission_warning(warnings: list[str], omitted: Counter[str]) -> None:
    if not omitted or any(warning.startswith("Visual output omitted or summarized") for warning in warnings):
        return
    details = ", ".join(f"{key}={count}" for key, count in sorted(omitted.items()) if count > 0)
    warnings.append(f"Visual output omitted or summarized content: {details}.")


def _record_minimal_fallback_omissions(
    graph: MermaidGraph,
    *,
    omitted: Counter[str],
    repairs: MermaidRepairLog,
) -> None:
    role_names = {
        "topic": "fallback_topic_nodes",
        "spine": "fallback_year_anchors",
        "branch": "fallback_branches",
        "event": "fallback_entries",
        "root": "fallback_root_nodes",
        "citing": "fallback_citing_nodes",
        "reference": "fallback_reference_nodes",
        "shared": "fallback_shared_nodes",
        "notice": "fallback_notice_nodes",
    }
    for node in graph.nodes:
        omitted[role_names.get(node.role, "fallback_other_nodes")] += 1
    omitted["fallback_edges"] += len(graph.edges)
    repairs.add("minimal_fallback_omitted_graph")


__all__ = [
    "DEFAULT_MERMAID_LIMITS",
    "MermaidEdge",
    "MermaidGraph",
    "MermaidGraphBuilder",
    "MermaidLimits",
    "MermaidNode",
    "MermaidRenderResult",
    "MermaidRepairLog",
    "MermaidValidator",
    "mermaid_label",
    "render_mermaid_graph",
    "stable_mermaid_node_id",
    "validate_mermaid_source",
]
