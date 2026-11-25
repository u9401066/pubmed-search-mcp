"""Compose server/tenant-owned fulltext reuse with infrastructure adapters."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pubmed_search.infrastructure.sources.fulltext_prefetch import fetch_prefetch_xml
from pubmed_search.infrastructure.sources.registry import get_source_registry
from pubmed_search.shared.settings import load_settings
from pubmed_search.shared.tenancy import current_tenant

from .tool_session import get_session_manager, get_tool_session_runtime

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pubmed_search.application.fulltext.cache import FulltextCache, XMLFetcher
    from pubmed_search.application.fulltext.plan import FulltextAccessContext
    from pubmed_search.application.fulltext.service import SuppliedFulltextLookup
    from pubmed_search.application.fulltext.supplied import SuppliedFulltextRecord, SuppliedFulltextStore
    from pubmed_search.domain.entities.article import UnifiedArticle
    from pubmed_search.shared.settings import AppSettings


def prefetch_search_fulltext(articles: Sequence[UnifiedArticle]) -> dict[str, Any]:
    """Bind a cheap prefetch to a stable owner; retain no MCP Context or callbacks."""
    tenant = current_tenant()
    limit = load_settings().fulltext_prefetch_limit
    reason = None
    if not tenant.owns_durable_storage:
        reason = "stable_tenant_required"
    elif not limit:
        reason = "operator_disabled"
    elif not get_source_registry().is_enabled("europe_pmc"):
        reason = "source_disabled"
    if reason:
        return {"mode": "prefetch", "status": "disabled", "reason": reason, "articles": []}
    snapshot = get_tool_session_runtime().fulltext_cache.prefetch(
        articles,
        tenant=tenant.tenant_id,
        fetch=fetch_prefetch_xml,
        limit=limit,
    )
    for article in snapshot["articles"]:
        article["read_request"] = {
            "tool": "get_fulltext",
            "arguments": {"source": dict(article["source"]), "include_pdf_links": False, "output_format": "json"},
        }
    return snapshot


async def get_cached_fulltext_xml(pmcid: str, fetch: XMLFetcher) -> str | None:
    """Share ready/in-flight XML across get_fulltext calls for one stable tenant."""
    return await bind_cached_fulltext_fetcher(fetch)(pmcid)


def bind_cached_fulltext_fetcher(fetch: XMLFetcher) -> XMLFetcher:
    """Capture this request's tenant and runtime cache for later, concurrent use.

    Fulltext sources may run in child tasks, which see a *copy* of the request
    context; resolving the cache here keeps every task on one shared cache.
    """
    return _bind_cached(fetch, get_tool_session_runtime().fulltext_cache)


def bind_cached_article_page_fetcher(fetch: XMLFetcher) -> XMLFetcher:
    """Share parsed PMC article pages across explicit reads of one stable tenant.

    Only ``get_fulltext`` binds this fetcher; search prefetch never does, so the
    public article page is never read speculatively or in batch.
    """
    return _bind_cached(fetch, get_tool_session_runtime().article_page_cache)


def _bind_cached(fetch: XMLFetcher, cache: FulltextCache) -> XMLFetcher:
    tenant = current_tenant()
    if not tenant.owns_durable_storage:
        return fetch
    tenant_id = tenant.tenant_id

    async def cached(pmcid: str) -> str | None:
        return await cache.get(pmcid, tenant=tenant_id, fetch=fetch)

    return cached


def supplied_fulltext_store() -> SuppliedFulltextStore | None:
    """Return the current tenant's store of registered (supplied) fulltext.

    The store lives under the tenant's session data directory, beside its
    artifacts. Callers that may not own durable data, or servers without a
    persistent data directory, get ``None``.
    """
    from pubmed_search.application.fulltext.supplied import SuppliedFulltextStore

    if not current_tenant().owns_durable_storage:
        return None
    manager = get_session_manager()
    root = getattr(manager, "data_dir", None)  # tenant-ok: the session manager is already tenant-scoped
    if not isinstance(root, (str, Path)):
        return None
    return SuppliedFulltextStore(Path(root) / "fulltext" / "supplied")


def attach_registered_fulltext(articles: list[dict[str, Any]]) -> None:
    """Mark note-export articles that have registered (supplied) fulltext.

    Only facts are attached (origin, artifact URI, retrieval time), never the
    text itself; the note records that unverified supplied text exists.
    """
    store = supplied_fulltext_store()
    if store is None:
        return
    for article in articles:
        identifiers = [
            (kind, str(article[key]))
            for kind, key in (("pmid", "pmid"), ("pmcid", "pmc_id"), ("doi", "doi"))
            if article.get(key)
        ]
        try:
            record = store.find(identifiers) if identifiers else None
        except Exception:
            record = None
        if record is not None:
            article["registered_fulltext"] = {
                "origin": record.origin,
                "record_id": record.record_id,
                "artifact_uri": record.artifact_uri or "",
                "retrieved_at": record.provenance.retrieved_at,
            }


def bind_supplied_fulltext_lookup() -> SuppliedFulltextLookup | None:
    """Capture this tenant's supplied-fulltext store for get_fulltext reads."""
    store = supplied_fulltext_store()
    if store is None:
        return None

    async def lookup(identifiers: list[tuple[str, str]]) -> SuppliedFulltextRecord | None:
        return await asyncio.to_thread(store.find, identifiers)

    return lookup


def build_fulltext_access_context(settings: AppSettings) -> FulltextAccessContext:
    """Describe the access routes configured on this server (never their secrets)."""
    from pubmed_search.application.fulltext.plan import FulltextAccessContext
    from pubmed_search.infrastructure.sources.browser_session import get_browser_session_config
    from pubmed_search.infrastructure.sources.openurl import get_openurl_config

    try:
        openurl_configured = get_openurl_config().get_builder() is not None
    except Exception:
        openurl_configured = False
    try:
        broker_configured = bool(get_browser_session_config().is_configured)
    except Exception:
        broker_configured = False
    return FulltextAccessContext(
        article_page_enabled=settings.fulltext_pmc_html,
        openurl_configured=openurl_configured,
        ezproxy_configured=bool(settings.ezproxy_enabled and settings.ezproxy_host),
        browser_broker_configured=broker_configured,
    )
