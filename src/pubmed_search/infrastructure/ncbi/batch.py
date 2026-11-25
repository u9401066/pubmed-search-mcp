"""
Entrez Batch Module - Large Result Set Processing

Provides functionality for processing large result sets using NCBI History Server.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

from Bio import Entrez

from .base import (
    DEFAULT_ENTREZ_TOOL,
    NCBIProviderSchemaError,
    execute_entrez_operation,
    raise_ncbi_infrastructure_error,
    run_entrez_callable,
)

# PubMed's E-utilities ESearch cannot page beyond the first 10,000 records.
MAX_ESEARCH_RETRIEVAL = 10_000
_HISTORY_MAX_ATTEMPTS = 3
_HISTORY_RETRY_DELAY = 2.0


def _string_values(value: Any) -> list[str]:
    """Return a bounded list of provider strings from an Entrez list element."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()][:50]
    return []


def _parse_esearch_snapshot(record: Any, *, use_history: bool) -> dict[str, Any]:
    """Validate one ESearch envelope without trusting provider types."""
    if not isinstance(record, dict) or "Count" not in record:
        raise NCBIProviderSchemaError("history_search")
    try:
        count = int(str(record["Count"]))
    except (TypeError, ValueError):
        raise NCBIProviderSchemaError("history_search") from None
    raw_ids = record.get("IdList", [])
    if count < 0 or not isinstance(raw_ids, (list, tuple)):
        raise NCBIProviderSchemaError("history_search")
    pmids = [str(item).strip() for item in raw_ids]
    if any(not pmid.isascii() or not pmid.isdigit() or int(pmid) <= 0 for pmid in pmids):
        raise NCBIProviderSchemaError("history_search")
    webenv = str(record.get("WebEnv") or "") or None
    query_key = str(record.get("QueryKey") or "") or None
    if use_history and count > len(pmids) and (webenv is None or query_key is None):
        raise NCBIProviderSchemaError("history_search")

    translation_set: list[dict[str, str]] = []
    raw_translation_set = record.get("TranslationSet") or []
    if isinstance(raw_translation_set, (list, tuple)):
        for item in raw_translation_set[:200]:
            if isinstance(item, dict):
                translation_set.append({"from": str(item.get("From", "")), "to": str(item.get("To", ""))})
    raw_errors = record.get("ErrorList") or {}
    raw_warnings = record.get("WarningList") or {}
    errors = raw_errors if isinstance(raw_errors, dict) else {}
    warnings = raw_warnings if isinstance(raw_warnings, dict) else {}
    translation = record.get("QueryTranslation")
    return {
        "count": count,
        "pmids": pmids,
        "webenv": webenv,
        "query_key": query_key,
        "query_translation": str(translation) if translation is not None and str(translation).strip() else None,
        "translation_set": translation_set,
        "provider_errors": {
            "phrases_not_found": _string_values(errors.get("PhraseNotFound")),
            "fields_not_found": _string_values(errors.get("FieldNotFound")),
        },
        "provider_warnings": {
            "phrases_ignored": _string_values(warnings.get("PhraseIgnored")),
            "quoted_phrases_not_found": _string_values(warnings.get("QuotedPhraseNotFound")),
            "output_messages": _string_values(warnings.get("OutputMessage")),
        },
    }


def _parse_uilist(payload: Any) -> list[str]:
    """Parse an EFetch ``rettype=uilist`` text payload into canonical PMIDs."""
    text = payload.decode("utf-8", errors="strict") if isinstance(payload, bytes) else payload
    if not isinstance(text, str):
        raise NCBIProviderSchemaError("history_pmids")
    pmids = [line.strip() for line in text.splitlines() if line.strip()]
    if any(not pmid.isascii() or not pmid.isdigit() or int(pmid) <= 0 for pmid in pmids):
        raise NCBIProviderSchemaError("history_pmids")
    return pmids


