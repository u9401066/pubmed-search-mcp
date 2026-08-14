"""Metadata-only Semantic Scholar Datasets API data-plane client.

This module intentionally stops at release, partition-manifest, and diff
metadata.  It never downloads the multi-gigabyte data files and is not wired as
an MCP tool or source-registry entry.
"""

from __future__ import annotations

import urllib.parse
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pubmed_search.infrastructure.sources.base_client import BaseAPIClient

S2_DATASETS_API_BASE = "https://api.semanticscholar.org/datasets/v1"
DatasetModelT = TypeVar("DatasetModelT", bound=BaseModel)


class SemanticScholarDatasetResponseError(RuntimeError):
    """Sanitized schema/empty-response failure for operator workflows."""


class SemanticScholarDatasetSummary(BaseModel):
    """Dataset metadata embedded in a release catalog."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    description: str = ""
    readme: str = Field(default="", alias="README")


class SemanticScholarReleaseManifest(BaseModel):
    """One immutable release catalog and its licensing README."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    release_id: str
    readme: str = Field(default="", alias="README")
    datasets: list[SemanticScholarDatasetSummary] = Field(default_factory=list)


class SemanticScholarDatasetManifest(SemanticScholarDatasetSummary):
    """Dataset metadata plus temporary pre-signed partition URLs."""

    files: list[str] = Field(default_factory=list, repr=False)


class SemanticScholarDatasetDiff(BaseModel):
    """Changes between two sequential Semantic Scholar releases."""

    from_release: str
    to_release: str
    update_files: list[str] = Field(default_factory=list, repr=False)
    delete_files: list[str] = Field(default_factory=list, repr=False)


class SemanticScholarDatasetDiffManifest(BaseModel):
    """Ordered diff chain needed to advance one local dataset release."""

    dataset: str
    start_release: str
    end_release: str
    diffs: list[SemanticScholarDatasetDiff] = Field(default_factory=list)


class SemanticScholarDatasetsClient(BaseAPIClient):
    """Fetch Datasets API control-plane metadata without downloading files."""

    _service_name = "Semantic Scholar"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0) -> None:
        self._api_key = api_key.strip() if isinstance(api_key, str) and api_key.strip() else None
        super().__init__(
            timeout=timeout,
            min_interval=1.0,
            strict_errors=True,
            headers={
                "User-Agent": "pubmed-search-mcp/1.0",
                "Accept": "application/json",
            },
            follow_redirects=False,
        )

    async def _execute_request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        request_headers = dict(headers or {})
        if self._api_key:
            request_headers["x-api-key"] = self._api_key
        return await super()._execute_request(
            url,
            method=method,
            data=data,
            params=params,
            headers=request_headers,
        )

    async def list_releases(self) -> list[str]:
        """List release identifiers; this official endpoint needs no API key."""

        # This official endpoint is an array-root JSON response.
        payload: Any = await self._make_request(f"{S2_DATASETS_API_BASE}/release/")
        if not isinstance(payload, list):
            raise SemanticScholarDatasetResponseError("Semantic Scholar release catalog response was invalid")
        return [release for release in payload if isinstance(release, str)]

    async def get_release_manifest(self, release_id: str = "latest") -> SemanticScholarReleaseManifest | None:
        """Fetch a release catalog and the exact upstream licensing READMEs."""

        encoded_release = self._encode_component(release_id, name="release_id")
        payload = await self._make_request(f"{S2_DATASETS_API_BASE}/release/{encoded_release}")
        if not isinstance(payload, dict):
            raise SemanticScholarDatasetResponseError("Semantic Scholar release manifest response was invalid")
        manifest = _validate_response_model(SemanticScholarReleaseManifest, payload)
        if manifest is None:
            raise SemanticScholarDatasetResponseError("Semantic Scholar release manifest response was invalid")
        return manifest

    async def get_dataset_manifest(
        self,
        release_id: str,
        dataset_name: str,
    ) -> SemanticScholarDatasetManifest | None:
        """Fetch temporary partition URLs; never download their contents."""

        self._require_api_key("dataset partition manifests")
        encoded_release = self._encode_component(release_id, name="release_id")
        encoded_dataset = self._encode_component(dataset_name, name="dataset_name")
        url = f"{S2_DATASETS_API_BASE}/release/{encoded_release}/dataset/{encoded_dataset}"
        payload = await self._make_request(url)
        if not isinstance(payload, dict):
            raise SemanticScholarDatasetResponseError("Semantic Scholar dataset manifest response was invalid")
        manifest = _validate_response_model(SemanticScholarDatasetManifest, payload)
        if manifest is None:
            raise SemanticScholarDatasetResponseError("Semantic Scholar dataset manifest response was invalid")
        return manifest

    async def get_diff_manifest(
        self,
        start_release_id: str,
        end_release_id: str,
        dataset_name: str,
    ) -> SemanticScholarDatasetDiffManifest | None:
        """Fetch the ordered update/delete manifest between two releases."""

        self._require_api_key("dataset diff manifests")
        encoded_start = self._encode_component(start_release_id, name="start_release_id")
        encoded_end = self._encode_component(end_release_id, name="end_release_id")
        encoded_dataset = self._encode_component(dataset_name, name="dataset_name")
        url = f"{S2_DATASETS_API_BASE}/diffs/{encoded_start}/to/{encoded_end}/{encoded_dataset}"
        payload = await self._make_request(url)
        if not isinstance(payload, dict):
            raise SemanticScholarDatasetResponseError("Semantic Scholar diff manifest response was invalid")
        manifest = _validate_response_model(SemanticScholarDatasetDiffManifest, payload)
        if manifest is None:
            raise SemanticScholarDatasetResponseError("Semantic Scholar diff manifest response was invalid")
        return manifest

    def _require_api_key(self, operation: str) -> None:
        if not self._api_key:
            raise ValueError(f"Semantic Scholar {operation} require an API key")

    @staticmethod
    def _encode_component(value: str, *, name: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{name} must not be empty")
        return urllib.parse.quote(normalized, safe="")


def _validate_response_model(
    model_type: type[DatasetModelT],
    payload: dict[str, Any],
) -> DatasetModelT | None:
    """Validate outside the raising frame so signed URLs cannot survive in exception context."""

    try:
        return model_type.model_validate(payload)
    except ValidationError:
        return None


__all__ = [
    "S2_DATASETS_API_BASE",
    "SemanticScholarDatasetResponseError",
    "SemanticScholarDatasetDiff",
    "SemanticScholarDatasetDiffManifest",
    "SemanticScholarDatasetManifest",
    "SemanticScholarDatasetSummary",
    "SemanticScholarDatasetsClient",
    "SemanticScholarReleaseManifest",
]
