"""Screening decisions and PRISMA 2020 flow counts for a saved pipeline.

A saved pipeline is the review project. Runs whose complete record set was
retrieved (``retrieval: exhaustive``) register their PMIDs automatically; a
PMID first identified by a later update run therefore lands in the
title/abstract queue without any manual bookkeeping. Reviewers record
decisions per PMID and stage; the latest decision per (PMID, stage) counts,
earlier ones remain as an audit log, and disagreements between reviewer
labels are reported as conflicts rather than silently resolved.

Retries: a decision without ``decision_id`` is a replay only when it repeats
the *latest* decision of the same reviewer for that PMID and stage (same
decision, reason and note). Anything else -- including a return to an earlier
decision (include, exclude, include) -- is appended and becomes effective.
A client-supplied ``decision_id`` is idempotent on its own: resending it is a
replay even after later decisions, and reusing it for different content fails.

PRISMA 2020 mapping (identification via databases):

* records identified = sum of records identified by every registered run's
  searches (``retrieval.identified_count``: the search/merge result before
  pipeline ``filter`` steps; a run without it counts its persisted records);
* records marked ineligible by automation tools = identified records that the
  run's pipeline filters removed before screening;
* duplicate records removed = identified − automation removals − unique PMIDs;
* records screened = unique PMIDs (title/abstract stage);
* records excluded = latest title/abstract decision ``exclude``;
* reports sought for retrieval = title/abstract ``include`` or ``maybe``;
* reports not retrieved = full-text ``exclude`` with reason ``not retrieved``;
* reports assessed for eligibility = other full-text include/exclude decisions;
* reports excluded (with reasons) = full-text ``exclude`` grouped by reason;
* studies included = full-text ``include`` (counted per record/report).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Protocol

from pubmed_search.shared.credential_sanitizer import contains_credential_material
from pubmed_search.shared.markdown import escape_markdown_text

if TYPE_CHECKING:
    from pubmed_search.domain.entities.pipeline import PipelineRun

STAGES = ("title_abstract", "full_text")
DECISIONS = ("include", "exclude", "maybe")
MAX_DECISIONS_PER_REQUEST = 500
DEFAULT_REVIEWER = "reviewer_1"
NOT_RETRIEVED_REASONS = frozenset({"not retrieved", "not_retrieved", "full text not retrieved", "report not retrieved"})
_REVIEWER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,63}$")
_DECISION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_PMID_RE = re.compile(r"^[1-9][0-9]{0,9}$")


class ScreeningStore(Protocol):
    def register_run(
        self,
        run_id: str,
        *,
        database: str,
        pmids: list[str],
        run_started: str | None,
        exhaustive: bool,
        identified_count: int | None = None,
    ) -> dict[str, Any]: ...

    def record_decisions(self, decisions: list[dict[str, Any]]) -> dict[str, Any]: ...

    def decision_log(self, *, pmid: str | None, offset: int, limit: int) -> dict[str, Any]: ...

    def queue(self, *, stage: str, run_id: str | None, offset: int, limit: int) -> dict[str, Any]: ...

    def flow_counts(self) -> dict[str, Any]: ...

    def decision_summary(self) -> dict[str, int]: ...


def run_is_complete_identification(run: PipelineRun) -> bool:
    """Whether a run identified a complete record set.

    ``retrieval.exhaustive`` is true only when every search feeding the final
    record set was an exhaustive PubMed step that collected all of its PMIDs;
    a ``mixed`` run (any bounded source upstream) is never complete.
    """
    return (
        run.record_basis == "final_step_full"
        and run.retrieval.get("exhaustive") is True
        and run.status in {"success", "partial"}
        and bool(run.pmids)
    )


def _identified_count(run: PipelineRun) -> int | None:
    value = run.retrieval.get("identified_count")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _run_database(run: PipelineRun) -> str:
    databases = list(dict.fromkeys(str(search.get("database")) for search in run.searches if search.get("database")))
    return " + ".join(databases) or "PubMed"


def _text(value: Any, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\0" in value:
        raise ValueError(f"{field} must contain 1 to {maximum} characters")
    if contains_credential_material(value):
        raise ValueError(f"{field} contains credential material")
    return " ".join(value.split())


def normalize_decision(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate one decision; ``decision_id`` stays ``None`` unless the client supplied a retry key.

    Content-derived keys are deliberately not used: a reviewer returning to an
    earlier decision would otherwise collide with that earlier key and be
    discarded as a replay. The store assigns a fresh key when none is given.
    """
    pmid = str(raw.get("pmid") or "").strip()
    if not _PMID_RE.fullmatch(pmid):
        raise ValueError("pmid must be a canonical positive PubMed ID")
    stage = raw.get("stage")
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {', '.join(STAGES)}")
    decision = raw.get("decision")
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(DECISIONS)}")
    reviewer = raw.get("reviewer") or DEFAULT_REVIEWER
    if not isinstance(reviewer, str) or not _REVIEWER_RE.fullmatch(reviewer):
        raise ValueError("reviewer must be a 1-64 character label (letters, digits, _ . @ -)")
    reason = _text(raw.get("reason"), "reason", 500)
    note = _text(raw.get("note"), "note", 2000)
    if stage == "full_text" and decision == "exclude" and reason is None:
        raise ValueError(f"PMID {pmid}: full-text exclusions require a reason (PRISMA 2020)")
    normalized: dict[str, Any] = {
        "pmid": pmid,
        "stage": stage,
        "decision": decision,
        "reason": reason,
        "reviewer": reviewer,
        "note": note,
    }
    decision_id = raw.get("decision_id")
    if decision_id is not None and (not isinstance(decision_id, str) or not _DECISION_ID_RE.fullmatch(decision_id)):
        raise ValueError("decision_id must be a stable identifier of 1 to 96 letters, digits, _ . or -")
    normalized["decision_id"] = decision_id
    return normalized


