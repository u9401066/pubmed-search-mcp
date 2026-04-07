"""Tests for centralized Pydantic settings."""

from __future__ import annotations

from pubmed_search.shared.settings import DEFAULT_DATA_DIR, DEFAULT_EMAIL, DEFAULT_HTTP_API_PORT, load_settings


class TestAppSettings:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("NCBI_EMAIL", raising=False)
        monkeypatch.delenv("PUBMED_DATA_DIR", raising=False)
        monkeypatch.delenv("PUBMED_HTTP_API_PORT", raising=False)

        settings = load_settings()

        assert settings.ncbi_email == DEFAULT_EMAIL
        assert settings.data_dir == DEFAULT_DATA_DIR
        assert settings.http_api_port == DEFAULT_HTTP_API_PORT

    def test_disabled_sources_are_normalized(self, monkeypatch):
        monkeypatch.setenv("PUBMED_SEARCH_DISABLED_SOURCES", "semantic-scholar, core")

        settings = load_settings()

        assert settings.disabled_sources == ("semantic_scholar", "core")

    def test_commercial_source_flags_parse(self, monkeypatch):
        monkeypatch.setenv("SCOPUS_ENABLED", "true")
        monkeypatch.setenv("SCOPUS_API_KEY", "licensed-key")
        monkeypatch.setenv("WEB_OF_SCIENCE_ENABLED", "1")
        monkeypatch.setenv("WEB_OF_SCIENCE_API_KEY", "wos-key")

        settings = load_settings()

        assert settings.scopus_enabled is True
        assert settings.scopus_api_key == "licensed-key"
        assert settings.web_of_science_enabled is True
        assert settings.web_of_science_api_key == "wos-key"

    def test_empty_openurl_values_are_allowed(self, monkeypatch):
        monkeypatch.setenv("OPENURL_RESOLVER", "")
        monkeypatch.setenv("OPENURL_PRESET", "")

        settings = load_settings()

        assert settings.openurl_resolver == ""
        assert settings.openurl_preset == ""