"""Application-owned unified-search request, use case, and ports."""

from __future__ import annotations

from .clinical_trials import ClinicalTrialsCoverage
from .request import (
    UnifiedSearchRequest,
    normalize_unified_search_request,
    validate_unified_search_input_envelope,
)
from .use_case import (
    EnrichmentPort,
    EnrichmentReportPort,
    PlanObserverPort,
    ProgressPort,
    SourceBrokerPort,
    SourceRegistryPort,
    SourceSelectionError,
    UnifiedSearchExecutorPort,
    UnifiedSearchOutcome,
    UnifiedSearchPlannerPort,
    UnifiedSearchUseCase,
)

__all__ = [
    "ProgressPort",
    "ClinicalTrialsCoverage",
    "EnrichmentPort",
    "EnrichmentReportPort",
    "PlanObserverPort",
    "SourceBrokerPort",
    "SourceRegistryPort",
    "SourceSelectionError",
    "UnifiedSearchExecutorPort",
    "UnifiedSearchOutcome",
    "UnifiedSearchPlannerPort",
    "UnifiedSearchRequest",
    "UnifiedSearchUseCase",
    "normalize_unified_search_request",
    "validate_unified_search_input_envelope",
]
