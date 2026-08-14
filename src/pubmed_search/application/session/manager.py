"""
Research session management and article cache coordination.

Session state stores research workflow context only.
Article caching is delegated to a dedicated cache collaborator that uses the
shared cache substrate, so backends can change without rewriting the
application layer.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

from pubmed_search.application.session.artifacts import ArtifactStore
from pubmed_search.shared.cache_substrate import CacheBackend, CacheStore, JsonFileCacheBackend, MemoryCacheBackend
from pubmed_search.shared.credential_sanitizer import is_credential_field, redact_credential_assignments
from pubmed_search.shared.datetime_utils import parse_iso8601_datetime
from pubmed_search.shared.file_io import atomic_write_json
from pubmed_search.shared.locking import synchronized

logger = logging.getLogger(__name__)
MAX_SESSION_EVENT_LOG = 200
_SAFE_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
SEARCH_RUN_SCHEMA_VERSION = "search-run/v1"
SEARCH_RUN_ACTIVE_STATUSES = frozenset({"started", "planned", "running"})
SEARCH_RUN_TERMINAL_STATUSES = frozenset({"completed", "partial", "failed", "cancelled", "interrupted"})
SEARCH_RUN_STATUSES = SEARCH_RUN_ACTIVE_STATUSES | SEARCH_RUN_TERMINAL_STATUSES
SOURCE_ATTEMPT_STATUSES = frozenset(
    {
        "pending",
        "running",
        "ok",
        "completed",
        "empty",
        "partial",
        "error",
        "failed",
        "timeout",
        "rate_limited",
        "skipped",
        "disabled",
        "not_requested",
        "cancelled",
    }
)
_UNIFIED_REPLAY_KEYS = frozenset(
    {
        "query",
        "limit",
        "sources",
        "ranking",
        "output_format",
        "filters",
        "options",
        "pipeline",
        "dry_run",
        "stop_at",
    }
)


def _utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _redact_persisted_text(value: str) -> str:
    return redact_credential_assignments(value)


def _sanitize_persisted_value(value: Any) -> Any:
    """Deep-copy JSON-like values while removing credential-bearing fields."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if is_credential_field(str(key)) else _sanitize_persisted_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_persisted_value(item) for item in value]
    if isinstance(value, str):
        return _redact_persisted_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return copy.deepcopy(value)
    return str(value)


def _sanitize_failure_message(message: str) -> str:
    return _redact_persisted_text(message)[:2_000]


def _artifact_locator(manifest: dict[str, Any]) -> dict[str, Any]:
    """Project a durable, host-independent locator into a search-run record."""
    raw_files = manifest.get("files")
    files: dict[str, Any] = {}
    if isinstance(raw_files, dict):
        for name, info in raw_files.items():
            if isinstance(info, dict):
                files[str(name)] = {
                    key: copy.deepcopy(info.get(key)) for key in ("size_bytes", "sha256") if info.get(key) is not None
                }
    return {
        "artifact_id": str(manifest.get("artifact_id") or ""),
        "artifact_uri": str(manifest.get("artifact_uri") or ""),
        "tool": str(manifest.get("tool") or ""),
        "kind": str(manifest.get("kind") or ""),
        "primary_file": str(manifest.get("primary_file") or ""),
        "sha256": str(manifest.get("sha256") or ""),
        "files": files,
    }


@dataclass
class CachedArticle:
    """Cached article data."""

    pmid: str
    title: str
    authors: list[str]
    abstract: str
    journal: str
    year: str
    doi: str = ""
    pmc_id: str = ""
    cached_at: str = field(default_factory=_utcnow_iso)
    full_data: dict[str, Any] = field(default_factory=dict)

    def is_expired(self, max_age_days: int = 7) -> bool:
        """Check if cache entry is expired."""
        cached_time = parse_iso8601_datetime(self.cached_at)
        now = datetime.now(tz=timezone.utc)
        if cached_time.tzinfo is None:
            cached_time = cached_time.replace(tzinfo=timezone.utc)
        return now - cached_time > timedelta(days=max_age_days)

    @classmethod
    def from_article_data(cls, pmid: str, article_data: dict[str, Any]) -> CachedArticle:
        payload = copy.deepcopy(article_data)
        raw_cached_at = payload.get("cached_at")
        cached_at = raw_cached_at if isinstance(raw_cached_at, str) else _utcnow_iso()
        payload["cached_at"] = cached_at
        payload.setdefault("pmid", pmid)

        return cls(
            pmid=pmid,
            title=payload.get("title", ""),
            authors=payload.get("authors", []),
            abstract=payload.get("abstract", ""),
            journal=payload.get("journal", ""),
            year=payload.get("year", ""),
            doi=payload.get("doi", ""),
            pmc_id=payload.get("pmc_id", ""),
            cached_at=cached_at,
            full_data=payload,
        )

    def as_article_dict(self) -> dict[str, Any]:
        """Return a dict payload suitable for API/tools responses."""
        payload = copy.deepcopy(self.full_data)
        payload.setdefault("pmid", self.pmid)
        payload.setdefault("title", self.title)
        payload.setdefault("authors", list(self.authors))
        payload.setdefault("abstract", self.abstract)
        payload.setdefault("journal", self.journal)
        payload.setdefault("year", self.year)
        payload.setdefault("doi", self.doi)
        payload.setdefault("pmc_id", self.pmc_id)
        payload["cached_at"] = self.cached_at
        return payload


