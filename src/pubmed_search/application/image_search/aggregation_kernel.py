"""Shared aggregation kernel for multi-source image search."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pubmed_search.shared.source_contracts import SourceAdapterResult, format_source_adapter_error

if TYPE_CHECKING:
    from pubmed_search.domain.entities.image import ImageResult


@dataclass(frozen=True)
class AggregatedImageResults:
    """Normalized output of the image aggregation kernel."""

    images: list[ImageResult]
    total_count: int
    sources_used: list[str]
    errors: list[str] = field(default_factory=list)
    source_counts: dict[str, int] = field(default_factory=dict)
    duplicates_removed: int = 0


class ImageAggregationKernel:
    """Own merge, deduplication, and partial-failure policy for image search."""

    def aggregate(
        self,
        adapter_results: list[SourceAdapterResult[ImageResult]],
        *,
        limit: int,
    ) -> AggregatedImageResults:
        all_images: list[ImageResult] = []
        total_count = 0
        errors: list[str] = []
        sources_used: list[str] = []
        source_counts: dict[str, int] = {}

        for adapter_result in adapter_results:
            source_counts[adapter_result.source] = len(adapter_result.items)
            total_count += adapter_result.total_count
            all_images.extend(adapter_result.items)
            errors.extend(format_source_adapter_error(error) for error in adapter_result.errors)
            if adapter_result.has_items or adapter_result.status in {"ok", "empty", "partial"}:
                sources_used.append(adapter_result.source)

        deduplicated, duplicates_removed = self.deduplicate(all_images)

        return AggregatedImageResults(
            images=deduplicated[:limit],
            total_count=total_count,
            sources_used=sources_used,
            errors=errors,
            source_counts=source_counts,
            duplicates_removed=duplicates_removed,
        )

    @staticmethod
    def deduplicate(images: list[ImageResult]) -> tuple[list[ImageResult], int]:
        """Deduplicate images with a stable multi-key policy."""
        seen_keys: set[str] = set()
        unique: list[ImageResult] = []

        for image in images:
            if image.pmid and image.source_id:
                key = f"pmid:{image.pmid}:source:{image.source_id}"
            elif image.source_id:
                key = f"sid:{image.source_id}"
            elif image.image_url:
                key = f"url:{image.image_url}"
            else:
                unique.append(image)
                continue

            if key in seen_keys:
                continue

            seen_keys.add(key)
            unique.append(image)

        return unique, max(len(images) - len(unique), 0)
