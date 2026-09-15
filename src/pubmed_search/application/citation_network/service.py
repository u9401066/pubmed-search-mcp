"""Bounded, deadline-aware citation-network construction.

The service owns traversal semantics while the MCP adapter only validates
transport inputs and serializes the resulting graph.  Fetches within each BFS
level run concurrently behind a semaphore, but results are merged in stable
frontier order so output remains deterministic.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pubmed_search.domain.value_objects.article_identifiers import normalize_pmid, try_normalize_pmid
from pubmed_search.shared.bounded_tasks import BoundedTaskSupervisor


class CitationSource(Protocol):
    """Source operations required by citation-network traversal."""

    async def fetch_details(self, pmids: list[str]) -> list[dict[str, Any]]: ...

    async def get_citing_articles(self, pmid: str, limit: int) -> list[dict[str, Any]]: ...

    async def get_article_references(self, pmid: str, limit: int) -> list[dict[str, Any]]: ...


CitationFetch = Callable[[str, int], Awaitable[list[dict[str, Any]]]]
MAX_PENDING_CITATION_TASKS = 128


class CitationTaskSupervisor(BoundedTaskSupervisor):
    """Own cancellation-resistant source tasks behind a hard capacity bound."""

    __slots__ = ()

    def __init__(self, *, max_pending: int = MAX_PENDING_CITATION_TASKS) -> None:
        super().__init__(max_pending=max_pending)


@dataclass(frozen=True)
class CitationNetworkConfig:
    """Validated traversal limits."""

    depth: int
    direction: str
    limit_per_level: int
    max_total_nodes: int = 100
    max_concurrency: int = 6
    timeout_seconds: float = 45.0

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (self.depth, self.limit_per_level, self.max_total_nodes, self.max_concurrency)
        ):
            raise ValueError("citation limits must be integers")
        if not 1 <= self.depth <= 3:
            raise ValueError("depth must be between 1 and 3")
        if self.direction not in {"forward", "backward", "both"}:
            raise ValueError("direction must be forward, backward, or both")
        if self.limit_per_level <= 0 or self.max_total_nodes <= 0:
            raise ValueError("citation limits must be positive")
        if (
            self.max_concurrency <= 0
            or isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("execution limits must be positive")


@dataclass(frozen=True)
class CitationSourceError:
    """Sanitized source failure tied to one attempted expansion."""

    source: str
    direction: str
    level: int
    parent_pmid: str
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "direction": self.direction,
            "level": self.level,
            "parent_pmid": self.parent_pmid,
            "kind": self.kind,
        }


class CitationBuildError(RuntimeError):
    """Fatal root-paper failure with a stable public error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class CitationNetworkResult:
    """Internal graph plus explicit coverage diagnostics."""

    root_article: dict[str, Any]
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    levels: dict[str, int]
    source_errors: list[CitationSourceError] = field(default_factory=list)
    requested_expansions: int = 0
    completed_expansions: int = 0
    timed_out_expansions: int = 0
    malformed_articles: int = 0
    node_cap_omissions: int = 0

    @property
    def partial(self) -> bool:
        return bool(
            self.source_errors or self.timed_out_expansions or self.malformed_articles or self.node_cap_omissions
        )

    def statistics(self) -> dict[str, Any]:
        return {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "citing_articles": sum(node.get("direction") in {"citing", "both"} for node in self.nodes),
            "reference_articles": sum(node.get("direction") in {"reference", "both"} for node in self.nodes),
            "shared_articles": sum(node.get("direction") == "both" for node in self.nodes),
            "levels": dict(self.levels),
        }

    def coverage(self) -> dict[str, Any]:
        failed_expansions = sum(error.kind != "overall_timeout" for error in self.source_errors)
        return {
            "status": "partial" if self.partial else "complete",
            "requested_expansions": self.requested_expansions,
            "completed_expansions": self.completed_expansions,
            "failed_expansions": failed_expansions,
            "timed_out_expansions": self.timed_out_expansions,
            "malformed_articles": self.malformed_articles,
            "node_cap_omissions": self.node_cap_omissions,
            "source_errors": [error.to_dict() for error in self.source_errors],
        }


