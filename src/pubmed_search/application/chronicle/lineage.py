"""Derive evidence-explainable topic lineages for research chronicles.

The older research-tree builder groups events by research stage (discovery,
clinical development, safety, and so on).  That view is useful, but it is not a
semantic account of how a field split into sub-topics.  Chronicle lineage uses
article MeSH descriptors and author keywords when they are sufficiently
distinctive.  If those signals cannot support at least two branches, the
detector falls back to the deterministic stage tree and records that limitation
in diagnostics instead of presenting the result as semantic clustering.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pubmed_search.application.timeline import build_research_tree
from pubmed_search.domain.entities.research_tree import ResearchBranch, ResearchTree

if TYPE_CHECKING:
    from pubmed_search.domain.entities.timeline import ResearchTimeline, TimelineEvent

_MAX_TOPIC_BRANCHES = 6
_MIN_TOPIC_COVERAGE = 0.6
_MIN_SIGNAL_PAPERS = 2
_MAX_TERMS_PER_EVENT = 64
_MAX_UNIQUE_TOPIC_SIGNALS = 4096
_MAX_RAW_SIGNAL_CHARS = 512
_SIGNAL_SOURCES = ("mesh_terms", "keywords")

# MeSH qualifiers are a controlled vocabulary. A slash is stripped only when
# its suffix is one of these qualifiers; biomedical names and author keywords
# such as ``PD-1/PD-L1`` must remain intact.
_MESH_QUALIFIERS = {
    "abnormalities",
    "administration & dosage",
    "adverse effects",
    "agonists",
    "analysis",
    "anatomy & histology",
    "antagonists & inhibitors",
    "biosynthesis",
    "blood",
    "cerebrospinal fluid",
    "chemical synthesis",
    "chemistry",
    "classification",
    "complications",
    "congenital",
    "contraindications",
    "cytology",
    "deficiency",
    "diagnosis",
    "diagnostic imaging",
    "diet therapy",
    "drug effects",
    "drug therapy",
    "economics",
    "education",
    "embryology",
    "enzymology",
    "epidemiology",
    "ethics",
    "ethnology",
    "etiology",
    "genetics",
    "growth & development",
    "history",
    "immunology",
    "injuries",
    "innervation",
    "instrumentation",
    "isolation & purification",
    "legislation & jurisprudence",
    "metabolism",
    "methods",
    "microbiology",
    "mortality",
    "nursing",
    "organization & administration",
    "parasitology",
    "pathology",
    "pharmacokinetics",
    "pharmacology",
    "physiology",
    "physiopathology",
    "poisoning",
    "prevention & control",
    "psychology",
    "radiation effects",
    "radiotherapy",
    "rehabilitation",
    "secondary",
    "secretion",
    "standards",
    "statistics & numerical data",
    "surgery",
    "therapeutic use",
    "therapy",
    "toxicity",
    "transmission",
    "transplantation",
    "trends",
    "ultrastructure",
    "urine",
    "veterinary",
    "virology",
}

# These descriptors describe study populations or publication mechanics more
# often than research directions.  Keeping them would create misleading
# branches such as "Humans" and "Adult" in almost every biomedical chronicle.
_GENERIC_BIOMEDICAL_TERMS = {
    "adult",
    "aged",
    "animals",
    "case reports",
    "child",
    "clinical trial",
    "clinical trials as topic",
    "comparative study",
    "controlled clinical trial",
    "female",
    "follow-up studies",
    "humans",
    "male",
    "middle aged",
    "multicenter study",
    "prospective studies",
    "randomized controlled trial",
    "retrospective studies",
    "review",
    "risk factors",
    "systematic review",
    "treatment outcome",
    "young adult",
}


@dataclass(frozen=True)
class _TopicSignal:
    """One candidate semantic branch and the events that expose it."""

    key: str
    label: str
    source: str
    event_indexes: frozenset[int]
    score: float


def build_chronicle_lineage(timeline: ResearchTimeline) -> ResearchTree:
    """Build a topic-signal lineage tree, with an explicit stage fallback.

    MeSH descriptors are preferred over author keywords because they are
    controlled vocabulary.  A semantic result is accepted only when at least
    two distinct branches can be formed and the selected signals cover at least
    60% of dated milestone events.
    """
    if not timeline.events:
        return ResearchTree(
            topic=timeline.topic,
            metadata={
                **timeline.metadata,
                "lineage_diagnostics": {
                    "basis": "none",
                    "reason": "No timeline events were available for lineage detection.",
                    "semantic_coverage_ratio": 0.0,
                    "selected_signals": [],
                    "signal_extraction": _empty_signal_extraction(),
                    **_empty_membership_diagnostics(assignment_semantics="none"),
                },
                "branch_metadata": {},
            },
        )

    candidates, extraction = _topic_signal_candidates(timeline)
    selected = _select_distinct_signals(candidates)
    selected, assignments, pruned = _supported_assignments(timeline.events, selected)
    extraction["signals_pruned_after_assignment"] = pruned
    assigned_branches = {signal.key for signal in assignments.values() if signal is not None}
    covered = sum(signal is not None for signal in assignments.values())
    coverage = covered / len(timeline.events)

    if len(assigned_branches) < 2 or coverage < _MIN_TOPIC_COVERAGE:
        reason = (
            "Fewer than two distinctive topic signals were supported."
            if len(assigned_branches) < 2
            else f"Topic signals covered only {coverage:.0%} of timeline events."
        )
        return _stage_fallback(
            timeline,
            reason=reason,
            semantic_coverage=coverage,
            signal_extraction=extraction,
        )

    return _topic_tree(timeline, selected, assignments, coverage, signal_extraction=extraction)


def _topic_signal_candidates(timeline: ResearchTimeline) -> tuple[list[_TopicSignal], dict[str, Any]]:
    """Extract and rank distinctive MeSH/keyword signals across events."""
    event_indexes: dict[str, set[int]] = defaultdict(set)
    labels: dict[str, Counter[str]] = defaultdict(Counter)
    sources: dict[str, Counter[str]] = defaultdict(Counter)
    topic_key = _normalize_signal(timeline.topic)
    extraction = _empty_signal_extraction()

    for index, event in enumerate(timeline.events):
        metadata = event.metadata if isinstance(event.metadata, dict) else {}
        seen_for_event: set[str] = set()
        terms_examined = 0
        for source in _SIGNAL_SOURCES:
            raw_values = metadata.get(source) or []
            if isinstance(raw_values, str):
                raw_values = [raw_values]
            if not isinstance(raw_values, (list, tuple, set)):
                continue
            for raw_index, raw in enumerate(raw_values):
                if terms_examined >= _MAX_TERMS_PER_EVENT:
                    extraction["terms_omitted_per_event_limit"] += len(raw_values) - raw_index
                    break
                terms_examined += 1
                extraction["terms_examined"] += 1
                if not isinstance(raw, str) or not raw.strip():
                    extraction["invalid_terms_omitted"] += 1
                    continue
                bounded_raw = raw
                if len(bounded_raw) > _MAX_RAW_SIGNAL_CHARS:
                    extraction["oversized_terms_truncated"] += 1
                    bounded_raw = bounded_raw[:_MAX_RAW_SIGNAL_CHARS]
                label = _clean_label(bounded_raw, source=source)
                key = _normalize_signal(label)
                if not _usable_signal(key, topic_key=topic_key) or key in seen_for_event:
                    continue
                if key not in event_indexes and len(event_indexes) >= _MAX_UNIQUE_TOPIC_SIGNALS:
                    extraction["unique_signals_omitted_limit"] += 1
                    continue
                seen_for_event.add(key)
                event_indexes[key].add(index)
                labels[key][label] += 1
                sources[key][source] += 1

    event_count = len(timeline.events)
    candidates: list[_TopicSignal] = []
    for key, indexes in event_indexes.items():
        frequency = len(indexes)
        if frequency < _MIN_SIGNAL_PAPERS or frequency == event_count:
            continue
        source = "mesh_terms" if sources[key]["mesh_terms"] else "keywords"
        source_bonus = 1.25 if source == "mesh_terms" else 1.0
        # Reward signals shared by several papers while penalizing terms so
        # broad that they do not distinguish one lineage from another.
        inverse_frequency = math.log((event_count + 1) / (frequency + 0.5)) + 0.5
        score = frequency * inverse_frequency * source_bonus
        label = sorted(labels[key].items(), key=lambda item: (-item[1], item[0].casefold()))[0][0]
        candidates.append(
            _TopicSignal(
                key=key,
                label=label,
                source=source,
                event_indexes=frozenset(indexes),
                score=score,
            )
        )

    extraction["unique_signals_retained"] = len(event_indexes)
    extraction["candidate_signals"] = len(candidates)
    return (
        sorted(candidates, key=lambda signal: (-signal.score, signal.label.casefold(), signal.key)),
        extraction,
    )


def _select_distinct_signals(candidates: list[_TopicSignal]) -> list[_TopicSignal]:
    """Choose signals with non-duplicate event coverage."""
    selected: list[_TopicSignal] = []
    for candidate in candidates:
        if any(_jaccard(candidate.event_indexes, prior.event_indexes) >= 0.9 for prior in selected):
            continue
        selected.append(candidate)
        if len(selected) >= _MAX_TOPIC_BRANCHES:
            break
    return selected


def _assign_events(
    events: list[TimelineEvent],
    selected: list[_TopicSignal],
) -> dict[int, _TopicSignal | None]:
    """Assign each event to its highest-ranked selected topic signal."""
    assignments: dict[int, _TopicSignal | None] = {}
    for index, _event in enumerate(events):
        assignments[index] = next((signal for signal in selected if index in signal.event_indexes), None)
    return assignments


def _supported_assignments(
    events: list[TimelineEvent],
    selected: list[_TopicSignal],
) -> tuple[list[_TopicSignal], dict[int, _TopicSignal | None], int]:
    """Remove branches that lack two assigned papers, then reassign safely.

    Candidate support is calculated before mutually overlapping signals are
    resolved. Rechecking after primary assignment prevents a highly overlapping
    signal from appearing as a high-confidence one-paper branch.
    """
    retained = list(selected)
    pruned = 0
    while retained:
        assignments = _assign_events(events, retained)
        assigned_counts = Counter(signal.key for signal in assignments.values() if signal is not None)
        supported = [signal for signal in retained if assigned_counts[signal.key] >= _MIN_SIGNAL_PAPERS]
        if len(supported) == len(retained):
            return retained, assignments, pruned
        pruned += len(retained) - len(supported)
        retained = supported
    return [], {index: None for index, _event in enumerate(events)}, pruned


def _topic_tree(
    timeline: ResearchTimeline,
    selected: list[_TopicSignal],
    assignments: dict[int, _TopicSignal | None],
    coverage: float,
    *,
    signal_extraction: dict[str, Any],
) -> ResearchTree:
    """Materialize selected topic signals as chronologically ordered branches."""
    events_by_signal: dict[str, list[TimelineEvent]] = defaultdict(list)
    unassigned: list[TimelineEvent] = []
    signal_by_key = {signal.key: signal for signal in selected}
    for index, event in enumerate(timeline.events):
        signal = assignments[index]
        if signal is None:
            unassigned.append(event)
        else:
            events_by_signal[signal.key].append(event)

    branch_rows: list[tuple[tuple[int, int, str], ResearchBranch, dict[str, Any]]] = []
    for key, events in events_by_signal.items():
        if not events:
            continue
        signal = signal_by_key[key]
        branch_id = _branch_id(signal)
        confidence = _signal_confidence(
            signal,
            assigned_count=len(events),
            event_count=len(timeline.events),
        )
        metadata = {
            "basis": "topic_signal",
            "signal": signal.label,
            "signal_source": signal.source,
            "confidence": confidence,
            "description": (
                f"Topic line grouped by the shared "
                f"{'MeSH descriptor' if signal.source == 'mesh_terms' else 'author keyword'} "
                f"{signal.label!r}."
            ),
        }
        branch_rows.append(
            (
                min(event.sort_key for event in events),
                ResearchBranch(branch_id=branch_id, label=signal.label, events=events),
                metadata,
            )
        )

    if unassigned:
        branch_rows.append(
            (
                min(event.sort_key for event in unassigned),
                ResearchBranch(branch_id="topic-cross-cutting", label="Cross-cutting / Other", events=unassigned),
                {
                    "basis": "topic_signal_unassigned",
                    "signal": None,
                    "signal_source": None,
                    "confidence": 0.35,
                    "description": "Events without a sufficiently distinctive shared MeSH term or keyword.",
                },
            )
        )

    branch_rows.sort(key=lambda row: (row[0], row[1].label.casefold()))
    branches: list[ResearchBranch] = []
    branch_metadata: dict[str, dict[str, Any]] = {}
    for order, (_first_event, branch, metadata) in enumerate(branch_rows, start=1):
        branch.order = order
        branches.append(branch)
        branch_metadata[branch.branch_id] = metadata

    membership_diagnostics = _semantic_membership_diagnostics(timeline.events, selected, assignments)

    return ResearchTree(
        topic=timeline.topic,
        branches=branches,
        total_articles=timeline.metadata.get("total_searched", len(timeline.events)),
        metadata={
            **timeline.metadata,
            "tree_branches": len(branches),
            "lineage_diagnostics": {
                "basis": "topic_signals",
                "reason": "Distinctive MeSH descriptors and author keywords supported semantic branching.",
                "semantic_coverage_ratio": round(coverage, 3),
                "selected_signals": [
                    {
                        "key": signal.key,
                        "label": signal.label,
                        "source": signal.source,
                        "branch_id": _branch_id(signal),
                        # Retain the historical name as the count of primary
                        # assignments while making matched support explicit.
                        "event_count": len(events_by_signal.get(signal.key, [])),
                        "primary_event_count": len(events_by_signal.get(signal.key, [])),
                        "matched_event_count": len(signal.event_indexes),
                        "score": round(signal.score, 3),
                    }
                    for signal in selected
                    if events_by_signal.get(signal.key)
                ],
                "signal_extraction": signal_extraction,
                **membership_diagnostics,
            },
            "branch_metadata": branch_metadata,
        },
    )


def _stage_fallback(
    timeline: ResearchTimeline,
    *,
    reason: str,
    semantic_coverage: float,
    signal_extraction: dict[str, Any],
) -> ResearchTree:
    """Return the deterministic stage tree with explicit caveat metadata."""
    tree = build_research_tree(timeline)
    branch_metadata: dict[str, dict[str, Any]] = {}

    def _walk(branch: ResearchBranch) -> None:
        branch_metadata[branch.branch_id] = {
            "basis": "research_stage_fallback",
            "signal": None,
            "signal_source": "milestone_type",
            "confidence": 0.65,
            "description": (f"Research-stage fallback line ({branch.label}); this is not a semantic topic cluster."),
        }
        for child in branch.sub_branches:
            _walk(child)

    for branch in tree.branches:
        _walk(branch)

    tree.metadata = {
        **tree.metadata,
        "lineage_diagnostics": {
            "basis": "research_stage_fallback",
            "reason": reason,
            "semantic_coverage_ratio": round(semantic_coverage, 3),
            "selected_signals": [],
            "signal_extraction": signal_extraction,
            **_empty_membership_diagnostics(assignment_semantics="research_stage_fallback"),
        },
        "branch_metadata": branch_metadata,
    }
    return tree


def _semantic_membership_diagnostics(
    events: list[TimelineEvent],
    selected: list[_TopicSignal],
    assignments: dict[int, _TopicSignal | None],
) -> dict[str, Any]:
    """Describe primary assignments without discarding multi-signal matches.

    A tree requires one owning branch per paper, but biomedical papers can span
    several selected topics.  These rows retain that many-to-many evidence as
    provenance instead of implying that the rendered branches are disjoint.
    """
    event_memberships: list[dict[str, Any]] = []
    cross_signal_links: list[dict[str, Any]] = []
    assigned_event_count = 0
    max_signals_per_event = 0

    for index, event in enumerate(events):
        primary = assignments.get(index)
        matched = [signal for signal in selected if index in signal.event_indexes]
        matched_payloads = [_signal_payload(signal) for signal in matched]
        primary_payload = _signal_payload(primary) if primary is not None else None
        secondary_branch_ids = [
            payload["branch_id"]
            for payload in matched_payloads
            if primary_payload is None or payload["branch_id"] != primary_payload["branch_id"]
        ]
        if primary is not None:
            assigned_event_count += 1
        max_signals_per_event = max(max_signals_per_event, len(matched_payloads))

        membership = {
            "event_index": index,
            "pmid": event.pmid or None,
            "primary_signal": primary_payload,
            "matched_signals": matched_payloads,
            "matched_signal_count": len(matched_payloads),
            "secondary_branch_ids": secondary_branch_ids,
        }
        event_memberships.append(membership)
        if primary_payload is not None and secondary_branch_ids:
            cross_signal_links.append(
                {
                    "event_index": index,
                    "pmid": event.pmid or None,
                    "primary_branch_id": primary_payload["branch_id"],
                    "secondary_branch_ids": secondary_branch_ids,
                    "matched_signals": matched_payloads,
                }
            )

    overlap_event_count = len(cross_signal_links)
    return {
        "assignment_semantics": "single_primary_branch_with_cross_signal_links",
        "assigned_event_count": assigned_event_count,
        "overlap_event_count": overlap_event_count,
        "overlap_ratio": overlap_event_count / len(events) if events else 0.0,
        "overlap_ratio_among_assigned": overlap_event_count / assigned_event_count if assigned_event_count else 0.0,
        "max_signals_per_event": max_signals_per_event,
        "event_signal_memberships": event_memberships,
        "cross_signal_links": cross_signal_links,
    }


def _signal_payload(signal: _TopicSignal) -> dict[str, str]:
    """Return the durable identity of one selected semantic signal."""
    return {
        "key": signal.key,
        "label": signal.label,
        "source": signal.source,
        "branch_id": _branch_id(signal),
    }


def _empty_membership_diagnostics(*, assignment_semantics: str) -> dict[str, Any]:
    """Return a stable no-overlap diagnostic shape for non-semantic trees."""
    return {
        "assignment_semantics": assignment_semantics,
        "assigned_event_count": 0,
        "overlap_event_count": 0,
        "overlap_ratio": 0.0,
        "overlap_ratio_among_assigned": 0.0,
        "max_signals_per_event": 0,
        "event_signal_memberships": [],
        "cross_signal_links": [],
    }


def _signal_confidence(signal: _TopicSignal, *, assigned_count: int, event_count: int) -> float:
    """Return a conservative confidence for one semantic grouping."""
    source_base = 0.5 if signal.source == "mesh_terms" else 0.4
    support_bonus = 0.15 * min(1.0, max(0, assigned_count - 1) / 3)
    coverage_bonus = 0.15 * min(1.0, assigned_count / max(event_count / 2, 1))
    return round(min(0.8, source_base + support_bonus + coverage_bonus), 3)


def _branch_id(signal: _TopicSignal) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", signal.key).strip("-")[:40] or "topic"
    digest = hashlib.sha256(signal.key.encode()).hexdigest()[:6]
    return f"topic-{slug}-{digest}"


def _empty_signal_extraction() -> dict[str, Any]:
    """Return bounded signal-extraction diagnostics."""
    return {
        "max_terms_per_event": _MAX_TERMS_PER_EVENT,
        "max_unique_topic_signals": _MAX_UNIQUE_TOPIC_SIGNALS,
        "max_raw_signal_chars": _MAX_RAW_SIGNAL_CHARS,
        "minimum_papers_per_signal": _MIN_SIGNAL_PAPERS,
        "terms_examined": 0,
        "terms_omitted_per_event_limit": 0,
        "invalid_terms_omitted": 0,
        "oversized_terms_truncated": 0,
        "unique_signals_omitted_limit": 0,
        "unique_signals_retained": 0,
        "candidate_signals": 0,
        "signals_pruned_after_assignment": 0,
    }


def _clean_label(value: str, *, source: str) -> str:
    """Normalize a signal and strip only controlled MeSH qualifiers."""
    label = unicodedata.normalize("NFKC", value).strip()
    label = re.sub(r"\s+", " ", label)
    if source == "mesh_terms":
        label = _strip_mesh_qualifiers(label)
    return label[:80]


def _strip_mesh_qualifiers(label: str) -> str:
    """Strip slash suffixes only when they are controlled MeSH qualifiers."""
    descriptor = label
    while "/" in descriptor:
        head, suffix = descriptor.rsplit("/", 1)
        normalized_suffix = re.sub(r"\s+", " ", suffix.strip()).casefold()
        if normalized_suffix not in _MESH_QUALIFIERS:
            break
        descriptor = head.strip()
    return descriptor


def _normalize_signal(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[^\w\s-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _usable_signal(key: str, *, topic_key: str) -> bool:
    if len(key) < 3 or key in _GENERIC_BIOMEDICAL_TERMS:
        return False
    if key == topic_key:
        return False
    tokens = key.split()
    return not (tokens and all(token in {"study", "research", "analysis", "disease", "drug"} for token in tokens))


def _jaccard(left: frozenset[int], right: frozenset[int]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


__all__ = ["build_chronicle_lineage"]
