"""HTTP Client Utilities."""

from .client import (
    configure_client,
    configure_proxy,
    get_proxy_status,
    http_get,
    http_get_safe,
    http_post,
    http_post_safe,
    set_rate_limit,
    with_retry,
)
from .pubmed_client import PubMedClient

__all__ = [
    # Core request functions
    "http_get",
    "http_get_safe",
    "http_post",
    "http_post_safe",
    # Configuration
    "configure_client",
    "configure_proxy",
    "get_proxy_status",
    "set_rate_limit",
    # Retry decorator
    "with_retry",
    # PubMed client
    "PubMedClient",
]
