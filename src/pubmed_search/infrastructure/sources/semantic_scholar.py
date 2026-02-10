"""
Semantic Scholar Integration

Provides cross-domain academic search via Semantic Scholar API.
This is an internal module - not exposed as separate MCP tools.

API Documentation: https://api.semanticscholar.org/api-docs/

Features:
- Cross-domain search (not limited to biomedicine)
- Citation graph analysis
- Author disambiguation
- Paper recommendations
"""

import logging
import urllib.parse
from typing import Any

from pubmed_search.infrastructure.sources.base_client import BaseAPIClient

logger = logging.getLogger(__name__)

# Semantic Scholar API endpoints
S2_API_BASE = "https://api.semanticscholar.org/graph/v1"
S2_SEARCH_URL = f"{S2_API_BASE}/paper/search"
S2_PAPER_URL = f"{S2_API_BASE}/paper"
S2_AUTHOR_URL = f"{S2_API_BASE}/author"

# Default fields to request (optimized for token efficiency)
DEFAULT_FIELDS = [
    "paperId",
    "title",
    "abstract",
    "year",
    "authors",
    "venue",
    "publicationVenue",
    "citationCount",
    "influentialCitationCount",
    "isOpenAccess",
    "openAccessPdf",
    "externalIds",  # Contains DOI, PubMed ID, etc.
]


