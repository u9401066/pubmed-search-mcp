"""Tests for the default-off Scopus connector skeleton."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pubmed_search.infrastructure.sources.scopus import ScopusClient


class TestScopusClient:
    def test_requires_api_key(self):
        with pytest.raises(ValueError, match="SCOPUS_API_KEY"):
            ScopusClient(api_key=None)

    async def test_search_normalizes_entries(self):
        client = ScopusClient(api_key="licensed-key")
        payload = {
            "search-results": {
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
                ]
            }
        }

        with patch.object(client, "_make_request", AsyncMock(return_value=payload)) as mock_make_request:
            results = await client.search("icu sedation", limit=5, min_year=2020, max_year=2025, open_access_only=True)

        assert len(results) == 1
        assert results[0]["title"] == "Scopus Article"
        assert results[0]["doi"] == "10.1000/scopus"
        assert results[0]["year"] == 2025
        assert results[0]["is_open_access"] is True
        assert results[0]["source"] == "scopus"
        params = mock_make_request.await_args.kwargs["params"]
        assert "OPENACCESS(1)" in params["query"]
        assert "PUBYEAR > 2019" in params["query"]
        assert "PUBYEAR < 2026" in params["query"]

    async def test_search_handles_empty_payload(self):
        client = ScopusClient(api_key="licensed-key")

        with patch.object(client, "_make_request", AsyncMock(return_value=None)):
            results = await client.search("icu sedation")

        assert results == []