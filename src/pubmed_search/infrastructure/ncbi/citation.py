"""
Entrez Citation Module - Citation Network Functionality

Provides functionality to explore citation networks (related, citing, references).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from Bio import Entrez

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


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
        try:
            handle = await self._rate_limited_call(
                Entrez.elink,
                dbfrom="pubmed",
                db="pubmed",
                id=pmid,
                linkname="pubmed_pubmed",
            )
            record = await asyncio.to_thread(Entrez.read, handle)
            handle.close()

            related_ids = []
            if record and record[0].get("LinkSetDb"):
                for linkset in record[0]["LinkSetDb"]:
                    if linkset.get("LinkName") == "pubmed_pubmed":
                        links = linkset.get("Link", [])
                        related_ids = [link["Id"] for link in links[:limit]]
                        break

            if related_ids:
                return await self.fetch_details(related_ids)
            return []
        except Exception as e:
            return [{"error": str(e)}]

    async def get_citing_articles(self, pmid: str, limit: int = 10) -> list[dict[str, Any]]:
        """
        Find articles that cite this article (via PMC).

        Args:
            pmid: PubMed ID.
            limit: Maximum number of citing articles to return.

        Returns:
            List of citing article details.
        """
        try:
            handle = await self._rate_limited_call(
                Entrez.elink,
                dbfrom="pubmed",
                db="pubmed",
                id=pmid,
                linkname="pubmed_pubmed_citedin",
            )
            record = await asyncio.to_thread(Entrez.read, handle)
            handle.close()

            citing_ids = []
            if record and record[0].get("LinkSetDb"):
                for linkset in record[0]["LinkSetDb"]:
                    if linkset.get("LinkName") == "pubmed_pubmed_citedin":
                        links = linkset.get("Link", [])
                        citing_ids = [link["Id"] for link in links[:limit]]
                        break

            if citing_ids:
                return await self.fetch_details(citing_ids)
            return []
        except Exception as e:
            return [{"error": str(e)}]

    async def get_article_references(self, pmid: str, limit: int = 20) -> list[dict[str, Any]]:
        """
        Get references (bibliography) of an article via PMC.

        Args:
            pmid: PubMed ID.
            limit: Maximum number of references to return.

        Returns:
            List of referenced article details.
        """
        try:
            handle = await self._rate_limited_call(
                Entrez.elink,
                dbfrom="pubmed",
                db="pubmed",
                id=pmid,
                linkname="pubmed_pubmed_refs",
            )
            record = await asyncio.to_thread(Entrez.read, handle)
            handle.close()

            ref_ids = []
            if record and record[0].get("LinkSetDb"):
                for linkset in record[0]["LinkSetDb"]:
                    if linkset.get("LinkName") == "pubmed_pubmed_refs":
                        links = linkset.get("Link", [])
                        ref_ids = [link["Id"] for link in links[:limit]]
                        break

            if ref_ids:
                return await self.fetch_details(ref_ids)
            return []
        except Exception as e:
            return [{"error": str(e)}]

    # Aliases for backward compatibility
    async def find_related_articles(self, pmid: str, limit: int = 5) -> list[dict[str, Any]]:
        """Alias for get_related_articles."""
        return await self.get_related_articles(pmid, limit)

    async def find_citing_articles(self, pmid: str, limit: int = 10) -> list[dict[str, Any]]:
        """Alias for get_citing_articles."""
        return await self.get_citing_articles(pmid, limit)