class SemanticScholarClient(BaseAPIClient):
    """
    Semantic Scholar API client.

    Usage:
        client = SemanticScholarClient()
        results = client.search("deep learning medical imaging", limit=10)
    """

    _service_name = "Semantic Scholar"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0):
        """
        Initialize client.

        Args:
            api_key: Optional S2 API key (increases rate limit from 100 to 1000 req/s)
            timeout: Request timeout in seconds
        """
        self._api_key = api_key
        super().__init__(
            timeout=timeout,
            min_interval=0.5,
            headers={
                "User-Agent": "pubmed-search-mcp/1.0",
                "Accept": "application/json",
            },
        )

    async def _execute_request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Add API key header to requests."""
        req_headers = dict(headers or {})
        if self._api_key:
            req_headers["x-api-key"] = self._api_key
        return await super()._execute_request(
            url, method=method, data=data, headers=req_headers
        )

    async def search(
        self,
        query: str,
        limit: int = 10,
        min_year: int | None = None,
        max_year: int | None = None,
        open_access_only: bool = False,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search Semantic Scholar.

        Args:
            query: Search query
            limit: Maximum results (max 100 per request)
            min_year: Filter by minimum publication year
            max_year: Filter by maximum publication year
            open_access_only: Only return open access papers
            fields: Fields to retrieve (default: DEFAULT_FIELDS)

        Returns:
            List of paper dictionaries in normalized format
        """
        try:
            params = {
                "query": query,
                "limit": str(min(limit, 100)),
                "fields": ",".join(fields or DEFAULT_FIELDS),
            }

            # Year filter
            if min_year or max_year:
                if min_year and max_year:
                    params["year"] = f"{min_year}-{max_year}"
                elif min_year:
                    params["year"] = f"{min_year}-"
                else:
                    params["year"] = f"-{max_year}"

            # Open access filter
            if open_access_only:
                params["openAccessPdf"] = ""  # Only papers with OA PDF

            url = f"{S2_SEARCH_URL}?{urllib.parse.urlencode(params)}"
            data = await self._make_request(url)

            if not isinstance(data, dict):
                return []

            papers = data.get("data", [])

            # Normalize to common format
            return [self._normalize_paper(p) for p in papers]

        except Exception as e:
            logger.error(f"Semantic Scholar search failed: {e}")
            return []

    async def get_paper(
        self, paper_id: str, fields: list[str] | None = None
    ) -> dict[str, Any] | None:
        """
        Get paper by ID (S2 paper ID, DOI, or PubMed ID).

        Args:
            paper_id: Paper identifier (e.g., "DOI:10.1234/example", "PMID:12345678")
            fields: Fields to retrieve

        Returns:
            Paper dictionary or None
        """
        try:
            # URL encode paper_id (important for DOIs)
            encoded_id = urllib.parse.quote(paper_id, safe="")
            params = {"fields": ",".join(fields or DEFAULT_FIELDS)}
            url = f"{S2_PAPER_URL}/{encoded_id}?{urllib.parse.urlencode(params)}"

            data = await self._make_request(url)
            if not isinstance(data, dict):
                return None

            return self._normalize_paper(data)

        except Exception as e:
            logger.error(f"Failed to get paper {paper_id}: {e}")
            return None

    async def get_citations(
        self, paper_id: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """
        Get papers that cite this paper.

        Args:
            paper_id: Paper identifier
            limit: Maximum results

        Returns:
            List of citing papers
        """
        try:
            encoded_id = urllib.parse.quote(paper_id, safe="")
            params = {
                "limit": str(min(limit, 100)),
                "fields": ",".join(DEFAULT_FIELDS),
            }
            url = f"{S2_PAPER_URL}/{encoded_id}/citations?{urllib.parse.urlencode(params)}"

            data = await self._make_request(url)
            if not isinstance(data, dict):
                return []

            papers = [item.get("citingPaper", {}) for item in data.get("data", [])]
            return [self._normalize_paper(p) for p in papers if p]

        except Exception as e:
            logger.error(f"Failed to get citations for {paper_id}: {e}")
            return []

    async def get_references(
        self, paper_id: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """
        Get papers referenced by this paper.

        Args:
            paper_id: Paper identifier
            limit: Maximum results

        Returns:
            List of referenced papers
        """
        try:
            encoded_id = urllib.parse.quote(paper_id, safe="")
            params = {
                "limit": str(min(limit, 100)),
                "fields": ",".join(DEFAULT_FIELDS),
            }
            url = f"{S2_PAPER_URL}/{encoded_id}/references?{urllib.parse.urlencode(params)}"

            data = await self._make_request(url)
            if not isinstance(data, dict):
                return []

            papers = [item.get("citedPaper", {}) for item in data.get("data", [])]
            return [self._normalize_paper(p) for p in papers if p]

        except Exception as e:
            logger.error(f"Failed to get references for {paper_id}: {e}")
            return []

    async def get_recommendations(
        self,
        paper_id: str,
        limit: int = 10,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get paper recommendations based on a seed paper.

        Uses Semantic Scholar's recommendation API which returns papers
        similar to the seed paper, with implicit similarity scores based
        on their ranking in the response.

        Args:
            paper_id: Paper identifier (S2 ID, DOI:xxx, or PMID:xxx)
            limit: Maximum recommendations (max 500)
            fields: Fields to retrieve

        Returns:
            List of recommended papers with similarity_score (0.0-1.0)
        """
        try:
            encoded_id = urllib.parse.quote(paper_id, safe="")
            params = {
                "limit": str(min(limit, 500)),
                "fields": ",".join(fields or DEFAULT_FIELDS),
            }
            # Recommendations endpoint
            url = f"https://api.semanticscholar.org/recommendations/v1/papers/forpaper/{encoded_id}?{urllib.parse.urlencode(params)}"

            data = await self._make_request(url)
            if not isinstance(data, dict):
                return []

            papers = data.get("recommendedPapers", [])
            results = []
            for i, paper in enumerate(papers):
                if paper:
                    normalized = self._normalize_paper(paper)
                    # Calculate similarity score based on ranking position
                    # First result = 1.0, linearly decreasing
                    normalized["similarity_score"] = max(
                        0.0, 1.0 - (i / max(len(papers), 1))
                    )
                    normalized["similarity_source"] = "semantic_scholar"
                    results.append(normalized)

            return results

        except Exception as e:
            logger.error(f"Failed to get recommendations for {paper_id}: {e}")
            return []

    async def get_paper_embedding_similarity(
        self,
        paper_id1: str,
        paper_id2: str,
    ) -> float | None:
        """
        Calculate embedding similarity between two papers.

        Note: S2 doesn't expose raw embeddings, but we can approximate
        by checking if paper2 appears in paper1's recommendations.

        Args:
            paper_id1: First paper identifier
            paper_id2: Second paper identifier

        Returns:
            Similarity score 0.0-1.0, or None if not calculable
        """
        try:
            recommendations = await self.get_recommendations(paper_id1, limit=100)

            for rec in recommendations:
                rec_s2_id = rec.get("_s2_id", "")
                rec_pmid = rec.get("pmid", "")
                rec_doi = rec.get("doi", "")

                # Check if paper_id2 matches any identifier
                paper_id2_clean = paper_id2.replace("PMID:", "").replace("DOI:", "")
                if (
                    (rec_s2_id and rec_s2_id == paper_id2)
                    or (rec_pmid and rec_pmid == paper_id2_clean)
                    or (rec_doi and rec_doi.lower() == paper_id2_clean.lower())
                ):
                    return rec.get("similarity_score", 0.5)

            # Not found in recommendations = low similarity
            return 0.1

        except Exception as e:
            logger.error(f"Failed to calculate similarity: {e}")
            return None

    def _normalize_paper(self, paper: dict[str, Any]) -> dict[str, Any]:
        """
        Normalize S2 paper to common format compatible with PubMed results.

        This allows seamless integration with existing tools.
        """
        external_ids = paper.get("externalIds", {}) or {}
        authors = paper.get("authors", []) or []
        venue = paper.get("publicationVenue") or paper.get("venue") or {}

        # Extract author names
        author_names = []
        authors_full = []
        for author in authors:
            name = author.get("name", "")
            author_names.append(name)
            # Try to split into first/last
            parts = name.rsplit(" ", 1)
            if len(parts) == 2:
                authors_full.append({"fore_name": parts[0], "last_name": parts[1]})
            else:
                authors_full.append({"last_name": name, "fore_name": ""})

        # Journal/venue name
        if isinstance(venue, dict):
            journal = venue.get("name", "")
            journal_abbrev = (
                venue.get("alternate_names", [""])[0]
                if venue.get("alternate_names")
                else ""
            )
        else:
            journal = str(venue) if venue else ""
            journal_abbrev = ""

        return {
            # Core fields - matching PubMed format
            "pmid": external_ids.get("PubMed", ""),
            "title": paper.get("title", ""),
            "abstract": paper.get("abstract", "") or "",
            "year": str(paper.get("year", "")),
            "month": "",
            "day": "",
            "authors": author_names,
            "authors_full": authors_full,
            "journal": journal,
            "journal_abbrev": journal_abbrev,
            "volume": "",
            "issue": "",
            "pages": "",
            "doi": external_ids.get("DOI", ""),
            "pmc_id": external_ids.get("PubMedCentral", ""),
            "keywords": [],
            "mesh_terms": [],
            # Extended IDs
            "arxiv_id": external_ids.get("ArXiv", ""),
            # Metrics (Semantic Scholar specific)
            "citation_count": paper.get("citationCount", 0),
            "influential_citations": paper.get("influentialCitationCount", 0),
            # Access info
            "is_open_access": paper.get("isOpenAccess", False),
            "pdf_url": (paper.get("openAccessPdf") or {}).get("url"),
            # Source marker for identification
            "_source": "semantic_scholar",
            "_s2_id": paper.get("paperId", ""),
        }
