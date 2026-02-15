"""
Pipeline application module — DAG-based search workflow executor.

Provides PipelineExecutor for running structured search pipelines,
and built-in templates for common workflows (PICO, comprehensive, etc.).
"""

from __future__ import annotations

from pubmed_search.application.pipeline.executor import PipelineExecutor
from pubmed_search.application.pipeline.templates import (
    PIPELINE_TEMPLATES,
    build_pipeline_from_template,
)

__all__ = [
    "PIPELINE_TEMPLATES",
    "PipelineExecutor",
    "build_pipeline_from_template",
]