@dataclass(frozen=True)
class _FetchWork:
    index: int
    direction: str
    level: int
    parent_pmid: str
    source_name: str
    fetch: CitationFetch


@dataclass(frozen=True)
class _FetchResult:
    work: _FetchWork
    articles: list[dict[str, Any]]
    error_kind: str | None = None


@dataclass
class _TraversalState:
    root_pmid: str
    root_article: dict[str, Any]
    config: CitationNetworkConfig
    directions: list[str]
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]] = field(default_factory=list)
    levels: dict[str, int] = field(default_factory=lambda: {"0": 1})
    source_errors: list[CitationSourceError] = field(default_factory=list)
    requested_expansions: int = 0
    completed_expansions: int = 0
    timed_out_expansions: int = 0
    malformed_articles: int = 0
    node_cap_omissions: int = 0
    node_by_pmid: dict[str, dict[str, Any]] = field(default_factory=dict)
    seen_nodes: set[str] = field(default_factory=set)
    seen_edges: set[tuple[str, str]] = field(default_factory=set)
    expanded_nodes: set[tuple[str, str]] = field(default_factory=set)
    queued_nodes: set[tuple[str, str]] = field(default_factory=set)
    frontier: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def initialize(
        cls,
        root_pmid: str,
        root_article: dict[str, Any],
        config: CitationNetworkConfig,
    ) -> _TraversalState:
        root_node = make_citation_node(root_article, level=0, direction="root")
        directions = [config.direction] if config.direction != "both" else ["forward", "backward"]
        return cls(
            root_pmid=root_pmid,
            root_article=root_article,
            config=config,
            directions=directions,
            nodes=[root_node],
            node_by_pmid={root_pmid: root_node},
            seen_nodes={root_pmid},
            queued_nodes={(direction, root_pmid) for direction in directions},
            frontier={direction: [root_pmid] for direction in directions},
        )

    def to_result(self) -> CitationNetworkResult:
        return CitationNetworkResult(
            root_article=self.root_article,
            nodes=self.nodes,
            edges=self.edges,
            levels=self.levels,
            source_errors=self.source_errors,
            requested_expansions=self.requested_expansions,
            completed_expansions=self.completed_expansions,
            timed_out_expansions=self.timed_out_expansions,
            malformed_articles=self.malformed_articles,
            node_cap_omissions=self.node_cap_omissions,
        )


