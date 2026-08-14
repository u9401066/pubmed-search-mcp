"""Tests for source registry and source-expression parsing."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest

from pubmed_search.infrastructure.sources.registry import (
    SourceCapabilities,
    SourceSelectionError,
    get_source_registry,
)


class TestSourceRegistry:
    def test_capabilities_are_immutable_and_alias_aware(self):
        registry = get_source_registry()
        capabilities = registry.get_capabilities("semantic-scholar")

        assert capabilities == registry.get_capabilities("semantic_scholar")
        assert capabilities is not None
        with pytest.raises(FrozenInstanceError):
            capabilities.max_page_size = 1  # type: ignore[misc]

    def test_openalex_capabilities_cover_semantic_cursor_search(self):
        capabilities = get_source_registry().get_capabilities("openalex")

        assert capabilities is not None
        assert capabilities.search_modes == ("keyword", "semantic", "systematic")
        assert capabilities.pagination == ("page", "cursor")
        assert capabilities.max_page_size == 100
        assert capabilities.mode_limits == (("keyword", 100), ("semantic", 50), ("systematic", 100))
        assert capabilities.operator_data_plane == "provider_available"
        assert capabilities.supports_counts is True

    def test_semantic_scholar_capabilities_cover_bounded_bulk_and_dataset_plane(self):
        capabilities = get_source_registry().get_capabilities("semantic_scholar")

        assert capabilities is not None
        assert capabilities.search_modes == ("relevance", "systematic")
        assert capabilities.pagination == ("offset", "token")
        assert capabilities.max_page_size == 1000
        assert capabilities.mode_limits == (("relevance", 100), ("systematic", 1000))
        assert capabilities.batch_limit == 500
        assert capabilities.operator_data_plane == "metadata_only"
        assert capabilities.supports_counts is True

    def test_capability_manifest_is_json_safe_and_contains_no_configuration_secrets(self):
        registry = get_source_registry()
        manifest = registry.capability_manifest()

        encoded = json.dumps(manifest)
        assert json.loads(encoded) == manifest
        assert "required_env_vars" not in encoded
        assert "enable_env_var" not in encoded
        assert "SCOPUS_API_KEY" not in encoded
        assert "CLINICALKEY" not in encoded.upper()
        assert "clinicalkey_ai" not in manifest

    def test_conservative_capabilities_for_other_selectable_source_classes(self):
        registry = get_source_registry()

        europe_pmc = registry.get_capabilities("europe_pmc")
        core = registry.get_capabilities("core")
        scopus = registry.get_capabilities("scopus")
        arxiv = registry.get_capabilities("arxiv")
        crossref = registry.get_capabilities("crossref")

        assert europe_pmc == SourceCapabilities(
            search_modes=("keyword",),
            pagination=("cursor",),
            max_page_size=1000,
            mode_limits=(("keyword", 1000),),
            supports_counts=True,
            supports_provenance=True,
        )
        assert core == SourceCapabilities(
            search_modes=("keyword",),
            pagination=("offset",),
            max_page_size=100,
            supports_counts=True,
            supports_provenance=True,
        )
        assert scopus == SourceCapabilities(
            search_modes=("keyword",),
            pagination=("offset",),
            max_page_size=25,
            mode_limits=(("keyword", 25),),
            supports_provenance=True,
        )
        assert arxiv == SourceCapabilities(
            search_modes=("keyword",),
            max_page_size=100,
            supports_provenance=True,
        )
        assert crossref == SourceCapabilities(
            search_modes=("enrichment",),
            pagination=("offset",),
            max_page_size=1000,
            supports_counts=True,
            supports_provenance=True,
        )

    def test_capability_metadata_does_not_change_unified_source_selection(self):
        registry = get_source_registry()
        with patch.dict(
            "os.environ",
            {
                "SCOPUS_ENABLED": "false",
                "SCOPUS_API_KEY": "",
                "WEB_OF_SCIENCE_ENABLED": "false",
                "WEB_OF_SCIENCE_API_KEY": "",
                "PUBMED_SEARCH_DISABLED_SOURCES": "",
            },
            clear=False,
        ):
            available = registry.list_unified_sources()
            selection = registry.resolve_unified_sources(
                "pubmed,openalex,semantic-scholar,crossref",
                auto_sources=["pubmed"],
            )

        assert available == [
            "pubmed",
            "openalex",
            "semantic_scholar",
            "europe_pmc",
            "core",
            "crossref",
            "arxiv",
            "medrxiv",
            "biorxiv",
        ]
        assert selection.mode == "explicit"
        assert selection.sources == ("pubmed", "openalex", "semantic_scholar", "crossref")

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

    def test_enrichment_only_source_raises(self):
        registry = get_source_registry()

        with pytest.raises(SourceSelectionError, match="primary search source"):
            registry.resolve_unified_sources("crossref", auto_sources=["pubmed"])

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

    def test_env_disabled_source_aliases_are_filtered(self):
        registry = get_source_registry()
        with patch.dict(
            "os.environ",
            {"PUBMED_SEARCH_DISABLED_SOURCES": "semantic-scholar, Europe PMC"},
            clear=False,
        ):
            available = registry.list_unified_sources()
            selection = registry.resolve_unified_sources(
                "auto",
                auto_sources=["pubmed", "semantic_scholar", "europe_pmc", "openalex"],
            )

        assert "semantic_scholar" not in available
        assert "europe_pmc" not in available
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

    def test_disabled_source_wins_over_enabled_commercial_credentials(self):
        registry = get_source_registry()
        with patch.dict(
            "os.environ",
            {
                "SCOPUS_ENABLED": "true",
                "SCOPUS_API_KEY": "licensed-key",
                "PUBMED_SEARCH_DISABLED_SOURCES": "scopus",
            },
            clear=False,
        ):
            assert registry.is_enabled("scopus") is False
            with pytest.raises(SourceSelectionError) as exc_info:
                registry.resolve_unified_sources("scopus", auto_sources=["pubmed"])

        assert "Unavailable source(s): scopus" in str(exc_info.value)
