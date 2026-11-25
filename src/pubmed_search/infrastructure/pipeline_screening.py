"""SQLite screening log for one saved pipeline (systematic-review project).

Follows the research-workspace journal pattern: one transaction per command,
``BEGIN IMMEDIATE`` for writes (and for the first open, so concurrent first
opens serialize before the schema is installed), and a local database file
that separate processes can share. Decisions are append-only; the latest
decision per (PMID, stage) is the effective one, so a changed decision keeps
its audit trail. Every write is idempotent through a stable key.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

_SCHEMA_VERSION = 1
_SCHEMA = (
    """CREATE TABLE runs (
        run_id TEXT PRIMARY KEY, sequence INTEGER NOT NULL UNIQUE, database TEXT NOT NULL,
        identified_count INTEGER NOT NULL, new_count INTEGER NOT NULL, exhaustive INTEGER NOT NULL,
        run_started TEXT, registered_at TEXT NOT NULL
    )""",
    """CREATE TABLE records (
        pmid TEXT PRIMARY KEY, first_run_id TEXT NOT NULL REFERENCES runs(run_id), identified_at TEXT NOT NULL
    )""",
    """CREATE TABLE decisions (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT, decision_id TEXT NOT NULL UNIQUE,
        pmid TEXT NOT NULL REFERENCES records(pmid), stage TEXT NOT NULL, decision TEXT NOT NULL,
        reason TEXT, reviewer TEXT NOT NULL, decided_at TEXT NOT NULL, payload TEXT NOT NULL
    )""",
    "CREATE INDEX decisions_by_stage ON decisions(stage, pmid, sequence)",
    "CREATE INDEX records_by_run ON records(first_run_id)",
)

_LATEST = """
    SELECT d.pmid, d.decision, d.reason FROM decisions d
    JOIN (SELECT pmid, MAX(sequence) AS seq FROM decisions WHERE stage=? GROUP BY pmid) m ON d.sequence = m.seq
