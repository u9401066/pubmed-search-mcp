"""Research Chronicle domain entities.

The chronicle is the durable, versioned, evidence-backed record of how a
research topic evolved. Timeline, lineage tree, citation graph, and narrative
outputs are *projections* of a :class:`ChronicleSnapshot`, never competing
sources of truth.

Key entities:
    - :class:`EvidenceArticle` / :class:`EvidenceBundle`: what backs a claim.
    - :class:`ChronicleEntry`: one interpretable research event or claim.
    - :class:`ChronicleBranch`: a readable research line grouping entries.
    - :class:`ChronicleGraph`: typed, auditable provenance graph.
    - :class:`ChronicleAudit`: completeness/integrity findings.
    - :class:`ChronicleSnapshot`: one immutable chronicle revision.

All entities round-trip through ``to_dict()`` / ``from_dict()`` so revisions can
be persisted as JSON artifacts and re-read by remote agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

CHRONICLE_SCHEMA_VERSION = "research-chronicle/v1"
_VALID_DATE_PART_COUNTS = frozenset({1, 2, 3})
_YEAR_DIGITS = 4
_MAX_CALENDAR_YEAR = 9999
_MONTH_PRECISION_PARTS = 2
_DAY_PRECISION_PARTS = 3

#: Audit statuses ordered from best to worst.
AUDIT_STATUS_ORDER = ("pass", "warn", "fail")


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()


def _as_str_list(value: Any) -> list[str]:
    """Coerce *value* into a list of non-empty strings."""
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item).strip()]


def _as_dict(value: Any) -> dict[str, Any]:
    """Return *value* when it is a dict, otherwise an empty dict."""
    return dict(value) if isinstance(value, dict) else {}


class ChronicleEntryType(Enum):
    """Interpretable kind of a chronicle entry."""

    MILESTONE = "milestone"
    EVIDENCE_SHIFT = "evidence_shift"
    GUIDELINE = "guideline"
    SAFETY = "safety"
    METHOD = "method"
    CONTROVERSY = "controversy"
    BACKGROUND = "background"

    @classmethod
    def parse(cls, value: Any) -> ChronicleEntryType:
        """Parse *value* into an entry type, defaulting to ``MILESTONE``."""
        try:
            return cls(str(value))
        except ValueError:
            return cls.MILESTONE


class ChronicleEntryStatus(Enum):
    """Lifecycle state of a chronicle entry within its revision."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    CONTESTED = "contested"
    BACKGROUND = "background"

    @classmethod
    def parse(cls, value: Any) -> ChronicleEntryStatus:
        """Parse *value* into a status, defaulting to ``ACTIVE``."""
        try:
            return cls(str(value))
        except ValueError:
            return cls.ACTIVE


class ChronicleNodeType(Enum):
    """Node kinds allowed in a chronicle provenance graph."""

    TOPIC = "Topic"
    BRANCH = "Branch"
    ENTRY = "ChronicleEntry"
    EVIDENCE = "EvidenceArticle"
    SESSION_EVENT = "SessionEvent"
    PIPELINE_RUN = "PipelineRun"
    ARTIFACT = "Artifact"


class ChronicleEdgeType(Enum):
    """Edge kinds allowed in a chronicle provenance graph."""

    PRECEDES = "precedes"
    BRANCHES_FROM = "branches_from"
    CONTAINS = "contains"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    UPDATES = "updates"
    SUPERSEDES = "supersedes"
    OBSERVED_IN_SESSION = "observed_in_session"
    DERIVED_FROM_PIPELINE_RUN = "derived_from_pipeline_run"
    PERSISTED_AS_ARTIFACT = "persisted_as_artifact"


