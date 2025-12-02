"""
Entrez Base Module - Configuration and Shared Utilities

Provides base class with Entrez configuration and common functionality.
"""

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
        Entrez.email = email
        if api_key:
            Entrez.api_key = api_key
        Entrez.max_tries = 3
        Entrez.sleep_between_tries = 15
        
        self._email = email
        self._api_key = api_key
    
    @property
    def email(self) -> str:
        """Get configured email."""
        return self._email
    
    @property
    def api_key(self) -> Optional[str]:
        """Get configured API key."""
        return self._api_key
