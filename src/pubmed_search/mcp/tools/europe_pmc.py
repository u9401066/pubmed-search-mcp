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
"""

import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ...sources import get_europe_pmc_client
from ._common import format_search_results

logger = logging.getLogger(__name__)


def register_europe_pmc_tools(mcp: FastMCP):
    """Register Europe PMC tools for fulltext access and search."""
    
    @mcp.tool()
    def search_europe_pmc(
        query: str,
        limit: int = 10,
        min_year: int = None,
        max_year: int = None,
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
            limit: Maximum number of results (default 10, max 1000).
            min_year: Filter by minimum publication year.
            max_year: Filter by maximum publication year.
            open_access_only: Only return open access papers.
            has_fulltext: Only return papers with fulltext available in Europe PMC.
            sort: Sort order - "relevance" (default), "date" (newest first), or "cited" (most cited).
            
        Returns:
            Search results with titles, abstracts, and fulltext availability.
        """
        logger.info(f"Searching Europe PMC: query='{query}', limit={limit}")
        
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
                query=query,
                limit=limit,
                min_year=min_year,
                max_year=max_year,
                open_access_only=open_access_only,
                has_fulltext=has_fulltext,
                sort=sort_param,
            )
            
            if not result.get("results"):
                return f"No results found in Europe PMC for '{query}'."
            
            total = result.get("hit_count", len(result["results"]))
            articles = result["results"]
            
            # Format header
            output = f"📚 **Europe PMC Search Results**\n"
            output += f"Found **{len(articles)}** results"
            if total > len(articles):
                output += f" (of {total:,} total)"
            
            filters = []
            if open_access_only:
                filters.append("Open Access")
            if has_fulltext:
                filters.append("Fulltext available")
            if min_year or max_year:
                year_range = f"{min_year or '...'}-{max_year or '...'}"
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
            return f"Error searching Europe PMC: {e}"

    @mcp.tool()
    def get_fulltext(
        pmcid: str,
        sections: str = None,
    ) -> str:
        """
        Get parsed fulltext content from Europe PMC.
        
        Returns structured fulltext with sections (Introduction, Methods, Results, etc.).
        Only works for articles available in PubMed Central (PMC).
        
        Args:
            pmcid: PubMed Central ID (e.g., "PMC7096777" or just "7096777").
            sections: Comma-separated section names to include (e.g., "introduction,methods").
                      If not specified, returns all sections.
                      Common sections: introduction, methods, results, discussion, conclusion.
            
        Returns:
            Structured fulltext with title, sections, and references.
        """
        logger.info(f"Getting fulltext for: {pmcid}")
        
        try:
            client = get_europe_pmc_client()
            
            # Normalize PMCID
            pmcid_normalized = pmcid.strip()
            if not pmcid_normalized.upper().startswith("PMC"):
                pmcid_normalized = f"PMC{pmcid_normalized}"
            
            # Get XML
            xml = client.get_fulltext_xml(pmcid_normalized)
            if not xml:
                return f"Fulltext not available for {pmcid_normalized}. The article may not be in PMC or not open access."
            
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
            return f"Error getting fulltext: {e}"

    @mcp.tool()
    def get_fulltext_xml(pmcid: str) -> str:
        """
        Get raw JATS XML fulltext from Europe PMC.
        
        Returns the complete XML document in JATS format. Use this if you need
        the raw XML structure for custom parsing or analysis.
        
        Args:
            pmcid: PubMed Central ID (e.g., "PMC7096777" or just "7096777").
            
        Returns:
            JATS XML document as string, or error message.
        """
        logger.info(f"Getting fulltext XML for: {pmcid}")
        
        try:
            client = get_europe_pmc_client()
            
            # Normalize PMCID
            pmcid_normalized = pmcid.strip()
            if not pmcid_normalized.upper().startswith("PMC"):
                pmcid_normalized = f"PMC{pmcid_normalized}"
            
            xml = client.get_fulltext_xml(pmcid_normalized)
            if not xml:
                return f"Fulltext XML not available for {pmcid_normalized}."
            
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
            return f"Error getting fulltext XML: {e}"

    @mcp.tool()
    def get_text_mined_terms(
        pmid: str = None,
        pmcid: str = None,
        semantic_type: str = None,
    ) -> str:
        """
        Get text-mined annotations from Europe PMC.
        
        Returns entities extracted from the article text including genes, diseases,
        chemicals, organisms, and more. Useful for identifying key concepts.
        
        Args:
            pmid: PubMed ID of the article.
            pmcid: PMC ID (alternative to PMID, use one or the other).
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
        logger.info(f"Getting text-mined terms for PMID={pmid}, PMCID={pmcid}")
        
        try:
            if not pmid and not pmcid:
                return "Please provide either pmid or pmcid."
            
            client = get_europe_pmc_client()
            
            # Determine source and ID
            if pmid:
                source = "MED"
                article_id = pmid
            else:
                source = "PMC"
                # Normalize PMCID
                article_id = pmcid.strip()
                if article_id.upper().startswith("PMC"):
                    article_id = article_id[3:]
            
            terms = client.get_text_mined_terms(source, article_id, semantic_type)
            
            if not terms:
                return f"No text-mined terms found for {source}:{article_id}."
            
            # Group by semantic type
            by_type = {}
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
                term_counts = {}
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
            return f"Error getting text-mined terms: {e}"

    @mcp.tool()
    def get_europe_pmc_citations(
        pmid: str = None,
        pmcid: str = None,
        direction: str = "citing",
        limit: int = 20,
    ) -> str:
        """
        Get citation network from Europe PMC.
        
        Can retrieve either articles that cite this paper (forward) or
        references this paper cites (backward).
        
        Args:
            pmid: PubMed ID of the source article.
            pmcid: PMC ID (alternative to PMID).
            direction: Citation direction:
                - "citing": Papers that cite this article (forward in time, default)
                - "references": Papers this article cites (backward, its bibliography)
            limit: Maximum number of results (default 20).
            
        Returns:
            List of citing or referenced articles.
        """
        logger.info(f"Getting {direction} for PMID={pmid}, PMCID={pmcid}")
        
        try:
            if not pmid and not pmcid:
                return "Please provide either pmid or pmcid."
            
            client = get_europe_pmc_client()
            
            # Determine source and ID
            if pmid:
                source = "MED"
                article_id = pmid
            else:
                source = "PMC"
                article_id = pmcid.strip()
                if article_id.upper().startswith("PMC"):
                    article_id = article_id[3:]
            
            # Get citations or references
            if direction == "references":
                results = client.get_references(source, article_id, limit=limit)
                direction_label = "References (Bibliography)"
                direction_desc = "papers cited BY this article"
            else:
                results = client.get_citations(source, article_id, limit=limit)
                direction_label = "Citing Articles"
                direction_desc = "papers that cite this article"
            
            if not results:
                return f"No {direction} found for {source}:{article_id}."
            
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
            return f"Error getting citations: {e}"