#: Allowed ``(source_type, target_type)`` pairs per edge type. Builders and the
#: audit both enforce this so the graph stays interpretable.
EDGE_INVARIANTS: dict[ChronicleEdgeType, tuple[tuple[ChronicleNodeType, ChronicleNodeType], ...]] = {
    ChronicleEdgeType.PRECEDES: ((ChronicleNodeType.ENTRY, ChronicleNodeType.ENTRY),),
    ChronicleEdgeType.SUPERSEDES: ((ChronicleNodeType.ENTRY, ChronicleNodeType.ENTRY),),
    ChronicleEdgeType.BRANCHES_FROM: ((ChronicleNodeType.BRANCH, ChronicleNodeType.BRANCH),),
    ChronicleEdgeType.CONTAINS: (
        (ChronicleNodeType.TOPIC, ChronicleNodeType.BRANCH),
        (ChronicleNodeType.BRANCH, ChronicleNodeType.ENTRY),
    ),
    ChronicleEdgeType.SUPPORTS: ((ChronicleNodeType.EVIDENCE, ChronicleNodeType.ENTRY),),
    ChronicleEdgeType.CONTRADICTS: ((ChronicleNodeType.EVIDENCE, ChronicleNodeType.ENTRY),),
    ChronicleEdgeType.UPDATES: ((ChronicleNodeType.EVIDENCE, ChronicleNodeType.ENTRY),),
    ChronicleEdgeType.OBSERVED_IN_SESSION: (
        (ChronicleNodeType.SESSION_EVENT, ChronicleNodeType.EVIDENCE),
        (ChronicleNodeType.SESSION_EVENT, ChronicleNodeType.ENTRY),
        (ChronicleNodeType.SESSION_EVENT, ChronicleNodeType.TOPIC),
    ),
    ChronicleEdgeType.DERIVED_FROM_PIPELINE_RUN: ((ChronicleNodeType.TOPIC, ChronicleNodeType.PIPELINE_RUN),),
    ChronicleEdgeType.PERSISTED_AS_ARTIFACT: ((ChronicleNodeType.TOPIC, ChronicleNodeType.ARTIFACT),),
}


