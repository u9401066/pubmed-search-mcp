"""Bounded, tenant-scoped XML reuse and optional speculative fulltext work.

Only public structured XML is eligible. Source selection, institutional access,
PDF downloads and rendering remain in the ordinary fulltext service. Callers
inject I/O; this runtime owns tasks independently of a finished MCP request.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pubmed_search.domain.value_objects.article_identifiers import IdentifierValidationError, normalize_pmcid
from pubmed_search.shared.bounded_tasks import BoundedTaskSupervisor

if TYPE_CHECKING:
    from pubmed_search.domain.entities.article import UnifiedArticle

XMLFetcher = Callable[[str], Awaitable[str | None]]
CacheKey = tuple[str, str]
MAX_PREFETCH_ARTICLES = 3
MAX_XML_CACHE_ITEM_BYTES = 2 * 1024 * 1024


class FulltextCacheError(RuntimeError):
    """A bounded XML operation could not complete; callers may try other sources."""


@dataclass
class _Entry:
    xml: str | None
    expires: float
    size: int
    failed: bool = False


@dataclass
class _Job:
    background: bool
    task: asyncio.Future[Any] = field(init=False)
    started: bool = False
    waiters: int = 0
    abandoned: bool = False


class FulltextCache:
    """One server's bounded XML cache, in-flight deduplication and prefetch queue."""

    def __init__(
        self,
        *,
        max_entries: int = 32,
        max_bytes: int = 16 * 1024 * 1024,
        ttl_seconds: float = 900,
        negative_ttl_seconds: float = 60,
        prefetch_timeout_seconds: float = 15,
        foreground_timeout_seconds: float = 45,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            min(
                max_entries,
                max_bytes,
                ttl_seconds,
                negative_ttl_seconds,
                prefetch_timeout_seconds,
                foreground_timeout_seconds,
            )
            <= 0
        ):
            raise ValueError("Fulltext cache bounds must be positive")
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._ttl = ttl_seconds
        self._negative_ttl = negative_ttl_seconds
        self._prefetch_timeout = prefetch_timeout_seconds
        self._foreground_timeout = foreground_timeout_seconds
        self._clock = clock
        self._entries: OrderedDict[CacheKey, _Entry] = OrderedDict()
        self._bytes = 0
        self._pending: dict[CacheKey, _Job] = {}
        self._jobs = BoundedTaskSupervisor(max_pending=16)
        self._io = BoundedTaskSupervisor(max_pending=16)
        self._background_slot = asyncio.Semaphore(1)
        self._closed = False

    def _entry(self, key: CacheKey) -> _Entry | None:
        for expired in [key for key, entry in self._entries.items() if entry.expires <= self._clock()]:
            self._bytes -= self._entries.pop(expired).size
        entry = self._entries.get(key)
        if entry is not None:
            self._entries.move_to_end(key)
        return entry

    def _store(self, key: CacheKey, xml: str | None, *, failed: bool = False) -> None:
        if self._closed:
            return
        size = len(xml.encode("utf-8")) if xml else 0
        if size > min(MAX_XML_CACHE_ITEM_BYTES, self._max_bytes):
            return
        previous = self._entries.pop(key, None)
        if previous is not None:
            self._bytes -= previous.size
        ttl = self._ttl if xml else self._negative_ttl
        self._entries[key] = _Entry(xml, self._clock() + ttl, size, failed)
        self._bytes += size
        while len(self._entries) > self._max_entries or self._bytes > self._max_bytes:
            _, evicted = self._entries.popitem(last=False)
            self._bytes -= evicted.size

    def prefetch(
        self,
        articles: Sequence[UnifiedArticle],
        *,
        tenant: str,
        fetch: XMLFetcher,
        limit: int = MAX_PREFETCH_ARTICLES,
    ) -> dict[str, Any]:
        """Schedule at most three top-ranked known PMCID candidates without awaiting I/O."""
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        # Do not scan deeper to replace ineligible high-ranked results.
        for article in articles[: max(0, min(limit, MAX_PREFETCH_ARTICLES))]:
            if not article.pmc or article.is_open_access is False:
                continue
            try:
                pmcid = normalize_pmcid(article.pmc)
            except IdentifierValidationError:
                continue
            if pmcid in seen:
                continue
            seen.add(pmcid)
            key = (tenant, pmcid)
            entry = self._entry(key)
            if self._closed:
                state = "disabled"
            elif entry is not None:
                state = "cached" if entry.xml else "cooldown"
            elif key in self._pending:
                state = "in_progress"
            elif sum(job.background for job in self._pending.values()) >= MAX_PREFETCH_ARTICLES:
                state = "capacity_limited"
            else:
                job = self._start(key, fetch, background=True)
                state = "scheduled" if job is not None else "capacity_limited"
            rows.append({"source": {"kind": "pmcid", "value": pmcid}, "status": state})
        return {
            "mode": "prefetch",
            "scope": "open_access_xml",
            "snapshot": True,
            "articles": rows,
            "max_articles": max(0, min(limit, MAX_PREFETCH_ARTICLES)),
            "deadline_seconds": self._prefetch_timeout,
            "next_action": "Call get_fulltext with a listed source when needed; it reuses ready or in-flight XML. Do not poll.",
        }

    def _start(self, key: CacheKey, fetch: XMLFetcher, *, background: bool) -> _Job | None:
        if self._closed:
            return None
        deadline = self._clock() + (self._prefetch_timeout if background else self._foreground_timeout)
        job = _Job(background=background)
        task = self._jobs.schedule(self._load(key, fetch, job=job, deadline=deadline))
        if task is None:
            return None
        job.task = task
        self._pending[key] = job

        def finished(_: asyncio.Future[Any]) -> None:
            if self._pending.get(key) is job:
                self._pending.pop(key, None)

        task.add_done_callback(finished)
        return job

    async def _load(self, key: CacheKey, fetch: XMLFetcher, *, job: _Job, deadline: float) -> str | None:
        try:
            xml = await self._fetch(key[1], fetch, job=job, deadline=deadline)
            self._store(key, xml)
            return xml
        except asyncio.CancelledError:
            raise
        except Exception:
            self._store(key, None, failed=True)
            raise FulltextCacheError("Structured fulltext was unavailable") from None

    async def _fetch(self, pmcid: str, fetch: XMLFetcher, *, job: _Job, deadline: float) -> str | None:
        work: asyncio.Future[Any] | None = None
        owns_slot = False
        try:
            if job.background:
                await asyncio.wait_for(self._background_slot.acquire(), timeout=max(0, deadline - self._clock()))
                owns_slot = True
            if self._closed or self._clock() >= deadline:
                raise FulltextCacheError("Fulltext XML deadline exceeded")
            job.started = True
            work = self._io.schedule(fetch(pmcid))
            if work is None:
                raise FulltextCacheError("Fulltext XML capacity reached")
            if owns_slot:
                # A cancellation-resistant source keeps its slot until it exits.
                work.add_done_callback(lambda _: self._background_slot.release())
                owns_slot = False
            done, _ = await asyncio.wait({work}, timeout=max(0, deadline - self._clock()))
            if not done or self._clock() >= deadline:
                raise FulltextCacheError("Fulltext XML deadline exceeded")
            xml = work.result()
            if xml is not None and not isinstance(xml, str):
                raise FulltextCacheError("Invalid structured fulltext response")
            return xml
        finally:
            if work is not None and not work.done():
                work.cancel()
            if owns_slot:
                self._background_slot.release()

    async def get(self, pmcid: str, *, tenant: str, fetch: XMLFetcher) -> str | None:
        """Reuse XML or join one operation; failed speculation never blocks a demand retry."""
        key = (tenant, normalize_pmcid(pmcid))
        for _ in range(2):
            if self._closed:
                raise FulltextCacheError("Fulltext runtime is closed")
            entry = self._entry(key)
            if entry is not None and not entry.failed:
                return entry.xml
            job = self._pending.get(key)
            if job is not None and (job.task.done() or job.abandoned):
                self._pending.pop(key, None)
                job = None
            if job is not None and job.background and not job.started:
                # No source I/O has begun: replace queued speculation with demand.
                # Running downloads remain shared, including their provider budget.
                job.task.cancel()
                self._pending.pop(key, None)
                job = None
            if job is None:
                job = self._start(key, fetch, background=False)
            if job is None:
                raise FulltextCacheError("Fulltext XML capacity reached")
            job.waiters += 1
            try:
                return await asyncio.shield(job.task)
            except FulltextCacheError:
                if not job.background:
                    raise
            finally:
                job.waiters -= 1
                if job.waiters == 0 and not job.background and not job.task.done():
                    job.abandoned = True
                    job.task.cancel()
        raise FulltextCacheError("Structured fulltext was unavailable")

    async def aclose(self) -> None:
        """Cancel owned work before source clients close; discard all cached text."""
        self._closed = True
        await self._jobs.aclose()
        await self._io.aclose()
        self._entries.clear()
        self._bytes = 0


__all__ = ["FulltextCache", "FulltextCacheError", "MAX_PREFETCH_ARTICLES", "MAX_XML_CACHE_ITEM_BYTES"]
