"""
Europe PMC Tools - Access Europe PMC for fulltext and search.

Tools:
- search_europe_pmc: Search Europe PMC (33M+ articles, 6.5M OA)
- get_fulltext: Get parsed fulltext content from Europe PMC
- get_fulltext_xml: Get raw JATS XML fulltext
- get_text_mined_terms: Get text-mined annotations (genes, diseases, chemicals)
- get_europe_pmc_citations: Get citation network from Europe PMC

Europe PMC unique features:
- Direct fulltext XML access via /{pmcid}/fullTextXML
- Text mining annotations (genes, diseases, chemicals, organisms)
- 33M+ publications, 6.5M open access fulltext
- No API key required

Phase 2.1 Updates:
- InputNormalizer for flexible input handling
- ResponseFormatter for consistent error messages
"""

import logging
from typing import Optional, Union, Dict, Any, List

from mcp.server.fastmcp import FastMCP

from ...sources import get_europe_pmc_client
from ._common import InputNormalizer, ResponseFormatter

logger = logging.getLogger(__name__)


def register_europe_pmc_tools(mcp: FastMCP):
    """Register Europe PMC tools for fulltext access and search."""
    
    @mcp.tool()
    def search_europe_pmc(
        query: str,
        limit: int = 10,
        min_year: Optional[int] = None,
        max_year: Optional[int] = None,
        open_access_only: bool = False,
        has_fulltext: bool = False,
        sort: str = "relevance",
    ) -> str:
        """
        Search Europe PMC for scientific literature.
        
        Europe PMC indexes 33M+ publications with 6.5M open access fulltext.
        Best for: finding open access papers, getting fulltext, European research.
        
        Args:
            query: Search query (supports standard boolean operators AND, OR, NOT).
            limit: Maximum number of results (1-100, default: 10).
            min_year: Filter by minimum publication year (e.g., 2020).
            max_year: Filter by maximum publication year (e.g., 2024).
            open_access_only: Only return open access papers.
            has_fulltext: Only return papers with fulltext available in Europe PMC.
            sort: Sort order - "relevance" (default), "date" (newest first), or "cited" (most cited).
            
        Returns:
            Search results with titles, abstracts, and fulltext availability.
        """
        # Phase 2.1: Input normalization
        normalized_query = InputNormalizer.normalize_query(query)
        if not normalized_query:
            return ResponseFormatter.error(
                error="Query is required",
                suggestion="Provide a search query",
                example='search_europe_pmc(query="COVID-19 treatment")',
                tool_name="search_europe_pmc"
            )
        
        normalized_limit = InputNormalizer.normalize_limit(limit, default=10, min_val=1, max_val=100)
        normalized_min_year = InputNormalizer.normalize_year(min_year)
        normalized_max_year = InputNormalizer.normalize_year(max_year)
        normalized_oa_only = InputNormalizer.normalize_bool(open_access_only, default=False)
        normalized_fulltext = InputNormalizer.normalize_bool(has_fulltext, default=False)
        
        logger.info(f"Searching Europe PMC: query='{normalized_query}', limit={normalized_limit}")
        
        try:
            client = get_europe_pmc_client()
            
            # Map sort_by to Europe PMC sort syntax
            sort_map = {
                "relevance": None,  # Default sorting
                "date": "P_PDATE_D desc",
                "cited": "CITED desc",
            }
            sort_param = sort_map.get(sort, None)
            
            result = client.search(
                query=normalized_query,
                limit=normalized_limit,
                min_year=normalized_min_year,
                max_year=normalized_max_year,
                open_access_only=normalized_oa_only,
                has_fulltext=normalized_fulltext,
                sort=sort_param,
            )
            
            if not result.get("results"):
                return ResponseFormatter.no_results(
                    query=normalized_query,
                    suggestions=[
                        "Try broader search terms",
                        "Remove year filters",
                        "Disable open_access_only filter",
                        "Try search_literature for PubMed instead"
                    ]
                )
            
            total = result.get("hit_count", len(result["results"]))
            articles = result["results"]
            
            # Format header
            output = "📚 **Europe PMC Search Results**\n"
            output += f"Found **{len(articles)}** results"
            if total > len(articles):
                output += f" (of {total:,} total)"
            
            filters = []
            if normalized_oa_only:
                filters.append("Open Access")
            if normalized_fulltext:
                filters.append("Fulltext available")
            if normalized_min_year or normalized_max_year:
                year_range = f"{normalized_min_year or '...'}-{normalized_max_year or '...'}"
                filters.append(year_range)
            if filters:
                output += f" | Filters: {', '.join(filters)}"
            output += "\n\n"
            
            # Format results
            for i, article in enumerate(articles, 1):
                pmid = article.get("pmid", "N/A")
                pmc_id = article.get("pmc_id", "")
                title = article.get("title", "No title")
                authors = article.get("authors", [])
                year = article.get("year", "")
                journal = article.get("journal", "")
                
                # Format author string
                if authors:
                    if len(authors) > 3:
                        author_str = f"{authors[0]} et al."
                    else:
                        author_str = ", ".join(authors)
                else:
                    author_str = article.get("author_string", "Unknown authors")
                
                # Status indicators
                indicators = []
                if article.get("is_open_access"):
                    indicators.append("🔓 OA")
                if article.get("has_fulltext"):
                    indicators.append("📄 Fulltext")
                if article.get("citation_count"):
                    indicators.append(f"📊 {article['citation_count']} cites")
                
                output += f"**{i}. [{pmid}]** {title}\n"
                output += f"   👤 {author_str} | 📅 {year} | 📰 {journal}\n"
                if pmc_id:
                    output += f"   🆔 PMC: {pmc_id}"
                if indicators:
                    output += f" | {' | '.join(indicators)}"
                output += "\n"
                
                # Abstract preview
                abstract = article.get("abstract", "")
                if abstract:
                    preview = abstract[:200] + "..." if len(abstract) > 200 else abstract
                    output += f"   📝 {preview}\n"
                
                output += "\n"
            
            # Add fulltext hint
            fulltext_available = [a for a in articles if a.get("has_fulltext") or a.get("pmc_id")]
            if fulltext_available:
                pmc_ids = [a.get("pmc_id") for a in fulltext_available[:3] if a.get("pmc_id")]
                if pmc_ids:
                    output += "---\n"
                    output += f"💡 **Tip**: Use `get_fulltext(pmcid='{pmc_ids[0]}')` to read the full paper\n"
            
            return output
            
        except Exception as e:
            logger.error(f"Europe PMC search failed: {e}")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check query syntax and try again",
                tool_name="search_europe_pmc"
            )

    @mcp.tool()
    def get_fulltext(
        pmcid: Union[str, int],
        sections: Optional[str] = None,
    ) -> str:
        """
        Get parsed fulltext content from Europe PMC.
        
        Returns structured fulltext with sections (Introduction, Methods, Results, etc.).
        Only works for articles available in PubMed Central (PMC).
        
        Args:
            pmcid: PubMed Central ID (accepts: "PMC7096777", "7096777", 7096777).
            sections: Comma-separated section names to include (e.g., "introduction,methods").
                      If not specified, returns all sections.
                      Common sections: introduction, methods, results, discussion, conclusion.
            
        Returns:
            Structured fulltext with title, sections, and references.
        """
        # Phase 2.1: Input normalization
        pmcid_normalized = InputNormalizer.normalize_pmcid(str(pmcid) if pmcid else None)
        if not pmcid_normalized:
            return ResponseFormatter.error(
                error="Invalid PMC ID format",
                suggestion="Provide a valid PMC ID number",
                example='get_fulltext(pmcid="PMC7096777")',
                tool_name="get_fulltext"
            )
        
        logger.info(f"Getting fulltext for: {pmcid_normalized}")
        
        try:
            client = get_europe_pmc_client()
            
            # Get XML
            xml = client.get_fulltext_xml(pmcid_normalized)
            if not xml:
                return ResponseFormatter.no_results(
                    query=pmcid_normalized,
                    suggestions=[
                        "Article may not be in PMC",
                        "Article may not be open access",
                        "Try get_article_fulltext_links to check availability"
                    ]
                )
            
            # Parse XML
            parsed = client.parse_fulltext_xml(xml)
            if not parsed:
                return f"Failed to parse fulltext for {pmcid_normalized}."
            
            # Format output
            output = f"📖 **Fulltext: {parsed.get('title', 'Unknown Title')}**\n"
            output += f"🆔 {pmcid_normalized}\n\n"
            
            # Filter sections if requested
            all_sections = parsed.get("sections", [])
            if sections:
                requested = [s.strip().lower() for s in sections.split(",")]
                filtered_sections = []
                for sec in all_sections:
                    sec_title = sec.get("title", "").lower()
                    # Match partial names (e.g., "intro" matches "introduction")
                    if any(req in sec_title or sec_title in req for req in requested):
                        filtered_sections.append(sec)
                all_sections = filtered_sections
            
            if not all_sections:
                # If no sections found, return raw content summary
                output += "⚠️ No structured sections found. Article may have different structure.\n\n"
                # Try to show any content we have
                if parsed.get("abstract"):
                    output += f"**Abstract**\n{parsed['abstract']}\n\n"
            else:
                # Format sections
                for sec in all_sections:
                    title = sec.get("title", "Untitled Section")
                    content = sec.get("content", "")
                    
                    if content:
                        output += f"## {title}\n\n"
                        # Truncate very long sections
                        if len(content) > 5000:
                            output += content[:5000]
                            output += f"\n\n... _{len(content) - 5000} characters truncated_\n\n"
                        else:
                            output += content + "\n\n"
            
            # Add reference count
            refs = parsed.get("references", [])
            if refs:
                output += f"---\n📚 **References**: {len(refs)} citations\n"
            
            return output
            
        except Exception as e:
            logger.error(f"Get fulltext failed: {e}")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check if the PMC ID is correct and the article is open access",
                tool_name="get_fulltext"
            )

    @mcp.tool()
    def get_fulltext_xml(pmcid: Union[str, int]) -> str:
        """
        Get raw JATS XML fulltext from Europe PMC.
        
        Returns the complete XML document in JATS format. Use this if you need
        the raw XML structure for custom parsing or analysis.
        
        Args:
            pmcid: PubMed Central ID (accepts: "PMC7096777", "7096777", 7096777).
            
        Returns:
            JATS XML document as string, or error message.
        """
        # Phase 2.1: Input normalization
        pmcid_normalized = InputNormalizer.normalize_pmcid(str(pmcid) if pmcid else None)
        if not pmcid_normalized:
            return ResponseFormatter.error(
                error="Invalid PMC ID format",
                suggestion="Provide a valid PMC ID number",
                example='get_fulltext_xml(pmcid="PMC7096777")',
                tool_name="get_fulltext_xml"
            )
        
        logger.info(f"Getting fulltext XML for: {pmcid_normalized}")
        
        try:
            client = get_europe_pmc_client()
            
            xml = client.get_fulltext_xml(pmcid_normalized)
            if not xml:
                return ResponseFormatter.no_results(
                    query=pmcid_normalized,
                    suggestions=[
                        "Article may not be in PMC",
                        "Article may not be open access"
                    ]
                )
            
            # Return with size info
            output = f"<!-- JATS XML for {pmcid_normalized} ({len(xml):,} bytes) -->\n\n"
            
            # Truncate if very large
            if len(xml) > 50000:
                output += xml[:50000]
                output += f"\n\n<!-- ... {len(xml) - 50000:,} bytes truncated -->"
            else:
                output += xml
            
            return output
            
        except Exception as e:
            logger.error(f"Get fulltext XML failed: {e}")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check if the PMC ID is correct",
                tool_name="get_fulltext_xml"
            )

    @mcp.tool()
    def get_text_mined_terms(
        pmid: Optional[Union[str, int]] = None,
        pmcid: Optional[Union[str, int]] = None,
        semantic_type: Optional[str] = None,
    ) -> str:
        """
        Get text-mined annotations from Europe PMC.
        
        Returns entities extracted from the article text including genes, diseases,
        chemicals, organisms, and more. Useful for identifying key concepts.
        
        Args:
            pmid: PubMed ID of the article (accepts: "12345678", 12345678).
            pmcid: PMC ID (alternative to PMID, accepts: "PMC7096777", "7096777").
            semantic_type: Filter by entity type. Options:
                - "GENE_PROTEIN": Genes and proteins
                - "DISEASE": Diseases and conditions  
                - "CHEMICAL": Drugs and chemicals
                - "ORGANISM": Species and organisms
                - "GO_TERM": Gene Ontology terms
                - None: Return all types (default)
            
        Returns:
            List of text-mined entities with counts and sections.
        """
        # Phase 2.1: Input normalization
        normalized_pmid = InputNormalizer.normalize_pmid_single(pmid) if pmid else None
        normalized_pmcid = InputNormalizer.normalize_pmcid(str(pmcid)) if pmcid else None
        
        logger.info(f"Getting text-mined terms for PMID={normalized_pmid}, PMCID={normalized_pmcid}")
        
        try:
            if not normalized_pmid and not normalized_pmcid:
                return ResponseFormatter.error(
                    error="Either pmid or pmcid is required",
                    suggestion="Provide a PMID or PMC ID",
                    example='get_text_mined_terms(pmid="12345678")',
                    tool_name="get_text_mined_terms"
                )
            
            client = get_europe_pmc_client()
            
            # Determine source and ID
            if normalized_pmid:
                source = "MED"
                article_id = normalized_pmid
            else:
                source = "PMC"
                # Extract digits from normalized PMCID (PMC7096777 -> 7096777)
                if normalized_pmcid and normalized_pmcid.startswith("PMC"):
                    article_id = normalized_pmcid[3:]
                else:
                    article_id = normalized_pmcid or ""
            
            terms = client.get_text_mined_terms(source, str(article_id), semantic_type)
            
            if not terms:
                id_str = f"PMID:{normalized_pmid}" if normalized_pmid else f"PMC:{normalized_pmcid}"
                return ResponseFormatter.no_results(
                    query=id_str,
                    suggestions=[
                        "Article may not have text-mining data",
                        "Try a different article"
                    ]
                )
            
            # Group by semantic type
            by_type: Dict[str, List[Dict[str, Any]]] = {}
            for term in terms:
                term_type = term.get("semantic_type", "OTHER")
                if term_type not in by_type:
                    by_type[term_type] = []
                by_type[term_type].append(term)
            
            # Format output
            id_str = f"PMID:{pmid}" if pmid else f"PMC:{pmcid}"
            output = f"🔬 **Text-Mined Terms for {id_str}**\n\n"
            output += f"Total: {len(terms)} annotations\n\n"
            
            # Type emoji mapping
            type_emoji = {
                "GENE_PROTEIN": "🧬",
                "DISEASE": "🏥",
                "CHEMICAL": "💊",
                "ORGANISM": "🦠",
                "GO_TERM": "📋",
                "EFO": "🔬",
            }
            
            for term_type, type_terms in sorted(by_type.items()):
                emoji = type_emoji.get(term_type, "📌")
                output += f"### {emoji} {term_type} ({len(type_terms)})\n\n"
                
                # Deduplicate and count
                term_counts: Dict[str, int] = {}
                for t in type_terms:
                    name = t.get("term", t.get("name", "Unknown"))
                    term_counts[name] = term_counts.get(name, 0) + 1
                
                # Sort by frequency
                sorted_terms = sorted(term_counts.items(), key=lambda x: x[1], reverse=True)
                
                # Show top 10 per type
                for name, count in sorted_terms[:10]:
                    output += f"- **{name}**"
                    if count > 1:
                        output += f" (×{count})"
                    output += "\n"
                
                if len(sorted_terms) > 10:
                    output += f"- _...and {len(sorted_terms) - 10} more_\n"
                
                output += "\n"
            
            return output
            
        except Exception as e:
            logger.error(f"Get text-mined terms failed: {e}")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check the ID and try again",
                tool_name="get_text_mined_terms"
            )

    @mcp.tool()
    def get_europe_pmc_citations(
        pmid: Optional[Union[str, int]] = None,
        pmcid: Optional[Union[str, int]] = None,
        direction: str = "citing",
        limit: int = 20,
    ) -> str:
        """
        Get citation network from Europe PMC.
        
        Can retrieve either articles that cite this paper (forward) or
        references this paper cites (backward).
        
        Args:
            pmid: PubMed ID of the source article (accepts: "12345678", 12345678).
            pmcid: PMC ID (alternative to PMID, accepts: "PMC7096777", "7096777").
            direction: Citation direction:
                - "citing": Papers that cite this article (forward in time, default)
                - "references": Papers this article cites (backward, its bibliography)
            limit: Maximum number of results (1-100, default: 20).
            
        Returns:
            List of citing or referenced articles.
        """
        # Phase 2.1: Input normalization
        normalized_pmid = InputNormalizer.normalize_pmid_single(pmid) if pmid else None
        normalized_pmcid = InputNormalizer.normalize_pmcid(str(pmcid)) if pmcid else None
        normalized_limit = InputNormalizer.normalize_limit(limit, default=20, min_val=1, max_val=100)
        
        logger.info(f"Getting {direction} for PMID={normalized_pmid}, PMCID={normalized_pmcid}")
        
        try:
            if not normalized_pmid and not normalized_pmcid:
                return ResponseFormatter.error(
                    error="Either pmid or pmcid is required",
                    suggestion="Provide a PMID or PMC ID",
                    example='get_europe_pmc_citations(pmid="12345678")',
                    tool_name="get_europe_pmc_citations"
                )
            
            client = get_europe_pmc_client()
            
            # Determine source and ID
            if normalized_pmid:
                source = "MED"
                article_id = normalized_pmid
            else:
                source = "PMC"
                if normalized_pmcid and normalized_pmcid.startswith("PMC"):
                    article_id = normalized_pmcid[3:]
                else:
                    article_id = normalized_pmcid or ""
            
            # Get citations or references
            if direction == "references":
                results = client.get_references(source, str(article_id), limit=normalized_limit)
                direction_label = "References (Bibliography)"
                direction_desc = "papers cited BY this article"
            else:
                results = client.get_citations(source, str(article_id), limit=normalized_limit)
                direction_label = "Citing Articles"
                direction_desc = "papers that cite this article"
            
            if not results:
                id_str = f"PMID:{normalized_pmid}" if normalized_pmid else f"PMC:{normalized_pmcid}"
                return ResponseFormatter.no_results(
                    query=id_str,
                    suggestions=[
                        f"Article may have no {direction}",
                        "Try find_citing_articles or get_article_references for PubMed data"
                    ]
                )
            
            # Format output
            id_str = f"PMID:{pmid}" if pmid else f"PMC:{pmcid}"
            output = f"📖 **{direction_label} for {id_str}**\n"
            output += f"Found **{len(results)}** {direction_desc}\n\n"
            
            # Format results
            for i, article in enumerate(results, 1):
                title = article.get("title", "No title")
                authors = article.get("authors", [])
                year = article.get("year", article.get("pub_year", ""))
                journal = article.get("journal", "")
                ref_pmid = article.get("pmid", "")
                doi = article.get("doi", "")
                
                # Author string
                if authors:
                    if len(authors) > 2:
                        author_str = f"{authors[0]} et al."
                    else:
                        author_str = ", ".join(authors)
                else:
                    author_str = article.get("author_string", "Unknown")
                
                output += f"**{i}.** {title}\n"
                output += f"   👤 {author_str} | 📅 {year}"
                if journal:
                    output += f" | 📰 {journal}"
                output += "\n"
                
                ids = []
                if ref_pmid:
                    ids.append(f"PMID:{ref_pmid}")
                if doi:
                    ids.append(f"DOI:{doi}")
                if ids:
                    output += f"   🔗 {' | '.join(ids)}\n"
                
                output += "\n"
            
            return output
            
        except Exception as e:
            logger.error(f"Get Europe PMC citations failed: {e}")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check the ID and direction parameter",
                tool_name="get_europe_pmc_citations"
            )
