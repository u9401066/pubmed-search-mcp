"""Runtime-owned literature-source clients and the typed search adapter.

The source registry is the sole capability/identity catalog. Non-PubMed
literature searches cross this module through ``search_alternate_source_adapter``;
provider failures, counts, continuation state, cost, and query provenance are
therefore never hidden behind list-only compatibility facades.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.shared.source_contracts import (
    SourceAdapterResult,
    normalize_source_adapter_error,
    validate_source_adapter_mapping_result,
)

from .contact import (
    first_contact_email,
    get_source_contact_email,
)
from .runtime import SourceRuntime, get_source_runtime

logger = logging.getLogger(__name__)

_REGISTRY_EXPORTS: dict[str, tuple[str, str]] = {
    "SourceDefinition": ("pubmed_search.infrastructure.sources.registry", "SourceDefinition"),
    "SourceRegistry": ("pubmed_search.infrastructure.sources.registry", "SourceRegistry"),
    "SourceSelection": ("pubmed_search.infrastructure.sources.registry", "SourceSelection"),
}


def __getattr__(name: str) -> Any:
    if name in _REGISTRY_EXPORTS:
        from importlib import import_module

        module_name, attr_name = _REGISTRY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _load_settings():
    from pubmed_search.shared.settings import load_settings

    return load_settings()


def _secret_value(value: object) -> str | None:
    """Unwrap Pydantic secret settings only at the client construction edge."""

    if value is None:
        return None
    getter = getattr(value, "get_secret_value", None)
    raw = getter() if callable(getter) else value
    normalized = str(raw).strip()
    return normalized or None


def get_source_registry():
    from .registry import get_source_registry as _get_source_registry

    return _get_source_registry()


AlternateSearchSource = Literal[
    "semantic_scholar",
    "openalex",
    "europe_pmc",
    "core",
    "scopus",
    "web_of_science",
]
AlternateSourceAdapterRunner = Callable[
    [str, int, int | None, int | None, bool, bool, str | None],
    Awaitable[SourceAdapterResult[dict[str, Any]]],
]


def get_semantic_scholar_client(api_key: str | None = None):
    """Get or create Semantic Scholar client (lazy initialization)."""
    settings = _load_settings()
    resolved_api_key = api_key or _secret_value(settings.semantic_scholar_api_key)

    def _factory():
        from .semantic_scholar import SemanticScholarClient

        return SemanticScholarClient(api_key=resolved_api_key)

    return get_source_runtime().get_or_create_client(("semantic_scholar", resolved_api_key), _factory)


def get_openalex_client(email: str | None = None, api_key: str | None = None):
    """Get or create OpenAlex client (lazy initialization)."""
    settings = _load_settings()
    resolved_email = first_contact_email(email, get_source_contact_email(), settings.ncbi_email)
    resolved_api_key = api_key or _secret_value(settings.openalex_api_key)

    def _factory():
        from .openalex import OpenAlexClient

        return OpenAlexClient(email=resolved_email, api_key=resolved_api_key)

    return get_source_runtime().get_or_create_client(("openalex", resolved_email, resolved_api_key), _factory)


def get_europe_pmc_client(email: str | None = None):
    """Get or create Europe PMC client (lazy initialization)."""
    settings = _load_settings()
    resolved_email = first_contact_email(email, get_source_contact_email(), settings.ncbi_email)

    def _factory():
        from .europe_pmc import EuropePMCClient

        return EuropePMCClient(email=resolved_email)

    return get_source_runtime().get_or_create_client(("europe_pmc", resolved_email), _factory)


def get_core_client(api_key: str | None = None):
    """Get or create CORE client (lazy initialization)."""
    settings = _load_settings()
    resolved_api_key = api_key or settings.core_api_key

    def _factory():
        from .core import COREClient

        return COREClient(api_key=resolved_api_key)

    return get_source_runtime().get_or_create_client(("core", resolved_api_key), _factory)


def get_scopus_client(api_key: str | None = None, insttoken: str | None = None):
    """Get or create Scopus client (lazy initialization, default-off unless licensed)."""
    settings = _load_settings()
    resolved_api_key = api_key or settings.scopus_api_key
    resolved_insttoken = insttoken or settings.scopus_insttoken

    def _factory():
        from .scopus import ScopusClient

        return ScopusClient(api_key=resolved_api_key, insttoken=resolved_insttoken)

    return get_source_runtime().get_or_create_client(
        ("scopus", resolved_api_key, resolved_insttoken),
        _factory,
    )


def get_web_of_science_client(api_key: str | None = None):
    """Get or create Web of Science client (lazy initialization, default-off unless licensed)."""
    settings = _load_settings()
    resolved_api_key = api_key or settings.web_of_science_api_key

    def _factory():
        from .web_of_science import WebOfScienceClient

        return WebOfScienceClient(api_key=resolved_api_key)

    return get_source_runtime().get_or_create_client(("web_of_science", resolved_api_key), _factory)


def get_ncbi_extended_client(email: str | None = None, api_key: str | None = None):
    """Get or create NCBI Extended client (lazy initialization)."""
    settings = _load_settings()
    resolved_email = first_contact_email(email, get_source_contact_email(), settings.ncbi_email)
    resolved_api_key = api_key or settings.ncbi_api_key

    def _factory():
        from .ncbi_extended import NCBIExtendedClient

        return NCBIExtendedClient(email=resolved_email, api_key=resolved_api_key)

    return get_source_runtime().get_or_create_client(
        ("ncbi_extended", resolved_email, resolved_api_key),
        _factory,
    )


def get_crossref_client(email: str | None = None):
    """Get or create CrossRef client (lazy initialization)."""
    settings = _load_settings()
    resolved_email = first_contact_email(
        email,
        settings.crossref_email,
        get_source_contact_email(),
        settings.ncbi_email,
    )

    def _factory():
        from .crossref import CrossRefClient

        return CrossRefClient(email=resolved_email)

    return get_source_runtime().get_or_create_client(("crossref", resolved_email), _factory)


def get_unpaywall_client(email: str | None = None):
    """Get or create Unpaywall client (lazy initialization)."""
    settings = _load_settings()
    resolved_email = first_contact_email(
        email,
        settings.unpaywall_email,
        get_source_contact_email(),
        settings.ncbi_email,
    )

    def _factory():
        from .unpaywall import UnpaywallClient

        return UnpaywallClient(email=resolved_email)

    return get_source_runtime().get_or_create_client(("unpaywall", resolved_email), _factory)


def get_openurl_builder(resolver_base: str | None = None, preset: str | None = None):
    """Get or create OpenURL builder (lazy initialization)."""
    settings = _load_settings()
    resolved_base = resolver_base or settings.openurl_resolver

    def _factory():
        from .openurl import OpenURLBuilder, get_openurl_config

        if preset:
            return OpenURLBuilder.from_preset(preset, resolver_base)
        if resolved_base:
            return OpenURLBuilder(resolver_base=resolved_base)
        return get_openurl_config().get_builder()

    return get_source_runtime().get_or_create_client(("openurl", preset, resolved_base), _factory)


def get_openi_client():
    """Get or create Open-i client (lazy initialization)."""

    def _factory():
        from .openi import OpenIClient

        return OpenIClient()

    return get_source_runtime().get_or_create_client(("openi",), _factory)


def get_browser_session_fetcher():
    """Get or create browser-session fetcher (lazy initialization)."""
    from .browser_session import get_browser_session_fetcher as _get_fetcher

    return _get_fetcher()


async def search_alternate_source_adapter(
    query: str,
    source: AlternateSearchSource,
    limit: int = 10,
    min_year: int | None = None,
    max_year: int | None = None,
    open_access_only: bool = False,
    has_fulltext: bool = False,
    email: str | None = None,
) -> SourceAdapterResult[dict[str, Any]]:
    """Search one non-PubMed source through the sole typed adapter contract."""

    operation = "search"
    resolved_source = source if isinstance(source, str) and source in _ALTERNATE_SOURCE_ADAPTERS else None
    if resolved_source is None or not _is_alternate_source(resolved_source):
        invalid_source = ValueError(f"Unknown, disabled, or non-search source: {source!r}")
        return SourceAdapterResult.failure(
            source=str(source),
            operation=operation,
            error=normalize_source_adapter_error(str(source), operation, invalid_source),
        )

    try:
        _validate_alternate_search_request(
            query=query,
            source=resolved_source,
            limit=limit,
            min_year=min_year,
            max_year=max_year,
            open_access_only=open_access_only,
            has_fulltext=has_fulltext,
        )
        runner = _ALTERNATE_SOURCE_ADAPTERS[resolved_source]
        outcome = await runner(
            query,
            limit,
            min_year,
            max_year,
            open_access_only,
            has_fulltext,
            email,
        )
        return validate_source_adapter_mapping_result(
            outcome,
            expected_source=resolved_source,
            expected_operation=operation,
        )
    except Exception as exc:
        adapter_error = normalize_source_adapter_error(resolved_source, operation, exc)
        logger.warning(
            "Alternate source adapter failed: %s.%s (%s)",
            resolved_source,
            operation,
            type(exc).__name__,
        )
        return SourceAdapterResult.failure(
            source=resolved_source,
            operation=operation,
            error=adapter_error,
        )


def _validate_alternate_search_request(
    *,
    query: str,
    source: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    open_access_only: bool,
    has_fulltext: bool,
) -> None:
    """Reject malformed source requests rather than allowing provider clamping."""

    if not isinstance(query, str) or not query.strip():
        raise ValueError("Alternate source search requires a non-empty query")
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise TypeError("Alternate source search limit must be an integer")
    max_limit = _ALTERNATE_SOURCE_LIMITS[source]
    if not 1 <= limit <= max_limit:
        raise ValueError(f"{source} search limit must be between 1 and {max_limit}")
    for field_name, value in (("min_year", min_year), ("max_year", max_year)):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            raise TypeError(f"{field_name} must be an integer or None")
        if value is not None and not 1000 <= value <= 9999:
            raise ValueError(f"{field_name} must be between 1000 and 9999")
    if min_year is not None and max_year is not None and min_year > max_year:
        raise ValueError("min_year must be less than or equal to max_year")
    if not isinstance(open_access_only, bool) or not isinstance(has_fulltext, bool):
        raise TypeError("open_access_only and has_fulltext must be booleans")
    if has_fulltext and source not in {"europe_pmc", "core"}:
        raise ValueError(f"{source} does not support a fulltext availability filter")
    if open_access_only and source == "core":
        raise ValueError("CORE does not expose a verified open-access-only filter")


def _page_adapter_result(
    *,
    source: str,
    logical_query: str,
    page: SourceSearchPage[dict[str, Any]],
) -> SourceAdapterResult[dict[str, Any]]:
    """Project one provider page into the shared result without losing metadata."""

    if not isinstance(page, SourceSearchPage):
        raise TypeError(f"{source} adapter must return SourceSearchPage")
    if page.source != source:
        raise ValueError(f"{source} adapter returned page for {page.source!r}")
    items = list(page.items)
    total_count = len(items) if page.total is None else page.total
    metadata: dict[str, Any] = {
        "total_available": page.total,
        "warnings": list(page.warnings),
        "mode": page.mode,
        **dict(page.metadata),
    }
    provenance = {
        "logical_query": logical_query,
        "physical_query": page.query or logical_query,
        "provider_mode": page.mode,
    }
    return SourceAdapterResult(
        source=source,
        operation="search",
        items=items,
        total_count=total_count,
        status="ok" if items else "empty",
        metadata=metadata,
        next_token=page.next_token,
        cursor=page.cursor,
        cost=page.cost,
        provenance=provenance,
    )


def _mapping_adapter_result(
    *,
    source: str,
    logical_query: str,
    physical_query: str,
    items: object,
    total_count: object | None = None,
    next_token: str | int | None = None,
    cursor: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> SourceAdapterResult[dict[str, Any]]:
    """Build a strict mapping result for providers without a page DTO."""

    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise TypeError(f"{source} returned a malformed result list")
    returned = len(items)
    if total_count is None:
        resolved_total = returned
    elif not isinstance(total_count, int) or isinstance(total_count, bool):
        raise TypeError(f"{source} returned a non-integer total count")
    elif total_count < returned:
        raise ValueError(f"{source} returned a total count smaller than its result page")
    else:
        resolved_total = total_count
    return SourceAdapterResult(
        source=source,
        operation="search",
        items=[dict(item) for item in items],
        total_count=resolved_total,
        status="ok" if items else "empty",
        metadata={
            "total_available": total_count,
            **dict(metadata or {}),
        },
        next_token=next_token,
        cursor=cursor,
        provenance={
            "logical_query": logical_query,
            "physical_query": physical_query,
            "provider_mode": "keyword",
        },
    )


async def _run_semantic_scholar_adapter(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    open_access_only: bool,
    has_fulltext: bool,
    email: str | None,
) -> SourceAdapterResult[dict[str, Any]]:
    del has_fulltext, email
    page = await get_semantic_scholar_client().search_page(
        query=query,
        limit=limit,
        min_year=min_year,
        max_year=max_year,
        open_access_only=open_access_only,
    )
    return _page_adapter_result(source="semantic_scholar", logical_query=query, page=page)


async def _run_openalex_adapter(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    open_access_only: bool,
    has_fulltext: bool,
    email: str | None,
) -> SourceAdapterResult[dict[str, Any]]:
    del has_fulltext
    page = await get_openalex_client(email).search_page(
        query=query,
        limit=limit,
        min_year=min_year,
        max_year=max_year,
        open_access_only=open_access_only,
    )
    return _page_adapter_result(source="openalex", logical_query=query, page=page)


async def _run_europe_pmc_adapter(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    open_access_only: bool,
    has_fulltext: bool,
    email: str | None,
) -> SourceAdapterResult[dict[str, Any]]:
    result = await get_europe_pmc_client(email).search(
        query=query,
        limit=limit,
        min_year=min_year,
        max_year=max_year,
        open_access_only=open_access_only,
        has_fulltext=has_fulltext,
    )
    if not isinstance(result, dict):
        raise TypeError("Europe PMC returned a malformed response")
    next_cursor = result.get("next_cursor")
    if next_cursor is not None and not isinstance(next_cursor, str):
        raise TypeError("Europe PMC returned a malformed cursor")
    from .europe_pmc import EuropePMCClient

    physical_query = EuropePMCClient.compile_query(
        query,
        min_year=min_year,
        max_year=max_year,
        open_access_only=open_access_only,
        has_fulltext=has_fulltext,
    )
    return _mapping_adapter_result(
        source="europe_pmc",
        logical_query=query,
        physical_query=physical_query,
        items=result.get("results"),
        total_count=result.get("hit_count"),
        cursor=next_cursor,
    )


async def _run_core_adapter(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    open_access_only: bool,
    has_fulltext: bool,
    email: str | None,
) -> SourceAdapterResult[dict[str, Any]]:
    del open_access_only, email
    client = get_core_client()
    result = await client.search(
        query=query,
        limit=limit,
        year_from=min_year,
        year_to=max_year,
        has_fulltext=has_fulltext,
    )
    if not isinstance(result, dict):
        raise TypeError("CORE returned a malformed response")
    raw_total = result.get("total_hits")
    if not isinstance(raw_total, int) or isinstance(raw_total, bool):
        raise TypeError("CORE returned a non-integer total count")
    return _mapping_adapter_result(
        source="core",
        logical_query=query,
        physical_query=client.compile_query(
            query,
            year_from=min_year,
            year_to=max_year,
            has_fulltext=has_fulltext,
        ),
        items=result.get("results"),
        total_count=raw_total,
        next_token=(limit if raw_total > limit else None),
        metadata={"offset": result.get("offset", 0)},
    )


async def _run_scopus_adapter(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    open_access_only: bool,
    has_fulltext: bool,
    email: str | None,
) -> SourceAdapterResult[dict[str, Any]]:
    del has_fulltext, email
    client = get_scopus_client()
    page = await client.search_page(
        query=query,
        limit=limit,
        min_year=min_year,
        max_year=max_year,
        open_access_only=open_access_only,
    )
    return _page_adapter_result(source="scopus", logical_query=query, page=page)


async def _run_web_of_science_adapter(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    open_access_only: bool,
    has_fulltext: bool,
    email: str | None,
) -> SourceAdapterResult[dict[str, Any]]:
    del has_fulltext, email
    client = get_web_of_science_client()
    page = await client.search_page(
        query=query,
        limit=limit,
        min_year=min_year,
        max_year=max_year,
        open_access_only=open_access_only,
    )
    return _page_adapter_result(source="web_of_science", logical_query=query, page=page)


_ALTERNATE_SOURCE_ADAPTERS: dict[str, AlternateSourceAdapterRunner] = {
    "semantic_scholar": _run_semantic_scholar_adapter,
    "openalex": _run_openalex_adapter,
    "europe_pmc": _run_europe_pmc_adapter,
    "core": _run_core_adapter,
    "scopus": _run_scopus_adapter,
    "web_of_science": _run_web_of_science_adapter,
}
_ALTERNATE_SOURCE_LIMITS = {
    "semantic_scholar": 100,
    "openalex": 100,
    "europe_pmc": 1_000,
    "core": 100,
    "scopus": 25,
    "web_of_science": 25,
}


def _is_alternate_source(source: str) -> bool:
    registry = get_source_registry()
    definition = registry.get(source)
    return bool(
        definition
        and definition.selectable_in_unified
        and definition.supports_primary_search
        and definition.key != "pubmed"
        and definition.alternate_search_runner in _ALTERNATE_SOURCE_ADAPTERS
        and registry.is_enabled(definition.key)
    )


# ============================================================================
# PDF/Fulltext Download (NEW: Multi-source PDF link discovery)
# ============================================================================
def get_fulltext_downloader():
    """Get or create FulltextDownloader instance (lazy initialization)."""

    def _factory():
        from .fulltext_download import FulltextDownloader

        return FulltextDownloader()

    return get_source_runtime().get_or_create_client(("fulltext_downloader",), _factory)


async def close_source_clients() -> None:
    """Close source clients owned by the currently bound runtime."""
    await get_source_runtime().close_source_clients()


# Explicit infrastructure source surface.
__all__ = [
    "SourceRuntime",
    "SourceDefinition",
    "SourceRegistry",
    "SourceSelection",
    "close_source_clients",
    "get_core_client",
    "get_crossref_client",
    "get_europe_pmc_client",
    "get_fulltext_downloader",
    "get_ncbi_extended_client",
    "get_openalex_client",
    "get_openi_client",
    "get_browser_session_fetcher",
    "get_openurl_builder",
    "get_scopus_client",
    "get_web_of_science_client",
    "get_source_registry",
    "get_semantic_scholar_client",
    "get_unpaywall_client",
    "search_alternate_source_adapter",
]
