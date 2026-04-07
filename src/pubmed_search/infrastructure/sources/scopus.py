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

from pubmed_search.infrastructure.sources.base_client import BaseAPIClient

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

    async def search(
        self,
        query: str,
        limit: int = 10,
        min_year: int | None = None,
        max_year: int | None = None,
        open_access_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Search Scopus and normalize the response into article-like dicts."""
        scopus_query = self._build_query(query, min_year=min_year, max_year=max_year, open_access_only=open_access_only)
        params = {
            "query": scopus_query,
            "count": str(min(limit, 25)),
            "start": "0",
            "view": "COMPLETE",
        }

        data = await self._make_request(SCOPUS_SEARCH_PATH, params=params)
        if not isinstance(data, dict):
            return []

        payload = data.get("search-results", {})
        entries = payload.get("entry", [])
        if not isinstance(entries, list):
            return []

        results: list[dict[str, Any]] = []
        for entry in entries:
            if isinstance(entry, dict):
                results.append(self._normalize_entry(entry))
        return results

    def _build_query(
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
