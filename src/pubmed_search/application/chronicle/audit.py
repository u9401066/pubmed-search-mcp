"""Completeness and integrity audit for chronicle revisions.

Every chronicle response carries an audit so agents can tell the difference
between "this is the whole picture" and "this is what we could retrieve".
Findings are actionable: each one names the gap and what to do about it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pubmed_search.domain.entities.chronicle import (
    ChronicleAudit,
    ChronicleAuditFinding,
)

if TYPE_CHECKING:
    from pubmed_search.domain.entities.chronicle import ChronicleSnapshot

#: Files a persisted chronicle artifact must always contain.
REQUIRED_ARTIFACT_FILES = (
    "manifest.json",
    "snapshot.json",
    "timeline.json",
    "lineage_tree.json",
    "graph.json",
    "evidence.json",
    "milestones.json",
    "audit.json",
)

#: Below this share of entries carrying identifiers, coverage is a hard failure.
_IDENTIFIER_FAIL_RATIO = 0.5


def audit_chronicle(snapshot: ChronicleSnapshot, *, artifact_files: list[str] | None = None) -> ChronicleAudit:
    """Audit *snapshot* for evidence, branch, graph, and chronology integrity.

    Args:
        snapshot: The revision to check.
        artifact_files: File names that were persisted for this revision. When
            provided, missing required files are reported.

    Returns:
        A :class:`ChronicleAudit` whose ``status`` is the worst finding status.
    """
    findings: list[ChronicleAuditFinding] = [
        _audit_inputs(snapshot),
        _audit_evidence(snapshot),
        _audit_identifiers(snapshot),
        _audit_branches(snapshot),
        _audit_graph(snapshot),
        _audit_chronology(snapshot),
        _audit_source_coverage(snapshot),
    ]
    if artifact_files is not None:
        findings.append(_audit_artifacts(artifact_files))
    return ChronicleAudit(findings=findings)


def _audit_inputs(snapshot: ChronicleSnapshot) -> ChronicleAuditFinding:
    """Check that the revision retrieved anything at all."""
    requested = len(snapshot.input_scope.pmids)
    retrieved = len(snapshot.entries)
    details = {
        "mode": snapshot.input_scope.mode,
        "requested_pmids": requested,
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
    if requested and retrieved < requested:
        return ChronicleAuditFinding(
            check="input_coverage",
            status="warn",
            message=(
                f"Only {retrieved} of {requested} requested PMIDs became chronicle entries; "
                "the rest lacked a detectable milestone or year."
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
    """Check for empty branches and entries with no research line."""
    empty_branches = [branch.branch_id for branch in snapshot.branches if not branch.entry_ids]
    orphan_entries = [entry.entry_id for entry in snapshot.entries if not entry.branch_id]
    details = {
        "branches": len(snapshot.branches),
        "empty_branches": empty_branches,
        "unassigned_entries": len(orphan_entries),
    }
    if not snapshot.branches:
        return ChronicleAuditFinding(
            check="branch_coverage",
            status="warn",
            message="No research branches were derived; the chronicle is a flat list.",
            details=details,
        )
    if empty_branches or orphan_entries:
        return ChronicleAuditFinding(
            check="branch_coverage",
            status="warn",
            message=(
                f"{len(empty_branches)} empty branches and {len(orphan_entries)} unassigned entries; "
                "the lineage tree is incomplete."
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
    details = {
        "nodes": len(snapshot.graph.nodes),
        "edges": len(snapshot.graph.edges),
        "violations": violations[:5],
    }
    if violations:
        return ChronicleAuditFinding(
            check="graph_integrity",
            status="fail",
            message=f"{len(violations)} graph edges violate the chronicle invariants.",
            details=details,
        )
    return ChronicleAuditFinding(
        check="graph_integrity",
        status="pass",
        message=f"Graph is consistent: {len(snapshot.graph.nodes)} nodes, {len(snapshot.graph.edges)} edges.",
        details=details,
    )


def _audit_chronology(snapshot: ChronicleSnapshot) -> ChronicleAuditFinding:
    """Check for entries without a usable year or with impossible ordering."""
    undated = [entry.entry_id for entry in snapshot.entries if entry.year is None]
    year_range = snapshot.year_range
    details = {"undated_entries": len(undated), "year_range": list(year_range) if year_range else None}
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
    details = {"source_counts": counts}
    if not counts:
        return ChronicleAuditFinding(
            check="source_coverage",
            status="warn",
            message="No per-source returned/available counts were captured; retrieval completeness is unknown.",
            details=details,
        )
    return ChronicleAuditFinding(
        check="source_coverage",
        status="pass",
        message=f"Source coverage recorded for {len(counts)} sources.",
        details=details,
    )


def _audit_artifacts(artifact_files: list[str]) -> ChronicleAuditFinding:
    """Check that all required artifact files were written."""
    missing = [name for name in REQUIRED_ARTIFACT_FILES if name not in artifact_files]
    details = {"required": list(REQUIRED_ARTIFACT_FILES), "present": artifact_files, "missing": missing}
    if missing:
        return ChronicleAuditFinding(
            check="artifact_files",
            status="fail",
            message=f"Chronicle artifact is missing required files: {', '.join(missing)}",
            details=details,
        )
    return ChronicleAuditFinding(
        check="artifact_files",
        status="pass",
        message="All required chronicle artifact files are present.",
        details=details,
    )


__all__ = ["REQUIRED_ARTIFACT_FILES", "audit_chronicle"]
