"""
Research session management and article cache coordination.

Session state stores research workflow context only.
Article caching is delegated to a dedicated cache collaborator that uses the
shared cache substrate, so backends can change without rewriting the
application layer.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

from pubmed_search.shared.cache_substrate import CacheBackend, CacheStore, JsonFileCacheBackend, MemoryCacheBackend

logger = logging.getLogger(__name__)
MAX_SESSION_EVENT_LOG = 200


def _utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


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
        cached_time = datetime.fromisoformat(self.cached_at)
        now = datetime.now(tz=timezone.utc)
        if cached_time.tzinfo is None:
            cached_time = cached_time.replace(tzinfo=timezone.utc)
        return now - cached_time > timedelta(days=max_age_days)

    @classmethod
    def from_article_data(cls, pmid: str, article_data: dict[str, Any]) -> CachedArticle:
        payload = dict(article_data)
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
        payload = dict(self.full_data)
        payload.setdefault("pmid", self.pmid)
        payload.setdefault("title", self.title)
        payload.setdefault("authors", self.authors)
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
    event_log: list[dict[str, Any]] = field(default_factory=list)
    reading_list: dict[str, dict[str, Any]] = field(default_factory=dict)
    excluded_pmids: list[str] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)

    def touch(self) -> None:
        """Update the last modified timestamp."""
        self.updated_at = _utcnow_iso()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchSession:
        payload = dict(data)
        payload.setdefault("article_cache", {})
        payload.setdefault("event_log", [])
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
        return CachedArticle(**raw)

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
        self.data_dir = Path(data_dir) if data_dir else None
        self.article_cache = article_cache or ArticleCache(cache_dir=str(self.data_dir) if self.data_dir else None)
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
        return self.data_dir / f"session_{session_id}.json"

    def _load_sessions(self) -> None:
        sessions_file = self._get_sessions_file()
        if not sessions_file.exists():
            return

        try:
            with sessions_file.open(encoding="utf-8") as handle:
                index = json.load(handle)
        except Exception as exc:
            logger.warning("Failed to load sessions: %s", exc)
            return

        self._current_session_id = index.get("current_session_id")
        for session_id in index.get("sessions", []):
            self._load_session(session_id)

        logger.info("Loaded %s sessions", len(self._sessions))

    def _load_session(self, session_id: str) -> None:
        session_file = self._get_session_file(session_id)
        if not session_file.exists():
            return

        try:
            with session_file.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:
            logger.warning("Failed to load session %s: %s", session_id, exc)
            return

        legacy_cache = payload.pop("article_cache", {}) if isinstance(payload, dict) else {}
        if not isinstance(payload, dict):
            logger.warning("Skipping malformed session payload for %s", session_id)
            return

        session = ResearchSession.from_dict(payload)
        self._sessions[session_id] = session

        if isinstance(legacy_cache, dict) and legacy_cache:
            self.article_cache.warmup(legacy_cache)
            self._refresh_session_cache_view(session)
            self._save_session(session)
        else:
            self._refresh_session_cache_view(session)

    def _save_session(self, session: ResearchSession) -> None:
        if not self.data_dir:
            return

        session_file = self._get_session_file(session.session_id)
        try:
            with session_file.open("w", encoding="utf-8") as handle:
                json.dump(session.to_dict(), handle, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("Failed to save session: %s", exc)

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
            with sessions_file.open("w", encoding="utf-8") as handle:
                json.dump(index, handle, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("Failed to save sessions index: %s", exc)

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
                "details": details or {},
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

    def create_session(self, topic: str = "") -> ResearchSession:
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

    def get_current_session(self) -> ResearchSession | None:
        if not self._current_session_id:
            return None
        session = self._sessions.get(self._current_session_id)
        if session is None:
            return None
        return self._refresh_session_cache_view(session)

    def get_or_create_session(self, topic: str = "default") -> ResearchSession:
        session = self.get_current_session()
        if session is None:
            session = self.create_session(topic)
        return session

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
        return session

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

    def warm_article_cache(self, articles: list[dict[str, Any]]) -> int:
        warmed = self.article_cache.put_many(articles)
        session = self.get_current_session()
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

    def add_to_cache(self, articles: list[dict[str, Any]], *, _skip_save: bool = False) -> int:
        warmed = self.article_cache.put_many(articles)
        session = self.get_current_session()
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

    def get_cached_article(self, pmid: str) -> dict[str, Any] | None:
        cached = self.article_cache.get(pmid)
        if cached is None:
            return None
        return cached.as_article_dict()

    def get_cached_article_map(self, pmids: Iterable[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
        pmid_list = [pmid for pmid in pmids if pmid]
        cached, missing = self.article_cache.get_many(pmid_list)
        return ({pmid: article.as_article_dict() for pmid, article in cached.items()}, missing)

    def get_from_cache(self, pmids: str | list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        pmid_list = [pmids] if isinstance(pmids, str) else pmids
        cached_map, missing = self.get_cached_article_map(pmid_list)
        ordered = [cached_map[pmid] for pmid in pmid_list if pmid in cached_map]
        return ordered, missing

    def get_session_cached_pmids(
        self,
        *,
        session: ResearchSession | None = None,
        limit: int | None = None,
    ) -> list[str]:
        active_session = session or self.get_current_session()
        if active_session is None:
            return []

        cached_pmids = [pmid for pmid in self._session_related_pmids(active_session) if pmid in self.article_cache]
        return cached_pmids[:limit] if limit is not None else cached_pmids

    def is_searched(self, pmid: str) -> bool:
        session = self.get_current_session()
        if session is None:
            return False
        return pmid in self._session_related_pmids(session)

    def add_search_record(self, query: str, pmids: list[str], filters: dict[str, Any] | None = None) -> None:
        session = self.get_or_create_session()
        record = {
            "query": query,
            "timestamp": _utcnow_iso(),
            "result_count": len(pmids),
            "pmids": pmids,
            "filters": filters or {},
        }
        session.search_history.append(record)
        self._append_session_event(
            session,
            kind="search_recorded",
            message="Recorded search query in session history",
            details={
                "query": query,
                "result_count": len(pmids),
                "pmid_count": len(pmids),
                "filters": filters or {},
            },
        )
        session.touch()
        self._refresh_session_cache_view(session)
        self._save_session(session)

    def get_session_event_log(
        self,
        *,
        session: ResearchSession | None = None,
        limit: int = 50,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent session events, optionally filtered by kind."""
        active_session = session or self.get_current_session()
        if active_session is None:
            return []

        events = active_session.event_log
        if kind:
            normalized_kind = kind.strip().lower()
            events = [event for event in events if str(event.get("kind", "")).lower() == normalized_kind]

        if limit <= 0:
            return []
        return events[-limit:]

    def find_cached_search(self, query: str, limit: int | None = None) -> list[dict[str, Any]] | None:
        session = self.get_current_session()
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
                logger.info("Cache hit for query '%s': %s articles", query, len(results))
                return results

        return None

    def add_to_reading_list(self, pmid: str, priority: int = 3, notes: str = "") -> None:
        session = self.get_or_create_session()
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

    def exclude_article(self, pmid: str) -> None:
        session = self.get_or_create_session()
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

    def get_session_summary(self) -> dict[str, Any]:
        session = self.get_current_session()
        if session is None:
            return {"status": "no_active_session"}

        cached_pmids = self.get_session_cached_pmids(session=session, limit=20)
        return {
            "session_id": session.session_id,
            "topic": session.topic,
            "cached_articles": len(self.get_session_cached_pmids(session=session)),
            "searches_performed": len(session.search_history),
            "event_entries": len(session.event_log),
            "reading_list_count": len(session.reading_list),
            "excluded_count": len(session.excluded_pmids),
            "recent_searches": [
                {"query": search.get("query", ""), "count": search.get("result_count", 0)}
                for search in session.search_history[-5:]
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
            "reading_list": session.reading_list,
            "cache_stats": self.article_cache.stats(),
        }
