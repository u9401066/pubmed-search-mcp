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

from pubmed_search.infrastructure.sources.base_client import BaseAPIClient

logger = logging.getLogger(__name__)

WEB_OF_SCIENCE_API_BASE = "https://api.clarivate.com"
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

    async def search(
        self,
        query: str,
        limit: int = 10,
        min_year: int | None = None,
        max_year: int | None = None,
        open_access_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Search Web of Science and normalize the response into article-like dicts."""
        wos_query = self._build_query(query, min_year=min_year, max_year=max_year, open_access_only=open_access_only)
        params = {
            "q": wos_query,
            "limit": str(min(limit, 25)),
            "page": "1",
        }

        data = await self._make_request(WEB_OF_SCIENCE_SEARCH_PATH, params=params)
        if not isinstance(data, dict):
            return []

        hits = data.get("hits", [])
        if not isinstance(hits, list):
            return []

        results: list[dict[str, Any]] = []
        for hit in hits:
            if isinstance(hit, dict):
                results.append(self._normalize_hit(hit))
        return results

    def _build_query(
        self,
        query: str,
        *,
        min_year: int | None,
        max_year: int | None,
        open_access_only: bool,
    ) -> str:
        terms = [f"TS=({query})"]
        if min_year and max_year:
            terms.append(f"PY=({min_year}-{max_year})")
        elif min_year:
            terms.append(f"PY=({min_year}-9999)")
        elif max_year:
            terms.append(f"PY=(1000-{max_year})")
        if open_access_only:
            terms.append("OA=(Y)")
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

        year_raw = source.get("publishedBiblioYear") or hit.get("publishedYear")
        year = int(year_raw) if isinstance(year_raw, (int, str)) and str(year_raw).isdigit() else None

        cited_by_count = 0
        if isinstance(citations, dict):
            cited_by_count = int(citations.get("count", 0) or 0)
        elif isinstance(citations, int):
            cited_by_count = citations

        return {
            "title": hit.get("title", ""),
            "abstract": hit.get("abstract", ""),
            "authors": authors,
            "journal": source.get("sourceTitle", ""),
            "journal_abbrev": source.get("sourceTitle", ""),
            "doi": identifiers.get("doi"),
            "year": year,
            "wos_id": hit.get("uid"),
            "link": links.get("record"),
            "is_open_access": bool(open_access.get("isOpenAccess")),
            "cited_by_count": cited_by_count,
            "source": "web_of_science",
        }
