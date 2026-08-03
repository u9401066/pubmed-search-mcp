"""Evidence-backed narrative rendering for chronicle revisions.

Narrative output is deliberately mechanical: every substantive sentence carries
its ``entry_id`` and the identifiers of the articles that back it, so an agent
can verify each claim without re-running the search.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pubmed_search.domain.entities.chronicle import ChronicleEntry, ChronicleSnapshot

#: Number of entries included per branch in ``brief`` mode.
_BRIEF_ENTRIES_PER_BRANCH = 3


def _citations(entry: ChronicleEntry) -> str:
    """Return a bracketed citation list for *entry*."""
    ids = [article.evidence_id for article in entry.evidence.all_articles]
    return f"[{entry.entry_id}; {', '.join(ids)}]" if ids else f"[{entry.entry_id}; no evidence]"


def narrate_chronicle(snapshot: ChronicleSnapshot, *, mode: str = "brief") -> str:
    """Render *snapshot* as evidence-backed Markdown.

    Args:
        snapshot: The revision to narrate.
        mode: ``brief`` limits each branch to its most confident entries;
            ``full`` includes every entry.

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

    entry_index = snapshot.entry_index
    limit = None if mode == "full" else _BRIEF_ENTRIES_PER_BRANCH

    for branch in snapshot.branches:
        entries = [entry_index[entry_id] for entry_id in branch.entry_ids if entry_id in entry_index]
        if not entries:
            continue
        entries.sort(key=lambda entry: (entry.year or 0, entry.entry_id))
        selected = entries if limit is None else sorted(entries, key=lambda entry: -entry.confidence)[:limit]
        selected.sort(key=lambda entry: (entry.year or 0, entry.entry_id))

        lines.append(f"## {branch.name}")
        lines.append("")
        for entry in selected:
            lines.append(f"- {entry.summary_claim} {_citations(entry)}")
        if limit is not None and len(entries) > len(selected):
            lines.append(f"- _{len(entries) - len(selected)} further entries omitted in brief mode._")
        lines.append("")

    unassigned = [entry for entry in snapshot.entries if not entry.branch_id]
    if unassigned:
        lines.append("## Unassigned Entries")
        lines.append("")
        shown = unassigned if limit is None else unassigned[:limit]
        for entry in shown:
            lines.append(f"- {entry.summary_claim} {_citations(entry)}")
        lines.append("")

    if snapshot.audit.warnings:
        lines.append("## Completeness Caveats")
        lines.append("")
        lines.extend(f"- {warning}" for warning in snapshot.audit.warnings)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


__all__ = ["narrate_chronicle"]
