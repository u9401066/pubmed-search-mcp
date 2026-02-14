"""
OpenURL Integration Tests

Tests for the institutional access / OpenURL link resolver functionality.
"""

from __future__ import annotations

import pytest


class TestOpenURLBuilder:
    """Test OpenURLBuilder class."""

    async def test_build_from_preset_ntu(self):
        """Test building OpenURL with NTU preset."""
        from pubmed_search.infrastructure.sources.openurl import OpenURLBuilder

        builder = OpenURLBuilder.from_preset("ntu")
        assert "ntu.primo.exlibrisgroup.com" in builder.resolver_base

        url = builder.build_from_article({"pmid": "12345678"})
        assert url is not None
        assert "pmid=12345678" in url

    async def test_build_from_preset_harvard(self):
        """Test building OpenURL with Harvard preset."""
        from pubmed_search.infrastructure.sources.openurl import OpenURLBuilder

        builder = OpenURLBuilder.from_preset("harvard")
        assert "hollis.harvard.edu" in builder.resolver_base

        url = builder.build_from_article(
            {
                "pmid": "33317804",
                "doi": "10.1016/j.bja.2020.10.027",
            }
        )
        assert url is not None
        assert "rft.doi=10.1016" in url

    async def test_build_with_full_metadata(self):
        """Test building OpenURL with complete article metadata."""
        from pubmed_search.infrastructure.sources.openurl import OpenURLBuilder

        builder = OpenURLBuilder(resolver_base="https://test.library.edu/openurl")
        url = builder.build_from_article(
            {
                "pmid": "12345678",
                "doi": "10.1001/jama.2024.1234",
                "title": "Test Article Title",
                "journal": "Test Journal",
                "year": "2024",
                "volume": "100",
                "issue": "5",
                "pages": "123-456",
            }
        )

        assert url is not None
        assert "rft.atitle=Test" in url
        assert "rft.jtitle=Test" in url
        assert "rft.date=2024" in url
        assert "rft.volume=100" in url
        assert "rft.spage=123" in url
        assert "rft.epage=456" in url

    async def test_unknown_preset_raises_error(self):
        """Test that unknown preset raises ValueError."""
        from pubmed_search.infrastructure.sources.openurl import OpenURLBuilder

        with pytest.raises(ValueError, match="Unknown preset"):
            OpenURLBuilder.from_preset("unknown_university")

    async def test_no_resolver_returns_none(self):
        """Test that empty resolver returns None."""
        from pubmed_search.infrastructure.sources.openurl import OpenURLBuilder

        builder = OpenURLBuilder(resolver_base="")
        url = builder.build_from_article({"pmid": "12345678"})
        assert url is None


class TestOpenURLConfig:
    """Test OpenURLConfig class."""

    async def test_config_from_env_preset(self, monkeypatch):
        """Test loading config from OPENURL_PRESET env var."""
        monkeypatch.setenv("OPENURL_PRESET", "ntu")
        monkeypatch.setenv("OPENURL_RESOLVER", "")

        # Reset singleton
        from pubmed_search.infrastructure.sources import openurl

        openurl._openurl_config = None

        from pubmed_search.infrastructure.sources.openurl import OpenURLConfig

        config = OpenURLConfig.from_env()

        assert config.preset == "ntu"
        assert config.enabled is True

        builder = config.get_builder()
        assert builder is not None
        assert "ntu.primo" in builder.resolver_base

    async def test_config_from_env_resolver(self, monkeypatch):
        """Test loading config from OPENURL_RESOLVER env var."""
        monkeypatch.setenv("OPENURL_PRESET", "")
        monkeypatch.setenv("OPENURL_RESOLVER", "https://custom.library.edu/openurl")

        from pubmed_search.infrastructure.sources import openurl

        openurl._openurl_config = None

        from pubmed_search.infrastructure.sources.openurl import OpenURLConfig

        config = OpenURLConfig.from_env()

        assert config.resolver_base == "https://custom.library.edu/openurl"

        builder = config.get_builder()
        assert builder is not None
        assert builder.resolver_base == "https://custom.library.edu/openurl"

    async def test_config_disabled(self, monkeypatch):
        """Test disabled config returns None builder."""
        monkeypatch.setenv("OPENURL_ENABLED", "false")

        from pubmed_search.infrastructure.sources import openurl

        openurl._openurl_config = None

        from pubmed_search.infrastructure.sources.openurl import OpenURLConfig

        config = OpenURLConfig.from_env()

        assert config.enabled is False
        assert config.get_builder() is None


class TestConvenienceFunctions:
    """Test convenience functions."""

    async def test_list_presets(self):
        """Test listing available presets."""
        from pubmed_search.infrastructure.sources.openurl import list_presets

        presets = list_presets()

        # Check some known presets exist
        assert "ntu" in presets
        assert "harvard" in presets
        assert "mit" in presets

        # Check URLs are strings
        for name, url in presets.items():
            assert isinstance(url, str)
            assert len(url) > 0

    async def test_configure_and_get_link(self, monkeypatch):
        """Test configure_openurl and get_openurl_link."""
        # Clear env vars
        monkeypatch.delenv("OPENURL_PRESET", raising=False)
        monkeypatch.delenv("OPENURL_RESOLVER", raising=False)

        from pubmed_search.infrastructure.sources import openurl

        openurl._openurl_config = None

        from pubmed_search.infrastructure.sources.openurl import (
            configure_openurl,
            get_openurl_link,
        )

        # Configure with preset
        configure_openurl(preset="harvard")

        # Get link
        link = get_openurl_link({"pmid": "12345678"})

        assert link is not None
        assert "hollis.harvard.edu" in link


class TestIntegrationWithUnifiedSearch:
    """Test integration with unified search output."""

    async def test_openurl_in_unified_output(self, monkeypatch):
        """Test that OpenURL appears in unified search formatted output."""
        # This would require mocking the searcher, so just test the config
        monkeypatch.setenv("OPENURL_PRESET", "harvard")

        from pubmed_search.infrastructure.sources import openurl

        openurl._openurl_config = None

        from pubmed_search.infrastructure.sources.openurl import get_openurl_config

        config = get_openurl_config()
        assert config.preset == "harvard"
        assert config.enabled is True


# Network tests (require external connectivity, skip in CI)
@pytest.mark.integration
class TestNetworkConnectivity:
    """Test actual network connectivity to resolvers."""

    async def test_harvard_resolver_reachable(self):
        """Test Harvard resolver is reachable."""
        import urllib.request

        from pubmed_search.infrastructure.sources.openurl import OpenURLBuilder

        builder = OpenURLBuilder.from_preset("harvard")
        url = builder.build_from_article({"pmid": "33317804"})

        req = urllib.request.Request(url, headers={"User-Agent": "Test/1.0"})

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                assert response.status == 200
        except urllib.error.HTTPError as e:
            # 3xx, 4xx are acceptable (resolver responded)
            assert e.code < 500
