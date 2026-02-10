"""
iCite Module - NIH Citation Metrics Integration

Provides citation metrics from NIH's iCite API:
- citation_count: Total citations
- relative_citation_ratio (RCR): Field-normalized citation metric
- nih_percentile: Percentile among NIH-funded papers
- apt: Approximate Potential to Translate (clinical relevance)

API Documentation: https://icite.od.nih.gov/api
"""

import logging
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

ICITE_API_BASE = "https://icite.od.nih.gov/api/pubs"
MAX_PMIDS_PER_REQUEST = 200  # iCite API limit
ICITE_CACHE_TTL = 1800  # 30 minutes cache for citation metrics


class _ICiteCache:
    """Simple in-memory TTL cache for iCite results."""

    def __init__(self, ttl: int = ICITE_CACHE_TTL):
        self._cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
        self._ttl = ttl

    def get(self, pmid: str) -> Dict[str, Any] | None:
        """Get cached metrics for a PMID, or None if expired/missing."""
        entry = self._cache.get(pmid)
        if entry is None:
            return None
        timestamp, data = entry
        if time.monotonic() - timestamp > self._ttl:
            del self._cache[pmid]
            return None
        return data

    def get_many(self, pmids: List[str]) -> tuple[Dict[str, Dict[str, Any]], List[str]]:
        """Get cached metrics for multiple PMIDs. Returns (cached, missing)."""
        cached: Dict[str, Dict[str, Any]] = {}
        missing: List[str] = []
        for pmid in pmids:
            data = self.get(pmid)
            if data is not None:
                cached[pmid] = data
            else:
                missing.append(pmid)
        return cached, missing

    def put_many(self, results: Dict[str, Dict[str, Any]]) -> None:
        """Cache multiple results at once."""
        now = time.monotonic()
        for pmid, data in results.items():
            self._cache[pmid] = (now, data)

    def __len__(self) -> int:
        return len(self._cache)


class ICiteMixin:
    """
    Mixin providing iCite citation metrics functionality.

    Methods:
        get_citation_metrics: Get citation data for PMIDs
        enrich_with_citations: Add citation metrics to search results
    """

    _icite_client: httpx.AsyncClient | None = None
    _icite_cache: _ICiteCache = _ICiteCache()

    async def _get_icite_client(self) -> httpx.AsyncClient:
        """Get or create a reusable httpx.AsyncClient for iCite."""
        if self._icite_client is None or self._icite_client.is_closed:
            self._icite_client = httpx.AsyncClient(timeout=30.0)
        return self._icite_client

    async def get_citation_metrics(
        self, pmids: List[str], fields: Optional[List[str]] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get citation metrics from iCite API (with in-memory TTL cache).

        Args:
            pmids: List of PubMed IDs
            fields: Specific fields to return (default: all citation-related)

        Returns:
            Dict mapping PMID -> metrics dict
        """
        if not pmids:
            return {}

        # Default fields for citation analysis
        if fields is None:
            fields = [
                "pmid",
                "year",
                "title",
                "journal",
                "citation_count",
                "citations_per_year",
                "relative_citation_ratio",
                "nih_percentile",
                "expected_citations_per_year",
                "field_citation_rate",
                "apt",
                "is_clinical",
                "cited_by_clin",
                "human",
                "animal",
                "molecular_cellular",
            ]

        # Check cache first
        cached, missing = self._icite_cache.get_many(pmids)
        if not missing:
            logger.debug(f"iCite cache hit: all {len(pmids)} PMIDs cached")
            return cached

        if cached:
            logger.debug(
                f"iCite cache: {len(cached)} hits, {len(missing)} misses"
            )

        results = dict(cached)  # Start with cached results

        # Fetch only missing PMIDs in batches
        for i in range(0, len(missing), MAX_PMIDS_PER_REQUEST):
            batch = missing[i : i + MAX_PMIDS_PER_REQUEST]
            batch_results = await self._fetch_icite_batch(batch, fields)
            results.update(batch_results)
            # Cache the new results
            self._icite_cache.put_many(batch_results)

        return results

    async def _fetch_icite_batch(
        self, pmids: List[str], fields: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Fetch a single batch from iCite API."""
        try:
            params = {"pmids": ",".join(str(p) for p in pmids), "fl": ",".join(fields)}

            client = await self._get_icite_client()
            response = await client.get(ICITE_API_BASE, params=params)
            response.raise_for_status()

            data = response.json()

            # Map by PMID for easy lookup
            results = {}
            for item in data.get("data", []):
                pmid = str(item.get("pmid", ""))
                if pmid:
                    results[pmid] = item

            return results

        except httpx.HTTPError as e:
            logger.error(f"iCite API request failed: {e}")
            return {}
        except Exception as e:
            logger.error(f"iCite processing error: {e}")
            return {}

    async def enrich_with_citations(
        self, articles: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Enrich article list with iCite citation metrics.

        Args:
            articles: List of article dicts (must have 'pmid' field)

        Returns:
            Articles with added 'icite' field containing metrics
        """
        if not articles:
            return articles

        # Extract PMIDs
        pmids = [str(a.get("pmid", "")) for a in articles if a.get("pmid")]

        if not pmids:
            return articles

        # Fetch metrics
        metrics = await self.get_citation_metrics(pmids)

        # Enrich articles
        enriched = []
        for article in articles:
            pmid = str(article.get("pmid", ""))
            article_copy = article.copy()

            if pmid in metrics:
                article_copy["icite"] = metrics[pmid]

            enriched.append(article_copy)

        return enriched

    def sort_by_citations(
        self,
        articles: List[Dict[str, Any]],
        metric: str = "citation_count",
        descending: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Sort articles by citation metric.

        Args:
            articles: List of enriched articles (with 'icite' field)
            metric: Which metric to sort by:
                - citation_count: Raw citation count
                - relative_citation_ratio: Field-normalized (recommended)
                - nih_percentile: Percentile ranking
                - citations_per_year: Citation velocity
            descending: Sort high to low (default True)

        Returns:
            Sorted article list
        """

        def get_metric(article):
            icite = article.get("icite", {})
            value = icite.get(metric)
            # Handle None/missing values - put at end
            if value is None:
                return float("-inf") if descending else float("inf")
            return value

        return sorted(articles, key=get_metric, reverse=descending)

    def filter_by_citations(
        self,
        articles: List[Dict[str, Any]],
        min_citations: Optional[int] = None,
        min_rcr: Optional[float] = None,
        min_percentile: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Filter articles by citation thresholds.

        Args:
            articles: List of enriched articles
            min_citations: Minimum citation count
            min_rcr: Minimum Relative Citation Ratio
            min_percentile: Minimum NIH percentile

        Returns:
            Filtered article list
        """
        filtered = []

        for article in articles:
            icite = article.get("icite", {})

            # Check citation count
            if min_citations is not None:
                count = icite.get("citation_count", 0) or 0
                if count < min_citations:
                    continue

            # Check RCR
            if min_rcr is not None:
                rcr = icite.get("relative_citation_ratio")
                if rcr is None or rcr < min_rcr:
                    continue

            # Check percentile
            if min_percentile is not None:
                percentile = icite.get("nih_percentile")
                if percentile is None or percentile < min_percentile:
                    continue

            filtered.append(article)

        return filtered
