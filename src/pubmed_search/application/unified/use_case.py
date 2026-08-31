"""Application-owned orchestration for a normal unified-search run.

The use case coordinates request-independent planning and execution through
explicit ports. It deliberately knows nothing about MCP contexts, serialized
tool responses, session journals, or artifact persistence; those are adapter
concerns handled after this use case returns its typed outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from pubmed_search.application.search.query_analyzer import QueryAnalyzer
    from pubmed_search.domain.entities.article import UnifiedArticle

    from .execution import UnifiedSearchExecutionResult
    from .planning import UnifiedSearchPlan
    from .request import UnifiedSearchRequest


class ProgressPort(Protocol):
    """Report bounded use-case progress without depending on MCP."""

    async def __call__(self, progress: float, total: float, message: str) -> None:
        """Report one progress update."""


class PlanObserverPort(Protocol):
    """Observe a completed plan before external source execution starts."""

    async def __call__(self, plan: UnifiedSearchPlan) -> None:
        """Receive one immutable planning handoff."""


class SourceBrokerPort(Protocol):
    """Execute source I/O through an outer-layer adapter."""

    def build_search_functions(self) -> Any:
        """Return exact source-key to typed-runner bindings."""

    async def execute_deep_search(self, *args: Any, **kwargs: Any) -> Any:
        """Execute a bounded multi-strategy search."""

    async def auto_relax(self, *args: Any, **kwargs: Any) -> Any:
        """Execute bounded PubMed query relaxation."""

    async def search_related_trials(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        """Execute the optional ClinicalTrials.gov adjunct."""


SourceAutoDispatchProfile = Literal[
    "lookup_identifier",
    "lookup",
    "simple",
    "moderate",
    "complex_comparison",
    "complex_systematic",
    "complex_default",
    "ambiguous",
]


class SourceRegistryPort(Protocol):
    """Application view of source capabilities and exact source selection."""

    def list_auto_dispatch_sources(self, profile: SourceAutoDispatchProfile) -> list[str]:
        """Return enabled sources for one application dispatch profile."""

    def filter_unified_sources(self, sources: list[str]) -> list[str]:
        """Return enabled canonical sources from an ordered candidate list."""

    def resolve_unified_sources(self, expression: str, *, auto_sources: list[str]) -> Any:
        """Resolve an exact source expression."""

    def list_unified_sources(self) -> list[str]:
        """Return enabled selectable source keys."""

    def get(self, value: str) -> Any:
        """Return one source definition, if registered."""

    def is_enabled(self, value: str) -> bool:
        """Return whether one canonical source is enabled."""


class EnrichmentReportPort(Protocol):
    """Typed diagnostic projection returned by an enrichment adapter."""

    def to_diagnostic(self) -> dict[str, Any]:
        """Return stable non-sensitive coverage diagnostics."""


class EnrichmentPort(Protocol):
    """Apply optional provider enrichments outside the application layer."""

    async def enrich(
        self,
        articles: list[UnifiedArticle],
        *,
        include_crossref: bool,
        include_journal_metrics: bool,
        include_unpaywall: bool,
    ) -> EnrichmentReportPort:
        """Enrich selected candidates and report typed coverage."""


@dataclass(eq=False)
class SourceSelectionError(ValueError):
    """Application error for invalid or unavailable source selections."""

    message: str
    invalid_sources: tuple[str, ...] = field(default_factory=tuple)
    unavailable_sources: tuple[str, ...] = field(default_factory=tuple)
    available_sources: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        super().__init__(self.message)


class UnifiedSearchPlannerPort(Protocol):
    """Turn one normalized request into an executable plan."""

    async def __call__(
        self,
        request: UnifiedSearchRequest,
        *,
        progress: ProgressPort,
        analyzer_factory: Callable[[], QueryAnalyzer],
        enhancer_factory: Callable[[], Any],
        source_registry_factory: Callable[[], Any],
    ) -> UnifiedSearchPlan:
        """Build a plan through injected analysis and registry boundaries."""


class UnifiedSearchExecutorPort(Protocol):
    """Execute one application plan through typed source runners."""

    async def __call__(
        self,
        plan: UnifiedSearchPlan,
        *,
        progress: ProgressPort,
        source_broker: SourceBrokerPort,
        enrichment: EnrichmentPort,
        source_registry: Any,
    ) -> UnifiedSearchExecutionResult:
        """Return typed execution state without formatting or persistence."""


@dataclass(frozen=True, slots=True)
class UnifiedSearchOutcome:
    """Typed handoff from the application use case to an outer adapter."""

    request: UnifiedSearchRequest
    plan: UnifiedSearchPlan
    execution: UnifiedSearchExecutionResult


class UnifiedSearchUseCase:
    """Coordinate planning, source binding, and execution for unified search."""

    def __init__(
        self,
        *,
        planner: UnifiedSearchPlannerPort,
        executor: UnifiedSearchExecutorPort,
        source_broker: SourceBrokerPort,
        enrichment: EnrichmentPort,
        analyzer_factory: Callable[[], QueryAnalyzer],
        enhancer_factory: Callable[[], Any],
        source_registry_factory: Callable[[], Any],
    ) -> None:
        self._planner = planner
        self._executor = executor
        self._source_broker = source_broker
        self._enrichment = enrichment
        self._analyzer_factory = analyzer_factory
        self._enhancer_factory = enhancer_factory
        self._source_registry_factory = source_registry_factory

    async def execute(
        self,
        request: UnifiedSearchRequest,
        *,
        progress: ProgressPort,
        plan_observer: PlanObserverPort | None = None,
    ) -> UnifiedSearchOutcome:
        """Plan and execute a normal search without presentation side effects."""
        registry = self._source_registry_factory()
        plan = await self._planner(
            request,
            progress=progress,
            analyzer_factory=self._analyzer_factory,
            enhancer_factory=self._enhancer_factory,
            source_registry_factory=lambda: registry,
        )
        if plan_observer is not None:
            await plan_observer(plan)
        execution = await self._executor(
            plan,
            progress=progress,
            source_broker=self._source_broker,
            enrichment=self._enrichment,
            source_registry=registry,
        )
        return UnifiedSearchOutcome(request=request, plan=plan, execution=execution)


__all__ = [
    "EnrichmentPort",
    "EnrichmentReportPort",
    "PlanObserverPort",
    "ProgressPort",
    "SourceSelectionError",
    "SourceBrokerPort",
    "SourceRegistryPort",
    "UnifiedSearchExecutorPort",
    "UnifiedSearchOutcome",
    "UnifiedSearchPlannerPort",
    "UnifiedSearchUseCase",
]
