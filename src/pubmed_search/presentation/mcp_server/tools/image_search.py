"""
Image Search Tool - Search biomedical images across Open-i and Europe PMC.

Tools:
- search_biomedical_images: Unified biomedical image search
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
    ) -> str:
        """
        🖼️ Search biomedical images across Open-i and Europe PMC.

        Searches medical/scientific images from multiple sources and returns
        image URLs with metadata (caption, article info, MeSH terms).

        ═══════════════════════════════════════════════════════════════
        SOURCES:
        ═══════════════════════════════════════════════════════════════
        - Open-i (NLM): X-ray, microscopy, clinical images
        - Europe PMC: Figure captions from 33M+ articles (future)

        ═══════════════════════════════════════════════════════════════
        EXAMPLES:
        ═══════════════════════════════════════════════════════════════

        General image search:
            search_biomedical_images("chest pneumonia CT scan")

        X-ray only:
            search_biomedical_images("fracture", image_type="xg")

        Microscopy images:
            search_biomedical_images("histology liver", image_type="mc")

        Clinical teaching images (MedPix):
            search_biomedical_images("pneumothorax", collection="mpx")

        ═══════════════════════════════════════════════════════════════

        Args:
            query: Search query (e.g., "chest X-ray pneumonia")
            sources: Image sources to search:
                - "auto": Select best sources (default)
                - "openi": Open-i only (best for medical images)
                - "europe_pmc": Europe PMC only (future)
                - "all": Search all sources
            image_type: Filter by image type (Open-i only):
                - "xg": X-ray images
                - "mc": Microscopy images
                - None: All types (default)
            collection: Filter by collection (Open-i only):
                - "pmc": PubMed Central articles
                - "mpx": MedPix clinical teaching images
                - "iu": Indiana University radiology reports
                - None: All collections (default)
            open_access_only: Only return open access images (default True)
            limit: Maximum number of images to return (default 10)

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

    if result.errors:
        parts.append(f"\n⚠️ Errors: {'; '.join(result.errors)}")

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
    parts.append('- Use `image_type="xg"` for X-ray, `"mc"` for microscopy')
    parts.append('- Use `collection="mpx"` for MedPix clinical teaching images')
    parts.append(
        "- Use `fetch_article_details(pmid=...)` to get full article info"
    )

    return "\n".join(parts)
