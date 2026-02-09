"""
Application Service: Image Search

Coordinates image search across Open-i and Europe PMC.
Handles source selection, result merging, and deduplication.

Usage:
    >>> service = ImageSearchService()
    >>> result = service.search("chest pneumonia", image_type="xg")
    >>> print(result.total_count)
"""

import logging
from dataclasses import dataclass, field

from pubmed_search.domain.entities.image import ImageResult

logger = logging.getLogger(__name__)


@dataclass
class ImageSearchResult:
    """Container for image search results."""

    images: list[ImageResult]
    total_count: int
    sources_used: list[str]
    query: str
    errors: list[str] = field(default_factory=list)


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

    def search(
        self,
        query: str,
        sources: list[str] | None = None,
        image_type: str | None = None,
        collection: str | None = None,
        open_access_only: bool = True,  # Reserved for Phase 4.2 Europe PMC
        limit: int = 10,
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

        # Determine sources to search
        active_sources = self._resolve_sources(sources, image_type, collection)

        all_images: list[ImageResult] = []
        errors: list[str] = []
        total_count = 0

        for source in active_sources:
            try:
                if source == "openi":
                    images, count = self._search_openi(
                        query=query,
                        image_type=image_type,
                        collection=collection,
                        limit=limit,
                    )
                    all_images.extend(images)
                    total_count += count
                # Future: elif source == "europe_pmc": ...
            except Exception as e:
                error_msg = f"{source}: {e}"
                logger.error(f"Image search failed for {error_msg}")
                errors.append(error_msg)

        # Deduplicate by PMID/source_id
        deduped = self._deduplicate(all_images)

        # Trim to limit
        final_images = deduped[:limit]

        return ImageSearchResult(
            images=final_images,
            total_count=total_count,
            sources_used=active_sources,
            query=query,
            errors=errors,
        )

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
                logger.warning(
                    f"No valid sources in {sources}, falling back to openi"
                )
                return ["openi"]
            return valid

        # Auto-select: for MVP, just use Open-i
        # Phase 4.2+ will add Europe PMC auto-selection logic
        return ["openi"]

    def _search_openi(
        self,
        query: str,
        image_type: str | None,
        collection: str | None,
        limit: int,
    ) -> tuple[list[ImageResult], int]:
        """
        Search Open-i via infrastructure client.

        Uses lazy initialization via get_openi_client().
        """
        from pubmed_search.infrastructure.sources import get_openi_client

        client = get_openi_client()
        return client.search(
            query=query,
            image_type=image_type,
            collection=collection,
            max_results=limit,
        )

    @staticmethod
    def _deduplicate(images: list[ImageResult]) -> list[ImageResult]:
        """
        Deduplicate images by PMID + source_id combination.

        When images from multiple sources share the same PMID,
        keep the first occurrence (source priority order matters).
        Images without identifiers are always kept.
        """
        seen_keys: set[str] = set()
        unique: list[ImageResult] = []

        for img in images:
            # Build dedup key
            if img.pmid and img.source_id:
                key = f"{img.pmid}:{img.source_id}"
            elif img.source_id:
                key = f"sid:{img.source_id}"
            elif img.image_url:
                key = f"url:{img.image_url}"
            else:
                # No identifier — keep it
                unique.append(img)
                continue

            if key not in seen_keys:
                seen_keys.add(key)
                unique.append(img)

        return unique
