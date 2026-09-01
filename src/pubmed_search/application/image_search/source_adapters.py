"""Source adapter contracts and registry assembly for image search.

Design:
    This module defines the narrow adapter protocol used by image-search
    orchestration and provides the default registry of source implementations.
    It keeps the application layer dependent on capabilities instead of direct
    infrastructure clients.

Maintenance:
    Add new image providers by implementing the protocol and registering them
    through the builder. Avoid moving provider-specific parsing logic into the
    registry layer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pubmed_search.domain.entities.image import ImageResult
from pubmed_search.shared.source_contracts import SourceAdapterError, SourceAdapterResult

ImageProviderStatus = Literal["ok", "empty", "partial"]
ImageProviderIssueKind = Literal["malformed_response", "malformed_rows"]


class ImageProviderResponseError(RuntimeError):
    """Sanitized failure raised when a provider response violates its schema."""


@dataclass(frozen=True, slots=True)
class ImageProviderIssue:
    """Sanitized provider issue carried without raw payload or exception text."""

    kind: ImageProviderIssueKind
    rejected_rows: int = 0

    def __post_init__(self) -> None:
        if self.kind not in {"malformed_response", "malformed_rows"}:
            raise ValueError("Image provider issue kind is invalid")
        if isinstance(self.rejected_rows, bool) or not isinstance(self.rejected_rows, int):
            raise TypeError("Image provider rejected_rows must be an integer")
        if self.rejected_rows < 0:
            raise ValueError("Image provider rejected_rows must be nonnegative")
        if self.kind == "malformed_rows" and self.rejected_rows == 0:
            raise ValueError("malformed_rows issues require at least one rejected row")


@dataclass(frozen=True, slots=True)
class ImageProviderSearchResult:
    """Strict result returned by an image-provider client.

    The provider boundary distinguishes a verified zero-result response from a
    failed or partially malformed response. Raw provider payloads never become
    part of this value.
    """

    images: list[ImageResult]
    total_count: int
    status: ImageProviderStatus
    rows_received: int
    pages_fetched: int
    issues: tuple[ImageProviderIssue, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.images, list) or any(not isinstance(image, ImageResult) for image in self.images):
            raise TypeError("Image provider results must contain only ImageResult values")
        for name, value in (
            ("total_count", self.total_count),
            ("rows_received", self.rows_received),
            ("pages_fetched", self.pages_fetched),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"Image provider {name} must be an integer")
            if value < 0:
                raise ValueError(f"Image provider {name} must be nonnegative")
        if self.pages_fetched == 0:
            raise ValueError("Image provider results require at least one validated page")
        if not isinstance(self.issues, tuple) or any(
            not isinstance(issue, ImageProviderIssue) for issue in self.issues
        ):
            raise TypeError("Image provider issues must be an ImageProviderIssue tuple")
        if self.status not in {"ok", "empty", "partial"}:
            raise ValueError("Image provider status is invalid")

        rejected_rows = sum(issue.rejected_rows for issue in self.issues)
        if self.rows_received != len(self.images) + rejected_rows:
            raise ValueError("Image provider row accounting is inconsistent")
        if self.total_count < self.rows_received:
            raise ValueError("Image provider total_count is smaller than received rows")
        if self.status == "empty" and (self.images or self.total_count != 0 or self.rows_received != 0 or self.issues):
            raise ValueError("An empty image-provider result must be a verified zero response")
        if self.status == "ok" and (not self.images or self.issues):
            raise ValueError("An ok image-provider result requires images and no issues")
        if self.status == "partial" and (not self.images or not self.issues):
            raise ValueError("A partial image-provider result requires images and issues")

    @property
    def rejected_rows(self) -> int:
        """Return the number of provider rows rejected during strict mapping."""

        return sum(issue.rejected_rows for issue in self.issues)


class ImageSourceAdapter(Protocol):
    """Contract for a source that can provide biomedical image results."""

    source_name: str

    async def search(
        self,
        *,
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
    ) -> SourceAdapterResult[ImageResult]:
        """Search a single image source and return its typed result envelope."""


class OpenIClientPort(Protocol):
    """Application-facing capability required from an Open-i client."""

    async def search(
        self,
        query: str,
        image_type: str | None = None,
        collection: str | None = None,
        max_results: int = 10,
        sort_by: str | None = None,
        article_type: str | None = None,
        specialty: str | None = None,
        license_type: str | None = None,
        subset: str | None = None,
        search_fields: str | None = None,
        video_only: bool = False,
        hmp_type: str | None = None,
    ) -> ImageProviderSearchResult:
        """Search Open-i and return a strict provider result."""


OpenIClientFactory = Callable[[], OpenIClientPort]


class OpenIImageSourceAdapter:
    """Open-i backed adapter implementing the image source contract."""

    source_name = "openi"

    def __init__(self, *, client_factory: OpenIClientFactory) -> None:
        self._client_factory = client_factory

    async def search(
        self,
        *,
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
    ) -> SourceAdapterResult[ImageResult]:
        client = self._client_factory()
        try:
            outcome = await client.search(
                query=query,
                image_type=image_type,
                collection=collection,
                max_results=limit,
                sort_by=sort_by,
                article_type=article_type,
                specialty=specialty,
                license_type=license_type,
                subset=subset,
                search_fields=search_fields,
                video_only=video_only,
                hmp_type=hmp_type,
            )
        except ImageProviderResponseError:
            return SourceAdapterResult.failure(
                source=self.source_name,
                operation="search_images",
                error=SourceAdapterError(
                    source=self.source_name,
                    operation="search_images",
                    message="Open-i returned a malformed response",
                    kind="validation",
                    retryable=False,
                ),
            )
        errors = [self._issue_to_error(issue) for issue in outcome.issues]
        return SourceAdapterResult(
            source=self.source_name,
            operation="search_images",
            items=outcome.images,
            total_count=outcome.total_count,
            status=outcome.status,
            errors=errors,
            metadata={
                "coverage": {
                    "schema_version": "biomedical-image-source-coverage/v1",
                    "returned": len(outcome.images),
                    "total_available": outcome.total_count,
                    "rows_received": outcome.rows_received,
                    "rows_rejected": outcome.rejected_rows,
                    "pages_fetched": outcome.pages_fetched,
                    "bounded": True,
                    "has_more": outcome.total_count > outcome.rows_received,
                    "response_complete": not outcome.issues,
                }
            },
        )

    @classmethod
    def _issue_to_error(cls, issue: ImageProviderIssue) -> SourceAdapterError:
        """Map a sanitized provider issue to the shared source contract."""

        message = (
            "Open-i returned malformed result rows"
            if issue.kind == "malformed_rows"
            else "Open-i returned a malformed response page"
        )
        return SourceAdapterError(
            source=cls.source_name,
            operation="search_images",
            message=message,
            kind="validation",
            retryable=False,
        )


def build_image_source_registry(
    *,
    openi_client_factory: OpenIClientFactory,
) -> dict[str, ImageSourceAdapter]:
    """Build the source adapter registry from explicit provider factories."""
    return {
        OpenIImageSourceAdapter.source_name: OpenIImageSourceAdapter(
            client_factory=openi_client_factory,
        ),
    }


__all__ = [
    "ImageProviderIssue",
    "ImageProviderIssueKind",
    "ImageProviderResponseError",
    "ImageProviderSearchResult",
    "ImageProviderStatus",
    "ImageSourceAdapter",
    "OpenIClientFactory",
    "OpenIClientPort",
    "OpenIImageSourceAdapter",
    "build_image_source_registry",
]
