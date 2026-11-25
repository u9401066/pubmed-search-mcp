"""NCBI adapter for MeSH correction evidence.

Implements the ``MeshCorrectionGateway`` port used by the application-layer
``MeshCorrectionService``:

- ``probe``: count-only PubMed ESearch (``retmax=0``) plus its diagnostics;
- ``lookup_exact``: exact preferred/entry-term MeSH lookup, delegated to the
  cached ``SearchStrategyGenerator.lookup_mesh_records``;
- ``sample``: one PubMed ESearch returning the evidence total and a bounded
  list of PMIDs;
- ``fetch_mesh_headings``: MEDLINE-format EFetch (``rettype=medline``) of the
  sampled PMIDs, batched, returning each record's ``MH`` values;
- ``count``: a count-only PubMed ESearch, used for descriptor background
  (``"X"[mh:noexp]``) and joint (evidence AND descriptor) counts.

Every method issues at most the requests its docstring states and caches
public-vocabulary results (samples 6 h; per-PMID headings and descriptor
counts 24 h, joint counts 6 h). All calls share the NCBI transport kernel's rate limit, retry
and circuit-breaker policy.
"""

from __future__ import annotations

import asyncio
import io
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol

from Bio import Entrez, Medline
from cachetools import TTLCache

from pubmed_search.domain.services.mesh_correction import EvidenceSample
from pubmed_search.domain.value_objects.query_diagnostics import QueryProbe

from .base import (
    DEFAULT_ENTREZ_TOOL,
    execute_entrez_operation,
    raise_ncbi_infrastructure_error,
    run_entrez_callable,
)
from .diagnostics import parse_esearch_diagnostics

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from pubmed_search.domain.services.mesh_phrase_matching import MeshRecord

SAMPLE_CACHE_TTL = 6 * 60 * 60
VOCABULARY_CACHE_TTL = 24 * 60 * 60
MAX_ATTEMPTS = 2
PROBE_TIMEOUT = 20.0
FETCH_TIMEOUT = 60.0


class MeshVocabulary(Protocol):
    """Exact-term MeSH lookup (implemented by ``SearchStrategyGenerator``)."""

    async def lookup_mesh_records(self, phrases: Iterable[str]) -> dict[str, tuple[MeshRecord, ...]]: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validated_pmids(raw: Any, *, limit: int) -> list[str]:
    if not isinstance(raw, list) or len(raw) > limit:
        raise TypeError("Invalid PubMed ID list")
    pmids = [str(pmid) for pmid in raw]
    if any(not pmid.isascii() or not pmid.isdecimal() for pmid in pmids) or len(set(pmids)) != len(pmids):
        raise ValueError("Invalid PubMed identifiers")
    return pmids


def _count(record: Any) -> int:
    count = int(str(record["Count"]))
    if count < 0:
        raise ValueError("Invalid PubMed count")
    return count


