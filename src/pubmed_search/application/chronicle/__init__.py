"""Research Chronicle application services.

The chronicle is the durable, versioned, evidence-backed record of how a
research topic evolved. Timeline, lineage tree, provenance graph, narrative,
and delta reports are projections of a stored ``ChronicleSnapshot``.

Usage:
    >>> service = ChronicleService(timeline_builder, ChronicleStore(data_dir))
    >>> snapshot = await service.build(topic="remimazolam")
    >>> service.render(snapshot, "timeline")["total_events"]
"""

from __future__ import annotations

from .analytics import analyze_milestones, compare_chronicles
from .assembler import assemble_chronicle, derive_chronicle_id
from .audit import REQUIRED_ARTIFACT_FILES, audit_chronicle
from .differ import diff_chronicles
from .graph import build_chronicle_graph
from .narrator import narrate_chronicle
from .projectors import (
    project_evidence,
    project_graph,
    project_lineage_tree,
    project_timeline,
    render_lineage_mindmap,
    render_timeline_mermaid,
)
from .service import (
    CHRONICLE_ARTIFACT_FILES,
    CHRONICLE_READ_ORDER,
    ChronicleEvidenceProvider,
    ChronicleService,
)
from .store import ChronicleStore

__all__ = [
    "CHRONICLE_ARTIFACT_FILES",
    "CHRONICLE_READ_ORDER",
    "REQUIRED_ARTIFACT_FILES",
    "ChronicleEvidenceProvider",
    "ChronicleService",
    "ChronicleStore",
    "analyze_milestones",
    "assemble_chronicle",
    "audit_chronicle",
    "build_chronicle_graph",
    "compare_chronicles",
    "derive_chronicle_id",
    "diff_chronicles",
    "narrate_chronicle",
    "project_evidence",
    "project_graph",
    "project_lineage_tree",
    "project_timeline",
    "render_lineage_mindmap",
    "render_timeline_mermaid",
]
