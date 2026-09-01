"""Session Management."""

from __future__ import annotations

from .artifact_envelope import (
    ARTIFACT_SCHEMA_VERSION,
    DEFAULT_AUDIT_MODE,
    ResearchArtifactEnvelope,
    audit_unified_search_artifact,
    build_unified_search_artifact_envelope,
    build_unified_search_query_strategy,
)
from .artifacts import ArtifactStore
from .manager import (
    MAX_SESSION_EVENT_LOG,
    RESEARCH_SESSION_SCHEMA_VERSION,
    SEARCH_RUN_ACTIVE_STATUSES,
    SEARCH_RUN_SCHEMA_VERSION,
    SEARCH_RUN_TERMINAL_STATUSES,
    SESSION_INDEX_SCHEMA_VERSION,
    ArticleCache,
    CachedArticle,
    ResearchSession,
    SearchRecord,
    SearchRun,
    SessionManager,
)
from .registry import TENANT_DIR_NAME, SessionManagerRegistry

__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "ArticleCache",
    "ArtifactStore",
    "CachedArticle",
    "DEFAULT_AUDIT_MODE",
    "MAX_SESSION_EVENT_LOG",
    "RESEARCH_SESSION_SCHEMA_VERSION",
    "ResearchArtifactEnvelope",
    "ResearchSession",
    "SEARCH_RUN_ACTIVE_STATUSES",
    "SEARCH_RUN_SCHEMA_VERSION",
    "SEARCH_RUN_TERMINAL_STATUSES",
    "SESSION_INDEX_SCHEMA_VERSION",
    "SearchRecord",
    "SearchRun",
    "SessionManager",
    "SessionManagerRegistry",
    "TENANT_DIR_NAME",
    "audit_unified_search_artifact",
    "build_unified_search_artifact_envelope",
    "build_unified_search_query_strategy",
]
