"""Compose server/tenant-owned fulltext reuse with infrastructure adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pubmed_search.infrastructure.sources.fulltext_prefetch import fetch_prefetch_xml
from pubmed_search.infrastructure.sources.registry import get_source_registry
from pubmed_search.shared.settings import load_settings
from pubmed_search.shared.tenancy import current_tenant

from .tool_session import get_tool_session_runtime

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pubmed_search.application.fulltext.cache import XMLFetcher
    from pubmed_search.domain.entities.article import UnifiedArticle


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
    tenant = current_tenant()
    if not tenant.owns_durable_storage:
        return fetch
    cache = get_tool_session_runtime().fulltext_cache
    tenant_id = tenant.tenant_id

    async def cached(pmcid: str) -> str | None:
        return await cache.get(pmcid, tenant=tenant_id, fetch=fetch)

    return cached