def _page(value: int, field: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{field} must be an integer between {minimum} and {maximum}")
    return value


class ScreeningService:
    """Validate screening commands and shape PRISMA 2020 flow counts."""

    def __init__(self, store: ScreeningStore) -> None:
        self._store = store

    def decision_summary(self) -> dict[str, int]:
        """Return how many decisions (and decided PMIDs) the log holds."""
        return self._store.decision_summary()

    def register_run(self, run: PipelineRun) -> dict[str, Any]:
        """Add a run's record set to identification (idempotent per run ID)."""
        if not run.pmids:
            raise ValueError("This run has no identified records to register")
        result = self._store.register_run(
            run.run_id,
            database=_run_database(run),
            pmids=list(dict.fromkeys(run.pmids)),
            run_started=run.started.isoformat() if run.started else None,
            exhaustive=run_is_complete_identification(run),
            identified_count=_identified_count(run),
        )
        result["exhaustive"] = bool(result.get("exhaustive"))
        return result

    def register_if_complete(self, run: PipelineRun) -> dict[str, Any] | None:
        """Auto-register only complete (exhaustive) identification runs."""
        return self.register_run(run) if run_is_complete_identification(run) else None

    def record(self, decisions: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(decisions, list) or not 1 <= len(decisions) <= MAX_DECISIONS_PER_REQUEST:
            raise ValueError(f"decisions must contain 1 to {MAX_DECISIONS_PER_REQUEST} items")
        normalized = [normalize_decision(item) for item in decisions]
        return self._store.record_decisions(normalized)

    def queue(self, *, stage: str, run_id: str | None = None, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        if stage not in STAGES:
            raise ValueError(f"stage must be one of {', '.join(STAGES)}")
        return self._store.queue(
            stage=stage,
            run_id=run_id,
            offset=_page(offset, "offset", 0, 1_000_000),
            limit=_page(limit, "limit", 1, 200),
        )

    def log(self, *, pmid: str | None = None, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        if pmid is not None and not _PMID_RE.fullmatch(pmid):
            raise ValueError("pmid must be a canonical positive PubMed ID")
        return self._store.decision_log(
            pmid=pmid,
            offset=_page(offset, "offset", 0, 10_000_000),
            limit=_page(limit, "limit", 1, 200),
        )

    def flow(self) -> dict[str, Any]:
        """Return PRISMA 2020 flow counts (identification via databases)."""
        raw = self._store.flow_counts()
        runs = list(raw["runs"])
        identified = sum(int(run["identified_count"]) for run in runs)
        automation = sum(int(run.get("automation_removed") or 0) for run in runs)
        unique = int(raw["unique_records"])
        ta = raw["title_abstract"]
        ft = raw["full_text"]
        reasons = dict(raw["full_text_exclusion_reasons"])
        not_retrieved = sum(count for reason, count in reasons.items() if reason.casefold() in NOT_RETRIEVED_REASONS)
        excluded_reasons = {
            reason: count for reason, count in reasons.items() if reason.casefold() not in NOT_RETRIEVED_REASONS
        }
        sought = ta["include"] + ta["maybe"]
        assessed = ft["include"] + ft["exclude"] - not_retrieved
        by_database: dict[str, int] = {}
        for run in runs:
            by_database[run["database"]] = by_database.get(run["database"], 0) + int(run["identified_count"])
        warnings: list[str] = []
        incomplete = [run["run_id"] for run in runs if not run["exhaustive"]]
        if incomplete:
            warnings.append(
                f"{len(incomplete)} registered run(s) were not exhaustive; identification counts are incomplete"
            )
        if raw["conflicts"]["title_abstract"] or raw["conflicts"]["full_text"]:
            warnings.append("Reviewer decisions conflict for some records; the latest decision is counted")
        return {
            "identification": {
                "records_identified": identified,
                "records_identified_by_database": by_database,
                "records_marked_ineligible_by_automation": automation,
                "duplicate_records_removed": identified - automation - unique,
                "records_after_duplicates_removed": unique,
            },
            "screening": {
                "records_screened": unique,
                "records_screened_with_decision": ta["include"] + ta["exclude"] + ta["maybe"],
                "records_excluded": ta["exclude"],
                "records_awaiting_screening": unique - (ta["include"] + ta["exclude"] + ta["maybe"]),
                "records_maybe": ta["maybe"],
                "reports_sought_for_retrieval": sought,
                "reports_not_retrieved": not_retrieved,
                "reports_assessed_for_eligibility": assessed,
                "reports_excluded": ft["exclude"] - not_retrieved,
                "reports_excluded_by_reason": excluded_reasons,
                "reports_awaiting_assessment": sought - not_retrieved - assessed,
                "reports_maybe": ft["maybe"],
            },
            "included": {"studies_included": ft["include"]},
            "runs": [
                {
                    "run_id": run["run_id"],
                    "database": run["database"],
                    "run_started": run["run_started"],
                    "registered_at": run["registered_at"],
                    "records_identified": run["identified_count"],
                    "records_marked_ineligible_by_automation": int(run.get("automation_removed") or 0),
                    "new_records": run["new_count"],
                    "new_records_unscreened": int(raw["unscreened_by_run"].get(run["run_id"], 0)),
                    "exhaustive": bool(run["exhaustive"]),
                }
                for run in runs
            ],
            "conflicts": raw["conflicts"],
            "reviewers": raw["reviewers"],
            "warnings": warnings,
            "notes": [
                "Counts are records/reports per PMID; group multiple reports of one study manually.",
                'Use reason "not retrieved" on a full-text exclusion to count a report that could not be obtained.',
            ],
        }


def render_prisma_flow_markdown(name: str, flow: dict[str, Any]) -> str:
    """Render PRISMA 2020 flow counts as a compact Markdown summary."""
    ident = flow["identification"]
    screening = flow["screening"]
    lines = [
        f"## PRISMA 2020 flow: {name}",
        "",
        "**Identification**",
        f"- Records identified from databases: {ident['records_identified']}"
        + (
            " (" + ", ".join(f"{db}: {count}" for db, count in ident["records_identified_by_database"].items()) + ")"
            if ident["records_identified_by_database"]
            else ""
        ),
        "- Records marked ineligible by automation tools (pipeline filter steps): "
        f"{ident['records_marked_ineligible_by_automation']}",
        f"- Duplicate records removed (across runs): {ident['duplicate_records_removed']}",
        "",
        "**Screening**",
        f"- Records screened: {screening['records_screened']} "
        f"(decided {screening['records_screened_with_decision']}, awaiting {screening['records_awaiting_screening']}, "
        f"maybe {screening['records_maybe']})",
        f"- Records excluded: {screening['records_excluded']}",
        f"- Reports sought for retrieval: {screening['reports_sought_for_retrieval']}",
        f"- Reports not retrieved: {screening['reports_not_retrieved']}",
        f"- Reports assessed for eligibility: {screening['reports_assessed_for_eligibility']} "
        f"(awaiting {screening['reports_awaiting_assessment']}, maybe {screening['reports_maybe']})",
        f"- Reports excluded: {screening['reports_excluded']}",
    ]
    lines.extend(
        f"  - {escape_markdown_text(reason)}: {count}"
        for reason, count in screening["reports_excluded_by_reason"].items()
    )
    lines.extend(["", "**Included**", f"- Studies included in review: {flow['included']['studies_included']}", ""])
    lines.append("| Run | Database | Identified | New | New unscreened | Exhaustive |")
    lines.append("|-----|----------|------------|-----|----------------|------------|")
    for run in flow["runs"]:
        lines.append(
            f"| `{run['run_id']}` | {run['database']} | {run['records_identified']} | {run['new_records']} "
            f"| {run['new_records_unscreened']} | {'yes' if run['exhaustive'] else 'no'} |"
        )
    for warning in flow["warnings"]:
        lines.append(f"\n⚠️ {warning}")
    return "\n".join(lines)


__all__ = [
    "DECISIONS",
    "MAX_DECISIONS_PER_REQUEST",
    "STAGES",
    "ScreeningService",
    "ScreeningStore",
    "normalize_decision",
    "render_prisma_flow_markdown",
    "run_is_complete_identification",
]
