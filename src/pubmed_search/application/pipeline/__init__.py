"""
Pipeline application module — DAG-based search workflow executor.

Provides PipelineExecutor for running structured search pipelines,
built-in templates for common workflows (PICO, comprehensive, etc.),
and persistence via PipelineStore + PipelineValidator.
"""

from __future__ import annotations

from pubmed_search.application.pipeline.executor import PipelineExecutor
from pubmed_search.application.pipeline.store import PipelineStore
from pubmed_search.application.pipeline.templates import (
    PIPELINE_TEMPLATES,
    build_pipeline_from_template,
)
from pubmed_search.application.pipeline.validator import (
    parse_and_validate_config,
    validate_and_fix,
)

__all__ = [
    "PIPELINE_TEMPLATES",
    "PipelineExecutor",
    "PipelineStore",
    "build_pipeline_from_template",
    "parse_and_validate_config",
    "validate_and_fix",
]
