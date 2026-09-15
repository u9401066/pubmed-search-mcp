"""Web of Science integration.

Provides a default-off connector skeleton for Clarivate Web of Science.
The connector is intentionally safe for unlicensed environments:

- it is disabled unless `WEB_OF_SCIENCE_ENABLED=true` and
  `WEB_OF_SCIENCE_API_KEY` are set
- unit tests use mocked responses only
- no live calls are required in CI
"""

from __future__ import annotations

import logging
from typing import Any, cast

from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.infrastructure.sources.base_client import (
    APIRequestError,
    BaseAPIClient,
    raise_provider_schema_error,
)
from pubmed_search.infrastructure.sources.official_generated_clients import (
    OfficialWebOfScienceGeneratedClient,
    WebOfScienceSearchRequest,
)
from pubmed_search.shared.async_utils import RetryableOperationError

logger = logging.getLogger(__name__)

WEB_OF_SCIENCE_API_BASE = "https://api.clarivate.com/apis/wos-starter/v1"
WEB_OF_SCIENCE_SEARCH_PATH = "/apis/wos-starter/v1/documents"


class WebOfScienceClient(BaseAPIClient):
    """Minimal Web of Science search client for licensed installations."""

    _service_name = "Web of Science"

    def __init__(
        self,
        api_key: str | None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("Web of Science requires WEB_OF_SCIENCE_API_KEY")

        self._api_key = api_key
        super().__init__(
            base_url=WEB_OF_SCIENCE_API_BASE,
            timeout=timeout,
            min_interval=0.2,
            headers={
                "User-Agent": "pubmed-search-mcp/1.0",
                "Accept": "application/json",
                "X-ApiKey": self._api_key,
            },
        )
        self._official_client = OfficialWebOfScienceGeneratedClient(self)

    async def search_page(
        self,
        query: str,
        limit: int = 10,
        min_year: int | None = None,
        max_year: int | None = None,
        open_access_only: bool = False,
        *,
        page: int = 1,
    ) -> SourceSearchPage[dict[str, Any]]:
        """Return one normalized Web of Science page with official metadata."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 25:
            raise ValueError("Web of Science page limit must be between 1 and 25")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ValueError("Web of Science page must be a positive integer")

        wos_query = self.compile_query(
            query,
            min_year=min_year,
            max_year=max_year,
            open_access_only=open_access_only,
        )
        try:
            request = WebOfScienceSearchRequest(
                q=wos_query,
                limit=limit,
                page=page,
            )

            response = await self._official_client.search_documents(request)
            if response is None:
                raise_provider_schema_error(self._service_name)

            items = [self._normalize_hit(hit.model_dump(exclude_none=True)) for hit in response.hits]
            response_page = response.metadata.page
            response_limit = response.metadata.limit
            total = response.metadata.total
            offset = (response_page - 1) * response_limit
            self._validate_pagination(total=total, offset=offset, returned=len(items))
            next_offset = response_page * response_limit if response_page * response_limit < total else None
            next_page = response_page + 1 if next_offset is not None else None
            warnings: list[str] = []
            if response_page != page:
                warnings.append("Web of Science response page differs from the requested page")
            if response_limit != limit:
                warnings.append("Web of Science response limit differs from the requested limit")

            return SourceSearchPage(
                source="web_of_science",
                items=items,
                total=total,
                next_token=next_page,
                query=wos_query,
                warnings=warnings,
                mode="keyword",
                metadata={
                    "page": response_page,
                    "requested_page": page,
                    "limit": response_limit,
                    "requested_limit": limit,
                    "offset": offset,
                    "returned": len(items),
                    "next_page": next_page,
                    "next_offset": next_offset,
                },
            )
        except (APIRequestError, RetryableOperationError):
            raise
        except Exception as exc:
            logger.warning("Web of Science search failed (%s)", type(exc).__name__)
            raise APIRequestError(self._service_name) from None

    @staticmethod
    def _validate_pagination(*, total: int, offset: int, returned: int) -> None:
        """Reject an official envelope whose count cannot contain its page."""
        if total < offset + returned:
            raise ValueError("Web of Science returned inconsistent pagination metadata")

    def compile_query(
        self,
        query: str,
        *,
        min_year: int | None,
        max_year: int | None,
        open_access_only: bool,
    ) -> str:
        if open_access_only:
            raise ValueError("Web of Science Starter does not support open_access_only")
        terms = [f"TS=({query})"]
        if min_year and max_year:
            terms.append(f"PY=({min_year}-{max_year})")
        elif min_year:
            terms.append(f"PY=({min_year}-9999)")
        elif max_year:
            terms.append(f"PY=(1000-{max_year})")
        return " AND ".join(terms)

    def _normalize_hit(self, hit: dict[str, Any]) -> dict[str, Any]:
        raw_source = hit.get("source")
        source = cast("dict[str, Any]", raw_source) if isinstance(raw_source, dict) else {}
        raw_identifiers = hit.get("identifiers")
        identifiers = cast("dict[str, Any]", raw_identifiers) if isinstance(raw_identifiers, dict) else {}
        raw_links = hit.get("links")
        links = cast("dict[str, Any]", raw_links) if isinstance(raw_links, dict) else {}
        raw_open_access = hit.get("openAccess")
        open_access = cast("dict[str, Any]", raw_open_access) if isinstance(raw_open_access, dict) else {}
        raw_names = hit.get("names")
        names = cast("dict[str, Any]", raw_names) if isinstance(raw_names, dict) else {}
        raw_authors = names.get("authors")
        authors_payload = raw_authors if isinstance(raw_authors, list) else []
        citations = hit.get("citations")

        authors: list[str] = []
        for author in authors_payload:
            if isinstance(author, dict) and author.get("displayName"):
                authors.append(str(author["displayName"]))
            elif isinstance(author, str):
                authors.append(author)

        year_raw = source.get("publishYear") or source.get("publishedBiblioYear") or hit.get("publishedYear")
        year = int(year_raw) if isinstance(year_raw, (int, str)) and str(year_raw).isdigit() else None

        cited_by_count = 0
        if isinstance(citations, dict):
            cited_by_count = int(citations.get("count", 0) or 0)
        elif isinstance(citations, list):
            preferred_count = None
            fallback_count = 0
            for item in citations:
                if not isinstance(item, dict):
                    continue
                count = int(item.get("count", 0) or 0)
                if item.get("db") == "WOS":
                    preferred_count = count
                    break
                fallback_count = max(fallback_count, count)
            cited_by_count = preferred_count if preferred_count is not None else fallback_count
        elif isinstance(citations, int):
            cited_by_count = citations

        return {
            "title": hit.get("title", ""),
            "abstract": hit.get("abstract", ""),
            "authors": authors,
            "journal": source.get("sourceTitle", ""),
            "journal_abbrev": source.get("sourceTitle", ""),
            "doi": identifiers.get("doi"),
            "pmid": identifiers.get("pmid"),
            "year": year,
            "wos_id": hit.get("uid"),
            "link": links.get("record"),
            "is_open_access": bool(open_access.get("isOpenAccess")),
            "cited_by_count": cited_by_count,
            "source": "web_of_science",
        }
