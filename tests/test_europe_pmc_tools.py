"""Tests for Europe PMC MCP tools — get_fulltext, get_text_mined_terms, helpers."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import toons

from pubmed_search.application.session.manager import SessionManager
from pubmed_search.infrastructure.sources.fulltext_download import (
    FulltextResult,
    PDFLink,
    PDFSource,
)
from pubmed_search.presentation.mcp_server.tools._common import set_session_manager
from pubmed_search.presentation.mcp_server.tools.europe_pmc import (
    register_europe_pmc_tools,
)


def _capture_tools(mcp):
    tools = {}
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
    register_europe_pmc_tools(mcp)
    return tools


@pytest.fixture
def tools():
    return _capture_tools(MagicMock())


# ============================================================
# get_fulltext
# ============================================================


class TestGetFulltext:
    @pytest.mark.asyncio
    async def test_no_identifier(self, tools):
        result = await tools["get_fulltext"]()
        assert "error" in result.lower() or "no valid" in result.lower()

    @pytest.mark.asyncio
    async def test_pmcid_success(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "Test Article",
                "sections": [{"title": "Introduction", "content": "Hello world"}],
                "abstract": "An abstract",
            }
        )
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_fulltext"](pmcid="PMC7096777")
        assert "Test Article" in result
        assert "Introduction" in result

    @pytest.mark.asyncio
    async def test_pmcid_no_xml(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = None
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_fulltext"](pmcid="PMC9999999")
        # Should still succeed if unpaywall / core have nothing either
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_doi_unpaywall_success(self, tools):
        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = {
            "is_oa": True,
            "title": "OA Paper",
            "oa_status": "gold",
            "best_oa_location": {
                "url_for_pdf": "https://example.com/paper.pdf",
                "host_type": "publisher",
                "version": "publishedVersion",
                "license": "cc-by",
            },
            "oa_locations": [],
        }
        mock_core = AsyncMock()
        mock_core.search.return_value = {"results": []}
        mock_downloader = AsyncMock()
        mock_downloader.get_fulltext.return_value = FulltextResult(
            doi="10.1234/test",
            pdf_links=[],
            text_content=None,
            error="No PDF links found for this article",
        )
        mock_downloader.close = AsyncMock()

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
                return_value=mock_unpaywall,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
                return_value=mock_core,
            ),
            patch(
                "pubmed_search.infrastructure.sources.fulltext_download.FulltextDownloader",
                return_value=mock_downloader,
            ),
        ):
            result = await tools["get_fulltext"](doi="10.1234/test")
        assert "example.com/paper.pdf" in result

    @pytest.mark.asyncio
    async def test_doi_core_fallback(self, tools):
        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = {"is_oa": False}

        mock_core = AsyncMock()
        mock_core.search.return_value = {
            "results": [
                {
                    "title": "CORE Paper",
                    "fullText": "Full text content here",
                    "downloadUrl": "https://core.ac.uk/download/pdf/123.pdf",
                }
            ]
        }
        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
                return_value=mock_unpaywall,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
                return_value=mock_core,
            ),
        ):
            result = await tools["get_fulltext"](doi="10.1234/test")
        assert "Full text content" in result or "core.ac.uk" in result

    @pytest.mark.asyncio
    async def test_pmid_identifier_auto_detect(self, tools):
        """Test auto-detection of PMID from identifier string."""
        result = await tools["get_fulltext"](identifier="12345678")
        # Should detect as PMID, result will depend on API but shouldn't crash
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_doi_identifier_auto_detect(self, tools):
        """Test auto-detection of DOI from identifier string."""
        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = {"is_oa": False}
        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
                return_value=mock_unpaywall,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
                return_value=MagicMock(search=AsyncMock(return_value={"results": []})),
            ),
        ):
            result = await tools["get_fulltext"](identifier="10.1038/s41586-021-03819-2")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_pmc_identifier_auto_detect(self, tools):
        """Test auto-detection of PMC ID from identifier string."""
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = None
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_fulltext"](identifier="PMC7096777")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_sections_filter(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "Filtered",
                "sections": [
                    {"title": "Introduction", "content": "Intro text"},
                    {"title": "Methods", "content": "Methods text"},
                    {"title": "Results", "content": "Results text"},
                ],
            }
        )
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_fulltext"](pmcid="PMC7096777", sections="introduction,results")
        assert "Intro text" in result or "Results text" in result

    @pytest.mark.asyncio
    async def test_europe_pmc_exception(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.side_effect = RuntimeError("API down")
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            # Should not crash, just log and continue to other sources
            result = await tools["get_fulltext"](pmcid="PMC7096777")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_no_results_at_all(self, tools):
        """When all sources fail, should return no results message."""
        result = await tools["get_fulltext"](pmid="99999999")
        assert "no" in result.lower() or "not" in result.lower()

    @pytest.mark.asyncio
    async def test_unpaywall_landing_page(self, tools):
        """Test unpaywall returning a landing page URL instead of PDF."""
        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = {
            "is_oa": True,
            "oa_status": "green",
            "best_oa_location": {
                "url": "https://example.com/article",
                "host_type": "repository",
            },
            "oa_locations": [],
        }
        mock_core = AsyncMock()
        mock_core.search.return_value = {"results": []}
        mock_downloader = AsyncMock()
        mock_downloader.get_fulltext.return_value = FulltextResult(
            doi="10.1234/test",
            pdf_links=[],
            text_content=None,
            error="No PDF links found for this article",
        )
        mock_downloader.close = AsyncMock()

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
                return_value=mock_unpaywall,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
                return_value=mock_core,
            ),
            patch(
                "pubmed_search.infrastructure.sources.fulltext_download.FulltextDownloader",
                return_value=mock_downloader,
            ),
        ):
            result = await tools["get_fulltext"](doi="10.1234/test")
        assert "example.com/article" in result

    @pytest.mark.asyncio
    async def test_reports_progress_and_logs(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "Test Article",
                "sections": [{"title": "Introduction", "content": "Hello world"}],
            }
        )
        ctx = AsyncMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_fulltext"](pmcid="PMC7096777", ctx=ctx)
        assert "Test Article" in result
        assert ctx.report_progress.await_count >= 3
        assert ctx.log.await_count >= 1

    @pytest.mark.asyncio
    async def test_hanging_progress_callbacks_do_not_block(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "Test Article",
                "sections": [{"title": "Introduction", "content": "Hello world"}],
            }
        )

        async def _hang(*args, **kwargs):
            await asyncio.Event().wait()

        ctx = MagicMock()
        ctx.report_progress = AsyncMock(side_effect=_hang)
        ctx.log = AsyncMock(side_effect=_hang)

        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await asyncio.wait_for(tools["get_fulltext"](pmcid="PMC7096777", ctx=ctx), timeout=1.0)

        assert "Test Article" in result

    @pytest.mark.asyncio
    async def test_progress_callbacks_that_ignore_cancellation_do_not_block(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "Test Article",
                "sections": [{"title": "Introduction", "content": "Hello world"}],
            }
        )

        async def _ignore_cancel(*args, **kwargs):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await asyncio.sleep(0.2)

        ctx = MagicMock()
        ctx.report_progress = AsyncMock(side_effect=_ignore_cancel)
        ctx.log = AsyncMock(side_effect=_ignore_cancel)

        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            started = time.monotonic()
            result = await asyncio.wait_for(tools["get_fulltext"](pmcid="PMC7096777", ctx=ctx), timeout=1.0)

        assert time.monotonic() - started < 0.2
        assert "Test Article" in result
        await asyncio.sleep(0.25)

    @pytest.mark.asyncio
    async def test_json_contract(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "Structured Article",
                "sections": [{"title": "Introduction", "content": "Hello world"}],
            }
        )
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_fulltext"](pmcid="PMC7096777", output_format="json")

        parsed = json.loads(result)
        assert parsed["tool"] == "get_fulltext"
        assert parsed["fulltext_available"] is True
        assert parsed["content_sections"][0]["title"] == "Introduction"
        assert parsed["source_counts"]
        assert parsed["next_tools"]
        assert parsed["next_commands"]
        assert parsed["section_provenance"]["content"]["surfacing_source"] == "Europe PMC"

    @pytest.mark.asyncio
    async def test_json_contract_persists_artifact(self, tools, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        set_session_manager(manager)
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "Persistent Fulltext",
                "sections": [{"title": "Introduction", "content": "Stored body"}],
            }
        )

        try:
            with patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
                return_value=mock_client,
            ):
                result = await tools["get_fulltext"](pmcid="PMC7096777", output_format="json")
        finally:
            set_session_manager(None)

        parsed = json.loads(result)
        artifact = parsed["artifact"]
        assert artifact["tool"] == "get_fulltext"
        assert "local_path" not in artifact
        stored_artifact = manager.list_artifacts(tool="get_fulltext")[0]
        stored = json.loads(Path(stored_artifact["local_path"]).read_text(encoding="utf-8"))
        assert stored["title"] == "Persistent Fulltext"

    @pytest.mark.asyncio
    async def test_json_contract_can_include_local_artifact_paths_for_local_workflows(
        self, tools, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS", "true")
        manager = SessionManager(data_dir=str(tmp_path))
        set_session_manager(manager)
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "Local Artifact Paths",
                "sections": [{"title": "Introduction", "content": "Stored body"}],
            }
        )

        try:
            with patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
                return_value=mock_client,
            ):
                result = await tools["get_fulltext"](pmcid="PMC7096777", output_format="json")
        finally:
            set_session_manager(None)

        parsed = json.loads(result)
        artifact = parsed["artifact"]
        assert Path(artifact["local_path"]).is_file()
        assert Path(artifact["manifest_path"]).is_file()

    @pytest.mark.asyncio
    async def test_pmid_json_resolves_doi_for_unpaywall_pdf(self, tools):
        mock_client = AsyncMock()
        mock_client.get_article.return_value = {
            "pmid": "41817525",
            "doi": "10.1001/jamanetworkopen.2026.1515",
        }

        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = {
            "is_oa": True,
            "title": "JAMA OA Paper",
            "oa_status": "gold",
            "best_oa_location": {
                "url_for_pdf": "https://jamanetwork.com/articlepdf/example.pdf",
                "host_type": "publisher",
                "version": "publishedVersion",
            },
            "oa_locations": [],
        }
        mock_downloader = AsyncMock()
        mock_downloader.get_fulltext.return_value = FulltextResult(
            doi="10.1001/jamanetworkopen.2026.1515",
            pdf_links=[],
            text_content=None,
            error="No extra PDF links found",
        )
        mock_downloader.close = AsyncMock()

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
                return_value=mock_client,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
                return_value=mock_unpaywall,
            ),
            patch(
                "pubmed_search.infrastructure.sources.fulltext_download.FulltextDownloader",
                return_value=mock_downloader,
            ),
        ):
            result = await tools["get_fulltext"](pmid="41817525", output_format="json")

        parsed = json.loads(result)
        assert parsed["identifiers"]["pmid"] == "41817525"
        assert parsed["identifiers"]["doi"] == "10.1001/jamanetworkopen.2026.1515"
        assert parsed["pdf_links"][0]["url"] == "https://jamanetwork.com/articlepdf/example.pdf"

    @pytest.mark.asyncio
    async def test_extended_sources_extracts_institutional_pdf_text(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = None

        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = {"is_oa": False}

        mock_core = AsyncMock()
        mock_core.search.return_value = {"results": []}

        mock_downloader = MagicMock()
        mock_downloader.get_fulltext = AsyncMock(
            return_value=FulltextResult(
                text_content="Institutional PDF text",
                pdf_links=[
                    PDFLink(
                        url="https://resolver.example.edu/openurl?id=1",
                        source=PDFSource.INSTITUTIONAL_RESOLVER,
                        access_type="subscription",
                        is_direct_pdf=False,
                    ),
                    PDFLink(
                        url="https://publisher.example.edu/paper.pdf",
                        source=PDFSource.INSTITUTIONAL_RESOLVER,
                        access_type="subscription",
                        is_direct_pdf=True,
                    ),
                ],
                source_used=PDFSource.INSTITUTIONAL_RESOLVER,
                content_type="pdf",
            )
        )
        mock_downloader.close = AsyncMock()

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
                return_value=mock_client,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
                return_value=mock_unpaywall,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
                return_value=mock_core,
            ),
            patch(
                "pubmed_search.infrastructure.sources.fulltext_download.FulltextDownloader",
                return_value=mock_downloader,
            ),
        ):
            result = await tools["get_fulltext"](doi="10.1234/test", extended_sources=True)

        mock_downloader.get_fulltext.assert_awaited_once_with(
            pmid=None,
            pmcid=None,
            doi="10.1234/test",
            strategy="extract_text",
            allow_browser_session=None,
        )
        assert "Institutional PDF text" in result
        assert "publisher.example.edu/paper.pdf" in result
        assert "Institutional" in result

    @pytest.mark.asyncio
    async def test_extended_sources_do_not_run_downloader_twice(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = None

        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = {"is_oa": False}

        mock_core = AsyncMock()
        mock_core.search.return_value = {"results": []}

        mock_downloader = MagicMock()
        mock_downloader.get_fulltext = AsyncMock(
            return_value=FulltextResult(
                text_content=None,
                pdf_links=[
                    PDFLink(
                        url="https://publisher.example.edu/paper.pdf",
                        source=PDFSource.INSTITUTIONAL_RESOLVER,
                        access_type="subscription",
                        is_direct_pdf=True,
                    )
                ],
                source_used=PDFSource.INSTITUTIONAL_RESOLVER,
            )
        )
        mock_downloader.close = AsyncMock()

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
                return_value=mock_client,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
                return_value=mock_unpaywall,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
                return_value=mock_core,
            ),
            patch(
                "pubmed_search.infrastructure.sources.fulltext_download.FulltextDownloader",
                return_value=mock_downloader,
            ),
        ):
            result = await tools["get_fulltext"](
                doi="10.1234/test",
                extended_sources=True,
                allow_browser_session=True,
            )

        assert "publisher.example.edu/paper.pdf" in result
        mock_downloader.get_fulltext.assert_awaited_once_with(
            pmid=None,
            pmcid=None,
            doi="10.1234/test",
            strategy="extract_text",
            allow_browser_session=True,
        )

    @pytest.mark.asyncio
    async def test_browser_session_assisted_fetch(self, tools):
        mock_fulltext = FulltextResult(
            doi="10.1234/test",
            text_content="Institutional PDF extracted text",
            source_used=PDFSource.BROWSER_SESSION,
            retrieved_url="https://publisher.example/download.pdf",
            pdf_links=[
                PDFLink(
                    url="https://resolver.library.edu/openurl?doi=10.1234/test",
                    source=PDFSource.OPENURL,
                    access_type="institutional",
                    is_direct_pdf=False,
                )
            ],
        )
        mock_downloader = AsyncMock()
        mock_downloader.get_fulltext.return_value = mock_fulltext
        mock_downloader.close = AsyncMock()
        mock_fetcher = MagicMock()
        mock_fetcher.is_enabled.return_value = True
        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = None
        mock_core = AsyncMock()
        mock_core.search.return_value = {"results": []}

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
                return_value=mock_unpaywall,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
                return_value=mock_core,
            ),
            patch(
                "pubmed_search.infrastructure.sources.fulltext_download.FulltextDownloader",
                return_value=mock_downloader,
            ),
            patch(
                "pubmed_search.infrastructure.sources.browser_session.get_browser_session_fetcher",
                return_value=mock_fetcher,
            ),
        ):
            result = await tools["get_fulltext"](doi="10.1234/test", allow_browser_session=True)

        assert "Browser-session broker fetched PDF" in result
        assert "Institutional PDF extracted text" in result

    @pytest.mark.asyncio
    async def test_browser_session_assisted_fetch_auto_mode(self, tools):
        mock_fulltext = FulltextResult(
            doi="10.1234/test",
            text_content="Institutional PDF extracted text",
            source_used=PDFSource.BROWSER_SESSION,
            retrieved_url="https://publisher.example/download.pdf",
            pdf_links=[
                PDFLink(
                    url="https://resolver.library.edu/openurl?doi=10.1234/test",
                    source=PDFSource.OPENURL,
                    access_type="institutional",
                    is_direct_pdf=False,
                )
            ],
        )
        mock_downloader = AsyncMock()
        mock_downloader.get_fulltext.return_value = mock_fulltext
        mock_downloader.close = AsyncMock()
        mock_fetcher = MagicMock()
        mock_fetcher.is_auto_enabled.return_value = True
        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = None
        mock_core = AsyncMock()
        mock_core.search.return_value = {"results": []}

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
                return_value=mock_unpaywall,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
                return_value=mock_core,
            ),
            patch(
                "pubmed_search.infrastructure.sources.fulltext_download.FulltextDownloader",
                return_value=mock_downloader,
            ),
            patch(
                "pubmed_search.infrastructure.sources.browser_session.get_browser_session_fetcher",
                return_value=mock_fetcher,
            ),
        ):
            result = await tools["get_fulltext"](doi="10.1234/test")

        assert "Browser-session broker fetched PDF" in result
        assert "Institutional PDF extracted text" in result
        mock_downloader.get_fulltext.assert_awaited_once()
        assert mock_downloader.get_fulltext.await_args.kwargs["allow_browser_session"] is None

    @pytest.mark.asyncio
    async def test_pdf_retrieval_fallback_runs_without_browser_session(self, tools):
        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = None
        mock_core = AsyncMock()
        mock_core.search.return_value = {"results": []}
        mock_downloader = AsyncMock()
        mock_downloader.get_fulltext.return_value = FulltextResult(
            doi="10.1234/test",
            text_content="Recovered from publisher PDF",
            source_used=PDFSource.CROSSREF,
            retrieved_url="https://publisher.example/paper.pdf",
            pdf_links=[
                PDFLink(
                    url="https://publisher.example/paper.pdf",
                    source=PDFSource.CROSSREF,
                )
            ],
        )
        mock_downloader.close = AsyncMock()
        mock_fetcher = MagicMock()
        mock_fetcher.is_auto_enabled.return_value = False

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
                return_value=mock_unpaywall,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
                return_value=mock_core,
            ),
            patch(
                "pubmed_search.infrastructure.sources.fulltext_download.FulltextDownloader",
                return_value=mock_downloader,
            ),
            patch(
                "pubmed_search.infrastructure.sources.browser_session.get_browser_session_fetcher",
                return_value=mock_fetcher,
            ),
        ):
            result = await tools["get_fulltext"](doi="10.1234/test")

        assert "Recovered from publisher PDF" in result
        assert "PDF retrieval fallback extracted text via CrossRef" in result
        mock_downloader.get_fulltext.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pdf_retrieval_fallback_persists_raw_text_sidecar(self, tools, tmp_path):
        raw_text = "Recovered from publisher PDF " * 700
        manager = SessionManager(data_dir=str(tmp_path))
        set_session_manager(manager)
        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = None
        mock_core = AsyncMock()
        mock_core.search.return_value = {"results": []}
        mock_downloader = AsyncMock()
        mock_downloader.get_fulltext.return_value = FulltextResult(
            doi="10.1234/test",
            text_content=raw_text,
            source_used=PDFSource.CROSSREF,
            retrieved_url="https://publisher.example/paper.pdf",
            pdf_links=[PDFLink(url="https://publisher.example/paper.pdf", source=PDFSource.CROSSREF)],
        )
        mock_downloader.close = AsyncMock()

        try:
            with (
                patch(
                    "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
                    return_value=mock_unpaywall,
                ),
                patch(
                    "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
                    return_value=mock_core,
                ),
                patch(
                    "pubmed_search.infrastructure.sources.fulltext_download.FulltextDownloader",
                    return_value=mock_downloader,
                ),
            ):
                result = await tools["get_fulltext"](doi="10.1234/test")
        finally:
            set_session_manager(None)

        assert "characters truncated" in result
        artifact = manager.list_artifacts(tool="get_fulltext")[0]
        raw = manager.read_artifact(artifact["artifact_id"], file_name="raw_content.txt", max_chars=0)
        assert raw["content"] == raw_text

    @pytest.mark.asyncio
    async def test_large_json_fulltext_response_uses_artifact_preview(self, tools, tmp_path, monkeypatch):
        monkeypatch.setenv("PUBMED_FULLTEXT_INLINE_MAX_CHARS", "500")
        manager = SessionManager(data_dir=str(tmp_path))
        set_session_manager(manager)
        long_content = "Long section body " * 300
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "Large Fulltext",
                "sections": [{"title": "Introduction", "content": long_content}],
            }
        )

        try:
            with patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
                return_value=mock_client,
            ):
                result = await tools["get_fulltext"](pmcid="PMC7096777", output_format="json")
        finally:
            set_session_manager(None)

        parsed = json.loads(result)
        assert parsed["artifact"]["artifact_id"]
        assert "omitted from inline response" in parsed["content"]
        assert len(parsed["content"]) < len(long_content)
        stored = manager.read_artifact(parsed["artifact"]["artifact_id"], max_chars=0)
        assert long_content[:1000] in stored["content"]

    @pytest.mark.asyncio
    async def test_large_markdown_fulltext_response_uses_artifact_preview(self, tools, tmp_path, monkeypatch):
        monkeypatch.setenv("PUBMED_FULLTEXT_INLINE_MAX_CHARS", "500")
        manager = SessionManager(data_dir=str(tmp_path))
        set_session_manager(manager)
        long_content = "Long markdown body " * 300
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "Large Markdown Fulltext",
                "sections": [{"title": "Introduction", "content": long_content}],
            }
        )

        try:
            with patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
                return_value=mock_client,
            ):
                result = await tools["get_fulltext"](pmcid="PMC7096777")
        finally:
            set_session_manager(None)

        assert "omitted from inline response" in result
        assert "Persistent Artifact" in result
        artifact = manager.list_artifacts(tool="get_fulltext")[0]
        stored = manager.read_artifact(artifact["artifact_id"], max_chars=0)
        assert long_content[:1000] in stored["content"]

    @pytest.mark.asyncio
    async def test_markdown_artifact_default_read_contains_untruncated_section_payload(self, tools, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        set_session_manager(manager)
        tail_sentinel = "TAIL_SENTINEL_UNTRUNCATED"
        long_content = ("A" * 5200) + tail_sentinel
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "Untruncated Artifact",
                "sections": [{"title": "Results", "content": long_content}],
            }
        )

        try:
            with patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
                return_value=mock_client,
            ):
                result = await tools["get_fulltext"](pmcid="PMC7096777")
        finally:
            set_session_manager(None)

        assert tail_sentinel not in result
        artifact = manager.list_artifacts(tool="get_fulltext")[0]
        stored = manager.read_artifact(artifact["artifact_id"], max_chars=0)
        assert stored["file"]["name"] == "payload.json"
        assert tail_sentinel in stored["content"]

    @pytest.mark.asyncio
    async def test_markdown_artifact_format_failure_does_not_hide_fulltext(self, tools, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        set_session_manager(manager)
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "Artifact Failure Article",
                "sections": [{"title": "Introduction", "content": "Still visible"}],
            }
        )

        try:
            with (
                patch(
                    "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
                    return_value=mock_client,
                ),
                patch(
                    "pubmed_search.presentation.mcp_server.tools.europe_pmc._format_get_fulltext_json",
                    side_effect=TypeError("artifact formatter failed"),
                ),
            ):
                result = await tools["get_fulltext"](pmcid="PMC7096777")
        finally:
            set_session_manager(None)

        assert "Artifact Failure Article" in result
        assert "Still visible" in result

    @pytest.mark.asyncio
    async def test_pdf_retrieval_fallback_reports_pdf_without_text(self, tools):
        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = None
        mock_core = AsyncMock()
        mock_core.search.return_value = {"results": []}
        mock_downloader = AsyncMock()
        mock_downloader.get_fulltext.return_value = FulltextResult(
            doi="10.1234/test",
            text_content=None,
            source_used=PDFSource.CROSSREF,
            retrieved_url="https://publisher.example/paper.pdf",
            error="PDF downloaded successfully, but text extraction failed across all candidate sources",
            pdf_links=[
                PDFLink(
                    url="https://publisher.example/paper.pdf",
                    source=PDFSource.CROSSREF,
                )
            ],
        )
        mock_downloader.close = AsyncMock()

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
                return_value=mock_unpaywall,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
                return_value=mock_core,
            ),
            patch(
                "pubmed_search.infrastructure.sources.fulltext_download.FulltextDownloader",
                return_value=mock_downloader,
            ),
        ):
            result = await tools["get_fulltext"](doi="10.1234/test")

        assert "retrieved PDF via CrossRef" in result
        assert "extracted text via CrossRef" not in result

    @pytest.mark.asyncio
    async def test_toon_contract(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "Structured Article",
                "sections": [{"title": "Introduction", "content": "Hello world"}],
            }
        )
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_fulltext"](pmcid="PMC7096777", output_format="toon")

        parsed = toons.loads(result)
        assert parsed["tool"] == "get_fulltext"
        assert parsed["fulltext_available"] is True
        assert parsed["content_sections"][0]["title"] == "Introduction"
        assert parsed["section_provenance"]["content"]["canonical_host"] == "PubMed Central"


# ============================================================
# get_text_mined_terms
# ============================================================


class TestGetTextMinedTerms:
    @pytest.mark.asyncio
    async def test_no_ids(self, tools):
        result = await tools["get_text_mined_terms"]()
        assert "error" in result.lower() or "required" in result.lower()

    @pytest.mark.asyncio
    async def test_pmid_success(self, tools):
        mock_client = AsyncMock()
        mock_client.get_text_mined_terms.return_value = [
            {"semantic_type": "GENE_PROTEIN", "term": "BRCA1"},
            {"semantic_type": "GENE_PROTEIN", "term": "BRCA1"},
            {"semantic_type": "DISEASE", "term": "Breast Cancer"},
            {"semantic_type": "CHEMICAL", "term": "Tamoxifen"},
        ]
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_text_mined_terms"](pmid="12345678")
        assert "BRCA1" in result
        assert "Breast Cancer" in result
        assert "×2" in result  # BRCA1 appears twice

    @pytest.mark.asyncio
    async def test_pmcid_success(self, tools):
        mock_client = AsyncMock()
        mock_client.get_text_mined_terms.return_value = [
            {"semantic_type": "ORGANISM", "term": "Homo sapiens"},
        ]
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_text_mined_terms"](pmcid="PMC7096777")
        assert "Homo sapiens" in result

    @pytest.mark.asyncio
    async def test_semantic_type_filter(self, tools):
        mock_client = AsyncMock()
        mock_client.get_text_mined_terms.return_value = [
            {"semantic_type": "CHEMICAL", "term": "Propofol"},
        ]
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_text_mined_terms"](pmid="12345678", semantic_type="CHEMICAL")
        assert "Propofol" in result

    @pytest.mark.asyncio
    async def test_no_terms_found(self, tools):
        mock_client = AsyncMock()
        mock_client.get_text_mined_terms.return_value = []
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_text_mined_terms"](pmid="12345678")
        assert "no" in result.lower()

    @pytest.mark.asyncio
    async def test_exception(self, tools):
        mock_client = AsyncMock()
        mock_client.get_text_mined_terms.side_effect = RuntimeError("API error")
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_text_mined_terms"](pmid="12345678")
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_reports_progress(self, tools):
        mock_client = AsyncMock()
        mock_client.get_text_mined_terms.return_value = [
            {"semantic_type": "GENE_PROTEIN", "term": "BRCA1"},
        ]
        ctx = AsyncMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_text_mined_terms"](pmid="12345678", ctx=ctx)
        assert "BRCA1" in result
        assert ctx.report_progress.await_count >= 2

    @pytest.mark.asyncio
    async def test_json_contract(self, tools):
        mock_client = AsyncMock()
        mock_client.get_text_mined_terms.return_value = [
            {"semantic_type": "GENE_PROTEIN", "term": "BRCA1"},
            {"semantic_type": "GENE_PROTEIN", "term": "BRCA1"},
            {"semantic_type": "DISEASE", "term": "Breast Cancer"},
        ]
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_text_mined_terms"](pmid="12345678", output_format="json")

        parsed = json.loads(result)
        assert parsed["tool"] == "get_text_mined_terms"
        assert parsed["annotation_count"] == 3
        assert any(group["semantic_type"] == "GENE_PROTEIN" for group in parsed["term_groups"])
        assert parsed["next_tools"]
        assert parsed["section_provenance"]["annotations"]["surfacing_source"] == "Europe PMC"

    @pytest.mark.asyncio
    async def test_toon_contract(self, tools):
        mock_client = AsyncMock()
        mock_client.get_text_mined_terms.return_value = [
            {"semantic_type": "CHEMICAL", "term": "Propofol"},
        ]
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_text_mined_terms"](pmid="12345678", output_format="toon")

        parsed = toons.loads(result)
        assert parsed["tool"] == "get_text_mined_terms"
        assert parsed["annotation_count"] == 1
        assert parsed["term_groups"][0]["terms"][0]["term"] == "Propofol"
