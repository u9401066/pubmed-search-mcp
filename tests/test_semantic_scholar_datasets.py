"""Synthetic Datasets API control-plane contract tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pubmed_search.infrastructure.sources.semantic_scholar_datasets import (
    SemanticScholarDatasetDiff,
    SemanticScholarDatasetManifest,
    SemanticScholarDatasetResponseError,
    SemanticScholarDatasetsClient,
)


@pytest.mark.asyncio
async def test_release_catalog_and_manifest_need_no_key() -> None:
    client = SemanticScholarDatasetsClient()
    client._min_interval = 0
    client._make_request = AsyncMock(
        side_effect=[
            ["2026-07-28", "2026-08-05", 123],
            {
                "release_id": "2026-08-05",
                "README": "release terms",
                "datasets": [
                    {
                        "name": "papers",
                        "description": "Core paper metadata",
                        "README": "ODC-BY attribution",
                    }
                ],
            },
        ]
    )
    try:
        releases = await client.list_releases()
        manifest = await client.get_release_manifest("latest")
    finally:
        await client.close()

    assert releases == ["2026-07-28", "2026-08-05"]
    assert manifest is not None
    assert manifest.release_id == "2026-08-05"
    assert manifest.readme == "release terms"
    assert manifest.datasets[0].readme == "ODC-BY attribution"
    assert client._make_request.await_args_list[0].args[0].endswith("/release/")
    assert client._make_request.await_args_list[1].args[0].endswith("/release/latest")


@pytest.mark.asyncio
async def test_dataset_partition_manifest_is_metadata_only_and_keyed() -> None:
    no_key_client = SemanticScholarDatasetsClient()
    try:
        with pytest.raises(ValueError, match="API key"):
            await no_key_client.get_dataset_manifest("latest", "papers")
    finally:
        await no_key_client.close()

    client = SemanticScholarDatasetsClient(api_key="secret")
    client._min_interval = 0
    client._make_request = AsyncMock(
        return_value={
            "name": "papers",
            "description": "Core paper metadata",
            "README": "ODC-BY attribution",
            "files": ["https://signed.example/part-1.gz", "https://signed.example/part-2.gz"],
        }
    )
    try:
        manifest = await client.get_dataset_manifest("2026-08-05", "papers")
    finally:
        await client.close()

    assert manifest is not None
    assert manifest.files == [
        "https://signed.example/part-1.gz",
        "https://signed.example/part-2.gz",
    ]
    assert client._make_request.await_count == 1
    assert "/release/2026-08-05/dataset/papers" in client._make_request.await_args.args[0]


@pytest.mark.asyncio
async def test_diff_manifest_preserves_ordered_update_and_delete_files() -> None:
    client = SemanticScholarDatasetsClient(api_key="secret")
    client._min_interval = 0
    client._make_request = AsyncMock(
        return_value={
            "dataset": "papers",
            "start_release": "2026-07-21",
            "end_release": "2026-08-05",
            "diffs": [
                {
                    "from_release": "2026-07-21",
                    "to_release": "2026-07-28",
                    "update_files": ["https://signed.example/update-1.gz"],
                    "delete_files": ["https://signed.example/delete-1.gz"],
                },
                {
                    "from_release": "2026-07-28",
                    "to_release": "2026-08-05",
                    "update_files": ["https://signed.example/update-2.gz"],
                    "delete_files": [],
                },
            ],
        }
    )
    try:
        manifest = await client.get_diff_manifest("2026-07-21", "latest", "papers")
    finally:
        await client.close()

    assert manifest is not None
    assert [diff.to_release for diff in manifest.diffs] == ["2026-07-28", "2026-08-05"]
    assert manifest.diffs[0].delete_files == ["https://signed.example/delete-1.gz"]
    assert "/diffs/2026-07-21/to/latest/papers" in client._make_request.await_args.args[0]


@pytest.mark.asyncio
async def test_dataset_client_does_not_offer_a_download_method() -> None:
    client = SemanticScholarDatasetsClient(api_key="secret")
    try:
        assert not hasattr(client, "download")
        assert not hasattr(client, "download_dataset")
    finally:
        await client.close()


def test_presigned_partition_urls_are_redacted_from_model_repr() -> None:
    signature = "X-Amz-Signature=secret"
    dataset = SemanticScholarDatasetManifest(
        name="papers",
        files=[f"https://signed.example/part.gz?{signature}"],
    )
    diff = SemanticScholarDatasetDiff(
        from_release="2026-08-01",
        to_release="2026-08-08",
        update_files=[f"https://signed.example/update.gz?{signature}"],
        delete_files=[f"https://signed.example/delete.gz?{signature}"],
    )

    assert signature not in repr(dataset)
    assert signature not in repr(diff)
    assert signature in dataset.files[0]


@pytest.mark.asyncio
async def test_operator_control_plane_does_not_turn_failure_into_empty_catalog() -> None:
    client = SemanticScholarDatasetsClient()
    client._make_request = AsyncMock(return_value=None)
    try:
        with pytest.raises(SemanticScholarDatasetResponseError, match="catalog response was invalid"):
            await client.list_releases()
    finally:
        await client.close()


@pytest.mark.parametrize(
    ("method_name", "args", "payload"),
    [
        (
            "get_dataset_manifest",
            ("2026-08-05", "papers"),
            {"files": ["https://signed.example/part.gz?X-Amz-Credential=SENTINEL"]},
        ),
        (
            "get_diff_manifest",
            ("2026-08-01", "2026-08-05", "papers"),
            {
                "diffs": [
                    {
                        "from_release": "2026-08-01",
                        "to_release": "2026-08-05",
                        "update_files": ["https://signed.example/update.gz?X-Amz-Credential=SENTINEL"],
                    }
                ]
            },
        ),
    ],
)
@pytest.mark.asyncio
async def test_schema_validation_errors_do_not_retain_presigned_urls(
    method_name: str,
    args: tuple[str, ...],
    payload: dict[str, object],
) -> None:
    client = SemanticScholarDatasetsClient(api_key="secret")
    client._make_request = AsyncMock(return_value=payload)
    try:
        with pytest.raises(SemanticScholarDatasetResponseError) as error_info:
            await getattr(client, method_name)(*args)
    finally:
        await client.close()

    error = error_info.value
    assert "SENTINEL" not in str(error)
    assert "SENTINEL" not in repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None
