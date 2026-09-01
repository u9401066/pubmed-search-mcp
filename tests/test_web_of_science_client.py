"""Tests for the default-off Web of Science connector skeleton."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pubmed_search.infrastructure.sources.base_client import APIRequestError
from pubmed_search.infrastructure.sources.web_of_science import WebOfScienceClient


class TestWebOfScienceClient:
    def test_requires_api_key(self):
        with pytest.raises(ValueError, match="WEB_OF_SCIENCE_API_KEY"):
            WebOfScienceClient(api_key=None)

    async def test_search_page_preserves_pagination_and_normalizes_hits(self):
        client = WebOfScienceClient(api_key="licensed-key")
        payload = {
            "metadata": {"total": 12, "page": 2, "limit": 5},
            "hits": [
                {
                    "uid": "WOS:001234567800001",
                    "title": "Web of Science Article",
                    "abstract": "Abstract text",
                    "names": {"authors": [{"displayName": "A B"}, {"displayName": "C D"}]},
                    "source": {"sourceTitle": "Journal of Testing", "publishedBiblioYear": "2024"},
                    "identifiers": {"doi": "10.1000/wos"},
                    "links": {"record": "https://www.webofscience.com/wos/woscc/full-record/WOS:001234567800001"},
                    "openAccess": {"isOpenAccess": True},
                    "citations": {"count": 17},
                }
            ],
        }

        with patch.object(client, "_make_request", AsyncMock(return_value=payload)) as mock_make_request:
            page = await client.search_page(
                "icu sedation",
                limit=5,
                min_year=2020,
                max_year=2024,
                open_access_only=True,
                page=2,
            )

        assert page.source == "web_of_science"
        assert page.total == 12
        assert page.next_token == 3
        assert page.query == "TS=(icu sedation) AND PY=(2020-2024) AND OA=(Y)"
        assert page.metadata == {
            "page": 2,
            "requested_page": 2,
            "limit": 5,
            "requested_limit": 5,
            "offset": 5,
            "returned": 1,
            "next_page": 3,
            "next_offset": 10,
        }
        assert len(page.items) == 1
        assert page.items[0]["title"] == "Web of Science Article"
        assert page.items[0]["doi"] == "10.1000/wos"
        assert page.items[0]["year"] == 2024
        assert page.items[0]["is_open_access"] is True
        assert page.items[0]["source"] == "web_of_science"
        params = mock_make_request.await_args.kwargs["params"]
        assert "TS=(icu sedation)" in params["q"]
        assert "PY=(2020-2024)" in params["q"]
        assert "OA=(Y)" in params["q"]
        assert params["page"] == 2
        assert params["limit"] == 5

    async def test_search_page_distinguishes_empty_page_from_failure(self):
        client = WebOfScienceClient(api_key="licensed-key")

        with patch.object(
            client,
            "_make_request",
            AsyncMock(return_value={"metadata": {"total": 0, "page": 1, "limit": 10}, "hits": []}),
        ):
            page = await client.search_page("icu sedation")

        assert page.items == []
        assert page.total == 0
        assert page.next_token is None

        with patch.object(client, "_make_request", AsyncMock(return_value=None)):
            with pytest.raises(APIRequestError):
                await client.search_page("icu sedation")

    def test_removed_list_search_has_no_alias(self):
        client = WebOfScienceClient(api_key="licensed-key")

        assert not hasattr(client, "search")
