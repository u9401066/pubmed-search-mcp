"""Shared aggregation kernel for multi-source image search."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from pubmed_search.shared.source_contracts import (
    SourceAdapterErrorKind,
    SourceAdapterResult,
    SourceAdapterStatus,
    format_source_adapter_error,
)

if TYPE_CHECKING:
    from pubmed_search.domain.entities.image import ImageResult

ImageSearchStatus = Literal["completed", "empty", "partial", "failed"]


@dataclass(frozen=True, slots=True)
class ImageSourceCoverageError:
    """Typed source failure without provider-controlled text."""

    kind: SourceAdapterErrorKind
    retryable: bool
    status_code: int | None

    def to_dict(self) -> dict[str, object]:
        """Serialize only stable, non-sensitive recovery fields."""

        return {
            "kind": self.kind,
            "retryable": self.retryable,
            "status_code": self.status_code,
        }


@dataclass(frozen=True, slots=True)
class ImageSourceCoverage:
    """Sanitized per-source response and row coverage."""

    source: str
    status: SourceAdapterStatus
    returned: int
    total_available: int | None
    rows_received: int | None
    rows_rejected: int
    pages_fetched: int | None
    bounded: bool
    has_more: bool | None
    response_complete: bool
    errors: tuple[ImageSourceCoverageError, ...] = ()

    @property
    def error_kinds(self) -> tuple[SourceAdapterErrorKind, ...]:
        """Return stable error categories for compact routing."""

        return tuple(error.kind for error in self.errors)

    def to_dict(self) -> dict[str, object]:
        """Return the stable public coverage contract without error text."""

        return {
            "schema_version": "biomedical-image-source-coverage/v1",
            "source": self.source,
            "status": self.status,
            "returned": self.returned,
            "total_available": self.total_available,
            "rows_received": self.rows_received,
            "rows_rejected": self.rows_rejected,
            "pages_fetched": self.pages_fetched,
            "bounded": self.bounded,
            "has_more": self.has_more,
            "response_complete": self.response_complete,
            "errors": [error.to_dict() for error in self.errors],
        }


@dataclass(frozen=True)
class AggregatedImageResults:
    """Normalized output of the image aggregation kernel."""

    images: list[ImageResult]
    total_count: int
    sources_used: list[str]
    search_status: ImageSearchStatus
    errors: list[str] = field(default_factory=list)
    source_counts: dict[str, int] = field(default_factory=dict)
    source_coverage: list[ImageSourceCoverage] = field(default_factory=list)
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
        source_coverage: list[ImageSourceCoverage] = []

        for adapter_result in adapter_results:
            source_counts[adapter_result.source] = len(adapter_result.items)
            total_count += adapter_result.total_count
            all_images.extend(adapter_result.items)
            errors.extend(format_source_adapter_error(error) for error in adapter_result.errors)
            source_coverage.append(self._source_coverage(adapter_result))
            if adapter_result.status != "error":
                sources_used.append(adapter_result.source)

        deduplicated, duplicates_removed = self.deduplicate(all_images)
        search_status = self._search_status(adapter_results)

        return AggregatedImageResults(
            images=deduplicated[:limit],
            total_count=total_count,
            sources_used=sources_used,
            search_status=search_status,
            errors=errors,
            source_counts=source_counts,
            source_coverage=source_coverage,
            duplicates_removed=duplicates_removed,
        )

    @staticmethod
    def _search_status(adapter_results: list[SourceAdapterResult[ImageResult]]) -> ImageSearchStatus:
        """Derive the overall status without collapsing failures into empty."""

        if not adapter_results or all(result.status == "error" for result in adapter_results):
            return "failed"
        if any(result.status in {"partial", "error"} for result in adapter_results):
            return "partial"
        if any(result.items for result in adapter_results):
            return "completed"
        return "empty"

    @classmethod
    def _source_coverage(cls, result: SourceAdapterResult[ImageResult]) -> ImageSourceCoverage:
        """Extract only allowlisted, typed coverage fields from adapter metadata."""

        raw = result.metadata.get("coverage")
        raw = raw if isinstance(raw, dict) else {}
        rows_received = cls._optional_nonnegative_int(raw.get("rows_received"))
        rows_rejected = cls._optional_nonnegative_int(raw.get("rows_rejected")) or 0
        pages_fetched = cls._optional_nonnegative_int(raw.get("pages_fetched"))
        raw_bounded = raw.get("bounded")
        bounded = raw_bounded if isinstance(raw_bounded, bool) else True
        has_more = raw.get("has_more") if isinstance(raw.get("has_more"), bool) else None
        raw_response_complete = raw.get("response_complete")
        response_complete = (
            raw_response_complete
            if isinstance(raw_response_complete, bool)
            else result.status in {"ok", "empty"} and not result.errors
        )
        return ImageSourceCoverage(
            source=result.source,
            status=result.status,
            returned=len(result.items),
            total_available=None if result.status == "error" else result.total_count,
            rows_received=rows_received,
            rows_rejected=rows_rejected,
            pages_fetched=pages_fetched,
            bounded=bounded,
            has_more=has_more,
            response_complete=response_complete,
            errors=tuple(
                ImageSourceCoverageError(
                    kind=error.kind,
                    retryable=error.retryable,
                    status_code=error.status_code,
                )
                for error in result.errors
            ),
        )

    @staticmethod
    def _optional_nonnegative_int(value: object) -> int | None:
        """Read one provider count without coercing bools, floats, or strings."""

        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

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
