"""
Application Service: Image Search

Coordinates image search across the adapters that are actually registered.
Handles result merging and deduplication without advertising future providers.

Usage:
    >>> service = ImageSearchService(adapters={"openi": openi_adapter})
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

from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any

from pubmed_search.shared.source_contracts import SourceAdapterCall, gather_source_adapter_calls

from .aggregation_kernel import ImageAggregationKernel, ImageSearchStatus, ImageSourceCoverage

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pubmed_search.domain.entities.image import ImageResult

    from .source_adapters import ImageSourceAdapter

IMAGE_SOURCE_TIMEOUT_SECONDS = 20.0


@dataclass
class ImageSearchResult:
    """Container for image search results."""

    images: list[ImageResult]
    total_count: int
    sources_used: list[str]
    query: str
    search_status: ImageSearchStatus
    source_counts: dict[str, int]
    source_coverage: list[ImageSourceCoverage]
    duplicates_removed: int
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

    def coverage(self) -> dict[str, object]:
        """Return the typed, privacy-safe image-search coverage contract."""

        return {
            "schema_version": "biomedical-image-search-coverage/v1",
            "status": self.search_status,
            "sources_attempted": [coverage.source for coverage in self.source_coverage],
            "sources_used": list(self.sources_used),
            "source_counts": dict(self.source_counts),
            "duplicates_removed": self.duplicates_removed,
            "sources": [coverage.to_dict() for coverage in self.source_coverage],
        }


class ImageSearchService:
    """
    Image search application service.

    Coordinates registered image adapters and handles result merging and
    deduplication. Provider adapters are required constructor dependencies.

    Architecture:
        Presentation composition root → Application (here) → adapter port
        Domain entities (ImageResult) flow upward.
    """

    def __init__(
        self,
        *,
        adapters: Mapping[str, ImageSourceAdapter],
        aggregation_kernel: ImageAggregationKernel | None = None,
    ) -> None:
        self._adapters = dict(adapters)
        self._aggregation_kernel = aggregation_kernel or ImageAggregationKernel()

    async def search(
        self,
        query: str,
        sources: list[str] | None = None,
        image_type: str | None = None,
        collection: str | None = None,
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
            sources: Optional subset of registered adapter names. Unknown names fail closed.
            image_type: Image type filter ("xg", "mc") — Open-i only
            collection: Collection filter ("pmc", "mpx", "iu") — Open-i only
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
            raise ValueError("Image search query must not be empty")
        query = query.strip()
        if len(query) > 500:
            raise ValueError("Image search query exceeds 500 characters")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise ValueError("Image search limit must be an integer from 1 to 50")

        # Run ImageQueryAdvisor for intelligent guidance
        from .advisor import ImageQueryAdvisor

        advisor = ImageQueryAdvisor()
        advice = advisor.advise(query, image_type=image_type)

        # Determine sources to search
        active_sources = self._resolve_sources(sources)
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
        if hmp_type:
            if collection != "hmd":
                raise ValueError("hmp_type requires collection='hmd'")
            applied_filters["hmp_type"] = hmp_type

        adapter_results = await gather_source_adapter_calls(
            self._build_source_calls(
                active_sources=active_sources,
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
            ),
            per_call_timeout=IMAGE_SOURCE_TIMEOUT_SECONDS,
        )
        aggregated = self._aggregation_kernel.aggregate(adapter_results, limit=limit)

        return ImageSearchResult(
            images=aggregated.images,
            total_count=aggregated.total_count,
            sources_used=aggregated.sources_used,
            query=query,
            search_status=aggregated.search_status,
            source_counts=aggregated.source_counts,
            source_coverage=aggregated.source_coverage,
            duplicates_removed=aggregated.duplicates_removed,
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
            adapter = self._adapters[source]

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
                    ),
                )
            )

        return calls

    def _resolve_sources(self, sources: list[str] | None) -> list[str]:
        """Resolve only providers backed by a live adapter, failing closed."""
        available = list(self._adapters)
        if not available:
            raise RuntimeError("No biomedical image source adapters are registered")
        if sources is None:
            return available
        requested: list[str] = []
        seen: set[str] = set()
        for source in sources:
            if not isinstance(source, str) or not source:
                raise ValueError("Biomedical image sources must be non-empty canonical strings")
            if source != source.strip():
                raise ValueError(f"Biomedical image source contains surrounding whitespace: {source!r}")
            if source in seen:
                raise ValueError(f"Duplicate biomedical image source: {source}")
            seen.add(source)
            requested.append(source)
        unknown = [source for source in requested if source not in self._adapters]
        if unknown:
            raise ValueError(
                f"Unknown biomedical image source(s): {', '.join(unknown)}; available: {', '.join(available)}"
            )
        if not requested:
            raise ValueError("At least one biomedical image source is required")
        return requested

    @staticmethod
    def _deduplicate(images: list[ImageResult]) -> list[ImageResult]:
        """Apply the shared aggregation-kernel deduplication policy."""
        deduplicated, _duplicates_removed = ImageAggregationKernel.deduplicate(images)
        return deduplicated
