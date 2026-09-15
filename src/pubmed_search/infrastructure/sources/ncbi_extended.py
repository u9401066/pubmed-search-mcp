"""
NCBI Extended API Integration

Provides access to additional NCBI Entrez databases beyond PubMed:
- Gene: Gene records with functions, pathways, interactions
- PubChem: Chemical compound information
- ClinVar: Clinical variant records

All use the same Entrez E-utilities infrastructure.
API Documentation: https://www.ncbi.nlm.nih.gov/books/NBK25497/
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

from pubmed_search.infrastructure.provider_payload import is_provider_error_envelope
from pubmed_search.infrastructure.sources.base_client import (
    APIRequestError,
    BaseAPIClient,
    raise_provider_schema_error,
)
from pubmed_search.shared.async_utils import RetryableOperationError

logger = logging.getLogger(__name__)

# NCBI Entrez base URL
ENTREZ_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Default values
DEFAULT_EMAIL = "pubmed-search-mcp@example.com"


def _require_payload(payload: object) -> dict[str, Any]:
    """Require one error-free NCBI JSON object."""
    if not isinstance(payload, dict) or is_provider_error_envelope(payload):
        raise_provider_schema_error("NCBI")
    return payload


def _normalize_provider_ids(value: object) -> list[str]:
    """Validate and normalize one NCBI identifier array."""
    if not isinstance(value, list):
        raise_provider_schema_error("NCBI")

    normalized: list[str] = []
    for raw_id in value:
        if isinstance(raw_id, bool) or not isinstance(raw_id, (str, int)):
            raise_provider_schema_error("NCBI")
        identifier = str(raw_id)
        if not identifier.isascii() or not identifier.isdigit() or int(identifier) <= 0:
            raise_provider_schema_error("NCBI")
        normalized.append(identifier)
    if len(normalized) != len(set(normalized)):
        raise_provider_schema_error("NCBI")
    return normalized


def _require_esearch_ids(payload: object) -> list[str]:
    """Return IDs from a structurally valid ESearch response."""
    root = _require_payload(payload)
    envelope = root.get("esearchresult")
    if not isinstance(envelope, dict) or is_provider_error_envelope(envelope) or "idlist" not in envelope:
        raise_provider_schema_error("NCBI")
    return _normalize_provider_ids(envelope["idlist"])


def _require_summary_result(payload: object) -> tuple[dict[str, Any], list[str]]:
    """Return the ESummary result map and its explicit UID coverage."""
    root = _require_payload(payload)
    result = root.get("result")
    if not isinstance(result, dict) or is_provider_error_envelope(result) or "uids" not in result:
        raise_provider_schema_error("NCBI")
    return result, _normalize_provider_ids(result["uids"])


def _require_summary_rows(payload: object, requested_ids: list[str]) -> list[dict[str, Any]]:
    """Require one valid ESummary row for every ID returned by ESearch."""
    result, returned_ids = _require_summary_result(payload)
    if len(returned_ids) != len(requested_ids) or set(returned_ids) != set(requested_ids):
        raise_provider_schema_error("NCBI")

    rows: list[dict[str, Any]] = []
    for identifier in requested_ids:
        row = result.get(identifier)
        if not isinstance(row, dict) or is_provider_error_envelope(row) or str(row.get("uid", "")) != identifier:
            raise_provider_schema_error("NCBI")
        rows.append(row)
    return rows


def _require_summary_item(payload: object, requested_id: str) -> dict[str, Any] | None:
    """Return a direct ESummary record, preserving only explicit not-found."""
    result, returned_ids = _require_summary_result(payload)
    if not returned_ids:
        if set(result) != {"uids"}:
            raise_provider_schema_error("NCBI")
        return None
    if returned_ids != [requested_id]:
        raise_provider_schema_error("NCBI")
    row = result.get(requested_id)
    if not isinstance(row, dict) or str(row.get("uid", "")) != requested_id:
        raise_provider_schema_error("NCBI")
    if is_provider_error_envelope(row):
        error = row.get("error", row.get("ERROR"))
        if isinstance(error, str) and error.strip().casefold() == "cannot get document summary":
            return None
        raise_provider_schema_error("NCBI")
    return row


def _require_pubmed_links(payload: object, *, requested_id: str, source_db: str) -> list[str]:
    """Parse a structurally valid ELink response into PubMed IDs."""
    root = _require_payload(payload)
    linksets = root.get("linksets")
    if not isinstance(linksets, list):
        raise_provider_schema_error("NCBI")

    pmids: list[str] = []
    for linkset in linksets:
        if not isinstance(linkset, dict) or is_provider_error_envelope(linkset):
            raise_provider_schema_error("NCBI")
        if linkset.get("dbfrom") != source_db or _normalize_provider_ids(linkset.get("ids")) != [requested_id]:
            raise_provider_schema_error("NCBI")
        if "linksetdbs" not in linkset:
            continue
        linksetdbs = linkset["linksetdbs"]
        if not isinstance(linksetdbs, list):
            raise_provider_schema_error("NCBI")
        for linksetdb in linksetdbs:
            if not isinstance(linksetdb, dict) or is_provider_error_envelope(linksetdb):
                raise_provider_schema_error("NCBI")
            if linksetdb.get("dbto") != "pubmed":
                continue
            if "links" not in linksetdb:
                raise_provider_schema_error("NCBI")
            pmids.extend(_normalize_provider_ids(linksetdb["links"]))
    return pmids


class NCBIExtendedClient(BaseAPIClient):
    """
    Client for extended NCBI Entrez databases.

    Provides access to Gene, PubChem, ClinVar, and other NCBI databases
    using the standard E-utilities API.

    Usage:
        client = NCBIExtendedClient(email="your@email.com")

        # Search genes
        genes = client.search_gene("BRCA1", limit=5)

        # Get compound info
        compound = client.get_compound_by_name("aspirin")

        # Search clinical variants
        variants = client.search_clinvar("BRCA1", limit=10)
    """

    _service_name = "NCBI"

    def __init__(
        self,
        email: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ):
        """
        Initialize NCBI extended client.

        Args:
            email: Contact email (required by NCBI policy)
            api_key: NCBI API key for higher rate limits
            timeout: Request timeout
        """
        self._email = email or DEFAULT_EMAIL
        self._api_key = api_key
        super().__init__(
            timeout=timeout,
            min_interval=0.34 if not api_key else 0.1,
            headers={
                "User-Agent": f"pubmed-search-mcp/1.0 (mailto:{self._email})",
                "Accept": "application/json",
            },
        )

    async def _execute_request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Add required NCBI parameters (email, tool, api_key) to URL."""
        separator = "&" if "?" in url else "?"
        url += f"{separator}email={urllib.parse.quote(self._email)}&tool=pubmed-search-mcp"
        if self._api_key:
            url += "&" + urllib.parse.urlencode({"api_key": self._api_key})
        return await super()._execute_request(url, method=method, data=data, params=params, headers=headers)

    # =========================================================================
    # Gene Database
    # =========================================================================

    async def search_gene(
        self,
        query: str,
        organism: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Search NCBI Gene database.

        Args:
            query: Gene name, symbol, or description
            organism: Filter by organism (e.g., "human", "Homo sapiens")
            limit: Maximum results

        Returns:
            List of gene records
        """
        try:
            # Build query
            search_query = query
            if organism:
                search_query = f"({query}) AND ({organism})[Organism]"

            # Search
            search_url = (
                f"{ENTREZ_BASE}/esearch.fcgi?db=gene"
                f"&term={urllib.parse.quote(search_query)}"
                f"&retmax={limit}&retmode=json"
            )

            search_result = await self._make_request(search_url, expect_json=True)
            ids = _require_esearch_ids(search_result)
            if not ids:
                return []

            # Fetch summaries
            ids_str = ",".join(ids)
            summary_url = f"{ENTREZ_BASE}/esummary.fcgi?db=gene&id={ids_str}&retmode=json"

            summary_result = await self._make_request(summary_url, expect_json=True)
            rows = _require_summary_rows(summary_result, ids)
            return [self._normalize_gene(row) for row in rows]

        except (APIRequestError, RetryableOperationError):
            raise
        except Exception as exc:
            logger.warning("Gene search failed (%s)", type(exc).__name__)
            raise APIRequestError("NCBI") from None

    async def get_gene(self, gene_id: str | int) -> dict | None:
        """
        Get gene details by NCBI Gene ID.

        Args:
            gene_id: NCBI Gene ID

        Returns:
            Gene record or None
        """
        try:
            gene_id = _normalize_provider_ids([gene_id])[0]
            url = f"{ENTREZ_BASE}/esummary.fcgi?db=gene&id={gene_id}&retmode=json"
            result = await self._make_request(url, expect_json=True)
            gene_data = _require_summary_item(result, str(gene_id))
            return self._normalize_gene(gene_data) if gene_data is not None else None

        except (APIRequestError, RetryableOperationError):
            raise
        except Exception as exc:
            logger.warning("Get gene failed (%s)", type(exc).__name__)
            raise APIRequestError("NCBI") from None

    async def get_gene_pubmed_links(self, gene_id: str | int, limit: int = 20) -> list[str]:
        """
        Get PubMed IDs linked to a gene.

        Args:
            gene_id: NCBI Gene ID
            limit: Maximum PubMed IDs to return

        Returns:
            List of PubMed IDs
        """
        try:
            gene_id = _normalize_provider_ids([gene_id])[0]
            url = f"{ENTREZ_BASE}/elink.fcgi?dbfrom=gene&db=pubmed&id={gene_id}&retmode=json"
            result = await self._make_request(url, expect_json=True)
            return _require_pubmed_links(result, requested_id=str(gene_id), source_db="gene")[:limit]

        except (APIRequestError, RetryableOperationError):
            raise
        except Exception as exc:
            logger.warning("Get gene PubMed links failed (%s)", type(exc).__name__)
            raise APIRequestError("NCBI") from None

    def _normalize_gene(self, gene: dict) -> dict:
        """Normalize gene data to common format."""
        return {
            "gene_id": gene.get("uid"),
            "symbol": gene.get("name", ""),
            "name": gene.get("description", ""),
            "organism": (gene.get("organism") or {}).get("scientificname", ""),
            "tax_id": (gene.get("organism") or {}).get("taxid"),
            "chromosome": gene.get("chromosome", ""),
            "map_location": gene.get("maplocation", ""),
            "aliases": gene.get("otheraliases", "").split(", ") if gene.get("otheraliases") else [],
            "summary": gene.get("summary", ""),
            "gene_type": gene.get("geneticsource", ""),
            "_source": "ncbi_gene",
        }

    # =========================================================================
    # PubChem Database
    # =========================================================================

    async def search_compound(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """
        Search PubChem for chemical compounds.

        Args:
            query: Compound name or description
            limit: Maximum results

        Returns:
            List of compound records
        """
        try:
            # Search PubChem Compound
            search_url = (
                f"{ENTREZ_BASE}/esearch.fcgi?db=pccompound&term={urllib.parse.quote(query)}&retmax={limit}&retmode=json"
            )

            search_result = await self._make_request(search_url, expect_json=True)
            ids = _require_esearch_ids(search_result)
            if not ids:
                return []

            # Fetch summaries
            ids_str = ",".join(ids)
            summary_url = f"{ENTREZ_BASE}/esummary.fcgi?db=pccompound&id={ids_str}&retmode=json"

            summary_result = await self._make_request(summary_url, expect_json=True)
            rows = _require_summary_rows(summary_result, ids)
            return [self._normalize_compound(row) for row in rows]

        except (APIRequestError, RetryableOperationError):
            raise
        except Exception as exc:
            logger.warning("Compound search failed (%s)", type(exc).__name__)
            raise APIRequestError("NCBI") from None

    async def get_compound(self, cid: str | int) -> dict | None:
        """
        Get compound details by PubChem CID.

        Args:
            cid: PubChem Compound ID

        Returns:
            Compound record or None
        """
        try:
            cid = _normalize_provider_ids([cid])[0]
            url = f"{ENTREZ_BASE}/esummary.fcgi?db=pccompound&id={cid}&retmode=json"
            result = await self._make_request(url, expect_json=True)
            compound_data = _require_summary_item(result, str(cid))
            return self._normalize_compound(compound_data) if compound_data is not None else None

        except (APIRequestError, RetryableOperationError):
            raise
        except Exception as exc:
            logger.warning("Get compound failed (%s)", type(exc).__name__)
            raise APIRequestError("NCBI") from None

    async def get_compound_pubmed_links(self, cid: str | int, limit: int = 20) -> list[str]:
        """
        Get PubMed IDs linked to a compound.

        Args:
            cid: PubChem Compound ID
            limit: Maximum PubMed IDs to return

        Returns:
            List of PubMed IDs
        """
        try:
            cid = _normalize_provider_ids([cid])[0]
            url = f"{ENTREZ_BASE}/elink.fcgi?dbfrom=pccompound&db=pubmed&id={cid}&retmode=json"
            result = await self._make_request(url, expect_json=True)
            return _require_pubmed_links(result, requested_id=str(cid), source_db="pccompound")[:limit]

        except (APIRequestError, RetryableOperationError):
            raise
        except Exception as exc:
            logger.warning("Get compound PubMed links failed (%s)", type(exc).__name__)
            raise APIRequestError("NCBI") from None

    def _normalize_compound(self, compound: dict) -> dict:
        """Normalize compound data to common format."""
        # Get synonyms
        synonyms = compound.get("synonymlist") or []
        if isinstance(synonyms, str):
            synonyms = [synonyms]

        return {
            "cid": compound.get("uid") or compound.get("cid"),
            "name": synonyms[0] if synonyms else "",
            "iupac_name": compound.get("iupacname", ""),
            "molecular_formula": compound.get("molecularformula", ""),
            "molecular_weight": compound.get("molecularweight"),
            "canonical_smiles": compound.get("canonicalsmiles", ""),
            "isomeric_smiles": compound.get("isomericsmiles", ""),
            "inchi": compound.get("inchi", ""),
            "inchikey": compound.get("inchikey", ""),
            "synonyms": synonyms[:10],  # Limit synonyms
            "charge": compound.get("charge"),
            "heavy_atom_count": compound.get("heavyatomcount"),
            "rotatable_bond_count": compound.get("rotatablebondcount"),
            "hydrogen_bond_donor_count": compound.get("hydrogenbonddonorcount"),
            "hydrogen_bond_acceptor_count": compound.get("hydrogenbondacceptorcount"),
            "_source": "pubchem",
        }

    # =========================================================================
    # ClinVar Database
    # =========================================================================

    async def search_clinvar(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """
        Search ClinVar for clinical variants.

        Args:
            query: Gene name, variant, or condition
            limit: Maximum results

        Returns:
            List of variant records
        """
        try:
            # Search ClinVar
            search_url = (
                f"{ENTREZ_BASE}/esearch.fcgi?db=clinvar&term={urllib.parse.quote(query)}&retmax={limit}&retmode=json"
            )

            search_result = await self._make_request(search_url, expect_json=True)
            ids = _require_esearch_ids(search_result)
            if not ids:
                return []

            # Fetch summaries
            ids_str = ",".join(ids)
            summary_url = f"{ENTREZ_BASE}/esummary.fcgi?db=clinvar&id={ids_str}&retmode=json"

            summary_result = await self._make_request(summary_url, expect_json=True)
            rows = _require_summary_rows(summary_result, ids)
            return [self._normalize_clinvar(row) for row in rows]

        except (APIRequestError, RetryableOperationError):
            raise
        except Exception as exc:
            logger.warning("ClinVar search failed (%s)", type(exc).__name__)
            raise APIRequestError("NCBI") from None

    def _normalize_clinvar(self, variant: dict) -> dict:
        """Normalize ClinVar data to common format."""
        # Get clinical significance
        clinical_sig = variant.get("clinical_significance", {})
        significance = clinical_sig.get("description", "") if isinstance(clinical_sig, dict) else str(clinical_sig)

        # Get genes
        genes = variant.get("genes") or []
        gene_symbols = []
        for gene in genes:
            if isinstance(gene, dict):
                gene_symbols.append(gene.get("symbol", ""))

        return {
            "clinvar_id": variant.get("uid"),
            "accession": variant.get("accession"),
            "title": variant.get("title", ""),
            "gene_symbols": gene_symbols,
            "clinical_significance": significance,
            "review_status": variant.get("review_status", ""),
            "variation_type": variant.get("obj_type", ""),
            "chromosome": variant.get("chr", ""),
            "start": variant.get("start"),
            "stop": variant.get("stop"),
            "conditions": [c.get("trait_name", "") for c in (variant.get("trait_set") or []) if isinstance(c, dict)],
            "_source": "clinvar",
        }
