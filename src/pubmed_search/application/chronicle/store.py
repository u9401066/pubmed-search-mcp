"""Versioned on-disk persistence for chronicle revisions.

Each chronicle owns a directory containing one JSON file per revision plus an
``index.json`` describing the chronicle. Revisions are monotonic and immutable:
an update always writes ``revision + 1`` rather than mutating history.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pubmed_search.domain.entities.chronicle import ChronicleSnapshot
from pubmed_search.shared.file_io import atomic_write_json
from pubmed_search.shared.locking import synchronized

if TYPE_CHECKING:
    from collections.abc import Callable

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_REVISION_FILE_RE = re.compile(r"^revision-(\d+)\.json$")

# MCP SDK v2 may execute synchronous handlers in worker threads. Every store
# rooted in this process therefore shares one revision-allocation boundary.
# Service deployments remain single-process/single-replica until a shared
# transactional persistence backend replaces these local files.
_CHRONICLE_PERSISTENCE_LOCK = threading.RLock()


class ChronicleStore:
    """Read and write chronicle revisions under a single root directory."""

    def __init__(self, root_dir: str | Path) -> None:
        """Create the store, making the root directory if needed.

        Args:
            root_dir: Directory that will hold one subdirectory per chronicle.
        """
        self.root_dir = Path(root_dir).expanduser().resolve()
        self._lock = _CHRONICLE_PERSISTENCE_LOCK
        self.root_dir.mkdir(parents=True, exist_ok=True)

    @synchronized
    def save(self, snapshot: ChronicleSnapshot) -> Path:
        """Persist a fixed revision without overwriting immutable history.

        Args:
            snapshot: The revision to write.

        Returns:
            The path of the written revision file.
        """
        return self._save_unlocked(snapshot)

    @synchronized
    def commit_next(
        self,
        chronicle_id: str,
        build_snapshot: Callable[[int, str | None], ChronicleSnapshot],
    ) -> ChronicleSnapshot:
        """Allocate and atomically publish the next immutable revision.

        ``build_snapshot`` runs while the process-wide transaction lock is
        held. It receives the revision allocated at commit time plus the
        original creation timestamp, if this chronicle already exists. This
        keeps revision-dependent projections consistent without holding the
        lock during external evidence retrieval.

        Args:
            chronicle_id: Stable identifier whose next revision is committed.
            build_snapshot: Finalizer accepting ``(revision, created_at)``.

        Returns:
            The finalized and persisted snapshot.
        """
        previous = self._load_unlocked(chronicle_id)
        revision = previous.revision + 1 if previous else 1
        snapshot = build_snapshot(revision, previous.created_at if previous else None)
        if snapshot.chronicle_id != chronicle_id:
            msg = f"Chronicle commit changed identity: expected {chronicle_id!r}, got {snapshot.chronicle_id!r}"
            raise ValueError(msg)
        if snapshot.revision != revision:
            msg = f"Chronicle commit must use allocated revision {revision}, got {snapshot.revision}"
            raise ValueError(msg)
        self._save_unlocked(snapshot)
        return snapshot

    @synchronized
    def load(self, chronicle_id: str, revision: int | None = None) -> ChronicleSnapshot | None:
        """Load one revision of a chronicle.

        Args:
            chronicle_id: Identifier of the chronicle to read.
            revision: Revision number, or ``None`` for the latest.

        Returns:
            The snapshot, or ``None`` when the chronicle or revision is absent.
        """
        return self._load_unlocked(chronicle_id, revision)

    @synchronized
    def latest_revision(self, chronicle_id: str) -> int | None:
        """Return the highest revision number stored for *chronicle_id*."""
        return self._latest_revision_unlocked(chronicle_id)

    @synchronized
    def list_revisions(self, chronicle_id: str) -> list[int]:
        """Return every stored revision number for *chronicle_id*, ascending."""
        return self._list_revisions_unlocked(chronicle_id)

    @synchronized
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

    def _save_unlocked(self, snapshot: ChronicleSnapshot) -> Path:
        """Persist one revision while the transaction lock is held."""
        if snapshot.revision < 1:
            msg = f"Chronicle revision must be positive: {snapshot.revision}"
            raise ValueError(msg)

        chronicle_dir = self._chronicle_dir(snapshot.chronicle_id)
        chronicle_dir.mkdir(parents=True, exist_ok=True)
        revision_path = chronicle_dir / f"revision-{snapshot.revision}.json"
        if revision_path.exists():
            msg = f"Chronicle revision already exists and is immutable: {snapshot.chronicle_id}@{snapshot.revision}"
            raise FileExistsError(msg)

        atomic_write_json(revision_path, snapshot.to_dict())

        # A fixed revision may be imported out of order. Keep the index pointed
        # at the actual highest immutable revision rather than the last caller.
        latest = self._load_unlocked(snapshot.chronicle_id)
        if latest is None:  # pragma: no cover - the revision was just published
            msg = f"Chronicle revision could not be reloaded: {snapshot.chronicle_id}@{snapshot.revision}"
            raise RuntimeError(msg)
        atomic_write_json(chronicle_dir / "index.json", self._index_record(latest))
        return revision_path

    def _load_unlocked(self, chronicle_id: str, revision: int | None = None) -> ChronicleSnapshot | None:
        """Load one revision while the transaction lock is held."""
        chronicle_dir = self._chronicle_dir(chronicle_id)
        if not chronicle_dir.is_dir():
            return None

        target = revision if revision is not None else self._latest_revision_unlocked(chronicle_id)
        if target is None:
            return None

        revision_path = chronicle_dir / f"revision-{target}.json"
        if not revision_path.is_file():
            return None
        return ChronicleSnapshot.from_dict(json.loads(revision_path.read_text(encoding="utf-8")))

    def _latest_revision_unlocked(self, chronicle_id: str) -> int | None:
        """Return the highest revision while the transaction lock is held."""
        revisions = self._list_revisions_unlocked(chronicle_id)
        return max(revisions) if revisions else None

    def _list_revisions_unlocked(self, chronicle_id: str) -> list[int]:
        """Return revision numbers while the transaction lock is held."""
        chronicle_dir = self._chronicle_dir(chronicle_id)
        if not chronicle_dir.is_dir():
            return []
        return sorted(
            int(match.group(1))
            for path in chronicle_dir.iterdir()
            if (match := _REVISION_FILE_RE.match(path.name)) is not None
        )

    @staticmethod
    def _index_record(snapshot: ChronicleSnapshot) -> dict[str, Any]:
        """Return the index record for the latest snapshot."""
        return {
            "chronicle_id": snapshot.chronicle_id,
            "topic": snapshot.topic,
            "latest_revision": snapshot.revision,
            "created_at": snapshot.created_at,
            "updated_at": snapshot.updated_at,
            "entry_count": len(snapshot.entries),
            "evidence_count": len(snapshot.evidence_articles),
            "audit_status": snapshot.audit.status,
            "mode": snapshot.input_scope.mode,
        }

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
