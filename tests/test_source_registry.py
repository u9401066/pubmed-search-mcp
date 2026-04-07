"""Tests for source registry and source-expression parsing."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from pubmed_search.infrastructure.sources.registry import SourceSelectionError, get_source_registry


class TestSourceRegistry:
    def test_list_unified_sources_contains_current_sources(self):
        registry = get_source_registry()
        available = registry.list_unified_sources()

        assert "pubmed" in available
        assert "openalex" in available
        assert "semantic_scholar" in available
        assert "europe_pmc" in available
        assert "crossref" in available
        assert "core" in available

    def test_resolve_auto_with_exclusion(self):
        registry = get_source_registry()
        selection = registry.resolve_unified_sources(
            "auto,-semantic_scholar",
            auto_sources=["pubmed", "openalex", "semantic_scholar"],
        )

        assert selection.mode == "auto"
        assert selection.sources == ("pubmed", "openalex")
        assert selection.excluded == ("semantic_scholar",)

    def test_exclusion_only_uses_auto_sources(self):
        registry = get_source_registry()
        selection = registry.resolve_unified_sources(
            "-semantic_scholar",
            auto_sources=["pubmed", "semantic_scholar", "europe_pmc"],
        )

        assert selection.mode == "auto"
        assert selection.sources == ("pubmed", "europe_pmc")

    def test_all_keyword_supports_exclusion(self):
        registry = get_source_registry()
        selection = registry.resolve_unified_sources(
            "all,-crossref",
            auto_sources=["pubmed"],
        )

        assert selection.mode == "all"
        assert "crossref" not in selection.sources
        assert "pubmed" in selection.sources
        assert "core" in selection.sources

    def test_invalid_source_raises(self):
        registry = get_source_registry()
        with pytest.raises(SourceSelectionError) as exc_info:
            registry.resolve_unified_sources("auto,-unknown_source", auto_sources=["pubmed"])

        assert "Invalid source(s): unknown_source" in str(exc_info.value)

    def test_env_disabled_source_is_filtered(self):
        registry = get_source_registry()
        with patch.dict("os.environ", {"PUBMED_SEARCH_DISABLED_SOURCES": "semantic_scholar, core"}, clear=False):
            available = registry.list_unified_sources()
            selection = registry.resolve_unified_sources(
                "auto",
                auto_sources=["pubmed", "semantic_scholar", "core", "openalex"],
            )

        assert "semantic_scholar" not in available
        assert "core" not in available
        assert selection.sources == ("pubmed", "openalex")

    def test_commercial_source_default_off(self):
        registry = get_source_registry()

        assert registry.is_enabled("scopus") is False
        assert registry.is_enabled("web_of_science") is False

        with pytest.raises(SourceSelectionError) as exc_info:
            registry.resolve_unified_sources("scopus", auto_sources=["pubmed"])

        assert "Unavailable source(s): scopus" in str(exc_info.value)

    def test_web_of_science_default_off(self):
        registry = get_source_registry()

        with pytest.raises(SourceSelectionError) as exc_info:
            registry.resolve_unified_sources("web_of_science", auto_sources=["pubmed"])

        assert "Unavailable source(s): web_of_science" in str(exc_info.value)

    def test_commercial_source_requires_enable_flag_and_key(self):
        registry = get_source_registry()
        with patch.dict(
            "os.environ",
            {"SCOPUS_ENABLED": "true", "SCOPUS_API_KEY": "licensed-key"},
            clear=False,
        ):
            selection = registry.resolve_unified_sources("all", auto_sources=["pubmed"])

        assert "scopus" in selection.sources

    def test_web_of_science_requires_enable_flag_and_key(self):
        registry = get_source_registry()
        with patch.dict(
            "os.environ",
            {"WEB_OF_SCIENCE_ENABLED": "true", "WEB_OF_SCIENCE_API_KEY": "licensed-key"},
            clear=False,
        ):
            selection = registry.resolve_unified_sources("all", auto_sources=["pubmed"])

        assert "web_of_science" in selection.sources

    def test_commercial_sources_do_not_join_auto_dispatch_by_default(self):
        registry = get_source_registry()
        with patch.dict(
            "os.environ",
            {
                "SCOPUS_ENABLED": "true",
                "SCOPUS_API_KEY": "licensed-key",
                "WEB_OF_SCIENCE_ENABLED": "true",
                "WEB_OF_SCIENCE_API_KEY": "licensed-key",
            },
            clear=False,
        ):
            sources = registry.list_auto_dispatch_sources("complex_systematic")

        assert "pubmed" in sources
        assert "scopus" not in sources
        assert "web_of_science" not in sources
