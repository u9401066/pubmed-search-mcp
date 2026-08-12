"""Versioned on-disk persistence for chronicle revisions.

Each chronicle owns a directory containing one JSON file per revision plus an
``index.json`` cache describing the latest revision. Revision JSON files are the
source of truth; the index is rebuilt when it is missing, corrupt, or stale.
Revisions are monotonic and immutable: an update always writes ``revision + 1``
rather than mutating history.
"""

from __future__ import annotations

import errno
import importlib
import json
import logging
import os
import re
import tempfile
import threading
import time
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pubmed_search.domain.entities.chronicle import ChronicleSnapshot

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_REVISION_FILE_RE = re.compile(r"^revision-(\d+)\.json$")
_LOCK_FILE_NAME = ".revision.lock"
_LOCK_TIMEOUT_SECONDS = 30.0
_LOCK_POLL_SECONDS = 0.01
_PLATFORM_LOCK = importlib.import_module("msvcrt" if os.name == "nt" else "fcntl")
_THREAD_LOCKS: dict[Path, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()

SnapshotFactory = Callable[[int, ChronicleSnapshot | None], ChronicleSnapshot]
logger = logging.getLogger(__name__)


def _normalize_topic(topic: str) -> str:
    """Return the exact-match key used for stored chronicle topics."""
    normalized = unicodedata.normalize("NFC", topic)
    return " ".join(normalized.split()).casefold()


def _thread_lock_for(path: Path) -> threading.Lock:
    """Return the process-local lock paired with one chronicle lock file."""
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(path, threading.Lock())


def _try_platform_lock(file_descriptor: int) -> None:
    """Attempt a non-blocking exclusive lock, raising when it is busy."""
    if os.name == "nt":
        os.lseek(file_descriptor, 0, os.SEEK_SET)
        _PLATFORM_LOCK.locking(file_descriptor, _PLATFORM_LOCK.LK_NBLCK, 1)
        return
    _PLATFORM_LOCK.flock(file_descriptor, _PLATFORM_LOCK.LOCK_EX | _PLATFORM_LOCK.LOCK_NB)


def _release_platform_lock(file_descriptor: int) -> None:
    """Release a lock acquired by :func:`_try_platform_lock`."""
    if os.name == "nt":
        os.lseek(file_descriptor, 0, os.SEEK_SET)
        _PLATFORM_LOCK.locking(file_descriptor, _PLATFORM_LOCK.LK_UNLCK, 1)
        return
    _PLATFORM_LOCK.flock(file_descriptor, _PLATFORM_LOCK.LOCK_UN)


def _fsync_directory(directory: Path) -> None:
    """Best-effort flush of directory metadata after an atomic rename/link."""
    try:
        file_descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(file_descriptor)
    except OSError:
        # Some supported platforms and filesystems cannot fsync directories.
        pass
    finally:
        os.close(file_descriptor)


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
        """Persist *snapshot* without ever replacing an existing revision.

        This method supports importing a specific revision number. New service
        revisions should use :meth:`append`, which allocates the next revision
        while holding the same process/thread-safe lock used for the write.

        Args:
            snapshot: The revision to write.

        Returns:
            The path of the written revision file.

        Raises:
            FileExistsError: If that revision is already stored.
            ValueError: If the revision number is not positive.
        """
        if snapshot.revision < 1:
            msg = f"Chronicle revisions must be positive, got {snapshot.revision}"
            raise ValueError(msg)

        chronicle_dir = self._chronicle_dir(snapshot.chronicle_id)
        chronicle_dir.mkdir(parents=True, exist_ok=True)
        serialized = self._serialize_snapshot(snapshot)
        with self._revision_lock(chronicle_dir):
            return self._save_locked(snapshot, serialized, chronicle_dir)

    def append(self, chronicle_id: str, factory: SnapshotFactory) -> ChronicleSnapshot:
        """Build and atomically append the next revision of one chronicle.

        Allocation, loading the predecessor, snapshot construction, and the
        exclusive revision write all happen under one lock. Consequently two
        threads or processes cannot allocate the same next revision.

        Args:
            chronicle_id: Chronicle whose next revision should be appended.
            factory: Called with ``(next_revision, previous_snapshot)``.

        Returns:
            The snapshot returned by *factory* after it is durably persisted.

        Raises:
            ValueError: If *factory* changes the chronicle ID or revision.
        """
        chronicle_dir = self._chronicle_dir(chronicle_id)
        chronicle_dir.mkdir(parents=True, exist_ok=True)

        with self._revision_lock(chronicle_dir):
            latest = self._latest_revision_in_dir(chronicle_dir)
            previous = self._load_from_dir(chronicle_dir, latest) if latest is not None else None
            next_revision = (latest or 0) + 1
            snapshot = factory(next_revision, previous)
            if snapshot.chronicle_id != chronicle_id:
                msg = f"Snapshot factory changed chronicle id: expected {chronicle_id}, got {snapshot.chronicle_id}"
                raise ValueError(msg)
            if snapshot.revision != next_revision:
                msg = f"Snapshot factory returned revision {snapshot.revision}; expected {next_revision}"
                raise ValueError(msg)

            self._save_locked(snapshot, self._serialize_snapshot(snapshot), chronicle_dir)
            return snapshot

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

        target = revision if revision is not None else self._latest_revision_in_dir(chronicle_dir)
        if target is None:
            return None
        return self._load_from_dir(chronicle_dir, target)

    def latest_revision(self, chronicle_id: str) -> int | None:
        """Return the highest revision number stored for *chronicle_id*."""
        chronicle_dir = self._chronicle_dir(chronicle_id)
        if not chronicle_dir.is_dir():
            return None
        return self._latest_revision_in_dir(chronicle_dir)

    def list_revisions(self, chronicle_id: str) -> list[int]:
        """Return every stored revision number for *chronicle_id*, ascending."""
        chronicle_dir = self._chronicle_dir(chronicle_id)
        if not chronicle_dir.is_dir():
            return []
        return self._revisions_in_dir(chronicle_dir)

    def list_chronicles(self, *, topic: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """List chronicle index records, most recently updated first.

        Args:
            topic: Optional case-insensitive substring filter on the topic.
            limit: Maximum number of records to return.

        Returns:
            Index records, each including ``chronicle_id`` and ``latest_revision``.
        """
        records = self._index_records()
        if topic:
            topic_key = _normalize_topic(topic)
            records = [record for record in records if topic_key in _normalize_topic(str(record.get("topic", "")))]

        records.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return records[: max(limit, 0)]

    def find_chronicle_ids_by_topic(self, topic: str) -> list[str]:
        """Return IDs whose normalized stored topic exactly matches *topic*.

        Normalization uses Unicode NFC, collapses whitespace, and case-folds.
        A list deliberately represents zero, one, or multiple matches so callers
        can surface ambiguity instead of silently choosing one chronicle.
        """
        topic_key = _normalize_topic(topic)
        if not topic_key:
            return []

        matching_ids = {
            str(record["chronicle_id"])
            for record in self._index_records()
            if record.get("chronicle_id") and _normalize_topic(str(record.get("topic", ""))) == topic_key
        }
        return sorted(matching_ids)

    def _save_locked(self, snapshot: ChronicleSnapshot, serialized: str, chronicle_dir: Path) -> Path:
        """Commit one revision, then refresh the rebuildable index cache.

        Publishing and fsyncing the immutable revision file is the commit point.
        Once that succeeds, an index failure must not make the caller believe
        the revision failed: list/find operations reconstruct the cache from the
        revision files on their next read.
        """
        revision_path = chronicle_dir / f"revision-{snapshot.revision}.json"
        self._write_revision_exclusive(revision_path, serialized)
        self._refresh_index_cache_best_effort_locked(chronicle_dir)
        return revision_path

    @staticmethod
    def _serialize_snapshot(snapshot: ChronicleSnapshot) -> str:
        """Serialize before reserving a revision so JSON failures write nothing."""
        return json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2, allow_nan=False)

    @staticmethod
    def _load_from_dir(chronicle_dir: Path, revision: int) -> ChronicleSnapshot | None:
        """Load one known revision directly from *chronicle_dir*."""
        revision_path = chronicle_dir / f"revision-{revision}.json"
        if not revision_path.is_file():
            return None
        return ChronicleSnapshot.from_dict(json.loads(revision_path.read_text(encoding="utf-8")))

    @staticmethod
    def _revisions_in_dir(chronicle_dir: Path) -> list[int]:
        """Return valid revision file numbers in ascending order."""
        return sorted(
            int(match.group(1))
            for path in chronicle_dir.iterdir()
            if (match := _REVISION_FILE_RE.match(path.name)) is not None
        )

    @classmethod
    def _latest_revision_in_dir(cls, chronicle_dir: Path) -> int | None:
        """Return the greatest on-disk revision number in *chronicle_dir*."""
        revisions = cls._revisions_in_dir(chronicle_dir)
        return revisions[-1] if revisions else None

    def _index_records(self) -> list[dict[str, Any]]:
        """Build authoritative records from revisions and repair index caches.

        A missing, corrupt, or stale ``index.json`` never hides a committed
        Chronicle. Each directory is reconciled under the same lock used by
        writers, and a cache-write failure does not suppress the derived record.
        """
        records: list[dict[str, Any]] = []
        try:
            chronicle_dirs = sorted(path for path in self.root_dir.iterdir() if path.is_dir())
        except OSError:
            logger.warning("Unable to enumerate Chronicle revision directories", exc_info=True)
            return records

        for chronicle_dir in chronicle_dirs:
            if _SAFE_ID_RE.fullmatch(chronicle_dir.name) is None:
                continue
            try:
                with self._revision_lock(chronicle_dir):
                    record = self._refresh_index_cache_best_effort_locked(chronicle_dir)
            except Exception:
                logger.warning(
                    "Unable to reconstruct Chronicle index cache from %s",
                    chronicle_dir,
                    exc_info=True,
                )
                continue
            if record is not None:
                records.append(record)
        return records

    def _refresh_index_cache_best_effort_locked(self, chronicle_dir: Path) -> dict[str, Any] | None:
        """Return the revision-derived record and best-effort refresh its cache.

        The caller must hold ``_revision_lock(chronicle_dir)``. All failures
        after a durable revision commit are deliberately contained here.
        """
        try:
            record, snapshot = self._authoritative_index_record(chronicle_dir)
        except Exception:
            logger.warning(
                "Unable to derive Chronicle index from revisions in %s",
                chronicle_dir,
                exc_info=True,
            )
            return None
        if record is None or snapshot is None:
            return None

        try:
            cached = self._read_index_cache(chronicle_dir)
            if cached != record:
                self._write_index_atomic(chronicle_dir, snapshot)
        except Exception:
            logger.warning(
                "Chronicle revision is durable but index cache refresh failed for %s",
                chronicle_dir,
                exc_info=True,
            )
        return record

    @classmethod
    def _authoritative_index_record(
        cls,
        chronicle_dir: Path,
    ) -> tuple[dict[str, Any] | None, ChronicleSnapshot | None]:
        """Derive the latest index record solely from immutable revisions."""
        latest = cls._latest_revision_in_dir(chronicle_dir)
        if latest is None:
            return None, None
        snapshot = cls._load_from_dir(chronicle_dir, latest)
        if snapshot is None:
            return None, None
        if snapshot.revision != latest:
            msg = f"Revision payload {snapshot.revision} does not match revision-{latest}.json"
            raise ValueError(msg)
        if snapshot.chronicle_id != chronicle_dir.name:
            msg = f"Revision Chronicle ID {snapshot.chronicle_id!r} does not match directory {chronicle_dir.name!r}"
            raise ValueError(msg)
        return cls._index_record(snapshot), snapshot

    @staticmethod
    def _read_index_cache(chronicle_dir: Path) -> dict[str, Any] | None:
        """Read ``index.json`` when it is valid; otherwise request a rebuild."""
        index_path = chronicle_dir / "index.json"
        try:
            record = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return record if isinstance(record, dict) else None

    @staticmethod
    def _index_record(snapshot: ChronicleSnapshot) -> dict[str, Any]:
        """Build the compact index representation for *snapshot*."""
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

    @classmethod
    def _write_index_atomic(cls, chronicle_dir: Path, snapshot: ChronicleSnapshot) -> None:
        """Atomically refresh ``index.json`` from the highest stored revision."""
        payload = json.dumps(cls._index_record(snapshot), ensure_ascii=False, indent=2)
        index_path = chronicle_dir / "index.json"
        temp_path = cls._write_temp_file(chronicle_dir, ".index-", payload)
        try:
            temp_path.replace(index_path)
            _fsync_directory(chronicle_dir)
        finally:
            temp_path.unlink(missing_ok=True)

    @classmethod
    def _write_revision_exclusive(cls, revision_path: Path, serialized: str) -> None:
        """Publish a complete JSON file atomically, refusing replacement."""
        temp_path = cls._write_temp_file(revision_path.parent, f".{revision_path.stem}-", serialized)
        try:
            try:
                # A same-directory hard link combines atomic publication with
                # no-replace semantics. The fully fsynced temp file is never
                # observable under the revision name until this succeeds.
                os.link(temp_path, revision_path)
            except FileExistsError as exc:
                msg = f"Chronicle revision is immutable and already exists: {revision_path}"
                raise FileExistsError(errno.EEXIST, msg, str(revision_path)) from exc
            _fsync_directory(revision_path.parent)
        finally:
            temp_path.unlink(missing_ok=True)

    @staticmethod
    def _write_temp_file(directory: Path, prefix: str, payload: str) -> Path:
        """Write and fsync a UTF-8 temporary file in *directory*."""
        file_descriptor, raw_path = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=directory)
        temp_path = Path(raw_path)
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise
        return temp_path

    @contextmanager
    def _revision_lock(self, chronicle_dir: Path) -> Iterator[None]:
        """Hold the per-chronicle thread and inter-process revision lock."""
        lock_path = chronicle_dir / _LOCK_FILE_NAME
        thread_lock = _thread_lock_for(lock_path)
        with thread_lock:
            file_descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            locked = False
            try:
                if os.name == "nt" and os.fstat(file_descriptor).st_size == 0:
                    os.write(file_descriptor, b"\0")
                    os.fsync(file_descriptor)

                deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
                while True:
                    try:
                        _try_platform_lock(file_descriptor)
                        locked = True
                        break
                    except OSError as exc:
                        if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                            raise
                        if time.monotonic() >= deadline:
                            msg = f"Timed out waiting for chronicle revision lock: {lock_path}"
                            raise TimeoutError(msg) from exc
                        time.sleep(_LOCK_POLL_SECONDS)
                yield
            finally:
                if locked:
                    _release_platform_lock(file_descriptor)
                os.close(file_descriptor)

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
