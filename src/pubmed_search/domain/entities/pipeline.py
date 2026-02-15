"""
Pipeline domain entities for structured search workflows.

A pipeline is a DAG (Directed Acyclic Graph) of steps, where each step
performs an action (search, merge, filter, etc.) and passes results downstream.

Persistence entities:
- PipelineMeta: Metadata for a saved pipeline configuration
- PipelineRun: Record of a single pipeline execution
- ValidationResult / ValidationFix: Auto-fix validation results
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
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


# =========================================================================
# Persistence Entities
# =========================================================================


class PipelineScope(Enum):
    """Storage scope for a pipeline."""

    WORKSPACE = "workspace"
    GLOBAL = "global"


@dataclass
class PipelineMeta:
    """Metadata for a saved pipeline configuration."""

    name: str
    scope: PipelineScope = PipelineScope.GLOBAL
    description: str = ""
    tags: list[str] = field(default_factory=list)
    config_hash: str = ""
    step_count: int = 0
    created: datetime | None = None
    updated: datetime | None = None
    run_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON index."""
        return {
            "name": self.name,
            "scope": self.scope.value,
            "description": self.description,
            "tags": self.tags,
            "config_hash": self.config_hash,
            "step_count": self.step_count,
            "created": self.created.isoformat() if self.created else None,
            "updated": self.updated.isoformat() if self.updated else None,
            "run_count": self.run_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineMeta:
        """Deserialize from JSON index."""
        return cls(
            name=data["name"],
            scope=PipelineScope(data.get("scope", "global")),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            config_hash=data.get("config_hash", ""),
            step_count=data.get("step_count", 0),
            created=datetime.fromisoformat(data["created"]) if data.get("created") else None,
            updated=datetime.fromisoformat(data["updated"]) if data.get("updated") else None,
            run_count=data.get("run_count", 0),
        )


@dataclass
class PipelineRun:
    """Record of a single pipeline execution."""

    run_id: str
    pipeline_name: str
    started: datetime | None = None
    finished: datetime | None = None
    status: Literal["success", "error", "timeout"] = "success"
    article_count: int = 0
    pmids: list[str] = field(default_factory=list)
    new_pmids: list[str] = field(default_factory=list)
    removed_pmids: list[str] = field(default_factory=list)
    error_message: str | None = None
    top_articles: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON storage."""
        return {
            "run_id": self.run_id,
            "pipeline_name": self.pipeline_name,
            "started": self.started.isoformat() if self.started else None,
            "finished": self.finished.isoformat() if self.finished else None,
            "status": self.status,
            "article_count": self.article_count,
            "pmids": self.pmids,
            "new_pmids": self.new_pmids,
            "removed_pmids": self.removed_pmids,
            "error_message": self.error_message,
            "top_articles": self.top_articles,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineRun:
        """Deserialize from JSON storage."""
        return cls(
            run_id=data.get("run_id", ""),
            pipeline_name=data.get("pipeline_name", ""),
            started=datetime.fromisoformat(data["started"]) if data.get("started") else None,
            finished=datetime.fromisoformat(data["finished"]) if data.get("finished") else None,
            status=data.get("status", "success"),
            article_count=data.get("article_count", 0),
            pmids=data.get("pmids", []),
            new_pmids=data.get("new_pmids", []),
            removed_pmids=data.get("removed_pmids", []),
            error_message=data.get("error_message"),
            top_articles=data.get("top_articles", []),
        )


# =========================================================================
# Validation Entities (for auto-fix)
# =========================================================================


class FixSeverity(Enum):
    """Severity level for a validation fix."""

    INFO = "info"  # Cosmetic (e.g., whitespace)
    WARNING = "warning"  # Auto-fixed semantic issue
    ERROR = "error"  # Unfixable — needs human/agent intervention


@dataclass
class ValidationFix:
    """A single correction applied during validation."""

    field: str
    original: Any
    corrected: Any
    reason: str
    severity: FixSeverity = FixSeverity.WARNING


@dataclass
class ValidationResult:
    """Result of pipeline config validation with auto-fix."""

    valid: bool
    fixes: list[ValidationFix] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    config: PipelineConfig | None = None

    @property
    def has_fixes(self) -> bool:
        """Whether any auto-fixes were applied."""
        return len(self.fixes) > 0

    @property
    def has_errors(self) -> bool:
        """Whether there are unfixable errors."""
        return len(self.errors) > 0

    def summary(self) -> str:
        """Human-readable summary of validation."""
        parts: list[str] = []
        if self.fixes:
            parts.append(f"Auto-fixed {len(self.fixes)} issue(s):")
            for fix in self.fixes:
                parts.append(f"  [{fix.severity.value}] {fix.field}: {fix.reason}")
                parts.append(f"    {fix.original!r} → {fix.corrected!r}")
        if self.errors:
            parts.append(f"Unfixable error(s) ({len(self.errors)}):")
            for err in self.errors:
                parts.append(f"  ❌ {err}")
        if not parts:
            parts.append("✅ Pipeline config is valid.")
        return "\n".join(parts)
