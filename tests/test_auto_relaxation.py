"""Tests for auto-search-relaxation feature.

Tests the progressive query relaxation engine that automatically
broadens search criteria when 0 results are returned.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.unified.helpers import (
    RelaxationResult,
    RelaxationStep,
    _generate_relaxation_steps,
)
from pubmed_search.infrastructure.sources.unified_broker import _auto_relax_search
from pubmed_search.presentation.mcp_server.tools.unified_formatting import (
    _format_as_json,
    _format_unified_results,
)
from pubmed_search.shared.source_contracts import SourceAdapterError, SourceAdapterResult

# ============================================================================
# _generate_relaxation_steps tests
# ============================================================================


class TestGenerateRelaxationSteps:
    """Test the relaxation step generator."""

    def test_no_steps_for_simple_query(self):
        """Simple 2-word query with no filters → only AND→OR and core keywords steps."""
        steps = _generate_relaxation_steps("cancer treatment", None, None, {})
        # No field tags, no AND (it's implicit in PubMed), no filters
        # Should have 0 or maybe core_keywords if > 2 significant words
        # "cancer treatment" has exactly 2 significant words → no core_keywords step
        assert all(isinstance(s, RelaxationStep) for s in steps)
        # No filters, no year, no field tags, no AND operator
        actions = [s.action for s in steps]
        assert "remove_advanced_filters" not in actions
        assert "remove_year_filter" not in actions

    def test_advanced_filters_relaxation(self):
        """Advanced filters should be the first thing to relax."""
        filters = {"age_group": "aged", "sex": "female", "clinical_query": "therapy"}
        steps = _generate_relaxation_steps("cancer", None, None, filters)

        assert len(steps) >= 1
        assert steps[0].action == "remove_advanced_filters"
        assert steps[0].level == 1
        assert "age_group" in steps[0].description
        assert steps[0].advanced_filters == {}  # Filters cleared

    def test_year_filter_relaxation(self):
        """Year filters should be relaxed at level 2."""
        steps = _generate_relaxation_steps("cancer", 2020, 2024, {})

        year_steps = [s for s in steps if s.action == "remove_year_filter"]
        assert len(year_steps) == 1
        assert year_steps[0].min_year is None
        assert year_steps[0].max_year is None
        assert "2020" in year_steps[0].description

    def test_year_filter_after_advanced_filters(self):
        """Year relaxation should come after advanced filters."""
        filters = {"clinical_query": "therapy"}
        steps = _generate_relaxation_steps("cancer", 2022, None, filters)

        filter_step = next(s for s in steps if s.action == "remove_advanced_filters")
        year_step = next(s for s in steps if s.action == "remove_year_filter")
        assert filter_step.level < year_step.level

    def test_field_tag_relaxation(self):
        """Field tags like [Title] should be removed."""
        steps = _generate_relaxation_steps("(cancer)[Title] AND (treatment)[MeSH Terms]", None, None, {})

        field_steps = [s for s in steps if s.action == "remove_field_tags"]
        assert len(field_steps) == 1
        # Verify field tags are stripped from the relaxed query
        assert "[Title]" not in field_steps[0].query
        assert "[MeSH Terms]" not in field_steps[0].query

    def test_and_to_or_relaxation(self):
        """AND should be relaxed to OR."""
        steps = _generate_relaxation_steps("cancer AND treatment AND therapy", None, None, {})

        or_steps = [s for s in steps if s.action == "and_to_or"]
        assert len(or_steps) == 1
        assert "OR" in or_steps[0].query
        assert "AND" not in or_steps[0].query

    def test_core_keywords_relaxation(self):
        """Long queries should be reduced to core keywords."""
        steps = _generate_relaxation_steps(
            "randomized controlled trial of remimazolam versus propofol for sedation",
            None,
            None,
            {},
        )

        core_steps = [s for s in steps if s.action == "core_keywords_only"]
        assert len(core_steps) == 1
        # Should have at most 3 words
        words = core_steps[0].query.split()
        assert len(words) <= 3

    def test_all_levels_ordered(self):
        """All relaxation levels should be in ascending order."""
        filters = {"clinical_query": "therapy", "age_group": "adult"}
        steps = _generate_relaxation_steps(
            "(cancer)[Title] AND randomized controlled trial[pt] AND (chemotherapy)[MeSH Terms]",
            2020,
            2024,
            filters,
        )

        levels = [s.level for s in steps]
        assert levels == sorted(levels), f"Levels not monotonically increasing: {levels}"
        # Verify ordering: filters < year < pub_type/field_tags < AND→OR < core
        actions = [s.action for s in steps]
        if "remove_advanced_filters" in actions and "remove_year_filter" in actions:
            assert actions.index("remove_advanced_filters") < actions.index("remove_year_filter")

    def test_empty_query_no_crash(self):
        """Empty query should not crash."""
        steps = _generate_relaxation_steps("", None, None, {})
        assert isinstance(steps, list)

    def test_no_duplicate_steps(self):
        """Should not generate duplicate relaxation actions."""
        steps = _generate_relaxation_steps("cancer AND treatment", 2020, 2024, {})
        actions = [s.action for s in steps]
        assert len(actions) == len(set(actions)), f"Duplicate actions: {actions}"

    def test_field_tags_various_formats(self):
        """Should handle various PubMed field tag formats."""
        for query in [
            "test[Title]",
            "test[tiab]",
            "test[Title/Abstract]",
            "test[MeSH Terms]",
            "test[MeSH Term]",
            "test[All Fields]",
        ]:
            steps = _generate_relaxation_steps(query, None, None, {})
            field_steps = [s for s in steps if s.action == "remove_field_tags"]
            assert len(field_steps) >= 1, f"No field tag step for query: {query}"

    def test_no_field_tag_step_when_none_present(self):
        """Should not generate field tag step when none exist."""
        steps = _generate_relaxation_steps("simple query", None, None, {})
        field_steps = [s for s in steps if s.action == "remove_field_tags"]
        assert len(field_steps) == 0

    def test_min_year_only(self):
        """Should handle min_year without max_year."""
        steps = _generate_relaxation_steps("test", 2020, None, {})
        year_steps = [s for s in steps if s.action == "remove_year_filter"]
        assert len(year_steps) == 1
        assert "2020" in year_steps[0].description

    def test_max_year_only(self):
        """Should handle max_year without min_year."""
        steps = _generate_relaxation_steps("test", None, 2024, {})
        year_steps = [s for s in steps if s.action == "remove_year_filter"]
        assert len(year_steps) == 1
        assert "2024" in year_steps[0].description

    def test_stop_words_filtered_in_core_keywords(self):
        """Stop words should be filtered from core keywords."""
        steps = _generate_relaxation_steps(
            "the effect of aspirin on the prevention of heart attack in elderly patients",
            None,
            None,
            {},
        )
        core_steps = [s for s in steps if s.action == "core_keywords_only"]
        if core_steps:
            words = core_steps[0].query.lower().split()
            stop_words = {"the", "of", "on", "in"}
            assert not any(w in stop_words for w in words)


# ============================================================================
# _auto_relax_search tests
# ============================================================================


class TestAutoRelaxSearch:
    """Test the auto-relaxation search loop."""

    @pytest.fixture
    def mock_searcher(self):
        """Create a mock LiteratureSearcher."""
        return AsyncMock()

    async def test_returns_none_when_no_steps(self, mock_searcher):
        """Should return None when no relaxation steps are possible."""
        result = await _auto_relax_search(mock_searcher, "simple", 10, None, None, {})
        # "simple" has no filters, no field tags, no AND, only 1 word
        # So no meaningful relaxation steps → might return None or empty result
        # (depends on whether core_keywords generates a step for 1-word query)
        if result is not None:
            assert isinstance(result, RelaxationResult)

    async def test_tries_relaxation_steps_in_order(self, mock_searcher):
        """Should try relaxation steps in order and stop at first success."""
        from pubmed_search.domain.entities.article import UnifiedArticle

        call_count = 0

        async def mock_search(
            searcher,
            query,
            limit,
            min_year=None,
            max_year=None,
            advanced_filters=None,
            **kwargs,
        ):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return SourceAdapterResult.empty(source="pubmed", operation="search")
            # Second step: has results
            return SourceAdapterResult(
                source="pubmed",
                operation="search",
                items=[UnifiedArticle(title="Test", primary_source="pubmed")],
                total_count=1,
                metadata={"total_available": 1},
            )

        with patch(
            "pubmed_search.infrastructure.sources.unified_broker._search_pubmed_adapter",
            side_effect=mock_search,
        ):
            result = await _auto_relax_search(
                mock_searcher,
                "cancer AND treatment",
                10,
                2020,
                None,
                {"clinical_query": "therapy"},
            )

        assert result is not None
        assert result.successful_step is not None
        # Should have tried at least 2 steps (first failed, second succeeded)
        assert len(result.steps_tried) >= 2

    async def test_returns_result_with_all_steps_failed(self, mock_searcher):
        """Should return result with no successful step when all fail."""
        with patch(
            "pubmed_search.infrastructure.sources.unified_broker._search_pubmed_adapter",
            new_callable=AsyncMock,
            return_value=SourceAdapterResult.empty(source="pubmed", operation="search"),
        ):
            result = await _auto_relax_search(
                mock_searcher,
                "cancer AND treatment",
                10,
                2020,
                None,
                {"clinical_query": "therapy"},
            )

        assert result is not None
        assert result.successful_step is None
        assert len(result.steps_tried) > 0

    async def test_first_step_success(self, mock_searcher):
        """Should stop immediately when first step succeeds."""
        from pubmed_search.domain.entities.article import UnifiedArticle

        with patch(
            "pubmed_search.infrastructure.sources.unified_broker._search_pubmed_adapter",
            new_callable=AsyncMock,
            return_value=SourceAdapterResult(
                source="pubmed",
                operation="search",
                items=[UnifiedArticle(title="Test", primary_source="pubmed")],
                total_count=1,
                metadata={"total_available": 1},
            ),
        ):
            result = await _auto_relax_search(
                mock_searcher,
                "cancer",
                10,
                2020,
                2024,
                {"clinical_query": "therapy"},
            )

        assert result is not None
        assert result.successful_step is not None
        assert result.successful_step.level == 1  # First step
        assert len(result.steps_tried) == 1

    async def test_handles_search_exception(self, mock_searcher):
        """Should handle exceptions during relaxed search gracefully."""
        with patch(
            "pubmed_search.infrastructure.sources.unified_broker._search_pubmed_adapter",
            new_callable=AsyncMock,
            side_effect=Exception("API error"),
        ):
            result = await _auto_relax_search(
                mock_searcher,
                "cancer",
                10,
                2020,
                None,
                {"clinical_query": "therapy"},
            )

        # Should not raise, should return result with all steps failed
        assert result is not None
        assert result.successful_step is None
        assert result.incomplete is True
        assert result.errors
        assert all(step.status == "error" for step in result.steps_tried)
        assert all(step.result_count == 0 for step in result.steps_tried)

    async def test_typed_pubmed_timeout_is_not_reported_as_empty(self, mock_searcher):
        """A real adapter failure must remain unknown coverage, not zero hits."""
        mock_searcher.search_page.side_effect = TimeoutError

        result = await _auto_relax_search(
            mock_searcher,
            "alpha AND beta",
            10,
            None,
            None,
            {},
        )

        assert result is not None
        assert result.successful_step is None
        assert result.incomplete is True
        assert result.steps_tried
        assert all(step.status == "error" for step in result.steps_tried)
        assert all(step.error is not None for step in result.steps_tried)
        assert all(step.error.kind == "timeout" for step in result.steps_tried if step.error)
        assert all(step.error.operation == "search" for step in result.steps_tried if step.error)


# ============================================================================
# Integration-style tests (relaxation in output formatting)
# ============================================================================


class TestRelaxationOutput:
    """Test relaxation info in formatted output."""

    def test_relaxation_step_dataclass(self):
        """Test RelaxationStep dataclass creation."""
        step = RelaxationStep(
            level=1,
            action="remove_advanced_filters",
            description="移除進階篩選條件: clinical_query=therapy",
            query="cancer",
            min_year=None,
            max_year=None,
            advanced_filters={},
            result_count=5,
        )
        assert step.level == 1
        assert step.result_count == 5

    def test_relaxation_result_dataclass(self):
        """Test RelaxationResult dataclass creation."""
        step = RelaxationStep(
            level=2,
            action="remove_year_filter",
            description="移除年份限制",
            query="cancer",
        )
        result = RelaxationResult(
            original_query="cancer",
            relaxed_query="cancer",
            steps_tried=[step],
            successful_step=step,
            total_results=10,
        )
        assert result.total_results == 10
        assert result.successful_step is step

    def test_relaxation_result_no_success(self):
        """Test RelaxationResult with no successful step."""
        step = RelaxationStep(
            level=1,
            action="remove_advanced_filters",
            description="test",
            query="cancer",
            result_count=0,
        )
        result = RelaxationResult(
            original_query="cancer",
            relaxed_query="cancer",
            steps_tried=[step],
            successful_step=None,
            total_results=0,
        )
        assert result.successful_step is None
        assert result.total_results == 0

    @staticmethod
    def _failed_result() -> RelaxationResult:
        error = SourceAdapterError(
            source="pubmed",
            operation="auto_relax",
            message="Request timed out",
            kind="timeout",
            retryable=True,
        )
        step = RelaxationStep(
            level=1,
            action="remove_year_filter",
            description="Remove year constraints",
            query="cancer",
            status="error",
            error=error,
        )
        return RelaxationResult(
            original_query="cancer AND therapy",
            relaxed_query="cancer AND therapy",
            steps_tried=[step],
            successful_step=None,
            total_results=0,
        )

    @staticmethod
    def _format_context():
        analysis = MagicMock()
        analysis.original_query = "cancer AND therapy"
        analysis.complexity.value = "simple"
        analysis.intent.value = "exploration"
        analysis.pico = None
        analysis.to_dict.return_value = {"query": analysis.original_query}
        stats = MagicMock()
        stats.by_source = {"pubmed": 0}
        stats.unique_articles = 0
        stats.duplicates_removed = 0
        stats.to_dict.return_value = {"unique_articles": 0}
        return analysis, stats

    def test_structured_failure_is_incomplete_not_confirmed_empty(self):
        analysis, stats = self._format_context()

        payload = json.loads(_format_as_json([], analysis, stats, relaxation_result=self._failed_result()))

        assert payload["relaxation"]["outcome"] == "incomplete"
        assert payload["relaxation"]["steps_tried"][0]["status"] == "error"
        assert payload["relaxation"]["steps_tried"][0]["error"]["kind"] == "timeout"
        assert "still 0 results" not in payload["relaxation"]["note"]

    async def test_markdown_failure_does_not_claim_every_broader_query_was_empty(self):
        analysis, stats = self._format_context()

        rendered = await _format_unified_results(
            [],
            analysis,
            stats,
            include_analysis=False,
            include_trials=False,
            relaxation_result=self._failed_result(),
        )

        assert "無法宣稱所有較寬查詢皆為零結果" in rendered
        assert "request failed (timeout)" in rendered
        assert "仍無結果" not in rendered
