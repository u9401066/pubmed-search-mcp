from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from pubmed_search.domain.entities.article import UnifiedArticle


def _outcome(request: object) -> SimpleNamespace:
    return SimpleNamespace(
        request=request,
        plan=SimpleNamespace(dispatch_sources=["pubmed"]),
        execution=SimpleNamespace(
            ranked=[UnifiedArticle(pmid="123", title="A useful article", primary_source="pubmed")],
            source_api_counts={"pubmed": (1, 1)},
            source_statuses={"pubmed": "ok"},
            source_errors=[],
            result_filter_counts={
                "retrieved_unique": 1,
                "excluded_detected_preprints": 0,
                "eligible_unique": 1,
                "returned": 1,
            },
        ),
    )


class _FakeUnifiedSearchUseCase:
    def __init__(self) -> None:
        self.request = None

    async def execute(self, request: object, *, progress: Any) -> SimpleNamespace:
        self.request = request
        await progress(1, 1, "done")
        return _outcome(request)


def test_public_api_config_repr_keeps_api_key_private() -> None:
    from pubmed_search.api import PubMedSearchConfig

    config = PubMedSearchConfig(api_key="private-test-api-key")
    assert "private-test-api-key" not in repr(config)
    assert config.api_key == "private-test-api-key"


async def test_public_api_unified_search_uses_injected_application_use_case() -> None:
    from pubmed_search.api import PubMedSearchClient, PubMedSearchConfig

    use_case = _FakeUnifiedSearchUseCase()
    client = PubMedSearchClient(
        PubMedSearchConfig(email="test@example.com"),
        searcher=object(),
        unified_search_use_case=use_case,
    )

    result = await client.unified_search(
        "remimazolam ICU sedation",
        limit=7,
        sources="pubmed",
    )

    assert use_case.request.query == "remimazolam ICU sedation"
    assert use_case.request.limit == 7
    assert result.articles[0].pmid == "123"
    assert result.source_counts[0].source == "pubmed"
    assert not hasattr(result, "raw")
    assert not hasattr(result, "artifact")
    await client.aclose()


async def test_public_api_context_owns_and_closes_its_source_runtime() -> None:
    from pubmed_search.api import PubMedSearchClient, PubMedSearchConfig
    from pubmed_search.infrastructure.sources.runtime import get_source_runtime

    seen_runtime = None

    class RuntimeAwareUseCase:
        async def execute(self, request: object, *, progress: Any) -> SimpleNamespace:
            nonlocal seen_runtime
            del progress
            seen_runtime = get_source_runtime()
            return _outcome(request)

    client = PubMedSearchClient(
        PubMedSearchConfig(email="sdk@example.com"),
        searcher=object(),
        unified_search_use_case=RuntimeAwareUseCase(),
    )
    async with client as entered:
        assert entered is client
        await client.unified_search("query")
        assert seen_runtime is client._source_runtime
        assert seen_runtime.contact_email == "sdk@example.com"

    assert client._source_runtime is None


async def test_public_api_search_pubmed_delegates_to_lazy_searcher() -> None:
    from pubmed_search.api import PubMedSearchClient, PubMedSearchConfig
    from pubmed_search.application.search.source_models import SourceSearchPage

    class FakeSearcher:
        async def search_page(self, **kwargs: Any) -> SourceSearchPage[dict[str, Any]]:
            assert kwargs["query"] == "diabetes"
            assert kwargs["limit"] == 3
            return SourceSearchPage(source="pubmed", items=[{"pmid": "42"}], total=1, query="diabetes")

    client = PubMedSearchClient(PubMedSearchConfig(email="test@example.com"), searcher=FakeSearcher())

    page = await client.search_pubmed_page("diabetes", limit=3)

    assert page.items == [{"pmid": "42"}]
    assert page.total == 1
    assert not hasattr(client, "search_pubmed")


def test_python_sdk_has_no_presentation_runner_surface() -> None:
    import inspect

    from pubmed_search.api import PubMedSearchClient

    signature = inspect.signature(PubMedSearchClient)
    assert "unified_search_runner" not in signature.parameters
    assert "unified_search_use_case" in signature.parameters
    source = inspect.getsource(PubMedSearchClient._get_unified_search_use_case)
    assert "presentation" not in source
