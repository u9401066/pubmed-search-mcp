"""
Image Search Tool - Search biomedical images through the Open-i adapter.

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

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field

from pubmed_search.shared.markdown import escape_markdown_code, escape_markdown_text, safe_markdown_url

from ._common import InputNormalizer, ResponseFormatter

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from pubmed_search.application.image_search import ImageSearchResult, ImageSearchService

ImageQuery = Annotated[str, Field(min_length=1, max_length=500)]
ImageLimit = Annotated[int, Field(ge=1, le=50)]
ImageType = Literal["xg", "xm", "x", "u", "ph", "p", "mc", "m", "g", "c"]
ImageCollection = Literal["pmc", "cxr", "usc", "hmd", "mpx"]
ImageSort = Literal["r", "o", "d", "e", "g", "oc", "pr", "pg", "t"]
ImageArticleType = Literal[
    "ab",
    "bk",
    "bf",
    "cr",
    "dp",
    "di",
    "ed",
    "ib",
    "in",
    "lt",
    "mr",
    "ma",
    "ne",
    "ob",
    "pr",
    "or",
    "re",
    "ra",
    "rw",
    "sr",
    "rr",
    "os",
    "hs",
    "ot",
]
ImageSpecialty = Literal[
    "b",
    "bc",
    "c",
    "ca",
    "cc",
    "d",
    "de",
    "dt",
    "e",
    "en",
    "f",
    "eh",
    "g",
    "ge",
    "gr",
    "gy",
    "h",
    "i",
    "id",
    "im",
    "n",
    "ne",
    "nu",
    "o",
    "or",
    "ot",
    "p",
    "py",
    "pu",
    "r",
    "s",
    "t",
    "u",
    "v",
    "vi",
]
ImageLicense = Literal["by", "bync", "byncnd", "byncsa"]
ImageSubset = Literal["b", "c", "e", "s", "x"]
ImageSearchField = Literal["t", "m", "ab", "msh", "c", "a"]
ImageHmpType = Literal[
    "ad",
    "ar",
    "at",
    "bi",
    "br",
    "cr",
    "ca",
    "ch",
    "cg",
    "cd",
    "dr",
    "ep",
    "ex",
    "hr",
    "hu",
    "lt",
    "mp",
    "nw",
    "pn",
    "ph",
    "pi",
    "po",
    "pt",
    "pc",
    "ps",
]


def register_image_search_tools(
    mcp: MCPServer,
    service: ImageSearchService,
) -> None:
    """Register biomedical image search tools with an injected service."""

    @mcp.tool()
    async def search_biomedical_images(
        query: ImageQuery,
        image_type: ImageType | None = None,
        collection: ImageCollection | None = None,
        limit: ImageLimit = 10,
        sort_by: ImageSort | None = None,
        article_type: ImageArticleType | None = None,
        specialty: ImageSpecialty | None = None,
        license_type: ImageLicense | None = None,
        subset: ImageSubset | None = None,
        search_fields: ImageSearchField | None = None,
        video_only: bool = False,
        hmp_type: ImageHmpType | None = None,
    ) -> str:
        """
        🖼️ Search biomedical images from NLM Open-i.

        Searches medical/scientific images from Open-i and returns
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
            hmp_type: History of Medicine publication type. Requires collection="hmd".

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
        if len(query) > 500:
            return ResponseFormatter.error(
                "Search query exceeds 500 characters",
                suggestion="Provide one concise English biomedical image query",
                tool_name="search_biomedical_images",
            )

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            return ResponseFormatter.error(
                "limit must be an integer from 1 to 50",
                tool_name="search_biomedical_images",
            )

        # 2. Call the registry-backed application service. The public schema
        # exposes only capabilities that have a live default adapter.
        try:
            result = await service.search(
                query=query,
                image_type=image_type,
                collection=collection,
                limit=limit,
                sort_by=sort_by,
                article_type=article_type,
                specialty=specialty,
                license_type=license_type,
                subset=subset,
                search_fields=search_fields,
                video_only=video_only,
                hmp_type=hmp_type,
            )
        except Exception as exc:
            logger.warning("Biomedical image search failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                "Biomedical image search could not be completed",
                suggestion="Check the bounded query and retry unavailable sources later",
                tool_name="search_biomedical_images",
            )

        # 3. Format output
        return _format_image_results(result)


