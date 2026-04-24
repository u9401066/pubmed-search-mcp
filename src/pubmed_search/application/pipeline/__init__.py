"""
Pipeline application module — DAG-based search workflow executor.

Provides PipelineExecutor for running structured search pipelines,
built-in templates for common workflows (PICO, comprehensive, etc.),
Pydantic-backed schema parsing, and persistence via PipelineStore plus
semantic validation/autofix.
"""

from __future__ import annotations

from pubmed_search.application.pipeline.executor import PipelineExecutor
from pubmed_search.application.pipeline.report_generator import generate_pipeline_report
from pubmed_search.application.pipeline.runner import StoredPipelineRunner
from pubmed_search.application.pipeline.schema import parse_pipeline_schema
from pubmed_search.application.pipeline.store import PipelineStore
from pubmed_search.application.pipeline.templates import (
    PIPELINE_TEMPLATES,
    build_pipeline_from_template,
)
from pubmed_search.application.pipeline.validator import (
    parse_and_validate_config,
    validate_and_fix,
)
from pubmed_search.domain.entities.pipeline import (
    MAX_PIPELINE_STEPS,
    VALID_ACTIONS,
    VALID_RANKINGS,
    VALID_TEMPLATES,
    FixSeverity,
    PipelineConfig,
    PipelineExecutionSettings,
    PipelineOutput,
    PipelineStep,
    ScheduleEntry,
    StepResult,
    ValidationFix,
    ValidationResult,
)

__all__ = [
    "PIPELINE_TEMPLATES",
    "FixSeverity",
    "MAX_PIPELINE_STEPS",
    "PipelineConfig",
    "PipelineExecutionSettings",
    "PipelineOutput",
    "PipelineExecutor",
    "PipelineStep",
    "PipelineStore",
    "ScheduleEntry",
    "StoredPipelineRunner",
    "StepResult",
    "VALID_ACTIONS",
    "VALID_RANKINGS",
    "VALID_TEMPLATES",
    "ValidationFix",
    "ValidationResult",
    "build_pipeline_from_template",
    "generate_pipeline_report",
    "parse_pipeline_schema",
    "parse_and_validate_config",
    "validate_and_fix",
]
