"""
Tests for biomedical image search (Phase 4.1).

Tests:
- Domain: ImageResult entity
- Infrastructure: OpenIClient mapper
- Application: ImageSearchService
- Presentation: search_biomedical_images tool
"""

from unittest.mock import AsyncMock, patch

import pytest

from pubmed_search.domain.entities.image import ImageResult, ImageSource
from pubmed_search.infrastructure.sources.openi import OpenIClient


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
                "image": {
                    "caption": "PA chest radiograph showing bilateral infiltrates"
                },
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
        assert ImageSource.EUROPE_PMC == "europe_pmc"
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
        result = OpenIClient._map_to_image_result({})
        assert result.image_url == ""
        assert result.thumbnail_url is None
        assert result.caption == ""
        assert result.pmid is None

    async def test_map_image_caption_not_dict(self):
        item = {"image": "not a dict", "uid": "test"}
        result = OpenIClient._map_to_image_result(item)
        assert result.caption == ""


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
        assert OpenIClient._extract_mesh({"MeSH": "invalid"}) == []

    async def test_extract_mesh_invalid_lists(self):
        item = {"MeSH": {"major": "not-a-list", "minor": 42}}
        assert OpenIClient._extract_mesh(item) == []


class TestOpenIClientSearch:
    """Tests for OpenIClient.search with mocked HTTP."""

    async def test_search_success(self, openi_client, sample_openi_response):
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ):
            images, total = await openi_client.search("chest pneumonia", max_results=10)

        assert total == 42
        assert len(images) == 2
        assert images[0].pmid == "12345678"

    async def test_search_empty_query(self, openi_client):
        images, total = await openi_client.search("")
        assert images == []
        assert total == 0

    async def test_search_empty_results(self, openi_client, empty_openi_response):
        with patch.object(
            openi_client, "_make_request", return_value=empty_openi_response
        ):
            images, total = await openi_client.search("nonexistent query")

        assert total == 0
        assert images == []

    async def test_search_request_failure(self, openi_client):
        with patch.object(openi_client, "_make_request", return_value=None):
            images, total = await openi_client.search("test")

        assert images == []
        assert total == 0

    async def test_search_default_image_type(self, openi_client, sample_openi_response):
        """When no image_type specified, defaults to None (all types)."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test")
            call_url = mock_req.call_args[0][0]
            # No 'it' parameter when None
            assert "it=" not in call_url

    async def test_search_invalid_image_type_ignored(
        self, openi_client, sample_openi_response
    ):
        """Invalid image_type is ignored (no 'it' param)."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", image_type="invalid")
            call_url = mock_req.call_args[0][0]
            assert "it=" not in call_url

    async def test_search_valid_image_type(self, openi_client, sample_openi_response):
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", image_type="xg")
            call_url = mock_req.call_args[0][0]
            assert "it=xg" in call_url

    async def test_search_photo_image_type(self, openi_client, sample_openi_response):
        """'ph' (Photo) is a valid image type."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", image_type="ph")
            call_url = mock_req.call_args[0][0]
            assert "it=ph" in call_url

    async def test_search_graphics_image_type(
        self, openi_client, sample_openi_response
    ):
        """'g' (Graphics) is a valid image type."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", image_type="g")
            call_url = mock_req.call_args[0][0]
            assert "it=g" in call_url

    async def test_search_valid_collection(self, openi_client, sample_openi_response):
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", collection="mpx")
            call_url = mock_req.call_args[0][0]
            assert "coll=mpx" in call_url

    async def test_search_respects_max_results(self, openi_client):
        """max_results=1 should only return 1 image even if API returns more."""
        response = {
            "total": 100,
            "list": [
                {"uid": f"img-{i}", "imgLarge": f"/img/{i}.png"} for i in range(10)
            ],
        }
        with patch.object(openi_client, "_make_request", return_value=response):
            images, total = await openi_client.search("test", max_results=1)

        assert len(images) == 1
        assert total == 100

    # ═══════════════════════════════════════════════════════════════════════════
    # New API Parameters Tests (v0.3.4)
    # ═══════════════════════════════════════════════════════════════════════════

    async def test_search_sort_by_date(self, openi_client, sample_openi_response):
        """sort_by='d' should add favor=d parameter."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", sort_by="d")
            call_url = mock_req.call_args[0][0]
            assert "favor=d" in call_url

    async def test_search_sort_by_relevance(self, openi_client, sample_openi_response):
        """sort_by='r' should add favor=r parameter."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", sort_by="r")
            call_url = mock_req.call_args[0][0]
            assert "favor=r" in call_url

    async def test_search_invalid_sort_by_ignored(
        self, openi_client, sample_openi_response
    ):
        """Invalid sort_by is ignored (no favor param)."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", sort_by="invalid")
            call_url = mock_req.call_args[0][0]
            assert "favor=" not in call_url

    async def test_search_article_type_case_report(
        self, openi_client, sample_openi_response
    ):
        """article_type='cr' should add at=cr parameter."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", article_type="cr")
            call_url = mock_req.call_args[0][0]
            assert "at=cr" in call_url

    async def test_search_invalid_article_type_ignored(
        self, openi_client, sample_openi_response
    ):
        """Invalid article_type is ignored."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", article_type="invalid")
            call_url = mock_req.call_args[0][0]
            assert "at=" not in call_url

    async def test_search_specialty_radiology(
        self, openi_client, sample_openi_response
    ):
        """specialty='r' should add sp=r parameter."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", specialty="r")
            call_url = mock_req.call_args[0][0]
            assert "sp=r" in call_url

    async def test_search_specialty_cardiology(
        self, openi_client, sample_openi_response
    ):
        """specialty='c' should add sp=c parameter."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", specialty="c")
            call_url = mock_req.call_args[0][0]
            assert "sp=c" in call_url

    async def test_search_invalid_specialty_ignored(
        self, openi_client, sample_openi_response
    ):
        """Invalid specialty is ignored."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", specialty="invalid")
            call_url = mock_req.call_args[0][0]
            assert "sp=" not in call_url

    async def test_search_license_cc_by(self, openi_client, sample_openi_response):
        """license_type='by' should add lic=by parameter."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", license_type="by")
            call_url = mock_req.call_args[0][0]
            assert "lic=by" in call_url

    async def test_search_license_cc_by_nc(self, openi_client, sample_openi_response):
        """license_type='bync' should add lic=bync parameter."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", license_type="bync")
            call_url = mock_req.call_args[0][0]
            assert "lic=bync" in call_url

    async def test_search_invalid_license_ignored(
        self, openi_client, sample_openi_response
    ):
        """Invalid license_type is ignored."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", license_type="invalid")
            call_url = mock_req.call_args[0][0]
            assert "lic=" not in call_url

    async def test_search_subset_cancer(self, openi_client, sample_openi_response):
        """subset='c' should add sub=c parameter."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", subset="c")
            call_url = mock_req.call_args[0][0]
            assert "sub=c" in call_url

    async def test_search_invalid_subset_ignored(
        self, openi_client, sample_openi_response
    ):
        """Invalid subset is ignored."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", subset="invalid")
            call_url = mock_req.call_args[0][0]
            assert "sub=" not in call_url

    async def test_search_fields_title(self, openi_client, sample_openi_response):
        """search_fields='t' should add fields=t parameter."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", search_fields="t")
            call_url = mock_req.call_args[0][0]
            assert "fields=t" in call_url

    async def test_search_fields_caption(self, openi_client, sample_openi_response):
        """search_fields='c' should add fields=c parameter."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", search_fields="c")
            call_url = mock_req.call_args[0][0]
            assert "fields=c" in call_url

    async def test_search_invalid_fields_ignored(
        self, openi_client, sample_openi_response
    ):
        """Invalid search_fields is ignored."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", search_fields="invalid")
            call_url = mock_req.call_args[0][0]
            assert "fields=" not in call_url

    async def test_search_video_only(self, openi_client, sample_openi_response):
        """video_only=True should add vid=1 parameter."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", video_only=True)
            call_url = mock_req.call_args[0][0]
            assert "vid=1" in call_url

    async def test_search_video_only_false(self, openi_client, sample_openi_response):
        """video_only=False should NOT add vid parameter."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
            await openi_client.search("test", video_only=False)
            call_url = mock_req.call_args[0][0]
            assert "vid=" not in call_url

    async def test_search_combined_filters(self, openi_client, sample_openi_response):
        """Multiple filters should be combined in URL."""
        with patch.object(
            openi_client, "_make_request", return_value=sample_openi_response
        ) as mock_req:
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
        from pubmed_search.application.image_search import ImageSearchService

        service = ImageSearchService()
        result = await service.search("")
        assert result.images == []
        assert result.total_count == 0

    async def test_search_delegates_to_openi(self, sample_openi_response):
        from pubmed_search.application.image_search import ImageSearchService

        service = ImageSearchService()
        mock_client = AsyncMock()
        mock_images = [
            ImageResult(image_url="https://openi.nlm.nih.gov/img/1.png", pmid="123"),
        ]
        mock_client.search.return_value = (mock_images, 1)

        with patch(
            "pubmed_search.infrastructure.sources.get_openi_client",
            return_value=mock_client,
        ):
            result = await service.search("chest pneumonia")

        assert len(result.images) == 1
        assert result.total_count == 1
        assert "openi" in result.sources_used

    async def test_search_handles_error(self):
        from pubmed_search.application.image_search import ImageSearchService

        service = ImageSearchService()

        with patch(
            "pubmed_search.infrastructure.sources.get_openi_client",
            side_effect=Exception("Connection failed"),
        ):
            result = await service.search("test")

        assert result.images == []
        assert len(result.errors) == 1
        assert "Connection failed" in result.errors[0]

    async def test_resolve_sources_default(self):
        from pubmed_search.application.image_search import ImageSearchService

        service = ImageSearchService()
        sources = service._resolve_sources(None, None, None)
        assert sources == ["openi"]

    async def test_resolve_sources_explicit(self):
        from pubmed_search.application.image_search import ImageSearchService

        service = ImageSearchService()
        sources = service._resolve_sources(["openi"], None, None)
        assert sources == ["openi"]

    async def test_resolve_sources_invalid_fallback(self):
        from pubmed_search.application.image_search import ImageSearchService

        service = ImageSearchService()
        sources = service._resolve_sources(["invalid_source"], None, None)
        assert sources == ["openi"]

    async def test_deduplicate(self):
        from pubmed_search.application.image_search import ImageSearchService

        images = [
            ImageResult(image_url="url1", pmid="123", source_id="a"),
            ImageResult(image_url="url2", pmid="123", source_id="a"),  # duplicate
            ImageResult(image_url="url3", pmid="456", source_id="b"),
        ]
        result = ImageSearchService._deduplicate(images)
        assert len(result) == 2

    async def test_deduplicate_by_url(self):
        from pubmed_search.application.image_search import ImageSearchService

        images = [
            ImageResult(image_url="same_url"),
            ImageResult(image_url="same_url"),  # duplicate by URL
        ]
        result = ImageSearchService._deduplicate(images)
        assert len(result) == 1

    # ═══════════════════════════════════════════════════════════════════════════
    # New API Parameters Tests (v0.3.4)
    # ═══════════════════════════════════════════════════════════════════════════

    async def test_search_with_sort_by(self):
        """sort_by parameter should be passed to client."""
        from pubmed_search.application.image_search import ImageSearchService

        service = ImageSearchService()
        mock_client = AsyncMock()
        mock_client.search.return_value = ([], 0)

        with patch(
            "pubmed_search.infrastructure.sources.get_openi_client",
            return_value=mock_client,
        ):
            await service.search("test", sort_by="d")

        mock_client.search.assert_called_once()
        call_kwargs = mock_client.search.call_args[1]
        assert call_kwargs["sort_by"] == "d"

    async def test_search_with_article_type(self):
        """article_type parameter should be passed to client."""
        from pubmed_search.application.image_search import ImageSearchService

        service = ImageSearchService()
        mock_client = AsyncMock()
        mock_client.search.return_value = ([], 0)

        with patch(
            "pubmed_search.infrastructure.sources.get_openi_client",
            return_value=mock_client,
        ):
            await service.search("test", article_type="cr")

        call_kwargs = mock_client.search.call_args[1]
        assert call_kwargs["article_type"] == "cr"

    async def test_search_with_specialty(self):
        """specialty parameter should be passed to client."""
        from pubmed_search.application.image_search import ImageSearchService

        service = ImageSearchService()
        mock_client = AsyncMock()
        mock_client.search.return_value = ([], 0)

        with patch(
            "pubmed_search.infrastructure.sources.get_openi_client",
            return_value=mock_client,
        ):
            await service.search("test", specialty="r")

        call_kwargs = mock_client.search.call_args[1]
        assert call_kwargs["specialty"] == "r"

    async def test_search_with_license_type(self):
        """license_type parameter should be passed to client."""
        from pubmed_search.application.image_search import ImageSearchService

        service = ImageSearchService()
        mock_client = AsyncMock()
        mock_client.search.return_value = ([], 0)

        with patch(
            "pubmed_search.infrastructure.sources.get_openi_client",
            return_value=mock_client,
        ):
            await service.search("test", license_type="by")

        call_kwargs = mock_client.search.call_args[1]
        assert call_kwargs["license_type"] == "by"

    async def test_search_with_video_only(self):
        """video_only parameter should be passed to client."""
        from pubmed_search.application.image_search import ImageSearchService

        service = ImageSearchService()
        mock_client = AsyncMock()
        mock_client.search.return_value = ([], 0)

        with patch(
            "pubmed_search.infrastructure.sources.get_openi_client",
            return_value=mock_client,
        ):
            await service.search("test", video_only=True)

        call_kwargs = mock_client.search.call_args[1]
        assert call_kwargs["video_only"] is True

    async def test_search_tracks_applied_filters(self):
        """applied_filters should track all set filters."""
        from pubmed_search.application.image_search import ImageSearchService

        service = ImageSearchService()
        mock_client = AsyncMock()
        mock_client.search.return_value = ([], 0)

        with patch(
            "pubmed_search.infrastructure.sources.get_openi_client",
            return_value=mock_client,
        ):
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

    async def test_search_with_all_new_parameters(self):
        """All new parameters should be passed to client."""
        from pubmed_search.application.image_search import ImageSearchService

        service = ImageSearchService()
        mock_client = AsyncMock()
        mock_client.search.return_value = ([], 0)

        with patch(
            "pubmed_search.infrastructure.sources.get_openi_client",
            return_value=mock_client,
        ):
            await service.search(
                "test",
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

    def _get_tool(self):
        """Register and return the tool function."""
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        from pubmed_search.presentation.mcp_server.tools.image_search import (
            register_image_search_tools,
        )

        register_image_search_tools(mcp)

        # Get the registered tool function
        tools = mcp._tool_manager._tools
        assert "search_biomedical_images" in tools
        return tools["search_biomedical_images"].fn

    async def test_empty_query_returns_error(self):
        tool_fn = self._get_tool()
        result = await tool_fn(query="")
        assert "Missing search query" in result

    async def test_successful_search(self):
        tool_fn = self._get_tool()
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
        )

        with patch(
            "pubmed_search.presentation.mcp_server.tools.image_search.ImageSearchService"
        ) as MockService:
            MockService.return_value.search = AsyncMock(return_value=mock_result)
            result = await tool_fn(query="chest pneumonia")

        assert "Image Search Results" in result
        assert "chest pneumonia" in result
        assert "12345678" in result
        assert "Chest X-ray" in result

    async def test_input_normalization(self):
        tool_fn = self._get_tool()

        from pubmed_search.application.image_search import ImageSearchResult

        mock_result = ImageSearchResult(
            images=[], total_count=0, sources_used=["openi"], query="test"
        )

        with patch(
            "pubmed_search.presentation.mcp_server.tools.image_search.ImageSearchService"
        ) as MockService:
            MockService.return_value.search = AsyncMock(return_value=mock_result)
            # Test with string limit and bool
            result = await tool_fn(query="test", limit="5", open_access_only="true")

        assert "No images found" in result

    async def test_unknown_sources_handled(self):
        tool_fn = self._get_tool()

        from pubmed_search.application.image_search import ImageSearchResult

        mock_result = ImageSearchResult(
            images=[], total_count=0, sources_used=["openi"], query="test"
        )

        with patch(
            "pubmed_search.presentation.mcp_server.tools.image_search.ImageSearchService"
        ) as MockService:
            MockService.return_value.search = AsyncMock(return_value=mock_result)
            # Unknown sources value should not crash
            result = await tool_fn(query="test", sources="unknown_source")

        assert isinstance(result, str)
