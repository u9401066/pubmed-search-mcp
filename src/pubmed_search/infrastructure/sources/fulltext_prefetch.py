"""Cheap structured-XML adapter sharing Europe PMC's existing transport budget."""

from __future__ import annotations

from pubmed_search.application.fulltext.cache import MAX_XML_CACHE_ITEM_BYTES

from .contact import get_source_contact_email
from .europe_pmc import EuropePMCClient
from .runtime import get_source_runtime


class _PrefetchClient(EuropePMCClient):
    """One attempt, small response cap; never discover links or download PDFs."""

    _MAX_RETRIES = 0

    def __init__(self) -> None:
        super().__init__(email=get_source_contact_email(), timeout=10)
        self._max_response_bytes = MAX_XML_CACHE_ITEM_BYTES


async def fetch_prefetch_xml(pmcid: str) -> str | None:
    """Reuse the owning server's bounded client and provider-wide rate/cooldown gates."""
    client = get_source_runtime().get_or_create_client(("europe_pmc_prefetch",), _PrefetchClient)
    return await client.get_fulltext_xml(pmcid)
