"""Tests for FigureClient - multi-source figure extraction."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pubmed_search.domain.entities.figure import ArticleFigure, ArticleFiguresResult
from pubmed_search.infrastructure.sources.figure_client import (
    ALLOWED_IMAGE_DOMAINS,
    FigureClient,
    _normalize_pmcid,
    validate_image_url,
)

# =========================================================================
# Sample fixtures
# =========================================================================

SAMPLE_JATS_XML = """\
<article>
  <front>
    <article-meta>
      <title-group>
        <article-title>Test Article With Figures</article-title>
      </title-group>
    </article-meta>
  </front>
  <body>
    <sec>
      <title>Introduction</title>
      <p>As shown in Figure 1, the results suggest...</p>
    </sec>
    <sec>
      <title>Results</title>
      <p>Figure 1 demonstrates the main finding. Figure 2 shows additional data.</p>
      <fig id="fig1">
        <label>Figure 1</label>
        <caption>
          <title>Main Findings</title>
          <p>This figure shows the primary results.</p>
        </caption>
        <graphic xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="article-fig1"/>
      </fig>
      <fig id="fig2">
        <label>Figure 2</label>
        <caption>
          <p>Secondary data analysis.</p>
        </caption>
        <graphic xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="article-fig2"/>
      </fig>
    </sec>
  </body>
</article>
"""

SAMPLE_JATS_XML_WITH_FIG_GROUP = """\
<article>
  <front>
    <article-meta>
      <title-group>
        <article-title>Article with Fig Group</article-title>
      </title-group>
    </article-meta>
  </front>
  <body>
    <sec>
      <title>Results</title>
      <fig-group id="fg1">
        <label>Figure 3</label>
        <caption><p>Multi-part figure</p></caption>
        <graphic xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="article-fg1"/>
        <fig id="fig3a">
          <label>Figure 3A</label>
          <caption><p>Part A</p></caption>
          <graphic xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="article-fig3a"/>
        </fig>
        <fig id="fig3b">
          <label>Figure 3B</label>
          <caption><p>Part B</p></caption>
          <graphic xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="article-fig3b"/>
        </fig>
      </fig-group>
    </sec>
  </body>
</article>
"""

SAMPLE_JATS_XML_WITH_TABLE = """\
<article>
  <front>
    <article-meta>
      <title-group><article-title>Table Article</article-title></title-group>
    </article-meta>
  </front>
  <body>
    <sec>
      <title>Results</title>
      <table-wrap id="tbl1">
        <label>Table 1</label>
        <caption><p>Summary statistics</p></caption>
        <graphic xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="table1-img"/>
      </table-wrap>
    </sec>
  </body>