"""


# Every statement is a complete literal; caller values are always bound parameters.
_TA_QUEUE_WHERE = (
    "FROM records r JOIN runs u ON u.run_id=r.first_run_id WHERE NOT EXISTS "
    "(SELECT 1 FROM decisions d WHERE d.pmid=r.pmid AND d.stage='title_abstract') "
    "AND (? IS NULL OR r.first_run_id=?)"
)
_FT_QUEUE_WHERE = (
    "FROM records r JOIN runs u ON u.run_id=r.first_run_id "
    "JOIN (SELECT d.pmid, d.decision FROM decisions d JOIN (SELECT pmid, MAX(sequence) AS seq FROM decisions "
    "WHERE stage='title_abstract' GROUP BY pmid) m ON d.sequence=m.seq) ta ON ta.pmid=r.pmid "
    "LEFT JOIN (SELECT d.pmid, d.decision FROM decisions d JOIN (SELECT pmid, MAX(sequence) AS seq FROM decisions "
    "WHERE stage='full_text' GROUP BY pmid) m ON d.sequence=m.seq) ft ON ft.pmid=r.pmid "
    "WHERE ta.decision IN ('include','maybe') AND (ft.decision IS NULL OR ft.decision='maybe') "
    "AND (? IS NULL OR r.first_run_id=?)"
)
_QUEUE_SQL = {
    "title_abstract": (
        "SELECT COUNT(*) " + _TA_QUEUE_WHERE,
        "SELECT r.pmid, r.first_run_id, NULL AS current "
        + _TA_QUEUE_WHERE
        + " ORDER BY u.sequence, CAST(r.pmid AS INTEGER) LIMIT ? OFFSET ?",
    ),
    "full_text": (
        "SELECT COUNT(*) " + _FT_QUEUE_WHERE,
        "SELECT r.pmid, r.first_run_id, ft.decision AS current "
        + _FT_QUEUE_WHERE
        + " ORDER BY u.sequence, CAST(r.pmid AS INTEGER) LIMIT ? OFFSET ?",
    ),
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _decision_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(row["payload"])
    return {**payload, "sequence": row["sequence"], "decided_at": row["decided_at"]}


class SQLiteScreeningStore:
    """Screening records and decisions of one pipeline in one database file."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.is_file()

    @contextmanager
    def _transaction(self, *, write: bool) -> Iterator[sqlite3.Connection]:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._path, timeout=10, isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            first_open = db.execute("PRAGMA user_version").fetchone()[0] == 0
            with db:
                db.execute("BEGIN IMMEDIATE" if write or first_open else "BEGIN")
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version == 0:
                    for statement in _SCHEMA:
                        db.execute(statement)
                    db.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
                elif version != _SCHEMA_VERSION:
                    raise ValueError(f"Unsupported screening database version {version}")
                yield db

    def decision_summary(self) -> dict[str, int]:
        """Count recorded decisions; a missing log is empty and is not created."""
        if not self.exists():
            return {"decisions": 0, "pmids": 0, "reviewers": 0, "records": 0}
        with self._transaction(write=False) as db:
            row = db.execute(
                "SELECT COUNT(*), COUNT(DISTINCT pmid), COUNT(DISTINCT reviewer) FROM decisions"
            ).fetchone()
            records = db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            return {"decisions": row[0], "pmids": row[1], "reviewers": row[2], "records": records}

    # ── Identification ──────────────────────────────────────────────────

    def register_run(
        self,
        run_id: str,
        *,
        database: str,
        pmids: list[str],
        run_started: str | None,
        exhaustive: bool,
    ) -> dict[str, Any]:
        """Add one run's identified records; records first seen here become unscreened."""
        with self._transaction(write=True) as db:
            existing = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if existing is not None:
                if existing["identified_count"] != len(pmids):
                    raise ValueError("run_id is already registered with a different record set")
                return {"run_id": run_id, **dict(existing), "replayed": True}
            sequence = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM runs").fetchone()[0]
            now = _now()
            db.execute(
                "INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)",
                (run_id, sequence, database, len(pmids), 0, int(exhaustive), run_started, now),
            )
            before = db.total_changes
            db.executemany(
                "INSERT INTO records(pmid, first_run_id, identified_at) VALUES(?,?,?) ON CONFLICT(pmid) DO NOTHING",
                [(pmid, run_id, now) for pmid in pmids],
            )
            new_count = db.total_changes - before
            db.execute("UPDATE runs SET new_count=? WHERE run_id=?", (new_count, run_id))
            row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            return {**dict(row), "replayed": False}

    def identified(self, pmids: list[str]) -> set[str]:
        """Return which of ``pmids`` were identified by a registered run."""
        if not pmids:
            return set()
        with self._transaction(write=False) as db:
            rows = db.execute(
                "SELECT pmid FROM records WHERE pmid IN (SELECT value FROM json_each(?))",
                (json.dumps(pmids),),
            )
            return {row[0] for row in rows}

    # ── Decisions ───────────────────────────────────────────────────────

    def record_decisions(self, decisions: list[dict[str, Any]]) -> dict[str, Any]:
        """Append decisions all-or-nothing; a repeated decision_id is a replay."""
        with self._transaction(write=True) as db:
            recorded: list[dict[str, Any]] = []
            replayed = 0
            for decision in decisions:
                existing = db.execute(
                    "SELECT * FROM decisions WHERE decision_id=?", (decision["decision_id"],)
                ).fetchone()
                if existing is not None:
                    if json.loads(existing["payload"]) != decision:
                        raise ValueError(f"decision_id {decision['decision_id']} already exists with different content")
                    recorded.append({**_decision_row(existing), "replayed": True})
                    replayed += 1
                    continue
                if db.execute("SELECT 1 FROM records WHERE pmid=?", (decision["pmid"],)).fetchone() is None:
                    raise ValueError(f"PMID {decision['pmid']} was not identified by a registered run")
                if decision["stage"] == "full_text":
                    latest = db.execute(
                        "SELECT decision FROM decisions WHERE pmid=? AND stage='title_abstract' "
                        "ORDER BY sequence DESC LIMIT 1",
                        (decision["pmid"],),
                    ).fetchone()
                    if latest is None or latest["decision"] not in {"include", "maybe"}:
                        raise ValueError(
                            f"PMID {decision['pmid']} needs a title/abstract include or maybe before full-text screening"
                        )
                now = _now()
                cursor = db.execute(
                    """INSERT INTO decisions(decision_id,pmid,stage,decision,reason,reviewer,decided_at,payload)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        decision["decision_id"],
                        decision["pmid"],
                        decision["stage"],
                        decision["decision"],
                        decision.get("reason"),
                        decision["reviewer"],
                        now,
                        json.dumps(decision, sort_keys=True),
                    ),
                )
                recorded.append({**decision, "sequence": cursor.lastrowid, "decided_at": now, "replayed": False})
            return {"decisions": recorded, "recorded": len(recorded) - replayed, "replayed": replayed}

    def decision_log(self, *, pmid: str | None, offset: int, limit: int) -> dict[str, Any]:
        with self._transaction(write=False) as db:
            total = db.execute("SELECT COUNT(*) FROM decisions WHERE ? IS NULL OR pmid=?", (pmid, pmid)).fetchone()[0]
            rows = db.execute(
                "SELECT * FROM decisions WHERE ? IS NULL OR pmid=? ORDER BY sequence LIMIT ? OFFSET ?",
                (pmid, pmid, limit, offset),
            ).fetchall()
            return {
                "total": total,
                "offset": offset,
                "decisions": [_decision_row(row) for row in rows],
                "next_offset": offset + limit if offset + limit < total else None,
            }

    # ── Queues and flow ─────────────────────────────────────────────────

    def queue(self, *, stage: str, run_id: str | None, offset: int, limit: int) -> dict[str, Any]:
        """Return records awaiting a decision at ``stage`` in identification order."""
        if stage not in _QUEUE_SQL:
            raise ValueError("Unknown screening stage")
        count_sql, rows_sql = _QUEUE_SQL[stage]
        with self._transaction(write=False) as db:
            total = db.execute(count_sql, (run_id, run_id)).fetchone()[0]
            rows = db.execute(rows_sql, (run_id, run_id, limit, offset)).fetchall()
            return {
                "stage": stage,
                "total": total,
                "offset": offset,
                "items": [
                    {"pmid": row["pmid"], "first_run_id": row["first_run_id"], "current_decision": row["current"]}
                    for row in rows
                ],
                "next_offset": offset + limit if offset + limit < total else None,
            }

    def flow_counts(self) -> dict[str, Any]:
        """Return raw aggregates for a PRISMA 2020 flow diagram."""
        with self._transaction(write=False) as db:
            runs = [dict(row) for row in db.execute("SELECT * FROM runs ORDER BY sequence")]
            unique = db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            ta_rows = db.execute(_LATEST, ("title_abstract",)).fetchall()
            ta = {"include": 0, "exclude": 0, "maybe": 0}
            advancing: set[str] = set()
            for row in ta_rows:
                ta[row["decision"]] += 1
                if row["decision"] in {"include", "maybe"}:
                    advancing.add(row["pmid"])
            ft = {"include": 0, "exclude": 0, "maybe": 0}
            reasons: dict[str, int] = {}
            for row in db.execute(_LATEST, ("full_text",)).fetchall():
                if row["pmid"] not in advancing:
                    continue  # a later title/abstract exclusion supersedes full-text work
                ft[row["decision"]] += 1
                if row["decision"] == "exclude":
                    label = row["reason"] or "unspecified"
                    reasons[label] = reasons.get(label, 0) + 1
            conflicts = {
                stage: db.execute(
                    """SELECT COUNT(*) FROM (
                           SELECT d.pmid FROM decisions d JOIN (
                               SELECT pmid, reviewer, MAX(sequence) AS seq FROM decisions WHERE stage=?
                               GROUP BY pmid, reviewer
                           ) m ON d.sequence=m.seq GROUP BY d.pmid HAVING COUNT(DISTINCT d.decision) > 1
                       )""",
                    (stage,),
                ).fetchone()[0]
                for stage in ("title_abstract", "full_text")
            }
            new_unscreened = {
                row["first_run_id"]: row["n"]
                for row in db.execute(
                    """SELECT first_run_id, COUNT(*) AS n FROM records r WHERE NOT EXISTS (
                           SELECT 1 FROM decisions d WHERE d.pmid=r.pmid AND d.stage='title_abstract'
                       ) GROUP BY first_run_id"""
                )
            }
            reviewers = [row[0] for row in db.execute("SELECT DISTINCT reviewer FROM decisions ORDER BY reviewer")]
            return {
                "runs": runs,
                "unique_records": unique,
                "title_abstract": ta,
                "full_text": ft,
                "full_text_exclusion_reasons": reasons,
                "conflicts": conflicts,
                "unscreened_by_run": new_unscreened,
                "reviewers": reviewers,
            }


__all__ = ["SQLiteScreeningStore"]