@dataclass(frozen=True)
class EvidenceArticle:
    """One article that supports, contradicts, or updates a chronicle entry.

    Attributes:
        title: Article title as reported by the retrieving source.
        pmid: PubMed identifier when known.
        doi: Digital Object Identifier when known.
        pmcid: PubMed Central identifier when known.
        year: Publication year.
        source: Which academic source returned the record.
        journal: Journal name.
        article_type: Publication type label (e.g. ``Randomized Controlled Trial``).
        citation_count: Total citations, when available.
        rcr: NIH Relative Citation Ratio, when available.
        claim_excerpt: Short quote or paraphrase backing the entry claim.
        fulltext_artifact_uri: Artifact URI of retrieved fulltext, when stored.
        figure_links: Figure metadata links for visual evidence.
        reference_verification_status: Result of reference verification, if run.
    """

    title: str
    pmid: str | None = None
    doi: str | None = None
    pmcid: str | None = None
    year: int | None = None
    source: str = "pubmed"
    journal: str | None = None
    article_type: str | None = None
    citation_count: int | None = None
    rcr: float | None = None
    claim_excerpt: str | None = None
    fulltext_artifact_uri: str | None = None
    figure_links: tuple[tuple[str, str], ...] = ()
    reference_verification_status: str | None = None

    @property
    def evidence_id(self) -> str:
        """Return a stable identifier for graph nodes and narrative citations."""
        if self.pmid:
            return f"pmid:{self.pmid}"
        if self.doi:
            return f"doi:{self.doi}"
        if self.pmcid:
            return f"pmcid:{self.pmcid}"
        return f"title:{self.title[:80]}"

    @property
    def has_identifier(self) -> bool:
        """Return whether the article carries a citable identifier."""
        return bool(self.pmid or self.doi or self.pmcid)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        return {
            "evidence_id": self.evidence_id,
            "title": self.title,
            "pmid": self.pmid,
            "doi": self.doi,
            "pmcid": self.pmcid,
            "year": self.year,
            "source": self.source,
            "journal": self.journal,
            "article_type": self.article_type,
            "citation_count": self.citation_count,
            "rcr": self.rcr,
            "claim_excerpt": self.claim_excerpt,
            "fulltext_artifact_uri": self.fulltext_artifact_uri,
            "figure_links": [{"label": label, "url": url} for label, url in self.figure_links],
            "reference_verification_status": self.reference_verification_status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceArticle:
        """Rebuild an evidence article from its serialized form."""
        raw_figures = data.get("figure_links") or []
        figure_links = tuple(
            (str(item.get("label", "")), str(item.get("url", "")))
            for item in raw_figures
            if isinstance(item, dict) and item.get("url")
        )
        year = data.get("year")
        return cls(
            title=str(data.get("title") or ""),
            pmid=data.get("pmid"),
            doi=data.get("doi"),
            pmcid=data.get("pmcid"),
            year=int(year) if isinstance(year, (int, float, str)) and str(year).isdigit() else None,
            source=str(data.get("source") or "pubmed"),
            journal=data.get("journal"),
            article_type=data.get("article_type"),
            citation_count=data.get("citation_count"),
            rcr=data.get("rcr"),
            claim_excerpt=data.get("claim_excerpt"),
            fulltext_artifact_uri=data.get("fulltext_artifact_uri"),
            figure_links=figure_links,
            reference_verification_status=data.get("reference_verification_status"),
        )


@dataclass
class EvidenceBundle:
    """Structured evidence attached to a single chronicle entry.

    Attributes:
        supporting_articles: Articles that back the entry claim.
        contradicting_articles: Articles that dispute the entry claim.
        updating_articles: Articles that refine or extend the entry claim.
        verification_summary: Reference-verification results, when available.
        source_coverage: Per-source returned/available counts for this entry.
    """

    supporting_articles: list[EvidenceArticle] = field(default_factory=list)
    contradicting_articles: list[EvidenceArticle] = field(default_factory=list)
    updating_articles: list[EvidenceArticle] = field(default_factory=list)
    verification_summary: dict[str, Any] = field(default_factory=dict)
    source_coverage: dict[str, Any] = field(default_factory=dict)

    @property
    def all_articles(self) -> list[EvidenceArticle]:
        """Return every article across all evidence roles."""
        return [*self.supporting_articles, *self.contradicting_articles, *self.updating_articles]

    @property
    def is_empty(self) -> bool:
        """Return whether the bundle carries no articles at all."""
        return not self.all_articles

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        return {
            "supporting_articles": [a.to_dict() for a in self.supporting_articles],
            "contradicting_articles": [a.to_dict() for a in self.contradicting_articles],
            "updating_articles": [a.to_dict() for a in self.updating_articles],
            "verification_summary": self.verification_summary,
            "source_coverage": self.source_coverage,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceBundle:
        """Rebuild an evidence bundle from its serialized form."""

        def _articles(key: str) -> list[EvidenceArticle]:
            raw = data.get(key) or []
            return [EvidenceArticle.from_dict(item) for item in raw if isinstance(item, dict)]

        return cls(
            supporting_articles=_articles("supporting_articles"),
            contradicting_articles=_articles("contradicting_articles"),
            updating_articles=_articles("updating_articles"),
            verification_summary=_as_dict(data.get("verification_summary")),
            source_coverage=_as_dict(data.get("source_coverage")),
        )


@dataclass
class ChronicleEntry:
    """One interpretable research event or claim inside a chronicle.

    Attributes:
        entry_id: Stable identifier, reused across revisions when the underlying
            evidence is unchanged.
        entry_type: Interpretable kind of event.
        title: Human-readable entry headline.
        time_start: ISO date/year string marking when the event begins.
        time_end: ISO date/year string marking when the event ends, if bounded.
        summary_claim: One-sentence claim that the evidence supports.
        branch_id: Owning branch, if assigned.
        confidence: Confidence in the entry, 0-1.
        status: Lifecycle state within this revision.
        evidence: Supporting/contradicting/updating articles.
        tags: Free-form labels used for filtering and clustering.
        provenance: Where the entry came from (search, pipeline, artifact, ...).
    """

    entry_id: str
    entry_type: ChronicleEntryType
    title: str
    time_start: str
    summary_claim: str
    time_end: str | None = None
    branch_id: str | None = None
    confidence: float = 0.0
    status: ChronicleEntryStatus = ChronicleEntryStatus.ACTIVE
    evidence: EvidenceBundle = field(default_factory=EvidenceBundle)
    tags: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def year(self) -> int | None:
        """Return the entry's starting year when parseable."""
        value = self.time_start.strip()
        parts = value.split("-")
        if (
            len(parts) not in _VALID_DATE_PART_COUNTS
            or len(parts[0]) != _YEAR_DIGITS
            or not all(part.isdigit() for part in parts)
        ):
            return None
        year = int(parts[0])
        if not 1 <= year <= _MAX_CALENDAR_YEAR:
            return None
        try:
            if len(parts) == _MONTH_PRECISION_PARTS:
                date(year, int(parts[1]), 1)
            elif len(parts) == _DAY_PRECISION_PARTS:
                date(year, int(parts[1]), int(parts[2]))
        except ValueError:
            return None
        return year

    @property
    def requires_evidence(self) -> bool:
        """Return whether this entry must carry at least one article."""
        return self.status is not ChronicleEntryStatus.BACKGROUND

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        return {
            "entry_id": self.entry_id,
            "entry_type": self.entry_type.value,
            "title": self.title,
            "time_start": self.time_start,
            "time_end": self.time_end,
            "summary_claim": self.summary_claim,
            "branch_id": self.branch_id,
            "confidence": round(self.confidence, 3),
            "status": self.status.value,
            "evidence": self.evidence.to_dict(),
            "tags": list(self.tags),
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChronicleEntry:
        """Rebuild a chronicle entry from its serialized form."""
        return cls(
            entry_id=str(data.get("entry_id") or ""),
            entry_type=ChronicleEntryType.parse(data.get("entry_type")),
            title=str(data.get("title") or ""),
            time_start=str(data.get("time_start") or ""),
            summary_claim=str(data.get("summary_claim") or ""),
            time_end=data.get("time_end"),
            branch_id=data.get("branch_id"),
            confidence=float(data.get("confidence") or 0.0),
            status=ChronicleEntryStatus.parse(data.get("status")),
            evidence=EvidenceBundle.from_dict(_as_dict(data.get("evidence"))),
            tags=_as_str_list(data.get("tags")),
            provenance=_as_dict(data.get("provenance")),
        )


@dataclass
class ChronicleBranch:
    """A readable research line that groups related chronicle entries.

    Attributes:
        branch_id: Stable branch identifier.
        name: Display label.
        description: What this research line covers.
        parent_branch_id: Parent branch for nested lines.
        entry_ids: Entries assigned to this branch, in chronological order.
        confidence: Confidence in the branch grouping, 0-1.
        tags: Free-form labels.
    """

    branch_id: str
    name: str
    description: str = ""
    parent_branch_id: str | None = None
    entry_ids: list[str] = field(default_factory=list)
    confidence: float = 1.0
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        return {
            "branch_id": self.branch_id,
            "name": self.name,
            "description": self.description,
            "parent_branch_id": self.parent_branch_id,
            "entry_ids": list(self.entry_ids),
            "confidence": round(self.confidence, 3),
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChronicleBranch:
        """Rebuild a chronicle branch from its serialized form."""
        raw_confidence = data.get("confidence")
        return cls(
            branch_id=str(data.get("branch_id") or ""),
            name=str(data.get("name") or ""),
            description=str(data.get("description") or ""),
            parent_branch_id=data.get("parent_branch_id"),
            entry_ids=_as_str_list(data.get("entry_ids")),
            confidence=float(raw_confidence) if raw_confidence is not None else 1.0,
            tags=_as_str_list(data.get("tags")),
        )


@dataclass(frozen=True)
class ChronicleGraphNode:
    """A typed node in the chronicle provenance graph."""

    node_id: str
    node_type: ChronicleNodeType
    label: str
    attributes: tuple[tuple[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        return {
            "id": self.node_id,
            "type": self.node_type.value,
            "label": self.label,
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class ChronicleGraphEdge:
    """A typed edge in the chronicle provenance graph."""

    source: str
    target: str
    edge_type: ChronicleEdgeType
    attributes: tuple[tuple[str, Any], ...] = ()

    @property
    def edge_id(self) -> str:
        """Return the stable identifier used for edge deduplication."""
        return f"{self.source}|{self.edge_type.value}|{self.target}"

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        return {
            "id": self.edge_id,
            "source": self.source,
            "target": self.target,
            "type": self.edge_type.value,
            "attributes": dict(self.attributes),
        }


@dataclass
class ChronicleGraph:
    """Typed, deduplicated provenance graph for one chronicle revision."""

    nodes: dict[str, ChronicleGraphNode] = field(default_factory=dict)
    edges: dict[str, ChronicleGraphEdge] = field(default_factory=dict)

    def add_node(self, node: ChronicleGraphNode) -> ChronicleGraphNode:
        """Add *node*, keeping the first definition when the ID repeats."""
        return self.nodes.setdefault(node.node_id, node)

    def add_edge(self, edge: ChronicleGraphEdge) -> ChronicleGraphEdge:
        """Add *edge*, keeping the first definition when the ID repeats."""
        return self.edges.setdefault(edge.edge_id, edge)

    def validate(self) -> list[str]:
        """Return human-readable violations of the graph invariants.

        Checks that every edge endpoint exists and that each edge type only
        connects the node-type pairs declared in :data:`EDGE_INVARIANTS`.
        """
        violations: list[str] = []
        for edge in self.edges.values():
            source = self.nodes.get(edge.source)
            target = self.nodes.get(edge.target)
            if source is None:
                violations.append(f"Edge {edge.edge_id} has unknown source node {edge.source}")
                continue
            if target is None:
                violations.append(f"Edge {edge.edge_id} has unknown target node {edge.target}")
                continue

            allowed = EDGE_INVARIANTS.get(edge.edge_type)
            if allowed and (source.node_type, target.node_type) not in allowed:
                violations.append(
                    f"Edge {edge.edge_id} connects {source.node_type.value} -> {target.node_type.value}, "
                    f"which is not allowed for '{edge.edge_type.value}'"
                )
        return violations

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        return {
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges.values()],
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChronicleGraph:
        """Rebuild a graph from its serialized form, skipping unknown types."""
        graph = cls()
        for raw in data.get("nodes") or []:
            if not isinstance(raw, dict):
                continue
            try:
                node_type = ChronicleNodeType(str(raw.get("type")))
            except ValueError:
                continue
            graph.add_node(
                ChronicleGraphNode(
                    node_id=str(raw.get("id") or ""),
                    node_type=node_type,
                    label=str(raw.get("label") or ""),
                    attributes=tuple(_as_dict(raw.get("attributes")).items()),
                )
            )
        for raw in data.get("edges") or []:
            if not isinstance(raw, dict):
                continue
            try:
                edge_type = ChronicleEdgeType(str(raw.get("type")))
            except ValueError:
                continue
            graph.add_edge(
                ChronicleGraphEdge(
                    source=str(raw.get("source") or ""),
                    target=str(raw.get("target") or ""),
                    edge_type=edge_type,
                    attributes=tuple(_as_dict(raw.get("attributes")).items()),
                )
            )
        return graph


@dataclass
class ChronicleInputScope:
    """How a chronicle revision was produced.

    Attributes:
        mode: ``topic``, ``pmids``, ``session``, ``artifact``, or ``pipeline``.
        query: Topic or query string, when the chronicle came from a search.
        pmids: Explicit PMIDs the chronicle was built from.
        source_artifact_uris: Upstream artifacts feeding this chronicle.
        pipeline_run_ids: Pipeline runs feeding this chronicle.
        filters: Search filters applied.
        source_counts: Per-source returned/available counts.
    """

    mode: str = "topic"
    query: str | None = None
    pmids: list[str] = field(default_factory=list)
    source_artifact_uris: list[str] = field(default_factory=list)
    pipeline_run_ids: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    source_counts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        return {
            "mode": self.mode,
            "query": self.query,
            "pmids": list(self.pmids),
            "source_artifact_uris": list(self.source_artifact_uris),
            "pipeline_run_ids": list(self.pipeline_run_ids),
            "filters": self.filters,
            "source_counts": self.source_counts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChronicleInputScope:
        """Rebuild an input scope from its serialized form."""
        return cls(
            mode=str(data.get("mode") or "topic"),
            query=data.get("query"),
            pmids=_as_str_list(data.get("pmids")),
            source_artifact_uris=_as_str_list(data.get("source_artifact_uris")),
            pipeline_run_ids=_as_str_list(data.get("pipeline_run_ids")),
            filters=_as_dict(data.get("filters")),
            source_counts=_as_dict(data.get("source_counts")),
        )


@dataclass(frozen=True)
class ChronicleAuditFinding:
    """One audit check outcome.

    Attributes:
        check: Stable check identifier, e.g. ``evidence_coverage``.
        status: ``pass``, ``warn``, or ``fail``.
        message: Actionable, human-readable explanation.
        details: Structured supporting numbers for the message.
    """

    check: str
    status: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        return {
            "check": self.check,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChronicleAuditFinding:
        """Rebuild an audit finding from its serialized form."""
        status = str(data.get("status") or "pass")
        return cls(
            check=str(data.get("check") or "unknown"),
            status=status if status in AUDIT_STATUS_ORDER else "warn",
            message=str(data.get("message") or ""),
            details=_as_dict(data.get("details")),
        )


@dataclass
class ChronicleAudit:
    """Aggregate completeness and integrity report for one revision."""

    findings: list[ChronicleAuditFinding] = field(default_factory=list)

    @property
    def status(self) -> str:
        """Return the worst status across all findings."""
        worst = "pass"
        for finding in self.findings:
            if AUDIT_STATUS_ORDER.index(finding.status) > AUDIT_STATUS_ORDER.index(worst):
                worst = finding.status
        return worst

    @property
    def warnings(self) -> list[str]:
        """Return messages for findings that are not ``pass``."""
        return [f.message for f in self.findings if f.status != "pass"]

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        return {
            "status": self.status,
            "findings": [f.to_dict() for f in self.findings],
            "counts": {status: sum(1 for f in self.findings if f.status == status) for status in AUDIT_STATUS_ORDER},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChronicleAudit:
        """Rebuild an audit from its serialized form."""
        raw = data.get("findings") or []
        return cls(findings=[ChronicleAuditFinding.from_dict(item) for item in raw if isinstance(item, dict)])


@dataclass
class ChronicleSnapshot:
    """One immutable chronicle revision - the chronicle source of truth.

    Attributes:
        chronicle_id: Stable identifier shared by every revision of a topic.
        topic: Human-readable research topic.
        revision: Monotonic revision number starting at 1.
        input_scope: How this revision was produced.
        entries: Interpretable research events, chronologically ordered.
        branches: Research lines grouping the entries.
        graph: Typed provenance graph.
        audit: Completeness/integrity findings for this revision.
        created_at: ISO timestamp of revision 1.
        updated_at: ISO timestamp of this revision.
        metadata: Free-form extras (diagnostics, counts, tool versions).
        schema_version: Serialization contract version.
    """

    chronicle_id: str
    topic: str
    revision: int = 1
    input_scope: ChronicleInputScope = field(default_factory=ChronicleInputScope)
    entries: list[ChronicleEntry] = field(default_factory=list)
    branches: list[ChronicleBranch] = field(default_factory=list)
    graph: ChronicleGraph = field(default_factory=ChronicleGraph)
    audit: ChronicleAudit = field(default_factory=ChronicleAudit)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = CHRONICLE_SCHEMA_VERSION

    @property
    def entry_index(self) -> dict[str, ChronicleEntry]:
        """Return entries keyed by ``entry_id``."""
        return {entry.entry_id: entry for entry in self.entries}

    @property
    def year_range(self) -> tuple[int, int] | None:
        """Return ``(first_year, last_year)`` across entries, if any."""
        years = [entry.year for entry in self.entries if entry.year is not None]
        return (min(years), max(years)) if years else None

    @property
    def evidence_articles(self) -> list[EvidenceArticle]:
        """Return every evidence article across all entries, deduplicated."""
        seen: dict[str, EvidenceArticle] = {}
        for entry in self.entries:
            for article in entry.evidence.all_articles:
                seen.setdefault(article.evidence_id, article)
        return list(seen.values())

    def to_dict(self) -> dict[str, Any]:
        """Convert the snapshot to a JSON-serializable dict."""
        return {
            "schema_version": self.schema_version,
            "chronicle_id": self.chronicle_id,
            "topic": self.topic,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "input_scope": self.input_scope.to_dict(),
            "entries": [entry.to_dict() for entry in self.entries],
            "branches": [branch.to_dict() for branch in self.branches],
            "graph": self.graph.to_dict(),
            "audit": self.audit.to_dict(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChronicleSnapshot:
        """Rebuild a snapshot from its serialized form."""
        raw_schema_version = data.get("schema_version")
        if raw_schema_version is not None and str(raw_schema_version) != CHRONICLE_SCHEMA_VERSION:
            msg = (
                f"Unsupported Chronicle schema version {raw_schema_version!r}; "
                f"this runtime supports {CHRONICLE_SCHEMA_VERSION!r}."
            )
            raise ValueError(msg)
        entries_raw = data.get("entries") or []
        branches_raw = data.get("branches") or []
        return cls(
            chronicle_id=str(data.get("chronicle_id") or ""),
            topic=str(data.get("topic") or ""),
            revision=int(data.get("revision") or 1),
            input_scope=ChronicleInputScope.from_dict(_as_dict(data.get("input_scope"))),
            entries=[ChronicleEntry.from_dict(item) for item in entries_raw if isinstance(item, dict)],
            branches=[ChronicleBranch.from_dict(item) for item in branches_raw if isinstance(item, dict)],
            graph=ChronicleGraph.from_dict(_as_dict(data.get("graph"))),
            audit=ChronicleAudit.from_dict(_as_dict(data.get("audit"))),
            created_at=str(data.get("created_at") or utc_now_iso()),
            updated_at=str(data.get("updated_at") or utc_now_iso()),
            metadata=_as_dict(data.get("metadata")),
            schema_version=str(data.get("schema_version") or CHRONICLE_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class ChronicleMembershipResolution:
    """Occurrence-aware reconciliation of entry and branch ownership fields."""

    branch_index_by_entry: tuple[int | None, ...]
    repair_reasons_by_entry: tuple[tuple[str, ...], ...]
    branch_entry_indices: tuple[tuple[int, ...], ...]
    dangling_memberships: tuple[tuple[int, str], ...]

    @property
    def repaired_entry_indices(self) -> tuple[int, ...]:
        """Return entry occurrences that cannot be assigned without guessing."""
        return tuple(index for index, branch_index in enumerate(self.branch_index_by_entry) if branch_index is None)


def resolve_chronicle_membership(snapshot: ChronicleSnapshot) -> ChronicleMembershipResolution:
    """Reconcile redundant branch ownership without silently choosing a side.

    An entry is assigned only when its ID is unique and the redundant ownership
    fields identify one branch occurrence without conflict.  A duplicated
    branch ID can therefore still be disambiguated when exactly one matching
    branch occurrence lists the entry exactly once.  Every genuinely ambiguous
    occurrence is retained as repaired/unassigned data by projections and
    reported by the audit.
    """
    entry_id_counts: dict[str, int] = {}
    for entry in snapshot.entries:
        entry_id_counts[entry.entry_id] = entry_id_counts.get(entry.entry_id, 0) + 1

    branch_occurrences: dict[str, list[int]] = {}
    memberships: dict[str, list[int]] = {}
    dangling: list[tuple[int, str]] = []
    known_entry_ids = set(entry_id_counts)
    for branch_index, branch in enumerate(snapshot.branches):
        branch_occurrences.setdefault(branch.branch_id, []).append(branch_index)
        for entry_id in branch.entry_ids:
            memberships.setdefault(entry_id, []).append(branch_index)
            if entry_id not in known_entry_ids:
                dangling.append((branch_index, entry_id))

    resolved: list[int | None] = []
    reasons_by_entry: list[tuple[str, ...]] = []
    branch_entries: list[list[int]] = [[] for _branch in snapshot.branches]
    for entry_index, entry in enumerate(snapshot.entries):
        reasons: list[str] = []
        if not entry.entry_id:
            reasons.append("empty_entry_id")
        if entry_id_counts.get(entry.entry_id, 0) != 1:
            reasons.append("duplicate_entry_id")

        branch_candidates = branch_occurrences.get(entry.branch_id or "", [])
        listed_in = memberships.get(entry.entry_id, [])
        if not entry.branch_id:
            reasons.append("missing_entry_branch_id")
        elif not branch_candidates:
            reasons.append("unknown_entry_branch_id")
        if len(branch_candidates) == 1:
            declared_index = branch_candidates[0]
        elif len(branch_candidates) > 1 and len(listed_in) == 1 and listed_in[0] in branch_candidates:
            declared_index = listed_in[0]
        else:
            declared_index = None
            if len(branch_candidates) > 1:
                reasons.append("ambiguous_entry_branch_id")

        declared_occurrences = listed_in.count(declared_index) if declared_index is not None else 0
        if declared_index is not None and declared_occurrences == 0:
            reasons.append("missing_from_declared_branch")
        elif declared_occurrences > 1:
            reasons.append("duplicate_membership_in_declared_branch")
        if any(branch_index != declared_index for branch_index in listed_in):
            reasons.append("conflicting_branch_membership")
        if len(listed_in) > 1 and "duplicate_membership_in_declared_branch" not in reasons:
            reasons.append("multiple_branch_memberships")

        if reasons or declared_index is None:
            resolved.append(None)
        else:
            resolved.append(declared_index)
            branch_entries[declared_index].append(entry_index)
        reasons_by_entry.append(tuple(reasons))

    return ChronicleMembershipResolution(
        branch_index_by_entry=tuple(resolved),
        repair_reasons_by_entry=tuple(reasons_by_entry),
        branch_entry_indices=tuple(tuple(indices) for indices in branch_entries),
        dangling_memberships=tuple(dangling),
    )


__all__ = [
    "AUDIT_STATUS_ORDER",
    "CHRONICLE_SCHEMA_VERSION",
    "EDGE_INVARIANTS",
    "ChronicleAudit",
    "ChronicleAuditFinding",
    "ChronicleBranch",
    "ChronicleEdgeType",
    "ChronicleEntry",
    "ChronicleEntryStatus",
    "ChronicleEntryType",
    "ChronicleGraph",
    "ChronicleGraphEdge",
    "ChronicleGraphNode",
    "ChronicleInputScope",
    "ChronicleMembershipResolution",
    "ChronicleNodeType",
    "ChronicleSnapshot",
    "EvidenceArticle",
    "EvidenceBundle",
    "resolve_chronicle_membership",
    "utc_now_iso",
]
