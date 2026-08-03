"""HTTP timing instrumentation for source clients.

Lives in the infrastructure layer because it patches :class:`BaseAPIClient`.
``shared/`` owns the generic counters, but it must not know about concrete
clients, so the wiring belongs here.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from pubmed_search.shared.profiling import PROFILING_ENABLED, record_http_time

from .base_client import BaseAPIClient

logger = logging.getLogger(__name__)


def install_http_profiling() -> bool:
    """Instrument ``BaseAPIClient._make_request`` to track time spent in HTTP.

    Call this once at startup, after imports.

    Returns:
        True when the patch was applied, False when profiling is disabled.
    """
    if not PROFILING_ENABLED:
        return False

    original_make_request = BaseAPIClient._make_request

    async def profiled_make_request(self: Any, url: str, **kwargs: Any) -> Any:
        start = time.perf_counter()
        try:
            return await original_make_request(self, url, **kwargs)
        finally:
            record_http_time((time.perf_counter() - start) * 1000)

    BaseAPIClient._make_request = profiled_make_request  # type: ignore[assignment]
    logger.info("HTTP profiling installed on BaseAPIClient")
    return True


__all__ = ["install_http_profiling"]
