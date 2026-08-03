"""Versioned on-disk persistence for chronicle revisions.

Each chronicle owns a directory containing one JSON file per revision plus an
``index.json`` describing the chronicle. Revisions are monotonic and immutable:
an update always writes ``revision + 1`` rather than mutating history.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pubmed_search.domain.entities.chronicle import ChronicleSnapshot

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_REVISION_FILE_RE = re.compile(r"^revision-(\d+)\.json$")


class ChronicleStore:
    """Read and write chronicle revisions under a single root directory."""

    def __init__(self, root_dir: str | Path) -> None:
        """Create the store, making the root directory if needed.

        Args:
            root_dir: Directory that will hold one subdirectory per chronicle.
        """
        self.root_dir = Path(root_dir).expanduser().resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def save(self, snapshot: ChronicleSnapshot) -> Path:
        """Persist *snapshot* as its own revision file and refresh the index.

        Args:
            snapshot: The revision to write.

        Returns:
            The path of the written revision file.
        """
        chronicle_dir = self._chronicle_dir(snapshot.chronicle_id)
        chronicle_dir.mkdir(parents=True, exist_ok=True)

        revision_path = chronicle_dir / f"revision-{snapshot.revision}.json"
        revision_path.write_text(
            json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        index_path = chronicle_dir / "index.json"
        index_path.write_text(
            json.dumps(
                {
                    "chronicle_id": snapshot.chronicle_id,
                    "topic": snapshot.topic,
                    "latest_revision": snapshot.revision,
                    "created_at": snapshot.created_at,
                    "updated_at": snapshot.updated_at,
                    "entry_count": len(snapshot.entries),
                    "evidence_count": len(snapshot.evidence_articles),
                    "audit_status": snapshot.audit.status,
                    "mode": snapshot.input_scope.mode,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return revision_path

    def load(self, chronicle_id: str, revision: int | None = None) -> ChronicleSnapshot | None:
        """Load one revision of a chronicle.

        Args:
            chronicle_id: Identifier of the chronicle to read.
            revision: Revision number, or ``None`` for the latest.

        Returns:
            The snapshot, or ``None`` when the chronicle or revision is absent.
        """
        chronicle_dir = self._chronicle_dir(chronicle_id)
        if not chronicle_dir.is_dir():
            return None

        target = revision if revision is not None else self.latest_revision(chronicle_id)
        if target is None:
            return None

        revision_path = chronicle_dir / f"revision-{target}.json"
        if not revision_path.is_file():
            return None
        return ChronicleSnapshot.from_dict(json.loads(revision_path.read_text(encoding="utf-8")))

    def latest_revision(self, chronicle_id: str) -> int | None:
        """Return the highest revision number stored for *chronicle_id*."""
        chronicle_dir = self._chronicle_dir(chronicle_id)
        if not chronicle_dir.is_dir():
            return None

        revisions = [
            int(match.group(1))
            for path in chronicle_dir.iterdir()
            if (match := _REVISION_FILE_RE.match(path.name)) is not None
        ]
        return max(revisions) if revisions else None

    def list_revisions(self, chronicle_id: str) -> list[int]:
        """Return every stored revision number for *chronicle_id*, ascending."""
        chronicle_dir = self._chronicle_dir(chronicle_id)
        if not chronicle_dir.is_dir():
            return []
        return sorted(
            int(match.group(1))
            for path in chronicle_dir.iterdir()
            if (match := _REVISION_FILE_RE.match(path.name)) is not None
        )

    def list_chronicles(self, *, topic: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """List chronicle index records, most recently updated first.

        Args:
            topic: Optional case-insensitive substring filter on the topic.
            limit: Maximum number of records to return.

        Returns:
            Index records, each including ``chronicle_id`` and ``latest_revision``.
        """
        records: list[dict[str, Any]] = []
        for index_path in self.root_dir.glob("*/index.json"):
            try:
                record = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(record, dict):
                continue
            if topic and topic.lower() not in str(record.get("topic", "")).lower():
                continue
            records.append(record)

        records.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return records[: max(limit, 0)]

    def _chronicle_dir(self, chronicle_id: str) -> Path:
        """Return the directory for *chronicle_id*, rejecting unsafe names."""
        if not _SAFE_ID_RE.match(chronicle_id):
            msg = f"Unsafe chronicle id: {chronicle_id}"
            raise ValueError(msg)
        path = (self.root_dir / chronicle_id).resolve()
        try:
            path.relative_to(self.root_dir)
        except ValueError as exc:
            msg = f"Chronicle path escapes root: {path}"
            raise ValueError(msg) from exc
        return path


__all__ = ["ChronicleStore"]
