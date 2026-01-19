"""
Copilot Studio Compatible Tools

This module wraps existing MCP tools with schemas that avoid patterns
that Copilot Studio doesn't support:

Known Issues (from Microsoft docs):
1. anyOf (multi-type arrays) - causes schema truncation
2. exclusiveMinimum as integer (must be boolean)
3. Reference type inputs ($ref)

Solution: All parameters use simple single types (string, boolean, integer)
with internal normalization via InputNormalizer.
"""

import logging
from typing import Literal

from mcp.server.fastmcp import FastMCP

from ..entrez import LiteratureSearcher
from .tools._common import InputNormalizer, ResponseFormatter

logger = logging.getLogger(__name__)


def register_copilot_compatible_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """
    Register Copilot Studio compatible tools.
    
    These tools have simplified schemas that avoid:
    - Union types (anyOf)
    - Optional types with null (use empty string instead)
    - Reference types ($ref)
    
    All parameters are single-type (string, int, bool) with internal normalization.
    """
    
    # ========================================================================
    # Core Search Tools
    # ========================================================================
    
    @mcp.tool()
    def search_pubmed(
        query: str,
        limit: int = 10,
        min_year: int = 0,
        max_year: int = 0,
    ) -> str:
        """
        Search PubMed for scientific literature.
        
        Args:
            query: Search query (keywords, MeSH terms, etc.)
            limit: Maximum number of results (1-100, default 10)
            min_year: Minimum publication year (0 = no filter)
            max_year: Maximum publication year (0 = no filter)
            
        Returns:
            Formatted search results with PMID, title, authors, journal
        """
        # Normalize inputs
        limit = InputNormalizer.normalize_limit(limit, default=10, max_val=100)
        min_year_val = min_year if min_year > 1900 else None
        max_year_val = max_year if max_year > 1900 else None
        
        try:
            results = searcher.search(
                query=query,
                limit=limit,
                min_year=min_year_val,
                max_year=max_year_val,
            )
            
            if not results:
                return ResponseFormatter.no_results(query=query)
            
            # Format results
            from .tools._common import format_search_results, _cache_results
            _cache_results(results, query)
            return format_search_results(results)
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return ResponseFormatter.error(e, tool_name="search_pubmed")
    
    @mcp.tool()
    def get_article(
        pmid: str,
    ) -> str:
        """
        Get detailed information about a specific article by PMID.
        
        Args:
            pmid: PubMed ID (e.g., "12345678" or "PMID:12345678")
            
        Returns:
            Article details including title, abstract, authors, etc.
        """
        # Normalize PMID
        clean_pmid = InputNormalizer.normalize_pmid_single(pmid)
        if not clean_pmid:
            return ResponseFormatter.error(
                "Invalid PMID format",
                suggestion="Use numeric PMID like '12345678'",
                example='get_article(pmid="12345678")',
                tool_name="get_article"
            )
        
        try:
            results = searcher.fetch_details([clean_pmid])
            
            if not results:
                return f"Article with PMID {clean_pmid} not found."
            
            article = results[0]
            
            # Format article details
            output = [
                f"## {article.get('title', 'No title')}",
                "",
                f"**PMID**: {article.get('pmid', '')}",
            ]
            
            if article.get('doi'):
                output.append(f"**DOI**: {article['doi']}")
            if article.get('pmc_id'):
                output.append(f"**PMC**: {article['pmc_id']}")
            
            output.append("")
            
            authors = article.get('authors', [])
            if authors:
                author_str = ', '.join(authors[:5])
                if len(authors) > 5:
                    author_str += f" et al. ({len(authors)} authors)"
                output.append(f"**Authors**: {author_str}")
            
            journal = article.get('journal', '')
            year = article.get('year', '')
            if journal:
                output.append(f"**Journal**: {journal} ({year})")
            
            abstract = article.get('abstract', '')
            if abstract:
                output.append(f"\n**Abstract**:\n{abstract}")
            
            return "\n".join(output)
            
        except Exception as e:
            logger.error(f"Failed to get article: {e}")
            return ResponseFormatter.error(e, tool_name="get_article")
    
    @mcp.tool()
    def find_related(
        pmid: str,
        limit: int = 10,
    ) -> str:
        """
        Find articles related to a given article.
        
        Args:
            pmid: PubMed ID of the reference article
            limit: Maximum number of related articles (1-50, default 10)
            
        Returns:
            List of related articles
        """
        clean_pmid = InputNormalizer.normalize_pmid_single(pmid)
        if not clean_pmid:
            return ResponseFormatter.error(
                "Invalid PMID",
                suggestion="Use numeric PMID",
                tool_name="find_related"
            )
        
        limit = InputNormalizer.normalize_limit(limit, default=10, max_val=50)
        
        try:
            results = searcher.find_related(clean_pmid, limit=limit)
            
            if not results:
                return f"No related articles found for PMID {clean_pmid}"
            
            from .tools._common import format_search_results, _cache_results
            _cache_results(results, f"related:{clean_pmid}")
            return format_search_results(results)
            
        except Exception as e:
            logger.error(f"Find related failed: {e}")
            return ResponseFormatter.error(e, tool_name="find_related")
    
    @mcp.tool()
    def find_citations(
        pmid: str,
        limit: int = 20,
    ) -> str:
        """
        Find articles that cite a given article.
        
        Args:
            pmid: PubMed ID of the cited article
            limit: Maximum number of citing articles (1-100, default 20)
            
        Returns:
            List of articles that cite this article
        """
        clean_pmid = InputNormalizer.normalize_pmid_single(pmid)
        if not clean_pmid:
            return ResponseFormatter.error(
                "Invalid PMID",
                tool_name="find_citations"
            )
        
        limit = InputNormalizer.normalize_limit(limit, default=20, max_val=100)
        
        try:
            results = searcher.find_citing_articles(clean_pmid, max_results=limit)
            
            if not results:
                return f"No citing articles found for PMID {clean_pmid}"
            
            from .tools._common import format_search_results, _cache_results
            _cache_results(results, f"citations:{clean_pmid}")
            return format_search_results(results)
            
        except Exception as e:
            logger.error(f"Find citations failed: {e}")
            return ResponseFormatter.error(e, tool_name="find_citations")
    
    @mcp.tool()
    def get_references(
        pmid: str,
        limit: int = 20,
    ) -> str:
        """
        Get the reference list of an article.
        
        Args:
            pmid: PubMed ID of the article
            limit: Maximum number of references (1-100, default 20)
            
        Returns:
            List of articles in the reference list
        """
        clean_pmid = InputNormalizer.normalize_pmid_single(pmid)
        if not clean_pmid:
            return ResponseFormatter.error(
                "Invalid PMID",
                tool_name="get_references"
            )
        
        limit = InputNormalizer.normalize_limit(limit, default=20, max_val=100)
        
        try:
            results = searcher.get_article_references(clean_pmid, max_results=limit)
            
            if not results:
                return f"No references found for PMID {clean_pmid}"
            
            from .tools._common import format_search_results, _cache_results
            _cache_results(results, f"references:{clean_pmid}")
            return format_search_results(results)
            
        except Exception as e:
            logger.error(f"Get references failed: {e}")
            return ResponseFormatter.error(e, tool_name="get_references")
    
    # ========================================================================
    # PICO and Query Generation Tools
    # ========================================================================
    
    @mcp.tool()
    def analyze_clinical_question(
        question: str,
    ) -> str:
        """
        Parse a clinical question into PICO elements.
        
        PICO = Population, Intervention, Comparison, Outcome
        
        Args:
            question: Clinical question in natural language
            
        Returns:
            Parsed PICO elements with search suggestions
        """
        from .tools.pico import _analyze_pico_description
        
        try:
            result = _analyze_pico_description(question)
            return result
        except Exception as e:
            logger.error(f"PICO analysis failed: {e}")
            return ResponseFormatter.error(e, tool_name="analyze_clinical_question")
    
    @mcp.tool()
    def expand_search_terms(
        topic: str,
    ) -> str:
        """
        Expand a search topic with MeSH terms and synonyms.
        
        Args:
            topic: Search topic or keyword
            
        Returns:
            MeSH terms, synonyms, and suggested search strategies
        """
        from .tools._common import get_strategy_generator
        import json
        
        strategy_gen = get_strategy_generator()
        
        if strategy_gen:
            try:
                result = strategy_gen.generate_strategies(
                    topic=topic,
                    strategy="comprehensive",
                    use_mesh=True,
                    check_spelling=True,
                    include_suggestions=True
                )
                return json.dumps(result, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.warning(f"Strategy generator failed: {e}")
        
        # Fallback
        return f"Search suggestions for '{topic}':\n1. ({topic})[Title/Abstract]\n2. ({topic})[MeSH Terms]"
    
    # ========================================================================
    # Full Text and Export Tools
    # ========================================================================
    
    @mcp.tool()
    def get_fulltext(
        pmcid: str,
        sections: str = "",
    ) -> str:
        """
        Get full text of an article from Europe PMC.
        
        Args:
            pmcid: PMC ID (e.g., "PMC7096777" or "7096777")
            sections: Comma-separated section names (empty = all)
                     Options: introduction, methods, results, discussion, conclusion
            
        Returns:
            Full text content in structured format
        """
        # Normalize PMCID
        clean_pmcid = InputNormalizer.normalize_pmcid(pmcid)
        if not clean_pmcid:
            return ResponseFormatter.error(
                "Invalid PMC ID",
                suggestion="Use format like 'PMC7096777' or '7096777'",
                tool_name="get_fulltext"
            )
        
        try:
            from ..sources.europe_pmc import EuropePMCClient
            
            client = EuropePMCClient()
            result = client.get_fulltext(
                pmcid=clean_pmcid,
                sections=sections.split(',') if sections else None
            )
            
            if not result or not result.get('content'):
                return f"Full text not available for {clean_pmcid}"
            
            # Format output
            output = [f"## Full Text: {clean_pmcid}"]
            
            for section in result.get('content', []):
                output.append(f"\n### {section.get('title', 'Section')}")
                output.append(section.get('text', ''))
            
            return "\n".join(output)
            
        except Exception as e:
            logger.error(f"Get fulltext failed: {e}")
            return ResponseFormatter.error(e, tool_name="get_fulltext")
    
    @mcp.tool()
    def export_citations(
        pmids: str,
        format: Literal["ris", "bibtex", "csv"] = "ris",
    ) -> str:
        """
        Export citations in various formats.
        
        Args:
            pmids: Comma-separated PMIDs or "last" for last search results
            format: Export format (ris, bibtex, csv)
            
        Returns:
            Citation data in requested format
        """
        from .tools._common import get_last_search_pmids
        
        # Handle "last" keyword
        if pmids.lower().strip() == "last":
            pmid_list = get_last_search_pmids()
            if not pmid_list:
                return ResponseFormatter.error(
                    "No previous search results",
                    suggestion="Run a search first, then use 'last'",
                    tool_name="export_citations"
                )
        else:
            pmid_list = InputNormalizer.normalize_pmids(pmids)
        
        if not pmid_list:
            return ResponseFormatter.error(
                "No valid PMIDs provided",
                suggestion="Use comma-separated PMIDs like '12345678,87654321'",
                tool_name="export_citations"
            )
        
        try:
            from ..export.formats import export_to_ris, export_to_bibtex, export_to_csv
            
            # Fetch article details
            articles = searcher.fetch_details(pmid_list[:50])  # Limit to 50
            
            if not articles:
                return "No articles found for the provided PMIDs"
            
            # Export based on format
            if format == "bibtex":
                content = export_to_bibtex(articles)
            elif format == "csv":
                content = export_to_csv(articles)
            else:
                content = export_to_ris(articles)
            
            return f"## Exported {len(articles)} citations ({format.upper()})\n\n```\n{content}\n```"
            
        except Exception as e:
            logger.error(f"Export failed: {e}")
            return ResponseFormatter.error(e, tool_name="export_citations")
    
    # ========================================================================
    # Gene and Compound Research
    # ========================================================================
    
    @mcp.tool()
    def search_gene(
        query: str,
        organism: str = "human",
        limit: int = 10,
    ) -> str:
        """
        Search NCBI Gene database.
        
        Args:
            query: Gene name or symbol (e.g., "BRCA1", "p53")
            organism: Organism filter (default "human")
            limit: Maximum results (1-50, default 10)
            
        Returns:
            Gene information including ID, symbol, description
        """
        limit = InputNormalizer.normalize_limit(limit, default=10, max_val=50)
        
        try:
            from ..ncbi.gene import search_gene_db
            
            results = search_gene_db(
                query=query,
                organism=organism if organism else "human",
                limit=limit
            )
            
            if not results:
                return f"No genes found for '{query}'"
            
            # Format output
            import json
            return json.dumps(results, indent=2, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"Gene search failed: {e}")
            return ResponseFormatter.error(e, tool_name="search_gene")
    
    @mcp.tool()
    def search_compound(
        query: str,
        limit: int = 10,
    ) -> str:
        """
        Search PubChem for chemical compounds.
        
        Args:
            query: Compound name (e.g., "aspirin", "propofol")
            limit: Maximum results (1-50, default 10)
            
        Returns:
            Compound information including CID, formula, structure
        """
        limit = InputNormalizer.normalize_limit(limit, default=10, max_val=50)
        
        try:
            from ..ncbi.pubchem import search_compound_db
            
            results = search_compound_db(
                query=query,
                limit=limit
            )
            
            if not results:
                return f"No compounds found for '{query}'"
            
            import json
            return json.dumps(results, indent=2, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"Compound search failed: {e}")
            return ResponseFormatter.error(e, tool_name="search_compound")


# Tool count for verification
COPILOT_TOOL_COUNT = 12  # Number of tools registered above
