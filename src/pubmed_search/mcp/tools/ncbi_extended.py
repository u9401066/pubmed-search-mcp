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
from typing import Any

from mcp.server import Server

logger = logging.getLogger(__name__)


def register_ncbi_extended_tools(mcp: Server) -> None:
    """Register NCBI Extended database tools with MCP server."""
    
    # =========================================================================
    # Gene Database Tools
    # =========================================================================
    
    @mcp.tool()
    async def search_gene(
        query: str,
        organism: str | None = None,
        limit: int = 10,
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
        try:
            from ..sources.ncbi_extended import get_ncbi_extended_client
            
            client = get_ncbi_extended_client()
            results = client.search_gene(
                query=query,
                organism=organism,
                limit=min(limit, 50),
            )
            
            return json.dumps({
                "count": len(results),
                "genes": results,
            }, indent=2, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"Gene search failed: {e}")
            return json.dumps({"error": str(e)})
    
    @mcp.tool()
    async def get_gene_details(gene_id: str) -> str:
        """
        Get detailed information about a gene by NCBI Gene ID.
        
        Args:
            gene_id: NCBI Gene ID (from search results or known)
            
        Returns:
            JSON with gene details including symbol, name, summary, location
        """
        try:
            from ..sources.ncbi_extended import get_ncbi_extended_client
            
            client = get_ncbi_extended_client()
            result = client.get_gene(gene_id)
            
            if result:
                return json.dumps(result, indent=2, ensure_ascii=False)
            else:
                return json.dumps({"error": f"Gene {gene_id} not found"})
                
        except Exception as e:
            logger.error(f"Get gene details failed: {e}")
            return json.dumps({"error": str(e)})
    
    @mcp.tool()
    async def get_gene_literature(
        gene_id: str,
        limit: int = 20,
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
        try:
            from ..sources.ncbi_extended import get_ncbi_extended_client
            
            client = get_ncbi_extended_client()
            pmids = client.get_gene_pubmed_links(gene_id, limit=min(limit, 100))
            
            return json.dumps({
                "gene_id": gene_id,
                "pubmed_count": len(pmids),
                "pmids": pmids,
                "note": "Use fetch_article_details with these PMIDs to get article info"
            }, indent=2)
            
        except Exception as e:
            logger.error(f"Get gene literature failed: {e}")
            return json.dumps({"error": str(e)})
    
    # =========================================================================
    # PubChem Database Tools
    # =========================================================================
    
    @mcp.tool()
    async def search_compound(
        query: str,
        limit: int = 10,
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
        try:
            from ..sources.ncbi_extended import get_ncbi_extended_client
            
            client = get_ncbi_extended_client()
            results = client.search_compound(
                query=query,
                limit=min(limit, 50),
            )
            
            return json.dumps({
                "count": len(results),
                "compounds": results,
            }, indent=2, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"Compound search failed: {e}")
            return json.dumps({"error": str(e)})
    
    @mcp.tool()
    async def get_compound_details(cid: str) -> str:
        """
        Get detailed information about a compound by PubChem CID.
        
        Args:
            cid: PubChem Compound ID
            
        Returns:
            JSON with compound details including formula, SMILES, properties
        """
        try:
            from ..sources.ncbi_extended import get_ncbi_extended_client
            
            client = get_ncbi_extended_client()
            result = client.get_compound(cid)
            
            if result:
                return json.dumps(result, indent=2, ensure_ascii=False)
            else:
                return json.dumps({"error": f"Compound {cid} not found"})
                
        except Exception as e:
            logger.error(f"Get compound details failed: {e}")
            return json.dumps({"error": str(e)})
    
    @mcp.tool()
    async def get_compound_literature(
        cid: str,
        limit: int = 20,
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
        try:
            from ..sources.ncbi_extended import get_ncbi_extended_client
            
            client = get_ncbi_extended_client()
            pmids = client.get_compound_pubmed_links(cid, limit=min(limit, 100))
            
            return json.dumps({
                "compound_cid": cid,
                "pubmed_count": len(pmids),
                "pmids": pmids,
                "note": "Use fetch_article_details with these PMIDs to get article info"
            }, indent=2)
            
        except Exception as e:
            logger.error(f"Get compound literature failed: {e}")
            return json.dumps({"error": str(e)})
    
    # =========================================================================
    # ClinVar Database Tools
    # =========================================================================
    
    @mcp.tool()
    async def search_clinvar(
        query: str,
        limit: int = 10,
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
        try:
            from ..sources.ncbi_extended import get_ncbi_extended_client
            
            client = get_ncbi_extended_client()
            results = client.search_clinvar(
                query=query,
                limit=min(limit, 50),
            )
            
            return json.dumps({
                "count": len(results),
                "variants": results,
            }, indent=2, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"ClinVar search failed: {e}")
            return json.dumps({"error": str(e)})
