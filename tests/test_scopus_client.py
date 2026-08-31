"""Tests for the default-off Scopus connector skeleton."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pubmed_search.infrastructure.sources.base_client import APIRequestError
from pubmed_search.infrastructure.sources.scopus import ScopusClient


class TestScopusClient:
    def test_requires_api_key(self):
        with pytest.raises(ValueError, match="SCOPUS_API_KEY"):
            ScopusClient(api_key=None)

    async def test_search_page_preserves_pagination_and_normalizes_entries(self):
        client = ScopusClient(api_key="licensed-key")
        payload = {
            "search-results": {
                "opensearch:totalResults": "42",
                "opensearch:startIndex": "5",
                "opensearch:itemsPerPage": "5",
                "entry": [
                    {
                        "dc:title": "Scopus Article",
                        "dc:description": "Abstract text",
                        "dc:creator": "A B",
                        "prism:publicationName": "Journal of Testing",
                        "prism:doi": "10.1000/scopus",
                        "prism:coverDate": "2025-01-01",
                        "dc:identifier": "SCOPUS_ID:123456789",
                        "eid": "2-s2.0-123456789",
                        "prism:url": "https://api.elsevier.com/content/abstract/scopus_id/123456789",
                        "openaccessFlag": "1",
                        "citedby-count": "42",
                    }
                ],
            }
        }

        with patch.object(client, "_make_request", AsyncMock(return_value=payload)) as mock_make_request:
            page = await client.search_page(
                "icu sedation",
                limit=5,
                min_year=2020,
                max_year=2025,
                open_access_only=True,
                offset=5,
            )

        assert page.source == "scopus"
        assert page.total == 42
        assert page.next_token == 10
        assert page.query == "TITLE-ABS-KEY(icu sedation) AND PUBYEAR > 2019 AND PUBYEAR < 2026 AND OPENACCESS(1)"
        assert page.metadata == {
            "offset": 5,
            "requested_offset": 5,
            "items_per_page": 5,
            "requested_limit": 5,
            "returned": 1,
            "next_offset": 10,
        }
        assert len(page.items) == 1
        assert page.items[0]["title"] == "Scopus Article"
        assert page.items[0]["doi"] == "10.1000/scopus"
        assert page.items[0]["year"] == 2025
        assert page.items[0]["is_open_access"] is True
        assert page.items[0]["source"] == "scopus"
        params = mock_make_request.await_args.kwargs["params"]
        assert "OPENACCESS(1)" in params["query"]
        assert "PUBYEAR > 2019" in params["query"]
        assert "PUBYEAR < 2026" in params["query"]
        assert "apiKey" not in params
        assert "insttoken" not in params
        assert "licensed-key" not in repr(params)
        assert params["start"] == 5
        assert params["count"] == 5

    async def test_search_page_distinguishes_empty_page_from_failure(self):
        client = ScopusClient(api_key="licensed-key")

        empty_payload = {
            "search-results": {
                "opensearch:totalResults": "0",
                "opensearch:startIndex": "0",
                "opensearch:itemsPerPage": "10",
                "entry": [],
            }
        }
        with patch.object(client, "_make_request", AsyncMock(return_value=empty_payload)):
            page = await client.search_page("icu sedation")

        assert page.items == []
        assert page.total == 0
        assert page.next_token is None

        with patch.object(client, "_make_request", AsyncMock(return_value=None)):
            with pytest.raises(APIRequestError):
                await client.search_page("icu sedation")

    def test_removed_list_search_and_query_wrapper_have_no_aliases(self):
        client = ScopusClient(api_key="licensed-key")

        assert not hasattr(client, "search")
        assert not hasattr(client, "_build_query")
