"""Tests for openurl MCP tools — configure, link, presets, test."""

from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from pubmed_search.presentation.mcp_server.tools.openurl import (
    register_openurl_tools,
    _format_article,
    _test_resolver_url,
)


def _capture_tools(mcp):
    tools = {}
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
    register_openurl_tools(mcp)
    return tools


@pytest.fixture
def tools():
    return _capture_tools(MagicMock())


# ============================================================
# _format_article (pure helper)
# ============================================================

class TestFormatArticle:
    def test_full_article(self):
        art = {"pmid": "123", "doi": "10.1/x", "title": "A"*100,
               "journal": "Nature", "year": "2024"}
        result = _format_article(art)
        assert "PMID: 123" in result
        assert "DOI: 10.1/x" in result
        assert "Nature" in result

    def test_empty_article(self):
        result = _format_article({})
        assert "No metadata" in result


# ============================================================
# _test_resolver_url
# ============================================================

class TestTestResolverUrl:
    @pytest.mark.asyncio
    async def test_invalid_scheme(self):
        result = await _test_resolver_url("ftp://example.com")
        assert result["reachable"] is False
        assert "scheme" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_unreachable(self):
        with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
            result = await _test_resolver_url("https://nonexistent.example.com/test")
        assert result["reachable"] is False

    @pytest.mark.asyncio
    async def test_http_error_still_reachable(self):
        import urllib.error
        err = urllib.error.HTTPError(
            "https://example.com", 403, "Forbidden", {}, None
        )
        with patch("urllib.request.urlopen", side_effect=err):
            result = await _test_resolver_url("https://example.com/resolver")
        assert result["reachable"] is True
        assert result["status_code"] == 403


# ============================================================
# configure_institutional_access
# ============================================================

class TestConfigureInstitutionalAccess:
    @pytest.mark.asyncio
    async def test_disable(self, tools):
        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.configure_openurl"
        ) as mock:
            result = await tools["configure_institutional_access"](enable=False)
        assert "disabled" in result.lower()
        mock.assert_called_once_with(enabled=False)

    @pytest.mark.asyncio
    async def test_unknown_preset(self, tools):
        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.list_presets",
            return_value={"ntu": "http://ntu.edu/resolver"},
        ):
            result = await tools["configure_institutional_access"](preset="zzz")
        assert "unknown" in result.lower() or "Unknown" in result

    @pytest.mark.asyncio
    async def test_valid_preset(self, tools):
        mock_config = MagicMock()
        mock_builder = MagicMock()
        mock_builder.resolver_base = "http://ntu.edu/resolver"
        mock_config.get_builder.return_value = mock_builder

        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.list_presets",
            return_value={"ntu": "http://ntu.edu/resolver"},
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.configure_openurl"
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.get_openurl_config",
            return_value=mock_config,
        ):
            result = await tools["configure_institutional_access"](preset="ntu")
        assert "configured" in result.lower() or "✅" in result

    @pytest.mark.asyncio
    async def test_custom_url(self, tools):
        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.configure_openurl"
        ):
            result = await tools["configure_institutional_access"](
                resolver_url="https://mylib.edu/resolver"
            )
        assert "configured" in result.lower() or "✅" in result

    @pytest.mark.asyncio
    async def test_show_current_config(self, tools):
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.resolver_base = "http://test.edu"
        mock_config.preset = None

        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.get_openurl_config",
            return_value=mock_config,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.list_presets",
            return_value={"ntu": "http://ntu.edu/resolver"},
        ):
            result = await tools["configure_institutional_access"]()
        assert "configuration" in result.lower() or "Status" in result

    @pytest.mark.asyncio
    async def test_exception(self, tools):
        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.configure_openurl",
            side_effect=RuntimeError("fail"),
        ):
            result = await tools["configure_institutional_access"](enable=False)
        # Should handle exception (via try/except in the tool)
        # The disable path calls configure_openurl before reaching other code
        assert "fail" in result.lower() or "Error" in result or "❌" in result


# ============================================================
# get_institutional_link
# ============================================================

class TestGetInstitutionalLink:
    @pytest.mark.asyncio
    async def test_not_configured(self, tools):
        mock_config = MagicMock()
        mock_config.get_builder.return_value = None

        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.get_openurl_config",
            return_value=mock_config,
        ):
            result = await tools["get_institutional_link"]()
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_no_identifiers(self, tools):
        mock_config = MagicMock()
        mock_builder = MagicMock()
        mock_config.get_builder.return_value = mock_builder

        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.get_openurl_config",
            return_value=mock_config,
        ):
            result = await tools["get_institutional_link"]()
        assert "provide" in result.lower() or "identifier" in result.lower()

    @pytest.mark.asyncio
    async def test_with_pmid(self, tools):
        mock_config = MagicMock()
        mock_builder = MagicMock()
        mock_builder.build_from_article.return_value = "https://resolver.edu/?pmid=123"
        mock_config.get_builder.return_value = mock_builder

        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.get_openurl_config",
            return_value=mock_config,
        ):
            result = await tools["get_institutional_link"](pmid="123")
        assert "resolver.edu" in result

    @pytest.mark.asyncio
    async def test_url_generation_fails(self, tools):
        mock_config = MagicMock()
        mock_builder = MagicMock()
        mock_builder.build_from_article.return_value = None
        mock_config.get_builder.return_value = mock_builder

        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.get_openurl_config",
            return_value=mock_config,
        ):
            result = await tools["get_institutional_link"](pmid="123")
        assert "could not" in result.lower() or "❌" in result


# ============================================================
# list_resolver_presets
# ============================================================

class TestListResolverPresets:
    @pytest.mark.asyncio
    async def test_returns_presets(self, tools):
        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.list_presets",
            return_value={
                "ntu": "http://ntu.edu",
                "harvard": "http://harvard.edu",
                "sfx": "http://sfx.example.com",
            },
        ):
            result = await tools["list_resolver_presets"]()
        assert "ntu" in result
        assert "harvard" in result


# ============================================================
# test_institutional_access
# ============================================================

class TestTestInstitutionalAccess:
    @pytest.mark.asyncio
    async def test_not_configured(self, tools):
        mock_config = MagicMock()
        mock_config.get_builder.return_value = None

        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.get_openurl_config",
            return_value=mock_config,
        ):
            result = await tools["test_institutional_access"]()
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_configured_and_reachable(self, tools):
        mock_config = MagicMock()
        mock_builder = MagicMock()
        mock_builder.resolver_base = "https://resolver.test.edu"
        mock_builder.build_from_article.return_value = "https://resolver.test.edu?openurl"
        mock_config.get_builder.return_value = mock_builder

        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.get_openurl_config",
            return_value=mock_config,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.openurl._test_resolver_url",
            return_value={
                "reachable": True,
                "status_code": 200,
                "response_time_ms": 50,
                "error": None,
            },
        ):
            result = await tools["test_institutional_access"](pmid="12345")
        assert "reachable" in result.lower() or "✅" in result
