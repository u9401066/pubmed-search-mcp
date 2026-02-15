"""
Pipeline domain entities for structured search workflows.

A pipeline is a DAG (Directed Acyclic Graph) of steps, where each step
performs an action (search, merge, filter, etc.) and passes results downstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from pubmed_search.domain.entities.article import UnifiedArticle

# Valid pipeline actions
VALID_ACTIONS: frozenset[str] = frozenset(
    {
        "search",
        "pico",
        "expand",
        "details",
        "related",
        "citing",
        "references",
        "metrics",
        "merge",
        "filter",
    }
)

# Valid built-in templates
VALID_TEMPLATES: frozenset[str] = frozenset(
    {
        "pico",
        "comprehensive",
        "exploration",
        "gene_drug",
    }
)

MAX_PIPELINE_STEPS = 20


@dataclass
class PipelineStep:
    """Single step in a search pipeline DAG."""

    id: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)
    on_error: Literal["skip", "abort"] = "skip"


@dataclass
class PipelineOutput:
    """Output configuration for pipeline results."""

    format: Literal["markdown", "json"] = "markdown"
    limit: int = 20
    ranking: Literal["balanced", "impact", "recency", "quality"] = "balanced"


@dataclass
class PipelineConfig:
    """Complete pipeline configuration — either custom steps or template reference."""

    steps: list[PipelineStep] = field(default_factory=list)
    name: str = ""
    output: PipelineOutput = field(default_factory=PipelineOutput)

    # Template-based creation (steps auto-generated from template)
    template: str | None = None
    template_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    """Result produced by a single pipeline step."""

    step_id: str
    action: str
    articles: list[UnifiedArticle] = field(default_factory=list)
    pmids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Whether this step completed without error."""
        return self.error is None
