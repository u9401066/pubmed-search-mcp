"""Tests for centralized Pydantic settings."""

from __future__ import annotations

from pubmed_search.shared.settings import (
    DEFAULT_DATA_DIR,
    DEFAULT_EMAIL,
    DEFAULT_FULLTEXT_INLINE_MAX_CHARS,
    DEFAULT_HTTP_API_PORT,
    load_settings,
)


class TestAppSettings:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("NCBI_EMAIL", raising=False)
        monkeypatch.delenv("PUBMED_DATA_DIR", raising=False)
        monkeypatch.delenv("PUBMED_NOTES_DIR", raising=False)
        monkeypatch.delenv("PUBMED_HTTP_API_PORT", raising=False)
        monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)

        settings = load_settings()

        assert settings.ncbi_email == DEFAULT_EMAIL
        assert settings.data_dir == DEFAULT_DATA_DIR
        assert settings.notes_dir is None
        assert settings.http_api_port == DEFAULT_HTTP_API_PORT
        assert settings.semantic_scholar_api_key is None
        assert settings.artifact_include_local_paths is False
        assert settings.fulltext_inline_max_chars == DEFAULT_FULLTEXT_INLINE_MAX_CHARS

    def test_artifact_runtime_settings_parse(self, monkeypatch):
        monkeypatch.setenv("PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS", "true")
        monkeypatch.setenv("PUBMED_FULLTEXT_INLINE_MAX_CHARS", "1234")

        settings = load_settings()

        assert settings.artifact_include_local_paths is True
        assert settings.fulltext_inline_max_chars == 1234

    def test_disabled_sources_are_normalized(self, monkeypatch):
        monkeypatch.setenv("PUBMED_SEARCH_DISABLED_SOURCES", "semantic-scholar, core")

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
        assert settings.openalex_api_key == "openalex-key"

    def test_semantic_scholar_api_key_strips_empty_values(self, monkeypatch):
        monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "  ")
        assert load_settings().semantic_scholar_api_key is None

        monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", " s2-key ")
        assert load_settings().semantic_scholar_api_key == "s2-key"

    def test_semantic_scholar_api_key_accepts_s2_alias(self, monkeypatch):
        monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
        monkeypatch.setenv("S2_API_KEY", " alias-key ")

        assert load_settings().semantic_scholar_api_key == "alias-key"

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
