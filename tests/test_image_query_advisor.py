"""
Tests for ImageQueryAdvisor and QueryAnalyzer image intent detection.

Tests:
- ImageQueryAdvisor: suitability scoring, image_type recommendation,
  temporal warnings, query enhancement
- QueryAnalyzer: image_search_recommended field
- Integration: advisor warnings flow through ImageSearchService
"""


from pubmed_search.application.image_search.advisor import (
    ImageQueryAdvisor,
    ImageSearchAdvice,
    advise_image_search,
)
from pubmed_search.application.search.query_analyzer import (
    QueryAnalyzer,
)


# ============================================================================
# ImageQueryAdvisor Tests
# ============================================================================


class TestImageQueryAdvisorSuitability:
    """Tests for query suitability scoring."""

    def setup_method(self):
        self.advisor = ImageQueryAdvisor()

    # --- Suitable queries ---

    def test_explicit_image_query(self):
        advice = self.advisor.advise("chest X-ray pneumonia image")
        assert advice.is_suitable is True
        assert advice.confidence > 0.3

    def test_radiology_query(self):
        advice = self.advisor.advise("chest radiograph bilateral infiltrate")
        assert advice.is_suitable is True

    def test_microscopy_query(self):
        advice = self.advisor.advise("histology liver biopsy staining")
        assert advice.is_suitable is True

    def test_photo_query(self):
        advice = self.advisor.advise("skin lesion dermatology clinical photo")
        assert advice.is_suitable is True

    def test_ct_scan_query(self):
        advice = self.advisor.advise("CT scan lung nodule")
        assert advice.is_suitable is True

    def test_anatomical_keyword_query(self):
        """Anatomical keywords alone provide moderate signal."""
        advice = self.advisor.advise("fracture displacement bone")
        assert advice.is_suitable is True

    def test_chinese_image_query(self):
        advice = self.advisor.advise("胸部X光 肺炎 影像")
        assert advice.is_suitable is True

    # --- Unsuitable queries ---

    def test_pharmacology_query(self):
        advice = self.advisor.advise("remimazolam pharmacokinetics dosing")
        assert advice.is_suitable is False

    def test_meta_analysis_query(self):
        advice = self.advisor.advise(
            "systematic review meta-analysis treatment efficacy"
        )
        assert advice.is_suitable is False

    def test_guideline_query(self):
        advice = self.advisor.advise("clinical practice guideline protocol")
        assert advice.is_suitable is False

    def test_genomics_query(self):
        advice = self.advisor.advise("gene expression molecular pathway signaling")
        assert advice.is_suitable is False

    def test_epidemiology_query(self):
        advice = self.advisor.advise("prevalence incidence epidemiology statistics")
        assert advice.is_suitable is False

    def test_suggestions_for_unsuitable(self):
        """Unsuitable queries should suggest alternative tools."""
        advice = self.advisor.advise("propofol mechanism of action pharmacodynamics")
        assert advice.is_suitable is False
        assert len(advice.suggestions) > 0
        assert any(
            "unified_search" in s or "search_literature" in s
            for s in advice.suggestions
        )


class TestImageQueryAdvisorImageType:
    """Tests for image_type recommendation."""

    def setup_method(self):
        self.advisor = ImageQueryAdvisor()

    def test_recommend_x_for_xray(self):
        advice = self.advisor.advise("chest X-ray pneumonia")
        assert advice.recommended_image_type == "x"  # "x" = X-ray
        assert "X光" in advice.image_type_reason or "放射" in advice.image_type_reason

    def test_recommend_mc_for_microscopy(self):
        advice = self.advisor.advise("histology liver biopsy pathology")
        assert advice.recommended_image_type == "mc"
        assert "顯微鏡" in advice.image_type_reason or "病理" in advice.image_type_reason

    def test_recommend_ph_for_photo(self):
        advice = self.advisor.advise("skin lesion dermatology clinical photo")
        assert advice.recommended_image_type == "ph"
        assert "照片" in advice.image_type_reason or "皮膚" in advice.image_type_reason

    def test_recommend_g_for_graphics(self):
        advice = self.advisor.advise("flowchart algorithm diagram")
        assert advice.recommended_image_type == "g"
        assert "圖表" in advice.image_type_reason or "示意" in advice.image_type_reason

    def test_recommend_c_for_ct(self):
        advice = self.advisor.advise("ct scan computed tomography hrct")
        assert advice.recommended_image_type == "c"
        assert "CT" in advice.image_type_reason or "斷層" in advice.image_type_reason

    def test_recommend_u_for_ultrasound(self):
        advice = self.advisor.advise("ultrasound echocardiography doppler")
        assert advice.recommended_image_type == "u"
        assert "超音波" in advice.image_type_reason

    def test_recommend_m_for_mri(self):
        """MRI queries should recommend 'm' (MRI), not 'mc' (Microscopy)."""
        advice = self.advisor.advise("brain mri t2 weighted flair")
        assert advice.recommended_image_type == "m"
        assert "MRI" in advice.image_type_reason or "磁振" in advice.image_type_reason

    def test_recommend_p_for_pet(self):
        """PET queries should recommend 'p' (PET), not 'ph' (Photographs)."""
        advice = self.advisor.advise("pet scan fdg suv")
        assert advice.recommended_image_type == "p"
        assert "PET" in advice.image_type_reason or "正子" in advice.image_type_reason

    def test_default_none_for_unknown(self):
        """Queries without specific image type keywords → None (all types)."""
        advice = self.advisor.advise("heart disease")
        assert advice.recommended_image_type is None
        assert "所有類型" in advice.image_type_reason

    def test_image_type_mismatch_warning(self):
        """Warning when explicit image_type doesn't match query content."""
        advice = self.advisor.advise("histology biopsy pathology", image_type="xg")
        assert len(advice.warnings) > 0
        assert any("mc" in w for w in advice.warnings)


