"""Tests for openurl MCP tools — configure, link, presets, test."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic import ValidationError

from pubmed_search.infrastructure.http.safe_outbound import SafeFetchResult, SafeOutboundError
from pubmed_search.infrastructure.sources.institutional_fetch import (
    AccessDiagnosis,
    ProbeResult,
)
from pubmed_search.presentation.mcp_server.tools.article_source import DOISource, PMIDSource
from pubmed_search.presentation.mcp_server.tools.openurl import (
    InstitutionalMetadataSource,
    _format_article,
    _test_resolver_url,
    register_openurl_tools,
)
from pubmed_search.shared.tenancy import TenantIdentity, bind_tenant


def _capture_tools(mcp, searcher=None):
    tools = {}
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
    register_openurl_tools(mcp, searcher or AsyncMock())
    return tools


@pytest.fixture
def tools():
    return _capture_tools(MagicMock())


# ============================================================
# _format_article (pure helper)
# ============================================================


class TestFormatArticle:
    async def test_full_article(self):
        art = {
            "pmid": "123",
            "doi": "10.1/x",
            "title": "A" * 100,
            "journal": "Nature",
            "year": "2024",
        }
        result = _format_article(art)
        assert "PMID: 123" in result
        assert "DOI: 10.1/x" in result
        assert "Nature" in result

    async def test_empty_article(self):
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
        assert "rejected" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_unreachable(self):
        with patch(
            "pubmed_search.infrastructure.http.safe_outbound.fetch_public_url",
            new_callable=AsyncMock,
            side_effect=SafeOutboundError("failed"),
        ):
            result = await _test_resolver_url("https://nonexistent.example.com/test")
        assert result["reachable"] is False

    @pytest.mark.asyncio
    async def test_private_destination_is_rejected_without_request(self):
        result = await _test_resolver_url("http://127.0.0.1/internal")

        assert result["reachable"] is False
        assert "safely" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_http_error_still_reachable(self):
        request = httpx.Request("GET", "https://example.com/resolver")
        mock_response = httpx.Response(403, request=request)
        with patch(
            "pubmed_search.infrastructure.http.safe_outbound.fetch_public_url",
            new_callable=AsyncMock,
            return_value=SafeFetchResult(response=mock_response, redirect_chain=("https://example.com/…",)),
        ):
            result = await _test_resolver_url("https://example.com/resolver")
        assert result["reachable"] is True
        assert result["status_code"] == 403


# ============================================================
# configure_institutional_access
# ============================================================


class TestConfigureInstitutionalAccess:
    async def test_disable(self, tools):
        with patch("pubmed_search.presentation.mcp_server.tools.openurl.configure_openurl") as mock:
            result = tools["configure_institutional_access"](enable=False)
        assert "disabled" in result.lower()
        mock.assert_called_once_with(enabled=False)

    async def test_unknown_preset(self, tools):
        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.list_presets",
            return_value={"ntu": "http://ntu.edu/resolver"},
        ):
            result = tools["configure_institutional_access"](preset="zzz")
        assert "unknown" in result.lower() or "Unknown" in result

    async def test_valid_preset(self, tools):
        mock_config = MagicMock()
        mock_builder = MagicMock()
        mock_builder.resolver_base = "http://ntu.edu/resolver"
        mock_config.get_builder.return_value = mock_builder

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.openurl.list_presets",
                return_value={"ntu": "http://ntu.edu/resolver"},
            ),
            patch("pubmed_search.presentation.mcp_server.tools.openurl.configure_openurl"),
            patch(
                "pubmed_search.presentation.mcp_server.tools.openurl.get_openurl_config",
                return_value=mock_config,
            ),
        ):
            result = tools["configure_institutional_access"](preset="ntu")
        assert "configured" in result.lower() or "✅" in result

    async def test_custom_url(self, tools):
        mock_config = MagicMock()
        mock_builder = MagicMock(resolver_base="https://mylib.edu/resolver")
        mock_config.get_builder.return_value = mock_builder
        with (
            patch("pubmed_search.presentation.mcp_server.tools.openurl.configure_openurl"),
            patch(
                "pubmed_search.presentation.mcp_server.tools.openurl.get_openurl_config",
                return_value=mock_config,
            ),
        ):
            result = tools["configure_institutional_access"](resolver_url="https://mylib.edu/resolver")
        assert "configured" in result.lower() or "✅" in result

    async def test_custom_url_rejects_query_credentials_without_echoing_them(self, tools):
        secret_url = "https://library.example/openurl?api_key=private-token"
        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.configure_openurl",
            side_effect=ValueError("OpenURL resolver URL must not contain a query"),
        ) as configure:
            result = tools["configure_institutional_access"](resolver_url=secret_url)

        configure.assert_called_once()
        assert "private-token" not in result
        assert "could not be completed" in result

    async def test_show_current_config(self, tools):
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.resolver_base = "http://test.edu"
        mock_config.preset = None
        mock_builder = MagicMock(resolver_base="http://test.edu")
        mock_config.get_builder.return_value = mock_builder

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.openurl.get_openurl_config",
                return_value=mock_config,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.openurl.list_presets",
                return_value={"ntu": "http://ntu.edu/resolver"},
            ),
        ):
            result = tools["configure_institutional_access"]()
        assert "configuration" in result.lower() or "Status" in result

    @pytest.mark.parametrize(
        "arguments",
        [
            {"enable": False},
            {"preset": "ntu"},
            {"resolver_url": "https://library.example/openurl"},
        ],
    )
    @pytest.mark.parametrize("identity_source", ["auth", "transport", "anonymous_http"])
    async def test_authenticated_service_cannot_mutate_deployment_config(self, tools, arguments, identity_source):
        identity = TenantIdentity.for_principal("remote-team", source=identity_source)

        with (
            patch("pubmed_search.presentation.mcp_server.tools.openurl.configure_openurl") as configure,
            bind_tenant(identity),
        ):
            result = tools["configure_institutional_access"](**arguments)

        assert "cannot change the server-owned, deployment-wide" in result
        configure.assert_not_called()

    async def test_authenticated_service_may_read_current_config(self, tools):
        identity = TenantIdentity.for_principal("remote-team", source="auth")
        mock_config = MagicMock(enabled=True, resolver_base="https://operator.example/openurl", preset=None)
        mock_config.get_builder.return_value = MagicMock(resolver_base="https://operator.example/openurl")

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.openurl.get_openurl_config",
                return_value=mock_config,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.openurl.list_presets",
                return_value={"ntu": "https://ntu.example/openurl"},
            ),
            patch("pubmed_search.presentation.mcp_server.tools.openurl.configure_openurl") as configure,
            bind_tenant(identity),
        ):
            result = tools["configure_institutional_access"]()

        assert "https://operator.example/openurl" in result
        configure.assert_not_called()

    async def test_authenticated_read_does_not_echo_invalid_raw_resolver(self, tools):
        identity = TenantIdentity.for_principal("remote-team", source="auth")
        mock_config = MagicMock(
            enabled=True,
            resolver_base="https://operator.example/openurl?token=private-token",
            preset="",
        )
        mock_config.get_builder.return_value = None

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.openurl.get_openurl_config",
                return_value=mock_config,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.openurl.list_presets",
                return_value={"ntu": "https://ntu.example/openurl"},
            ),
            bind_tenant(identity),
        ):
            result = tools["configure_institutional_access"]()

        assert "private-token" not in result
        assert "Not configured" in result

    async def test_authenticated_read_does_not_echo_invalid_raw_preset(self, tools):
        identity = TenantIdentity.for_principal("remote-team", source="auth")
        mock_config = MagicMock(enabled=True, resolver_base="", preset="private-token")
        mock_config.get_builder.return_value = None

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.openurl.get_openurl_config",
                return_value=mock_config,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.openurl.list_presets",
                return_value={"ntu": "https://ntu.example/openurl"},
            ),
            bind_tenant(identity),
        ):
            result = tools["configure_institutional_access"]()

        assert "private-token" not in result
        assert "Invalid configuration" in result

    async def test_exception(self, tools):
        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.configure_openurl",
            side_effect=RuntimeError("fail"),
        ):
            result = tools["configure_institutional_access"](enable=False)
        # Should handle exception (via try/except in the tool)
        # The disable path calls configure_openurl before reaching other code
        assert "fail" not in result.lower()
        assert "Error" in result or "❌" in result


# ============================================================
# get_institutional_link
# ============================================================


class TestGetInstitutionalLink:
    @pytest.mark.parametrize(
        "payload",
        [
            {"kind": "metadata", "title": "   "},
            {"kind": "metadata", "title": "Example", "year": "2024"},
            {"kind": "metadata", "title": "Example", "year": 999},
            {"kind": "metadata", "title": "Example", "journal": "J\nAMA"},
            {"kind": "metadata", "title": "Example", "unexpected": "field"},
        ],
    )
    def test_metadata_source_rejects_non_exact_values(self, payload):
        with pytest.raises(ValidationError):
            InstitutionalMetadataSource.model_validate(payload)

    async def test_not_configured(self, tools):
        mock_config = MagicMock()
        mock_config.get_builder.return_value = None

        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.get_openurl_config",
            return_value=mock_config,
        ):
            result = tools["get_institutional_link"](source=PMIDSource(kind="pmid", value="123"))
        assert "not configured" in result.lower()

    async def test_with_pmid(self, tools):
        mock_config = MagicMock()
        mock_builder = MagicMock()
        mock_builder.build_from_article.return_value = "https://resolver.edu/?pmid=123"
        mock_config.get_builder.return_value = mock_builder

        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.get_openurl_config",
            return_value=mock_config,
        ):
            result = tools["get_institutional_link"](source=PMIDSource(kind="pmid", value="123"))
        assert "resolver.edu" in result
        mock_builder.build_from_article.assert_called_once_with({"pmid": "123"})

    async def test_with_bounded_metadata(self, tools):
        mock_config = MagicMock()
        mock_builder = MagicMock()
        mock_builder.build_from_article.return_value = "https://resolver.edu/?title=Example"
        mock_config.get_builder.return_value = mock_builder

        source = InstitutionalMetadataSource(
            kind="metadata",
            title="Example",
            journal="JAMA",
            year=2024,
            volume="331",
            issue="1",
            pages="45-52",
        )
        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.get_openurl_config",
            return_value=mock_config,
        ):
            result = tools["get_institutional_link"](source=source)

        assert "resolver.edu" in result
        mock_builder.build_from_article.assert_called_once_with(
            {
                "title": "Example",
                "journal": "JAMA",
                "year": "2024",
                "volume": "331",
                "issue": "1",
                "pages": "45-52",
            }
        )

    async def test_url_generation_fails(self, tools):
        mock_config = MagicMock()
        mock_builder = MagicMock()
        mock_builder.build_from_article.return_value = None
        mock_config.get_builder.return_value = mock_builder

        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.get_openurl_config",
            return_value=mock_config,
        ):
            result = tools["get_institutional_link"](source=PMIDSource(kind="pmid", value="123"))
        assert "could not" in result.lower() or "❌" in result


# ============================================================
# list_resolver_presets
# ============================================================


class TestListResolverPresets:
    async def test_returns_presets(self, tools):
        with patch(
            "pubmed_search.presentation.mcp_server.tools.openurl.list_presets",
            return_value={
                "ntu": "http://ntu.edu",
                "harvard": "http://harvard.edu",
                "sfx": "http://sfx.example.com",
            },
        ):
            result = tools["list_resolver_presets"]()
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

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.openurl.get_openurl_config",
                return_value=mock_config,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.openurl._test_resolver_url",
                new_callable=AsyncMock,
                return_value={
                    "reachable": True,
                    "status_code": 200,
                    "response_time_ms": 50,
                    "error": None,
                },
            ),
        ):
            result = await tools["test_institutional_access"](pmid="12345")
        assert "reachable" in result.lower() or "✅" in result


# ============================================================
# diagnose_institutional_access
# ============================================================


class TestDiagnoseInstitutionalAccess:
    @pytest.mark.asyncio
    async def test_formats_diagnosis_and_delegates_flags(self, tools):
        diagnosis = AccessDiagnosis(
            pmid="12345",
            doi="10.1000/example",
            summary="Fulltext reachable via direct path.",
            openurl="https://resolver.example/openurl",
            recommended_path="direct",
            probes=[
                ProbeResult(
                    path="direct",
                    attempted=True,
                    success=True,
                    final_url="https://publisher.example/article",
                    status_code=200,
                    content_class="fulltext_html",
                    content_length=4096,
                    redirect_chain=[
                        "https://doi.org/10.1000/example",
                        "https://publisher.example/article",
                    ],
                    duration_ms=120,
                ),
                ProbeResult(
                    path="ezproxy",
                    attempted=False,
                    success=False,
                    error="not configured",
                    advice="Configure EZPROXY_HOST first.",
                ),
            ],
        )

        with patch(
            "pubmed_search.infrastructure.sources.institutional_fetch.diagnose_access",
            new_callable=AsyncMock,
            return_value=diagnosis,
        ) as mock_diagnose:
            result = await tools["diagnose_institutional_access"](
                source=DOISource(kind="doi", value="10.1000/example"),
                try_direct=True,
                try_ezproxy=False,
            )

        mock_diagnose.assert_awaited_once_with(
            pmid=None,
            doi="10.1000/example",
            try_direct=True,
            try_ezproxy=False,
        )
        assert "Institutional Access Diagnosis" in result
        assert "DOI**: 10.1000/example" in result
        assert "Recommended path**: `direct`" in result
        assert "OpenURL handoff" in result
        assert "`direct` probe" in result
        assert "content_class: `fulltext_html`" in result
        assert "_Skipped_: not configured" in result

    @pytest.mark.asyncio
    async def test_distinguishes_pubmed_resolution_outage_from_missing_doi(self):
        searcher = AsyncMock()
        searcher.fetch_details.side_effect = RuntimeError(
            "upstream https://private.example/detail?token=private-token failed"
        )
        tools = _capture_tools(MagicMock(), searcher)
        diagnosis = AccessDiagnosis(
            pmid="12345",
            summary="No DOI supplied. Direct/EZproxy fetch needs a DOI.",
            openurl="https://resolver.example/openurl",
            recommended_path=None,
        )

        with patch(
            "pubmed_search.infrastructure.sources.institutional_fetch.diagnose_access",
            new_callable=AsyncMock,
            return_value=diagnosis,
        ) as mock_diagnose:
            result = await tools["diagnose_institutional_access"](source=PMIDSource(kind="pmid", value="12345"))

        mock_diagnose.assert_awaited_once_with(
            pmid="12345",
            doi=None,
            try_direct=True,
            try_ezproxy=True,
        )
        assert "PMID→DOI resolution**: `error`" in result
        assert "PubMed DOI resolution was unavailable" in result
        assert "No DOI supplied" not in result
        assert "private-token" not in result

    @pytest.mark.asyncio
    async def test_reports_true_missing_doi_separately(self):
        searcher = AsyncMock()
        searcher.fetch_details.return_value = [{"pmid": "12345", "doi": None}]
        tools = _capture_tools(MagicMock(), searcher)
        diagnosis = AccessDiagnosis(
            pmid="12345",
            summary="No DOI supplied. Direct/EZproxy fetch needs a DOI.",
        )

        with patch(
            "pubmed_search.infrastructure.sources.institutional_fetch.diagnose_access",
            new_callable=AsyncMock,
            return_value=diagnosis,
        ):
            result = await tools["diagnose_institutional_access"](source=PMIDSource(kind="pmid", value="12345"))

        assert "PMID→DOI resolution**: `not_found`" in result
        assert "No DOI supplied" in result
