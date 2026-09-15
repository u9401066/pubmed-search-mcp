"""Completeness and integrity audit for chronicle revisions.

Every chronicle response carries an audit so agents can tell the difference
between "this is the whole picture" and "this is what we could retrieve".
Findings are actionable: each one names the gap and what to do about it.
"""

from __future__ import annotations

from collections import Counter
from itertools import pairwise
from math import isfinite
from typing import TYPE_CHECKING, Any

from pubmed_search.domain.entities.chronicle import (
    ChronicleAudit,
    ChronicleAuditFinding,
    ChronicleEdgeType,
    ChronicleNodeType,
    resolve_chronicle_membership,
)

from .graph import branch_node_id, topic_node_id
from .ordering import chronicle_time_status, chronology_key, definitely_precedes, parse_chronicle_time

if TYPE_CHECKING:
    from pubmed_search.domain.entities.chronicle import ChronicleSnapshot

#: Files a persisted chronicle artifact must always contain.
REQUIRED_ARTIFACT_FILES = (
    "manifest.json",
    "snapshot.json",
    "chronicle_map.json",
    "chronicle.mmd",
    "mermaid_validation.json",
    "timeline.json",
    "lineage_tree.json",
    "graph.json",
    "evidence.json",
    "milestones.json",
    "audit.json",
)

#: Below this share of entries carrying identifiers, coverage is a hard failure.
_IDENTIFIER_FAIL_RATIO = 0.5

#: At or above this share, topic branches cannot be described as cleanly split.
_LINEAGE_OVERLAP_WARN_RATIO = 0.2


def audit_chronicle(snapshot: ChronicleSnapshot, *, artifact_files: list[str] | None = None) -> ChronicleAudit:
    """Audit *snapshot* for evidence, branch, graph, and chronology integrity.

    Args:
        snapshot: The revision to check.
        artifact_files: File names prepared for the artifact bundle. When
            provided, missing required payload names are reported; this does not
            prove that persistence succeeded.

    Returns:
        A :class:`ChronicleAudit` whose ``status`` is the worst finding status.
    """
    findings: list[ChronicleAuditFinding] = [
        _audit_inputs(snapshot),
        _audit_snapshot_identity(snapshot),
        _audit_evidence(snapshot),
        _audit_identifiers(snapshot),
        _audit_branches(snapshot),
        _audit_lineage_semantics(snapshot),
        _audit_mermaid_validation(snapshot),
        _audit_graph(snapshot),
        _audit_chronology(snapshot),
        _audit_narrative_citations(snapshot),
        _audit_source_coverage(snapshot),
        _audit_citation_metrics_coverage(snapshot),
    ]
    if artifact_files is not None:
        findings.append(_audit_artifacts(artifact_files))
    return ChronicleAudit(findings=findings)


def _audit_inputs(snapshot: ChronicleSnapshot) -> ChronicleAuditFinding:
    """Check that the revision retrieved anything at all."""
    requested_pmids = {str(pmid).strip() for pmid in snapshot.input_scope.pmids if str(pmid).strip()}
    retrieved_pmids = {
        str(article.pmid).strip()
        for article in snapshot.evidence_articles
        if article.pmid and str(article.pmid).strip()
    }
    missing_pmids = sorted(requested_pmids - retrieved_pmids)
    unexpected_pmids = sorted(retrieved_pmids - requested_pmids) if requested_pmids else []
    requested = len(requested_pmids)
    retrieved = len(snapshot.entries)
    details = {
        "mode": snapshot.input_scope.mode,
        "requested_pmids": requested,
        "retrieved_pmids": len(retrieved_pmids),
        "missing_requested_pmids": missing_pmids,
        "unexpected_retrieved_pmids": unexpected_pmids,
        "entries_created": retrieved,
        "evidence_articles": len(snapshot.evidence_articles),
    }
    if retrieved == 0:
        return ChronicleAuditFinding(
            check="input_coverage",
            status="fail",
            message="No chronicle entries were produced. Broaden the topic, raise max_events, or supply PMIDs.",
            details=details,
        )
    if unexpected_pmids:
        return ChronicleAuditFinding(
            check="input_coverage",
            status="fail",
            message=(
                f"Explicit PMID scope produced {len(unexpected_pmids)} unrequested PubMed records; "
                "the evidence identity contract is violated."
            ),
            details=details,
        )
    if missing_pmids:
        return ChronicleAuditFinding(
            check="input_coverage",
            status="warn",
            message=(
                f"Only {requested - len(missing_pmids)} of {requested} requested PMIDs became chronicle evidence; "
                "the missing identifiers were not returned by PubMed."
            ),
            details=details,
        )
    return ChronicleAuditFinding(
        check="input_coverage",
        status="pass",
        message=f"{retrieved} entries assembled from the requested scope.",
        details=details,
    )


def _audit_evidence(snapshot: ChronicleSnapshot) -> ChronicleAuditFinding:
    """Check that non-background entries carry at least one article."""
    missing = [entry.entry_id for entry in snapshot.entries if entry.requires_evidence and entry.evidence.is_empty]
    details = {
        "entries": len(snapshot.entries),
        "entries_without_evidence": len(missing),
        "sample": missing[:5],
    }
    if missing:
        return ChronicleAuditFinding(
            check="evidence_coverage",
            status="fail",
            message=f"{len(missing)} entries have no supporting article. Every non-background entry must cite evidence.",
            details=details,
        )
    return ChronicleAuditFinding(
        check="evidence_coverage",
        status="pass",
        message="Every non-background entry cites at least one article.",
        details=details,
    )


