"""
OpenAlex Integration

Provides open access academic search via OpenAlex API.
This is an internal module - not exposed as separate MCP tools.

API Documentation: https://help.openalex.org/api/

Features:
- Credit-aware anonymous or API-key access
- Open access filter (DOAJ integration built-in)
- Comprehensive coverage (200M+ works)
- Institution and concept relationships
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any, NoReturn

from pubmed_search.application.search.source_models import SourceSearchPage, coerce_optional_total
from pubmed_search.infrastructure.sources.base_client import APIRequestError, BaseAPIClient
from pubmed_search.infrastructure.sources.contact import first_contact_email, get_configured_source_contact_email
from pubmed_search.shared.async_utils import RetryableOperationError, get_rate_limiter

logger = logging.getLogger(__name__)

# OpenAlex API endpoints
OA_API_BASE = "https://api.openalex.org"
OA_WORKS_URL = f"{OA_API_BASE}/works"
OA_AUTHORS_URL = f"{OA_API_BASE}/authors"

DEFAULT_EMAIL = "pubmed-search-mcp@example.com"

# ``select`` only accepts root fields.  Keep this provider DTO compact while
# retaining every field needed by the domain mapper.
OPENALEX_WORK_SELECT = (
    "id",
    "doi",
    "ids",
    "title",
    "display_name",
    "abstract_inverted_index",
    "authorships",
    "publication_year",
    "publication_date",
    "type",
    "open_access",
    "best_oa_location",
    "primary_location",
    "cited_by_count",
)
OPENALEX_MAX_PER_PAGE = 100
OPENALEX_SEMANTIC_MAX_QUERY_CHARS = 2_000
OPENALEX_SEMANTIC_MAX_RESULTS = 50
OPENALEX_CURSOR_MAX_RESULTS = 100_000
OPENALEX_CURSOR_MAX_PAGES = 1_000


def _raise_retryable_error(error: RetryableOperationError | None) -> None:
    if error is not None:
        raise RetryableOperationError(
            str(error),
            retry_after=error.retry_after,
            status_code=error.status_code,
        )


def _raise_api_request_error(service_name: str) -> NoReturn:
    """Raise outside request parsing blocks so the public error stays sanitized."""
    raise APIRequestError(service_name)


def _require_result_list(value: object) -> list[object]:
    """Validate the provider collection shape without accepting false-empty drift."""
    if not isinstance(value, list):
        raise TypeError("OpenAlex results must be a list")
    return value


class OpenAlexClient(BaseAPIClient):
    """
    OpenAlex API client.

    Usage:
        client = OpenAlexClient(email="your@email.com")
        results = client.search("CRISPR gene editing", limit=10, open_access_only=True)
    """

    _service_name = "OpenAlex"

    def __init__(self, email: str | None = None, api_key: str | None = None, timeout: float = 30.0):
        """
        Initialize client.

        Args:
            email: Contact email used for responsible anonymous access.
            api_key: Optional OpenAlex API key for a larger daily credit budget.
            timeout: Request timeout in seconds
        """
        self._email = first_contact_email(email, get_configured_source_contact_email(), DEFAULT_EMAIL) or DEFAULT_EMAIL
        self._api_key = api_key.strip() if isinstance(api_key, str) and api_key.strip() else None
        # Keep credentials out of URLs: exceptions and reverse-proxy access
        # logs commonly include the complete query string. OpenAlex supports a
        # Bearer API key, while ``mailto`` remains a non-secret contact hint.
        self._auth_params = {"mailto": self._email}
        request_headers = {
            "User-Agent": f"pubmed-search-mcp/1.0 (mailto:{self._email})",
            "Accept": "application/json",
        }
        if self._api_key:
            request_headers["Authorization"] = f"Bearer {self._api_key}"
        super().__init__(
            timeout=timeout,
            min_interval=0.1,
            headers=request_headers,
            follow_redirects=False,
        )

    async def search(
        self,
        query: str,
        limit: int = 10,
        min_year: int | None = None,
        max_year: int | None = None,
        open_access_only: bool = False,
        is_doaj: bool = False,
        sort: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search OpenAlex and return the legacy normalized list contract.

        Unified search uses :meth:`search_page` instead so raw OpenAlex DTOs
        cross the domain mapper exactly once.

        Args:
            query: Search query (searches title, abstract, fulltext)
            limit: Maximum results (max 100 per page)
            min_year: Filter by minimum publication year
            max_year: Filter by maximum publication year
            open_access_only: Only return open access works
            is_doaj: Only return works from DOAJ journals
            sort: Sort order. Options:
                  - None (default): Use OpenAlex default (relevance when searching)
                  - "cited_by_count:desc": Most cited first
                  - "publication_date:desc": Most recent first
                  Note: "relevance_score" only works when search is active

        Returns:
            List of work dictionaries in normalized format
        """
        try:
            page = await self.search_page(
                query,
                limit=limit,
                min_year=min_year,
                max_year=max_year,
                open_access_only=open_access_only,
                is_doaj=is_doaj,
                sort=sort,
            )
        except APIRequestError as exc:
            logger.warning("OpenAlex legacy search returned no items (%s)", type(exc).__name__)
            return []
        return [self._normalize_work(work) for work in page.items]

    async def search_page(
        self,
        query: str,
        limit: int = 10,
        min_year: int | None = None,
        max_year: int | None = None,
        open_access_only: bool = False,
        is_doaj: bool = False,
        sort: str | None = None,
        *,
        cursor: str | None = None,
    ) -> SourceSearchPage[dict[str, Any]]:
        """Return one keyword-search page containing raw OpenAlex work DTOs."""

        return await self._search_work_page(
            query_parameter="search",
            query=query,
            limit=limit,
            min_year=min_year,
            max_year=max_year,
            open_access_only=open_access_only,
            is_doaj=is_doaj,
            sort=sort,
            cursor=cursor,
            mode="keyword",
        )

    async def search_semantic_page(
        self,
        query: str,
        limit: int = 10,
        min_year: int | None = None,
        max_year: int | None = None,
        open_access_only: bool = False,
        is_doaj: bool = False,
    ) -> SourceSearchPage[dict[str, Any]]:
        """Run native OpenAlex semantic search within its hard API limits."""

        if len(query) > OPENALEX_SEMANTIC_MAX_QUERY_CHARS:
            msg = f"OpenAlex semantic queries are limited to {OPENALEX_SEMANTIC_MAX_QUERY_CHARS} characters"
            raise ValueError(msg)
        semantic_limiter = get_rate_limiter(
            "source:openalex:semantic",
            rate=1.0,
            per=1.0,
            conservative=True,
        )
        await semantic_limiter.acquire()
        return await self._search_work_page(
            query_parameter="search.semantic",
            query=query,
            limit=min(limit, OPENALEX_SEMANTIC_MAX_RESULTS),
            min_year=min_year,
            max_year=max_year,
            open_access_only=open_access_only,
            is_doaj=is_doaj,
            sort=None,
            cursor=None,
            mode="semantic",
        )

    async def search_cursor(
        self,
        query: str,
        *,
        max_results: int = 1_000,
        max_pages: int = 10,
        min_year: int | None = None,
        max_year: int | None = None,
        open_access_only: bool = False,
        is_doaj: bool = False,
        sort: str | None = None,
    ) -> SourceSearchPage[dict[str, Any]]:
        """Traverse keyword results with an explicitly bounded cursor loop."""

        if not 1 <= max_results <= OPENALEX_CURSOR_MAX_RESULTS:
            msg = f"max_results must be between 1 and {OPENALEX_CURSOR_MAX_RESULTS}"
            raise ValueError(msg)
        if not 1 <= max_pages <= OPENALEX_CURSOR_MAX_PAGES:
            msg = f"max_pages must be between 1 and {OPENALEX_CURSOR_MAX_PAGES}"
            raise ValueError(msg)

        items: list[dict[str, Any]] = []
        warnings: list[str] = []
        seen_cursors: set[str] = set()
        cursor = "*"
        total: int | None = None
        canonical_query: str | None = query
        total_cost = 0.0
        cost_seen = False
        pages_fetched = 0

        while cursor and pages_fetched < max_pages and len(items) < max_results:
            if cursor in seen_cursors:
                warnings.append("OpenAlex returned a repeated cursor; pagination stopped")
                break
            seen_cursors.add(cursor)
            page = await self.search_page(
                query,
                limit=min(OPENALEX_MAX_PER_PAGE, max_results - len(items)),
                min_year=min_year,
                max_year=max_year,
                open_access_only=open_access_only,
                is_doaj=is_doaj,
                sort=sort,
                cursor=cursor,
            )
            pages_fetched += 1
            items.extend(page.items[: max_results - len(items)])
            warnings.extend(page.warnings)
            total = page.total if total is None else total
            canonical_query = page.query or canonical_query
            if page.cost is not None:
                total_cost += page.cost
                cost_seen = True
            cursor = page.cursor or ""

        if cursor and pages_fetched >= max_pages and len(items) < max_results:
            warnings.append("OpenAlex cursor pagination stopped at max_pages")

        return SourceSearchPage(
            source="openalex",
            items=items,
            total=total,
            cursor=cursor or None,
            query=canonical_query,
            cost=total_cost if cost_seen else None,
            warnings=warnings,
            mode="keyword",
            metadata={"pages_fetched": pages_fetched, "bounded": True},
        )

    async def _search_work_page(
        self,
        *,
        query_parameter: str,
        query: str,
        limit: int,
        min_year: int | None,
        max_year: int | None,
        open_access_only: bool,
        is_doaj: bool,
        sort: str | None,
        cursor: str | None,
        mode: str,
    ) -> SourceSearchPage[dict[str, Any]]:
        """Execute one works request without normalizing provider DTOs."""

        try:
            filters = self._build_work_filters(
                min_year=min_year,
                max_year=max_year,
                open_access_only=open_access_only,
                is_doaj=is_doaj,
            )
            params = {
                query_parameter: query,
                "per_page": str(max(1, min(limit, OPENALEX_MAX_PER_PAGE))),
                "select": ",".join(OPENALEX_WORK_SELECT),
                **self._auth_params,
            }
            if sort:
                params["sort"] = sort
            if filters:
                params["filter"] = ",".join(filters)
            if cursor is not None:
                params["cursor"] = cursor

            url = f"{OA_WORKS_URL}?{urllib.parse.urlencode(params)}"
            data = await self._make_request(url)
            if not isinstance(data, dict):
                retryable = self.last_retryable_error
                _raise_retryable_error(retryable)
                _raise_api_request_error(self._service_name)

            raw_results = data.get("results")
            if raw_results is None:
                raw_results = []
            raw_results = _require_result_list(raw_results)
            works = [work for work in raw_results if isinstance(work, dict)]
            meta = data.get("meta") or {}
            total, warnings = coerce_optional_total(meta.get("count"))
            raw_x_query = meta.get("x_query")
            if isinstance(raw_x_query, str):
                canonical_query = raw_x_query
            elif isinstance(raw_x_query, dict) and isinstance(raw_x_query.get("oql"), str):
                canonical_query = raw_x_query["oql"]
            else:
                canonical_query = query
            next_cursor = meta.get("next_cursor")
            if not isinstance(next_cursor, str):
                next_cursor = None
            cost = self._coerce_cost(meta.get("cost_usd"), warnings)
            rate_limit = self.last_rate_limit_headers
            self._append_low_credit_warning(rate_limit, warnings)
            return SourceSearchPage(
                source="openalex",
                items=works,
                total=total,
                cursor=next_cursor,
                query=canonical_query,
                cost=cost,
                warnings=warnings,
                mode=mode,
                metadata={
                    "request_query": query,
                    "meta": {key: value for key, value in meta.items() if key != "x_query"},
                    "x_query": (
                        {key: value for key, value in raw_x_query.items() if key in {"oql", "oqo"}}
                        if isinstance(raw_x_query, dict)
                        else raw_x_query
                    ),
                    "rate_limit": rate_limit,
                },
            )
        except RetryableOperationError:
            raise
        except APIRequestError:
            raise
        except Exception as exc:
            logger.warning("OpenAlex %s search failed (%s)", mode, type(exc).__name__)
        raise APIRequestError(self._service_name)

    @staticmethod
    def _build_work_filters(
        *,
        min_year: int | None,
        max_year: int | None,
        open_access_only: bool,
        is_doaj: bool,
    ) -> list[str]:
        filters: list[str] = []
        if min_year:
            filters.append(f"from_publication_date:{min_year}-01-01")
        if max_year:
            filters.append(f"to_publication_date:{max_year}-12-31")
        if open_access_only:
            filters.append("is_oa:true")
        if is_doaj:
            filters.append("locations.source.is_in_doaj:true")
        return filters

    @staticmethod
    def _coerce_cost(value: object, warnings: list[str]) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            warnings.append("OpenAlex returned an invalid boolean cost")
            return None
        if not isinstance(value, (int, float, str)):
            warnings.append(f"OpenAlex returned a non-numeric cost: {value!r}")
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            warnings.append(f"OpenAlex returned a non-numeric cost: {value!r}")
            return None

    @staticmethod
    def _append_low_credit_warning(rate_limit: dict[str, str], warnings: list[str]) -> None:
        """Surface a response-driven warning before the daily budget is empty."""

        thresholds = {
            "x-ratelimit-remaining": 10.0,
            "x-ratelimit-remaining-usd": 0.01,
        }
        for header, threshold in thresholds.items():
            raw = rate_limit.get(header)
            if raw is None:
                continue
            try:
                remaining = float(raw)
            except ValueError:
                continue
            if remaining <= threshold:
                warnings.append(f"OpenAlex credit budget is low ({header}={raw})")

    async def get_work(self, work_id: str) -> dict[str, Any] | None:
        """
        Get work by ID (OpenAlex ID, DOI, or PMID).

        Args:
            work_id: Work identifier (e.g., "doi:10.1234/example", "pmid:12345678")

        Returns:
            Work dictionary or None
        """
        try:
            # Normalize ID format
            if work_id.startswith("10."):  # DOI
                work_id = f"doi:{work_id}"
            elif work_id.isdigit():  # PMID
                work_id = f"pmid:{work_id}"

            # URL encode the work_id
            encoded_id = urllib.parse.quote(work_id, safe="")
            params = dict(self._auth_params)
            url = f"{OA_WORKS_URL}/{encoded_id}?{urllib.parse.urlencode(params)}"

            data = await self._make_request(url)
            if not isinstance(data, dict):
                return None

            return self._normalize_work(data)

        except Exception as exc:
            logger.warning("OpenAlex work lookup failed (%s)", type(exc).__name__)
            return None

    async def get_citations(self, work_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """
        Get works that cite this work.

        Args:
            work_id: Work identifier
            limit: Maximum results

        Returns:
            List of citing works
        """
        try:
            # Use filter to find citing works
            params = {
                "filter": f"cites:{work_id}",
                "per_page": str(max(1, min(limit, OPENALEX_MAX_PER_PAGE))),
                "sort": "cited_by_count:desc",
                **self._auth_params,
            }

            url = f"{OA_WORKS_URL}?{urllib.parse.urlencode(params)}"
            data = await self._make_request(url)

            if not isinstance(data, dict):
                return []

            return [self._normalize_work(w) for w in data.get("results", [])]

        except Exception as exc:
            logger.warning("OpenAlex citation lookup failed (%s)", type(exc).__name__)
            return []

    async def get_source(self, source_id: str) -> dict[str, Any] | None:
        """
        Get journal/source metadata from OpenAlex Sources API.

        Returns journal-level metrics including:
        - 2yr_mean_citedness (≈ Impact Factor)
        - h_index, i10_index
        - works_count, cited_by_count
        - ISSN, DOAJ status, subject areas

        Args:
            source_id: OpenAlex source ID (e.g., "S137773608") or full URL

        Returns:
            Source metadata dict or None
        """
        try:
            # Normalize ID
            if source_id.startswith("https://openalex.org/"):
                source_id = source_id.replace("https://openalex.org/", "")

            params = dict(self._auth_params)
            url = f"{OA_API_BASE}/sources/{source_id}?{urllib.parse.urlencode(params)}"

            data = await self._make_request(url)
            if not isinstance(data, dict):
                return None

            return self._normalize_source(data)

        except Exception as exc:
            logger.debug("OpenAlex source lookup failed (%s)", type(exc).__name__)
            return None

    async def get_sources_batch(self, source_ids: list[str]) -> dict[str, dict[str, Any]]:
        """
        Batch-fetch journal/source metadata using OpenAlex filter API.

        Uses the filter endpoint to fetch multiple sources in a single request.

        Args:
            source_ids: List of OpenAlex source IDs

        Returns:
            Dict mapping source_id → source metadata
        """
        if not source_ids:
            return {}

        try:
            # OpenAlex supports batch filter: openalex_id:S1|S2|S3
            # Max ~50 per request
            clean_ids = []
            for sid in source_ids[:50]:
                clean_id = sid.replace("https://openalex.org/", "")
                clean_ids.append(clean_id)

            filter_str = "openalex:" + "|".join(clean_ids)
            params = {
                "filter": filter_str,
                "per_page": str(len(clean_ids)),
                **self._auth_params,
            }

            url = f"{OA_API_BASE}/sources?{urllib.parse.urlencode(params)}"
            data = await self._make_request(url)

            if not isinstance(data, dict):
                return {}

            result = {}
            for source in data.get("results", []):
                oa_id = source.get("id", "").replace("https://openalex.org/", "")
                if oa_id:
                    result[oa_id] = self._normalize_source(source)

            return result

        except Exception as exc:
            logger.debug("OpenAlex source batch lookup failed (%s)", type(exc).__name__)
            return {}

    async def get_author(self, author_id: str) -> dict[str, Any] | None:
        """
        Get author metadata by OpenAlex author ID or ORCID.

        Args:
            author_id: OpenAlex author ID (for example ``A123456789``), a full
                OpenAlex URL, or an ORCID identifier.

        Returns:
            Normalized author metadata or ``None`` if the author is not found.
        """
        try:
            normalized_author_id = author_id.strip()
            if normalized_author_id.startswith("https://openalex.org/"):
                normalized_author_id = normalized_author_id.replace("https://openalex.org/", "")
            elif (
                not normalized_author_id.startswith("https://orcid.org/")
                and normalized_author_id.count("-") == 3
                and normalized_author_id.replace("-", "").isdigit()
            ):
                normalized_author_id = f"https://orcid.org/{normalized_author_id}"

            params = dict(self._auth_params)
            encoded_id = urllib.parse.quote(normalized_author_id, safe="")
            url = f"{OA_AUTHORS_URL}/{encoded_id}?{urllib.parse.urlencode(params)}"

            data = await self._make_request(url)
            if not isinstance(data, dict):
                return None

            return self._normalize_author(data)
        except Exception as exc:
            logger.debug("OpenAlex author lookup failed (%s)", type(exc).__name__)
            return None

    async def search_authors(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """
        Search OpenAlex authors by name.

        Args:
            query: Author name query.
            limit: Maximum number of authors to return.

        Returns:
            List of normalized author metadata dictionaries.
        """
        try:
            params = {
                "search": query,
                "per_page": str(max(1, min(limit, OPENALEX_MAX_PER_PAGE))),
                **self._auth_params,
            }
            url = f"{OA_AUTHORS_URL}?{urllib.parse.urlencode(params)}"
            data = await self._make_request(url)

            if not isinstance(data, dict):
                return []

            return [self._normalize_author(author) for author in data.get("results", [])]
        except Exception as exc:
            logger.debug("OpenAlex author search failed (%s)", type(exc).__name__)
            return []

    @staticmethod
    def _normalize_source(source: dict[str, Any]) -> dict[str, Any]:
        """Normalize OpenAlex source to journal metrics format."""
        summary = source.get("summary_stats", {}) or {}

        # Extract ISSNs
        issns = source.get("issn", []) or []
        issn_l = source.get("issn_l")

        # Extract subject areas from x_concepts (top-level concepts)
        concepts = source.get("x_concepts", []) or []
        subject_areas = [
            c.get("display_name", "")
            for c in concepts[:5]  # Top 5 concepts
            if c.get("level", 99) <= 1 and c.get("display_name")
        ]

        return {
            "openalex_source_id": source.get("id", "").replace("https://openalex.org/", ""),
            "display_name": source.get("display_name", ""),
            "issn": issns[0] if issns else None,
            "issn_l": issn_l,
            "h_index": summary.get("h_index"),
            "two_year_mean_citedness": summary.get("2yr_mean_citedness"),
            "i10_index": summary.get("i10_index"),
            "works_count": source.get("works_count"),
            "cited_by_count": source.get("cited_by_count"),
            "is_in_doaj": source.get("is_in_doaj"),
            "source_type": source.get("type"),
            "subject_areas": subject_areas,
        }

    @staticmethod
    def _normalize_author(author: dict[str, Any]) -> dict[str, Any]:
        """Normalize OpenAlex author metadata for reuse in enrichment flows.

        Args:
            author: Raw OpenAlex author payload.

        Returns:
            A compact author metadata dictionary with stable keys.
        """
        summary = author.get("summary_stats", {}) or {}
        ids = author.get("ids", {}) or {}
        orcid = ids.get("orcid") or author.get("orcid") or ""
        if orcid.startswith("https://orcid.org/"):
            orcid = orcid.replace("https://orcid.org/", "")

        institutions = author.get("last_known_institutions", []) or []
        institution_names = [
            institution.get("display_name", "")
            for institution in institutions
            if isinstance(institution, dict) and institution.get("display_name")
        ]

        concepts = author.get("x_concepts", []) or []
        concept_names = [
            concept.get("display_name", "")
            for concept in concepts[:5]
            if isinstance(concept, dict) and concept.get("display_name")
        ]

        return {
            "openalex_author_id": author.get("id", "").replace("https://openalex.org/", ""),
            "display_name": author.get("display_name", ""),
            "orcid": orcid,
            "works_count": author.get("works_count"),
            "cited_by_count": author.get("cited_by_count"),
            "h_index": summary.get("h_index"),
            "i10_index": summary.get("i10_index"),
            "two_year_mean_citedness": summary.get("2yr_mean_citedness"),
            "last_known_institutions": institution_names,
            "concepts": concept_names,
            "_source": "openalex",
        }

    def _normalize_work(self, work: dict[str, Any]) -> dict[str, Any]:
        """
        Normalize OpenAlex work to common format compatible with PubMed results.

        Note: OpenAlex returns very large objects. We extract only essential fields
        to avoid token explosion when sending to LLM.
        """
        # Extract IDs
        ids = work.get("ids", {}) or {}
        doi = ids.get("doi", "")
        if doi and doi.startswith("https://doi.org/"):
            doi = doi.replace("https://doi.org/", "")

        pmid = ids.get("pmid", "")
        if pmid and pmid.startswith("https://pubmed.ncbi.nlm.nih.gov/"):
            pmid = pmid.replace("https://pubmed.ncbi.nlm.nih.gov/", "").rstrip("/")

        pmc_id = ids.get("pmcid", "")
        if pmc_id and "PMC" in pmc_id:
            # Extract just the PMC ID
            pmc_id = pmc_id.split("PMC")[-1] if "PMC" in pmc_id else pmc_id
            pmc_id = f"PMC{pmc_id}" if pmc_id and not pmc_id.startswith("PMC") else pmc_id

        # Extract authors (limit to avoid token explosion)
        authorships = work.get("authorships", []) or []
        author_names = []
        authors_full = []
        for authorship in authorships[:10]:  # Limit to 10 authors
            author = authorship.get("author", {}) or {}
            name = author.get("display_name", "")
            if name:
                author_names.append(name)
                parts = name.rsplit(" ", 1)
                if len(parts) == 2:
                    authors_full.append({"fore_name": parts[0], "last_name": parts[1]})
                else:
                    authors_full.append({"last_name": name, "fore_name": ""})

        # Extract journal/source
        primary_location = work.get("primary_location", {}) or {}
        source = primary_location.get("source", {}) or {}
        journal = source.get("display_name", "")

        # Extract year/date
        pub_date = work.get("publication_date", "") or ""
        year = pub_date[:4] if pub_date else str(work.get("publication_year", ""))
        month = pub_date[5:7] if len(pub_date) >= 7 else ""
        day = pub_date[8:10] if len(pub_date) >= 10 else ""

        # Extract open access info
        oa = work.get("open_access", {}) or {}
        best_oa = work.get("best_oa_location", {}) or {}

        return {
            # Core fields - matching PubMed format
            "pmid": pmid,
            "title": work.get("display_name", "") or work.get("title", ""),
            "abstract": self._get_abstract(work),
            "year": year,
            "month": month,
            "day": day,
            "authors": author_names,
            "authors_full": authors_full,
            "journal": journal,
            "journal_abbrev": "",  # OpenAlex doesn't provide abbreviations
            "volume": "",
            "issue": "",
            "pages": "",
            "doi": doi,
            "pmc_id": pmc_id,
            "keywords": [],
            "mesh_terms": [],
            # Metrics
            "citation_count": work.get("cited_by_count", 0),
            # Access
            "is_open_access": oa.get("is_oa", False),
            "oa_status": oa.get("oa_status", ""),  # gold, green, bronze, etc.
            "pdf_url": best_oa.get("pdf_url"),
            "is_doaj": source.get("is_in_doaj", False),
            # Source marker
            "_source": "openalex",
            "_openalex_id": work.get("id", ""),
            "_openalex_source_id": source.get("id", ""),  # For journal metrics lookup
        }

    def _get_abstract(self, work: dict[str, Any]) -> str:
        """
        Extract abstract from OpenAlex inverted index format.

        OpenAlex stores abstracts as inverted indices to save space.
        We need to reconstruct the original text.
        """
        abstract_index = work.get("abstract_inverted_index")
        if not abstract_index:
            return ""

        try:
            # Reconstruct from inverted index
            # Format: {"word": [positions], ...}
            word_positions = []
            for word, positions in abstract_index.items():
                for pos in positions:
                    word_positions.append((pos, word))

            # Sort by position and join
            word_positions.sort(key=lambda x: x[0])
            return " ".join(word for _, word in word_positions)

        except Exception as exc:
            logger.warning("OpenAlex abstract reconstruction failed (%s)", type(exc).__name__)
            return ""