class TestImageQueryAdvisorTemporal:
    """Tests for temporal relevance checking (Open-i ~2020 cutoff)."""

    def setup_method(self):
        self.advisor = ImageQueryAdvisor()

    def test_covid_warning(self):
        advice = self.advisor.advise("covid-19 chest CT scan")
        assert advice.has_warnings
        assert any("2020" in w for w in advice.warnings)

    def test_recent_year_warning(self):
        advice = self.advisor.advise("lung cancer imaging 2023")
        assert advice.has_warnings
        assert any("2023" in w or "2020" in w for w in advice.warnings)

    def test_no_temporal_warning_for_old_topics(self):
        advice = self.advisor.advise("chest X-ray pneumonia")
        temporal_warnings = [w for w in advice.warnings if "2020" in w]
        assert len(temporal_warnings) == 0

    def test_post_2020_keyword_sars_cov_2(self):
        advice = self.advisor.advise("sars-cov-2 lung imaging")
        assert any("2020" in w for w in advice.warnings)

    def test_year_2025_triggers_warning(self):
        advice = self.advisor.advise("radiology trends 2025")
        assert advice.has_warnings


class TestImageQueryAdvisorQueryEnhancement:
    """Tests for query enhancement / noise removal."""

    def setup_method(self):
        self.advisor = ImageQueryAdvisor()

    def test_removes_study_type_noise(self):
        advice = self.advisor.advise("chest X-ray pneumonia systematic review")
        if advice.enhanced_query:
            assert "systematic review" not in advice.enhanced_query

    def test_removes_year_noise(self):
        advice = self.advisor.advise("fracture imaging 2023")
        if advice.enhanced_query:
            assert "2023" not in advice.enhanced_query

    def test_preserves_core_terms(self):
        advice = self.advisor.advise("chest pneumonia X-ray")
        # Should either be None (no enhancement needed) or still contain core terms
        if advice.enhanced_query:
            assert "chest" in advice.enhanced_query
            assert "pneumonia" in advice.enhanced_query


class TestImageQueryAdvisorCoarseCategory:
    """Tests for coarse category classification."""

    def setup_method(self):
        self.advisor = ImageQueryAdvisor()

    def test_radiology_category_from_xray(self):
        advice = self.advisor.advise("chest X-ray pneumonia")
        assert advice.coarse_category == "radiology"

    def test_radiology_category_from_ct(self):
        advice = self.advisor.advise("ct scan computed tomography hrct")
        assert advice.coarse_category == "radiology"

    def test_radiology_category_from_mri(self):
        advice = self.advisor.advise("brain mri t2 weighted flair")
        assert advice.coarse_category == "radiology"

    def test_radiology_category_from_pet(self):
        advice = self.advisor.advise("pet scan fdg suv")
        assert advice.coarse_category == "radiology"

    def test_ultrasound_category(self):
        advice = self.advisor.advise("ultrasound echocardiography")
        assert advice.coarse_category == "ultrasound"

    def test_microscopy_category(self):
        advice = self.advisor.advise("histology liver biopsy pathology")
        assert advice.coarse_category == "microscopy"

    def test_photo_category(self):
        advice = self.advisor.advise("skin lesion dermatology clinical photo")
        assert advice.coarse_category == "photo"

    def test_graphics_category(self):
        advice = self.advisor.advise("flowchart algorithm diagram")
        assert advice.coarse_category == "graphics"

    def test_none_category_for_generic(self):
        advice = self.advisor.advise("heart disease")
        assert advice.coarse_category is None