def _audit_snapshot_identity(snapshot: ChronicleSnapshot) -> ChronicleAuditFinding:
    """Require non-empty, unique entry IDs before any keyed projection is trusted."""
    counts = Counter(entry.entry_id for entry in snapshot.entries)
    duplicate_ids = sorted(entry_id for entry_id, count in counts.items() if count > 1)
    empty_indices = [index for index, entry in enumerate(snapshot.entries) if not entry.entry_id]
    details = {"duplicate_entry_ids": duplicate_ids, "empty_entry_id_indices": empty_indices}
    if duplicate_ids or empty_indices:
        return ChronicleAuditFinding(
            check="snapshot_identity",
            status="fail",
            message=(
                f"Snapshot identity is ambiguous: {len(duplicate_ids)} duplicate entry IDs and "
                f"{len(empty_indices)} empty entry IDs. Keyed projections cannot safely deduplicate these entries."
            ),
            details=details,
        )
    return ChronicleAuditFinding(
        check="snapshot_identity",
        status="pass",
        message=f"All {len(snapshot.entries)} entry IDs are non-empty and unique.",
        details=details,
    )


def _audit_identifiers(snapshot: ChronicleSnapshot) -> ChronicleAuditFinding:
    """Check that evidence articles are citable (PMID/DOI/PMCID)."""
    articles = snapshot.evidence_articles
    if not articles:
        return ChronicleAuditFinding(
            check="evidence_identifiers",
            status="warn",
            message="No evidence articles to check for identifiers.",
            details={"articles": 0},
        )

    unidentified = [a.title for a in articles if not a.has_identifier]
    missing_year = [a.evidence_id for a in articles if a.year is None]
    identified_ratio = 1 - (len(unidentified) / len(articles))
    details = {
        "articles": len(articles),
        "without_identifier": len(unidentified),
        "without_year": len(missing_year),
        "identified_ratio": round(identified_ratio, 3),
    }
    if identified_ratio < _IDENTIFIER_FAIL_RATIO:
        status, message = "fail", "Most evidence articles lack a PMID/DOI/PMCID, so claims cannot be verified."
    elif unidentified or missing_year:
        status, message = (
            "warn",
            f"{len(unidentified)} articles lack an identifier and {len(missing_year)} lack a year.",
        )
    else:
        status, message = "pass", "All evidence articles carry an identifier and a year."
    return ChronicleAuditFinding(check="evidence_identifiers", status=status, message=message, details=details)


def _audit_branches(snapshot: ChronicleSnapshot) -> ChronicleAuditFinding:
    """Check bidirectional, exactly-once ownership and structural branch links."""
    membership = resolve_chronicle_membership(snapshot)
    child_parent_ids = {branch.parent_branch_id for branch in snapshot.branches if branch.parent_branch_id}
    empty_branches = [
        branch.branch_id
        for branch in snapshot.branches
        if not branch.entry_ids and branch.branch_id not in child_parent_ids
    ]
    repaired_entries = [
        {
            "entry_index": index,
            "entry_id": snapshot.entries[index].entry_id,
            "declared_branch_id": snapshot.entries[index].branch_id,
            "reasons": list(membership.repair_reasons_by_entry[index]),
        }
        for index in membership.repaired_entry_indices
    ]
    branch_id_counts = Counter(branch.branch_id for branch in snapshot.branches)
    duplicate_branch_ids = sorted(branch_id for branch_id, count in branch_id_counts.items() if count > 1)
    known_branch_ids = set(branch_id_counts)
    invalid_assignments = [entry.entry_id for entry in snapshot.entries if entry.branch_id not in known_branch_ids]
    invalid_parents = [
        branch.branch_id
        for branch in snapshot.branches
        if branch.parent_branch_id and branch.parent_branch_id not in known_branch_ids
    ]
    details = {
        "branches": len(snapshot.branches),
        "empty_branches": empty_branches,
        "unassigned_entries": len(repaired_entries),
        "repaired_entries": repaired_entries,
        "dangling_branch_memberships": [
            {
                "branch_index": branch_index,
                "branch_id": snapshot.branches[branch_index].branch_id,
                "entry_id": entry_id,
            }
            for branch_index, entry_id in membership.dangling_memberships
        ],
        "duplicate_branch_ids": duplicate_branch_ids,
        "invalid_entry_assignments": invalid_assignments,
        "invalid_parent_branches": invalid_parents,
    }
    if not snapshot.branches:
        return ChronicleAuditFinding(
            check="branch_coverage",
            status="warn",
            message="No research branches were derived; the chronicle is a flat list.",
            details=details,
        )
    if (
        empty_branches
        or repaired_entries
        or membership.dangling_memberships
        or duplicate_branch_ids
        or invalid_assignments
        or invalid_parents
    ):
        return ChronicleAuditFinding(
            check="branch_coverage",
            status="warn",
            message=(
                f"Branch repair required: {len(empty_branches)} empty leaf branches, "
                f"{len(repaired_entries)} unassigned or inconsistent entries, "
                f"{len(duplicate_branch_ids)} duplicate IDs, {len(invalid_assignments)} invalid assignments, "
                f"{len(invalid_parents)} invalid parents, and "
                f"{len(membership.dangling_memberships)} dangling memberships."
            ),
            details=details,
        )
    return ChronicleAuditFinding(
        check="branch_coverage",
        status="pass",
        message=f"All {len(snapshot.entries)} entries are assigned across {len(snapshot.branches)} branches.",
        details=details,
    )


