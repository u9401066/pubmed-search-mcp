"""SQLite journal for research decisions and open actions under a tenant's local data root."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pubmed_search.application.research_workspace import ACTIVITIES

if TYPE_CHECKING:
    from collections.abc import Iterator

_SCHEMA = (
    """CREATE TABLE workspaces (
        workspace_id TEXT PRIMARY KEY, question TEXT NOT NULL, created_at TEXT NOT NULL
    )""",
    """CREATE TABLE records (
        workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
        sequence INTEGER NOT NULL, record_id TEXT NOT NULL, activity TEXT NOT NULL,
        payload TEXT NOT NULL, created_at TEXT NOT NULL, next_action TEXT, resolved_by TEXT,
        PRIMARY KEY (workspace_id, sequence), UNIQUE (workspace_id, record_id)
    )""",
    """CREATE INDEX open_actions ON records(workspace_id, sequence)
       WHERE next_action IS NOT NULL AND resolved_by IS NULL""",
)


def _decode_record(row: sqlite3.Row) -> dict[str, Any]:
    return {**json.loads(row["payload"]), "sequence": row["sequence"], "created_at": row["created_at"]}


class SQLiteResearchWorkspaceStore:
    """Each command has one transaction. Separate processes can share a local database file."""

    def __init__(self, tenant_root: Path | str) -> None:
        self._path = Path(tenant_root) / "research-workspaces.sqlite3"

    @contextmanager
    def _transaction(self, *, write: bool) -> Iterator[sqlite3.Connection]:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._path, timeout=10, isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            # Make concurrent first opens serialize before installing the schema.
            first_open = db.execute("PRAGMA user_version").fetchone()[0] == 0
            with db:
                db.execute("BEGIN IMMEDIATE" if write or first_open else "BEGIN")
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version == 0:
                    for statement in _SCHEMA:
                        db.execute(statement)
                    db.execute("PRAGMA user_version=1")
                elif version != 1:
                    raise ValueError(f"Unsupported research workspace database version {version}")
                yield db

    @staticmethod
    def _workspace(db: sqlite3.Connection, workspace_id: str) -> dict[str, Any]:
        row = db.execute("SELECT * FROM workspaces WHERE workspace_id=?", (workspace_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown workspace_id: {workspace_id}")
        return dict(row)

    def create(self, workspace_id: str, question: str) -> dict[str, Any]:
        with self._transaction(write=True) as db:
            now = datetime.now(timezone.utc).isoformat()
            result = db.execute(
                "INSERT INTO workspaces VALUES(?,?,?) ON CONFLICT(workspace_id) DO NOTHING",
                (workspace_id, question, now),
            )
            workspace = self._workspace(db, workspace_id)
            if workspace["question"] != question:
                raise ValueError("workspace_id already exists with a different question")
            return {**workspace, "replayed": result.rowcount == 0}

    def append(self, workspace_id: str, record: dict[str, Any]) -> dict[str, Any]:
        record_id = record["record_id"]
        with self._transaction(write=True) as db:
            self._workspace(db, workspace_id)
            lookup = "SELECT * FROM records WHERE workspace_id=? AND record_id=?"
            existing = db.execute(lookup, (workspace_id, record_id)).fetchone()
            if existing is not None:
                if json.loads(existing["payload"]) != record:
                    raise ValueError("record_id already exists with different content")
                return {"workspace_id": workspace_id, "record": _decode_record(existing), "replayed": True}

            for parent in record["parent_ids"]:
                if db.execute(lookup, (workspace_id, parent)).fetchone() is None:
                    raise ValueError(f"Unknown parent record: {parent}")
            for prior in record["resolves"]:
                closed = db.execute(
                    """UPDATE records SET resolved_by=? WHERE workspace_id=? AND record_id=?
                       AND next_action IS NOT NULL AND resolved_by IS NULL""",
                    (record_id, workspace_id, prior),
                )
                if closed.rowcount != 1:
                    raise ValueError(f"Record has no open action in this workspace: {prior}")
            sequence = db.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM records WHERE workspace_id=?", (workspace_id,)
            ).fetchone()[0]
            now = datetime.now(timezone.utc).isoformat()
            db.execute(
                """INSERT INTO records(workspace_id,sequence,record_id,activity,payload,created_at,next_action)
                   VALUES(?,?,?,?,?,?,?)""",
                (workspace_id, sequence, record_id, record["activity"], json.dumps(record), now, record["next_action"]),
            )
            return {
                "workspace_id": workspace_id,
                "record": {**record, "sequence": sequence, "created_at": now},
                "replayed": False,
            }

    def read(self, workspace_id: str, after: int | None, limit: int, open_offset: int) -> dict[str, Any]:
        with self._transaction(write=False) as db:
            workspace = self._workspace(db, workspace_id)
            counts = dict.fromkeys(ACTIVITIES, 0)
            counts.update(
                db.execute(
                    "SELECT activity, COUNT(*) FROM records WHERE workspace_id=? GROUP BY activity", (workspace_id,)
                )
            )
            total = sum(counts.values())
            cursor = max(0, total - limit) if after is None else after
            rows = db.execute(
                "SELECT * FROM records WHERE workspace_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                (workspace_id, cursor, limit),
            )
            records = [_decode_record(row) for row in rows]
            open_count = db.execute(
                "SELECT COUNT(*) FROM records WHERE workspace_id=? AND next_action IS NOT NULL AND resolved_by IS NULL",
                (workspace_id,),
            ).fetchone()[0]
            open_rows = db.execute(
                """SELECT record_id,sequence,next_action,payload FROM records WHERE workspace_id=?
                   AND next_action IS NOT NULL AND resolved_by IS NULL ORDER BY sequence LIMIT ? OFFSET ?""",
                (workspace_id, limit, open_offset),
            )
            return {
                **workspace,
                "record_count": total,
                "activity_counts": counts,
                "records": records,
                "next_after": records[-1]["sequence"] if records and records[-1]["sequence"] < total else None,
                "open_actions": [
                    {
                        "record_id": row["record_id"],
                        "sequence": row["sequence"],
                        "next_action": row["next_action"],
                        "source_refs": json.loads(row["payload"])["source_refs"],
                    }
                    for row in open_rows
                ],
                "open_action_count": open_count,
                "next_open_offset": open_offset + limit if open_offset + limit < open_count else None,
            }

    def list_workspaces(self, offset: int, limit: int) -> dict[str, Any]:
        with self._transaction(write=False) as db:
            rows = db.execute(
                """SELECT w.*,
                   (SELECT COUNT(*) FROM records r WHERE r.workspace_id=w.workspace_id) AS record_count
                   FROM workspaces w ORDER BY w.workspace_id LIMIT ? OFFSET ?""",
                (limit + 1, offset),
            ).fetchall()
            return {
                "workspaces": [dict(row) for row in rows[:limit]],
                "next_offset": offset + limit if len(rows) > limit else None,
            }
