"""
Image Search Tool - Search biomedical images across Open-i and Europe PMC.

Tools:
- search_biomedical_images: Unified biomedical image search with full API support

Full API Parameters (Open-i):
- query: Search query (required)
- image_type: xg/xm/x/u/ph/p/mc/m/g/c
- collection: pmc/cxr/usc/hmd/mpx
- sort_by: r/d/o/t/e/g
- article_type: cr/or/re/sr/...
- specialty: r/c/ne/pu/d/...
- license: by/bync/byncnd/byncsa
- subset: b/c/e/s/x
- search_fields: t/m/ab/msh/c/a
- video_only: true/false
"""

import logging
from typing import Union

from mcp.server.fastmcp import FastMCP

from pubmed_search.application.image_search import ImageSearchResult, ImageSearchService

from ._common import InputNormalizer, ResponseFormatter

logger = logging.getLogger(__name__)


def register_image_search_tools(mcp: FastMCP):
    """Register biomedical image search MCP tools.

    Note: Does not need searcher parameter. ImageSearchService
    manages its own infrastructure clients.
    Consistent with register_vision_tools(mcp) pattern.
    """

    @mcp.tool()
    def search_biomedical_images(
        query: str,
        sources: str = "auto",
        image_type: Union[str, None] = None,
        collection: Union[str, None] = None,
        open_access_only: Union[bool, str] = True,
        limit: Union[int, str] = 10,
        # New parameters (v0.3.4)
        sort_by: Union[str, None] = None,
        article_type: Union[str, None] = None,
        specialty: Union[str, None] = None,
        license_type: Union[str, None] = None,
        subset: Union[str, None] = None,
        search_fields: Union[str, None] = None,
        video_only: Union[bool, str] = False,
    ) -> str:
        """
        🖼️ Search biomedical images across Open-i and Europe PMC.

        Searches medical/scientific images from multiple sources and returns
        image URLs with metadata (caption, article info, MeSH terms).

        ═══════════════════════════════════════════════════════════════        ⚠️ CRITICAL - LANGUAGE REQUIREMENT:
        ═══════════════════════════════════════════════════════════
        Open-i ONLY supports English queries. If the user queries in
        non-English (Chinese, Japanese, Korean, etc.), you MUST:
        1. Translate the query to English medical terminology first
        2. Then call this tool with the English query
        Example: "喉頭水腫" → "laryngeal edema"
                 "胸部X光肺炎" → "chest X-ray pneumonia"
        The tool has built-in translation hints for common CJK medical
        terms, but YOU should always verify the translation is correct.

        ═══════════════════════════════════════════════════════════        SOURCES:
        ═══════════════════════════════════════════════════════════════
        - Open-i (NLM): X-ray, microscopy, clinical images (~133K)
        - Europe PMC: Figure captions from 33M+ articles (future)

        ═══════════════════════════════════════════════════════════════
        EXAMPLES:
        ═══════════════════════════════════════════════════════════════

        General image search:
            search_biomedical_images("chest pneumonia CT scan")

        X-ray only:
            search_biomedical_images("fracture", image_type="x")

        Microscopy images:
            search_biomedical_images("histology liver", image_type="mc")

        Clinical teaching images (MedPix):
            search_biomedical_images("pneumothorax", collection="mpx")

        Case reports with CC-BY license, sorted by date:
            search_biomedical_images(
                "lung cancer",
                article_type="cr",
                license_type="by",
                sort_by="d"
            )

        Cardiology specialty images:
            search_biomedical_images("echocardiogram", specialty="c")

        Video content only:
            search_biomedical_images("surgery technique", video_only=True)

        ═══════════════════════════════════════════════════════════════

        Args:
            query: Search query (e.g., "chest X-ray pneumonia")
            sources: Image sources to search:
                - "auto": Select best sources (default)
                - "openi": Open-i only (best for medical images)
                - "europe_pmc": Europe PMC only (future)
                - "all": Search all sources
            image_type: Filter by image type (Open-i only):
                Positive filters:
                - "c": CT scan images
                - "g": Graphics / line art / diagrams
                - "m": MRI images
                - "mc": Microscopy / histology images
                - "p": PET scan images
                - "ph": Photographs / clinical photos
                - "u": Ultrasound images
                - "x": X-ray images
                Exclusion filters:
                - "xg": Exclude Graphics (removes graphic images from results)
                - "xm": Exclude Multipanel (removes multipanel images)
                - None: All types (default)
            collection: Filter by collection (Open-i only):
                - "pmc": PubMed Central articles
                - "mpx": MedPix clinical teaching images (high quality)
                - "cxr": Chest X-ray collection
                - "hmd": History of Medicine
                - "usc": USC collection
                - None: All collections (default)
            open_access_only: Only return open access images (default True)
            limit: Maximum number of images to return (default 10, max 50)
            sort_by: Sort results by (Open-i only):
                - "r": Relevance (default)
                - "d": Date (newest first)
                - "o": Oldest first
                - "t": Title
                - "e": Education relevance
                - "g": Graphics priority
            article_type: Filter by article type (Open-i only):
                - "cr": Case Report
                - "or": Original Research
                - "re": Review
                - "sr": Systematic Review
                - "ra": Research Article
                - "ed": Editorial
                - "lt": Letter
                - "bk": Book
                - and more... (see API docs)
            specialty: Filter by medical specialty (Open-i only):
                - "r": Radiology
                - "c": Cardiology
                - "ne": Neurology
                - "pu": Pulmonology
                - "d": Dermatology
                - "g": Gastroenterology
                - "or": Orthopedics
                - "o": Ophthalmology
                - "s": Surgery
                - "p": Pediatrics
                - "id": Infectious Disease
                - "i": Immunology
                - and more... (see API docs)
            license_type: Filter by Creative Commons license (Open-i only):
                - "by": CC-BY (Attribution)
                - "bync": CC-BY-NC (Attribution-NonCommercial)
                - "byncnd": CC-BY-NC-ND (Attribution-NonCommercial-NoDerivs)
                - "byncsa": CC-BY-NC-SA (Attribution-NonCommercial-ShareAlike)
            subset: Filter by subject subset (Open-i only):
                - "b": Behavioral Sciences
                - "c": Cancer
                - "e": Ethics
                - "s": Surgery
                - "x": Toxicology
            search_fields: Search in specific fields (Open-i only):
                - "t": Title only
                - "m": MeSH terms only
                - "ab": Abstract only
                - "msh": MeSH heading only
                - "c": Caption only
                - "a": Author only
            video_only: If True, only return video content (default False)

        Returns:
            Formatted image results with URLs, captions, and article metadata
        """
        # 1. Input normalization
        query = InputNormalizer.normalize_query(query)
        if not query:
            return ResponseFormatter.error(
                "Missing search query",
                suggestion="Provide a search query describing the images you want",
                example='search_biomedical_images("chest X-ray pneumonia")',
                tool_name="search_biomedical_images",
            )

        limit = InputNormalizer.normalize_limit(limit, default=10, max_val=50)
        open_access_only = InputNormalizer.normalize_bool(
            open_access_only, default=True
        )
        video_only = InputNormalizer.normalize_bool(video_only, default=False)

        # 2. Map sources string to list
        source_map = {
            "auto": None,
            "openi": ["openi"],
            "europe_pmc": ["europe_pmc"],
            "all": ["openi", "europe_pmc"],
        }
        source_list = source_map.get(sources)
        if sources not in source_map:
            logger.warning(
                f"Unknown sources value '{sources}', using auto"
            )
            source_list = None

        # 3. Call application service
        try:
            service = ImageSearchService()
            result = service.search(
                query=query,
                sources=source_list,
                image_type=image_type,
                collection=collection,
                open_access_only=open_access_only,
                limit=limit,
                sort_by=sort_by,
                article_type=article_type,
                specialty=specialty,
                license_type=license_type,
                subset=subset,
                search_fields=search_fields,
                video_only=video_only,
            )
        except Exception as e:
            return ResponseFormatter.error(
                e,
                suggestion="Check your query and try again",
                tool_name="search_biomedical_images",
            )

        # 4. Format output
        return _format_image_results(result)