def _audit_graph(snapshot: ChronicleSnapshot) -> ChronicleAuditFinding:
    """Check graph edge invariants and endpoint integrity."""
    violations = snapshot.graph.validate()
    expected_nodes, expected_edges = _expected_graph_contract(snapshot)
    actual_nodes = snapshot.graph.nodes
    missing_nodes = sorted(node_id for node_id in expected_nodes if node_id not in actual_nodes)
    wrong_node_types = sorted(
        f"{node_id}: expected {node_type.value}, got {actual_nodes[node_id].node_type.value}"
        for node_id, node_type in expected_nodes.items()
        if node_id in actual_nodes and actual_nodes[node_id].node_type is not node_type
    )
    actual_edges = {
        (edge.source, edge.target, edge.edge_type)
        for edge in snapshot.graph.edges.values()
        if edge.edge_type is not ChronicleEdgeType.SUPERSEDES
    }
    missing_edges = sorted(
        (source, target, edge_type.value) for source, target, edge_type in expected_edges - actual_edges
    )
    unexpected_edges = sorted(
        (source, target, edge_type.value) for source, target, edge_type in actual_edges - expected_edges
    )
    chronology_violations = _graph_chronology_violations(snapshot)
    details = {
        "nodes": len(snapshot.graph.nodes),
        "edges": len(snapshot.graph.edges),
        "violations": violations[:5],
        "missing_expected_nodes": missing_nodes[:20],
        "wrong_expected_node_types": wrong_node_types[:20],
        "missing_expected_edges": missing_edges[:20],
        "unexpected_managed_edges": unexpected_edges[:20],
        "chronology_violations": chronology_violations[:20],
    }
    problem_count = (
        len(violations)
        + len(missing_nodes)
        + len(wrong_node_types)
        + len(missing_edges)
        + len(unexpected_edges)
        + len(chronology_violations)
    )
    if problem_count:
        return ChronicleAuditFinding(
            check="graph_integrity",
            status="fail",
            message=(
                f"Graph has {problem_count} integrity problems: {len(violations)} invariant violations, "
                f"{len(missing_nodes)} missing nodes, {len(wrong_node_types)} wrong node types, "
                f"{len(missing_edges)} missing edges, {len(unexpected_edges)} unexpected edges, and "
                f"{len(chronology_violations)} chronology violations."
            ),
            details=details,
        )
    return ChronicleAuditFinding(
        check="graph_integrity",
        status="pass",
        message=f"Graph is consistent: {len(snapshot.graph.nodes)} nodes, {len(snapshot.graph.edges)} edges.",
        details=details,
    )