def _format_image_results(result: ImageSearchResult) -> str:
    """Format ImageSearchResult as markdown output."""
    parts: list[str] = []

    # Header
    parts.append("## 🖼️ Image Search Results")
    parts.append(f"**Query**: {escape_markdown_text(result.query)}")
    parts.append(f"**Search status**: `{escape_markdown_code(result.search_status)}`")
    parts.append(f"**Found**: {len(result.images)} images (total available: {result.total_count})")
    rendered_sources = ", ".join(escape_markdown_text(source) for source in result.sources_used) or "none"
    parts.append(f"**Responding sources**: {rendered_sources}")
    if result.source_coverage:
        parts.append("**Source coverage**:")
        for coverage in result.source_coverage:
            total = "unknown" if coverage.total_available is None else str(coverage.total_available)
            coverage_details = [
                f"status={coverage.status}",
                f"returned={coverage.returned}",
                f"total_available={total}",
                f"rows_rejected={coverage.rows_rejected}",
            ]
            if coverage.has_more is not None:
                coverage_details.append(f"has_more={str(coverage.has_more).lower()}")
            parts.append(
                f"- {escape_markdown_text(coverage.source)}: `{escape_markdown_code(', '.join(coverage_details))}`"
            )

    # Show applied filters
    if result.applied_filters:
        filter_strs = [
            f"{escape_markdown_text(k)}={escape_markdown_text(v)}" for k, v in result.applied_filters.items()
        ]
        parts.append(f"**Filters**: {', '.join(filter_strs)}")

    if result.errors:
        parts.append(f"\n⚠️ Errors: {'; '.join(escape_markdown_text(error) for error in result.errors)}")

    # Advisor warnings (intelligent guidance)
    if result.advisor_warnings:
        parts.append("")
        parts.append("### ⚠️ 智慧建議")
        for w in result.advisor_warnings:
            parts.append(f"- {escape_markdown_text(w)}")

    if result.advisor_suggestions:
        for s in result.advisor_suggestions:
            parts.append(f"- 💡 {escape_markdown_text(s)}")

    if result.recommended_image_type:
        parts.append(f"- 🎯 建議 image_type: `{escape_markdown_code(result.recommended_image_type)}`")

    if result.coarse_category:
        parts.append(f"- 📂 粗分類: {escape_markdown_text(result.coarse_category)}")

    if result.recommended_collection:
        parts.append(
            f"- 📦 建議 collection: `{escape_markdown_code(result.recommended_collection)}` "
            f"({escape_markdown_text(result.collection_reason)})"
        )

    feature_hits = result.advisor_diagnostics.get("feature_hits", []) if result.advisor_diagnostics else []
    if feature_hits:
        parts.append("")
        parts.append("### 🔎 Query Diagnostics")
        for hit in feature_hits[:6]:
            matched_terms = ", ".join(escape_markdown_text(term) for term in hit.get("matched_terms", []))
            score_delta = hit.get("score_delta")
            details = escape_markdown_text(hit["reason"])
            if matched_terms:
                details = f"{details}: {matched_terms}"
            if score_delta is not None:
                details = f"{details} ({score_delta:+.2f})"
            category = escape_markdown_text(hit["category"])
            rule = escape_markdown_text(hit["rule"])
            parts.append(f"- {category}/{rule}: {details}")

    if not result.images:
        if result.search_status == "partial":
            parts.append(
                "\nNo images were returned by the responding source subset, but coverage is partial; "
                "do not interpret this as a verified zero-result search."
            )
        elif result.search_status == "empty":
            parts.append("\nNo images found in the bounded, successfully queried source set. Try broader search terms.")
        else:
            parts.append(
                "\nBiomedical image search could not be completed because all requested sources were unavailable. "
                "Retry later; do not interpret this outage as evidence that no images exist."
            )
        return "\n".join(parts)

    parts.append("")

    # Image results
    for i, img in enumerate(result.images, 1):
        parts.append(f"### {i}. {escape_markdown_text(img.article_title or 'Untitled')}")

        # Image info
        if img.image_url:
            parts.append(f"🖼️ **Image**: {safe_markdown_url(img.image_url) or 'unsafe URL omitted'}")
        if img.thumbnail_url:
            parts.append(f"🔍 **Thumbnail**: {safe_markdown_url(img.thumbnail_url) or 'unsafe URL omitted'}")
        if img.caption:
            # Truncate very long captions
            caption = img.caption
            if len(caption) > 300:
                caption = caption[:297] + "..."
            parts.append(f"📝 **Caption**: {escape_markdown_text(caption)}")
        if img.label:
            parts.append(f"🏷️ **Label**: {escape_markdown_text(img.label)}")

        # Article info
        article_parts: list[str] = []
        if img.pmid:
            article_parts.append(f"PMID: {escape_markdown_text(img.pmid)}")
        if img.pmcid:
            article_parts.append(f"PMC: {escape_markdown_text(img.pmcid)}")
        if img.journal:
            article_parts.append(escape_markdown_text(img.journal))
        if img.pub_year:
            article_parts.append(escape_markdown_text(img.pub_year))
        if article_parts:
            parts.append(f"📄 {' | '.join(article_parts)}")

        if img.authors:
            # Truncate long author lists
            authors = img.authors
            if len(authors) > 100:
                authors = authors[:97] + "..."
            parts.append(f"👤 {escape_markdown_text(authors)}")

        # MeSH terms
        if img.mesh_terms:
            terms = ", ".join(escape_markdown_text(term) for term in img.mesh_terms[:5])
            if len(img.mesh_terms) > 5:
                terms += f" (+{len(img.mesh_terms) - 5} more)"
            parts.append(f"🏥 **MeSH**: {terms}")

        # Image type / collection
        meta_parts: list[str] = []
        if img.image_type:
            meta_parts.append(f"Type: {escape_markdown_text(img.image_type)}")
        if img.collection:
            meta_parts.append(f"Collection: {escape_markdown_text(img.collection)}")
        if img.source:
            meta_parts.append(f"Source: {escape_markdown_text(img.source)}")
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
    parts.append("- Use `fetch_article_details(pmids=...)` to get full article info")

    return "\n".join(parts)
