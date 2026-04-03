"""Source adapter registry for image search providers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pubmed_search.domain.entities.image import ImageResult


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
        open_access_only: bool,
    ) -> tuple[list[ImageResult], int]:
        """Search a single image source and return normalized image entities."""


class OpenIImageSourceAdapter:
    """Open-i backed adapter implementing the image source contract."""

    source_name = "openi"

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
        open_access_only: bool,
    ) -> tuple[list[ImageResult], int]:
        del open_access_only

        from pubmed_search.infrastructure.sources import get_openi_client

        client = get_openi_client()  # type: ignore[no-untyped-call]
        return await client.search(  # type: ignore[no-any-return, no-untyped-call]
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


def build_image_source_registry() -> dict[str, ImageSourceAdapter]:
    """Build the default source adapter registry for image search."""
    return {
        OpenIImageSourceAdapter.source_name: OpenIImageSourceAdapter(),
    }
