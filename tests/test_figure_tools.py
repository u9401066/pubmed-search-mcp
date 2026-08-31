"""Tests for figure_tools MCP tool layer."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
import toons
from pydantic import ValidationError

from pubmed_search.domain.entities.figure import ArticleFigure, ArticleFiguresResult
from pubmed_search.presentation.mcp_server.tools.article_source import PMCIDSource, PMIDSource


class TestGetArticleFiguresTool:
    """Tests for get_article_figures MCP tool."""

    @pytest.fixture
    def mock_result(self):
        """A successful ArticleFiguresResult."""
        return ArticleFiguresResult(
            pmcid="PMC12086443",
            pmid="40384072",
            article_title="Test Article",
            total_figures=2,
            figures=[
                ArticleFigure(
                    figure_id="fig1",
                    label="Figure 1",
                    caption_title="Overview",
                    caption_text="Main results.",
                    image_url="https://europepmc.org/articles/PMC12086443/bin/fig1.jpg",
                    graphic_href="fig1",
                    mentioned_in_sections=["Results"],
                ),
                ArticleFigure(
                    figure_id="fig2",
                    label="Figure 2",
                    caption_text="Secondary data.",
                    image_url="https://europepmc.org/articles/PMC12086443/bin/fig2.jpg",
                    graphic_href="fig2",
                ),
            ],
            pdf_links=[
                {
                    "source": "PubMed Central",
                    "url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12086443/pdf/",
                    "type": "pdf",
                },
            ],
            source="europepmc",
        )

    @pytest.fixture
    def mock_error_result(self):
        """An error ArticleFiguresResult."""
        return ArticleFiguresResult(
            pmcid="PMC999",
            error="token=secret https://user:pass@example.test/private/path",
            error_detail="/srv/private/figure-cache",
        )

    async def _call_tool(self, **kwargs):
        """Helper: import and call the tool function directly."""
        # Register tools on a mock MCP server, then call inner function
        from unittest.mock import MagicMock

        mcp = MagicMock()
        tools_registered = {}

        def capture_tool():
            def decorator(fn):
                tools_registered[fn.__name__] = fn
                return fn

            return decorator

        mcp.tool = capture_tool
        from pubmed_search.presentation.mcp_server.tools.figure_tools import (
            register_figure_tools,
        )

        register_figure_tools(mcp)
        fn = tools_registered["get_article_figures"]
        return await fn(**kwargs)

    @patch("pubmed_search.infrastructure.sources.figure_client.get_figure_client")
    async def test_with_pmcid(self, mock_get_client, mock_result):
        """Test direct PMCID input."""
        mock_client = AsyncMock()
        mock_client.get_article_figures.return_value = mock_result
        mock_get_client.return_value = mock_client

        output = await self._call_tool(source=PMCIDSource(kind="pmcid", value="PMC12086443"))

        assert "Figure 1" in output
        assert "Figure 2" in output
        assert "pdf" in output.lower()
        mock_client.get_article_figures.assert_called_once()

    @patch("pubmed_search.infrastructure.sources.figure_client.get_figure_client")
    async def test_explicit_pmcid_source(self, mock_get_client, mock_result):
        """Test the schema-exact PMCID source contract."""
        mock_client = AsyncMock()
        mock_client.get_article_figures.return_value = mock_result
        mock_get_client.return_value = mock_client

        output = await self._call_tool(source=PMCIDSource(kind="pmcid", value="PMC12086443"))

        assert "Figure 1" in output
        mock_client.get_article_figures.assert_called_once()

    @patch("pubmed_search.presentation.mcp_server.tools.figure_tools._resolve_pmid_to_pmcid")
    @patch("pubmed_search.infrastructure.sources.figure_client.get_figure_client")
    async def test_with_pmid_resolved(self, mock_get_client, mock_resolve, mock_result):
        """Test PMID input that resolves to PMCID."""
        mock_resolve.return_value = "PMC12086443"
        mock_client = AsyncMock()
        mock_client.get_article_figures.return_value = mock_result
        mock_get_client.return_value = mock_client

        output = await self._call_tool(
            source=PMIDSource(kind="pmid", value="40384072"),
            output_format="json",
        )
        parsed = json.loads(output)

        assert parsed["figure_count"] == 2
        assert parsed["identifiers"]["requested"] == {"kind": "pmid", "value": "40384072"}
        assert any(
            'get_fulltext(source={"kind":"pmid","value":"40384072"}' in command for command in parsed["next_commands"]
        )
        assert all("get_fulltext(pmid=" not in command for command in parsed["next_commands"])
        mock_resolve.assert_called_once()

    @patch("pubmed_search.presentation.mcp_server.tools.figure_tools._resolve_pmid_to_pmcid")
    async def test_with_pmid_not_in_pmc(self, mock_resolve):
        """Test PMID that has no PMC ID."""
        mock_resolve.return_value = None

        output = await self._call_tool(source=PMIDSource(kind="pmid", value="99999999"))

        assert "not available in PMC" in output or "error" in output.lower()

    @patch("pubmed_search.presentation.mcp_server.tools.figure_tools._resolve_pmid_to_pmcid")
    async def test_resolution_outage_is_not_reported_as_missing_article(self, mock_resolve):
        mock_resolve.side_effect = RuntimeError("token=super-secret")

        output = await self._call_tool(source=PMIDSource(kind="pmid", value="99999999"))

        assert "resolution source unavailable" in output
        assert "not available in PMC" not in output
        assert "super-secret" not in output

    async def test_source_is_required(self):
        """Compatibility-era optional identifier arguments are gone."""
        with pytest.raises(TypeError, match="source"):
            await self._call_tool()

    def test_source_models_reject_non_string_and_unprefixed_values(self):
        with pytest.raises(ValidationError):
            PMIDSource(kind="pmid", value=123)
        with pytest.raises(ValidationError):
            PMCIDSource(kind="pmcid", value="12086443")

    @patch("pubmed_search.infrastructure.sources.figure_client.get_figure_client")
    async def test_error_result(self, mock_get_client, mock_error_result):
        """Test formatting of error results."""
        mock_client = AsyncMock()
        mock_client.get_article_figures.return_value = mock_error_result
        mock_get_client.return_value = mock_client

        output = await self._call_tool(source=PMCIDSource(kind="pmcid", value="PMC999"))

        assert "error" in output.lower()
        assert "secret" not in output
        assert "example.test" not in output
        assert "/srv/private" not in output

    @patch("pubmed_search.presentation.mcp_server.tools.figure_tools._resolve_pmid_to_pmcid")
    @patch("pubmed_search.infrastructure.sources.figure_client.get_figure_client")
    async def test_explicit_pmid_source_is_resolved(self, mock_get_client, mock_resolve, mock_result):
        """The discriminator, rather than a numeric heuristic, selects PMID."""
        mock_resolve.return_value = "PMC12086443"
        mock_client = AsyncMock()
        mock_client.get_article_figures.return_value = mock_result
        mock_get_client.return_value = mock_client

        await self._call_tool(source=PMIDSource(kind="pmid", value="123456789"))

        mock_resolve.assert_awaited_once_with("123456789")
        mock_client.get_article_figures.assert_awaited_once()

    @patch("pubmed_search.infrastructure.sources.figure_client.get_figure_client")
    async def test_output_includes_pdf_links(self, mock_get_client, mock_result):
        """Test that PDF links are in the output."""
        mock_client = AsyncMock()
        mock_client.get_article_figures.return_value = mock_result
        mock_get_client.return_value = mock_client

        output = await self._call_tool(source=PMCIDSource(kind="pmcid", value="PMC12086443"))

        assert "PDF" in output or "pdf" in output
        assert "ncbi.nlm.nih.gov" in output

    @patch("pubmed_search.infrastructure.sources.figure_client.get_figure_client")
    async def test_output_includes_image_urls(self, mock_get_client, mock_result):
        """Test that image URLs appear in output."""
        mock_client = AsyncMock()
        mock_client.get_article_figures.return_value = mock_result
        mock_get_client.return_value = mock_client

        output = await self._call_tool(source=PMCIDSource(kind="pmcid", value="PMC12086443"))

        assert "europepmc.org" in output
        assert "fig1.jpg" in output

    @patch("pubmed_search.infrastructure.sources.figure_client.get_figure_client")
    async def test_json_contract(self, mock_get_client, mock_result):
        """Structured JSON output should expose figures, provenance, and next actions."""
        mock_client = AsyncMock()
        mock_client.get_article_figures.return_value = mock_result
        mock_get_client.return_value = mock_client

        output = await self._call_tool(source=PMCIDSource(kind="pmcid", value="PMC12086443"), output_format="json")
        parsed = json.loads(output)

        assert parsed["tool"] == "get_article_figures"
        assert parsed["figure_count"] == 2
        assert parsed["figures"][0]["label"] == "Figure 1"
        assert parsed["identifiers"]["requested"] == {"kind": "pmcid", "value": "PMC12086443"}
        assert parsed["next_tools"]
        assert any(
            'get_text_mined_terms(source={"kind":"pmcid","value":"PMC12086443"}' in command
            for command in parsed["next_commands"]
        )
        assert all("get_text_mined_terms(pmcid=" not in command for command in parsed["next_commands"])
        assert parsed["section_provenance"]["figures"]["canonical_host"] == "PubMed Central"

    @patch("pubmed_search.infrastructure.sources.figure_client.get_figure_client")
    async def test_toon_contract(self, mock_get_client, mock_result):
        """Structured TOON output should decode to the same figure payload model."""
        mock_client = AsyncMock()
        mock_client.get_article_figures.return_value = mock_result
        mock_get_client.return_value = mock_client

        output = await self._call_tool(source=PMCIDSource(kind="pmcid", value="PMC12086443"), output_format="toon")
        parsed = toons.loads(output)

        assert parsed["tool"] == "get_article_figures"
        assert parsed["figure_count"] == 2
        assert parsed["pdf_links"][0]["source"] == "PubMed Central"
        assert parsed["next_commands"]


class TestResolvePmidToPmcid:
    """Test the PMID→PMCID resolver."""

    async def test_resolve_success(self):
        from pubmed_search.presentation.mcp_server.tools.figure_tools import (
            _resolve_pmid_to_pmcid,
        )

        mock_client = AsyncMock()
        mock_client.search.return_value = {
            "results": [{"pmc_id": "PMC12086443"}],
        }
        with patch(
            "pubmed_search.infrastructure.sources.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await _resolve_pmid_to_pmcid("40384072")
            assert result == "PMC12086443"

    async def test_resolve_not_in_pmc(self):
        from pubmed_search.presentation.mcp_server.tools.figure_tools import (
            _resolve_pmid_to_pmcid,
        )

        mock_client = AsyncMock()
        mock_client.search.return_value = {"results": []}
        with patch(
            "pubmed_search.infrastructure.sources.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await _resolve_pmid_to_pmcid("99999")
            assert result is None

    async def test_resolve_error(self):
        from pubmed_search.presentation.mcp_server.tools.figure_tools import (
            _resolve_pmid_to_pmcid,
        )

        with patch(
            "pubmed_search.infrastructure.sources.get_europe_pmc_client",
            side_effect=Exception("Connection failed"),
        ):
            with pytest.raises(Exception, match="Connection failed"):
                await _resolve_pmid_to_pmcid("12345")


class TestFormatFiguresOutput:
    """Test the output formatter."""

    def test_format_with_figures(self):
        from pubmed_search.presentation.mcp_server.tools.figure_tools import (
            _format_figures_output,
        )

        result = ArticleFiguresResult(
            pmcid="PMC123",
            pmid="456",
            article_title="Test",
            total_figures=1,
            figures=[
                ArticleFigure(
                    figure_id="f1",
                    label="Figure 1",
                    caption_title="Title",
                    caption_text="Caption text here",
                    image_url="https://europepmc.org/articles/PMC123/bin/f1.jpg",
                    graphic_href="f1",
                    mentioned_in_sections=["Results"],
                ),
            ],
            pdf_links=[{"source": "PMC", "url": "https://example.com/pdf", "type": "pdf"}],
            source="europepmc",
        )

        output = _format_figures_output(result)

        assert "Figure 1" in output
        assert "Title" in output
        assert "Caption text here" in output
        assert "pdf" in output.lower() or "PDF" in output
        assert "Results" in output

    def test_format_empty_figures(self):
        from pubmed_search.presentation.mcp_server.tools.figure_tools import (
            _format_figures_output,
        )

        result = ArticleFiguresResult(pmcid="PMC123", source="europepmc")
        output = _format_figures_output(result)
        assert "No figures" in output

    def test_format_with_subfigures(self):
        from pubmed_search.presentation.mcp_server.tools.figure_tools import (
            _format_figures_output,
        )

        sub = ArticleFigure(
            figure_id="f1a",
            label="(A)",
            caption_text="Subfigure A showing detailed view of the results.",
            image_url="https://europepmc.org/articles/PMC123/bin/f1a.jpg",
        )
        fig = ArticleFigure(
            figure_id="f1",
            label="Figure 1",
            caption_text="Multi-part",
            subfigures=[sub],
        )
        result = ArticleFiguresResult(
            pmcid="PMC123",
            total_figures=1,
            figures=[fig],
            source="europepmc",
        )

        output = _format_figures_output(result)
        assert "Sub-figures" in output or "(A)" in output

    def test_format_neutralizes_markdown_and_active_urls(self):
        from pubmed_search.presentation.mcp_server.tools.figure_tools import (
            _format_figures_output,
        )

        result = ArticleFiguresResult(
            pmcid="PMC123",
            article_title="Title\n# injected",
            total_figures=1,
            figures=[
                ArticleFigure(
                    figure_id="f1",
                    label="[click](https://attacker.invalid)",
                    caption_text="caption\n```mermaid\ngraph TD",
                    image_url="javascript:alert(1)",
                    graphic_href="`break`",
                )
            ],
            pdf_links=[{"source": "bad\n# heading", "url": "javascript:alert(1)", "type": "pdf"}],
            source="external",
        )

        output = _format_figures_output(result)

        assert "\n# injected" not in output
        assert "\n```mermaid" not in output
        assert "javascript:" not in output
        assert "unsafe URL omitted" in output
        assert "\\[click\\]\\(https://attacker.invalid\\)" in output
