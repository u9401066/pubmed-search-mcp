"""Tests for the default-off Web of Science connector skeleton."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pubmed_search.infrastructure.sources.web_of_science import WebOfScienceClient


class TestWebOfScienceClient:
    def test_requires_api_key(self):
        with pytest.raises(ValueError, match="WEB_OF_SCIENCE_API_KEY"):
            WebOfScienceClient(api_key=None)

    async def test_search_normalizes_hits(self):
        client = WebOfScienceClient(api_key="licensed-key")
        payload = {
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
            ]
        }

        with patch.object(client, "_make_request", AsyncMock(return_value=payload)) as mock_make_request:
            results = await client.search("icu sedation", limit=5, min_year=2020, max_year=2024, open_access_only=True)

        assert len(results) == 1
        assert results[0]["title"] == "Web of Science Article"
        assert results[0]["doi"] == "10.1000/wos"
        assert results[0]["year"] == 2024
        assert results[0]["is_open_access"] is True
        assert results[0]["source"] == "web_of_science"
        params = mock_make_request.await_args.kwargs["params"]
        assert "TS=(icu sedation)" in params["q"]
        assert "PY=(2020-2024)" in params["q"]
        assert "OA=(Y)" in params["q"]

    async def test_search_handles_empty_payload(self):
        client = WebOfScienceClient(api_key="licensed-key")

        with patch.object(client, "_make_request", AsyncMock(return_value=None)):
            results = await client.search("icu sedation")

        assert results == []