def _format_image_results(result: ImageSearchResult) -> str:
    """Format ImageSearchResult as markdown output."""
    parts: list[str] = []

    # Header
    parts.append("## 🖼️ Image Search Results")
    parts.append(f"**Query**: {result.query}")
    parts.append(
        f"**Found**: {len(result.images)} images "
        f"(total available: {result.total_count})"
    )
    parts.append(f"**Sources**: {', '.join(result.sources_used)}")

    # Show applied filters
    if result.applied_filters:
        filter_strs = [f"{k}={v}" for k, v in result.applied_filters.items()]
        parts.append(f"**Filters**: {', '.join(filter_strs)}")

    if result.errors:
        parts.append(f"\n⚠️ Errors: {'; '.join(result.errors)}")

    # Advisor warnings (intelligent guidance)
    if result.advisor_warnings:
        parts.append("")
        parts.append("### ⚠️ 智慧建議")
        for w in result.advisor_warnings:
            parts.append(f"- {w}")

    if result.advisor_suggestions:
        for s in result.advisor_suggestions:
            parts.append(f"- 💡 {s}")

    if result.recommended_image_type:
        parts.append(
            f"- 🎯 建議 image_type: `{result.recommended_image_type}`"
        )

    if result.coarse_category:
        parts.append(
            f"- 📂 粗分類: {result.coarse_category}"
        )

    if result.recommended_collection:
        parts.append(
            f"- 📦 建議 collection: `{result.recommended_collection}` "
            f"({result.collection_reason})"
        )

    if not result.images:
        parts.append("\nNo images found. Try broader search terms.")
        return "\n".join(parts)

    parts.append("")

    # Image results
    for i, img in enumerate(result.images, 1):
        parts.append(f"### {i}. {img.article_title or 'Untitled'}")

        # Image info
        if img.image_url:
            parts.append(f"🖼️ **Image**: {img.image_url}")
        if img.thumbnail_url:
            parts.append(f"🔍 **Thumbnail**: {img.thumbnail_url}")
        if img.caption:
            # Truncate very long captions
            caption = img.caption
            if len(caption) > 300:
                caption = caption[:297] + "..."
            parts.append(f"📝 **Caption**: {caption}")
        if img.label:
            parts.append(f"🏷️ **Label**: {img.label}")

        # Article info
        article_parts: list[str] = []
        if img.pmid:
            article_parts.append(f"PMID: {img.pmid}")
        if img.pmcid:
            article_parts.append(f"PMC: {img.pmcid}")
        if img.journal:
            article_parts.append(img.journal)
        if img.pub_year:
            article_parts.append(str(img.pub_year))
        if article_parts:
            parts.append(f"📄 {' | '.join(article_parts)}")

        if img.authors:
            # Truncate long author lists
            authors = img.authors
            if len(authors) > 100:
                authors = authors[:97] + "..."
            parts.append(f"👤 {authors}")

        # MeSH terms
        if img.mesh_terms:
            terms = ", ".join(img.mesh_terms[:5])
            if len(img.mesh_terms) > 5:
                terms += f" (+{len(img.mesh_terms) - 5} more)"
            parts.append(f"🏥 **MeSH**: {terms}")

        # Image type / collection
        meta_parts: list[str] = []
        if img.image_type:
            meta_parts.append(f"Type: {img.image_type}")
        if img.collection:
            meta_parts.append(f"Collection: {img.collection}")
        if img.source:
            meta_parts.append(f"Source: {img.source}")
        if meta_parts:
            parts.append(f"ℹ️ {' | '.join(meta_parts)}")

        parts.append("")

    # Footer with tips
    parts.append("---")
    parts.append("💡 **Tips**:")
    parts.append('- Use `image_type="x"` for X-ray, `"m"` for MRI, `"mc"` for microscopy, `"c"` for CT')
    parts.append('- Use `collection="mpx"` for MedPix clinical teaching images')
    parts.append('- Use `sort_by="d"` for newest images, `article_type="cr"` for case reports')
    parts.append('- Use `specialty="r"` for radiology, `"c"` for cardiology')
    parts.append('- Use `license_type="by"` for CC-BY licensed images')
    parts.append(
        "- Use `fetch_article_details(pmid=...)` to get full article info"
    )

    return "\n".join(parts)