def _audit_lineage_semantics(snapshot: ChronicleSnapshot) -> ChronicleAuditFinding:
    """Report semantic support and whether topic branches materially overlap."""
    raw = snapshot.metadata.get("lineage_diagnostics")
    diagnostics = raw if isinstance(raw, dict) else {}
    basis = str(diagnostics.get("basis") or "unknown")
    coverage = _bounded_diagnostic_ratio(diagnostics.get("semantic_coverage_ratio"))
    selected = diagnostics.get("selected_signals")
    selected_signals = selected if isinstance(selected, list) else []
    raw_cross_links = diagnostics.get("cross_signal_links")
    cross_signal_links = (
        [link for link in raw_cross_links if isinstance(link, dict)] if isinstance(raw_cross_links, list) else []
    )
    raw_memberships = diagnostics.get("event_signal_memberships")
    memberships = (
        [membership for membership in raw_memberships if isinstance(membership, dict)]
        if isinstance(raw_memberships, list)
        else []
    )
    membership_overlap_count = sum(
        bool(membership.get("secondary_branch_ids"))
        or _nonnegative_diagnostic_count(membership.get("matched_signal_count")) > 1
        for membership in memberships
    )
    overlap_event_count = max(
        _nonnegative_diagnostic_count(diagnostics.get("overlap_event_count")),
        len(cross_signal_links),
        membership_overlap_count,
    )
    derived_overlap_ratio = overlap_event_count / len(snapshot.entries) if snapshot.entries else 0.0
    overlap_ratio = (
        min(1.0, derived_overlap_ratio)
        if snapshot.entries
        else _bounded_diagnostic_ratio(diagnostics.get("overlap_ratio"))
    )
    assigned_event_count = _nonnegative_diagnostic_count(diagnostics.get("assigned_event_count"))
    derived_assigned_overlap_ratio = overlap_event_count / assigned_event_count if assigned_event_count else 0.0
    overlap_ratio_among_assigned = (
        min(1.0, derived_assigned_overlap_ratio)
        if assigned_event_count
        else _bounded_diagnostic_ratio(diagnostics.get("overlap_ratio_among_assigned"))
    )
    details = {
        "basis": basis,
        "semantic_coverage_ratio": round(coverage, 3),
        "selected_signal_count": len(selected_signals),
        "selected_signals": selected_signals,
        "assignment_semantics": diagnostics.get("assignment_semantics"),
        "assigned_event_count": assigned_event_count,
        "overlap_event_count": overlap_event_count,
        "overlap_ratio": round(overlap_ratio, 3),
        "overlap_ratio_among_assigned": round(overlap_ratio_among_assigned, 3),
        "overlap_warning_ratio": _LINEAGE_OVERLAP_WARN_RATIO,
        "max_signals_per_event": _nonnegative_diagnostic_count(diagnostics.get("max_signals_per_event")),
        "cross_signal_link_count": len(cross_signal_links),
        "cross_signal_link_sample": cross_signal_links[:10],
        "reason": diagnostics.get("reason"),
    }
    if basis == "topic_signals" and len(selected_signals) >= 2 and coverage >= 0.6:
        significant_overlap_ratio = max(overlap_ratio, overlap_ratio_among_assigned)
        if overlap_event_count and significant_overlap_ratio >= _LINEAGE_OVERLAP_WARN_RATIO:
            return ChronicleAuditFinding(
                check="lineage_semantics",
                status="warn",
                message=(
                    f"Semantic topic grouping is supported, but {overlap_event_count} entries "
                    f"({overlap_ratio:.0%} overall; {overlap_ratio_among_assigned:.0%} of assigned entries) "
                    "matched multiple selected signals. Branches are single primary assignments with explicit "
                    "cross-links, not cleanly separated or causal lineages."
                ),
                details=details,
            )
        return ChronicleAuditFinding(
            check="lineage_semantics",
            status="pass",
            message=(
                f"Semantic topic grouping is supported by {len(selected_signals)} distinctive "
                f"MeSH/keyword signals covering {coverage:.0%} of entries. Branches are primary assignments "
                "rather than causal lineages; multi-signal matches remain explicit cross-link provenance."
            ),
            details=details,
        )
    if basis == "research_stage_fallback":
        return ChronicleAuditFinding(
            check="lineage_semantics",
            status="warn",
            message=(
                "Topic signals were insufficient, so branches show research stages rather than semantic sub-topics. "
                "Do not describe this projection as a discovered topic lineage."
            ),
            details=details,
        )
    return ChronicleAuditFinding(
        check="lineage_semantics",
        status="warn",
        message="Semantic lineage provenance is missing or insufficient; interpret branch labels cautiously.",
        details=details,
    )


def _bounded_diagnostic_ratio(value: object) -> float:
    """Coerce an untrusted persisted diagnostic into a finite 0-1 ratio."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 0.0
    try:
        ratio = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not isfinite(ratio):
        return 0.0
    return min(1.0, max(0.0, ratio))


def _nonnegative_diagnostic_count(value: object) -> int:
    """Coerce an untrusted persisted diagnostic into a non-negative count."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if isinstance(value, float) and not isfinite(value):
        return 0
    return max(0, int(value))


def _audit_mermaid_validation(snapshot: ChronicleSnapshot) -> ChronicleAuditFinding:
    """Report deterministic Mermaid normalization and fallback status."""
    from .projectors import render_chronicle_mermaid_result

    result = render_chronicle_mermaid_result(snapshot)
    details = result.to_dict()
    correction_codes = {
        str(correction.get("code")) for correction in result.corrections if isinstance(correction, dict)
    }
    structural_repair_codes = {
        "branch_cycle_removed",
        "duplicate_branch_id",
        "duplicate_entry_id",
        "invalid_branch_parent",
        "invalid_branch_year",
        "invalid_year_anchor",
        "malformed_projection",
        "malformed_projection_row",
        "visual_size_capped",
    }
    if not result.structural_valid:
        return ChronicleAuditFinding(
            check="mermaid_renderability",
            status="fail",
            message="The minimal Mermaid fallback failed structural validation.",
            details=details,
        )
    if result.omitted_counts:
        omitted_total = sum(result.omitted_counts.values())
        fallback_note = f" using the {result.tier} tier" if result.tier != "rich" else ""
        return ChronicleAuditFinding(
            check="mermaid_renderability",
            status="warn",
            message=(
                f"Mermaid{fallback_note} is structurally valid but summarizes {omitted_total} visual items; "
                "use chronicle_map.json, timeline.json, or snapshot.json for the complete record."
            ),
            details=details,
        )
    if result.status == "fallback":
        return ChronicleAuditFinding(
            check="mermaid_renderability",
            status="warn",
            message=(
                f"Mermaid was rebuilt with the {result.tier} fallback; "
                "the complete coordinate data remains in chronicle_map.json."
            ),
            details=details,
        )
    structural_repairs = sorted(correction_codes & structural_repair_codes)
    if structural_repairs:
        return ChronicleAuditFinding(
            check="mermaid_renderability",
            status="warn",
            message=(
                "Mermaid renders after structural repair "
                f"({', '.join(structural_repairs)}); verify the repaired lineage in chronicle_map.json."
            ),
            details=details,
        )
    if result.status == "repaired":
        return ChronicleAuditFinding(
            check="mermaid_renderability",
            status="pass",
            message="Mermaid passed structural validation after deterministic label or structure normalization.",
            details=details,
        )
    return ChronicleAuditFinding(
        check="mermaid_renderability",
        status="pass",
        message="Mermaid passed deterministic structural validation without repairs.",
        details=details,
    )