@dataclass
class SearchRecord:
    """Record of a search query."""

    query: str
    timestamp: str
    result_count: int
    pmids: list[str]
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchRun:
    """Durable lifecycle envelope for one ``unified_search`` invocation.

    The compact envelope complements result artifacts: it stays cheap to list
    while preserving enough request, plan, source-attempt, and result metadata
    for an agent to explain, resume, or explicitly replay a run.
    """

    run_id: str
    query: str
    status: str
    request: dict[str, Any]
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)
    schema_version: str = SEARCH_RUN_SCHEMA_VERSION
    plan: dict[str, Any] = field(default_factory=dict)
    source_attempts: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    artifact: dict[str, Any] | None = None
    failure: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    replay_of: str | None = None
    recoverable: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Return a detached, JSON-safe representation."""
        return _sanitize_persisted_value(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SearchRun:
        """Read current or older run dictionaries without accepting unknown state."""
        status = str(payload.get("status") or "interrupted")
        if status not in SEARCH_RUN_STATUSES:
            status = "interrupted"
        raw_request = payload.get("request")
        raw_plan = payload.get("plan")
        raw_attempts = payload.get("source_attempts")
        raw_result = payload.get("result")
        return cls(
            run_id=str(payload.get("run_id") or ""),
            query=str(payload.get("query") or ""),
            status=status,
            request=dict(raw_request) if isinstance(raw_request, dict) else {},
            created_at=str(payload.get("created_at") or _utcnow_iso()),
            updated_at=str(payload.get("updated_at") or payload.get("created_at") or _utcnow_iso()),
            schema_version=str(payload.get("schema_version") or SEARCH_RUN_SCHEMA_VERSION),
            plan=dict(raw_plan) if isinstance(raw_plan, dict) else {},
            source_attempts=[dict(item) for item in raw_attempts if isinstance(item, dict)]
            if isinstance(raw_attempts, list)
            else [],
            result=dict(raw_result) if isinstance(raw_result, dict) else {},
            artifact=dict(payload["artifact"]) if isinstance(payload.get("artifact"), dict) else None,
            failure=dict(payload["failure"]) if isinstance(payload.get("failure"), dict) else None,
            warnings=[str(item) for item in list(payload.get("warnings") or [])],
            replay_of=str(payload["replay_of"]) if payload.get("replay_of") else None,
            recoverable=bool(payload.get("recoverable", True)),
        )


@dataclass
class ResearchSession:
    """Aggregate root for research workflow state."""

    session_id: str
    topic: str = ""
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)

    # Compatibility snapshot only. The authoritative cache lives in ArticleCache.
    article_cache: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)

    # Session-owned references to cached articles. The payloads live in ArticleCache.
    cached_pmids: list[str] = field(default_factory=list)

    search_history: list[dict[str, Any]] = field(default_factory=list)
    search_runs: list[dict[str, Any]] = field(default_factory=list)
    event_log: list[dict[str, Any]] = field(default_factory=list)
    reading_list: dict[str, dict[str, Any]] = field(default_factory=dict)
    excluded_pmids: list[str] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    def touch(self) -> None:
        """Update the last modified timestamp."""
        self.updated_at = _utcnow_iso()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchSession:
        payload = dict(data)
        payload.setdefault("article_cache", {})
        payload.setdefault("event_log", [])
        payload.setdefault("artifacts", [])
        raw_search_runs = payload.get("search_runs")
        payload["search_runs"] = (
            [
                SearchRun.from_dict(item).to_dict()
                for item in raw_search_runs
                if isinstance(item, dict) and _SAFE_SESSION_ID_RE.fullmatch(str(item.get("run_id") or ""))
            ]
            if isinstance(raw_search_runs, list)
            else []
        )
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        """Serialize session state without persisting cache payloads."""
        payload = asdict(self)
        payload.pop("article_cache", None)
        return payload


class ArticleCache:
    """Article cache wrapper using the shared cache substrate."""

    def __init__(
        self,
        cache_dir: str | None = None,
        max_age_days: int = 7,
        backend: CacheBackend | None = None,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.max_age_days = max_age_days

        if backend is None:
            if self.cache_dir:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                backend = JsonFileCacheBackend(self.cache_dir / "article_cache.json")
            else:
                backend = MemoryCacheBackend()

        self._store = CacheStore[CachedArticle](
            backend,
            default_ttl=max_age_days * 86400.0,
            key_normalizer=lambda value: value.strip(),
            serializer=asdict,
            deserializer=self._deserialize_cached_article,
            name="article-cache",
        )

    @staticmethod
    def _deserialize_cached_article(raw: Any) -> CachedArticle:
        if isinstance(raw, CachedArticle):
            return raw
        if not isinstance(raw, dict):
            raise TypeError("Article cache payload must be a dict")
        try:
            return CachedArticle(**raw)
        except TypeError:
            pmid = str(raw.get("pmid") or "")
            return CachedArticle.from_article_data(pmid, raw)

    def get(self, pmid: str) -> CachedArticle | None:
        return self._store.get(pmid)

    def get_many(self, pmids: list[str]) -> tuple[dict[str, CachedArticle], list[str]]:
        return self._store.get_many(pmids)

    def put(self, pmid: str, article_data: dict[str, Any]) -> None:
        self._store.set(pmid, CachedArticle.from_article_data(pmid, article_data))

    def put_many(self, articles: list[dict[str, Any]]) -> int:
        entries: list[tuple[str, CachedArticle]] = []
        for article in articles:
            pmid = article.get("pmid", "")
            if pmid:
                entries.append((pmid, CachedArticle.from_article_data(pmid, article)))

        return self._store.warmup(entries)

    def warmup(self, articles: dict[str, dict[str, Any]] | list[dict[str, Any]]) -> int:
        if isinstance(articles, dict):
            payloads = []
            for pmid, article in articles.items():
                payload = dict(article)
                payload.setdefault("pmid", pmid)
                payloads.append(payload)
            return self.put_many(payloads)

        return self.put_many(articles)

    def invalidate(self, pmid: str) -> bool:
        return self._store.invalidate(pmid)

    def clear(self) -> int:
        return self._store.clear()

    def cleanup_expired(self) -> int:
        return self._store.cleanup_expired()

    def stats(self) -> dict[str, Any]:
        snapshot = self._store.snapshot()
        return {
            "total_cached": len(self._store),
            "valid": len(self._store),
            "expired": snapshot["expirations"],
            "cache_dir": str(self.cache_dir) if self.cache_dir else "memory_only",
            **snapshot,
        }

    def __contains__(self, pmid: str) -> bool:
        return pmid in self._store

    def __len__(self) -> int:
        return len(self._store)


class SessionManager:
    """Manage research sessions and coordinate the shared article cache."""

    def __init__(self, data_dir: str | None = None, article_cache: ArticleCache | None = None):
        self._lock = threading.RLock()
        self.data_dir = Path(data_dir) if data_dir else None
        self.article_cache = article_cache or ArticleCache(cache_dir=str(self.data_dir) if self.data_dir else None)
        self.artifact_store = ArtifactStore(self.data_dir / "artifacts") if self.data_dir else None
        self._sessions: dict[str, ResearchSession] = {}
        self._current_session_id: str | None = None

        if self.data_dir:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self._load_sessions()

    def _get_sessions_file(self) -> Path:
        if self.data_dir is None:
            raise RuntimeError("data_dir not configured")
        return self.data_dir / "sessions.json"

    def _get_session_file(self, session_id: str) -> Path:
        if self.data_dir is None:
            raise RuntimeError("data_dir not configured")
        if not _SAFE_SESSION_ID_RE.fullmatch(session_id):
            msg = f"Unsafe session id: {session_id}"
            raise ValueError(msg)
        path = (self.data_dir / f"session_{session_id}.json").resolve()
        try:
            path.relative_to(self.data_dir.resolve())
        except ValueError as exc:
            msg = f"Session path escapes data directory: {path}"
            raise ValueError(msg) from exc
        return path

    def _load_sessions(self) -> None:
        sessions_file = self._get_sessions_file()
        index: dict[str, Any] = {}
        index_needs_repair = not sessions_file.exists()
        if sessions_file.exists():
            try:
                with sessions_file.open(encoding="utf-8") as handle:
                    loaded_index = json.load(handle)
                if isinstance(loaded_index, dict):
                    index = loaded_index
                else:
                    index_needs_repair = True
            except Exception as exc:
                logger.warning("Failed to load sessions index; scanning session files: %s", exc)
                index_needs_repair = True

        candidate_ids: list[str] = []
        raw_index_ids = index.get("sessions", [])
        if isinstance(raw_index_ids, list):
            candidate_ids.extend(str(item) for item in raw_index_ids)
        for session_file in sorted(self.data_dir.glob("session_*.json") if self.data_dir else []):
            candidate = session_file.stem.removeprefix("session_")
            if candidate not in candidate_ids:
                candidate_ids.append(candidate)
                index_needs_repair = True

        requested_current = index.get("current_session_id")
        self._current_session_id = str(requested_current) if requested_current else None
        recovered_state = False
        for session_id in candidate_ids:
            recovered_state = self._load_session(session_id) or recovered_state

        if self._current_session_id not in self._sessions:
            self._current_session_id = max(
                self._sessions,
                key=lambda item: self._sessions[item].updated_at,
                default=None,
            )
            index_needs_repair = bool(self._sessions) or index_needs_repair

        if (index_needs_repair or recovered_state) and (self._sessions or sessions_file.exists()):
            self._save_sessions_index()
        logger.info("Loaded %s sessions", len(self._sessions))

    def _load_session(self, session_id: str) -> bool:
        """Load one session and return whether recovery changed durable state."""
        try:
            session_file = self._get_session_file(session_id)
        except ValueError as exc:
            logger.warning("Skipping unsafe session id %s: %s", session_id, exc)
            return False
        if not session_file.exists():
            return False

        try:
            with session_file.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:
            logger.warning("Failed to load session %s: %s", session_id, exc)
            return False

        legacy_cache = payload.pop("article_cache", {}) if isinstance(payload, dict) else {}
        if not isinstance(payload, dict):
            logger.warning("Skipping malformed session payload for %s", session_id)
            return False

        try:
            session = ResearchSession.from_dict(payload)
        except (TypeError, ValueError) as exc:
            logger.warning("Skipping malformed session payload for %s: %s", session_id, exc)
            return False
        if session.session_id != session_id:
            logger.warning("Skipping session payload whose id does not match its filename: %s", session_id)
            return False
        self._sessions[session_id] = session

        changed = False
        if isinstance(legacy_cache, dict) and legacy_cache:
            self.article_cache.warmup(legacy_cache)
            self._refresh_session_cache_view(session)
            changed = True
        else:
            self._refresh_session_cache_view(session)

        changed = self._recover_interrupted_search_runs(session) or changed
        changed = self._reconcile_session_artifacts(session) or changed
        if changed:
            # Do not rewrite the sessions index inside the load loop: doing so
            # could temporarily publish a partial index before all sessions are
            # loaded.  The caller repairs the index after the loop.
            atomic_write_json(session_file, session.to_dict())
        return changed

    def _save_session(self, session: ResearchSession) -> None:
        if not self.data_dir:
            return

        session_file = self._get_session_file(session.session_id)
        try:
            atomic_write_json(session_file, session.to_dict())
        except Exception as exc:
            logger.warning("Failed to save session: %s", exc)
            raise

        self._save_sessions_index()

    def _save_sessions_index(self) -> None:
        if not self.data_dir:
            return

        sessions_file = self._get_sessions_file()
        index = {
            "current_session_id": self._current_session_id,
            "sessions": list(self._sessions.keys()),
        }
        try:
            atomic_write_json(sessions_file, index)
        except Exception as exc:
            logger.warning("Failed to save sessions index: %s", exc)
            raise

    @staticmethod
    def _find_search_run(session: ResearchSession, run_id: str) -> dict[str, Any] | None:
        for run in session.search_runs:
            if isinstance(run, dict) and run.get("run_id") == run_id:
                return run
        return None

    @staticmethod
    def _legacy_run_id(session: ResearchSession, index: int, record: dict[str, Any]) -> str:
        identity = json.dumps(
            {
                "session_id": session.session_id,
                "index": index,
                "query": record.get("query", ""),
                "timestamp": record.get("timestamp", ""),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        return f"legacy-{digest}"

    def _legacy_search_runs(self, session: ResearchSession) -> list[dict[str, Any]]:
        """Project pre-journal search history into stable read-only run envelopes."""
        journal_ids = {
            str(run.get("run_id")) for run in session.search_runs if isinstance(run, dict) and run.get("run_id")
        }
        runs: list[dict[str, Any]] = []
        for index, record in enumerate(session.search_history):
            if not isinstance(record, dict):
                continue
            # A run id means this history row already has a first-class
            # journal record and must not be projected a second time.
            if record.get("run_id") in journal_ids:
                continue
            timestamp = str(record.get("timestamp") or "")
            query = str(record.get("query") or "")
            filters = dict(record.get("filters") or {})
            pmids = [str(item) for item in list(record.get("pmids") or []) if item]
            legacy_run_id = str(record.get("run_id") or "")
            if not _SAFE_SESSION_ID_RE.fullmatch(legacy_run_id):
                legacy_run_id = self._legacy_run_id(session, index, record)
            runs.append(
                SearchRun(
                    run_id=legacy_run_id,
                    query=query,
                    status="completed",
                    request={"query": query, "filters": filters},
                    created_at=timestamp or session.created_at,
                    updated_at=timestamp or session.updated_at,
                    result={
                        "count": int(record.get("result_count", len(pmids)) or 0),
                        "pmids": pmids,
                        "references": [],
                    },
                    recoverable=True,
                ).to_dict()
            )
        return runs

    def _recover_interrupted_search_runs(self, session: ResearchSession) -> bool:
        changed = False
        now = _utcnow_iso()
        for run in session.search_runs:
            if not isinstance(run, dict) or run.get("status") not in SEARCH_RUN_ACTIVE_STATUSES:
                continue
            run["status"] = "interrupted"
            run["updated_at"] = now
            run["recoverable"] = True
            run["failure"] = {
                "stage": "recovery",
                "type": "InterruptedSearchRun",
                "message": "The server stopped before this search reached a terminal state.",
                "retryable": True,
            }
            self._append_session_event(
                session,
                kind="search_run_interrupted",
                level="warning",
                message="Recovered an interrupted search run",
                details={"run_id": run.get("run_id"), "previous_status": "in_progress"},
            )
            changed = True
        if changed:
            session.touch()
        return changed

    @staticmethod
    def _resolve_artifact_search_run_id(
        session: ResearchSession,
        *,
        tool: str,
        summary: dict[str, Any] | None,
        metadata: dict[str, Any] | None,
    ) -> str | None:
        if tool != "unified_search":
            return None
        for payload in (metadata, summary):
            if isinstance(payload, dict) and payload.get("search_run_id"):
                return str(payload["search_run_id"])
        query = str((summary or {}).get("query") or "")
        if not query:
            return None
        for run in reversed(session.search_runs):
            if not isinstance(run, dict) or run.get("artifact"):
                continue
            if str(run.get("query") or "") == query:
                return str(run.get("run_id") or "") or None
        return None

    def _link_artifact_to_run(self, session: ResearchSession, manifest: dict[str, Any]) -> bool:
        metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
        summary = manifest.get("summary") if isinstance(manifest.get("summary"), dict) else {}
        run_id = self._resolve_artifact_search_run_id(
            session,
            tool=str(manifest.get("tool") or ""),
            summary=summary,
            metadata=metadata,
        )
        if not run_id:
            return False
        run = self._find_search_run(session, run_id)
        if run is None:
            return False
        locator = _artifact_locator(manifest)
        if run.get("artifact") == locator:
            return False
        run["artifact"] = locator
        run["updated_at"] = _utcnow_iso()
        return True

    def _reconcile_session_artifacts(self, session: ResearchSession) -> bool:
        """Index published-but-unreferenced artifacts after an interrupted save."""
        if self.artifact_store is None:
            return False
        try:
            discovered = self.artifact_store.discover(session_id=session.session_id)
        except (OSError, ValueError) as exc:
            logger.warning("Artifact recovery failed for session %s: %s", session.session_id, type(exc).__name__)
            return False
        known_ids = {
            str(item.get("artifact_id"))
            for item in session.artifacts
            if isinstance(item, dict) and item.get("artifact_id")
        }
        changed = False
        recovered_ids: list[str] = []
        for manifest in discovered:
            artifact_id = str(manifest.get("artifact_id") or "")
            if artifact_id and artifact_id not in known_ids:
                session.artifacts.append(copy.deepcopy(manifest))
                known_ids.add(artifact_id)
                recovered_ids.append(artifact_id)
                changed = True
            changed = self._link_artifact_to_run(session, manifest) or changed
        if recovered_ids:
            self._append_session_event(
                session,
                kind="artifacts_recovered",
                level="warning",
                message="Recovered published artifacts that were missing from the session index",
                details={"artifact_ids": recovered_ids},
            )
        if changed:
            session.touch()
        return changed

    def _session_related_pmids(self, session: ResearchSession) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()

        def add(pmid: str) -> None:
            if pmid and pmid not in seen:
                seen.add(pmid)
                ordered.append(pmid)

        for pmid in session.cached_pmids:
            add(pmid)

        for record in session.search_history:
            for pmid in record.get("pmids", []):
                add(pmid)

        for pmid in session.reading_list:
            add(pmid)

        for pmid in session.excluded_pmids:
            add(pmid)

        for pmid in session.notes:
            add(pmid)

        return ordered

    def _refresh_session_cache_view(self, session: ResearchSession) -> ResearchSession:
        cached_map, _ = self.get_cached_article_map(self._session_related_pmids(session))
        session.article_cache = cached_map
        return session

    @staticmethod
    def _append_session_event(
        session: ResearchSession,
        *,
        kind: str,
        message: str,
        details: dict[str, Any] | None = None,
        level: str = "info",
    ) -> None:
        """Append one bounded session event for user-visible history and debugging."""
        session.event_log.append(
            {
                "timestamp": _utcnow_iso(),
                "kind": kind,
                "level": level,
                "message": message,
                "details": copy.deepcopy(details) if details else {},
            }
        )
        overflow = len(session.event_log) - MAX_SESSION_EVENT_LOG
        if overflow > 0:
            del session.event_log[:overflow]

    @staticmethod
    def _record_cached_pmids(session: ResearchSession, pmids: Iterable[str]) -> None:
        seen = set(session.cached_pmids)
        for pmid in pmids:
            if pmid and pmid not in seen:
                seen.add(pmid)
                session.cached_pmids.append(pmid)

    def _create_session(self, topic: str = "") -> ResearchSession:
        session_id = hashlib.md5(  # nosec B324
            f"{topic}{_utcnow_iso()}".encode(),
            usedforsecurity=False,
        ).hexdigest()[:12]
        session = ResearchSession(session_id=session_id, topic=topic)
        self._append_session_event(
            session,
            kind="session_created",
            message="Session created",
            details={"session_id": session_id, "topic": topic},
        )
        self._sessions[session_id] = session
        self._current_session_id = session_id
        self._save_session(session)
        logger.info("Created session %s: %s", session_id, topic)
        return self._refresh_session_cache_view(session)

    def _current_session(self) -> ResearchSession | None:
        if not self._current_session_id:
            return None
        session = self._sessions.get(self._current_session_id)
        if session is None:
            return None
        return self._refresh_session_cache_view(session)

    def _get_or_create_session(self, topic: str = "default") -> ResearchSession:
        session = self._current_session()
        return session if session is not None else self._create_session(topic)

    def _snapshot_session(self, session: ResearchSession | None) -> ResearchSession | None:
        """Detach a coherent query result from mutable manager-owned state."""
        return copy.deepcopy(session) if session is not None else None

    @synchronized
    def create_session(self, topic: str = "") -> ResearchSession:
        return copy.deepcopy(self._create_session(topic))

    @synchronized
    def get_current_session(self) -> ResearchSession | None:
        return self._snapshot_session(self._current_session())

    @synchronized
    def get_session(self, session_id: str) -> ResearchSession | None:
        """Return a persisted session by id without switching the active session."""
        return self._snapshot_session(self._get_session_for_artifact_lookup(session_id))

    @synchronized
    def get_or_create_session(self, topic: str = "default") -> ResearchSession:
        return copy.deepcopy(self._get_or_create_session(topic))

    @synchronized
    def switch_session(self, session_id: str) -> ResearchSession | None:
        if session_id not in self._sessions:
            return None
        self._current_session_id = session_id
        session = self._sessions[session_id]
        self._append_session_event(
            session,
            kind="session_switched",
            message="Session activated",
            details={"session_id": session_id},
        )
        session.touch()
        self._refresh_session_cache_view(session)
        self._save_session(session)
        return self._snapshot_session(session)

    @synchronized
    def list_sessions(self) -> list[dict[str, Any]]:
        return [
            {
                "session_id": session.session_id,
                "topic": session.topic,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "article_count": len(self.get_session_cached_pmids(session=session)),
                "search_count": len(session.search_history),
                "is_current": session.session_id == self._current_session_id,
            }
            for session in self._sessions.values()
        ]

    @synchronized
    def warm_article_cache(self, articles: list[dict[str, Any]]) -> int:
        warmed = self.article_cache.put_many(articles)
        session = self._current_session()
        if session:
            self._record_cached_pmids(session, [article.get("pmid", "") for article in articles])
            if warmed:
                self._append_session_event(
                    session,
                    kind="cache_warmed",
                    message="Session cache warmed with article payloads",
                    details={
                        "article_count": warmed,
                        "pmids": [article.get("pmid", "") for article in articles[:10] if article.get("pmid")],
                    },
                )
            self._refresh_session_cache_view(session)
            self._save_session(session)
        return warmed

    @synchronized
    def add_to_cache(self, articles: list[dict[str, Any]], *, _skip_save: bool = False) -> int:
        warmed = self.article_cache.put_many(articles)
        session = self._current_session()
        if session:
            self._record_cached_pmids(session, [article.get("pmid", "") for article in articles])
            if warmed:
                self._append_session_event(
                    session,
                    kind="cache_updated",
                    message="Cached article payloads added to the active session",
                    details={
                        "article_count": warmed,
                        "pmids": [article.get("pmid", "") for article in articles[:10] if article.get("pmid")],
                    },
                )
        if session and not _skip_save:
            self._refresh_session_cache_view(session)
            self._save_session(session)
        elif session:
            self._refresh_session_cache_view(session)
        return warmed

    @synchronized
    def get_cached_article(self, pmid: str) -> dict[str, Any] | None:
        cached = self.article_cache.get(pmid)
        if cached is None:
            return None
        return cached.as_article_dict()

    @synchronized
    def get_cached_article_map(self, pmids: Iterable[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
        pmid_list = [pmid for pmid in pmids if pmid]
        cached, missing = self.article_cache.get_many(pmid_list)
        return ({pmid: article.as_article_dict() for pmid, article in cached.items()}, missing)

    @synchronized
    def get_from_cache(self, pmids: str | list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        pmid_list = [pmids] if isinstance(pmids, str) else pmids
        cached_map, missing = self.get_cached_article_map(pmid_list)
        ordered = [cached_map[pmid] for pmid in pmid_list if pmid in cached_map]
        return ordered, missing

    @synchronized
    def get_session_cached_pmids(
        self,
        *,
        session: ResearchSession | None = None,
        limit: int | None = None,
    ) -> list[str]:
        active_session = session or self._current_session()
        if active_session is None:
            return []

        cached_pmids = [pmid for pmid in self._session_related_pmids(active_session) if pmid in self.article_cache]
        return cached_pmids[:limit] if limit is not None else cached_pmids

    @synchronized
    def is_searched(self, pmid: str) -> bool:
        session = self._current_session()
        if session is None:
            return False
        return pmid in self._session_related_pmids(session)

    @staticmethod
    def _replay_request(query: str, request: dict[str, Any] | None) -> dict[str, Any]:
        raw = dict(request or {})
        raw.setdefault("query", query)
        return {
            key: _sanitize_persisted_value(raw[key])
            for key in _UNIFIED_REPLAY_KEYS
            if key in raw and raw[key] is not None
        }

    @staticmethod
    def _failure_payload(
        error: str | BaseException | dict[str, Any],
        *,
        stage: str,
        retryable: bool,
    ) -> dict[str, Any]:
        if isinstance(error, dict):
            payload = _sanitize_persisted_value(error)
            if not isinstance(payload, dict):
                payload = {"message": str(payload)}
            message = _sanitize_failure_message(str(payload.get("message") or "Search failed"))
            error_type = str(payload.get("type") or "SearchFailure")
            safe_stage = str(payload.get("stage") or stage)
        elif isinstance(error, BaseException):
            message = _sanitize_failure_message(str(error) or type(error).__name__)
            error_type = type(error).__name__
            safe_stage = stage
        else:
            message = _sanitize_failure_message(str(error))
            error_type = "SearchFailure"
            safe_stage = stage
        return {
            "stage": safe_stage[:80],
            "type": error_type[:120],
            "message": message,
            "retryable": bool(retryable),
        }

    def _persist_run_change(self, session: ResearchSession, before: ResearchSession) -> None:
        session.touch()
        try:
            self._save_session(session)
        except BaseException:
            # A failed durability boundary must not make an in-memory caller
            # believe state was committed.  If the session file was replaced
            # just before an index failure, restart recovery still sees it.
            self._sessions[session.session_id] = before
            raise

    @synchronized
    def start_search_run(
        self,
        query: str,
        *,
        request: dict[str, Any] | None = None,
        replay_of: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Create and durably publish a search-run envelope before planning."""
        session = self._get_or_create_session()
        before = copy.deepcopy(session)
        resolved_run_id = run_id or uuid.uuid4().hex
        if not _SAFE_SESSION_ID_RE.fullmatch(resolved_run_id):
            msg = f"Unsafe search run id: {resolved_run_id}"
            raise ValueError(msg)
        if self._find_search_run(session, resolved_run_id) is not None:
            msg = f"Search run already exists: {resolved_run_id}"
            raise ValueError(msg)

        replay_request = self._replay_request(query, request)
        run = SearchRun(
            run_id=resolved_run_id,
            query=query,
            status="started",
            request=replay_request,
            replay_of=replay_of,
            recoverable=True,
        ).to_dict()
        session.search_runs.append(run)
        self._append_session_event(
            session,
            kind="search_run_started",
            message="Search run started",
            details={"run_id": resolved_run_id, "replay_of": replay_of},
        )
        self._persist_run_change(session, before)
        return copy.deepcopy(run)

    @synchronized
    def plan_search_run(
        self,
        run_id: str,
        *,
        plan: dict[str, Any],
        sources: list[str] | None = None,
    ) -> dict[str, Any]:
        """Persist the normalized execution plan before provider I/O begins."""
        session = self._get_or_create_session()
        before = copy.deepcopy(session)
        run = self._find_search_run(session, run_id)
        if run is None:
            raise KeyError(f"Search run not found: {run_id}")
        if run.get("status") in SEARCH_RUN_TERMINAL_STATUSES:
            raise ValueError(f"Cannot plan terminal search run: {run_id}")
        normalized_plan = _sanitize_persisted_value(plan)
        if not isinstance(normalized_plan, dict):
            raise TypeError("Search run plan must be a dictionary")
        if sources is not None:
            normalized_plan["sources"] = [str(source) for source in sources]
        run["plan"] = normalized_plan
        run["status"] = "planned"
        run["updated_at"] = _utcnow_iso()
        self._append_session_event(
            session,
            kind="search_run_planned",
            message="Search run plan persisted",
            details={"run_id": run_id, "sources": normalized_plan.get("sources", [])},
        )
        self._persist_run_change(session, before)
        return copy.deepcopy(run)

    @synchronized
    def record_search_source_attempt(
        self,
        run_id: str,
        source: str,
        status: str,
        *,
        logical_query: str | None = None,
        physical_query: str | None = None,
        returned: int | None = None,
        available: int | None = None,
        metadata: dict[str, Any] | None = None,
        error: str | BaseException | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append or finish one structured provider attempt for a search run."""
        normalized_status = status.strip().lower()
        if normalized_status not in SOURCE_ATTEMPT_STATUSES:
            raise ValueError(f"Unsupported source attempt status: {status}")
        session = self._get_or_create_session()
        before = copy.deepcopy(session)
        run = self._find_search_run(session, run_id)
        if run is None:
            raise KeyError(f"Search run not found: {run_id}")
        if run.get("status") in SEARCH_RUN_TERMINAL_STATUSES:
            raise ValueError(f"Cannot update terminal search run: {run_id}")

        attempts = run.setdefault("source_attempts", [])
        if not isinstance(attempts, list):
            attempts = []
            run["source_attempts"] = attempts
        open_attempt = next(
            (
                attempt
                for attempt in reversed(attempts)
                if isinstance(attempt, dict)
                and attempt.get("source") == source
                and attempt.get("status") in {"pending", "running"}
            ),
            None,
        )
        now = _utcnow_iso()
        if open_attempt is None:
            attempt_no = 1 + sum(
                1 for attempt in attempts if isinstance(attempt, dict) and attempt.get("source") == source
            )
            open_attempt = {
                "source": source,
                "attempt": attempt_no,
                "started_at": now,
            }
            attempts.append(open_attempt)
        open_attempt.update(
            {
                "status": normalized_status,
                "updated_at": now,
                "logical_query": _redact_persisted_text(logical_query) if logical_query is not None else None,
                "physical_query": _redact_persisted_text(physical_query) if physical_query is not None else None,
                "returned": int(returned) if returned is not None else None,
                "available": int(available) if available is not None else None,
                "metadata": _sanitize_persisted_value(metadata or {}),
            }
        )
        if normalized_status not in {"pending", "running"}:
            open_attempt["completed_at"] = now
        if error is not None:
            open_attempt["failure"] = self._failure_payload(
                error,
                stage=f"source:{source}",
                retryable=normalized_status in {"error", "failed", "partial", "timeout", "rate_limited"},
            )
        run["status"] = "running"
        run["updated_at"] = now
        self._append_session_event(
            session,
            kind="search_source_attempt",
            level=(
                "warning" if normalized_status in {"error", "failed", "partial", "timeout", "rate_limited"} else "info"
            ),
            message="Search source attempt updated",
            details={"run_id": run_id, "source": source, "status": normalized_status},
        )
        self._persist_run_change(session, before)
        return copy.deepcopy(run)

    @synchronized
    def attach_search_run_artifact(self, run_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
        """Attach a verified artifact locator without reopening the run status."""
        session = self._get_or_create_session()
        before = copy.deepcopy(session)
        run = self._find_search_run(session, run_id)
        if run is None:
            raise KeyError(f"Search run not found: {run_id}")
        run["artifact"] = _artifact_locator(manifest)
        run["updated_at"] = _utcnow_iso()
        self._append_session_event(
            session,
            kind="search_run_artifact_attached",
            message="Search artifact linked to search run",
            details={"run_id": run_id, "artifact_id": manifest.get("artifact_id")},
        )
        self._persist_run_change(session, before)
        return copy.deepcopy(run)

    @synchronized
    def complete_search_run(
        self,
        run_id: str,
        *,
        pmids: list[str],
        result_count: int | None = None,
        result_refs: list[dict[str, Any]] | None = None,
        artifact: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        status: str = "completed",
        failure: str | BaseException | dict[str, Any] | None = None,
        retryable: bool = True,
    ) -> dict[str, Any]:
        """Commit terminal result metadata and its legacy history projection."""
        normalized_status = status.strip().lower()
        if normalized_status not in {"completed", "partial", "failed", "cancelled"}:
            raise ValueError(f"Unsupported completion status: {status}")
        session = self._get_or_create_session()
        before = copy.deepcopy(session)
        run = self._find_search_run(session, run_id)
        if run is None:
            raise KeyError(f"Search run not found: {run_id}")
        if run.get("status") in SEARCH_RUN_TERMINAL_STATUSES:
            raise ValueError(f"Search run is already terminal: {run_id}")

        recorded_pmids = [str(pmid) for pmid in pmids if pmid]
        references = _sanitize_persisted_value(result_refs or [])
        run["result"] = {
            "count": int(result_count) if result_count is not None else len(recorded_pmids),
            "pmids": recorded_pmids,
            "references": references if isinstance(references, list) else [],
        }
        run["warnings"] = [_sanitize_failure_message(str(item)) for item in list(warnings or [])]
        if artifact is not None:
            candidate_locator = _artifact_locator(artifact)
            existing_locator = run.get("artifact") if isinstance(run.get("artifact"), dict) else None
            same_persisted_artifact = bool(
                existing_locator
                and (
                    (
                        candidate_locator.get("artifact_id")
                        and existing_locator.get("artifact_id") == candidate_locator.get("artifact_id")
                    )
                    or (
                        candidate_locator.get("artifact_uri")
                        and existing_locator.get("artifact_uri") == candidate_locator.get("artifact_uri")
                    )
                )
            )
            # ``persist_tool_artifact`` intentionally returns a public compact
            # locator whose ``files`` value is a list.  ``save_artifact`` has
            # already linked the checksum-bearing manifest to this run; never
            # replace that durable locator with the less complete projection.
            if not same_persisted_artifact:
                run["artifact"] = candidate_locator
        run["status"] = normalized_status
        run["failure"] = (
            self._failure_payload(
                failure or "All selected search sources failed",
                stage="execution",
                retryable=retryable,
            )
            if normalized_status == "failed"
            else None
        )
        run["recoverable"] = normalized_status != "completed"
        run["updated_at"] = _utcnow_iso()

        history_row = next(
            (row for row in session.search_history if isinstance(row, dict) and row.get("run_id") == run_id),
            None,
        )
        if history_row is None:
            filters = run.get("request", {}).get("filters", {}) if isinstance(run.get("request"), dict) else {}
            session.search_history.append(
                {
                    "run_id": run_id,
                    "query": str(run.get("query") or ""),
                    "timestamp": run["updated_at"],
                    "result_count": run["result"]["count"],
                    "pmids": recorded_pmids,
                    "filters": copy.deepcopy(filters) if isinstance(filters, dict) else {},
                    "status": normalized_status,
                }
            )
        self._record_cached_pmids(session, recorded_pmids)
        self._append_session_event(
            session,
            kind="search_run_completed",
            level="error"
            if normalized_status == "failed"
            else "warning"
            if normalized_status != "completed"
            else "info",
            message="Search run reached a terminal result state",
            details={"run_id": run_id, "status": normalized_status, "result_count": run["result"]["count"]},
        )
        self._refresh_session_cache_view(session)
        self._persist_run_change(session, before)
        return copy.deepcopy(run)

    @synchronized
    def fail_search_run(
        self,
        run_id: str,
        error: str | BaseException | dict[str, Any],
        *,
        stage: str = "execution",
        retryable: bool = True,
    ) -> dict[str, Any]:
        """Commit a sanitized terminal failure while retaining replay inputs."""
        session = self._get_or_create_session()
        before = copy.deepcopy(session)
        run = self._find_search_run(session, run_id)
        if run is None:
            raise KeyError(f"Search run not found: {run_id}")
        if run.get("status") in SEARCH_RUN_TERMINAL_STATUSES:
            raise ValueError(f"Search run is already terminal: {run_id}")
        failure = self._failure_payload(error, stage=stage, retryable=retryable)
        run["status"] = "failed"
        run["failure"] = failure
        run["recoverable"] = bool(retryable)
        run["updated_at"] = _utcnow_iso()
        self._append_session_event(
            session,
            kind="search_run_failed",
            level="error",
            message="Search run failed",
            details={"run_id": run_id, "stage": failure["stage"], "retryable": bool(retryable)},
        )
        self._persist_run_change(session, before)
        return copy.deepcopy(run)

    @synchronized
    def list_search_runs(
        self,
        *,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List first-class and deterministic legacy search-run envelopes."""
        session = self._get_session_for_artifact_lookup(session_id)
        if session is None or limit <= 0:
            return []
        runs = [copy.deepcopy(run) for run in session.search_runs if isinstance(run, dict)]
        runs.extend(self._legacy_search_runs(session))
        if status:
            normalized = status.strip().lower()
            runs = [run for run in runs if str(run.get("status") or "").lower() == normalized]
        runs.sort(key=lambda run: (str(run.get("created_at") or ""), str(run.get("run_id") or "")))
        return runs[-limit:]

    @synchronized
    def get_search_run(self, run_id: str, *, session_id: str | None = None) -> dict[str, Any] | None:
        """Return one detached run envelope by stable id."""
        for run in self.list_search_runs(session_id=session_id, limit=100_000):
            if run.get("run_id") == run_id:
                return run
        return None

    @synchronized
    def get_search_run_replay(self, run_id: str, *, session_id: str | None = None) -> dict[str, Any] | None:
        """Return exact, credential-free kwargs for an explicit replay."""
        run = self.get_search_run(run_id, session_id=session_id)
        if run is None:
            return None
        request = run.get("request") if isinstance(run.get("request"), dict) else {}
        arguments = self._replay_request(str(run.get("query") or ""), request)
        return {
            "tool": "unified_search",
            "arguments": arguments,
            "replay_of": run_id,
            "previous_status": run.get("status"),
        }

    @synchronized
    def add_search_record(self, query: str, pmids: list[str], filters: dict[str, Any] | None = None) -> None:
        session = self._get_or_create_session()
        before = copy.deepcopy(session)
        recorded_pmids = list(pmids)
        recorded_filters = copy.deepcopy(filters) if filters else {}
        run_id = uuid.uuid4().hex
        timestamp = _utcnow_iso()
        record = {
            "run_id": run_id,
            "query": query,
            "timestamp": timestamp,
            "result_count": len(recorded_pmids),
            "pmids": recorded_pmids,
            "filters": recorded_filters,
            "status": "completed",
        }
        session.search_history.append(record)
        session.search_runs.append(
            SearchRun(
                run_id=run_id,
                query=query,
                status="completed",
                request=self._replay_request(query, {"query": query, "filters": recorded_filters}),
                created_at=timestamp,
                updated_at=timestamp,
                result={"count": len(recorded_pmids), "pmids": recorded_pmids, "references": []},
                recoverable=False,
            ).to_dict()
        )
        self._append_session_event(
            session,
            kind="search_recorded",
            message="Recorded search query in session history",
            details={
                "query": query,
                "result_count": len(recorded_pmids),
                "pmid_count": len(recorded_pmids),
                "filters": recorded_filters,
            },
        )
        session.touch()
        self._refresh_session_cache_view(session)
        try:
            self._save_session(session)
        except BaseException:
            self._sessions[session.session_id] = before
            raise

    @synchronized
    def save_artifact(
        self,
        *,
        tool: str,
        kind: str,
        files: dict[str, Any],
        primary_file: str,
        summary: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a tool output artifact and index its manifest in the active session."""
        if self.artifact_store is None:
            msg = "Artifact persistence requires SessionManager(data_dir=...)"
            raise RuntimeError(msg)

        session = self._get_or_create_session()
        resolved_run_id = self._resolve_artifact_search_run_id(
            session,
            tool=tool,
            summary=summary,
            metadata=metadata,
        )
        persisted_metadata = copy.deepcopy(metadata) if metadata else {}
        if resolved_run_id:
            persisted_metadata["search_run_id"] = resolved_run_id
        manifest = self.artifact_store.save(
            session_id=session.session_id,
            tool=tool,
            kind=kind,
            files=files,
            primary_file=primary_file,
            summary=summary,
            metadata=persisted_metadata,
        )
        session.artifacts.append(copy.deepcopy(manifest))
        self._link_artifact_to_run(session, manifest)
        self._append_session_event(
            session,
            kind="artifact_saved",
            message="Persistent MCP output artifact saved",
            details={
                "artifact_id": manifest["artifact_id"],
                "tool": tool,
                "kind": kind,
                "primary_file": primary_file,
            },
        )
        session.touch()
        self._save_session(session)
        return copy.deepcopy(manifest)

    @synchronized
    def list_artifacts(
        self,
        *,
        session_id: str | None = None,
        tool: str | None = None,
        kind: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List recent artifact manifests from one session."""
        session = self._get_session_for_artifact_lookup(session_id)
        if session is None:
            return []

        artifacts = list(getattr(session, "artifacts", []))
        if tool:
            artifacts = [artifact for artifact in artifacts if artifact.get("tool") == tool]
        if kind:
            artifacts = [artifact for artifact in artifacts if artifact.get("kind") == kind]
        if limit <= 0:
            return []
        return copy.deepcopy(artifacts[-limit:])

    @synchronized
    def get_artifact_manifest(
        self,
        artifact_id: str,
        *,
        artifact_uri: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return one artifact manifest from a specific or active session."""
        uri_session_id, uri_artifact_id = self._parse_artifact_uri(artifact_uri)
        lookup_session_id = session_id or uri_session_id
        lookup_artifact_id = uri_artifact_id or artifact_id
        if not lookup_artifact_id:
            return None

        for manifest in self.list_artifacts(session_id=lookup_session_id, limit=10_000):
            if manifest.get("artifact_id") == lookup_artifact_id:
                return manifest
        return None

    def _get_session_for_artifact_lookup(self, session_id: str | None = None) -> ResearchSession | None:
        if not session_id:
            return self._current_session()
        if not _SAFE_SESSION_ID_RE.fullmatch(session_id):
            msg = f"Unsafe session id: {session_id}"
            raise ValueError(msg)

        session = self._sessions.get(session_id)
        if session is None and self.data_dir is not None:
            recovered = self._load_session(session_id)
            if recovered:
                self._save_sessions_index()
            session = self._sessions.get(session_id)
        if session is None:
            return None
        return self._refresh_session_cache_view(session)

    @staticmethod
    def _parse_artifact_uri(artifact_uri: str | None) -> tuple[str | None, str | None]:
        if not artifact_uri:
            return None, None
        value = artifact_uri.strip()
        if not value.startswith("artifact://"):
            return None, value or None
        parts = [part for part in value.removeprefix("artifact://").split("/") if part]
        if len(parts) >= 2:
            return parts[0], parts[-1]
        if parts:
            return None, parts[0]
        return None, None

    @synchronized
    def read_artifact(
        self,
        artifact_id: str = "",
        *,
        artifact_uri: str | None = None,
        session_id: str | None = None,
        file_name: str | None = None,
        max_chars: int = 200_000,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Read an artifact file for remote clients that cannot access local paths."""
        if self.artifact_store is None:
            return {"success": False, "error": "Artifact persistence is not configured"}

        try:
            manifest = self.get_artifact_manifest(
                artifact_id,
                artifact_uri=artifact_uri,
                session_id=session_id,
            )
        except Exception as exc:
            return {"success": False, "error": str(exc)}
        if manifest is None:
            return {"success": False, "error": f"Artifact not found: {artifact_uri or artifact_id}"}

        try:
            file_info, content = self.artifact_store.read_file(manifest, file_name=file_name)
        except Exception as exc:
            return {"success": False, "error": str(exc), "artifact": manifest}

        truncated = False
        start = max(offset, 0)
        content = content[start:] if start <= len(content) else ""
        next_offset: int | None = None
        if max_chars > 0 and len(content) > max_chars:
            content = content[:max_chars]
            truncated = True
            next_offset = start + max_chars

        return {
            "success": True,
            "artifact": manifest,
            "file": {
                "name": file_name or manifest.get("primary_file"),
                **file_info,
            },
            "available_files": sorted((manifest.get("files") or {}).keys()),
            "read_order": [
                file
                for file in (manifest.get("summary") or {}).get("read_order", [])
                if file in (manifest.get("files") or {})
            ],
            "retrieval": {
                "artifact_id": manifest.get("artifact_id"),
                "artifact_uri": manifest.get("artifact_uri"),
                "artifact_file": file_name or manifest.get("primary_file"),
                "offset": start,
                "max_chars": max_chars,
                "supports_paging": True,
                "next_offset": next_offset,
            },
            "content": content,
            "offset": start,
            "next_offset": next_offset,
            "truncated": truncated,
        }

    @synchronized
    def get_session_event_log(
        self,
        *,
        session: ResearchSession | None = None,
        limit: int = 50,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent session events, optionally filtered by kind."""
        active_session = session or self._current_session()
        if active_session is None:
            return []

        events = active_session.event_log
        if kind:
            normalized_kind = kind.strip().lower()
            events = [event for event in events if str(event.get("kind", "")).lower() == normalized_kind]

        if limit <= 0:
            return []
        return copy.deepcopy(events[-limit:])

    @synchronized
    def find_cached_search(self, query: str, limit: int | None = None) -> list[dict[str, Any]] | None:
        session = self._current_session()
        if session is None:
            return None

        normalized_query = query.strip().lower()

        for record in reversed(session.search_history):
            if record.get("query", "").strip().lower() != normalized_query:
                continue

            pmids = record.get("pmids", [])
            if limit and len(pmids) < limit:
                continue

            requested_pmids = pmids[:limit] if limit else pmids
            cached_map, missing = self.get_cached_article_map(requested_pmids)
            if missing:
                continue

            results = [cached_map[pmid] for pmid in requested_pmids if pmid in cached_map]
            if results and (not limit or len(results) >= limit):
                logger.info("Session cache hit: %s articles", len(results))
                return results

        return None

    @synchronized
    def add_to_reading_list(self, pmid: str, priority: int = 3, notes: str = "") -> None:
        session = self._get_or_create_session()
        session.reading_list[pmid] = {
            "priority": priority,
            "status": "unread",
            "added_at": _utcnow_iso(),
            "notes": notes,
        }
        self._append_session_event(
            session,
            kind="reading_list_updated",
            message="Article added to reading list",
            details={"pmid": pmid, "priority": priority},
        )
        session.touch()
        self._refresh_session_cache_view(session)
        self._save_session(session)

    @synchronized
    def exclude_article(self, pmid: str) -> None:
        session = self._get_or_create_session()
        if pmid not in session.excluded_pmids:
            session.excluded_pmids.append(pmid)
            self._append_session_event(
                session,
                kind="article_excluded",
                message="Article excluded from the active session",
                details={"pmid": pmid},
            )
            session.touch()
            self._refresh_session_cache_view(session)
            self._save_session(session)

    @synchronized
    def get_session_summary(self) -> dict[str, Any]:
        session = self._current_session()
        if session is None:
            return {"status": "no_active_session"}

        cached_pmids = self.get_session_cached_pmids(session=session, limit=20)
        recent_runs = self.list_search_runs(limit=5)
        status_counts: dict[str, int] = {}
        for run in self.list_search_runs(limit=100_000):
            status = str(run.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        return {
            "session_id": session.session_id,
            "topic": session.topic,
            "cached_articles": len(self.get_session_cached_pmids(session=session)),
            "searches_performed": len(session.search_history),
            "search_runs": len(session.search_runs) + len(self._legacy_search_runs(session)),
            "search_run_statuses": status_counts,
            "event_entries": len(session.event_log),
            "reading_list_count": len(session.reading_list),
            "excluded_count": len(session.excluded_pmids),
            "recent_searches": [
                {"query": search.get("query", ""), "count": search.get("result_count", 0)}
                for search in session.search_history[-5:]
            ],
            "recent_search_runs": [
                {
                    "run_id": run.get("run_id"),
                    "query": str(run.get("query") or "")[:80],
                    "status": run.get("status"),
                    "result_count": (run.get("result") or {}).get("count", 0),
                    "artifact_uri": (run.get("artifact") or {}).get("artifact_uri"),
                }
                for run in recent_runs
            ],
            "recent_events": [
                {
                    "timestamp": event.get("timestamp", "")[:19],
                    "kind": event.get("kind", ""),
                    "message": event.get("message", ""),
                }
                for event in session.event_log[-5:]
            ],
            "cached_pmids": cached_pmids,
            "reading_list": copy.deepcopy(session.reading_list),
            "cache_stats": self.article_cache.stats(),
        }
