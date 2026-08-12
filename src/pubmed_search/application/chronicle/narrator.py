"""Evidence-backed narrative rendering for chronicle revisions.

Narrative output is deliberately mechanical: every substantive sentence carries
its ``entry_id`` and the identifiers of the articles that back it, so an agent
can verify each claim without re-running the search.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pubmed_search.domain.entities.chronicle import resolve_chronicle_membership

from .analytics import landmark_rank_key
from .ordering import chronology_key

if TYPE_CHECKING:
    from pubmed_search.domain.entities.chronicle import ChronicleEntry, ChronicleSnapshot

#: Number of entries included per branch in ``brief`` mode.
_BRIEF_ENTRIES_PER_BRANCH = 3


def _select_brief_entries(entries: list[ChronicleEntry], limit: int) -> list[ChronicleEntry]:
    """Select scientifically important entries without using detection confidence."""
    selected = sorted(entries, key=landmark_rank_key)[:limit]
    selected.sort(key=chronology_key)
    return selected


def narrative_citation(entry: ChronicleEntry) -> str:
    """Return a bracketed citation list for *entry*."""
    ids = [article.evidence_id for article in entry.evidence.all_articles]
    return f"[{entry.entry_id}; {', '.join(ids)}]" if ids else f"[{entry.entry_id}; no evidence]"


def narrate_chronicle(snapshot: ChronicleSnapshot, *, mode: str = "brief") -> str:
    """Render *snapshot* as evidence-backed Markdown.

    Args:
        snapshot: The revision to narrate.
        mode: ``brief`` selects entries by explicit landmark importance, with
            citation counts as fallback; ``full`` includes every entry.

    Returns:
        Markdown text in which every claim line ends with its entry ID and
        evidence identifiers.
    """
    year_range = snapshot.year_range
    span = f"{year_range[0]}\u2013{year_range[1]}" if year_range else "unknown span"
    lines = [
        f"# Research Chronicle: {snapshot.topic}",
        "",
        (
            f"Revision {snapshot.revision} \u00b7 {len(snapshot.entries)} entries \u00b7 "
            f"{len(snapshot.evidence_articles)} evidence articles \u00b7 {span} \u00b7 "
            f"audit: {snapshot.audit.status}"
        ),
        "",
    ]

    if not snapshot.entries:
        lines.append("No chronicle entries were assembled, so no claims can be made.")
        return "\n".join(lines)

    membership = resolve_chronicle_membership(snapshot)
    global_rank = {
        entry_index: order
        for order, entry_index in enumerate(
            sorted(range(len(snapshot.entries)), key=lambda index: chronology_key(snapshot.entries[index]))
        )
    }
    limit = None if mode == "full" else _BRIEF_ENTRIES_PER_BRANCH

    for branch_index, branch in enumerate(snapshot.branches):
        entry_indices = list(membership.branch_entry_indices[branch_index])
        entry_indices.sort(key=lambda index: (chronology_key(snapshot.entries[index]), global_rank[index]))
        entries = [snapshot.entries[index] for index in entry_indices]
        if not entries:
            continue
        selected = entries if limit is None else _select_brief_entries(entries, limit)
        if limit is None:
            selected.sort(key=chronology_key)

        lines.append(f"## {branch.name}")
        lines.append("")
        for entry in selected:
            lines.append(f"- {entry.summary_claim} {narrative_citation(entry)}")
        if limit is not None and len(entries) > len(selected):
            lines.append(f"- _{len(entries) - len(selected)} further entries omitted in brief mode._")
        lines.append("")

    unassigned_indices = sorted(membership.repaired_entry_indices, key=lambda index: global_rank[index])
    unassigned = [snapshot.entries[index] for index in unassigned_indices]
    if unassigned:
        lines.append("## Unassigned Entries")
        lines.append("")
        shown = unassigned if limit is None else _select_brief_entries(unassigned, limit)
        for entry in shown:
            lines.append(f"- {entry.summary_claim} {narrative_citation(entry)}")
        if limit is not None and len(unassigned) > len(shown):
            lines.append(f"- _{len(unassigned) - len(shown)} further repaired entries omitted in brief mode._")
        lines.append("")

    if snapshot.audit.warnings:
        lines.append("## Completeness Caveats")
        lines.append("")
        lines.extend(f"- {warning}" for warning in snapshot.audit.warnings)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


__all__ = ["narrate_chronicle", "narrative_citation"]
