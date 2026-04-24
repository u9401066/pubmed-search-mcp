"""
Entrez Utils Module - Utility Functions

Provides various utility functions for Entrez operations including:
- Quick summary fetch
- Spell checking
- Database info
- MeSH validation
- Citation matching
- Export functions
"""

from __future__ import annotations

import asyncio
from typing import Any

from Bio import Entrez

from .base import DEFAULT_ENTREZ_TOOL, execute_entrez_operation, run_entrez_callable


class UtilsMixin:
    """
    Mixin providing utility functions for Entrez operations.

    Methods:
        quick_fetch_summary: Fast metadata fetch using ESummary
        spell_check_query: Check and correct query spelling
        get_database_counts: Get result counts across databases
        validate_mesh_terms: Validate MeSH terms
        find_by_citation: Find article by citation details
        export_citations: Export citations in various formats
        get_database_info: Get database statistics
    """

    async def _execute_entrez(self, operation, *, service_name: str, timeout: float = 45.0):
        """Execute one utility operation through the shared transport kernel."""
        if hasattr(self, "_execute_entrez_call"):
            return await self._execute_entrez_call(operation, service_name=service_name, timeout=timeout)
        return await execute_entrez_operation(
            operation,
            api_key=getattr(self, "_api_key", None),
            service_name=service_name,
            timeout=timeout,
        )

    def _entrez_runtime_kwargs(self) -> dict[str, Any]:
        """Return consistent Bio.Entrez runtime metadata for this caller."""
        return {
            "email": getattr(self, "_email", None),
            "api_key": getattr(self, "_api_key", None),
            "tool": getattr(self, "_tool", DEFAULT_ENTREZ_TOOL),
        }

    async def quick_fetch_summary(self, id_list: list[str]) -> list[dict[str, Any]]:
        """
        Fetch article summaries using ESummary (faster than EFetch for metadata only).

        Args:
            id_list: List of PubMed IDs.

        Returns:
            List of article summaries with basic metadata.
        """
        if not id_list:
            return []

        try:
            async def _do_summary() -> Any:
                handle = await asyncio.to_thread(
                    run_entrez_callable,
                    Entrez,
                    Entrez.esummary,
                    db="pubmed",
                    id=",".join(id_list),
                    **self._entrez_runtime_kwargs(),
                )
                try:
                    return await asyncio.to_thread(Entrez.read, handle)
                finally:
                    handle.close()

            summaries = await self._execute_entrez(_do_summary, service_name="ncbi-utils:esummary")

            results = []
            for summary in summaries:
                # ESummary returns DictionaryElement but hasattr check is safer
                if hasattr(summary, "get") or hasattr(summary, "__getitem__"):
                    # AuthorList contains StringElements, not dicts
                    author_list = summary.get("AuthorList", [])
                    authors = [str(author) for author in author_list]

                    pub_date = summary.get("PubDate", "")
                    year = pub_date.split()[0] if pub_date else ""

                    results.append(
                        {
                            "pmid": str(summary.get("Id", "")),
                            "title": str(summary.get("Title", "")),
                            "authors": authors,
                            "journal": str(summary.get("Source", "")),
                            "year": year,
                            "doi": str(summary.get("DOI", "")),
                            "pmc_id": str(summary.get("PMCID", "")),
                        }
                    )

            return results
        except Exception as e:
            return [{"error": str(e)}]

    async def spell_check_query(self, query: str) -> str:
        """
        Get spelling suggestions for search queries using ESpell.

        Args:
            query: The search query to check.

        Returns:
            Corrected query string if suggestions found, original query otherwise.
        """
        try:
            async def _do_spell_check() -> dict[str, Any]:
                handle = await asyncio.to_thread(
                    run_entrez_callable,
                    Entrez,
                    Entrez.espell,
                    db="pubmed",
                    term=query,
                    **self._entrez_runtime_kwargs(),
                )
                try:
                    return await asyncio.to_thread(Entrez.read, handle)
                finally:
                    handle.close()

            result = await self._execute_entrez(_do_spell_check, service_name="ncbi-utils:espell")

            corrected = result.get("CorrectedQuery", "")
            return corrected if corrected else query
        except Exception:
            return query

    async def get_database_counts(self, query: str) -> dict[str, Any]:
        """
        Get result counts across multiple NCBI databases using EGQuery.

        Args:
            query: The search query.

        Returns:
            Dictionary mapping database names to result counts.
        """
        try:
            async def _do_egquery() -> dict[str, Any]:
                handle = await asyncio.to_thread(
                    run_entrez_callable,
                    Entrez,
                    Entrez.egquery,
                    term=query,
                    **self._entrez_runtime_kwargs(),
                )
                try:
                    return await asyncio.to_thread(Entrez.read, handle)
                finally:
                    handle.close()

            result = await self._execute_entrez(_do_egquery, service_name="ncbi-utils:egquery")

            counts = {}
            for db_result in result["eGQueryResult"]:
                db_name = db_result.get("DbName", "")
                count = db_result.get("Count", "0")
                try:
                    counts[db_name] = int(count)
                except ValueError:
                    counts[db_name] = 0

            return counts
        except Exception as e:
            return {"error": str(e)}

    async def validate_mesh_terms(self, terms: list[str]) -> dict[str, Any]:
        """
        Validate MeSH terms and get their IDs using MeSH database.

        Args:
            terms: List of potential MeSH terms to validate.

        Returns:
            Dictionary with valid terms and their IDs.
        """
        try:
            query = " OR ".join([f'"{term}"[MeSH Terms]' for term in terms])

            async def _do_mesh_search() -> dict[str, Any]:
                handle = await asyncio.to_thread(
                    run_entrez_callable,
                    Entrez,
                    Entrez.esearch,
                    db="mesh",
                    term=query,
                    retmax=len(terms),
                    **self._entrez_runtime_kwargs(),
                )
                try:
                    return await asyncio.to_thread(Entrez.read, handle)
                finally:
                    handle.close()

            result = await self._execute_entrez(_do_mesh_search, service_name="ncbi-utils:mesh-esearch")

            mesh_ids = result.get("IdList", [])

            if mesh_ids:
                async def _do_mesh_summary() -> Any:
                    handle = await asyncio.to_thread(
                        run_entrez_callable,
                        Entrez,
                        Entrez.esummary,
                        db="mesh",
                        id=",".join(mesh_ids),
                        **self._entrez_runtime_kwargs(),
                    )
                    try:
                        return await asyncio.to_thread(Entrez.read, handle)
                    finally:
                        handle.close()

                summaries = await self._execute_entrez(
                    _do_mesh_summary,
                    service_name="ncbi-utils:mesh-esummary",
                )

                validated_terms = []
                for summary in summaries:
                    if isinstance(summary, dict):
                        validated_terms.append(
                            {
                                "mesh_id": summary.get("Id", ""),
                                "term": summary.get("DS_MeshTerms", [""])[0] if summary.get("DS_MeshTerms") else "",
                                "tree_numbers": summary.get("DS_IdxLinks", []),
                            }
                        )

                return {"valid_count": len(validated_terms), "terms": validated_terms}

            return {"valid_count": 0, "terms": []}
        except Exception as e:
            return {"error": str(e)}

    async def find_by_citation(
        self,
        journal: str,
        year: str,
        volume: str = "",
        first_page: str = "",
        author: str = "",
        title: str = "",
    ) -> str | None:
        """
        Find article by citation details using ECitMatch.

        Args:
            journal: Journal name or abbreviation.
            year: Publication year.
            volume: Volume number (optional).
            first_page: First page number (optional).
            author: First author last name (optional).
            title: Article title (optional).

        Returns:
            PMID if found, None otherwise.
        """
        try:
            citation_string = f"{journal}|{year}|{volume}|{first_page}|{author}||"

            async def _do_citation_match() -> str:
                handle = await asyncio.to_thread(
                    run_entrez_callable,
                    Entrez,
                    Entrez.ecitmatch,
                    db="pubmed",
                    bdata=citation_string,
                    **self._entrez_runtime_kwargs(),
                )
                try:
                    return str((await asyncio.to_thread(handle.read)).strip())
                finally:
                    handle.close()

            result = await self._execute_entrez(_do_citation_match, service_name="ncbi-utils:ecitmatch")

            if result and "\t" in result:
                parts = result.split("\t")
                if len(parts) > 1 and parts[1].isdigit():
                    return parts[1]

            return None
        except Exception:
            return None

    async def verify_references(
        self,
        citations: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        """
        Verify a batch of reference citations against PubMed via ECitMatch.

        This promotes ECitMatch from a one-off utility into a first-class
        reference-verification workflow: each citation is looked up concurrently
        and the result contains the original citation fields plus the resolved
        PMID (or None when not found) and a ``verified`` flag.

        Args:
            citations: List of citation dicts, each may contain any subset of:
                - ``journal``: Journal name or abbreviation.
                - ``year``: Publication year.
                - ``volume``: Volume number.
                - ``first_page``: First page number.
                - ``author``: First author last name.
                Unrecognised keys are passed through unchanged in the result.

        Returns:
            List of result dicts with the original citation fields plus:
            - ``pmid``: Resolved PubMed identifier, or ``None`` when not found.
            - ``verified``: ``True`` when a PMID was found, ``False`` otherwise.
        """
        async def _verify_one(citation: dict[str, str]) -> dict[str, Any]:
            pmid = await self.find_by_citation(
                journal=citation.get("journal", ""),
                year=citation.get("year", ""),
                volume=citation.get("volume", ""),
                first_page=citation.get("first_page", ""),
                author=citation.get("author", ""),
                title=citation.get("title", ""),
            )
            return {**citation, "pmid": pmid, "verified": pmid is not None}

        return list(await asyncio.gather(*[_verify_one(c) for c in citations]))

    async def export_citations(self, id_list: list[str], fmt: str = "medline") -> str:
        """
        Export citations in various formats.

        Args:
            id_list: List of PubMed IDs.
            fmt: Output format - "medline", "pubmed" (XML), "abstract".

        Returns:
            Formatted citation text.
        """
        if not id_list:
            return ""

        try:
            valid_formats = {
                "medline": ("medline", "text"),
                "pubmed": ("pubmed", "xml"),
                "abstract": ("abstract", "text"),
            }

            if fmt not in valid_formats:
                fmt = "medline"

            rettype, retmode = valid_formats[fmt]

            async def _do_export() -> str:
                handle = await asyncio.to_thread(
                    run_entrez_callable,
                    Entrez,
                    Entrez.efetch,
                    db="pubmed",
                    id=id_list,
                    rettype=rettype,
                    retmode=retmode,
                    **self._entrez_runtime_kwargs(),
                )
                try:
                    return await asyncio.to_thread(handle.read)
                finally:
                    handle.close()

            return await self._execute_entrez(_do_export, service_name="ncbi-utils:efetch", timeout=60.0)
        except Exception as e:
            return f"Error exporting citations: {e!s}"

    async def get_database_info(self, db: str = "pubmed") -> dict[str, Any]:
        """
        Get database statistics and field information using EInfo.

        Args:
            db: Database name (default: pubmed).

        Returns:
            Dictionary with database information including:
            - name, description, count, last_update
            - available search fields
        """
        try:
            async def _do_einfo() -> dict[str, Any]:
                handle = await asyncio.to_thread(
                    run_entrez_callable,
                    Entrez,
                    Entrez.einfo,
                    db=db,
                    **self._entrez_runtime_kwargs(),
                )
                try:
                    return await asyncio.to_thread(Entrez.read, handle)
                finally:
                    handle.close()

            result = await self._execute_entrez(_do_einfo, service_name="ncbi-utils:einfo")

            db_info = result.get("DbInfo", {})

            return {
                "name": db_info.get("DbName", ""),
                "menu_name": db_info.get("MenuName", ""),
                "description": db_info.get("Description", ""),
                "count": db_info.get("Count", "0"),
                "last_update": db_info.get("LastUpdate", ""),
                "fields": [
                    {
                        "name": field.get("Name", ""),
                        "full_name": field.get("FullName", ""),
                        "description": field.get("Description", ""),
                    }
                    for field in db_info.get("FieldList", [])
                ],
            }
        except Exception as e:
            return {"error": str(e)}