</article>
"""

SAMPLE_BIOC_JSON = {
    "documents": [
        {
            "passages": [
                {
                    "infons": {"type": "fig_title_caption", "id": "fig_1"},
                    "text": "Figure 1. Main results of the study showing trends.",
                },
                {
                    "infons": {"section_type": "FIG", "id": "fig_2"},
                    "text": "Figure 2 Additional analysis panel.",
                },
                {
                    "infons": {"type": "paragraph"},
                    "text": "This is a regular paragraph, not a figure.",
                },
            ]
        }
    ]
}


# =========================================================================
# Test classes
# =========================================================================


class TestValidateImageUrl:
    """Tests for SSRF protection URL validation."""

    def test_valid_europepmc_url(self):
        assert validate_image_url("https://europepmc.org/articles/PMC123/bin/fig1.jpg")

    def test_valid_ncbi_cdn_url(self):
        assert validate_image_url("https://cdn.ncbi.nlm.nih.gov/pmc/blobs/xyz.jpg")

    def test_valid_pmc_url(self):
        assert validate_image_url("https://pmc.ncbi.nlm.nih.gov/articles/PMC123/")

    def test_reject_ftp_scheme(self):
        assert not validate_image_url("ftp://europepmc.org/fig.jpg")

    def test_reject_non_whitelisted_domain(self):
        assert not validate_image_url("https://evil.com/image.jpg")

    def test_reject_data_uri(self):
        assert not validate_image_url("data:image/png;base64,abc")

    def test_reject_empty_string(self):
        assert not validate_image_url("")

    def test_reject_malformed_url(self):
        assert not validate_image_url("not-a-url")

    def test_all_allowed_domains(self):
        for domain in ALLOWED_IMAGE_DOMAINS:
            assert validate_image_url(f"https://{domain}/test.jpg")


class TestNormalizePmcid:
    """Tests for PMCID normalization."""

    def test_already_prefixed(self):
        assert _normalize_pmcid("PMC12345") == "PMC12345"

    def test_numeric_only(self):
        assert _normalize_pmcid("12345") == "PMC12345"

    def test_lowercase_prefix(self):
        assert _normalize_pmcid("pmc12345") == "PMC12345"

    def test_strip_whitespace(self):
        assert _normalize_pmcid("  PMC12345  ") == "PMC12345"


class TestFigureClient:
    """Tests for FigureClient infrastructure layer."""

    @pytest.fixture
    def client(self):
        return FigureClient(timeout=10.0)

    # ----- JATS XML Parsing -----

    def test_parse_jats_figures_basic(self, client):
        figures, title = client._parse_jats_figures(SAMPLE_JATS_XML, "PMC123")
        assert title == "Test Article With Figures"
        assert figures is not None
        assert len(figures) == 2
        assert figures[0].label == "Figure 1"
        assert figures[0].caption_title == "Main Findings"
        assert figures[0].caption_text == "This figure shows the primary results."
        assert figures[0].graphic_href == "article-fig1"
        assert figures[1].label == "Figure 2"

    def test_parse_jats_figures_resolves_urls(self, client):
        figures, _ = client._parse_jats_figures(SAMPLE_JATS_XML, "PMC123")
        assert figures is not None
        assert figures[0].image_url is not None
        assert "PMC123" in figures[0].image_url
        assert "article-fig1" in figures[0].image_url

    def test_parse_jats_figures_section_references(self, client):
        figures, _ = client._parse_jats_figures(SAMPLE_JATS_XML, "PMC123")
        assert figures is not None
        # Figure 1 is mentioned in Introduction and Results
        assert "Introduction" in figures[0].mentioned_in_sections
        assert "Results" in figures[0].mentioned_in_sections
        # Figure 2 is mentioned in Results only
        assert "Results" in figures[1].mentioned_in_sections

    def test_parse_jats_with_subfigures(self, client):
        figures, title = client._parse_jats_figures(
            SAMPLE_JATS_XML_WITH_FIG_GROUP,
            "PMC123",
            include_subfigures=True,
        )
        assert title == "Article with Fig Group"
        assert figures is not None
        # Should have individual figs (3A, 3B from within fig-group iter)
        # plus the fig-group itself with subfigures
        fig_group = [f for f in figures if f.subfigures]
        assert len(fig_group) >= 1

    def test_parse_jats_with_tables(self, client):
        figures, _ = client._parse_jats_figures(
            SAMPLE_JATS_XML_WITH_TABLE,
            "PMC123",
            include_tables=True,
        )
        assert figures is not None
        assert len(figures) >= 1
        assert figures[0].label == "Table 1"

    def test_parse_jats_invalid_xml(self, client):
        result = client._parse_jats_figures("not valid xml <><>", "PMC123")
        assert result == (None, None)

    def test_parse_jats_empty_article(self, client):
        xml = "<article><body></body></article>"
        figures, title = client._parse_jats_figures(xml, "PMC123")
        assert figures is not None
        assert len(figures) == 0
        assert title is None

    # ----- BioC JSON Parsing -----

    def test_parse_bioc_figures(self, client):
        figures = client._parse_bioc_figures(SAMPLE_BIOC_JSON)
        assert len(figures) == 2
        assert figures[0].label == "Figure 1"
        assert "results of the study" in figures[0].caption_text
        assert figures[0].image_url is None  # BioC lacks image URLs

    def test_parse_bioc_empty(self, client):
        assert client._parse_bioc_figures({}) == []
        assert client._parse_bioc_figures({"documents": []}) == []

    # ----- URL Resolution -----

    def test_resolve_image_url_basic(self, client):
        url = client._resolve_image_url("PMC123", "article-fig1")
        assert url is not None
        assert "europepmc.org" in url
        assert "PMC123" in url
        assert "article-fig1" in url

    def test_resolve_image_url_empty_href(self, client):
        assert client._resolve_image_url("PMC123", "") is None

    # ----- Full extraction flow -----

    async def test_get_article_figures_epmc_success(self, client):
        """Test full extraction using Europe PMC source."""
        with patch.object(client, "_make_request", new_callable=AsyncMock) as mock:
            mock.return_value = SAMPLE_JATS_XML
            result = await client.get_article_figures("PMC123")

            assert isinstance(result, ArticleFiguresResult)
            assert result.source == "europepmc"
            assert result.total_figures == 2
            assert len(result.pdf_links) == 2
            assert result.error is None

    async def test_get_article_figures_fallback_to_efetch(self, client):
        """Test fallback to PMC efetch when Europe PMC fails."""
        call_count = 0

        async def side_effect(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "europepmc" in url:
                raise ConnectionError("EPMC down")
            return SAMPLE_JATS_XML

        with patch.object(client, "_make_request", side_effect=side_effect):
            result = await client.get_article_figures("PMC123")

            assert result.source == "pmc_efetch"
            assert result.total_figures == 2

    async def test_get_article_figures_fallback_to_bioc(self, client):
        """Test fallback to BioC JSON when both XML sources fail."""
        call_count = 0

        async def side_effect(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "europepmc" in url or "efetch" in url:
                raise ConnectionError("Down")
            return SAMPLE_BIOC_JSON

        with patch.object(client, "_make_request", side_effect=side_effect):
            result = await client.get_article_figures("PMC123")

            assert result.source == "bioc"
            assert result.total_figures == 2

    async def test_get_article_figures_all_fail(self, client):
        """Test error when all sources fail."""
        with patch.object(
            client,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=ConnectionError("All down"),
        ):
            result = await client.get_article_figures("PMC123")

            assert result.error == "source_unavailable"
            assert result.error_detail is not None

    async def test_get_article_figures_normalizes_pmcid(self, client):
        """Test that numeric PMCIDs are normalized."""
        with patch.object(client, "_make_request", new_callable=AsyncMock) as mock:
            mock.return_value = SAMPLE_JATS_XML
            result = await client.get_article_figures("12345")

            assert result.pmcid == "PMC12345"

    # ----- HTML scraping fallback -----

    async def test_resolve_image_urls_from_html(self, client):
        """Test HTML scraping for CDN URLs."""
        html = """
        <html><body>
        <img src="https://cdn.ncbi.nlm.nih.gov/pmc/blobs/abc/article-fig1.jpg" alt="Fig 1"/>
        <img src="https://cdn.ncbi.nlm.nih.gov/pmc/blobs/xyz/article-fig2.gif" alt="Fig 2"/>
        </body></html>
        """
        figures = [
            ArticleFigure(figure_id="f1", label="Figure 1", graphic_href="article-fig1"),
            ArticleFigure(figure_id="f2", label="Figure 2", graphic_href="article-fig2"),
        ]

        with patch.object(client, "_make_request", new_callable=AsyncMock, return_value=html):
            updated = await client.resolve_image_urls_from_html("PMC123", figures)

            assert updated[0].image_url is not None
            assert "cdn.ncbi.nlm.nih.gov" in updated[0].image_url
            assert updated[1].image_url is not None

    async def test_resolve_image_urls_from_html_failure(self, client):
        """Test HTML scraping gracefully handles failure."""
        figures = [ArticleFigure(figure_id="f1", label="Fig 1", graphic_href="x")]

        with patch.object(
            client,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=ConnectionError("Failed"),
        ):
            result = await client.resolve_image_urls_from_html("PMC123", figures)
            # Should return original figures, not raise
            assert len(result) == 1

    # ----- Singleton -----

    def test_get_figure_client_singleton(self):
        from pubmed_search.infrastructure.sources.figure_client import (
            get_figure_client,
        )

        c1 = get_figure_client()
        c2 = get_figure_client()
        assert c1 is c2

    # ----- 404 handling -----

    def test_handle_expected_status_404(self, client):
        """Test 404 is treated as expected (not_found)."""

        class FakeResp:
            status_code = 404

        result = client._handle_expected_status(FakeResp(), "http://example.com")
        assert result == {"error": "not_found"}
