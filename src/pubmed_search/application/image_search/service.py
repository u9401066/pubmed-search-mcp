"""
Application Service: Image Search

Coordinates image search across Open-i and Europe PMC.
Handles source selection, result merging, and deduplication.

Usage:
    >>> service = ImageSearchService()
    >>> result = service.search("chest pneumonia", image_type="xg")
    >>> print(result.total_count)

Full API support (v0.3.4):
    >>> result = service.search(
    ...     query="pneumonia",
    ...     image_type="xg",
    ...     sort_by="d",  # newest first
    ...     article_type="cr",  # case reports only
    ...     specialty="pu",  # pulmonology
    ...     license_type="by",  # CC-BY license
    ... )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any

from pubmed_search.shared.source_contracts import SourceAdapterCall, gather_source_adapter_calls

from .aggregation_kernel import ImageAggregationKernel
from .source_adapters import build_image_source_registry

if TYPE_CHECKING:
    from pubmed_search.domain.entities.image import ImageResult

    from .source_adapters import ImageSourceAdapter

logger = logging.getLogger(__name__)


@dataclass
class ImageSearchResult:
    """Container for image search results."""

    images: list[ImageResult]
    total_count: int
    sources_used: list[str]
    query: str
    errors: list[str] = field(default_factory=list)
    advisor_warnings: list[str] = field(default_factory=list)
    advisor_suggestions: list[str] = field(default_factory=list)
    advisor_diagnostics: dict[str, Any] = field(default_factory=dict)
    recommended_image_type: str | None = None
    coarse_category: str | None = None
    recommended_collection: str | None = None
    collection_reason: str = ""
    # Applied filters (for display)
    applied_filters: dict[str, str] = field(default_factory=dict)


class ImageSearchService:
    """
    Image search application service.

    Coordinates Open-i (and future Europe PMC) image search,
    handles multi-source result merging and deduplication.

    Architecture:
        Presentation → Application (here) → Infrastructure (OpenIClient)
        Domain entities (ImageResult) flow upward.
    """

    # Valid source identifiers
    VALID_SOURCES = {"openi", "europe_pmc"}

    def __init__(
        self,
        *,
        adapters: dict[str, ImageSourceAdapter] | None = None,
        aggregation_kernel: ImageAggregationKernel | None = None,
    ) -> None:
        self._adapters = adapters or build_image_source_registry()
        self._aggregation_kernel = aggregation_kernel or ImageAggregationKernel()

    async def search(
        self,
        query: str,
        sources: list[str] | None = None,
        image_type: str | None = None,
        collection: str | None = None,
        open_access_only: bool = True,  # Reserved for Phase 4.2 Europe PMC
        limit: int = 10,
        # New parameters (v0.3.4) - passed through to OpenIClient
        sort_by: str | None = None,
        article_type: str | None = None,
        specialty: str | None = None,
        license_type: str | None = None,
        subset: str | None = None,
        search_fields: str | None = None,
        video_only: bool = False,
        hmp_type: str | None = None,
    ) -> ImageSearchResult:
        """
        Unified image search across available sources.

        Args:
            query: Search query (e.g., "chest pneumonia CT")
            sources: Source list (None = auto-select, or ["openi"], ["europe_pmc"], etc.)
            image_type: Image type filter ("xg", "mc") — Open-i only
            collection: Collection filter ("pmc", "mpx", "iu") — Open-i only
            open_access_only: Only return open access images (default True)
            limit: Maximum number of images to return
            sort_by: Sort results by ("r"=relevance, "d"=date, "o"=oldest, "t"=title)
            article_type: Article type filter ("cr"=case report, "or"=original, "re"=review)
            specialty: Medical specialty ("r"=radiology, "c"=cardiology, "ne"=neurology)
            license_type: License filter ("by"=CC-BY, "bync"=CC-BY-NC, etc.)
            subset: Subject subset ("b"=behavioral, "c"=cancer, "s"=surgery)
            search_fields: Search in specific fields ("t"=title, "c"=caption, "a"=author)
            video_only: If True, only return video content
            hmp_type: HMD publication type (for History of Medicine collection)

        Returns:
            ImageSearchResult with images, count, and metadata
        """
        if not query or not query.strip():
            return ImageSearchResult(
                images=[],
                total_count=0,
                sources_used=[],
                query=query or "",
            )

        # Run ImageQueryAdvisor for intelligent guidance
        from .advisor import ImageQueryAdvisor

        advisor = ImageQueryAdvisor()
        advice = advisor.advise(query, image_type=image_type)

        # Determine sources to search
        active_sources = self._resolve_sources(sources, image_type, collection)
        applied_filters: dict[str, str] = {}

        # Track applied filters for display
        if image_type:
            applied_filters["image_type"] = image_type
        if collection:
            applied_filters["collection"] = collection
        if sort_by:
            applied_filters["sort_by"] = sort_by
        if article_type:
            applied_filters["article_type"] = article_type
        if specialty:
            applied_filters["specialty"] = specialty
        if license_type:
            applied_filters["license"] = license_type
        if subset:
            applied_filters["subset"] = subset
        if search_fields:
            applied_filters["fields"] = search_fields
        if video_only:
            applied_filters["video_only"] = "true"

        adapter_results = await gather_source_adapter_calls(
            self._build_source_calls(
                active_sources=active_sources,
                query=query,
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
                hmp_type=hmp_type,
            )
        )
        aggregated = self._aggregation_kernel.aggregate(adapter_results, limit=limit)

        return ImageSearchResult(
            images=aggregated.images,
            total_count=aggregated.total_count,
            sources_used=aggregated.sources_used,
            query=query,
            errors=aggregated.errors,
            advisor_warnings=advice.warnings,
            advisor_suggestions=advice.suggestions,
            advisor_diagnostics=advice.diagnostics,
            recommended_image_type=advice.recommended_image_type,
            coarse_category=advice.coarse_category,
            recommended_collection=advice.recommended_collection,
            collection_reason=advice.collection_reason,
            applied_filters=applied_filters,
        )

    def _build_source_calls(
        self,
        *,
        active_sources: list[str],
        query: str,
        image_type: str | None,
        collection: str | None,
        open_access_only: bool,
        limit: int,
        sort_by: str | None,
        article_type: str | None,
        specialty: str | None,
        license_type: str | None,
        subset: str | None,
        search_fields: str | None,
        video_only: bool,
        hmp_type: str | None,
    ) -> list[SourceAdapterCall[ImageResult]]:
        """Convert resolved sources into source-adapter calls."""
        calls: list[SourceAdapterCall[ImageResult]] = []

        for source in active_sources:
            adapter = self._adapters.get(source)
            if adapter is None:
                calls.append(
                    SourceAdapterCall(
                        source=source,
                        operation="search_images",
                        execute=partial(self._raise_unavailable_source, source),
                    )
                )
                continue

            calls.append(
                SourceAdapterCall(
                    source=source,
                    operation="search_images",
                    execute=partial(
                        adapter.search,
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
                        open_access_only=open_access_only,
                    ),
                )
            )

        return calls

    @staticmethod
    async def _raise_unavailable_source(source: str) -> None:
        msg = f"Image source adapter not implemented: {source}"
        raise NotImplementedError(msg)

    def _resolve_sources(
        self,
        sources: list[str] | None,
        image_type: str | None,
        collection: str | None,
    ) -> list[str]:
        """
        Determine which sources to search.

        Args:
            sources: Explicit source list or None for auto-select
            image_type: If set, implies Open-i
            collection: If set, implies Open-i

        Returns:
            List of source identifiers
        """
        if sources is not None:
            # Validate and filter
            valid = [s for s in sources if s in self.VALID_SOURCES]
            if not valid:
                logger.warning(f"No valid sources in {sources}, falling back to openi")
                return ["openi"]
            return valid

        # Auto-select: for MVP, just use Open-i
        # Phase 4.2+ will add Europe PMC auto-selection logic
        return ["openi"]

    @staticmethod
    def _deduplicate(images: list[ImageResult]) -> list[ImageResult]:
        """Backward-compatible proxy to the shared aggregation kernel dedup policy."""
        deduplicated, _duplicates_removed = ImageAggregationKernel.deduplicate(images)
        return deduplicated
