"""Durable, single-writer checkpoints for long-running paired experiments."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from pubmed_search.shared.file_io import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

# These statuses measure execution infrastructure, not research ability. Keep
# every attempt but leave its arm pending until a later, explicitly resumed run.
PENDING_STATUSES = frozenset({"provider_limited", "process_failed", "invalid_trace", "interrupted"})
TERMINAL_STATUSES = frozenset({"completed", "invalid_answer", "timeout"})


def write_json(path: Path, value: Any) -> None:
    """Publish whole JSON files atomically; never expose a half-written result."""
    atomic_write_text(path, json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


class ExperimentStore:
    """Require an identical protocol on resume; preserve every executed attempt."""

    def __init__(self, root: Path, manifest: dict[str, Any], *, resume: bool = False):
        # Keep imports of the evaluation/scoring helpers portable. Execution of
        # this runner uses POSIX process groups and advisory locks.
        import fcntl

        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self._lock = (root / ".lock").open("a+")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._validate_manifest(manifest, resume)
        except BaseException:
            self._lock.close()
            raise
        self.fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True, allow_nan=False).encode()).hexdigest()

    def _validate_manifest(self, manifest: dict[str, Any], resume: bool) -> None:
        path = self.root / "manifest.json"
        if path.exists():
            if not resume:
                raise ValueError("Experiment exists; use --resume with the same protocol")
            previous = json.dumps(json.loads(path.read_text(encoding="utf-8")), sort_keys=True, allow_nan=False)
            if previous != json.dumps(manifest, sort_keys=True, allow_nan=False):
                raise ValueError("Resume protocol mismatch: dataset, revision, model, or evaluator changed")
        else:
            if resume:
                raise ValueError("Cannot resume without manifest.json")
            if any(p.name != ".lock" for p in self.root.iterdir()):
                raise ValueError("New experiment directory must be empty")
            write_json(path, manifest)

    def case_root(self, qid: str, repeat: int, arm: str) -> Path:
        if not isinstance(qid, str) or len(qid) != 64 or any(char not in "0123456789abcdef" for char in qid):
            raise ValueError("Query IDs must be SHA-256 hex digests")
        if type(repeat) is not int or repeat < 0 or arm not in ("native", "package"):
            raise ValueError("Invalid repeat or arm")
        return self.root / "cases" / qid / f"r{repeat:03d}-{arm}"

    def outcome(self, qid: str, repeat: int, arm: str) -> dict[str, Any] | None:
        """Recover a completed attempt even if progress writing was interrupted."""
        case = self.case_root(qid, repeat, arm)
        for attempt in sorted(case.glob("attempt-*")):
            path = attempt / "result.json"
            if not path.exists():
                continue
            result = self._read_attempt(path)
            if result["status"] in TERMINAL_STATUSES:
                return result
        return None

    def _read_attempt(self, path: Path) -> dict[str, Any]:
        """Apply the same integrity checks to scoring and resource accounting."""
        result = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            raise ValueError("Checkpoint must be a JSON object")  # noqa: TRY004 - malformed persisted JSON
        if result.get("experiment_fingerprint") != self.fingerprint:
            raise ValueError("Checkpoint belongs to a different experiment")
        qid, repeat, arm = result.get("query_id"), result.get("repeat"), result.get("arm")
        if not isinstance(qid, str) or type(repeat) is not int or not isinstance(arm, str):
            raise ValueError("Invalid checkpoint question, repeat, or arm")
        case = self.case_root(qid, repeat, arm)
        if case != path.parent.parent:
            raise ValueError("Checkpoint question, repeat, or arm mismatch")
        status = result.get("status")
        if not isinstance(status, str) or status not in PENDING_STATUSES | TERMINAL_STATUSES:
            raise ValueError("Unknown checkpoint status")
        events = path.parent / "events.jsonl"
        if hashlib.sha256(events.read_bytes()).hexdigest() != result.get("events_sha256"):
            raise ValueError("Checkpoint trace fingerprint mismatch")
        return result

    def next_attempt(self, qid: str, repeat: int, arm: str) -> Path:
        case = self.case_root(qid, repeat, arm)
        case.mkdir(parents=True, exist_ok=True)
        numbers = [int(path.name.removeprefix("attempt-")) for path in case.glob("attempt-*")]
        return case / f"attempt-{max(numbers, default=0) + 1:04d}"

    def attempts(self) -> list[dict[str, Any]]:
        """Include failed attempts in resource accounting, without re-running them."""
        return [self._read_attempt(path) for path in sorted(self.root.glob("cases/*/*/attempt-*/result.json"))]

    def unfinished_attempts(self) -> int:
        """A killed process may have consumed tokens without emitting a result."""
        return sum(not (path / "result.json").exists() for path in self.root.glob("cases/*/*/attempt-*"))

    def close(self) -> None:
        self._lock.close()
