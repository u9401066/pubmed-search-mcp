"""Scopus integration.

Provides a default-off connector skeleton for Elsevier Scopus.
The connector is intentionally safe for unlicensed environments:

- it is disabled unless `SCOPUS_ENABLED=true` and `SCOPUS_API_KEY` are set
- unit tests use mocked responses only
- no live calls are required in CI
"""

from __future__ import annotations

import logging
from typing import Any

from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.infrastructure.sources.base_client import (
    APIRequestError,
    BaseAPIClient,
    raise_provider_schema_error,
)
from pubmed_search.infrastructure.sources.official_generated_clients import (
    OfficialScopusGeneratedClient,
    ScopusSearchRequest,
)
from pubmed_search.shared.async_utils import RetryableOperationError

logger = logging.getLogger(__name__)

SCOPUS_API_BASE = "https://api.elsevier.com"
SCOPUS_SEARCH_PATH = "/content/search/scopus"


class ScopusClient(BaseAPIClient):
    """Minimal Scopus search client for licensed installations."""

    _service_name = "Scopus"

    def __init__(
        self,
        api_key: str | None,
        insttoken: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("Scopus requires SCOPUS_API_KEY")

        self._api_key = api_key
        self._insttoken = insttoken
        super().__init__(
            base_url=SCOPUS_API_BASE,
            timeout=timeout,
            min_interval=0.2,
            headers={
                "User-Agent": "pubmed-search-mcp/1.0",
                "Accept": "application/json",
                "X-ELS-APIKey": self._api_key,
            },
        )
        self._official_client = OfficialScopusGeneratedClient(self)

    async def _execute_request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        request_headers = dict(headers or {})
        request_headers.setdefault("X-ELS-APIKey", self._api_key)
        if self._insttoken:
            request_headers.setdefault("X-ELS-Insttoken", self._insttoken)
        return await super()._execute_request(url, method=method, data=data, params=params, headers=request_headers)

    async def search_page(
        self,
        query: str,
        limit: int = 10,
        min_year: int | None = None,
        max_year: int | None = None,
        open_access_only: bool = False,
        *,
        offset: int = 0,
    ) -> SourceSearchPage[dict[str, Any]]:
        """Return one normalized Scopus page with its official pagination metadata."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 25:
            raise ValueError("Scopus page limit must be between 1 and 25")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("Scopus offset must be a non-negative integer")

        try:
            scopus_query = self.compile_query(
                query,
                min_year=min_year,
                max_year=max_year,
                open_access_only=open_access_only,
            )
            request = ScopusSearchRequest(
                query=scopus_query,
                count=limit,
                start=offset,
            )

            response = await self._official_client.search_documents(request)
            if response is None:
                raise_provider_schema_error(self._service_name)

            items = [
                self._normalize_entry(entry.model_dump(by_alias=True, exclude_none=True))
                for entry in response.entries()
            ]
            pagination = response.search_results
            total = pagination.total_results
            start_index = pagination.start_index if pagination.start_index is not None else offset
            items_per_page = pagination.items_per_page
            warnings: list[str] = []
            if pagination.start_index is None:
                warnings.append("Scopus response omitted opensearch:startIndex; requested offset was used")
            elif pagination.start_index != offset:
                warnings.append("Scopus response start index differs from the requested offset")
            if items_per_page is None:
                warnings.append("Scopus response omitted opensearch:itemsPerPage")
            elif items_per_page != limit:
                warnings.append("Scopus response page size differs from the requested limit")
            if total is None:
                warnings.append("Scopus response omitted opensearch:totalResults")
            else:
                self._validate_pagination(total=total, start_index=start_index, returned=len(items))

            next_offset: int | None = None
            if total is not None and items_per_page is not None and items_per_page > 0:
                candidate = start_index + items_per_page
                if candidate < total:
                    next_offset = candidate

            return SourceSearchPage(
                source="scopus",
                items=items,
                total=total,
                next_token=next_offset,
                query=scopus_query,
                warnings=warnings,
                mode="keyword",
                metadata={
                    "offset": start_index,
                    "requested_offset": offset,
                    "items_per_page": items_per_page,
                    "requested_limit": limit,
                    "returned": len(items),
                    "next_offset": next_offset,
                },
            )
        except (APIRequestError, RetryableOperationError):
            raise
        except Exception as exc:
            logger.warning("Scopus search failed (%s)", type(exc).__name__)
            raise APIRequestError(self._service_name) from None

    @staticmethod
    def _validate_pagination(*, total: int, start_index: int, returned: int) -> None:
        """Reject an official envelope whose count cannot contain its page."""
        if total < start_index + returned:
            raise ValueError("Scopus returned inconsistent pagination metadata")

    def compile_query(
        self,
        query: str,
        *,
        min_year: int | None,
        max_year: int | None,
        open_access_only: bool,
    ) -> str:
        terms = [f"TITLE-ABS-KEY({query})"]
        if min_year:
            terms.append(f"PUBYEAR > {min_year - 1}")
        if max_year:
            terms.append(f"PUBYEAR < {max_year + 1}")
        if open_access_only:
            terms.append("OPENACCESS(1)")
        return " AND ".join(terms)

    def _normalize_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        cover_date = str(entry.get("prism:coverDate", ""))
        year: int | None = None
        if len(cover_date) >= 4 and cover_date[:4].isdigit():
            year = int(cover_date[:4])

        doi = entry.get("prism:doi") or entry.get("dc:identifier")
        if isinstance(doi, str) and doi.startswith("SCOPUS_ID:"):
            doi = None

        scopus_id = entry.get("dc:identifier")
        return {
            "title": entry.get("dc:title", ""),
            "abstract": entry.get("dc:description", ""),
            "authors": [entry.get("dc:creator", "")] if entry.get("dc:creator") else [],
            "journal": entry.get("prism:publicationName", ""),
            "journal_abbrev": entry.get("prism:publicationName", ""),
            "doi": doi,
            "year": year,
            "scopus_id": scopus_id,
            "eid": entry.get("eid"),
            "link": entry.get("prism:url") or entry.get("link"),
            "is_open_access": entry.get("openaccessFlag") == "1",
            "cited_by_count": int(entry.get("citedby-count", 0) or 0),
            "source": "scopus",
        }
