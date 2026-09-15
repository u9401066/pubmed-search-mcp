"""
Tests for biomedical image search (Phase 4.1).

Tests:
- Domain: ImageResult entity
- Infrastructure: OpenIClient mapper
- Application: ImageSearchService
- Presentation: search_biomedical_images tool
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.image_search import (
    ImageSearchService,
    ImageSourceCoverage,
    ImageSourceCoverageError,
)
from pubmed_search.application.image_search.source_adapters import (
    ImageProviderResponseError,
    ImageProviderSearchResult,
    build_image_source_registry,
)
from pubmed_search.domain.entities.image import ImageResult, ImageSource
from pubmed_search.infrastructure.sources.openi import OpenIClient
from pubmed_search.shared.source_contracts import SourceAdapterResult

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_openi_response():
    """Sample Open-i API response for testing."""
    return {
        "total": 42,
        "list": [
            {
                "uid": "openi-001",
                "pmid": "12345678",
                "pmcid": "PMC1234567",
                "title": "Chest X-ray findings in pneumonia patients",
                "journal_title": "Radiology",
                "authors": "Smith J, Doe A",
                "imgLarge": "/imgs/large/12345.png",
                "imgThumb": "/imgs/thumb/12345.png",
                "image": {"caption": "PA chest radiograph showing bilateral infiltrates"},
                "MeSH": {
                    "major": ["Pneumonia", "Radiography, Thoracic"],
                    "minor": ["Adult", "Humans"],
                },
            },
            {
                "uid": "openi-002",
                "pmid": "87654321",
                "title": "Normal chest anatomy",
                "journal_title": "Journal of Anatomy",
                "authors": "Lee K",
                "imgLarge": "/imgs/large/67890.png",
                "imgThumb": "",
                "image": {"caption": "Normal chest X-ray"},
                "MeSH": {"major": ["Thorax"], "minor": []},
            },
        ],
    }


@pytest.fixture
def empty_openi_response():
    """Empty Open-i API response."""
    return {"total": 0, "list": []}


@pytest.fixture
def openi_client():
    """Create an OpenIClient instance for testing."""
    client = OpenIClient(timeout=5.0)
    client._min_interval = 0  # Disable rate limiting in tests
    return client


def _image_search_service(client: Any | None = None) -> ImageSearchService:
    """Compose the application service with an explicit test client factory."""
    resolved_client = client if client is not None else AsyncMock()
    if client is None:
        resolved_client.search.return_value = _provider_result([], 0)
    return ImageSearchService(
        adapters=build_image_source_registry(
            openi_client_factory=lambda: resolved_client,
        )
    )


def _provider_result(images: list[ImageResult], total: int) -> ImageProviderSearchResult:
    """Build a strict provider outcome for application-service tests."""

    return ImageProviderSearchResult(
        images=images,
        total_count=total,
        status="ok" if images else "empty",
        rows_received=len(images),
        pages_fetched=1,
    )


# ============================================================================
# Domain Layer Tests
# ============================================================================


class TestImageResult:
    """Tests for ImageResult domain entity."""

    async def test_basic_creation(self):
        img = ImageResult(
            image_url="https://example.com/img.png",
            caption="Test image",
            source=ImageSource.OPENI,
        )
        assert img.image_url == "https://example.com/img.png"
        assert img.caption == "Test image"
        assert img.source == ImageSource.OPENI

    async def test_has_article_link_with_pmid(self):
        img = ImageResult(image_url="", pmid="12345")
        assert img.has_article_link is True

    async def test_has_article_link_with_pmcid(self):
        img = ImageResult(image_url="", pmcid="PMC123")
        assert img.has_article_link is True

    async def test_has_article_link_with_doi(self):
        img = ImageResult(image_url="", doi="10.1234/test")
        assert img.has_article_link is True

    async def test_has_article_link_none(self):
        img = ImageResult(image_url="")
        assert img.has_article_link is False

    async def test_best_identifier_pmid(self):
        img = ImageResult(image_url="", pmid="12345", pmcid="PMC123")
        assert img.best_identifier == "PMID:12345"

    async def test_best_identifier_pmcid(self):
        img = ImageResult(image_url="", pmcid="PMC123")
        assert img.best_identifier == "PMC123"

    async def test_best_identifier_doi(self):
        img = ImageResult(image_url="", doi="10.1234/test")
        assert img.best_identifier == "DOI:10.1234/test"

    async def test_best_identifier_source_id(self):
        img = ImageResult(image_url="", source_id="uid-123")
        assert img.best_identifier == "uid-123"

    async def test_to_dict(self):
        img = ImageResult(
            image_url="https://example.com/img.png",
            pmid="12345",
            source=ImageSource.OPENI,
            mesh_terms=["Pneumonia"],
        )
        d = img.to_dict()
        assert d["image_url"] == "https://example.com/img.png"
        assert d["pmid"] == "12345"
        assert d["source"] == ImageSource.OPENI
        assert d["mesh_terms"] == ["Pneumonia"]

    async def test_default_values(self):
        img = ImageResult(image_url="https://example.com/img.png")
        assert img.caption == ""
        assert img.label == ""
        assert img.mesh_terms == []
        assert img.image_type is None
        assert img.pub_year is None


class TestImageSource:
    """Tests for ImageSource enum."""

    async def test_enum_values(self):
        assert ImageSource.OPENI == "openi"
        assert ImageSource.MEDPIX == "medpix"

    async def test_is_string(self):
        # str, Enum — can be used as string
        assert isinstance(ImageSource.OPENI, str)


# ============================================================================
# Infrastructure Layer Tests
# ============================================================================


class TestOpenIClientMapper:
    """Tests for OpenIClient._map_to_image_result mapper."""

    async def test_map_full_item(self, sample_openi_response):
        item = sample_openi_response["list"][0]
        result = OpenIClient._map_to_image_result(item)

        assert isinstance(result, ImageResult)
        assert result.source == ImageSource.OPENI
        assert result.source_id == "openi-001"
        assert result.pmid == "12345678"
        assert result.pmcid == "PMC1234567"
        assert result.article_title == "Chest X-ray findings in pneumonia patients"
        assert result.journal == "Radiology"
        assert result.authors == "Smith J, Doe A"
        assert "https://openi.nlm.nih.gov/imgs/large/12345.png" in result.image_url
        assert "https://openi.nlm.nih.gov/imgs/thumb/12345.png" in result.thumbnail_url
        assert result.caption == "PA chest radiograph showing bilateral infiltrates"

    async def test_map_missing_thumbnail(self, sample_openi_response):
        item = sample_openi_response["list"][1]
        result = OpenIClient._map_to_image_result(item)

        # Empty imgThumb → None
        assert result.thumbnail_url is None

    async def test_map_empty_item(self):
        with pytest.raises(TypeError, match="required text"):
            OpenIClient._map_to_image_result({})

    async def test_map_image_caption_not_dict(self):
        item = {"image": "not a dict", "uid": "test", "imgLarge": "/img/test.png"}
        with pytest.raises(TypeError, match="image metadata"):
            OpenIClient._map_to_image_result(item)


class TestOpenIClientMeSH:
    """Tests for OpenIClient._extract_mesh."""

    async def test_extract_mesh_full(self, sample_openi_response):
        item = sample_openi_response["list"][0]
        terms = OpenIClient._extract_mesh(item)
        assert "Pneumonia" in terms
        assert "Radiography, Thoracic" in terms
        assert "Adult" in terms
        assert "Humans" in terms

    async def test_extract_mesh_empty(self):
        assert OpenIClient._extract_mesh({}) == []

    async def test_extract_mesh_not_dict(self):
        with pytest.raises(TypeError, match="MeSH metadata"):
            OpenIClient._extract_mesh({"MeSH": "invalid"})

    async def test_extract_mesh_invalid_lists(self):
        item = {"MeSH": {"major": "not-a-list", "minor": 42}}
        with pytest.raises(TypeError, match="MeSH terms"):
            OpenIClient._extract_mesh(item)


class TestOpenIClientSearch:
    """Tests for OpenIClient.search with mocked HTTP."""

    async def test_search_success(self, openi_client, sample_openi_response):
        with patch.object(openi_client, "_make_request", return_value=sample_openi_response):
            outcome = await openi_client.search("chest pneumonia", max_results=10)

        assert outcome.status == "ok"
        assert outcome.total_count == 42
        assert len(outcome.images) == 2
        assert outcome.images[0].pmid == "12345678"

    async def test_search_empty_query(self, openi_client):
        with pytest.raises(ValueError, match="must not be empty"):
            await openi_client.search("")

    async def test_search_empty_results(self, openi_client, empty_openi_response):
        with patch.object(openi_client, "_make_request", return_value=empty_openi_response):
            outcome = await openi_client.search("nonexistent query")

        assert outcome.status == "empty"
        assert outcome.total_count == 0
        assert outcome.images == []

    async def test_search_request_failure(self, openi_client):
        with patch.object(openi_client, "_make_request", return_value=None):
            with pytest.raises(ImageProviderResponseError, match="response validation failed"):
                await openi_client.search("test")

    @pytest.mark.parametrize(
        "payload",
        [
            {"list": []},
            {"total": 0},
            {"total": True, "list": []},
            {"total": -1, "list": []},
            {"total": "0", "list": []},
            {"total": 0, "list": {}},
            {"total": 1, "list": []},
        ],
    )
    async def test_search_malformed_envelope_is_not_empty(self, openi_client, payload):
        with patch.object(openi_client, "_make_request", return_value=payload):
            with pytest.raises(ImageProviderResponseError, match="response validation failed"):
                await openi_client.search("test")

    async def test_search_partial_bad_rows_has_typed_sanitized_issue(
        self,
        openi_client,
        sample_openi_response,
        caplog,
    ):
        secret = "token=private-openi-row-marker"
        response = {
            "total": 2,
            "list": [
                sample_openi_response["list"][0],
                {"uid": secret, "imgLarge": 42},
            ],
        }

        with patch.object(openi_client, "_make_request", return_value=response):
            outcome = await openi_client.search("test")

        assert outcome.status == "partial"
        assert len(outcome.images) == 1
        assert outcome.rows_received == 2
        assert outcome.rejected_rows == 1
        assert outcome.issues[0].kind == "malformed_rows"
        assert secret not in str(outcome)
        assert secret not in caplog.text

    async def test_search_all_bad_rows_fails_closed(self, openi_client):
        response = {
            "total": 1,
            "list": [{"uid": "bad-row", "imgLarge": 42}],
        }

        with patch.object(openi_client, "_make_request", return_value=response):
            with pytest.raises(ImageProviderResponseError, match="response validation failed"):
                await openi_client.search("test")

    async def test_search_raw_error_payload_is_sanitized(self, openi_client, caplog):
        secret = "token=secret-provider-payload /srv/private/openi"
        with patch.object(openi_client, "_make_request", return_value={"error": secret}):
            with pytest.raises(ImageProviderResponseError) as exc_info:
                await openi_client.search("test")

        assert secret not in str(exc_info.value)
        assert secret not in caplog.text

    async def test_search_default_image_type(self, openi_client, sample_openi_response):
        """When no image_type specified, defaults to None (all types)."""
        with patch.object(openi_client, "_make_request", return_value=sample_openi_response) as mock_req:
            await openi_client.search("test")
            call_url = mock_req.call_args[0][0]
            # No 'it' parameter when None
            assert "it=" not in call_url

    async def test_search_invalid_image_type_is_rejected(self, openi_client):
        with pytest.raises(ValueError, match="image_type"):
            await openi_client.search("test", image_type="invalid")

    async def test_search_valid_image_type(self, openi_client, sample_openi_response):
        with patch.object(openi_client, "_make_request", return_value=sample_openi_response) as mock_req:
            await openi_client.search("test", image_type="xg")
            call_url = mock_req.call_args[0][0]
            assert "it=xg" in call_url

    async def test_search_photo_image_type(self, openi_client, sample_openi_response):
        """'ph' (Photo) is a valid image type."""
        with patch.object(openi_client, "_make_request", return_value=sample_openi_response) as mock_req:
            await openi_client.search("test", image_type="ph")
            call_url = mock_req.call_args[0][0]
            assert "it=ph" in call_url

    async def test_search_graphics_image_type(self, openi_client, sample_openi_response):
        """'g' (Graphics) is a valid image type."""
        with patch.object(openi_client, "_make_request", return_value=sample_openi_response) as mock_req:
            await openi_client.search("test", image_type="g")
            call_url = mock_req.call_args[0][0]
            assert "it=g" in call_url

    async def test_search_valid_collection(self, openi_client, sample_openi_response):
        with patch.object(openi_client, "_make_request", return_value=sample_openi_response) as mock_req:
            await openi_client.search("test", collection="mpx")
            call_url = mock_req.call_args[0][0]
            assert "coll=mpx" in call_url

    async def test_search_respects_max_results(self, openi_client):
        """max_results=1 should only return 1 image even if API returns more."""
        response = {
            "total": 100,
            "list": [{"uid": f"img-{i}", "imgLarge": f"/img/{i}.png"} for i in range(10)],
        }
        with patch.object(openi_client, "_make_request", return_value=response):
            outcome = await openi_client.search("test", max_results=1)

        assert len(outcome.images) == 1
        assert outcome.total_count == 100

    # ═══════════════════════════════════════════════════════════════════════════
    # New API Parameters Tests (v0.3.4)
    # ═══════════════════════════════════════════════════════════════════════════

    async def test_search_sort_by_date(self, openi_client, sample_openi_response):
        """sort_by='d' should add favor=d parameter."""
        with patch.object(openi_client, "_make_request", return_value=sample_openi_response) as mock_req:
            await openi_client.search("test", sort_by="d")
            call_url = mock_req.call_args[0][0]
            assert "favor=d" in call_url

    async def test_search_sort_by_relevance(self, openi_client, sample_openi_response):
        """sort_by='r' should add favor=r parameter."""
        with patch.object(openi_client, "_make_request", return_value=sample_openi_response) as mock_req:
            await openi_client.search("test", sort_by="r")
            call_url = mock_req.call_args[0][0]
            assert "favor=r" in call_url

    async def test_search_invalid_sort_by_is_rejected(self, openi_client):
        with pytest.raises(ValueError, match="sort_by"):
            await openi_client.search("test", sort_by="invalid")

    async def test_search_article_type_case_report(self, openi_client, sample_openi_response):
        """article_type='cr' should add at=cr parameter."""
        with patch.object(openi_client, "_make_request", return_value=sample_openi_response) as mock_req:
            await openi_client.search("test", article_type="cr")
            call_url = mock_req.call_args[0][0]
            assert "at=cr" in call_url

    async def test_search_invalid_article_type_is_rejected(self, openi_client):
        with pytest.raises(ValueError, match="article_type"):
            await openi_client.search("test", article_type="invalid")

    async def test_search_specialty_radiology(self, openi_client, sample_openi_response):
        """specialty='r' should add sp=r parameter."""
        with patch.object(openi_client, "_make_request", return_value=sample_openi_response) as mock_req:
            await openi_client.search("test", specialty="r")
            call_url = mock_req.call_args[0][0]
            assert "sp=r" in call_url

    async def test_search_specialty_cardiology(self, openi_client, sample_openi_response):
        """specialty='c' should add sp=c parameter."""
        with patch.object(openi_client, "_make_request", return_value=sample_openi_response) as mock_req:
            await openi_client.search("test", specialty="c")
            call_url = mock_req.call_args[0][0]
            assert "sp=c" in call_url

    async def test_search_invalid_specialty_is_rejected(self, openi_client):
        with pytest.raises(ValueError, match="specialty"):
            await openi_client.search("test", specialty="invalid")

    async def test_search_license_cc_by(self, openi_client, sample_openi_response):
        """license_type='by' should add lic=by parameter."""
        with patch.object(openi_client, "_make_request", return_value=sample_openi_response) as mock_req:
            await openi_client.search("test", license_type="by")
            call_url = mock_req.call_args[0][0]
            assert "lic=by" in call_url

    async def test_search_license_cc_by_nc(self, openi_client, sample_openi_response):
        """license_type='bync' should add lic=bync parameter."""
        with patch.object(openi_client, "_make_request", return_value=sample_openi_response) as mock_req:
            await openi_client.search("test", license_type="bync")
            call_url = mock_req.call_args[0][0]
            assert "lic=bync" in call_url

    async def test_search_invalid_license_is_rejected(self, openi_client):
        with pytest.raises(ValueError, match="license_type"):
            await openi_client.search("test", license_type="invalid")

    async def test_search_subset_cancer(self, openi_client, sample_openi_response):
        """subset='c' should add sub=c parameter."""
        with patch.object(openi_client, "_make_request", return_value=sample_openi_response) as mock_req:
            await openi_client.search("test", subset="c")
            call_url = mock_req.call_args[0][0]
            assert "sub=c" in call_url

    async def test_search_invalid_subset_is_rejected(self, openi_client):
        with pytest.raises(ValueError, match="subset"):
            await openi_client.search("test", subset="invalid")

    async def test_search_fields_title(self, openi_client, sample_openi_response):
        """search_fields='t' should add fields=t parameter."""
        with patch.object(openi_client, "_make_request", return_value=sample_openi_response) as mock_req:
            await openi_client.search("test", search_fields="t")
            call_url = mock_req.call_args[0][0]
            assert "fields=t" in call_url

    async def test_search_fields_caption(self, openi_client, sample_openi_response):
        """search_fields='c' should add fields=c parameter."""
        with patch.object(openi_client, "_make_request", return_value=sample_openi_response) as mock_req:
            await openi_client.search("test", search_fields="c")
            call_url = mock_req.call_args[0][0]
            assert "fields=c" in call_url

    async def test_search_invalid_fields_is_rejected(self, openi_client):
        with pytest.raises(ValueError, match="search_fields"):
            await openi_client.search("test", search_fields="invalid")

    async def test_search_video_only(self, openi_client, sample_openi_response):
        """video_only=True should add vid=1 parameter."""
        with patch.object(openi_client, "_make_request", return_value=sample_openi_response) as mock_req:
            await openi_client.search("test", video_only=True)
            call_url = mock_req.call_args[0][0]
            assert "vid=1" in call_url

    async def test_search_video_only_false(self, openi_client, sample_openi_response):
        """video_only=False should NOT add vid parameter."""
        with patch.object(openi_client, "_make_request", return_value=sample_openi_response) as mock_req:
            await openi_client.search("test", video_only=False)
            call_url = mock_req.call_args[0][0]
            assert "vid=" not in call_url

    async def test_search_combined_filters(self, openi_client, sample_openi_response):
        """Multiple filters should be combined in URL."""
        with patch.object(openi_client, "_make_request", return_value=sample_openi_response) as mock_req:
            await openi_client.search(
                "test",
                image_type="xg",
                collection="pmc",
                sort_by="d",
                article_type="cr",
                specialty="r",
                license_type="by",
            )
            call_url = mock_req.call_args[0][0]
            assert "it=xg" in call_url
            assert "coll=pmc" in call_url
            assert "favor=d" in call_url
            assert "at=cr" in call_url
            assert "sp=r" in call_url
            assert "lic=by" in call_url


# ============================================================================
# Application Layer Tests
# ============================================================================


class TestImageSearchService:
    """Tests for ImageSearchService application service."""

    async def test_search_empty_query(self):
        service = _image_search_service()
        with pytest.raises(ValueError, match="must not be empty"):
            await service.search("")

    async def test_search_delegates_to_openi(self, sample_openi_response):
        mock_client = AsyncMock()
        mock_images = [
            ImageResult(image_url="https://openi.nlm.nih.gov/img/1.png", pmid="123"),
        ]
        mock_client.search.return_value = _provider_result(mock_images, 1)
        service = _image_search_service(mock_client)

        result = await service.search("chest pneumonia")

        assert len(result.images) == 1
        assert result.total_count == 1
        assert "openi" in result.sources_used
        assert result.search_status == "completed"
        assert result.coverage()["status"] == "completed"
        assert result.source_coverage[0].status == "ok"

    async def test_search_verified_zero_is_empty_with_responding_source(self):
        service = _image_search_service()

        result = await service.search("no matches")

        assert result.search_status == "empty"
        assert result.images == []
        assert result.total_count == 0
        assert result.sources_used == ["openi"]
        assert result.errors == []
        assert result.source_counts == {"openi": 0}
        assert result.source_coverage[0].status == "empty"
        assert result.source_coverage[0].total_available == 0
        assert result.source_coverage[0].response_complete is True

    async def test_search_handles_error(self):
        def failing_factory() -> Any:
            raise RuntimeError("Connection failed")

        from pubmed_search.application.image_search.source_adapters import OpenIImageSourceAdapter

        service = ImageSearchService(adapters={"openi": OpenIImageSourceAdapter(client_factory=failing_factory)})

        result = await service.search("test")

        assert result.images == []
        assert len(result.errors) == 1
        assert result.errors == ["openi: Source adapter failed"]
        assert result.search_status == "failed"
        assert result.sources_used == []
        assert result.source_coverage[0].total_available is None
        assert result.source_coverage[0].error_kinds == ("unexpected",)

    async def test_search_preserves_typed_partial_openi_coverage(
        self,
        openi_client,
        sample_openi_response,
    ):
        response = {
            "total": 2,
            "list": [
                sample_openi_response["list"][0],
                {"uid": "bad-row", "imgLarge": 42},
            ],
        }
        service = _image_search_service(openi_client)

        with patch.object(openi_client, "_make_request", return_value=response):
            result = await service.search("test")

        assert result.search_status == "partial"
        assert result.sources_used == ["openi"]
        assert result.source_counts == {"openi": 1}
        assert result.errors == ["openi: Open-i returned malformed result rows"]
        coverage = result.source_coverage[0]
        assert coverage.status == "partial"
        assert coverage.returned == 1
        assert coverage.total_available == 2
        assert coverage.rows_received == 2
        assert coverage.rows_rejected == 1
        assert coverage.response_complete is False

    async def test_search_outage_and_secret_are_failed_unknown_coverage(self):
        secret = "token=private-openi-key /srv/private/openi-cache"
        mock_client = AsyncMock()
        mock_client.search.side_effect = RuntimeError(secret)
        service = _image_search_service(mock_client)

        result = await service.search("test")

        assert result.search_status == "failed"
        assert result.images == []
        assert result.total_count == 0
        assert result.sources_used == []
        assert result.errors == ["openi: Source adapter failed"]
        assert result.source_coverage[0].status == "error"
        assert result.source_coverage[0].total_available is None
        assert result.source_coverage[0].error_kinds == ("unexpected",)
        assert secret not in str(result.coverage())
        assert secret not in str(result.errors)

    async def test_search_malformed_openi_envelope_is_failed_not_empty(self, openi_client):
        service = _image_search_service(openi_client)

        with patch.object(openi_client, "_make_request", return_value={"total": 0}):
            result = await service.search("test")

        assert result.search_status == "failed"
        assert result.sources_used == []
        assert result.source_coverage[0].status == "error"
        assert result.source_coverage[0].total_available is None
        assert result.source_coverage[0].error_kinds == ("validation",)

    async def test_search_uses_injected_source_adapters(self):
        from pubmed_search.application.image_search import ImageSearchService

        class StubAdapter:
            def __init__(self, images, total):
                self.search = AsyncMock(
                    return_value=SourceAdapterResult(
                        source="openi",
                        operation="search_images",
                        items=images,
                        total_count=total,
                        status="ok" if images else "empty",
                    )
                )

        images = [
            ImageResult(image_url="https://example.org/img.png", pmid="123", source_id="img-1"),
        ]
        adapter = StubAdapter(images, 1)
        service = ImageSearchService(adapters={"openi": adapter})

        result = await service.search("test")

        adapter.search.assert_awaited_once()
        assert result.images == images
        assert result.total_count == 1
        assert result.sources_used == ["openi"]

    async def test_search_preserves_partial_failures_from_adapters(self):
        from pubmed_search.application.image_search import ImageSearchService

        class StubAdapter:
            def __init__(self, *, result=None, error=None):
                self.search = AsyncMock()
                if error is not None:
                    self.search.side_effect = error
                else:
                    self.search.return_value = result

        ok_images = [
            ImageResult(image_url="https://example.org/ok.png", pmid="123", source_id="ok-1"),
        ]
        adapters = {
            "openi": StubAdapter(
                result=SourceAdapterResult(
                    source="openi",
                    operation="search_images",
                    items=ok_images,
                    total_count=1,
                )
            ),
            "europe_pmc": StubAdapter(error=RuntimeError("adapter offline")),
        }
        service = ImageSearchService(adapters=adapters)

        result = await service.search("test", sources=["openi", "europe_pmc"])

        assert result.total_count == 1
        assert len(result.images) == 1
        assert result.sources_used == ["openi"]
        assert result.errors == ["europe_pmc: Source adapter failed"]
        assert result.search_status == "partial"
        assert [coverage.status for coverage in result.source_coverage] == ["ok", "error"]

    async def test_resolve_sources_default(self):
        service = _image_search_service()
        sources = service._resolve_sources(None)
        assert sources == ["openi"]

    async def test_resolve_sources_explicit(self):
        service = _image_search_service()
        sources = service._resolve_sources(["openi"])
        assert sources == ["openi"]

    async def test_resolve_sources_invalid_fails_closed(self):
        service = _image_search_service()
        with pytest.raises(ValueError, match="Unknown biomedical image source"):
            service._resolve_sources(["invalid_source"])

    @pytest.mark.parametrize(
        ("sources", "message"),
        [
            (["OPENI"], "Unknown biomedical image source"),
            ([" openi"], "surrounding whitespace"),
            ([""], "non-empty canonical strings"),
            (["openi", "openi"], "Duplicate biomedical image source"),
        ],
    )
    async def test_resolve_sources_rejects_repaired_or_duplicate_tokens(self, sources, message):
        with pytest.raises(ValueError, match=message):
            _image_search_service()._resolve_sources(sources)

    async def test_deduplicate(self):
        images = [
            ImageResult(image_url="url1", pmid="123", source_id="a"),
            ImageResult(image_url="url2", pmid="123", source_id="a"),  # duplicate
            ImageResult(image_url="url3", pmid="456", source_id="b"),
        ]
        from pubmed_search.application.image_search.aggregation_kernel import ImageAggregationKernel

        result, _ = ImageAggregationKernel.deduplicate(images)
        assert len(result) == 2

    async def test_deduplicate_by_url(self):
        images = [
            ImageResult(image_url="same_url"),
            ImageResult(image_url="same_url"),  # duplicate by URL
        ]
        from pubmed_search.application.image_search.aggregation_kernel import ImageAggregationKernel

        result, _ = ImageAggregationKernel.deduplicate(images)
        assert len(result) == 1

    # ═══════════════════════════════════════════════════════════════════════════
    # New API Parameters Tests (v0.3.4)
    # ═══════════════════════════════════════════════════════════════════════════

    async def test_search_with_sort_by(self):
        """sort_by parameter should be passed to client."""
        mock_client = AsyncMock()
        mock_client.search.return_value = _provider_result([], 0)
        service = _image_search_service(mock_client)

        await service.search("test", sort_by="d")

        mock_client.search.assert_called_once()
        call_kwargs = mock_client.search.call_args[1]
        assert call_kwargs["sort_by"] == "d"

    async def test_search_with_article_type(self):
        """article_type parameter should be passed to client."""
        mock_client = AsyncMock()
        mock_client.search.return_value = _provider_result([], 0)
        service = _image_search_service(mock_client)

        await service.search("test", article_type="cr")

        call_kwargs = mock_client.search.call_args[1]
        assert call_kwargs["article_type"] == "cr"

    async def test_search_with_specialty(self):
        """specialty parameter should be passed to client."""
        mock_client = AsyncMock()
        mock_client.search.return_value = _provider_result([], 0)
        service = _image_search_service(mock_client)

        await service.search("test", specialty="r")

        call_kwargs = mock_client.search.call_args[1]
        assert call_kwargs["specialty"] == "r"

    async def test_search_with_license_type(self):
        """license_type parameter should be passed to client."""
        mock_client = AsyncMock()
        mock_client.search.return_value = _provider_result([], 0)
        service = _image_search_service(mock_client)

        await service.search("test", license_type="by")

        call_kwargs = mock_client.search.call_args[1]
        assert call_kwargs["license_type"] == "by"

    async def test_search_with_video_only(self):
        """video_only parameter should be passed to client."""
        mock_client = AsyncMock()
        mock_client.search.return_value = _provider_result([], 0)
        service = _image_search_service(mock_client)

        await service.search("test", video_only=True)

        call_kwargs = mock_client.search.call_args[1]
        assert call_kwargs["video_only"] is True

    async def test_search_tracks_applied_filters(self):
        """applied_filters should track all set filters."""
        mock_client = AsyncMock()
        mock_client.search.return_value = _provider_result([], 0)
        service = _image_search_service(mock_client)

        result = await service.search(
            "test",
            image_type="xg",
            sort_by="d",
            article_type="cr",
            specialty="r",
            license_type="by",
        )

        assert result.applied_filters["image_type"] == "xg"
        assert result.applied_filters["sort_by"] == "d"
        assert result.applied_filters["article_type"] == "cr"
        assert result.applied_filters["specialty"] == "r"
        assert result.applied_filters["license"] == "by"

    async def test_hmp_type_requires_history_of_medicine_collection(self):
        service = _image_search_service()
        with pytest.raises(ValueError, match="requires collection='hmd'"):
            await service.search("test", hmp_type="ar")

    async def test_search_with_all_new_parameters(self):
        """All new parameters should be passed to client."""
        mock_client = AsyncMock()
        mock_client.search.return_value = _provider_result([], 0)
        service = _image_search_service(mock_client)

        await service.search(
            "test",
            collection="hmd",
            sort_by="d",
            article_type="cr",
            specialty="r",
            license_type="by",
            subset="c",
            search_fields="t",
            video_only=True,
            hmp_type="ar",
        )

        call_kwargs = mock_client.search.call_args[1]
        assert call_kwargs["sort_by"] == "d"
        assert call_kwargs["article_type"] == "cr"
        assert call_kwargs["specialty"] == "r"
        assert call_kwargs["license_type"] == "by"
        assert call_kwargs["subset"] == "c"
        assert call_kwargs["search_fields"] == "t"
        assert call_kwargs["video_only"] is True
        assert call_kwargs["hmp_type"] == "ar"


# ============================================================================
# Presentation Layer Tests
# ============================================================================


class TestSearchBiomedicalImagesTool:
    """Tests for the search_biomedical_images MCP tool."""

    def _get_tool(
        self,
        *,
        search_result: Any = None,
        search_error: Exception | None = None,
    ) -> tuple[Any, MagicMock]:
        """Register and return the tool function."""
        from mcp.server.mcpserver import MCPServer

        mcp = MCPServer("test")
        from pubmed_search.presentation.mcp_server.tools.image_search import (
            register_image_search_tools,
        )

        service = MagicMock(spec=ImageSearchService)
        service.search = AsyncMock(return_value=search_result, side_effect=search_error)
        register_image_search_tools(mcp, service)

        # Get the registered tool function
        tools = mcp._tool_manager._tools
        assert "search_biomedical_images" in tools
        return tools["search_biomedical_images"].fn, service

    async def test_empty_query_returns_error(self):
        tool_fn, _service = self._get_tool()
        result = await tool_fn(query="")
        assert "Missing search query" in result

    async def test_successful_search(self):
        mock_images = [
            ImageResult(
                image_url="https://openi.nlm.nih.gov/img/1.png",
                caption="Chest X-ray",
                pmid="12345678",
                article_title="Test Article",
                source=ImageSource.OPENI,
            ),
        ]

        from pubmed_search.application.image_search import ImageSearchResult

        mock_result = ImageSearchResult(
            images=mock_images,
            total_count=1,
            sources_used=["openi"],
            query="chest pneumonia",
            search_status="completed",
            source_counts={"openi": 1},
            source_coverage=[
                ImageSourceCoverage(
                    source="openi",
                    status="ok",
                    returned=1,
                    total_available=1,
                    rows_received=1,
                    rows_rejected=0,
                    pages_fetched=1,
                    bounded=True,
                    has_more=False,
                    response_complete=True,
                )
            ],
            duplicates_removed=0,
        )
        tool_fn, _service = self._get_tool(search_result=mock_result)

        result = await tool_fn(query="chest pneumonia")

        assert "Image Search Results" in result
        assert "chest pneumonia" in result
        assert "12345678" in result
        assert "Chest X-ray" in result

    async def test_markdown_output_neutralizes_external_metadata(self):
        mock_images = [
            ImageResult(
                image_url="javascript:alert(1)",
                thumbnail_url="data:text/html,pwned",
                caption="caption\n# injected",
                article_title="[click](https://attacker.invalid)",
                journal="journal\n```mermaid",
                source=ImageSource.OPENI,
            ),
        ]

        from pubmed_search.application.image_search import ImageSearchResult

        mock_result = ImageSearchResult(
            images=mock_images,
            total_count=1,
            sources_used=["openi\n# source"],
            query="query\n# query",
            search_status="completed",
            source_counts={"openi": 1},
            source_coverage=[],
            duplicates_removed=0,
        )
        tool_fn, _service = self._get_tool(search_result=mock_result)

        result = await tool_fn(query="safe query")

        assert "javascript:" not in result
        assert "data:text" not in result
        assert "\n# injected" not in result
        assert "\n```mermaid" not in result
        assert "unsafe URL omitted" in result
        assert "\\[click\\]\\(https://attacker.invalid\\)" in result

    async def test_string_limit_is_rejected_without_coercion(self):
        from pubmed_search.application.image_search import ImageSearchResult

        mock_result = ImageSearchResult(
            images=[],
            total_count=0,
            sources_used=["openi"],
            query="test",
            search_status="empty",
            source_counts={"openi": 0},
            source_coverage=[],
            duplicates_removed=0,
        )
        tool_fn, service = self._get_tool(search_result=mock_result)

        result = await tool_fn(query="test", limit="5")

        assert "limit must be an integer" in result
        service.search.assert_not_awaited()

    async def test_total_provider_failure_is_not_reported_as_empty_success(self):
        from pubmed_search.application.image_search import ImageSearchResult

        failed = ImageSearchResult(
            images=[],
            total_count=0,
            sources_used=[],
            query="test",
            search_status="failed",
            source_counts={"openi": 0},
            source_coverage=[
                ImageSourceCoverage(
                    source="openi",
                    status="error",
                    returned=0,
                    total_available=None,
                    rows_received=None,
                    rows_rejected=0,
                    pages_fetched=None,
                    bounded=True,
                    has_more=None,
                    response_complete=False,
                    errors=(
                        ImageSourceCoverageError(
                            kind="timeout",
                            retryable=True,
                            status_code=None,
                        ),
                    ),
                )
            ],
            duplicates_removed=0,
            errors=["openi: source unavailable"],
        )
        tool_fn, _service = self._get_tool(search_result=failed)

        result = await tool_fn(query="test")

        assert "all requested sources were unavailable" in result
        assert "Search status**: `failed`" in result
        assert "status=error" in result
        assert "total_available=unknown" in result
        assert "No images found" not in result

    async def test_partial_result_exposes_coverage_without_claiming_empty(self):
        from pubmed_search.application.image_search import ImageSearchResult

        partial = ImageSearchResult(
            images=[
                ImageResult(
                    image_url="https://openi.nlm.nih.gov/img/1.png",
                    source=ImageSource.OPENI,
                    source_id="img-1",
                )
            ],
            total_count=2,
            sources_used=["openi"],
            query="test",
            search_status="partial",
            source_counts={"openi": 1},
            source_coverage=[
                ImageSourceCoverage(
                    source="openi",
                    status="partial",
                    returned=1,
                    total_available=2,
                    rows_received=2,
                    rows_rejected=1,
                    pages_fetched=1,
                    bounded=True,
                    has_more=False,
                    response_complete=False,
                    errors=(
                        ImageSourceCoverageError(
                            kind="validation",
                            retryable=False,
                            status_code=None,
                        ),
                    ),
                )
            ],
            duplicates_removed=0,
            errors=["openi: Open-i returned malformed result rows"],
        )
        tool_fn, _service = self._get_tool(search_result=partial)

        result = await tool_fn(query="test")

        assert "Search status**: `partial`" in result
        assert "status=partial" in result
        assert "rows_rejected=1" in result
        assert "No images found" not in result

    async def test_unexpected_failure_does_not_expose_exception_details(self):
        tool_fn, _service = self._get_tool(search_error=RuntimeError("token=secret /srv/private/image-cache"))

        result = await tool_fn(query="test")

        assert "Biomedical image search could not be completed" in result
        assert "secret" not in result
        assert "/srv/private" not in result

    async def test_removed_unimplemented_arguments_are_absent_from_public_signature(self):
        tool_fn, _service = self._get_tool()
        import inspect

        parameters = inspect.signature(tool_fn).parameters
        assert "sources" not in parameters
        assert "open_access_only" not in parameters


async def test_image_advisor_does_not_infer_ct_from_effectiveness_or_pet_from_competition():
    from pubmed_search.application.image_search import ImageQueryAdvisor

    advice = ImageQueryAdvisor().advise("treatment effectiveness and competition")
    assert advice.recommended_image_type is None
    assert not advice.is_suitable
