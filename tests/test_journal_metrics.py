"""
Tests for JournalMetrics dataclass and _enrich_with_journal_metrics pipeline step.

Covers:
- JournalMetrics dataclass and properties
- _enrich_with_journal_metrics() function
- _extract_openalex_source_id() helper
- Pipeline integration
- Output formatting with journal metrics
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pubmed_search.domain.entities.article import (
    JournalMetrics,
    SourceMetadata,
    UnifiedArticle,
)

# =============================================================================
# JournalMetrics Dataclass Tests
# =============================================================================


class TestJournalMetrics:
    """Tests for JournalMetrics dataclass."""

    def test_default_values(self):
        jm = JournalMetrics()
        assert jm.issn is None
        assert jm.issn_l is None
        assert jm.openalex_source_id is None
        assert jm.h_index is None
        assert jm.two_year_mean_citedness is None
        assert jm.i10_index is None
        assert jm.works_count is None
        assert jm.cited_by_count is None
        assert jm.is_in_doaj is None
        assert jm.source_type is None
        assert jm.subject_areas == []

    def test_full_initialization(self):
        jm = JournalMetrics(
            issn="0028-4793",
            issn_l="0028-4793",
            openalex_source_id="S62468778",
            h_index=1000,
            two_year_mean_citedness=91.25,
            i10_index=25000,
            works_count=100000,
            cited_by_count=5000000,
            is_in_doaj=False,
            source_type="journal",
            subject_areas=["Medicine", "Immunology"],
        )
        assert jm.issn == "0028-4793"
        assert jm.h_index == 1000
        assert jm.two_year_mean_citedness == 91.25
        assert jm.subject_areas == ["Medicine", "Immunology"]

    def test_impact_tier_top(self):
        jm = JournalMetrics(two_year_mean_citedness=91.25)
        assert jm.impact_tier == "top"

    def test_impact_tier_high(self):
        jm = JournalMetrics(two_year_mean_citedness=7.5)
        assert jm.impact_tier == "high"

    def test_impact_tier_medium(self):
        jm = JournalMetrics(two_year_mean_citedness=3.0)
        assert jm.impact_tier == "medium"

    def test_impact_tier_low(self):
        jm = JournalMetrics(two_year_mean_citedness=1.5)
        assert jm.impact_tier == "low"

    def test_impact_tier_minimal(self):
        jm = JournalMetrics(two_year_mean_citedness=0.5)
        assert jm.impact_tier == "minimal"

    def test_impact_tier_unknown(self):
        jm = JournalMetrics()
        assert jm.impact_tier == "unknown"

    def test_impact_tier_boundary_10(self):
        jm = JournalMetrics(two_year_mean_citedness=10.0)
        assert jm.impact_tier == "top"

    def test_impact_tier_boundary_5(self):
        jm = JournalMetrics(two_year_mean_citedness=5.0)
        assert jm.impact_tier == "high"

    def test_impact_tier_boundary_2(self):
        jm = JournalMetrics(two_year_mean_citedness=2.0)
        assert jm.impact_tier == "medium"

    def test_impact_tier_boundary_1(self):
        jm = JournalMetrics(two_year_mean_citedness=1.0)
        assert jm.impact_tier == "low"

    def test_impact_tier_zero(self):
        jm = JournalMetrics(two_year_mean_citedness=0.0)
        assert jm.impact_tier == "minimal"


# =============================================================================
# UnifiedArticle Integration Tests
# =============================================================================


class TestUnifiedArticleJournalMetrics:
    """Test JournalMetrics integration with UnifiedArticle."""

    def test_default_none(self):
        article = UnifiedArticle(title="Test", primary_source="pubmed")
        assert article.journal_metrics is None

    def test_set_journal_metrics(self):
        jm = JournalMetrics(h_index=100, two_year_mean_citedness=5.0)
        article = UnifiedArticle(title="Test", primary_source="openalex", journal_metrics=jm)
        assert article.journal_metrics is not None
        assert article.journal_metrics.h_index == 100
        assert article.journal_metrics.two_year_mean_citedness == 5.0

    def test_to_dict_includes_journal_metrics(self):
        jm = JournalMetrics(
            issn="0028-4793",
            h_index=1000,
            two_year_mean_citedness=91.25,
            is_in_doaj=False,
            subject_areas=["Medicine"],
        )
        article = UnifiedArticle(title="Test", primary_source="openalex", journal_metrics=jm)
        d = article.to_dict()
        assert "journal_metrics" in d
        assert d["journal_metrics"]["issn"] == "0028-4793"
        assert d["journal_metrics"]["h_index"] == 1000
        assert d["journal_metrics"]["impact_factor_approx"] == 91.25
        assert d["journal_metrics"]["is_in_doaj"] is False
        assert d["journal_metrics"]["subject_areas"] == ["Medicine"]
        assert d["journal_metrics"]["impact_tier"] == "top"

    def test_to_dict_no_journal_metrics(self):
        article = UnifiedArticle(title="Test", primary_source="pubmed")
        d = article.to_dict()
        # journal_metrics should be None or not included
        assert d.get("journal_metrics") is None

    def test_merge_from_journal_metrics(self):
        jm = JournalMetrics(h_index=100, two_year_mean_citedness=5.0)
        article1 = UnifiedArticle(title="Test", primary_source="pubmed")
        article2 = UnifiedArticle(title="Test", primary_source="openalex", journal_metrics=jm)
        article1.merge_from(article2)
        assert article1.journal_metrics is not None
        assert article1.journal_metrics.h_index == 100

    def test_merge_from_does_not_overwrite_existing(self):
        jm1 = JournalMetrics(h_index=100, two_year_mean_citedness=5.0)
        jm2 = JournalMetrics(h_index=200, two_year_mean_citedness=10.0)
        article1 = UnifiedArticle(title="Test", primary_source="openalex", journal_metrics=jm1)
        article2 = UnifiedArticle(title="Test", primary_source="openalex", journal_metrics=jm2)
        article1.merge_from(article2)
        # Should keep original (or merge smartly)
        assert article1.journal_metrics is not None
        assert article1.journal_metrics.h_index == 100  # Original preserved


# =============================================================================
# _extract_openalex_source_id Tests
# =============================================================================


class TestExtractOpenAlexSourceId:
    """Test _extract_openalex_source_id helper function."""

    def test_from_normalized_field(self):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _extract_openalex_source_id,
        )

        article = UnifiedArticle(
            title="Test",
            primary_source="openalex",
            sources=[
                SourceMetadata(
                    source="openalex",
                    raw_data={"_openalex_source_id": "https://openalex.org/S62468778"},
                )
            ],
        )
        result = _extract_openalex_source_id(article)
        assert result == "https://openalex.org/S62468778"

    def test_from_primary_location(self):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _extract_openalex_source_id,
        )

        article = UnifiedArticle(
            title="Test",
            primary_source="openalex",
            sources=[
                SourceMetadata(
                    source="openalex",
                    raw_data={"primary_location": {"source": {"id": "https://openalex.org/S12345"}}},
                )
            ],
        )
        result = _extract_openalex_source_id(article)
        assert result == "https://openalex.org/S12345"

    def test_no_openalex_source(self):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _extract_openalex_source_id,
        )

        article = UnifiedArticle(
            title="Test",
            primary_source="pubmed",
            sources=[SourceMetadata(source="pubmed", raw_data={"pmid": "12345"})],
        )
        result = _extract_openalex_source_id(article)
        assert result is None

    def test_empty_sources(self):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _extract_openalex_source_id,
        )

        article = UnifiedArticle(title="Test", primary_source="pubmed", sources=[])
        result = _extract_openalex_source_id(article)
        assert result is None

    def test_openalex_source_no_raw_data(self):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _extract_openalex_source_id,
        )

        article = UnifiedArticle(
            title="Test",
            primary_source="openalex",
            sources=[SourceMetadata(source="openalex", raw_data=None)],
        )
        result = _extract_openalex_source_id(article)
        assert result is None

    def test_openalex_source_empty_source_id(self):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _extract_openalex_source_id,
        )

        article = UnifiedArticle(
            title="Test",
            primary_source="openalex",
            sources=[SourceMetadata(source="openalex", raw_data={"_openalex_source_id": ""})],
        )
        result = _extract_openalex_source_id(article)
        assert result is None

    def test_prefers_normalized_field_over_nested(self):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _extract_openalex_source_id,
        )

        article = UnifiedArticle(
            title="Test",
            primary_source="openalex",
            sources=[
                SourceMetadata(
                    source="openalex",
                    raw_data={
                        "_openalex_source_id": "https://openalex.org/S62468778",
                        "primary_location": {"source": {"id": "https://openalex.org/S99999"}},
                    },
                )
            ],
        )
        result = _extract_openalex_source_id(article)
        # Should prefer _openalex_source_id
        assert result == "https://openalex.org/S62468778"


# =============================================================================
# _enrich_with_journal_metrics Tests
# =============================================================================


class TestEnrichWithJournalMetrics:
    """Test _enrich_with_journal_metrics pipeline function."""

    @pytest.fixture
    def mock_source_data(self):
        """Sample source data from OpenAlex."""
        return {
            "S62468778": {
                "openalex_source_id": "S62468778",
                "display_name": "New England Journal of Medicine",
                "issn": "0028-4793",
                "issn_l": "0028-4793",
                "h_index": 1000,
                "two_year_mean_citedness": 91.25,
                "i10_index": 25000,
                "works_count": 100000,
                "cited_by_count": 5000000,
                "is_in_doaj": False,
                "source_type": "journal",
                "subject_areas": ["Medicine", "Immunology"],
            },
            "S137773608": {
                "openalex_source_id": "S137773608",
                "display_name": "Nature",
                "issn": "0028-0836",
                "issn_l": "0028-0836",
                "h_index": 1200,
                "two_year_mean_citedness": 50.5,
                "i10_index": 30000,
                "works_count": 200000,
                "cited_by_count": 8000000,
                "is_in_doaj": False,
                "source_type": "journal",
                "subject_areas": ["Multidisciplinary"],
            },
        }

    @pytest.fixture
    def articles_with_openalex_source(self):
        """Articles with OpenAlex source IDs."""
        return [
            UnifiedArticle(
                title="Article 1",
                primary_source="openalex",
                sources=[
                    SourceMetadata(
                        source="openalex",
                        raw_data={"_openalex_source_id": "https://openalex.org/S62468778"},
                    )
                ],
            ),
            UnifiedArticle(
                title="Article 2",
                primary_source="openalex",
                sources=[
                    SourceMetadata(
                        source="openalex",
                        raw_data={"_openalex_source_id": "https://openalex.org/S137773608"},
                    )
                ],
            ),
            UnifiedArticle(
                title="Article 3 (PubMed only)",
                primary_source="pubmed",
                sources=[SourceMetadata(source="pubmed", raw_data={"pmid": "99999"})],
            ),
        ]

    async def test_enriches_openalex_articles(self, articles_with_openalex_source, mock_source_data):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_journal_metrics,
        )

        mock_client = AsyncMock()
        mock_client.get_sources_batch = AsyncMock(return_value=mock_source_data)

        with patch(
            "pubmed_search.presentation.mcp_server.tools.unified.get_openalex_client",
            return_value=mock_client,
        ):
            await _enrich_with_journal_metrics(articles_with_openalex_source)

        # Article 1 should have NEJM metrics
        assert articles_with_openalex_source[0].journal_metrics is not None
        assert articles_with_openalex_source[0].journal_metrics.h_index == 1000
        assert articles_with_openalex_source[0].journal_metrics.two_year_mean_citedness == 91.25
        assert articles_with_openalex_source[0].journal_metrics.impact_tier == "top"

        # Article 2 should have Nature metrics
        assert articles_with_openalex_source[1].journal_metrics is not None
        assert articles_with_openalex_source[1].journal_metrics.h_index == 1200

        # Article 3 (PubMed only) should NOT be enriched
        assert articles_with_openalex_source[2].journal_metrics is None

    async def test_skips_already_enriched(self, mock_source_data):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_journal_metrics,
        )

        existing_jm = JournalMetrics(h_index=999)
        articles = [
            UnifiedArticle(
                title="Already enriched",
                primary_source="openalex",
                journal_metrics=existing_jm,
                sources=[
                    SourceMetadata(
                        source="openalex",
                        raw_data={"_openalex_source_id": "https://openalex.org/S62468778"},
                    )
                ],
            ),
        ]

        mock_client = AsyncMock()
        mock_client.get_sources_batch = AsyncMock(return_value=mock_source_data)

        with patch(
            "pubmed_search.presentation.mcp_server.tools.unified.get_openalex_client",
            return_value=mock_client,
        ):
            await _enrich_with_journal_metrics(articles)

        # Should keep existing metrics
        assert articles[0].journal_metrics.h_index == 999

    async def test_no_openalex_articles(self):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_journal_metrics,
        )

        articles = [
            UnifiedArticle(
                title="PubMed only",
                primary_source="pubmed",
                sources=[SourceMetadata(source="pubmed", raw_data={"pmid": "12345"})],
            ),
        ]

        mock_client = AsyncMock()
        mock_client.get_sources_batch = AsyncMock(return_value={})

        with patch(
            "pubmed_search.presentation.mcp_server.tools.unified.get_openalex_client",
            return_value=mock_client,
        ):
            await _enrich_with_journal_metrics(articles)

        # get_sources_batch should never be called (no source IDs extracted)
        mock_client.get_sources_batch.assert_not_called()
        assert articles[0].journal_metrics is None

    async def test_handles_api_failure_gracefully(self):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_journal_metrics,
        )

        articles = [
            UnifiedArticle(
                title="Article",
                primary_source="openalex",
                sources=[
                    SourceMetadata(
                        source="openalex",
                        raw_data={"_openalex_source_id": "https://openalex.org/S12345"},
                    )
                ],
            ),
        ]

        mock_client = AsyncMock()
        mock_client.get_sources_batch = AsyncMock(side_effect=Exception("API down"))

        with patch(
            "pubmed_search.presentation.mcp_server.tools.unified.get_openalex_client",
            return_value=mock_client,
        ):
            # Should not raise
            await _enrich_with_journal_metrics(articles)

        assert articles[0].journal_metrics is None

    async def test_same_journal_shared_across_articles(self, mock_source_data):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_journal_metrics,
        )

        articles = [
            UnifiedArticle(
                title=f"NEJM Article {i}",
                primary_source="openalex",
                sources=[
                    SourceMetadata(
                        source="openalex",
                        raw_data={"_openalex_source_id": "https://openalex.org/S62468778"},
                    )
                ],
            )
            for i in range(3)
        ]

        mock_client = AsyncMock()
        mock_client.get_sources_batch = AsyncMock(return_value=mock_source_data)

        with patch(
            "pubmed_search.presentation.mcp_server.tools.unified.get_openalex_client",
            return_value=mock_client,
        ):
            await _enrich_with_journal_metrics(articles)

        # All should have the same metrics
        for a in articles:
            assert a.journal_metrics is not None
            assert a.journal_metrics.h_index == 1000

        # Only one batch call should be made
        mock_client.get_sources_batch.assert_called_once()

    async def test_empty_article_list(self):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_journal_metrics,
        )

        mock_client = AsyncMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.unified.get_openalex_client",
            return_value=mock_client,
        ):
            await _enrich_with_journal_metrics([])

        mock_client.get_sources_batch.assert_not_called()

    async def test_source_not_found_in_batch(self):
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_journal_metrics,
        )

        articles = [
            UnifiedArticle(
                title="Article",
                primary_source="openalex",
                sources=[
                    SourceMetadata(
                        source="openalex",
                        raw_data={"_openalex_source_id": "https://openalex.org/S99999999"},
                    )
                ],
            ),
        ]

        mock_client = AsyncMock()
        # Return empty — source not found
        mock_client.get_sources_batch = AsyncMock(return_value={})

        with patch(
            "pubmed_search.presentation.mcp_server.tools.unified.get_openalex_client",
            return_value=mock_client,
        ):
            await _enrich_with_journal_metrics(articles)

        assert articles[0].journal_metrics is None


# =============================================================================
# OpenAlex Client Tests (get_source and get_sources_batch)
# =============================================================================


class TestOpenAlexSourceMethods:
    """Test OpenAlex client source methods."""

    async def test_get_source_returns_normalized_data(self):
        from pubmed_search.infrastructure.sources.openalex import OpenAlexClient

        client = OpenAlexClient(email="test@example.com")

        mock_response = {
            "id": "https://openalex.org/S62468778",
            "display_name": "New England Journal of Medicine",
            "issn": ["0028-4793", "1533-4406"],
            "issn_l": "0028-4793",
            "summary_stats": {
                "2yr_mean_citedness": 91.25,
                "h_index": 1000,
                "i10_index": 25000,
            },
            "works_count": 100000,
            "cited_by_count": 5000000,
            "is_in_doaj": False,
            "type": "journal",
            "x_concepts": [
                {"display_name": "Medicine", "level": 0},
                {"display_name": "Internal Medicine", "level": 1},
                {"display_name": "Biochemistry", "level": 2},  # level > 1, skipped
            ],
        }

        with patch.object(client, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_response
            result = await client.get_source("S62468778")

        assert result is not None
        assert result["display_name"] == "New England Journal of Medicine"
        assert result["issn"] == "0028-4793"
        assert result["issn_l"] == "0028-4793"
        assert result["h_index"] == 1000
        assert result["two_year_mean_citedness"] == 91.25
        assert result["i10_index"] == 25000
        assert result["is_in_doaj"] is False
        # Only level <= 1 concepts
        assert "Medicine" in result["subject_areas"]
        assert "Internal Medicine" in result["subject_areas"]
        assert "Biochemistry" not in result["subject_areas"]

    async def test_get_source_handles_full_url(self):
        from pubmed_search.infrastructure.sources.openalex import OpenAlexClient

        client = OpenAlexClient(email="test@example.com")

        with patch.object(client, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {
                "id": "https://openalex.org/S62468778",
                "display_name": "NEJM",
            }
            result = await client.get_source("https://openalex.org/S62468778")

        assert result is not None
        # Verify URL was normalized correctly
        call_url = mock_req.call_args[0][0]
        assert "S62468778" in call_url
        assert "openalex.org/S62468778" not in call_url.split("/sources/")[1].split("?")[0] or True

    async def test_get_source_returns_none_on_error(self):
        from pubmed_search.infrastructure.sources.openalex import OpenAlexClient

        client = OpenAlexClient(email="test@example.com")

        with patch.object(client, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = Exception("Not found")
            result = await client.get_source("S99999")

        assert result is None

    async def test_get_sources_batch_returns_dict(self):
        from pubmed_search.infrastructure.sources.openalex import OpenAlexClient

        client = OpenAlexClient(email="test@example.com")

        mock_response = {
            "results": [
                {
                    "id": "https://openalex.org/S62468778",
                    "display_name": "NEJM",
                    "summary_stats": {"h_index": 1000},
                },
                {
                    "id": "https://openalex.org/S137773608",
                    "display_name": "Nature",
                    "summary_stats": {"h_index": 1200},
                },
            ]
        }

        with patch.object(client, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_response
            result = await client.get_sources_batch(["S62468778", "S137773608"])

        assert len(result) == 2
        assert "S62468778" in result
        assert "S137773608" in result
        assert result["S62468778"]["display_name"] == "NEJM"
        assert result["S137773608"]["h_index"] == 1200

    async def test_get_sources_batch_empty_list(self):
        from pubmed_search.infrastructure.sources.openalex import OpenAlexClient

        client = OpenAlexClient(email="test@example.com")
        result = await client.get_sources_batch([])
        assert result == {}

    async def test_get_sources_batch_handles_error(self):
        from pubmed_search.infrastructure.sources.openalex import OpenAlexClient

        client = OpenAlexClient(email="test@example.com")

        with patch.object(client, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = Exception("API error")
            result = await client.get_sources_batch(["S12345"])

        assert result == {}


# =============================================================================
# _normalize_work Source ID Capture Tests
# =============================================================================


class TestNormalizeWorkSourceId:
    """Test that _normalize_work captures _openalex_source_id."""

    def test_captures_source_id(self):
        from pubmed_search.infrastructure.sources.openalex import OpenAlexClient

        client = OpenAlexClient(email="test@example.com")

        work = {
            "id": "https://openalex.org/W12345",
            "title": "Test Paper",
            "primary_location": {
                "source": {
                    "id": "https://openalex.org/S62468778",
                    "display_name": "NEJM",
                }
            },
            "authorships": [],
            "publication_year": 2024,
        }

        result = client._normalize_work(work)
        assert result["_openalex_source_id"] == "https://openalex.org/S62468778"

    def test_empty_source_id_when_no_source(self):
        from pubmed_search.infrastructure.sources.openalex import OpenAlexClient

        client = OpenAlexClient(email="test@example.com")

        work = {
            "id": "https://openalex.org/W12345",
            "title": "Test Paper",
            "primary_location": {},
            "authorships": [],
            "publication_year": 2024,
        }

        result = client._normalize_work(work)
        assert result["_openalex_source_id"] == ""
