"""
NCBI Extended API Integration

Provides access to additional NCBI Entrez databases beyond PubMed:
- Gene: Gene records with functions, pathways, interactions
- PubChem: Chemical compound information
- ClinVar: Clinical variant records

All use the same Entrez E-utilities infrastructure.
API Documentation: https://www.ncbi.nlm.nih.gov/books/NBK25497/
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

# NCBI Entrez base URL
ENTREZ_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Default values
DEFAULT_EMAIL = "pubmed-search-mcp@example.com"


class NCBIExtendedClient:
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
    
    def __init__(
        self,
        email: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0
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
        self._timeout = timeout
        self._last_request_time = 0
        # Rate limit: 3/sec without key, 10/sec with key
        self._min_interval = 0.34 if not api_key else 0.1
    
    def _rate_limit(self):
        """Simple rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()
    
    def _make_request(self, url: str, expect_json: bool = False) -> dict | str | None:
        """Make HTTP request to NCBI."""
        self._rate_limit()
        
        # Add required parameters
        separator = "&" if "?" in url else "?"
        url += f"{separator}email={urllib.parse.quote(self._email)}&tool=pubmed-search-mcp"
        if self._api_key:
            url += f"&api_key={self._api_key}"
        
        request = urllib.request.Request(url)
        request.add_header("User-Agent", f"pubmed-search-mcp/1.0 (mailto:{self._email})")
        
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                content = response.read().decode("utf-8")
                if expect_json:
                    return json.loads(content)
                return content
        except urllib.error.HTTPError as e:
            logger.error(f"NCBI HTTP error {e.code}: {e.reason}")
            return None
        except Exception as e:
            logger.error(f"NCBI request failed: {e}")
            return None
    
    # =========================================================================
    # Gene Database
    # =========================================================================
    
    def search_gene(
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
                search_query += f" AND {organism}[Organism]"
            
            # Search
            search_url = (
                f"{ENTREZ_BASE}/esearch.fcgi?db=gene"
                f"&term={urllib.parse.quote(search_query)}"
                f"&retmax={limit}&retmode=json"
            )
            
            search_result = self._make_request(search_url, expect_json=True)
            if not search_result:
                return []
            
            ids = search_result.get("esearchresult", {}).get("idlist", [])
            if not ids:
                return []
            
            # Fetch summaries
            ids_str = ",".join(ids)
            summary_url = (
                f"{ENTREZ_BASE}/esummary.fcgi?db=gene"
                f"&id={ids_str}&retmode=json"
            )
            
            summary_result = self._make_request(summary_url, expect_json=True)
            if not summary_result:
                return []
            
            # Parse results
            genes = []
            result_data = summary_result.get("result", {})
            for gene_id in ids:
                gene_data = result_data.get(gene_id, {})
                if gene_data:
                    genes.append(self._normalize_gene(gene_data))
            
            return genes
            
        except Exception as e:
            logger.error(f"Gene search failed: {e}")
            return []
    
    def get_gene(self, gene_id: str | int) -> dict | None:
        """
        Get gene details by NCBI Gene ID.
        
        Args:
            gene_id: NCBI Gene ID
            
        Returns:
            Gene record or None
        """
        try:
            url = f"{ENTREZ_BASE}/esummary.fcgi?db=gene&id={gene_id}&retmode=json"
            result = self._make_request(url, expect_json=True)
            
            if not result:
                return None
            
            gene_data = result.get("result", {}).get(str(gene_id), {})
            if gene_data:
                return self._normalize_gene(gene_data)
            
            return None
            
        except Exception as e:
            logger.error(f"Get gene failed: {e}")
            return None
    
    def get_gene_pubmed_links(self, gene_id: str | int, limit: int = 20) -> list[str]:
        """
        Get PubMed IDs linked to a gene.
        
        Args:
            gene_id: NCBI Gene ID
            limit: Maximum PubMed IDs to return
            
        Returns:
            List of PubMed IDs
        """
        try:
            url = (
                f"{ENTREZ_BASE}/elink.fcgi?dbfrom=gene&db=pubmed"
                f"&id={gene_id}&retmode=json"
            )
            result = self._make_request(url, expect_json=True)
            
            if not result:
                return []
            
            linksets = result.get("linksets", [])
            pmids = []
            
            for linkset in linksets:
                for linksetdb in linkset.get("linksetdbs", []):
                    if linksetdb.get("dbto") == "pubmed":
                        pmids.extend([str(x) for x in linksetdb.get("links", [])])
            
            return pmids[:limit]
            
        except Exception as e:
            logger.error(f"Get gene PubMed links failed: {e}")
            return []
    
    def _normalize_gene(self, gene: dict) -> dict:
        """Normalize gene data to common format."""
        return {
            "gene_id": gene.get("uid"),
            "symbol": gene.get("name", ""),
            "name": gene.get("description", ""),
            "organism": gene.get("organism", {}).get("scientificname", ""),
            "tax_id": gene.get("organism", {}).get("taxid"),
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
    
    def search_compound(
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
                f"{ENTREZ_BASE}/esearch.fcgi?db=pccompound"
                f"&term={urllib.parse.quote(query)}"
                f"&retmax={limit}&retmode=json"
            )
            
            search_result = self._make_request(search_url, expect_json=True)
            if not search_result:
                return []
            
            ids = search_result.get("esearchresult", {}).get("idlist", [])
            if not ids:
                return []
            
            # Fetch summaries
            ids_str = ",".join(ids)
            summary_url = (
                f"{ENTREZ_BASE}/esummary.fcgi?db=pccompound"
                f"&id={ids_str}&retmode=json"
            )
            
            summary_result = self._make_request(summary_url, expect_json=True)
            if not summary_result:
                return []
            
            # Parse results
            compounds = []
            result_data = summary_result.get("result", {})
            for cid in ids:
                compound_data = result_data.get(cid, {})
                if compound_data:
                    compounds.append(self._normalize_compound(compound_data))
            
            return compounds
            
        except Exception as e:
            logger.error(f"Compound search failed: {e}")
            return []
    
    def get_compound(self, cid: str | int) -> dict | None:
        """
        Get compound details by PubChem CID.
        
        Args:
            cid: PubChem Compound ID
            
        Returns:
            Compound record or None
        """
        try:
            url = f"{ENTREZ_BASE}/esummary.fcgi?db=pccompound&id={cid}&retmode=json"
            result = self._make_request(url, expect_json=True)
            
            if not result:
                return None
            
            compound_data = result.get("result", {}).get(str(cid), {})
            if compound_data:
                return self._normalize_compound(compound_data)
            
            return None
            
        except Exception as e:
            logger.error(f"Get compound failed: {e}")
            return None
    
    def get_compound_pubmed_links(self, cid: str | int, limit: int = 20) -> list[str]:
        """
        Get PubMed IDs linked to a compound.
        
        Args:
            cid: PubChem Compound ID
            limit: Maximum PubMed IDs to return
            
        Returns:
            List of PubMed IDs
        """
        try:
            url = (
                f"{ENTREZ_BASE}/elink.fcgi?dbfrom=pccompound&db=pubmed"
                f"&id={cid}&retmode=json"
            )
            result = self._make_request(url, expect_json=True)
            
            if not result:
                return []
            
            linksets = result.get("linksets", [])
            pmids = []
            
            for linkset in linksets:
                for linksetdb in linkset.get("linksetdbs", []):
                    if linksetdb.get("dbto") == "pubmed":
                        pmids.extend([str(x) for x in linksetdb.get("links", [])])
            
            return pmids[:limit]
            
        except Exception as e:
            logger.error(f"Get compound PubMed links failed: {e}")
            return []
    
    def _normalize_compound(self, compound: dict) -> dict:
        """Normalize compound data to common format."""
        # Get synonyms
        synonyms = compound.get("synonymlist", [])
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
    
    def search_clinvar(
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
                f"{ENTREZ_BASE}/esearch.fcgi?db=clinvar"
                f"&term={urllib.parse.quote(query)}"
                f"&retmax={limit}&retmode=json"
            )
            
            search_result = self._make_request(search_url, expect_json=True)
            if not search_result:
                return []
            
            ids = search_result.get("esearchresult", {}).get("idlist", [])
            if not ids:
                return []
            
            # Fetch summaries
            ids_str = ",".join(ids)
            summary_url = (
                f"{ENTREZ_BASE}/esummary.fcgi?db=clinvar"
                f"&id={ids_str}&retmode=json"
            )
            
            summary_result = self._make_request(summary_url, expect_json=True)
            if not summary_result:
                return []
            
            # Parse results
            variants = []
            result_data = summary_result.get("result", {})
            for var_id in ids:
                var_data = result_data.get(var_id, {})
                if var_data:
                    variants.append(self._normalize_clinvar(var_data))
            
            return variants
            
        except Exception as e:
            logger.error(f"ClinVar search failed: {e}")
            return []
    
    def _normalize_clinvar(self, variant: dict) -> dict:
        """Normalize ClinVar data to common format."""
        # Get clinical significance
        clinical_sig = variant.get("clinical_significance", {})
        if isinstance(clinical_sig, dict):
            significance = clinical_sig.get("description", "")
        else:
            significance = str(clinical_sig)
        
        # Get genes
        genes = variant.get("genes", [])
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
            "conditions": [c.get("trait_name", "") for c in variant.get("trait_set", []) if isinstance(c, dict)],
            "_source": "clinvar",
        }


# Singleton instance
_ncbi_extended_client: NCBIExtendedClient | None = None


def get_ncbi_extended_client(
    email: str | None = None,
    api_key: str | None = None
) -> NCBIExtendedClient:
    """Get or create NCBI extended client singleton."""
    global _ncbi_extended_client
    if _ncbi_extended_client is None:
        import os
        _ncbi_extended_client = NCBIExtendedClient(
            email=email or os.environ.get("NCBI_EMAIL"),
            api_key=api_key or os.environ.get("NCBI_API_KEY"),
        )
    return _ncbi_extended_client
