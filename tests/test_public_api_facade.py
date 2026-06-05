from __future__ import annotations

import json
from typing import Any

import pytest


async def _fake_unified_runner(**kwargs: Any) -> str:
    assert kwargs["query"] == "remimazolam ICU sedation"
    assert kwargs["limit"] == 7
    assert kwargs["sources"] == "pubmed"
    return json.dumps(
        {
            "query": {"original": kwargs["query"]},
            "articles": [
                {
                    "pmid": "123",
                    "title": "A useful article",
                    "primary_source": "pubmed",
                }
            ],
            "source_counts": [{"source": "pubmed", "returned": 1, "total_available": 1}],
            "artifact_summary": {
                "artifact_id": "artifact-1",
                "artifact_uri": "session://artifacts/artifact-1",
            },
        }
    )


def test_public_api_exports_stable_facade_types() -> None:
    from pubmed_search.api import PubMedSearchClient, PubMedSearchConfig, UnifiedSearchResult

    assert PubMedSearchClient is not None
    assert PubMedSearchConfig(email="test@example.com").email == "test@example.com"
    assert UnifiedSearchResult(raw="{}", output_format="json").structured == {}


async def test_public_api_unified_search_uses_injected_runner_without_mcp_server() -> None:
    from pubmed_search.api import PubMedSearchClient, PubMedSearchConfig

    client = PubMedSearchClient(
        PubMedSearchConfig(email="test@example.com"),
        searcher=object(),
        unified_search_runner=_fake_unified_runner,
    )

    result = await client.unified_search(
        "remimazolam ICU sedation",
        limit=7,
        sources="pubmed",
        output_format="json",
    )

    assert result.output_format == "json"
    assert result.articles == [{"pmid": "123", "title": "A useful article", "primary_source": "pubmed"}]
    assert result.artifact == {
        "artifact_id": "artifact-1",
        "artifact_uri": "session://artifacts/artifact-1",
    }


async def test_public_api_search_pubmed_delegates_to_lazy_searcher() -> None:
    from pubmed_search.api import PubMedSearchClient, PubMedSearchConfig

    class FakeSearcher:
        async def search(self, **kwargs: Any) -> list[dict[str, Any]]:
            assert kwargs["query"] == "diabetes"
            assert kwargs["limit"] == 3
            return [{"pmid": "42"}]

    client = PubMedSearchClient(PubMedSearchConfig(email="test@example.com"), searcher=FakeSearcher())

    assert await client.search_pubmed("diabetes", limit=3) == [{"pmid": "42"}]


def test_unified_search_result_rejects_invalid_json() -> None:
    from pubmed_search.api import UnifiedSearchResult

    with pytest.raises(ValueError, match="Unable to parse"):
        UnifiedSearchResult(raw="{not-json", output_format="json")


def test_unified_search_result_keeps_non_json_formats_unparsed() -> None:
    from pubmed_search.api import UnifiedSearchResult

    result = UnifiedSearchResult(raw="results:\n- pmid: 123", output_format="toon")

    assert result.structured == {}
    assert result.articles == []


def test_unified_search_result_supports_legacy_results_key() -> None:
    from pubmed_search.api import UnifiedSearchResult

    result = UnifiedSearchResult(raw=json.dumps({"results": [{"pmid": "123"}]}), output_format="json")

    assert result.articles == [{"pmid": "123"}]
