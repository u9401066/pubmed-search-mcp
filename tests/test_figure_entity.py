"""Tests for ArticleFigure and ArticleFiguresResult domain entities."""

from __future__ import annotations

from pubmed_search.domain.entities.figure import ArticleFigure, ArticleFiguresResult


class TestArticleFigure:
    """Tests for ArticleFigure dataclass."""

    def test_basic_creation(self):
        fig = ArticleFigure(
            figure_id="f1",
            label="Figure 1",
            caption_text="Architecture diagram",
        )
        assert fig.figure_id == "f1"
        assert fig.label == "Figure 1"
        assert fig.caption_text == "Architecture diagram"
        assert fig.image_url is None
        assert fig.subfigures is None

    def test_full_creation(self):
        fig = ArticleFigure(
            figure_id="f1-article",
            label="Figure 1",
            caption_title="System Architecture",
            caption_text="Overview of the proposed system.",
            image_url="https://europepmc.org/articles/PMC123/bin/fig1.jpg",
            image_url_large="https://europepmc.org/articles/PMC123/bin/fig1_large.jpg",
            graphic_href="article-fig1",
            mentioned_in_sections=["Methods", "Results"],
        )
        assert fig.caption_title == "System Architecture"
        assert fig.image_url is not None
        assert "Methods" in fig.mentioned_in_sections

    def test_to_dict(self):
        fig = ArticleFigure(
            figure_id="f1",
            label="Figure 1",
            caption_text="Test caption",
            graphic_href="fig1",
        )
        d = fig.to_dict()
        assert d["figure_id"] == "f1"
        assert d["label"] == "Figure 1"
        assert d["caption_text"] == "Test caption"
        assert d["graphic_href"] == "fig1"
        assert "subfigures" not in d  # None subfigures not included

    def test_to_dict_with_subfigures(self):
        sub = ArticleFigure(figure_id="f1a", label="(A)", caption_text="Part A")
        fig = ArticleFigure(
            figure_id="f1",
            label="Figure 1",
            caption_text="Multi-part figure",
            subfigures=[sub],
        )
        d = fig.to_dict()
        assert "subfigures" in d
        assert len(d["subfigures"]) == 1
        assert d["subfigures"][0]["label"] == "(A)"

    def test_to_dict_with_mentioned_sections(self):
        fig = ArticleFigure(
            figure_id="f1",
            label="Figure 1",
            caption_text="Test",
            mentioned_in_sections=["Introduction", "Discussion"],
        )
        d = fig.to_dict()
        assert d["mentioned_in_sections"] == ["Introduction", "Discussion"]


class TestArticleFiguresResult:
    """Tests for ArticleFiguresResult dataclass."""

    def test_empty_result(self):
        result = ArticleFiguresResult(pmcid="PMC123")
        assert result.total_figures == 0
        assert result.figures == []
        assert result.is_open_access is True
        assert result.error is None

    def test_with_figures(self):
        figs = [
            ArticleFigure(figure_id="f1", label="Figure 1", caption_text="Cap1"),
            ArticleFigure(figure_id="f2", label="Figure 2", caption_text="Cap2"),
        ]
        result = ArticleFiguresResult(
            pmcid="PMC123",
            pmid="12345",
            article_title="Test Article",
            total_figures=2,
            figures=figs,
            source="europepmc",
        )
        assert result.total_figures == 2
        assert result.pmid == "12345"

    def test_with_pdf_links(self):
        result = ArticleFiguresResult(
            pmcid="PMC123",
            pdf_links=[
                {"source": "PubMed Central", "url": "https://example.com/pdf", "type": "pdf"},
            ],
        )
        d = result.to_dict()
        assert len(d["pdf_links"]) == 1

    def test_to_dict_with_error(self):
        result = ArticleFiguresResult(
            pmcid="PMC999",
            error="source_unavailable",
            error_detail="All sources failed",
        )
        d = result.to_dict()
        assert d["error"] == "source_unavailable"
        assert d["error_detail"] == "All sources failed"

    def test_to_dict_minimal(self):
        result = ArticleFiguresResult(pmcid="PMC123")
        d = result.to_dict()
        assert "pmcid" in d
        assert "total_figures" in d
        assert "source" in d
        assert "is_open_access" in d
        assert "pmid" not in d  # None pmid excluded