def _audit_chronology(snapshot: ChronicleSnapshot) -> ChronicleAuditFinding:
    """Distinguish legitimately undated entries from malformed/impossible dates."""
    undated: list[str] = []
    invalid: list[dict[str, str | None]] = []
    reversed_ranges: list[str] = []
    for entry in snapshot.entries:
        status = chronicle_time_status(entry.time_start)
        if status == "undated":
            undated.append(entry.entry_id)
        elif status == "invalid":
            invalid.append({"entry_id": entry.entry_id, "field": "time_start", "value": entry.time_start})

        if entry.time_end is None:
            continue
        end_status = chronicle_time_status(entry.time_end)
        if end_status != "valid":
            invalid.append({"entry_id": entry.entry_id, "field": "time_end", "value": entry.time_end})
            continue
        start = parse_chronicle_time(entry.time_start)
        end = parse_chronicle_time(entry.time_end)
        if start is not None and end is not None and end.latest < start.earliest:
            reversed_ranges.append(entry.entry_id)

    year_range = snapshot.year_range
    details = {
        "undated_entries": len(undated),
        "undated_entry_ids": undated,
        "invalid_dates": invalid,
        "reversed_ranges": reversed_ranges,
        "year_range": list(year_range) if year_range else None,
    }
    if invalid or reversed_ranges:
        return ChronicleAuditFinding(
            check="chronology",
            status="fail",
            message=(
                f"Chronology contains {len(invalid)} malformed or impossible date values and "
                f"{len(reversed_ranges)} ranges whose end precedes their start."
            ),
            details=details,
        )
    if undated:
        return ChronicleAuditFinding(
            check="chronology",
            status="warn",
            message=f"{len(undated)} entries have no parseable year and cannot be placed on the timeline.",
            details=details,
        )
    return ChronicleAuditFinding(
        check="chronology",
        status="pass",
        message=f"All entries are dated; span {year_range[0]}-{year_range[1]}." if year_range else "No entries dated.",
        details=details,
    )


def _audit_source_coverage(snapshot: ChronicleSnapshot) -> ChronicleAuditFinding:
    """Check whether per-source retrieval counts were captured."""
    counts = snapshot.input_scope.source_counts
    raw_timeline_metadata = snapshot.metadata.get("timeline_metadata")
    timeline_metadata = raw_timeline_metadata if isinstance(raw_timeline_metadata, dict) else {}
    retrieved_count = _nonnegative_diagnostic_count(timeline_metadata.get("total_searched"))
    filtered_count = _nonnegative_diagnostic_count(timeline_metadata.get("articles_after_filters"))
    candidate_count = _nonnegative_diagnostic_count(timeline_metadata.get("milestone_candidates"))
    detected_before_cap = _nonnegative_diagnostic_count(timeline_metadata.get("events_before_output_cap"))
    emitted_count = len(snapshot.entries)
    selection_limited = bool(
        (candidate_count and filtered_count > candidate_count)
        or (detected_before_cap and detected_before_cap > emitted_count)
    )
    details: dict[str, Any] = {
        "source_counts": counts,
        "normalized_counts": {},
        "selection_counts": {
            "retrieved": retrieved_count,
            "after_filters": filtered_count,
            "milestone_candidates": candidate_count,
            "events_before_output_cap": detected_before_cap,
            "events_emitted": emitted_count,
        },
        "selection_limited": selection_limited,
    }
    if not counts:
        return ChronicleAuditFinding(
            check="source_coverage",
            status="warn",
            message="No per-source returned/available counts were captured; retrieval completeness is unknown.",
            details=details,
        )

    incomplete_sources: list[str] = []
    unknown_available_sources: list[str] = []
    invalid_sources: list[str] = []
    for source, raw_counts in counts.items():
        returned: int | None
        available: int | None
        if isinstance(raw_counts, dict):
            raw_returned = raw_counts.get("returned")
            raw_available = raw_counts.get("available")
            returned = (
                raw_returned
                if isinstance(raw_returned, int) and not isinstance(raw_returned, bool) and raw_returned >= 0
                else None
            )
            available = (
                raw_available
                if isinstance(raw_available, int) and not isinstance(raw_available, bool) and raw_available >= 0
                else None
            )
        else:
            returned = None
            available = None

        details["normalized_counts"][str(source)] = {"returned": returned, "available": available}
        if returned is None or (available is not None and returned > available):
            invalid_sources.append(str(source))
        elif available is None:
            unknown_available_sources.append(str(source))
        elif available > returned:
            incomplete_sources.append(str(source))

    details["incomplete_sources"] = incomplete_sources
    details["unknown_available_sources"] = unknown_available_sources
    details["invalid_sources"] = invalid_sources
    if invalid_sources:
        return ChronicleAuditFinding(
            check="source_coverage",
            status="warn",
            message=f"Source counts are malformed for: {', '.join(invalid_sources)}.",
            details=details,
        )
    if unknown_available_sources or incomplete_sources or selection_limited:
        limitations: list[str] = []
        if incomplete_sources:
            limitations.append(f"bounded samples from {', '.join(incomplete_sources)}")
        if unknown_available_sources:
            limitations.append(f"unknown total availability for {', '.join(unknown_available_sources)}")
        if selection_limited:
            limitations.append("landmark/candidate or output limits selected a subset of retrieved articles")
        return ChronicleAuditFinding(
            check="source_coverage",
            status="warn",
            message=(
                "Retrieval coverage is not exhaustive (" + "; ".join(limitations) + "). "
                "Treat the Chronicle as an observed, ranked sample rather than a complete census."
            ),
            details=details,
        )
    return ChronicleAuditFinding(
        check="source_coverage",
        status="pass",
        message=f"Source coverage recorded for {len(counts)} sources.",
        details=details,
    )


