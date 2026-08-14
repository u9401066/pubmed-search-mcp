"""Safe logging defaults for HTTP clients used by server entry points."""

from __future__ import annotations

import logging


def harden_http_client_logging() -> None:
    """Suppress request-line logs that can expose URL query strings.

    ``httpx`` logs full outbound URLs at INFO, including provider search terms,
    contact parameters, and credentials used by legacy endpoints. Application
    diagnostics are already source-scoped and sanitized, so transport loggers
    stay at WARNING or above.
    """
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


__all__ = ["harden_http_client_logging"]
