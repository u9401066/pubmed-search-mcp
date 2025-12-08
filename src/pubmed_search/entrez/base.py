"""
Entrez Base Module - Configuration and Shared Utilities

Provides base class with Entrez configuration and common functionality.
Includes rate limiting to respect NCBI API limits.
"""

import time
from Bio import Entrez
from enum import Enum
from typing import Optional


class SearchStrategy(Enum):
    """Search strategy options for literature search."""
    RECENT = "recent"
    MOST_CITED = "most_cited"
    RELEVANCE = "relevance"
    IMPACT = "impact"
    AGENT_DECIDED = "agent_decided"


# Global rate limiter state
_last_request_time = 0.0
_min_request_interval = 0.34  # ~3 requests/second (NCBI limit without API key)


def _rate_limit():
    """Ensure minimum interval between API requests."""
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < _min_request_interval:
        time.sleep(_min_request_interval - elapsed)
    _last_request_time = time.time()


class EntrezBase:
    """
    Base class for Entrez API interactions.
    
    Handles configuration and provides shared utilities for all Entrez operations.
    
    Attributes:
        email: Email address required by NCBI Entrez API.
        api_key: Optional NCBI API key for higher rate limits.
    """
    
    def __init__(self, email: str = "your.email@example.com", api_key: Optional[str] = None):
        """
        Initialize Entrez configuration.
        
        Args:
            email: Email address required by NCBI Entrez API.
            api_key: Optional NCBI API key for higher rate limits (10/sec vs 3/sec).
        """
        global _min_request_interval
        
        Entrez.email = email
        if api_key:
            Entrez.api_key = api_key
            _min_request_interval = 0.1  # 10 requests/second with API key
        else:
            _min_request_interval = 0.34  # ~3 requests/second without API key
            
        Entrez.max_tries = 3
        Entrez.sleep_between_tries = 15
        
        self._email = email
        self._api_key = api_key
    
    def _rate_limited_call(self, func, *args, **kwargs):
        """Execute a function with rate limiting."""
        _rate_limit()
        return func(*args, **kwargs)
    
    @property
    def email(self) -> str:
        """Get configured email."""
        return self._email
    
    @property
    def api_key(self) -> Optional[str]:
        """Get configured API key."""
        return self._api_key
