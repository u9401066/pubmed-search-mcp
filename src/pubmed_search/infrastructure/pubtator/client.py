"""
PubTator3 API Client

Async HTTP client for PubTator3 API with:
- Built-in rate limiting (3 requests/second)
- Automatic retry with exponential backoff
- Graceful error handling
- Connection pooling via httpx

API Documentation:
https://www.ncbi.nlm.nih.gov/research/pubtator3/api
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import httpx

from pubmed_search.infrastructure.pubtator.models import (
    EntityMatch,
    PubTatorEntity,
    RelationMatch,
)
from pubmed_search.infrastructure.sources.base_client import BaseAPIClient

logger = logging.getLogger(__name__)


class PubTator3Error(Exception):
    """Base exception for PubTator3 API errors."""


class RateLimitExceededError(PubTator3Error):
    """Rate limit exceeded - retry later."""


class PubTatorClient(BaseAPIClient):
    """
    Async client for PubTator3 API.

    Features:
    - Entity autocomplete: Find standardized entity IDs
    - Entity search: Search articles by entity
    - Relation queries: Find entity-entity relationships
    - Rate limiting: 3 requests/second (configurable)
    - Retry: Automatic retry with exponential backoff

    Example:
        client = PubTatorClient()

        # Find entity
        matches = await client.find_entity("propofol", concept="chemical")

        # Get relations
        relations = await client.find_relations(
            "@CHEMICAL_Propofol",
            relation_type="treat"
        )
    """

    BASE_URL = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api"
    DEFAULT_TIMEOUT = 15.0
    DEFAULT_RATE_LIMIT = 3.0  # requests per second
    _service_name = "PubTator3"

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        rate_limit: float = DEFAULT_RATE_LIMIT,
    ):
        """
        Initialize PubTator3 client.

        Args:
            timeout: Request timeout in seconds
            rate_limit: Max requests per second
        """
        self._timeout = timeout
        self._requests_per_second = rate_limit
        self._default_headers = {"User-Agent": "PubMed-Search-MCP/1.0"}
        super().__init__(
            base_url=self.BASE_URL,
            timeout=timeout,
            min_interval=1.0 / rate_limit,
            headers=self._default_headers,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or recreate the underlying HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=5.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                headers=self._default_headers,
            )
        return self._client

    async def close(self):
        """Close HTTP client and release resources."""
        if not self._client.is_closed:
            await self._client.aclose()
        self._client = None  # type: ignore[assignment]

    async def _execute_request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Execute a request using the lazily recreated shared client."""
        client = await self._get_client()
        return await client.get(url, params=params or data or {}, headers=headers or {})

    async def _request(
        self,
        endpoint: str,
        params: dict | None = None,
    ) -> dict | None:
        """
        Make rate-limited HTTP request with retry.

        Args:
            endpoint: API endpoint path
            params: Query parameters

        Returns:
            JSON response or None on failure.
        """
        data = await self._make_request(endpoint, data=params or {}, expect_json=True)
        return data if isinstance(data, dict) else None

    # ==================== Entity APIs ====================

    async def find_entity(
        self,
        query: str,
        concept: Literal["gene", "disease", "chemical", "species", "variant"] | None = None,
        limit: int = 5,
    ) -> list[EntityMatch]:
        """
        Find entity via autocomplete.

        Args:
            query: Search text (e.g., "propofol", "BRCA1")
            concept: Filter by entity type
            limit: Maximum results

        Returns:
            List of matching entities

        Example:
            matches = await client.find_entity("propofol", concept="chemical")
            # [EntityMatch(entity_id="@CHEMICAL_Propofol", name="Propofol", ...)]
        """
        params = {"query": query, "limit": limit}
        if concept:
            params["concept"] = concept

        data = await self._request("entity/autocomplete/", params)
        if not data:
            return []

        results = []
        for item in data.get("results", [])[:limit]:
            results.append(
                EntityMatch(
                    entity_id=item.get("_id", item.get("id", "")),
                    name=item.get("name", item.get("text", "")),
                    type=item.get("type", item.get("category", "unknown")),
                    identifier=item.get("identifier", item.get("id")),
                    score=item.get("score", 1.0),
                )
            )

        return results

    async def search_by_entity(
        self,
        entity_id: str,
        limit: int = 100,
    ) -> dict:
        """
        Search articles by entity ID.

        Args:
            entity_id: PubTator3 entity ID (e.g., "@CHEMICAL_Propofol")
            limit: Maximum articles to return

        Returns:
            dict with 'count' and 'pmids'
        """
        params = {"text": entity_id, "limit": limit}

        data = await self._request("search/", params)
        if not data:
            return {"count": 0, "pmids": []}

        return {
            "count": data.get("count", 0),
            "pmids": data.get("results", [])[:limit],
        }

    async def resolve_entity(
        self,
        text: str,
        preferred_type: Literal["gene", "disease", "chemical", "species", "variant"] | None = None,
    ) -> PubTatorEntity | None:
        """
        Resolve text to standardized entity.

        This is a convenience method that combines autocomplete
        and entity lookup.

        Args:
            text: User input text
            preferred_type: Preferred entity type filter

        Returns:
            Resolved entity or None
        """
        matches = await self.find_entity(text, concept=preferred_type, limit=1)
        if not matches:
            return None

        match = matches[0]
        return PubTatorEntity(
            original_text=text,
            resolved_name=match.name,
            entity_type=match.type,
            entity_id=match.entity_id,
            mesh_id=match.mesh_id,
            ncbi_id=match.identifier if match.type == "gene" else None,
        )

    # ==================== Relation APIs ====================

    async def find_relations(
        self,
        entity_id: str,
        relation_type: Literal["treat", "associate", "cause", "interact", "inhibit", "stimulate"] | None = None,
        target_type: Literal["gene", "disease", "chemical", "species", "variant"] | None = None,
        limit: int = 20,
    ) -> list[RelationMatch]:
        """
        Find entity relations.

        Args:
            entity_id: Source entity ID
            relation_type: Filter by relation type
            target_type: Filter target entity type
            limit: Maximum results

        Returns:
            List of relations

        Example:
            # What diseases does propofol treat?
            relations = await client.find_relations(
                "@CHEMICAL_Propofol",
                relation_type="treat",
                target_type="disease"
            )
        """
        params = {"e1": entity_id}
        if relation_type:
            params["type"] = relation_type
        if target_type:
            params["e2"] = target_type

        data = await self._request("relations/", params)
        if not data:
            return []

        results = []
        for item in data.get("results", [])[:limit]:
            results.append(
                RelationMatch(
                    source_entity=item.get("e1", {}).get("id", entity_id),
                    source_name=item.get("e1", {}).get("name", ""),
                    relation_type=item.get("type", item.get("relation", "")),
                    target_entity=item.get("e2", {}).get("id", ""),
                    target_name=item.get("e2", {}).get("name", ""),
                    evidence_count=item.get("count", item.get("score", 0)),
                    pmids=item.get("pmids", [])[:10],
                )
            )

        return results

    # ==================== BioNER Annotation ====================

    async def get_annotations(
        self,
        pmid: str,
    ) -> dict:
        """
        Get BioNER annotations for a PubMed article.

        Args:
            pmid: PubMed ID

        Returns:
            dict with annotated entities by type
        """
        data = await self._request("publications/export/pubtator", {"pmids": pmid})
        if not data:
            return {}

        # Parse PubTator format
        annotations: dict[str, list[Any]] = {
            "genes": [],
            "diseases": [],
            "chemicals": [],
            "species": [],
            "variants": [],
        }

        # Parse the response (format depends on API)
        if isinstance(data, dict) and "PubTator3" in data:
            for annotation in data.get("PubTator3", []):
                entity_type = annotation.get("type", "").lower()
                if entity_type in annotations:
                    annotations[entity_type].append(
                        {
                            "text": annotation.get("text", ""),
                            "id": annotation.get("identifier", ""),
                        }
                    )

        return annotations


# ==================== Singleton Factory ====================

_client_instance: PubTatorClient | None = None


def get_pubtator_client() -> PubTatorClient:
    """
    Get singleton PubTator3 client.

    Returns:
        Shared PubTatorClient instance
    """
    global _client_instance
    if _client_instance is None:
        _client_instance = PubTatorClient()
    return _client_instance


async def close_pubtator_client():
    """Close singleton client (for cleanup)."""
    global _client_instance
    if _client_instance is not None:
        await _client_instance.close()
        _client_instance = None
