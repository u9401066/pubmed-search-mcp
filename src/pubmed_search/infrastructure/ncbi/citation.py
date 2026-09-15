"""
Entrez Citation Module - Citation Network Functionality

Provides functionality to explore citation networks (related, citing, references).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from Bio import Entrez

from pubmed_search.domain.value_objects.article_identifiers import normalize_pmid, try_normalize_pmid

from .base import NCBIProviderSchemaError, raise_ncbi_infrastructure_error

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


async def _read_entrez_handle(handle: Any) -> Any:
    """Read an Entrez handle and always close it, even on parse failure."""
    try:
        return await asyncio.to_thread(Entrez.read, handle)
    finally:
        handle.close()


class CitationMixin:
    """
    Mixin providing citation network functionality.

    Requires the host class to provide:
        _rate_limited_call: Callable for rate-limited Entrez calls
        fetch_details: Method to fetch article details by PMID list

    Methods:
        get_related_articles: Find related articles using PubMed's algorithm
        get_citing_articles: Find articles that cite a given paper
        get_article_references: Get the bibliography of an article
    """

    _rate_limited_call: Callable[..., Coroutine[Any, Any, Any]]
    fetch_details: Callable[..., Coroutine[Any, Any, list[dict[str, Any]]]]

    async def get_related_articles(self, pmid: str, limit: int = 5) -> list[dict[str, Any]]:
        """
        Find related articles using PubMed's related articles feature.

        Args:
            pmid: PubMed ID to find related articles for.
            limit: Maximum number of related articles to return.

        Returns:
            List of related article details.
        """
        return await self._get_linked_articles(pmid, limit, "pubmed_pubmed", "related_articles", exclude_self=True)

    async def get_citing_articles(self, pmid: str, limit: int = 10) -> list[dict[str, Any]]:
        """
        Find articles that cite this article (via PMC).

        Args:
            pmid: PubMed ID.
            limit: Maximum number of citing articles to return.

        Returns:
            List of citing article details.
        """
        return await self._get_linked_articles(pmid, limit, "pubmed_pubmed_citedin", "citing_articles")

    async def get_article_references(self, pmid: str, limit: int = 20) -> list[dict[str, Any]]:
        """
        Get references (bibliography) of an article via PMC.

        Args:
            pmid: PubMed ID.
            limit: Maximum number of references to return.

        Returns:
            List of referenced article details.
        """
        return await self._get_linked_articles(pmid, limit, "pubmed_pubmed_refs", "article_references")

    async def _get_linked_articles(
        self, pmid: str, limit: int, linkname: str, operation: str, *, exclude_self: bool = False
    ) -> list[dict[str, Any]]:
        """Share ELink parsing while preserving direction, order and error provenance."""
        pmid = normalize_pmid(pmid)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= 10_000:
            raise ValueError("limit must be an integer between 0 and 10000")
        if limit == 0:
            return []
        try:
            handle = await self._rate_limited_call(
                Entrez.elink, dbfrom="pubmed", db="pubmed", id=pmid, linkname=linkname
            )
            record = await _read_entrez_handle(handle)
            ids = self._parse_linked_ids(record, pmid, linkname, operation, exclude_self=exclude_self)
            return await self.fetch_details(list(ids)[:limit]) if ids else []
        except Exception as exc:
            raise_ncbi_infrastructure_error(operation, exc)

    @staticmethod
    def _parse_linked_ids(
        record: Any, pmid: str, linkname: str, operation: str, *, exclude_self: bool
    ) -> dict[str, None]:
        """Validate provider link rows and retain first occurrence order."""
        if not isinstance(record, list):
            raise NCBIProviderSchemaError(operation)
        ids: dict[str, None] = {}
        for group in record:
            if not isinstance(group, dict) or not isinstance(group.get("LinkSetDb", []), list):
                raise NCBIProviderSchemaError(operation)
            for linkset in group.get("LinkSetDb", []):
                if not isinstance(linkset, dict):
                    raise NCBIProviderSchemaError(operation)
                if linkset.get("LinkName") != linkname:
                    continue
                links = linkset.get("Link", [])
                if not isinstance(links, list):
                    raise NCBIProviderSchemaError(operation)
                for link in links:
                    identifier = try_normalize_pmid(link.get("Id")) if isinstance(link, dict) else None
                    if identifier is None:
                        raise NCBIProviderSchemaError(operation)
                    if not exclude_self or identifier != pmid:
                        ids[identifier] = None
        return ids
