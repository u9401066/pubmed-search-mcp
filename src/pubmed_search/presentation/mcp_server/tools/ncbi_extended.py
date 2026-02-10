"""
NCBI Extended Database MCP Tools

Provides MCP tools for accessing additional NCBI databases beyond PubMed:
- Gene: Gene records with functions, pathways, interactions
- PubChem: Chemical compound information
- ClinVar: Clinical variant records

These tools complement PubMed search for comprehensive biomedical research.
"""

import json
import logging
from typing import Union

from mcp.server.fastmcp import FastMCP

from ._common import InputNormalizer, ResponseFormatter

logger = logging.getLogger(__name__)


def register_ncbi_extended_tools(mcp: FastMCP) -> None:
    """Register NCBI Extended database tools with MCP server."""

    # =========================================================================
    # Gene Database Tools
    # =========================================================================

    @mcp.tool()
    async def search_gene(
        query: str,
        organism: str | None = None,
        limit: Union[int, str] = 10,
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
        query = InputNormalizer.normalize_query(query)
        if not query:
            return ResponseFormatter.error(
                "Empty query",
                suggestion="Provide a gene name or symbol",
                example='search_gene(query="BRCA1", organism="human")',
                tool_name="search_gene",
            )

        limit = InputNormalizer.normalize_limit(limit, default=10, max_val=50)
        organism = organism.strip() if organism else None

        try:
            from pubmed_search.infrastructure.sources.ncbi_extended import (
                get_ncbi_extended_client,
            )  # type: ignore[import-not-found]

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
                    "count": len(results),
                    "genes": results,
                },
                indent=2,
                ensure_ascii=False,
            )

        except Exception as e:
            logger.error(f"Gene search failed: {e}")
            return ResponseFormatter.error(e, tool_name="search_gene")

    @mcp.tool()
    async def get_gene_details(gene_id: Union[str, int]) -> str:
        """
        Get detailed information about a gene by NCBI Gene ID.

        Args:
            gene_id: NCBI Gene ID (from search results or known)

        Returns:
            JSON with gene details including symbol, name, summary, location
        """
        # Normalize input
        if gene_id is None:
            return ResponseFormatter.error(
                "Missing gene_id",
                suggestion="Provide an NCBI Gene ID",
                example='get_gene_details(gene_id="672")',
                tool_name="get_gene_details",
            )
        gene_id = str(gene_id).strip()

        try:
            from pubmed_search.infrastructure.sources.ncbi_extended import (
                get_ncbi_extended_client,
            )  # type: ignore[import-not-found]

            client = get_ncbi_extended_client()
            result = await client.get_gene(gene_id)

            if result:
                return json.dumps(result, indent=2, ensure_ascii=False)
            else:
                return ResponseFormatter.no_results(
                    suggestions=[
                        f"Gene ID '{gene_id}' not found",
                        "Use search_gene to find valid Gene IDs",
                    ]
                )

        except Exception as e:
            logger.error(f"Get gene details failed: {e}")
            return ResponseFormatter.error(e, tool_name="get_gene_details")

    @mcp.tool()
    async def get_gene_literature(
        gene_id: Union[str, int],
        limit: Union[int, str] = 20,
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
        if gene_id is None:
            return ResponseFormatter.error(
                "Missing gene_id",
                suggestion="Provide an NCBI Gene ID",
                example='get_gene_literature(gene_id="672", limit=20)',
                tool_name="get_gene_literature",
            )
        gene_id = str(gene_id).strip()
        limit = InputNormalizer.normalize_limit(limit, default=20, max_val=100)

        try:
            from pubmed_search.infrastructure.sources.ncbi_extended import (
                get_ncbi_extended_client,
            )  # type: ignore[import-not-found]

            client = get_ncbi_extended_client()
            pmids = await client.get_gene_pubmed_links(gene_id, limit=limit)

            if not pmids:
                return ResponseFormatter.no_results(
                    suggestions=[
                        f"No linked publications found for Gene ID '{gene_id}'",
                        "Try search_literature with gene name instead",
                    ]
                )

            return json.dumps(
                {
                    "gene_id": gene_id,
                    "pubmed_count": len(pmids),
                    "pmids": pmids,
                    "note": "Use fetch_article_details with these PMIDs to get article info",
                },
                indent=2,
            )

        except Exception as e:
            logger.error(f"Get gene literature failed: {e}")
            return ResponseFormatter.error(e, tool_name="get_gene_literature")

    # =========================================================================
    # PubChem Database Tools
    # =========================================================================

    @mcp.tool()
    async def search_compound(
        query: str,
        limit: Union[int, str] = 10,
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
        query = InputNormalizer.normalize_query(query)
        if not query:
            return ResponseFormatter.error(
                "Empty query",
                suggestion="Provide a compound or drug name",
                example='search_compound(query="aspirin")',
                tool_name="search_compound",
            )

        limit = InputNormalizer.normalize_limit(limit, default=10, max_val=50)

        try:
            from pubmed_search.infrastructure.sources.ncbi_extended import (
                get_ncbi_extended_client,
            )  # type: ignore[import-not-found]

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
                    "count": len(results),
                    "compounds": results,
                },
                indent=2,
                ensure_ascii=False,
            )

        except Exception as e:
            logger.error(f"Compound search failed: {e}")
            return ResponseFormatter.error(e, tool_name="search_compound")

    @mcp.tool()
    async def get_compound_details(cid: Union[str, int]) -> str:
        """
        Get detailed information about a compound by PubChem CID.

        Args:
            cid: PubChem Compound ID

        Returns:
            JSON with compound details including formula, SMILES, properties
        """
        # Normalize input
        if cid is None:
            return ResponseFormatter.error(
                "Missing cid",
                suggestion="Provide a PubChem Compound ID",
                example='get_compound_details(cid="2244")',
                tool_name="get_compound_details",
            )
        cid = str(cid).strip()

        try:
            from pubmed_search.infrastructure.sources.ncbi_extended import (
                get_ncbi_extended_client,
            )  # type: ignore[import-not-found]

            client = get_ncbi_extended_client()
            result = await client.get_compound(cid)

            if result:
                return json.dumps(result, indent=2, ensure_ascii=False)
            else:
                return ResponseFormatter.no_results(
                    suggestions=[
                        f"Compound CID '{cid}' not found",
                        "Use search_compound to find valid CIDs",
                    ]
                )

        except Exception as e:
            logger.error(f"Get compound details failed: {e}")
            return ResponseFormatter.error(e, tool_name="get_compound_details")

    @mcp.tool()
    async def get_compound_literature(
        cid: Union[str, int],
        limit: Union[int, str] = 20,
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
        if cid is None:
            return ResponseFormatter.error(
                "Missing cid",
                suggestion="Provide a PubChem Compound ID",
                example='get_compound_literature(cid="2244", limit=20)',
                tool_name="get_compound_literature",
            )
        cid = str(cid).strip()
        limit = InputNormalizer.normalize_limit(limit, default=20, max_val=100)

        try:
            from pubmed_search.infrastructure.sources.ncbi_extended import (
                get_ncbi_extended_client,
            )  # type: ignore[import-not-found]

            client = get_ncbi_extended_client()
            pmids = await client.get_compound_pubmed_links(cid, limit=limit)

            if not pmids:
                return ResponseFormatter.no_results(
                    suggestions=[
                        f"No linked publications found for CID '{cid}'",
                        "Try search_literature with compound name instead",
                    ]
                )

            return json.dumps(
                {
                    "compound_cid": cid,
                    "pubmed_count": len(pmids),
                    "pmids": pmids,
                    "note": "Use fetch_article_details with these PMIDs to get article info",
                },
                indent=2,
            )

        except Exception as e:
            logger.error(f"Get compound literature failed: {e}")
            return ResponseFormatter.error(e, tool_name="get_compound_literature")

    # =========================================================================
    # ClinVar Database Tools
    # =========================================================================

    @mcp.tool()
    async def search_clinvar(
        query: str,
        limit: Union[int, str] = 10,
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
        query = InputNormalizer.normalize_query(query)
        if not query:
            return ResponseFormatter.error(
                "Empty query",
                suggestion="Provide a gene name, variant, or disease",
                example='search_clinvar(query="BRCA1")',
                tool_name="search_clinvar",
            )

        limit = InputNormalizer.normalize_limit(limit, default=10, max_val=50)

        try:
            from pubmed_search.infrastructure.sources.ncbi_extended import (
                get_ncbi_extended_client,
            )  # type: ignore[import-not-found]

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
                    "count": len(results),
                    "variants": results,
                },
                indent=2,
                ensure_ascii=False,
            )

        except Exception as e:
            logger.error(f"ClinVar search failed: {e}")
            return ResponseFormatter.error(e, tool_name="search_clinvar")
