"""
NCBI Extended Database MCP Tools

Provides MCP tools for accessing additional NCBI databases beyond PubMed:
- Gene: Gene records with functions, pathways, interactions
- PubChem: Chemical compound information
- ClinVar: Clinical variant records

These tools complement PubMed search for comprehensive biomedical research.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from pubmed_search.domain.value_objects import (
    NcbiIdentifierValidationError,
    normalize_ncbi_identifier,
)

from ._common import InputNormalizer, ResponseFormatter

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

logger = logging.getLogger(__name__)

NcbiQuery = Annotated[str, Field(min_length=1, max_length=500)]
OrganismFilter = Annotated[str, Field(min_length=1, max_length=200)]
NcbiIdentifier = Annotated[str, Field(min_length=1, max_length=20, pattern=r"^[1-9][0-9]{0,19}$")]
SearchLimit = Annotated[int, Field(ge=1, le=50)]
LiteratureLimit = Annotated[int, Field(ge=1, le=100)]


def _bounded_query(value: str, *, label: str, max_chars: int = 500) -> str:
    normalized = InputNormalizer.normalize_query(value)
    if not normalized:
        raise ValueError(f"{label} is empty")
    if len(normalized) > max_chars:
        raise ValueError(f"{label} exceeds {max_chars} characters")
    return normalized


def register_ncbi_extended_tools(mcp: MCPServer) -> None:
    """Register NCBI Extended database tools with MCP server."""

    # =========================================================================
    # Gene Database Tools
    # =========================================================================

    @mcp.tool()
    async def search_gene(
        query: NcbiQuery,
        organism: OrganismFilter | None = None,
        limit: SearchLimit = 10,
    ) -> str:
        """
        Search NCBI Gene database for gene information.

        ═══════════════════════════════════════════════════════════════
        USE CASES:
        ═══════════════════════════════════════════════════════════════
        - Look up gene function and description
        - Find gene aliases and official symbols
        - Get chromosome location
        - Find genes by name or function

        Args:
            query: Gene name, symbol, or function keyword
            organism: Filter by organism (e.g., "human", "Homo sapiens", "mouse")
            limit: Maximum results (1-50)

        Returns:
            JSON with gene records including symbols, names, locations
        """
        # Normalize inputs
        try:
            query = _bounded_query(query, label="Gene query")
            if organism is not None:
                organism = _bounded_query(organism, label="Organism filter", max_chars=200)
        except ValueError as exc:
            return ResponseFormatter.error(
                exc,
                suggestion="Provide a gene name or symbol",
                example='search_gene(query="BRCA1", organism="human")',
                tool_name="search_gene",
            )

        try:
            from pubmed_search.infrastructure.sources import get_ncbi_extended_client

            client = get_ncbi_extended_client()
            results = await client.search_gene(
                query=query,
                organism=organism,
                limit=limit,
            )

            if not results:
                return ResponseFormatter.no_results(
                    query=f"{query}" + (f" (organism: {organism})" if organism else ""),
                    suggestions=[
                        "Try the official gene symbol (e.g., TP53 instead of p53)",
                        "Remove organism filter for broader search",
                        "Check gene name spelling",
                    ],
                )

            return json.dumps(
                {
                    "status": "success",
                    "source": "ncbi_gene",
                    "count": len(results),
                    "genes": results,
                },
                indent=2,
                ensure_ascii=False,
            )

        except Exception as exc:
            logger.warning("Gene search failed (%s)", type(exc).__name__)
            return ResponseFormatter.error("NCBI Gene search could not be completed", tool_name="search_gene")

    @mcp.tool()
    async def get_gene_details(gene_id: NcbiIdentifier) -> str:
        """
        Get detailed information about a gene by NCBI Gene ID.

        Args:
            gene_id: NCBI Gene ID (from search results or known)

        Returns:
            JSON with gene details including symbol, name, summary, location
        """
        # Normalize input
        try:
            normalized_gene_id = normalize_ncbi_identifier(gene_id, label="Gene ID")
        except NcbiIdentifierValidationError as exc:
            return ResponseFormatter.error(
                exc,
                suggestion="Provide an NCBI Gene ID",
                example='get_gene_details(gene_id="672")',
                tool_name="get_gene_details",
            )

        try:
            from pubmed_search.infrastructure.sources import get_ncbi_extended_client

            client = get_ncbi_extended_client()
            result = await client.get_gene(normalized_gene_id)

            if result:
                return json.dumps(
                    {"status": "success", "source": "ncbi_gene", "gene": result},
                    indent=2,
                    ensure_ascii=False,
                )
            return ResponseFormatter.no_results(
                suggestions=[
                    f"Gene ID '{normalized_gene_id}' not found",
                    "Use search_gene to find valid Gene IDs",
                ]
            )

        except Exception as exc:
            logger.warning("Gene detail lookup failed (%s)", type(exc).__name__)
            return ResponseFormatter.error("NCBI Gene details could not be retrieved", tool_name="get_gene_details")

    @mcp.tool()
    async def get_gene_literature(
        gene_id: NcbiIdentifier,
        limit: LiteratureLimit = 20,
    ) -> str:
        """
        Get PubMed articles linked to a gene.

        This uses NCBI's curated gene-to-publication links, which are
        more precise than keyword searches.

        Args:
            gene_id: NCBI Gene ID
            limit: Maximum PubMed IDs to return (1-100)

        Returns:
            JSON with linked PubMed IDs
        """
        # Normalize inputs
        try:
            normalized_gene_id = normalize_ncbi_identifier(gene_id, label="Gene ID")
        except NcbiIdentifierValidationError as exc:
            return ResponseFormatter.error(
                exc,
                suggestion="Provide an NCBI Gene ID",
                example='get_gene_literature(gene_id="672", limit=20)',
                tool_name="get_gene_literature",
            )

        try:
            from pubmed_search.infrastructure.sources import get_ncbi_extended_client

            client = get_ncbi_extended_client()
            pmids = await client.get_gene_pubmed_links(normalized_gene_id, limit=limit)

            if not pmids:
                return ResponseFormatter.no_results(
                    suggestions=[
                        f"No linked publications found for Gene ID '{normalized_gene_id}'",
                        "Try unified_search with the gene name instead",
                    ]
                )

            return json.dumps(
                {
                    "status": "success",
                    "source": "ncbi_gene",
                    "gene_id": normalized_gene_id,
                    "pubmed_count": len(pmids),
                    "pmids": pmids,
                    "note": "Use fetch_article_details with these PMIDs to get article info",
                },
                indent=2,
            )

        except Exception as exc:
            logger.warning("Gene literature lookup failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                "NCBI Gene literature could not be retrieved",
                tool_name="get_gene_literature",
            )

    # =========================================================================
    # PubChem Database Tools
    # =========================================================================

    @mcp.tool()
    async def search_compound(
        query: NcbiQuery,
        limit: SearchLimit = 10,
    ) -> str:
        """
        Search PubChem for chemical compounds.

        ═══════════════════════════════════════════════════════════════
        USE CASES:
        ═══════════════════════════════════════════════════════════════
        - Look up drug/compound information
        - Find molecular formula and structure
        - Get compound synonyms and identifiers
        - Research chemical properties

        Args:
            query: Compound name or description
            limit: Maximum results (1-50)

        Returns:
            JSON with compound records including names, formulas, properties
        """
        # Normalize inputs
        try:
            query = _bounded_query(query, label="Compound query")
        except ValueError as exc:
            return ResponseFormatter.error(
                exc,
                suggestion="Provide a compound or drug name",
                example='search_compound(query="aspirin")',
                tool_name="search_compound",
            )
        try:
            from pubmed_search.infrastructure.sources import get_ncbi_extended_client

            client = get_ncbi_extended_client()
            results = await client.search_compound(
                query=query,
                limit=limit,
            )

            if not results:
                return ResponseFormatter.no_results(
                    query=query,
                    suggestions=[
                        "Try the generic name instead of brand name",
                        "Check compound name spelling",
                        "Try alternative drug names or synonyms",
                    ],
                )

            return json.dumps(
                {
                    "status": "success",
                    "source": "pubchem",
                    "count": len(results),
                    "compounds": results,
                },
                indent=2,
                ensure_ascii=False,
            )

        except Exception as exc:
            logger.warning("Compound search failed (%s)", type(exc).__name__)
            return ResponseFormatter.error("PubChem search could not be completed", tool_name="search_compound")

    @mcp.tool()
    async def get_compound_details(cid: NcbiIdentifier) -> str:
        """
        Get detailed information about a compound by PubChem CID.

        Args:
            cid: PubChem Compound ID

        Returns:
            JSON with compound details including formula, SMILES, properties
        """
        # Normalize input
        try:
            normalized_cid = normalize_ncbi_identifier(cid, label="PubChem CID")
        except NcbiIdentifierValidationError as exc:
            return ResponseFormatter.error(
                exc,
                suggestion="Provide a PubChem Compound ID",
                example='get_compound_details(cid="2244")',
                tool_name="get_compound_details",
            )
        try:
            from pubmed_search.infrastructure.sources import get_ncbi_extended_client

            client = get_ncbi_extended_client()
            result = await client.get_compound(normalized_cid)

            if result:
                return json.dumps(
                    {"status": "success", "source": "pubchem", "compound": result},
                    indent=2,
                    ensure_ascii=False,
                )
            return ResponseFormatter.no_results(
                suggestions=[
                    f"Compound CID '{normalized_cid}' not found",
                    "Use search_compound to find valid CIDs",
                ]
            )

        except Exception as exc:
            logger.warning("Compound detail lookup failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                "PubChem compound details could not be retrieved",
                tool_name="get_compound_details",
            )

    @mcp.tool()
    async def get_compound_literature(
        cid: NcbiIdentifier,
        limit: LiteratureLimit = 20,
    ) -> str:
        """
        Get PubMed articles linked to a compound.

        Uses NCBI's curated compound-to-publication links.

        Args:
            cid: PubChem Compound ID
            limit: Maximum PubMed IDs to return (1-100)

        Returns:
            JSON with linked PubMed IDs
        """
        # Normalize inputs
        try:
            normalized_cid = normalize_ncbi_identifier(cid, label="PubChem CID")
        except NcbiIdentifierValidationError as exc:
            return ResponseFormatter.error(
                exc,
                suggestion="Provide a PubChem Compound ID",
                example='get_compound_literature(cid="2244", limit=20)',
                tool_name="get_compound_literature",
            )
        try:
            from pubmed_search.infrastructure.sources import get_ncbi_extended_client

            client = get_ncbi_extended_client()
            pmids = await client.get_compound_pubmed_links(normalized_cid, limit=limit)

            if not pmids:
                return ResponseFormatter.no_results(
                    suggestions=[
                        f"No linked publications found for CID '{normalized_cid}'",
                        "Try unified_search with the compound name instead",
                    ]
                )

            return json.dumps(
                {
                    "status": "success",
                    "source": "pubchem",
                    "compound_cid": normalized_cid,
                    "pubmed_count": len(pmids),
                    "pmids": pmids,
                    "note": "Use fetch_article_details with these PMIDs to get article info",
                },
                indent=2,
            )

        except Exception as exc:
            logger.warning("Compound literature lookup failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                "PubChem literature could not be retrieved",
                tool_name="get_compound_literature",
            )

    # =========================================================================
    # ClinVar Database Tools
    # =========================================================================

    @mcp.tool()
    async def search_clinvar(
        query: NcbiQuery,
        limit: SearchLimit = 10,
    ) -> str:
        """
        Search ClinVar for clinical variants.

        ═══════════════════════════════════════════════════════════════
        USE CASES:
        ═══════════════════════════════════════════════════════════════
        - Look up clinical significance of genetic variants
        - Find variants associated with diseases
        - Research gene-disease associations
        - Get variant pathogenicity classifications

        Args:
            query: Gene name, variant, or disease condition
            limit: Maximum results (1-50)

        Returns:
            JSON with variant records including significance and conditions
        """
        # Normalize inputs
        try:
            query = _bounded_query(query, label="ClinVar query")
        except ValueError as exc:
            return ResponseFormatter.error(
                exc,
                suggestion="Provide a gene name, variant, or disease",
                example='search_clinvar(query="BRCA1")',
                tool_name="search_clinvar",
            )
        try:
            from pubmed_search.infrastructure.sources import get_ncbi_extended_client

            client = get_ncbi_extended_client()
            results = await client.search_clinvar(
                query=query,
                limit=limit,
            )

            if not results:
                return ResponseFormatter.no_results(
                    query=query,
                    suggestions=[
                        "Try the official gene symbol",
                        "Try the disease name without abbreviations",
                        "Check variant notation format (e.g., NM_000059.3:c.5946delT)",
                    ],
                )

            return json.dumps(
                {
                    "status": "success",
                    "source": "clinvar",
                    "count": len(results),
                    "variants": results,
                },
                indent=2,
                ensure_ascii=False,
            )

        except Exception as exc:
            logger.warning("ClinVar search failed (%s)", type(exc).__name__)
            return ResponseFormatter.error("ClinVar search could not be completed", tool_name="search_clinvar")