def _audit_citation_metrics_coverage(snapshot: ChronicleSnapshot) -> ChronicleAuditFinding:
    """Audit iCite enrichment coverage and its effective-ranking claim."""
    raw_timeline_metadata = snapshot.metadata.get("timeline_metadata")
    timeline_metadata = raw_timeline_metadata if isinstance(raw_timeline_metadata, dict) else {}
    raw_retrieval = timeline_metadata.get("retrieval")
    retrieval = raw_retrieval if isinstance(raw_retrieval, dict) else {}
    supported_modes = {"topic_search", "explicit_pmids"}
    supported_rankings = {"pubmed_relevance", "icite_citation_count_then_pubmed_relevance"}
    raw_retrieval_mode = retrieval.get("mode")
    raw_ranking = retrieval.get("ranking")
    raw_ranking_requested = retrieval.get("ranking_requested")
    retrieval_mode = (
        raw_retrieval_mode if isinstance(raw_retrieval_mode, str) and raw_retrieval_mode in supported_modes else None
    )
    ranking = raw_ranking if isinstance(raw_ranking, str) and raw_ranking in supported_rankings else None
    ranking_requested = (
        raw_ranking_requested
        if isinstance(raw_ranking_requested, str) and raw_ranking_requested in supported_rankings
        else None
    )
    base_details: dict[str, Any] = {
        "retrieval_mode": retrieval_mode,
        "ranking_requested": ranking_requested,
        "effective_ranking": ranking,
    }
    if retrieval_mode != "topic_search":
        return ChronicleAuditFinding(
            check="citation_metrics_coverage",
            status="pass",
            message="Citation-metric enrichment is not applicable to this retrieval mode.",
            details={**base_details, "status": "not_applicable"},
        )

    raw_coverage = retrieval.get("citation_metrics")
    if not isinstance(raw_coverage, dict):
        return ChronicleAuditFinding(
            check="citation_metrics_coverage",
            status="warn",
            message="Topic retrieval did not record typed iCite coverage; citation-based ranking is not auditable.",
            details={**base_details, "status": "unknown"},
        )

    expected_statuses = {"not_requested", "complete", "partial", "empty", "error"}
    raw_status = raw_coverage.get("status")
    status = raw_status if isinstance(raw_status, str) and raw_status in expected_statuses else None
    requested = _strict_nonnegative_count(raw_coverage.get("requested"))
    returned = _strict_nonnegative_count(raw_coverage.get("returned"))
    applied = _strict_nonnegative_count(raw_coverage.get("applied"))
    citation_counts_applied = _strict_nonnegative_count(raw_coverage.get("citation_counts_applied"))
    complete = raw_coverage.get("complete") if isinstance(raw_coverage.get("complete"), bool) else None
    raw_error = raw_coverage.get("error")
    safe_error = _safe_citation_metrics_error(raw_error)
    details = {
        **base_details,
        "schema_version": (
            "citation-metrics-coverage/v1"
            if raw_coverage.get("schema_version") == "citation-metrics-coverage/v1"
            else None
        ),
        "source": "nih_icite" if raw_coverage.get("source") == "nih_icite" else None,
        "status": status,
        "requested": requested,
        "returned": returned,
        "applied": applied,
        "citation_counts_applied": citation_counts_applied,
        "complete": complete,
        "error": safe_error,
    }
    counts = (requested, returned, applied, citation_counts_applied)
    structurally_valid = (
        raw_coverage.get("schema_version") == "citation-metrics-coverage/v1"
        and raw_coverage.get("source") == "nih_icite"
        and ranking is not None
        and ranking_requested is not None
        and status in expected_statuses
        and all(count is not None for count in counts)
        and complete is not None
    )
    if (
        structurally_valid
        and requested is not None
        and returned is not None
        and applied is not None
        and citation_counts_applied is not None
    ):
        structurally_valid = (
            applied <= requested
            and applied <= returned
            and citation_counts_applied <= applied
            and (
                (status == "not_requested" and counts == (0, 0, 0, 0) and complete is False and raw_error is None)
                or (
                    status == "complete"
                    and requested > 0
                    and applied == requested
                    and complete is True
                    and raw_error is None
                )
                or (status == "partial" and 0 < applied < requested and complete is False and raw_error is None)
                or (
                    status == "empty"
                    and requested > 0
                    and applied == 0
                    and citation_counts_applied == 0
                    and complete is False
                    and raw_error is None
                )
                or (
                    status == "error"
                    and requested > 0
                    and applied == 0
                    and citation_counts_applied == 0
                    and complete is False
                    and safe_error is not None
                )
            )
        )
    else:
        structurally_valid = False

    claims_icite_ranking = ranking == "icite_citation_count_then_pubmed_relevance"
    requested_icite_ranking = ranking_requested == "icite_citation_count_then_pubmed_relevance"
    has_sortable_metrics = (
        structurally_valid
        and status in {"complete", "partial"}
        and citation_counts_applied is not None
        and citation_counts_applied > 0
    )
    if claims_icite_ranking and not has_sortable_metrics:
        return ChronicleAuditFinding(
            check="citation_metrics_coverage",
            status="fail",
            message="The Chronicle claims iCite ranking without any validated citation counts.",
            details=details,
        )
    if claims_icite_ranking and not requested_icite_ranking:
        return ChronicleAuditFinding(
            check="citation_metrics_coverage",
            status="fail",
            message="The Chronicle applied iCite ranking even though PubMed relevance was requested.",
            details=details,
        )
    if requested_icite_ranking and has_sortable_metrics and not claims_icite_ranking:
        return ChronicleAuditFinding(
            check="citation_metrics_coverage",
            status="fail",
            message="Validated citation counts were available, but the requested iCite ranking was not applied.",
            details=details,
        )
    if not structurally_valid:
        return ChronicleAuditFinding(
            check="citation_metrics_coverage",
            status="warn",
            message="iCite coverage metadata is malformed; citation enrichment completeness is unknown.",
            details=details,
        )
    if status == "error":
        return ChronicleAuditFinding(
            check="citation_metrics_coverage",
            status="warn",
            message="iCite enrichment failed; effective ranking fell back to PubMed relevance.",
            details=details,
        )
    if status == "partial":
        return ChronicleAuditFinding(
            check="citation_metrics_coverage",
            status="warn",
            message=f"iCite metrics covered {applied} of {requested} requested articles.",
            details=details,
        )
    if status == "empty":
        return ChronicleAuditFinding(
            check="citation_metrics_coverage",
            status="warn",
            message="iCite returned no metrics for the requested articles; effective ranking remained PubMed relevance.",
            details=details,
        )
    if status == "not_requested":
        return ChronicleAuditFinding(
            check="citation_metrics_coverage",
            status="pass",
            message="No articles required citation-metric enrichment.",
            details=details,
        )
    if requested_icite_ranking and not has_sortable_metrics:
        return ChronicleAuditFinding(
            check="citation_metrics_coverage",
            status="warn",
            message="iCite ranking was requested, but no valid citation counts were available to apply it.",
            details=details,
        )
    return ChronicleAuditFinding(
        check="citation_metrics_coverage",
        status="pass",
        message=f"iCite metrics covered all {requested} requested articles.",
        details=details,
    )


