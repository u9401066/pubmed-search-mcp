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

from __future__ import annotations

import logging
import math
import re
import urllib.parse
from typing import TYPE_CHECKING, Any

from pubmed_search.application.search.source_models import SourceSearchPage, coerce_optional_total
from pubmed_search.infrastructure.sources.base_client import (
    _CONTINUE,
    APIRequestError,
    BaseAPIClient,
    raise_provider_schema_error,
    raise_sanitized_retryable_error,
)
from pubmed_search.infrastructure.sources.official_generated_clients import (
    OfficialSemanticScholarGeneratedClient,
    SemanticScholarSearchRequest,
)
from pubmed_search.shared.async_utils import RetryableOperationError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import httpx

# Semantic Scholar API endpoints
S2_API_BASE = "https://api.semanticscholar.org/graph/v1"
S2_SEARCH_URL = f"{S2_API_BASE}/paper/search"
S2_BULK_SEARCH_URL = f"{S2_API_BASE}/paper/search/bulk"
S2_PAPER_BATCH_URL = f"{S2_API_BASE}/paper/batch"
S2_PAPER_URL = f"{S2_API_BASE}/paper"
S2_AUTHOR_URL = f"{S2_API_BASE}/author"
S2_RELEVANCE_MAX_RESULTS = 100
S2_BULK_MAX_RESULTS = 10_000_000
S2_BULK_MAX_PAGES = 10_000
S2_BATCH_MAX_IDS = 500
_S2_BULK_SORT_PATTERN = re.compile(r"^(paperId|publicationDate|citationCount)(?::(asc|desc))?$")
_PUBMED_FIELD_TAG_PATTERN = re.compile(r"\[[^\]]+\]")

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

DEFAULT_AUTHOR_FIELDS = [
    "authorId",
    "name",
    "aliases",
    "affiliations",
    "homepage",
    "paperCount",
    "citationCount",
    "hIndex",
    "externalIds",
    "url",
]


def _require_result_list(value: object) -> list[object]:
    """Validate provider collection shape without accepting false-empty drift."""
    if not isinstance(value, list):
        raise TypeError("Semantic Scholar data must be a list")
    return value


def compile_semantic_scholar_bulk_query(query: str) -> str:
    """Compile common Boolean syntax to S2 bulk syntax without silent loss."""

    normalized = query.strip()
    if not normalized:
        raise ValueError("Semantic Scholar bulk search requires a non-empty query")
    if _PUBMED_FIELD_TAG_PATTERN.search(normalized):
        raise ValueError("PubMed field tags cannot be translated safely to Semantic Scholar bulk search")
    segments = re.split(r'("(?:[^"\\]|\\.)*")', normalized)
    outside_quotes = "".join(segments[::2])
    if '"' in outside_quotes:
        raise ValueError("Semantic Scholar bulk query contains an unbalanced quote")
    depth = 0
    for character in outside_quotes:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("Semantic Scholar bulk query contains unbalanced parentheses")
    if depth:
        raise ValueError("Semantic Scholar bulk query contains unbalanced parentheses")

    for index in range(0, len(segments), 2):
        segment = segments[index]
        segment = re.sub(r"\bNOT\s+", "-", segment, flags=re.IGNORECASE)
        segment = re.sub(r"\bAND\b", "+", segment, flags=re.IGNORECASE)
        segment = re.sub(r"\bOR\b", "|", segment, flags=re.IGNORECASE)
        segments[index] = segment
    return " ".join("".join(segments).split())