class BatchMixin:
    """
    Mixin providing batch processing functionality using NCBI History Server.

    Methods:
        search_with_history: Search and store results on NCBI server
        fetch_batch_from_history: Fetch results in batches
        esearch_snapshot: Count/translation-aware ESearch snapshot (optionally on the History Server)
        fetch_history_pmids: Page PMIDs from a stored History Server snapshot (EFetch uilist)
    """

    async def search_with_history(self, query: str, batch_size: int = 500) -> dict[str, Any]:
        """
        Search large result sets efficiently using NCBI History Server.
        Returns WebEnv and QueryKey for batch processing.

        Args:
            query: Search query string.
            batch_size: Number of results to process per batch.

        Returns:
            Dictionary with search metadata for batch processing:
            - webenv: WebEnv identifier for this search session
            - query_key: QueryKey for this search
            - count: Total number of results
            - batch_size: Recommended batch size
        """
        try:
            api_key = getattr(self, "_api_key", None)
            email = getattr(self, "_email", None)
            tool = getattr(self, "_tool", DEFAULT_ENTREZ_TOOL)

            async def do_search() -> dict[str, Any]:
                handle = await asyncio.to_thread(
                    run_entrez_callable,
                    Entrez,
                    Entrez.esearch,
                    db="pubmed",
                    term=query,
                    usehistory="y",
                    retmax=0,
                    email=email,
                    api_key=api_key,
                    tool=tool,
                )
                try:
                    return await asyncio.to_thread(Entrez.read, handle)
                finally:
                    handle.close()

            search_results = await execute_entrez_operation(
                do_search,
                api_key=api_key,
                service_name="ncbi-batch:esearch",
                timeout=45.0,
            )

            return {
                "webenv": search_results.get("WebEnv", ""),
                "query_key": search_results.get("QueryKey", ""),
                "count": int(search_results.get("Count", 0)),
                "batch_size": batch_size,
            }
        except Exception as exc:
            raise_ncbi_infrastructure_error("history_search", exc)

    async def fetch_batch_from_history(
        self, webenv: str, query_key: str, start: int, batch_size: int
    ) -> list[dict[str, Any]]:
        """
        Fetch a batch of results using History Server credentials.

        Args:
            webenv: WebEnv from search_with_history.
            query_key: QueryKey from search_with_history.
            start: Starting index (0-based).
            batch_size: Number of results to fetch.

        Returns:
            List of article details for this batch.

        Example:
            >>> history = await searcher.search_with_history("cancer therapy")
            >>> total = history['count']
            >>> batch_size = history['batch_size']
            >>> for start in range(0, total, batch_size):
            ...     batch = await searcher.fetch_batch_from_history(
            ...         history['webenv'], history['query_key'],
            ...         start, batch_size
            ...     )
            ...     process_batch(batch)
        """
        try:
            api_key = getattr(self, "_api_key", None)
            email = getattr(self, "_email", None)
            tool = getattr(self, "_tool", DEFAULT_ENTREZ_TOOL)

            async def do_fetch() -> Any:
                handle = await asyncio.to_thread(
                    run_entrez_callable,
                    Entrez,
                    Entrez.efetch,
                    db="pubmed",
                    retstart=start,
                    retmax=batch_size,
                    webenv=webenv,
                    query_key=query_key,
                    retmode="xml",
                    email=email,
                    api_key=api_key,
                    tool=tool,
                )
                try:
                    return await asyncio.to_thread(Entrez.read, handle)
                finally:
                    handle.close()

            papers = await execute_entrez_operation(
                do_fetch,
                api_key=api_key,
                service_name="ncbi-batch:efetch",
                timeout=60.0,
            )

            results = []
            if "PubmedArticle" in papers:
                for article in papers["PubmedArticle"]:
                    medline_citation = article["MedlineCitation"]
                    article_data = medline_citation["Article"]

                    title = article_data.get("ArticleTitle", "No title")
                    pmid = str(medline_citation.get("PMID", ""))

                    # Extract basic info
                    authors = []
                    if "AuthorList" in article_data:
                        for author in article_data["AuthorList"]:
                            if "LastName" in author:
                                authors.append(f"{author['LastName']} {author.get('ForeName', '')}".strip())

                    journal = article_data.get("Journal", {}).get("Title", "Unknown")
                    year = article_data.get("Journal", {}).get("JournalIssue", {}).get("PubDate", {}).get("Year", "")

                    results.append(
                        {
                            "pmid": pmid,
                            "title": title,
                            "authors": authors,
                            "journal": journal,
                            "year": year,
                        }
                    )

            return results
        except Exception as exc:
            raise_ncbi_infrastructure_error("history_fetch", exc)

    async def esearch_snapshot(
        self,
        query: str,
        *,
        retmax: int,
        min_year: int | None = None,
        max_year: int | None = None,
        age_group: str | None = None,
        sex: str | None = None,
        species: str | None = None,
        language: str | None = None,
        clinical_query: str | None = None,
        use_history: bool = True,
    ) -> dict[str, Any]:
        """Run one ESearch and return its count, first PMID page and PubMed translation.

        ``retmax=0`` performs a count-only search. With ``use_history`` the
        result set is stored on the NCBI History Server so later pages can be
        read with :meth:`fetch_history_pmids` from the same snapshot. Filters
        are compiled exactly as for ``search_page`` so the physical query is
        reproducible.
        """
        if isinstance(retmax, bool) or not isinstance(retmax, int) or not 0 <= retmax <= MAX_ESEARCH_RETRIEVAL:
            raise ValueError(f"retmax must be an integer between 0 and {MAX_ESEARCH_RETRIEVAL}")
        full_query, _sort = cast("Any", self)._compile_search_request(
            query=query,
            limit=max(retmax, 1),
            min_year=min_year,
            max_year=max_year,
            article_type=None,
            strategy="relevance",
            age_group=age_group,
            sex=sex,
            species=species,
            language=language,
            clinical_query=clinical_query,
            detail_level="summary",
        )
        api_key = getattr(self, "_api_key", None)
        email = getattr(self, "_email", None)
        tool = getattr(self, "_tool", DEFAULT_ENTREZ_TOOL)

        async def do_search() -> Any:
            handle = await asyncio.to_thread(
                run_entrez_callable,
                Entrez,
                Entrez.esearch,
                db="pubmed",
                term=full_query,
                retstart=0,
                retmax=retmax,
                usehistory="y" if use_history else "n",
                email=email,
                api_key=api_key,
                tool=tool,
            )
            try:
                return await asyncio.to_thread(Entrez.read, handle)
            finally:
                handle.close()

        try:
            record = await execute_entrez_operation(
                do_search,
                api_key=api_key,
                service_name="ncbi-batch:esearch-history",
                timeout=45.0,
                max_attempts=_HISTORY_MAX_ATTEMPTS,
                base_delay=_HISTORY_RETRY_DELAY,
            )
            snapshot = _parse_esearch_snapshot(record, use_history=use_history)
        except Exception as exc:
            raise_ncbi_infrastructure_error(
                "history_search",
                exc,
                execution_metadata={"physical_query": full_query, "query_executed": True},
            )
        return {
            **snapshot,
            "logical_query": query,
            "physical_query": full_query,
            "retmax": retmax,
            "use_history": use_history,
        }

    async def fetch_history_pmids(
        self,
        webenv: str,
        query_key: str,
        *,
        retstart: int,
        retmax: int,
    ) -> list[str]:
        """Read one page of PMIDs from a stored History Server result set.

        Uses EFetch ``rettype=uilist`` so every page comes from the exact
        snapshot created by :meth:`esearch_snapshot`, rather than re-running
        a query that PubMed may have updated in the meantime.
        """
        if not isinstance(webenv, str) or not webenv.strip() or not isinstance(query_key, str) or not query_key:
            raise ValueError("webenv and query_key are required")
        if isinstance(retstart, bool) or not isinstance(retstart, int) or not 0 <= retstart < MAX_ESEARCH_RETRIEVAL:
            raise ValueError(f"retstart must be an integer between 0 and {MAX_ESEARCH_RETRIEVAL - 1}")
        if isinstance(retmax, bool) or not isinstance(retmax, int) or not 1 <= retmax <= MAX_ESEARCH_RETRIEVAL:
            raise ValueError(f"retmax must be an integer between 1 and {MAX_ESEARCH_RETRIEVAL}")
        api_key = getattr(self, "_api_key", None)
        email = getattr(self, "_email", None)
        tool = getattr(self, "_tool", DEFAULT_ENTREZ_TOOL)

        async def do_fetch() -> Any:
            handle = await asyncio.to_thread(
                run_entrez_callable,
                Entrez,
                Entrez.efetch,
                db="pubmed",
                webenv=webenv,
                query_key=query_key,
                retstart=retstart,
                retmax=retmax,
                rettype="uilist",
                retmode="text",
                email=email,
                api_key=api_key,
                tool=tool,
            )
            try:
                return await asyncio.to_thread(handle.read)
            finally:
                handle.close()

        try:
            payload = await execute_entrez_operation(
                do_fetch,
                api_key=api_key,
                service_name="ncbi-batch:efetch-uilist",
                timeout=60.0,
                max_attempts=_HISTORY_MAX_ATTEMPTS,
                base_delay=_HISTORY_RETRY_DELAY,
            )
            pmids = _parse_uilist(payload)
        except Exception as exc:
            raise_ncbi_infrastructure_error("history_pmids", exc)
        if len(pmids) > retmax:
            raise NCBIProviderSchemaError("history_pmids")
        return pmids