class TestImageQueryAdvisorCollection:
    """Tests for collection recommendation."""

    def setup_method(self):
        self.advisor = ImageQueryAdvisor()

    def test_cxr_collection_for_chest_xray(self):
        advice = self.advisor.advise("chest x-ray pa view pneumonia")
        assert advice.recommended_collection == "cxr"
        assert "胸部" in advice.collection_reason or "cxr" in advice.collection_reason

    def test_mpx_collection_for_teaching(self):
        advice = self.advisor.advise("clinical case teaching image")
        assert advice.recommended_collection == "mpx"
        assert "教學" in advice.collection_reason or "MedPix" in advice.collection_reason

    def test_hmd_collection_for_medical_history(self):
        advice = self.advisor.advise("history of medicine vintage")
        assert advice.recommended_collection == "hmd"

    def test_no_collection_for_generic(self):
        advice = self.advisor.advise("chest pneumonia X-ray")
        assert advice.recommended_collection is None


class TestImageSearchAdviceDataclass:
    """Tests for ImageSearchAdvice data class."""

    def test_has_warnings_true(self):
        advice = ImageSearchAdvice(
            is_suitable=True,
            confidence=0.8,
            warnings=["test warning"],
        )
        assert advice.has_warnings is True

    def test_has_warnings_false(self):
        advice = ImageSearchAdvice(
            is_suitable=True,
            confidence=0.8,
        )
        assert advice.has_warnings is False

    def test_format_warnings(self):
        advice = ImageSearchAdvice(
            is_suitable=True,
            confidence=0.8,
            warnings=["Warning 1", "Warning 2"],
        )
        formatted = advice.format_warnings()
        assert "⚠️ Warning 1" in formatted
        assert "⚠️ Warning 2" in formatted

    def test_format_suggestions(self):
        advice = ImageSearchAdvice(
            is_suitable=False,
            confidence=0.2,
            suggestions=["Use search_literature()"],
        )
        formatted = advice.format_suggestions()
        assert "💡 Use search_literature()" in formatted

    def test_format_empty(self):
        advice = ImageSearchAdvice(is_suitable=True, confidence=0.5)
        assert advice.format_warnings() == ""
        assert advice.format_suggestions() == ""


class TestAdviseImageSearchConvenience:
    """Tests for the convenience function."""

    def test_convenience_function(self):
        advice = advise_image_search("chest X-ray pneumonia")
        assert isinstance(advice, ImageSearchAdvice)
        assert advice.is_suitable is True

    def test_convenience_with_image_type(self):
        advice = advise_image_search("histology", image_type="xg")
        assert isinstance(advice, ImageSearchAdvice)
        # Should warn about mismatch
        assert advice.has_warnings


# ============================================================================
# QueryAnalyzer Image Intent Tests
# ============================================================================


class TestQueryAnalyzerImageIntent:
    """Tests for image intent detection in QueryAnalyzer."""

    def setup_method(self):
        self.analyzer = QueryAnalyzer()

    def test_explicit_image_intent(self):
        result = self.analyzer.analyze("chest X-ray image pneumonia")
        assert result.image_search_recommended is True
        assert result.image_search_reason != ""

    def test_radiology_intent(self):
        result = self.analyzer.analyze("CT scan lung nodule MRI")
        assert result.image_search_recommended is True

    def test_histology_intent(self):
        result = self.analyzer.analyze("histology liver biopsy microscopy")
        assert result.image_search_recommended is True

    def test_no_image_intent_for_text_query(self):
        result = self.analyzer.analyze("metformin diabetes treatment efficacy")
        assert result.image_search_recommended is False
        assert result.image_search_reason == ""

    def test_no_image_intent_for_pmid(self):
        result = self.analyzer.analyze("PMID:12345678")
        assert result.image_search_recommended is False

    def test_image_intent_in_to_dict(self):
        result = self.analyzer.analyze("X-ray chest pneumonia scan")
        d = result.to_dict()
        assert "image_search_recommended" in d
        assert "image_search_reason" in d
        assert d["image_search_recommended"] is True

    def test_chinese_image_intent(self):
        result = self.analyzer.analyze("胸部X光 肺炎 影像")
        assert result.image_search_recommended is True

    def test_anatomy_keywords_weaker_signal(self):
        """Single anatomy keyword should NOT trigger image recommendation."""
        result = self.analyzer.analyze("fracture management protocol")
        # Single anatomy keyword = score 1 < threshold 2
        assert result.image_search_recommended is False

    def test_multiple_anatomy_keywords(self):
        """Multiple anatomy keywords should trigger recommendation."""
        result = self.analyzer.analyze("fracture pneumonia opacity nodule")
        assert result.image_search_recommended is True


