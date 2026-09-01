"""
Pipeline application module — DAG-based search workflow executor.

Provides PipelineExecutor for running structured search pipelines,
built-in templates for common workflows (PICO, comprehensive, etc.),
strict Pydantic-backed schema parsing, and persistence via PipelineStore plus
fail-closed semantic validation.
"""

from __future__ import annotations

from pubmed_search.application.pipeline.action_contracts import (
    MAX_PIPELINE_DETAILS_PMIDS,
    validate_pipeline_action_contracts,
    validate_pipeline_details_pmids,
    validate_pipeline_discovery_pmid,
)
from pubmed_search.application.pipeline.budgets import (
    PIPELINE_ACTION_LIMITS,
    PIPELINE_OUTPUT_LIMIT,
    PIPELINE_TEMPLATE_LIMITS,
    action_limit,
    validate_pipeline_budgets,
)
from pubmed_search.application.pipeline.config_parser import (
    MAX_PIPELINE_CONFIG_CHARS,
    MAX_PIPELINE_CONFIG_DEPTH,
    MAX_PIPELINE_CONFIG_NODES,
    parse_pipeline_config_file,
    parse_pipeline_config_text,
)
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
    validate_pipeline_config,
)
from pubmed_search.domain.entities.pipeline import (
    MAX_PIPELINE_STEPS,
    VALID_ACTIONS,
    VALID_RANKINGS,
    VALID_TEMPLATES,
    PipelineConfig,
    PipelineOutput,
    PipelineStep,
    ScheduleEntry,
    StepResult,
    ValidationResult,
)

__all__ = [
    "PIPELINE_TEMPLATES",
    "PIPELINE_ACTION_LIMITS",
    "PIPELINE_OUTPUT_LIMIT",
    "PIPELINE_TEMPLATE_LIMITS",
    "MAX_PIPELINE_STEPS",
    "MAX_PIPELINE_CONFIG_CHARS",
    "MAX_PIPELINE_CONFIG_DEPTH",
    "MAX_PIPELINE_CONFIG_NODES",
    "MAX_PIPELINE_DETAILS_PMIDS",
    "PipelineConfig",
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
    "ValidationResult",
    "build_pipeline_from_template",
    "action_limit",
    "generate_pipeline_report",
    "parse_pipeline_schema",
    "parse_pipeline_config_file",
    "parse_pipeline_config_text",
    "parse_and_validate_config",
    "validate_pipeline_config",
    "validate_pipeline_action_contracts",
    "validate_pipeline_budgets",
    "validate_pipeline_details_pmids",
    "validate_pipeline_discovery_pmid",
]