def _plain(value: Any, fallback: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or fallback


def make_citation_node(article: dict[str, Any], level: int, direction: str) -> dict[str, Any]:
    """Create a normalized internal node from source article metadata."""
    pmid = _plain(article.get("pmid"), "unknown")
    title = _plain(article.get("title"), "Unknown Title")
    year = _plain(article.get("year"), "?")
    journal = _plain(article.get("journal"), "Unknown Journal")
    raw_authors = article.get("authors")
    authors = [_plain(author, "Unknown") for author in raw_authors] if isinstance(raw_authors, list) else []
    first_author = authors[0] if authors else "Unknown"
    doi = _plain(article.get("doi"), "")
    short_title = title[:60] + "..." if len(title) > 60 else title
    return {
        "pmid": pmid,
        "label": f"{first_author} ({year})",
        "title": title,
        "short_title": short_title,
        "year": year,
        "journal": journal,
        "authors": authors[:3],
        "first_author": first_author,
        "doi": doi,
        "level": level,
        "direction": direction,
        "node_type": "root" if level == 0 else direction,
    }


def make_citation_edge(source_pmid: str, target_pmid: str) -> dict[str, Any]:
    """Create one directed `source cites target` relationship."""
    return {"source": source_pmid, "target": target_pmid, "edge_type": "cites"}


def _valid_pmid(value: Any) -> str | None:
    return try_normalize_pmid(value)


class CitationNetworkService:
    """Construct citation graphs without losing convergent/shared edges."""

    def __init__(
        self,
        source: CitationSource,
        *,
        task_supervisor: CitationTaskSupervisor | None = None,
    ) -> None:
        self._source = source
        self._task_supervisor = task_supervisor or CitationTaskSupervisor()

    async def build(self, root_pmid: str, config: CitationNetworkConfig) -> CitationNetworkResult:
        root_pmid = normalize_pmid(root_pmid)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + config.timeout_seconds
        root_article = await self._fetch_root(root_pmid, deadline=deadline)
        root_article = {**root_article, "pmid": root_pmid}
        state = _TraversalState.initialize(root_pmid, root_article, config)
        semaphore = asyncio.Semaphore(config.max_concurrency)

        for level in range(1, config.depth + 1):
            work = self._build_level_work(state, level)
            if not work:
                break
            state.requested_expansions += len(work)
            fetched, timed_out = await self._run_level_work(
                work,
                deadline=deadline,
                limit=config.limit_per_level,
                semaphore=semaphore,
            )
            state.completed_expansions += len(fetched)
            state.timed_out_expansions += timed_out
            state.frontier = self._merge_level(state, fetched, level)
            if timed_out:
                self._record_overall_timeout(state, level)
                break

        return state.to_result()

    def _build_level_work(self, state: _TraversalState, level: int) -> list[_FetchWork]:
        work: list[_FetchWork] = []
        for direction in state.directions:
            fetch, source_name = self._source_operation(direction)
            for parent_pmid in state.frontier.get(direction, []):
                key = (direction, parent_pmid)
                if key in state.expanded_nodes:
                    continue
                state.expanded_nodes.add(key)
                work.append(
                    _FetchWork(
                        index=len(work),
                        direction=direction,
                        level=level,
                        parent_pmid=parent_pmid,
                        source_name=source_name,
                        fetch=fetch,
                    )
                )
        return work

    async def _run_level_work(
        self,
        work: list[_FetchWork],
        *,
        deadline: float,
        limit: int,
        semaphore: asyncio.Semaphore,
    ) -> tuple[list[_FetchResult], int]:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return [], len(work)
        tasks: list[asyncio.Future[Any]] = []
        rejected: list[_FetchResult] = []
        for item in work:
            task = self._task_supervisor.schedule(
                self._fetch_related(item, limit=limit, semaphore=semaphore),
                name=f"citation-{item.direction}-{item.parent_pmid}",
            )
            if task is None:
                rejected.append(_FetchResult(item, [], "task_capacity"))
            else:
                tasks.append(task)
        if not tasks:
            return rejected, 0
        try:
            done, pending = await asyncio.wait(tasks, timeout=remaining)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.sleep(0)
            raise
        for task in pending:
            task.cancel()
        if pending:
            # Give cancellation-aware clients one event-loop turn to release
            # sockets, without letting a cancellation-swallowing source extend
            # the operation-wide deadline.
            await asyncio.sleep(0)
        fetched = sorted(
            [*(task.result() for task in done), *rejected],
            key=lambda result: result.work.index,
        )
        return fetched, len(pending)

    def _merge_level(
        self,
        state: _TraversalState,
        fetched: list[_FetchResult],
        level: int,
    ) -> dict[str, list[str]]:
        next_frontier: dict[str, list[str]] = {direction: [] for direction in state.directions}
        for result in fetched:
            if result.error_kind is not None:
                self._record_source_error(state, result)
                continue
            for article in result.articles:
                self._merge_article(state, result.work, article, level, next_frontier)
        return next_frontier

    @staticmethod
    def _record_source_error(state: _TraversalState, result: _FetchResult) -> None:
        item = result.work
        state.source_errors.append(
            CitationSourceError(
                item.source_name,
                item.direction,
                item.level,
                item.parent_pmid,
                result.error_kind or "source_error",
            )
        )

    @staticmethod
    def _merge_article(
        state: _TraversalState,
        work: _FetchWork,
        article: Any,
        level: int,
        next_frontier: dict[str, list[str]],
    ) -> None:
        if not isinstance(article, dict):
            state.malformed_articles += 1
            return
        article_pmid = _valid_pmid(article.get("pmid"))
        if article_pmid is None:
            state.malformed_articles += 1
            return
        if not CitationNetworkService._retain_node(state, article, article_pmid, work.direction, level):
            return
        CitationNetworkService._retain_edge(state, work, article_pmid)
        queue_key = (work.direction, article_pmid)
        if level < state.config.depth and queue_key not in state.queued_nodes:
            state.queued_nodes.add(queue_key)
            next_frontier[work.direction].append(article_pmid)

    @staticmethod
    def _retain_node(
        state: _TraversalState,
        article: dict[str, Any],
        article_pmid: str,
        direction: str,
        level: int,
    ) -> bool:
        observed_direction = "citing" if direction == "forward" else "reference"
        if article_pmid in state.seen_nodes:
            node = state.node_by_pmid[article_pmid]
            if node["direction"] not in {"root", observed_direction, "both"}:
                node["direction"] = "both"
                node["node_type"] = "both"
            return True
        if len(state.nodes) >= state.config.max_total_nodes:
            state.node_cap_omissions += 1
            return False
        node = make_citation_node(article, level=level, direction=observed_direction)
        state.nodes.append(node)
        state.node_by_pmid[article_pmid] = node
        state.seen_nodes.add(article_pmid)
        state.levels[str(level)] = state.levels.get(str(level), 0) + 1
        return True

    @staticmethod
    def _retain_edge(state: _TraversalState, work: _FetchWork, article_pmid: str) -> None:
        edge_key = (article_pmid, work.parent_pmid) if work.direction == "forward" else (work.parent_pmid, article_pmid)
        if edge_key[0] == edge_key[1] or edge_key in state.seen_edges:
            return
        state.seen_edges.add(edge_key)
        state.edges.append(make_citation_edge(*edge_key))

    @staticmethod
    def _record_overall_timeout(state: _TraversalState, level: int) -> None:
        state.source_errors.append(
            CitationSourceError("citation_network", "both", level, state.root_pmid, "overall_timeout")
        )

    async def _fetch_root(self, pmid: str, *, deadline: float) -> dict[str, Any]:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise CitationBuildError("root_timeout")
        task = self._task_supervisor.schedule(
            self._source.fetch_details([pmid]),
            name=f"citation-root-{pmid}",
        )
        if task is None:
            raise CitationBuildError("runtime_saturated")
        try:
            done, _pending = await asyncio.wait({task}, timeout=remaining)
        except BaseException:
            task.cancel()
            await asyncio.sleep(0)
            raise
        if not done:
            task.cancel()
            raise CitationBuildError("root_timeout")
        try:
            rows = task.result()
        except Exception as exc:
            raise CitationBuildError("root_source_unavailable") from exc
        if not isinstance(rows, list):
            raise CitationBuildError("root_source_unavailable")
        if not rows:
            raise CitationBuildError("root_not_found")
        if not isinstance(rows[0], dict) or _valid_pmid(rows[0].get("pmid")) != pmid:
            raise CitationBuildError("root_source_unavailable")
        return rows[0]

    def _source_operation(self, direction: str) -> tuple[CitationFetch, str]:
        if direction == "forward":
            return self._source.get_citing_articles, "pubmed_citing"
        return self._source.get_article_references, "pubmed_references"

    @staticmethod
    async def _fetch_related(
        work: _FetchWork,
        *,
        limit: int,
        semaphore: asyncio.Semaphore,
    ) -> _FetchResult:
        async with semaphore:
            try:
                rows = await work.fetch(work.parent_pmid, limit)
            except asyncio.CancelledError:
                raise
            except Exception:
                return _FetchResult(work=work, articles=[], error_kind="source_exception")
        if not isinstance(rows, list):
            return _FetchResult(work=work, articles=[], error_kind="invalid_source_response")
        return _FetchResult(work=work, articles=rows)
