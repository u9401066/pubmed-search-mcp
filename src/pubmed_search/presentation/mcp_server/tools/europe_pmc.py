"""
Europe PMC Tools - Access Europe PMC for fulltext and search.

Tools:
- get_fulltext: 🔥 Enhanced multi-source fulltext retrieval
  - Supports PMID, PMC ID, or DOI input
  - Auto-tries: Europe PMC → Unpaywall → CORE
  - Extended sources: CrossRef, DOAJ, Zenodo, PubMed LinkOut (15 total)
  - Returns fulltext content + PDF links
- get_text_mined_terms: Get text-mined annotations (genes, diseases, chemicals)

Internal (not registered):
- search_europe_pmc: Use unified_search instead
- get_fulltext_xml: Use get_fulltext instead
- get_europe_pmc_citations: Use find_citing_articles instead

Phase 2.2 Updates (v0.1.21):
- Multi-source fulltext: Europe PMC, Unpaywall, CORE
- Flexible input: PMID, PMC ID, or DOI
- PDF link aggregation from all sources

Phase 3 Updates (v0.2.8):
- Extended sources via FulltextDownloader (15 total sources)
- CrossRef, DOAJ, Zenodo, PubMed LinkOut integration
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union

from mcp.server.fastmcp import FastMCP

from pubmed_search.infrastructure.sources import get_europe_pmc_client
from pubmed_search.infrastructure.sources.core import get_core_client
from pubmed_search.infrastructure.sources.unpaywall import get_unpaywall_client

from ._common import InputNormalizer, ResponseFormatter

logger = logging.getLogger(__name__)


def register_europe_pmc_tools(mcp: FastMCP):
    """
    Register Europe PMC tools for fulltext access and text mining.

    Note: search_europe_pmc is NOT registered - use unified_search instead.
    Only registers:
    - get_fulltext: Get parsed fulltext content
    - get_text_mined_terms: Get text-mined annotations
    """

    # NOTE: search_europe_pmc is NOT registered as a tool.
    # Use unified_search(sources=["europe_pmc"]) instead.
    # Keeping the function for internal use by unified_search.
    # @mcp.tool()  # REMOVED - integrated into unified_search
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
                tool_name="search_europe_pmc",
            )

        normalized_limit = InputNormalizer.normalize_limit(
            limit, default=10, min_val=1, max_val=100
        )
        normalized_min_year = InputNormalizer.normalize_year(min_year)
        normalized_max_year = InputNormalizer.normalize_year(max_year)
        normalized_oa_only = InputNormalizer.normalize_bool(
            open_access_only, default=False
        )
        normalized_fulltext = InputNormalizer.normalize_bool(
            has_fulltext, default=False
        )

        logger.info(
            f"Searching Europe PMC: query='{normalized_query}', limit={normalized_limit}"
        )

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
                        "Try search_literature for PubMed instead",
                    ],
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
                year_range = (
                    f"{normalized_min_year or '...'}-{normalized_max_year or '...'}"
                )
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
                    preview = (
                        abstract[:200] + "..." if len(abstract) > 200 else abstract
                    )
                    output += f"   📝 {preview}\n"

                output += "\n"

            # Add fulltext hint
            fulltext_available = [
                a for a in articles if a.get("has_fulltext") or a.get("pmc_id")
            ]
            if fulltext_available:
                pmc_ids = [
                    a.get("pmc_id") for a in fulltext_available[:3] if a.get("pmc_id")
                ]
                if pmc_ids:
                    output += "---\n"
                    output += f"💡 **Tip**: Use `get_fulltext(pmcid='{pmc_ids[0]}')` to read the full paper\n"

            return output

        except Exception as e:
            logger.error(f"Europe PMC search failed: {e}")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check query syntax and try again",
                tool_name="search_europe_pmc",
            )

    @mcp.tool()
    def get_fulltext(
        identifier: Optional[str] = None,
        pmcid: Optional[Union[str, int]] = None,
        pmid: Optional[Union[str, int]] = None,
        doi: Optional[str] = None,
        sections: Optional[str] = None,
        include_pdf_links: bool = True,
        extended_sources: bool = False,
    ) -> str:
        """
        🔥 Enhanced multi-source fulltext retrieval.

        Automatically tries multiple sources to find the best fulltext:
        1. Europe PMC (if PMC ID available)
        2. Unpaywall (finds OA versions via DOI)
        3. CORE (200M+ open access papers)

        With extended_sources=True, also searches:
        4. CrossRef (publisher links)
        5. DOAJ (Gold OA journals)
        6. Zenodo (research repository)
        7. PubMed LinkOut (external providers)
        8. Semantic Scholar, OpenAlex, arXiv, bioRxiv, medRxiv

        Accepts flexible input - provide ANY ONE of:
        - identifier: Auto-detects PMID, PMC ID, or DOI
        - pmcid: Direct PMC ID
        - pmid: PubMed ID (will lookup PMC ID)
        - doi: DOI (will search Unpaywall/CORE)

        Args:
            identifier: Auto-detect format - PMID, PMC ID, or DOI
                       Examples: "PMC7096777", "12345678", "10.1001/jama.2024.1234"
            pmcid: PubMed Central ID (e.g., "PMC7096777", "7096777")
            pmid: PubMed ID (e.g., "12345678")
            doi: DOI (e.g., "10.1001/jama.2024.1234")
            sections: Filter sections (e.g., "introduction,methods,results")
            include_pdf_links: Include PDF download links (default: True)
            extended_sources: Search 15 sources instead of 3 (default: False)

        Returns:
            Fulltext content with PDF links from all available sources.

        Example:
            get_fulltext(identifier="PMC7096777")
            get_fulltext(doi="10.1038/s41586-021-03819-2")
            get_fulltext(pmid="12345678", extended_sources=True)
        """

        # Phase 2.2: Smart identifier detection
        detected_pmcid = pmcid
        detected_doi = doi
        detected_pmid = pmid

        if identifier:
            identifier = str(identifier).strip()
            # Detect format
            if identifier.upper().startswith("PMC") or (
                identifier.isdigit() and len(identifier) > 6
            ):
                if identifier.upper().startswith("PMC"):
                    detected_pmcid = identifier
                else:
                    # Could be PMID or PMC number - assume PMID if < 8 digits
                    if len(identifier) <= 8:
                        detected_pmid = identifier
                    else:
                        detected_pmcid = f"PMC{identifier}"
            elif identifier.startswith("10.") or "doi.org" in identifier:
                # DOI format
                detected_doi = identifier.replace("https://doi.org/", "").replace(
                    "http://doi.org/", ""
                )
            elif identifier.isdigit():
                detected_pmid = identifier
            else:
                # Try as PMID
                detected_pmid = identifier

        # Normalize inputs
        if detected_pmcid:
            detected_pmcid = InputNormalizer.normalize_pmcid(str(detected_pmcid))
        if detected_pmid:
            detected_pmid = InputNormalizer.normalize_pmid_single(detected_pmid)

        if not any([detected_pmcid, detected_pmid, detected_doi]):
            return ResponseFormatter.error(
                error="No valid identifier provided",
                suggestion="Provide pmcid, pmid, doi, or auto-detect identifier",
                example='get_fulltext(identifier="PMC7096777") or get_fulltext(doi="10.1038/...")',
                tool_name="get_fulltext",
            )

        logger.info(
            f"Getting fulltext: pmcid={detected_pmcid}, pmid={detected_pmid}, doi={detected_doi}"
        )

        # Collect results from all sources
        fulltext_content = None
        pdf_links: List[Dict[str, Any]] = []
        sources_tried = []
        article_title = None

        # === SOURCE 1: Europe PMC (best for structured fulltext) ===
        if detected_pmcid:
            sources_tried.append("Europe PMC")
            try:
                client = get_europe_pmc_client()
                xml = client.get_fulltext_xml(detected_pmcid)
                if xml:
                    parsed = client.parse_fulltext_xml(xml)
                    if parsed:
                        fulltext_content = _format_sections(parsed, sections)
                        article_title = parsed.get("title")
                        # Add PMC PDF link
                        pmc_num = detected_pmcid.replace("PMC", "")
                        pdf_links.append(
                            {
                                "source": "PubMed Central",
                                "url": f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_num}/pdf/",
                                "type": "pdf",
                                "access": "open_access",
                            }
                        )
            except Exception as e:
                logger.warning(f"Europe PMC failed: {e}")

        # === SOURCE 2: Unpaywall (best for finding OA via DOI) ===
        if detected_doi:
            sources_tried.append("Unpaywall")
            try:
                unpaywall = get_unpaywall_client()
                oa_info = unpaywall.get_oa_status(detected_doi)
                if oa_info and oa_info.get("is_oa"):
                    # Get title if we don't have it
                    if not article_title:
                        article_title = oa_info.get("title")

                    # Collect all OA links
                    best_loc = oa_info.get("best_oa_location", {})
                    if best_loc:
                        if best_loc.get("url_for_pdf"):
                            pdf_links.append(
                                {
                                    "source": f"Unpaywall ({best_loc.get('host_type', 'unknown')})",
                                    "url": best_loc["url_for_pdf"],
                                    "type": "pdf",
                                    "access": oa_info.get("oa_status", "open_access"),
                                    "version": best_loc.get("version", "unknown"),
                                    "license": best_loc.get("license"),
                                }
                            )
                        elif best_loc.get("url"):
                            pdf_links.append(
                                {
                                    "source": f"Unpaywall ({best_loc.get('host_type', 'unknown')})",
                                    "url": best_loc["url"],
                                    "type": "landing_page",
                                    "access": oa_info.get("oa_status", "open_access"),
                                }
                            )

                    # Add alternative locations
                    for loc in oa_info.get("oa_locations", [])[:3]:  # Top 3
                        if loc != best_loc and loc.get("url_for_pdf"):
                            pdf_links.append(
                                {
                                    "source": f"Unpaywall ({loc.get('host_type', 'repository')})",
                                    "url": loc["url_for_pdf"],
                                    "type": "pdf",
                                    "access": "alternative",
                                    "version": loc.get("version"),
                                }
                            )
            except Exception as e:
                logger.warning(f"Unpaywall failed: {e}")

        # === SOURCE 3: CORE (200M+ open access papers) ===
        if detected_doi and not fulltext_content:
            sources_tried.append("CORE")
            try:
                core = get_core_client()
                # Search by DOI
                results = core.search(f'doi:"{detected_doi}"', limit=1)
                if results and results.get("results"):
                    work = results["results"][0]
                    if not article_title:
                        article_title = work.get("title")

                    # Get fulltext if available
                    if work.get("fullText"):
                        fulltext_content = _format_core_fulltext(work, sections)

                    # Add download links
                    if work.get("downloadUrl"):
                        pdf_links.append(
                            {
                                "source": "CORE",
                                "url": work["downloadUrl"],
                                "type": "pdf",
                                "access": "open_access",
                            }
                        )
                    if work.get("sourceFulltextUrls"):
                        for url in work["sourceFulltextUrls"][:2]:
                            pdf_links.append(
                                {
                                    "source": "CORE (source)",
                                    "url": url,
                                    "type": "fulltext",
                                    "access": "open_access",
                                }
                            )
            except Exception as e:
                logger.warning(f"CORE failed: {e}")

        # === EXTENDED SOURCES (15 total) ===
        if extended_sources:
            sources_tried.append("Extended (15 sources)")
            try:
                from pubmed_search.infrastructure.sources.fulltext_download import (
                    FulltextDownloader,
                )

                # Ensure string types for downloader
                pmid_str = str(detected_pmid) if detected_pmid else None
                pmcid_str = str(detected_pmcid) if detected_pmcid else None
                doi_str = str(detected_doi) if detected_doi else None

                async def _get_extended_links():
                    downloader = FulltextDownloader()
                    try:
                        return await downloader.get_pdf_links(
                            pmid=pmid_str,
                            pmcid=pmcid_str,
                            doi=doi_str,
                        )
                    finally:
                        await downloader.close()

                # Run async function in sync context
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop and loop.is_running():
                    # Already in async context - create task
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(asyncio.run, _get_extended_links())
                        extended_links = future.result(timeout=30)
                else:
                    extended_links = asyncio.run(_get_extended_links())

                # Merge extended links (avoid duplicates)
                seen_urls = {link["url"] for link in pdf_links}
                for ext_link in extended_links:
                    if ext_link.url not in seen_urls:
                        seen_urls.add(ext_link.url)
                        pdf_links.append({
                            "source": ext_link.source.display_name,
                            "url": ext_link.url,
                            "type": "pdf" if ext_link.is_direct_pdf else "landing_page",
                            "access": ext_link.access_type,
                            "version": ext_link.version,
                            "license": ext_link.license,
                        })

                logger.info(f"Extended sources found {len(extended_links)} additional links")
            except Exception as e:
                logger.warning(f"Extended sources failed: {e}")

        # === BUILD OUTPUT ===
        if not fulltext_content and not pdf_links:
            return ResponseFormatter.no_results(
                query=f"pmcid={detected_pmcid}, pmid={detected_pmid}, doi={detected_doi}",
                suggestions=[
                    "Article may not be open access",
                    "Try searching with DOI for Unpaywall lookup",
                    "Check if article is available in PubMed Central",
                    f"Sources tried: {', '.join(sources_tried)}",
                ],
            )

        # Format output
        output = f"📖 **{article_title or 'Fulltext Retrieved'}**\n"
        output += f"🔍 Sources checked: {', '.join(sources_tried)}\n\n"

        # PDF Links section
        if pdf_links and include_pdf_links:
            output += "## 📥 PDF/Fulltext Links\n\n"
            # Deduplicate by URL
            seen_urls = set()
            for link in pdf_links:
                if link["url"] not in seen_urls:
                    seen_urls.add(link["url"])
                    icon = "📄" if link["type"] == "pdf" else "🔗"
                    access_badge = {
                        "gold": "🥇 Gold OA",
                        "green": "🟢 Green OA",
                        "hybrid": "🔶 Hybrid",
                        "bronze": "🟤 Bronze",
                        "open_access": "🔓 Open Access",
                        "alternative": "📋 Alternative",
                    }.get(link.get("access", ""), "")

                    output += f"- {icon} **{link['source']}** {access_badge}\n"
                    output += f"  {link['url']}\n"
                    if link.get("version"):
                        output += f"  _Version: {link['version']}_\n"
                    if link.get("license"):
                        output += f"  _License: {link['license']}_\n"
            output += "\n"

        # Fulltext content
        if fulltext_content:
            output += "## 📝 Content\n\n"
            output += fulltext_content
        elif pdf_links:
            output += "_Structured fulltext not available. Use the PDF links above to access the article._\n"

        return output

    def _format_sections(parsed: Dict[str, Any], sections_filter: Optional[str]) -> str:
        """Format parsed Europe PMC sections."""
        all_sections = parsed.get("sections", [])

        if sections_filter:
            requested = [s.strip().lower() for s in sections_filter.split(",")]
            filtered = []
            for sec in all_sections:
                sec_title = sec.get("title", "").lower()
                if any(req in sec_title or sec_title in req for req in requested):
                    filtered.append(sec)
            all_sections = filtered

        if not all_sections:
            if parsed.get("abstract"):
                return f"**Abstract**\n{parsed['abstract']}\n\n"
            return ""

        output = ""
        for sec in all_sections:
            title = sec.get("title", "Untitled Section")
            content = sec.get("content", "")
            if content:
                output += f"### {title}\n\n"
                if len(content) > 5000:
                    output += content[:5000]
                    output += (
                        f"\n\n_... {len(content) - 5000} characters truncated_\n\n"
                    )
                else:
                    output += content + "\n\n"

        refs = parsed.get("references", [])
        if refs:
            output += f"---\n📚 **References**: {len(refs)} citations\n"

        return output

    def _format_core_fulltext(
        work: Dict[str, Any], sections_filter: Optional[str]
    ) -> str:
        """Format CORE fulltext."""
        fulltext = work.get("fullText", "")
        if not fulltext:
            return ""

        # CORE fulltext is usually plain text, not structured
        if sections_filter:
            # Try to extract requested sections by searching for keywords
            output = ""
            for section in sections_filter.split(","):
                section = section.strip().lower()
                # Simple section extraction (CORE doesn't have structured sections)
                # Just show that we have content
                if section in fulltext.lower():
                    output += f"_Contains '{section}' section_\n"
            if output:
                output += "\n"

        # Truncate if too long
        if len(fulltext) > 10000:
            return (
                fulltext[:10000]
                + f"\n\n_... {len(fulltext) - 10000} characters truncated_"
            )
        return fulltext

    # NOTE: get_fulltext_xml is NOT registered as a tool.
    # Use get_fulltext instead - it provides better parsed output.
    # @mcp.tool()  # REMOVED - use get_fulltext instead
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
        pmcid_normalized = InputNormalizer.normalize_pmcid(
            str(pmcid) if pmcid else None
        )
        if not pmcid_normalized:
            return ResponseFormatter.error(
                error="Invalid PMC ID format",
                suggestion="Provide a valid PMC ID number",
                example='get_fulltext_xml(pmcid="PMC7096777")',
                tool_name="get_fulltext_xml",
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
                        "Article may not be open access",
                    ],
                )

            # Return with size info
            output = (
                f"<!-- JATS XML for {pmcid_normalized} ({len(xml):,} bytes) -->\n\n"
            )

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
                tool_name="get_fulltext_xml",
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
        normalized_pmcid = (
            InputNormalizer.normalize_pmcid(str(pmcid)) if pmcid else None
        )

        logger.info(
            f"Getting text-mined terms for PMID={normalized_pmid}, PMCID={normalized_pmcid}"
        )

        try:
            if not normalized_pmid and not normalized_pmcid:
                return ResponseFormatter.error(
                    error="Either pmid or pmcid is required",
                    suggestion="Provide a PMID or PMC ID",
                    example='get_text_mined_terms(pmid="12345678")',
                    tool_name="get_text_mined_terms",
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
                id_str = (
                    f"PMID:{normalized_pmid}"
                    if normalized_pmid
                    else f"PMC:{normalized_pmcid}"
                )
                return ResponseFormatter.no_results(
                    query=id_str,
                    suggestions=[
                        "Article may not have text-mining data",
                        "Try a different article",
                    ],
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
                sorted_terms = sorted(
                    term_counts.items(), key=lambda x: x[1], reverse=True
                )

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
                tool_name="get_text_mined_terms",
            )

    # NOTE: get_europe_pmc_citations is NOT registered as a tool.
    # Use find_citing_articles or get_article_references instead.
    # @mcp.tool()  # REMOVED - use find_citing_articles instead
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
        normalized_pmcid = (
            InputNormalizer.normalize_pmcid(str(pmcid)) if pmcid else None
        )
        normalized_limit = InputNormalizer.normalize_limit(
            limit, default=20, min_val=1, max_val=100
        )

        logger.info(
            f"Getting {direction} for PMID={normalized_pmid}, PMCID={normalized_pmcid}"
        )

        try:
            if not normalized_pmid and not normalized_pmcid:
                return ResponseFormatter.error(
                    error="Either pmid or pmcid is required",
                    suggestion="Provide a PMID or PMC ID",
                    example='get_europe_pmc_citations(pmid="12345678")',
                    tool_name="get_europe_pmc_citations",
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
                results = client.get_references(
                    source, str(article_id), limit=normalized_limit
                )
                direction_label = "References (Bibliography)"
                direction_desc = "papers cited BY this article"
            else:
                results = client.get_citations(
                    source, str(article_id), limit=normalized_limit
                )
                direction_label = "Citing Articles"
                direction_desc = "papers that cite this article"

            if not results:
                id_str = (
                    f"PMID:{normalized_pmid}"
                    if normalized_pmid
                    else f"PMC:{normalized_pmcid}"
                )
                return ResponseFormatter.no_results(
                    query=id_str,
                    suggestions=[
                        f"Article may have no {direction}",
                        "Try find_citing_articles or get_article_references for PubMed data",
                    ],
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
                tool_name="get_europe_pmc_citations",
            )