def parse_medline_headings(text: str, expected: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """``MH`` values per PMID from MEDLINE text; PMIDs outside ``expected`` are a schema error."""
    allowed = set(expected)
    headings: dict[str, tuple[str, ...]] = {}
    for record in Medline.parse(io.StringIO(text)):
        pmid = str(record.get("PMID", "")).strip()
        if pmid not in allowed:
            raise ValueError("MEDLINE record outside the requested PMIDs")
        values = record.get("MH", [])
        if isinstance(values, str):
            values = [values]
        headings[pmid] = tuple(str(value).strip() for value in values if str(value).strip())
    return headings


class NCBIMeshEvidenceGateway:
    """Entrez-backed evidence for ``MeshCorrectionService`` with bounded, cached requests."""

    def __init__(
        self,
        email: str,
        api_key: str | None = None,
        *,
        vocabulary: MeshVocabulary | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if vocabulary is None:
            from .strategy import SearchStrategyGenerator

            vocabulary = SearchStrategyGenerator(email=email, api_key=api_key)
        self._email = email
        self._api_key = api_key
        self._tool = DEFAULT_ENTREZ_TOOL
        self._vocabulary = vocabulary
        self._clock = clock
        self._samples: TTLCache[tuple[str, int, str], EvidenceSample] = TTLCache(maxsize=256, ttl=SAMPLE_CACHE_TTL)
        self._headings: TTLCache[str, tuple[str, ...]] = TTLCache(maxsize=16_384, ttl=VOCABULARY_CACHE_TTL)
        self._counts: TTLCache[str, int] = TTLCache(maxsize=4_096, ttl=SAMPLE_CACHE_TTL)

    async def _call(self, operation: Callable[[], Any], *, service_name: str, timeout: float) -> Any:
        return await execute_entrez_operation(
            operation,
            api_key=self._api_key,
            service_name=service_name,
            timeout=timeout,
            max_attempts=MAX_ATTEMPTS,
        )

    async def _esearch(self, term: str, *, retmax: int, sort: str | None, service_name: str) -> Any:
        kwargs: dict[str, Any] = {"db": "pubmed", "term": term, "retmax": retmax, "usehistory": "n"}
        if sort is not None:
            kwargs["sort"] = sort

        async def _do_search() -> Any:
            handle = await asyncio.to_thread(
                run_entrez_callable,
                Entrez,
                Entrez.esearch,
                email=self._email,
                api_key=self._api_key,
                tool=self._tool,
                **kwargs,
            )
            try:
                return await asyncio.to_thread(Entrez.read, handle)
            finally:
                handle.close()

        return await self._call(_do_search, service_name=service_name, timeout=PROBE_TIMEOUT)

    async def probe(self, query: str) -> QueryProbe:
        """Count and diagnostics for ``query``. One ESearch, never cached."""
        try:
            record = await self._esearch(query, retmax=0, sort=None, service_name="ncbi-mesh-correction:probe")
            return QueryProbe(query=query, count=_count(record), diagnostics=parse_esearch_diagnostics(record))
        except Exception as exc:
            raise_ncbi_infrastructure_error("mesh_correction_probe", exc)

    async def lookup_exact(self, phrases: Sequence[str]) -> Mapping[str, tuple[MeshRecord, ...]]:
        """Exact MeSH records by ``term_key``. At most two requests (batched ESearch + ESummary), cached."""
        return await self._vocabulary.lookup_mesh_records(phrases)

    async def sample(self, query: str, *, limit: int, sort: str) -> EvidenceSample:
        """Evidence total and up to ``limit`` PMIDs. One ESearch; cached for 6 hours."""
        key = (query, limit, sort)
        cached = self._samples.get(key)
        if cached is not None:
            return cached
        try:
            record = await self._esearch(query, retmax=limit, sort=sort, service_name="ncbi-mesh-correction:sample")
            total = _count(record)
            pmids = _validated_pmids(record["IdList"], limit=min(limit, total))
            sample = EvidenceSample(
                query=query,
                total=total,
                pmids=tuple(pmids),
                sort=sort,
                retrieved_at=self._clock().isoformat(timespec="seconds"),
                diagnostics=parse_esearch_diagnostics(record),
            )
        except Exception as exc:
            raise_ncbi_infrastructure_error("mesh_correction_sample", exc)
        self._samples[key] = sample
        return sample

    async def fetch_mesh_headings(self, pmids: Sequence[str], *, batch_size: int) -> dict[str, tuple[str, ...]]:
        """MEDLINE ``MH`` values per PMID. One EFetch per ``batch_size`` uncached PMIDs; cached 24 hours.

        PMIDs that MEDLINE returns without headings map to an empty tuple.
        """
        missing = [pmid for pmid in dict.fromkeys(pmids) if pmid not in self._headings]
        for offset in range(0, len(missing), batch_size):
            batch = missing[offset : offset + batch_size]
            try:
                fetched = parse_medline_headings(await self._efetch_medline(batch), batch)
            except Exception as exc:
                raise_ncbi_infrastructure_error("mesh_correction_headings", exc)
            for pmid in batch:
                self._headings[pmid] = fetched.get(pmid, ())
        return {pmid: self._headings.get(pmid, ()) for pmid in pmids}

    async def _efetch_medline(self, pmids: list[str]) -> str:
        async def _do_fetch() -> str:
            handle = await asyncio.to_thread(
                run_entrez_callable,
                Entrez,
                Entrez.efetch,
                db="pubmed",
                id=",".join(pmids),
                rettype="medline",
                retmode="text",
                email=self._email,
                api_key=self._api_key,
                tool=self._tool,
            )
            try:
                return str(await asyncio.to_thread(handle.read))
            finally:
                handle.close()

        result: str = await self._call(_do_fetch, service_name="ncbi-mesh-correction:efetch", timeout=FETCH_TIMEOUT)
        return result

    async def count(self, query: str) -> int:
        """PubMed count of ``query``. One ESearch; cached for 6 hours."""
        cached = self._counts.get(query)
        if cached is not None:
            return cached
        try:
            record = await self._esearch(query, retmax=0, sort=None, service_name="ncbi-mesh-correction:count")
            value = _count(record)
        except Exception as exc:
            raise_ncbi_infrastructure_error("mesh_correction_count", exc)
        self._counts[query] = value
        return value


__all__ = ["MeshVocabulary", "NCBIMeshEvidenceGateway", "parse_medline_headings"]
