"""Find dated indexing patterns for historical review in one Chronicle revision."""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import TYPE_CHECKING, Any

from pubmed_search.domain.value_objects.article_identifiers import (
    try_normalize_doi,
    try_normalize_pmcid,
    try_normalize_pmid,
)

from .lineage import MAX_TOPIC_BRANCHES
from .ordering import ChronicleTime, parse_chronicle_time

if TYPE_CHECKING:
    from pubmed_search.domain.entities.chronicle import ChronicleEntry, ChronicleMembershipResolution, ChronicleSnapshot


@dataclass(frozen=True)
class _Paper:
    entry: ChronicleEntry
    date: ChronicleTime
    evidence_id: str
    identifiers: frozenset[str]
    branch_ids: tuple[str, ...]

    def locator(self) -> dict[str, str]:
        return {"entry_id": self.entry.entry_id, "evidence_id": self.evidence_id, "time_start": self.entry.time_start}


def _signal_ids(entry: ChronicleEntry, owner_id: str, semantic_ids: set[str]) -> tuple[str, ...]:
    """Use the complete saved membership, including secondary signals."""
    matches = entry.provenance.get("lineage_matched_signals")
    if not isinstance(matches, list) or len(matches) > len(semantic_ids):
        return ()
    ids: set[str] = set()
    for match in matches:
        branch_id = match.get("branch_id") if isinstance(match, dict) else None
        if not isinstance(branch_id, str) or branch_id not in semantic_ids:
            return ()
        ids.add(branch_id)
    if (
        owner_id not in ids
        or len(ids) != len(matches)
        or entry.provenance.get("lineage_matched_signal_count", len(ids)) != len(ids)
    ):
        return ()
    return tuple(sorted(ids))


def project_divergence_review(snapshot: ChronicleSnapshot, membership: ChronicleMembershipResolution) -> dict[str, Any]:
    """Return one inspectable, non-causal indexing pattern per eligible topic pair."""
    result: dict[str, Any] = {
        "status": "insufficient_signal_provenance",
        "basis": "shared_indexed_topics_followed_by_separately_indexed_papers_in_scope",
        "interpretation": "This pattern describes indexing in this revision. Historical descent, influence and disagreement require independent source evidence.",
        "witness_selection": "First eligible shared paper and first separately indexed paper on each branch strictly "
        "after it, in chronology display order with evidence ID breaking ties. The first single-signal paper per "
        "branch strictly before the shared paper, when available, shows prior visibility. Each locator identifies a different paper.",
        "entries_with_signal_membership": 0,
        "eligible_dated_papers": 0,
        "candidates": [],
    }
    diagnostics = snapshot.metadata.get("lineage_diagnostics")
    if not isinstance(diagnostics, dict) or diagnostics.get("basis") != "topic_signals":
        return result
    semantic_branches = [branch for branch in snapshot.branches if "lineage_basis:topic_signal" in branch.tags]
    if len(semantic_branches) > MAX_TOPIC_BRANCHES:
        result.update(
            status="topic_branch_limit_exceeded",
            observed_topic_branches=len(semantic_branches),
            maximum_topic_branches=MAX_TOPIC_BRANCHES,
        )
        return result
    branch_id_counts = Counter(b.branch_id for b in snapshot.branches)
    semantic_ids = {branch.branch_id for branch in semantic_branches if branch_id_counts[branch.branch_id] == 1}
    papers = []
    identifier_counts: Counter[str] = Counter()
    for entry, owner in zip(snapshot.entries, membership.branch_index_by_entry, strict=True):
        if owner is None:
            continue
        signals = _signal_ids(entry, snapshot.branches[owner].branch_id, semantic_ids)
        if not signals:
            continue
        result["entries_with_signal_membership"] += 1
        date = parse_chronicle_time(entry.time_start)
        # Signal membership refers to the indexed paper of the event. Additional
        # supporting sources in a legacy entry cannot be assumed to carry its tags.
        if date is None or len(entry.evidence.supporting_articles) != 1:
            continue
        article = entry.evidence.supporting_articles[0]
        identifiers = frozenset(
            f"{kind}:{value}"
            for kind, value in (
                ("pmid", try_normalize_pmid(article.pmid)),
                ("pmcid", try_normalize_pmcid(article.pmcid)),
                ("doi", try_normalize_doi(article.doi)),
            )
            if value
        )
        if not identifiers or (article.year is not None and article.year != date.year):
            continue
        identifier_counts.update(identifiers)
        papers.append(_Paper(entry, date, article.evidence_id, identifiers, signals))
    if not result["entries_with_signal_membership"]:
        return result

    # A paper classified under multiple entries cannot serve as independent witnesses.
    eligible = sorted(
        (paper for paper in papers if all(identifier_counts[value] == 1 for value in paper.identifiers)),
        key=lambda paper: (paper.date.sort_key, paper.evidence_id),
    )
    singles: dict[str, list[_Paper]] = defaultdict(list)
    for paper in eligible:
        if len(paper.branch_ids) == 1:
            singles[paper.branch_ids[0]].append(paper)
    by_pair = {}
    for shared in eligible:
        if len(shared.branch_ids) < 2:
            continue
        later = {}
        for branch_id in shared.branch_ids:
            papers_on_branch = singles.get(branch_id, [])
            index = bisect_right(papers_on_branch, shared.date.latest, key=lambda paper: paper.date.earliest)
            if index < len(papers_on_branch):
                later[branch_id] = papers_on_branch[index]
        for pair in combinations(later, 2):
            if pair not in by_pair:
                earlier = []
                for branch_id in pair:
                    prior = next((p for p in singles[branch_id] if p.date.latest < shared.date.earliest), None)
                    if prior is not None:
                        earlier.append({"branch_id": branch_id, **prior.locator()})
                by_pair[pair] = {
                    "branch_ids": list(pair),
                    "shared_paper": shared.locator(),
                    "later_papers": [{"branch_id": branch_id, **later[branch_id].locator()} for branch_id in pair],
                    "earlier_single_signal_papers": earlier,
                }
    result.update(
        status="evaluated",
        eligible_dated_papers=len(eligible),
        candidates=[by_pair[pair] for pair in sorted(by_pair)],
    )
    return result