class SemanticScholarClient(BaseAPIClient):
    """
    Semantic Scholar API client.

    Usage:
        client = SemanticScholarClient()
        page = await client.search_page("deep learning medical imaging", limit=10)
    """

    _service_name = "Semantic Scholar"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0):
        """
        Initialize client.

        Args:
            api_key: Optional S2 API key for higher Semantic Scholar quota
            timeout: Request timeout in seconds
        """
        self._api_key = api_key
        super().__init__(
            timeout=timeout,
            # New API keys start at one request per second across endpoints.
            # Higher grants should be introduced through explicit configuration,
            # never inferred merely from the presence of a key.
            min_interval=1.0,
            headers={
                "User-Agent": "pubmed-search-mcp/1.0",
                "Accept": "application/json",
            },
            follow_redirects=False,
        )
        self._official_client = OfficialSemanticScholarGeneratedClient(self)

    def _handle_expected_status(self, response: httpx.Response, url: str) -> Any:
        """Treat only a real provider 404 as an absent Semantic Scholar entity."""

        if response.status_code == 404:
            return None
        return _CONTINUE

    async def _execute_request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Add API key header to requests."""
        req_headers = dict(headers or {})
        if self._api_key:
            req_headers["x-api-key"] = self._api_key
        return await super()._execute_request(url, method=method, data=data, params=params, headers=req_headers)

    async def search_page(
        self,
        query: str,
        limit: int = 10,
        min_year: int | None = None,
        max_year: int | None = None,
        open_access_only: bool = False,
        fields: list[str] | None = None,
        offset: int = 0,
    ) -> SourceSearchPage[dict[str, Any]]:
        """Return one relevance-ranked page of raw Semantic Scholar DTOs."""

        page_limit = max(1, min(limit, S2_RELEVANCE_MAX_RESULTS))
        if offset < 0 or offset + page_limit > 1_000:
            raise ValueError("Semantic Scholar relevance search window is limited to 1,000 results")
        try:
            params: dict[str, str | int | None] = {
                "query": query,
                "limit": page_limit,
                "offset": offset,
                "fields": ",".join(fields or DEFAULT_FIELDS),
                "year": self._year_filter(min_year, max_year),
                "openAccessPdf": "" if open_access_only else None,
            }
            request = SemanticScholarSearchRequest.model_validate(params)
            response = await self._official_client.search_papers(request)
            if response is None:
                raise_provider_schema_error(self._service_name)

            total, warnings = coerce_optional_total(response.total)
            return SourceSearchPage(
                source="semantic_scholar",
                items=[paper.model_dump(exclude_none=True) for paper in response.data],
                total=total,
                next_token=response.next,
                query=query,
                warnings=warnings,
                mode="relevance",
                metadata={"offset": response.offset},
            )
        except RetryableOperationError as exc:
            raise_sanitized_retryable_error(self._service_name, exc)
        except APIRequestError:
            raise
        except Exception as exc:
            logger.warning("Semantic Scholar search failed (%s)", type(exc).__name__)
        raise APIRequestError(self._service_name)

    async def bulk_search_page(
        self,
        query: str,
        *,
        token: str | None = None,
        min_year: int | None = None,
        max_year: int | None = None,
        open_access_only: bool = False,
        fields: list[str] | None = None,
        sort: str = "paperId",
    ) -> SourceSearchPage[dict[str, Any]]:
        """Return one raw S2 bulk page; continuation tokens stay opaque."""

        if not query.strip():
            raise ValueError("Semantic Scholar bulk search requires a non-empty query")
        if not _S2_BULK_SORT_PATTERN.fullmatch(sort):
            raise ValueError("Unsupported Semantic Scholar bulk sort")

        try:
            params: dict[str, str] = {
                "query": query,
                "fields": ",".join(fields or DEFAULT_FIELDS),
                "sort": sort,
            }
            if token:
                params["token"] = token
            year = self._year_filter(min_year, max_year)
            if year:
                params["year"] = year
            if open_access_only:
                params["openAccessPdf"] = ""

            url = f"{S2_BULK_SEARCH_URL}?{urllib.parse.urlencode(params)}"
            payload = await self._make_request(url)
            if not isinstance(payload, dict):
                raise_provider_schema_error(self._service_name)

            raw_data = payload.get("data")
            if raw_data is None and payload.get("total") == 0 and not isinstance(payload.get("total"), bool):
                raw_data = []
            raw_data = _require_result_list(raw_data)
            if any(not isinstance(paper, dict) for paper in raw_data):
                raise_provider_schema_error(self._service_name)
            items = [paper for paper in raw_data if isinstance(paper, dict)]
            total, warnings = coerce_optional_total(payload.get("total"))
            next_token = payload.get("token")
            if next_token is not None and not isinstance(next_token, str):
                raise_provider_schema_error(self._service_name)
            return SourceSearchPage(
                source="semantic_scholar",
                items=items,
                total=total,
                next_token=next_token,
                query=query,
                warnings=warnings,
                mode="bulk",
                metadata={"sort": sort},
            )
        except RetryableOperationError as exc:
            raise_sanitized_retryable_error(self._service_name, exc)
        except APIRequestError:
            raise
        except Exception as exc:
            logger.warning("Semantic Scholar bulk search failed (%s)", type(exc).__name__)
        raise APIRequestError(self._service_name)

    async def bulk_search(
        self,
        query: str,
        *,
        max_results: int = 1_000,
        max_pages: int = 10,
        min_year: int | None = None,
        max_year: int | None = None,
        open_access_only: bool = False,
        fields: list[str] | None = None,
        sort: str = "paperId",
    ) -> SourceSearchPage[dict[str, Any]]:
        """Run a bounded S2 bulk-token traversal without approaching corpus scale."""

        if (
            isinstance(max_results, bool)
            or not isinstance(max_results, int)
            or not 1 <= max_results <= S2_BULK_MAX_RESULTS
        ):
            raise ValueError(f"max_results must be between 1 and {S2_BULK_MAX_RESULTS}")
        if isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= S2_BULK_MAX_PAGES:
            raise ValueError(f"max_pages must be between 1 and {S2_BULK_MAX_PAGES}")

        items: list[dict[str, Any]] = []
        warnings: list[str] = []
        seen_tokens: set[str] = set()
        token: str | None = None
        total: int | None = None
        pages_fetched = 0
        truncated_page = False

        while pages_fetched < max_pages and len(items) < max_results:
            page = await self.bulk_search_page(
                query,
                token=token,
                min_year=min_year,
                max_year=max_year,
                open_access_only=open_access_only,
                fields=fields,
                sort=sort,
            )
            pages_fetched += 1
            remaining = max_results - len(items)
            items.extend(page.items[:remaining])
            warnings.extend(page.warnings)
            total = page.total if total is None else total
            if len(page.items) > remaining:
                truncated_page = True
                token = None
                warnings.append(
                    "Semantic Scholar stopped within a bulk page; no continuation token can resume the unconsumed records. Increase max_results to retrieve the full page."
                )
                break
            next_token = page.next_token if isinstance(page.next_token, str) else None
            if not next_token:
                token = None
                break
            if next_token in seen_tokens:
                warnings.append("Semantic Scholar returned a repeated bulk token; pagination stopped")
                token = next_token
                break
            seen_tokens.add(next_token)
            token = next_token

        if token and pages_fetched >= max_pages and len(items) < max_results:
            warnings.append("Semantic Scholar bulk pagination stopped at max_pages")

        return SourceSearchPage(
            source="semantic_scholar",
            items=items,
            total=total,
            next_token=token,
            query=query,
            warnings=warnings,
            mode="bulk",
            metadata={"pages_fetched": pages_fetched, "bounded": True, "sort": sort, "truncated_page": truncated_page},
        )

    async def get_papers_batch(
        self,
        paper_ids: list[str],
        *,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any] | None]:
        """Fetch up to 500 paper DTOs while preserving response order/nulls."""

        if len(paper_ids) > S2_BATCH_MAX_IDS:
            raise ValueError(f"Semantic Scholar paper batch accepts at most {S2_BATCH_MAX_IDS} IDs")
        if not paper_ids:
            return []
        params = {"fields": ",".join(fields or DEFAULT_FIELDS)}
        url = f"{S2_PAPER_BATCH_URL}?{urllib.parse.urlencode(params)}"
        # The shared transport historically annotates JSON roots as mappings;
        # this official endpoint is the intentional array-root exception.
        payload: Any = await self._make_request(url, method="POST", data={"ids": paper_ids})
        if not isinstance(payload, list):
            raise_provider_schema_error(self._service_name)
        if len(payload) != len(paper_ids) or any(
            paper is not None and not isinstance(paper, dict) for paper in payload
        ):
            raise APIRequestError(self._service_name)
        return [paper if isinstance(paper, dict) else None for paper in payload]

    @staticmethod
    def _year_filter(min_year: int | None, max_year: int | None) -> str | None:
        if min_year and max_year:
            return f"{min_year}-{max_year}"
        if min_year:
            return f"{min_year}-"
        if max_year:
            return f"-{max_year}"
        return None

    async def get_paper(self, paper_id: str, fields: list[str] | None = None) -> dict[str, Any] | None:
        """
        Get paper by ID (S2 paper ID, DOI, or PubMed ID).

        Args:
            paper_id: Paper identifier (e.g., "DOI:10.1234/example", "PMID:12345678")
            fields: Fields to retrieve

        Returns:
            Paper dictionary or None
        """
        try:
            response = await self._official_client.get_paper(
                paper_id,
                fields=",".join(fields or DEFAULT_FIELDS),
            )
            if response is None:
                return None

            return self._normalize_paper(response.model_dump(exclude_none=True))

        except APIRequestError:
            raise
        except RetryableOperationError as exc:
            raise_sanitized_retryable_error(self._service_name, exc)
        except Exception as exc:
            logger.warning("Semantic Scholar paper lookup failed (%s)", type(exc).__name__)
            raise APIRequestError(self._service_name) from exc

    async def get_citations(self, paper_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """
        Get papers that cite this paper.

        Args:
            paper_id: Paper identifier
            limit: Maximum results

        Returns:
            List of citing papers
        """
        try:
            response = await self._official_client.get_citations(
                paper_id,
                limit=min(limit, 100),
                fields=",".join(DEFAULT_FIELDS),
            )
            if response is None:
                return []

            papers = [item.citingPaper.model_dump(exclude_none=True) for item in response.data if item.citingPaper]
            return [self._normalize_paper(paper) for paper in papers]

        except APIRequestError:
            raise
        except RetryableOperationError as exc:
            raise_sanitized_retryable_error(self._service_name, exc)
        except Exception as exc:
            logger.warning("Semantic Scholar citation lookup failed (%s)", type(exc).__name__)
            raise APIRequestError(self._service_name) from exc

    async def get_references(self, paper_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """
        Get papers referenced by this paper.

        Args:
            paper_id: Paper identifier
            limit: Maximum results

        Returns:
            List of referenced papers
        """
        try:
            response = await self._official_client.get_references(
                paper_id,
                limit=min(limit, 100),
                fields=",".join(DEFAULT_FIELDS),
            )
            if response is None:
                return []

            papers = [item.citedPaper.model_dump(exclude_none=True) for item in response.data if item.citedPaper]
            return [self._normalize_paper(paper) for paper in papers]

        except APIRequestError:
            raise
        except RetryableOperationError as exc:
            raise_sanitized_retryable_error(self._service_name, exc)
        except Exception as exc:
            logger.warning("Semantic Scholar reference lookup failed (%s)", type(exc).__name__)
            raise APIRequestError(self._service_name) from exc

    async def get_recommendations(
        self,
        paper_id: str,
        limit: int = 10,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get paper recommendations based on a seed paper.

        Uses Semantic Scholar's recommendation API. The upstream response is
        ordered; this client exposes that order only as a rank percentile and
        does not claim a semantic-similarity measurement.

        Args:
            paper_id: Paper identifier (S2 ID, DOI:xxx, or PMID:xxx)
            limit: Maximum recommendations (max 500)
            fields: Fields to retrieve

        Returns:
            Recommended papers with ``rank_percentile`` metadata (0.0-1.0)
        """
        try:
            response = await self._official_client.get_recommendations(
                paper_id,
                limit=min(limit, 500),
                fields=",".join(fields or DEFAULT_FIELDS),
            )
            if response is None:
                return []

            papers = response.recommendedPapers
            results = []
            for i, paper in enumerate(papers):
                normalized = self._normalize_paper(paper.model_dump(exclude_none=True))
                normalized["rank_percentile"] = (len(papers) - i) / len(papers)
                normalized["rank_percentile_source"] = "semantic_scholar_recommendation_order"
                results.append(normalized)

            return results

        except APIRequestError:
            raise
        except RetryableOperationError as exc:
            raise_sanitized_retryable_error(self._service_name, exc)
        except Exception as exc:
            logger.warning("Semantic Scholar recommendation lookup failed (%s)", type(exc).__name__)
            raise APIRequestError(self._service_name) from exc

    async def search_authors(
        self,
        query: str,
        limit: int = 10,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search Semantic Scholar authors by name.

        Args:
            query: Author name query.
            limit: Maximum authors to return.
            fields: Optional author field selection.

        Returns:
            List of normalized author metadata dictionaries.
        """
        try:
            params = {
                "query": query,
                "limit": str(min(limit, 100)),
                "fields": ",".join(fields or DEFAULT_AUTHOR_FIELDS),
            }
            url = f"{S2_AUTHOR_URL}/search?{urllib.parse.urlencode(params)}"
            data = await self._make_request(url)
            if not isinstance(data, dict):
                raise_provider_schema_error(self._service_name)

            authors = data.get("data")
            if not isinstance(authors, list) or any(not isinstance(author, dict) for author in authors):
                raise_provider_schema_error(self._service_name)

            return [self._normalize_author(author) for author in authors]
        except APIRequestError:
            raise
        except RetryableOperationError as exc:
            raise_sanitized_retryable_error(self._service_name, exc)
        except Exception as exc:
            logger.warning("Semantic Scholar author search failed (%s)", type(exc).__name__)
            raise APIRequestError(self._service_name) from exc

    async def get_author(self, author_id: str, fields: list[str] | None = None) -> dict[str, Any] | None:
        """
        Get an author profile by Semantic Scholar author identifier.

        Args:
            author_id: Semantic Scholar author identifier.
            fields: Optional author field selection.

        Returns:
            Normalized author metadata or ``None`` when the author is not found.
        """
        try:
            encoded_id = urllib.parse.quote(author_id, safe="")
            params = {"fields": ",".join(fields or DEFAULT_AUTHOR_FIELDS)}
            url = f"{S2_AUTHOR_URL}/{encoded_id}?{urllib.parse.urlencode(params)}"

            data = await self._make_request(url)
            if data is None:
                return None
            if not isinstance(data, dict):
                raise_provider_schema_error(self._service_name)

            return self._normalize_author(data)
        except APIRequestError:
            raise
        except RetryableOperationError as exc:
            raise_sanitized_retryable_error(self._service_name, exc)
        except Exception as exc:
            logger.warning("Semantic Scholar author lookup failed (%s)", type(exc).__name__)
            raise APIRequestError(self._service_name) from exc

    async def get_recommendation_rank_percentile(
        self,
        paper_id1: str,
        paper_id2: str,
    ) -> float | None:
        """
        Return a target paper's percentile within a bounded recommendation list.

        Semantic Scholar does not expose an embedding score here. Absence from
        the first 100 recommendations yields ``None`` rather than an invented
        low-similarity value.

        Args:
            paper_id1: First paper identifier
            paper_id2: Second paper identifier

        Returns:
            Rank percentile 0.0-1.0, or ``None`` if not observed/calculable
        """
        try:
            recommendations = await self.get_recommendations(paper_id1, limit=100)

            for rec in recommendations:
                rec_s2_id = rec.get("_s2_id", "")
                rec_pmid = rec.get("pmid", "")
                rec_doi = rec.get("doi", "")

                # Check if paper_id2 matches any identifier
                paper_id2_clean = re.sub(r"^(?:PMID|DOI):", "", paper_id2, flags=re.IGNORECASE)
                if (
                    (rec_s2_id and rec_s2_id == paper_id2)
                    or (rec_pmid and rec_pmid == paper_id2_clean)
                    or (rec_doi and rec_doi.lower() == paper_id2_clean.lower())
                ):
                    rank_percentile = rec.get("rank_percentile")
                    if isinstance(rank_percentile, bool) or not isinstance(rank_percentile, int | float):
                        return None
                    return (
                        float(rank_percentile) if math.isfinite(rank_percentile) and 0 <= rank_percentile <= 1 else None
                    )

            return None

        except APIRequestError:
            raise
        except RetryableOperationError as exc:
            raise_sanitized_retryable_error(self._service_name, exc)
        except Exception as exc:
            logger.warning("Semantic Scholar recommendation-rank lookup failed (%s)", type(exc).__name__)
            raise APIRequestError(self._service_name) from exc

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
            journal_abbrev = venue.get("alternate_names", [""])[0] if venue.get("alternate_names") else ""
        else:
            journal = str(venue) if venue else ""
            journal_abbrev = ""

        return {
            # Core fields - matching PubMed format
            "pmid": external_ids.get("PubMed", ""),
            "title": paper.get("title", ""),
            "abstract": paper.get("abstract", "") or "",
            "year": str(paper["year"]) if paper.get("year") is not None else "",
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

    @staticmethod
    def _normalize_author(author: dict[str, Any]) -> dict[str, Any]:
        """Normalize Semantic Scholar author metadata for downstream reuse.

        Args:
            author: Raw author payload from Semantic Scholar.

        Returns:
            Compact normalized author metadata.
        """
        external_ids = author.get("externalIds", {}) or {}
        return {
            "author_id": author.get("authorId", ""),
            "name": author.get("name", ""),
            "aliases": author.get("aliases", []) or [],
            "affiliations": author.get("affiliations", []) or [],
            "homepage": author.get("homepage", "") or "",
            "profile_url": author.get("url", "") or "",
            "paper_count": author.get("paperCount", 0),
            "citation_count": author.get("citationCount", 0),
            "h_index": author.get("hIndex"),
            "orcid": external_ids.get("ORCID", ""),
            "_source": "semantic_scholar",
        }
