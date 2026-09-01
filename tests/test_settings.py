"""Tests for centralized Pydantic settings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pubmed_search.shared.settings import (
    DEFAULT_DATA_DIR,
    DEFAULT_EMAIL,
    DEFAULT_FULLTEXT_INLINE_MAX_CHARS,
    get_settings,
    load_settings,
    reset_settings_cache,
)


class TestAppSettings:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("NCBI_EMAIL", raising=False)
        monkeypatch.delenv("PUBMED_DATA_DIR", raising=False)
        monkeypatch.delenv("PUBMED_NOTES_DIR", raising=False)
        monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
        monkeypatch.delenv("S2_API_KEY", raising=False)

        settings = load_settings()

        assert settings.ncbi_email == DEFAULT_EMAIL
        assert settings.data_dir == DEFAULT_DATA_DIR
        assert settings.notes_dir is None
        assert settings.semantic_scholar_api_key is None
        assert settings.artifact_include_local_paths is False
        assert settings.fulltext_inline_max_chars == DEFAULT_FULLTEXT_INLINE_MAX_CHARS

    def test_artifact_runtime_settings_parse(self, monkeypatch):
        monkeypatch.setenv("PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS", "true")
        monkeypatch.setenv("PUBMED_FULLTEXT_INLINE_MAX_CHARS", "1234")

        settings = load_settings()

        assert settings.artifact_include_local_paths is True
        assert settings.fulltext_inline_max_chars == 1234

    @pytest.mark.parametrize("value", ["0", "255", "200001"])
    def test_fulltext_inline_limit_is_bounded(self, monkeypatch, value):
        monkeypatch.setenv("PUBMED_FULLTEXT_INLINE_MAX_CHARS", value)

        with pytest.raises(ValidationError):
            load_settings()

    def test_disabled_sources_preserve_canonical_keys(self, monkeypatch):
        monkeypatch.setenv("PUBMED_SEARCH_DISABLED_SOURCES", "semantic_scholar, core")

        settings = load_settings()

        assert settings.disabled_sources == ("semantic_scholar", "core")

    def test_commercial_source_flags_parse(self, monkeypatch):
        monkeypatch.setenv("SCOPUS_ENABLED", "true")
        monkeypatch.setenv("SCOPUS_API_KEY", "licensed-key")
        monkeypatch.setenv("WEB_OF_SCIENCE_ENABLED", "1")
        monkeypatch.setenv("WEB_OF_SCIENCE_API_KEY", "wos-key")
        monkeypatch.setenv("OPENALEX_API_KEY", "openalex-key")

        settings = load_settings()

        assert settings.scopus_enabled is True
        assert settings.scopus_api_key == "licensed-key"
        assert settings.web_of_science_enabled is True
        assert settings.web_of_science_api_key == "wos-key"
        assert settings.openalex_api_key is not None
        assert settings.openalex_api_key.get_secret_value() == "openalex-key"

    def test_semantic_scholar_api_key_strips_empty_values(self, monkeypatch):
        monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "  ")
        assert load_settings().semantic_scholar_api_key is None

        monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", " s2-key ")
        semantic_key = load_settings().semantic_scholar_api_key
        assert semantic_key is not None
        assert semantic_key.get_secret_value() == "s2-key"

    def test_ncbi_api_key_strips_empty_values(self, monkeypatch):
        monkeypatch.setenv("NCBI_API_KEY", "  ")
        assert load_settings().ncbi_api_key is None

        monkeypatch.setenv("NCBI_API_KEY", " ncbi-key ")
        assert load_settings().ncbi_api_key == "ncbi-key"

    def test_retired_s2_api_key_does_not_configure_semantic_scholar(self, monkeypatch):
        monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
        monkeypatch.setenv("S2_API_KEY", " alias-key ")

        assert load_settings().semantic_scholar_api_key is None

    def test_provider_keys_are_redacted_from_settings_repr(self, monkeypatch):
        monkeypatch.setenv("OPENALEX_API_KEY", "openalex-secret")
        monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "semantic-secret")

        rendered = repr(load_settings())

        assert "openalex-secret" not in rendered
        assert "semantic-secret" not in rendered
        assert "**********" in rendered

    def test_empty_openurl_values_are_allowed(self, monkeypatch):
        monkeypatch.setenv("OPENURL_RESOLVER", "")
        monkeypatch.setenv("OPENURL_PRESET", "")

        settings = load_settings()

        assert settings.openurl_resolver == ""
        assert settings.openurl_preset == ""

    def test_notes_dir_strips_empty_values(self, monkeypatch):
        monkeypatch.setenv("PUBMED_NOTES_DIR", "  ")

        settings = load_settings()

        assert settings.notes_dir is None

    def test_cached_settings_require_explicit_reset(self, monkeypatch):
        reset_settings_cache()
        monkeypatch.setenv("NCBI_EMAIL", "first@example.com")
        first = get_settings()

        monkeypatch.setenv("NCBI_EMAIL", "second@example.com")
        assert get_settings() is first
        assert get_settings().ncbi_email == "first@example.com"

        reset_settings_cache()
        assert get_settings().ncbi_email == "second@example.com"
        reset_settings_cache()