def _strict_nonnegative_count(value: object) -> int | None:
    """Validate a persisted provenance count without coercing malformed values."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _safe_citation_metrics_error(value: object) -> dict[str, Any] | None:
    """Copy only bounded, query-safe fields from persisted iCite errors."""
    if not isinstance(value, dict):
        return None
    kind = value.get("kind")
    retryable = value.get("retryable")
    status_code = value.get("status_code")
    exception_type = value.get("exception_type")
    if not isinstance(kind, str) or kind not in {
        "http",
        "timeout",
        "transport",
        "retryable",
        "validation",
        "unexpected",
    }:
        return None
    if not isinstance(retryable, bool):
        return None
    if status_code is not None and (
        not isinstance(status_code, int) or isinstance(status_code, bool) or not 100 <= status_code <= 599
    ):
        return None
    if not isinstance(exception_type, str) or len(exception_type) > 100 or not exception_type.isidentifier():
        return None
    return {
        "source": "nih_icite",
        "operation": "citation_metrics",
        "kind": kind,
        "retryable": retryable,
        "status_code": status_code,
        "exception_type": exception_type,
    }


def _audit_artifacts(artifact_files: list[str]) -> ChronicleAuditFinding:
    """Preflight the prepared artifact bundle; this does not verify persistence."""
    missing = [name for name in REQUIRED_ARTIFACT_FILES if name not in artifact_files]
    details = {"required": list(REQUIRED_ARTIFACT_FILES), "present": artifact_files, "missing": missing}
    if missing:
        return ChronicleAuditFinding(
            check="artifact_bundle_preflight",
            status="fail",
            message=f"Prepared artifact bundle is missing required payloads: {', '.join(missing)}",
            details=details,
        )
    return ChronicleAuditFinding(
        check="artifact_bundle_preflight",
        status="pass",
        message=(
            "All required artifact payload names were prepared; this preflight does not verify that they were "
            "successfully persisted."
        ),
        details=details,
    )


def _expected_graph_contract(
    snapshot: ChronicleSnapshot,
) -> tuple[dict[str, ChronicleNodeType], set[tuple[str, str, ChronicleEdgeType]]]:
    """Derive the nodes and managed edges required by one snapshot."""
    nodes: dict[str, ChronicleNodeType] = {topic_node_id(snapshot.chronicle_id): ChronicleNodeType.TOPIC}
    edges: set[tuple[str, str, ChronicleEdgeType]] = set()
    topic_id = topic_node_id(snapshot.chronicle_id)
    branch_counts = Counter(branch.branch_id for branch in snapshot.branches)
    for branch in snapshot.branches:
        node_id = branch_node_id(branch.branch_id)
        nodes[node_id] = ChronicleNodeType.BRANCH
        if branch.parent_branch_id and branch_counts.get(branch.parent_branch_id) == 1:
            edges.add((node_id, branch_node_id(branch.parent_branch_id), ChronicleEdgeType.BRANCHES_FROM))
        elif not branch.parent_branch_id:
            edges.add((topic_id, node_id, ChronicleEdgeType.CONTAINS))

    membership = resolve_chronicle_membership(snapshot)
    for entry_index, entry in enumerate(snapshot.entries):
        nodes[entry.entry_id] = ChronicleNodeType.ENTRY
        branch_index = membership.branch_index_by_entry[entry_index]
        if branch_index is not None:
            edges.add(
                (
                    branch_node_id(snapshot.branches[branch_index].branch_id),
                    entry.entry_id,
                    ChronicleEdgeType.CONTAINS,
                )
            )
        roles = (
            (entry.evidence.supporting_articles, ChronicleEdgeType.SUPPORTS),
            (entry.evidence.contradicting_articles, ChronicleEdgeType.CONTRADICTS),
            (entry.evidence.updating_articles, ChronicleEdgeType.UPDATES),
        )
        for articles, edge_type in roles:
            for article in articles:
                nodes[article.evidence_id] = ChronicleNodeType.EVIDENCE
                edges.add((article.evidence_id, entry.entry_id, edge_type))

    for branch_entry_indices in membership.branch_entry_indices:
        ordered = sorted((snapshot.entries[index] for index in branch_entry_indices), key=chronology_key)
        for previous, current in pairwise(ordered):
            if definitely_precedes(previous, current):
                edges.add((previous.entry_id, current.entry_id, ChronicleEdgeType.PRECEDES))

    for run_id in snapshot.input_scope.pipeline_run_ids:
        node_id = f"pipeline_run:{run_id}"
        nodes[node_id] = ChronicleNodeType.PIPELINE_RUN
        edges.add((topic_id, node_id, ChronicleEdgeType.DERIVED_FROM_PIPELINE_RUN))
    for artifact_uri in snapshot.input_scope.source_artifact_uris:
        node_id = f"artifact:{artifact_uri}"
        nodes[node_id] = ChronicleNodeType.ARTIFACT
        edges.add((topic_id, node_id, ChronicleEdgeType.PERSISTED_AS_ARTIFACT))
    return nodes, edges


def _graph_chronology_violations(snapshot: ChronicleSnapshot) -> list[str]:
    """Reject temporal edges that publication precision cannot support."""
    entry_by_id = {entry.entry_id: entry for entry in snapshot.entries}
    violations: list[str] = []
    for edge in snapshot.graph.edges.values():
        if edge.edge_type is ChronicleEdgeType.PRECEDES:
            source, target = entry_by_id.get(edge.source), entry_by_id.get(edge.target)
            if source is not None and target is not None and not definitely_precedes(source, target):
                violations.append(f"PRECEDES {edge.source} -> {edge.target} is not proved by reported date precision")
        elif edge.edge_type is ChronicleEdgeType.SUPERSEDES:
            source, target = entry_by_id.get(edge.source), entry_by_id.get(edge.target)
            if source is not None and target is not None and not definitely_precedes(target, source):
                violations.append(f"SUPERSEDES {edge.source} -> {edge.target} reverses or lacks a provable chronology")
    return violations


def _audit_narrative_citations(snapshot: ChronicleSnapshot) -> ChronicleAuditFinding:
    """Ensure the full narrative retains every occurrence and its evidence IDs."""
    from .narrator import narrate_chronicle, narrative_claim

    narrative = narrate_chronicle(snapshot, mode="full")
    expected_lines = Counter(narrative_claim(entry) for entry in snapshot.entries)
    actual_lines = Counter(line for line in narrative.splitlines() if line.startswith("- "))
    missing: list[dict[str, object]] = []
    missing_total = 0
    for line, expected_count in expected_lines.items():
        missing_count = max(0, expected_count - actual_lines[line])
        if missing_count:
            missing_total += missing_count
            missing.append({"line": line, "missing_occurrences": missing_count})
    details = {"expected_claim_occurrences": len(snapshot.entries), "missing_claims": missing[:20]}
    if missing:
        return ChronicleAuditFinding(
            check="narrative_citations",
            status="fail",
            message=f"Full narrative omitted or incompletely cited {missing_total} claims.",
            details=details,
        )
    return ChronicleAuditFinding(
        check="narrative_citations",
        status="pass",
        message=f"Full narrative preserves citations for all {len(snapshot.entries)} entry occurrences.",
        details=details,
    )


__all__ = ["REQUIRED_ARTIFACT_FILES", "audit_chronicle"]