# ============================================================================
# Integration Tests: Advisor → Service → Presentation
# ============================================================================


class TestAdvisorIntegration:
    """Tests for advisor integration with ImageSearchService."""

    def test_service_includes_advisor_warnings(self):
        """ImageSearchService should include advisor warnings in result."""
        from unittest.mock import MagicMock, patch

        from pubmed_search.application.image_search import (
            ImageSearchService,
        )
        from pubmed_search.domain.entities.image import ImageResult

        service = ImageSearchService()
        mock_client = MagicMock()
        mock_images = [
            ImageResult(
                image_url="https://openi.nlm.nih.gov/img/1.png",
                pmid="123",
            ),
        ]
        mock_client.search.return_value = (mock_images, 1)

        with patch(
            "pubmed_search.infrastructure.sources.get_openi_client",
            return_value=mock_client,
        ):
            # Query with post-2020 keyword → should have temporal warning
            result = service.search("covid-19 chest CT")

        assert len(result.advisor_warnings) > 0
        assert any("2020" in w for w in result.advisor_warnings)

    def test_service_includes_suggestions_for_bad_query(self):
        """Non-image queries should get suggestions."""
        from unittest.mock import MagicMock, patch

        from pubmed_search.application.image_search import (
            ImageSearchService,
        )

        service = ImageSearchService()
        mock_client = MagicMock()
        mock_client.search.return_value = ([], 0)

        with patch(
            "pubmed_search.infrastructure.sources.get_openi_client",
            return_value=mock_client,
        ):
            result = service.search("pharmacokinetics dosing protocol")

        assert len(result.advisor_suggestions) > 0

    def test_service_passes_recommended_image_type(self):
        """Service should pass through recommended image type."""
        from unittest.mock import MagicMock, patch

        from pubmed_search.application.image_search import (
            ImageSearchService,
        )

        service = ImageSearchService()
        mock_client = MagicMock()
        mock_client.search.return_value = ([], 0)

        with patch(
            "pubmed_search.infrastructure.sources.get_openi_client",
            return_value=mock_client,
        ):
            result = service.search("histology liver pathology")

        assert result.recommended_image_type == "mc"

    def test_empty_query_no_advisor(self):
        """Empty query should skip advisor entirely."""
        from pubmed_search.application.image_search import ImageSearchService

        service = ImageSearchService()
        result = service.search("")
        assert result.advisor_warnings == []
        assert result.advisor_suggestions == []

    def test_presentation_formats_warnings(self):
        """Presentation layer should format advisor warnings in output."""
        from unittest.mock import patch

        from mcp.server.fastmcp import FastMCP

        from pubmed_search.application.image_search import ImageSearchResult
        from pubmed_search.domain.entities.image import ImageResult, ImageSource
        from pubmed_search.presentation.mcp_server.tools.image_search import (
            register_image_search_tools,
        )

        mcp = FastMCP("test")
        register_image_search_tools(mcp)
        tools = mcp._tool_manager._tools
        tool_fn = tools["search_biomedical_images"].fn

        mock_result = ImageSearchResult(
            images=[
                ImageResult(
                    image_url="https://openi.nlm.nih.gov/img/1.png",
                    caption="Test",
                    pmid="123",
                    article_title="Test",
                    source=ImageSource.OPENI,
                )
            ],
            total_count=1,
            sources_used=["openi"],
            query="covid-19 chest",
            advisor_warnings=["Open-i 索引凍結於 ~2020，查詢含 'covid-19' 可能找不到相關結果"],
            advisor_suggestions=[],
            recommended_image_type="xg",
        )

        with patch(
            "pubmed_search.presentation.mcp_server.tools.image_search.ImageSearchService"
        ) as MockService:
            MockService.return_value.search.return_value = mock_result
            result = tool_fn(query="covid-19 chest")

        assert "智慧建議" in result
        assert "2020" in result
        assert "xg" in result
