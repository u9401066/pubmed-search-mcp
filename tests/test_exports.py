"""
Tests for Export modules - formats.py and links.py.
"""

from __future__ import annotations

import json

import pytest


class TestExportFormats:
    """Tests for export format functions."""

    @pytest.fixture
    def sample_article(self):
        """Sample article for testing."""
        return {
            "pmid": "12345678",
            "title": "Effects of Drug X on Condition Y: A Clinical Trial",
            "authors": ["Smith John", "Doe Jane", "Johnson Alice"],
            "abstract": "Background: Test abstract. Methods: We studied. Results: Found results.",
            "journal": "Journal of Medicine",
            "journal_abbrev": "J Med",
            "year": "2024",
            "volume": "10",
            "issue": "5",
            "pages": "100-110",
            "doi": "10.1000/test.001",
            "pmc_id": "PMC9876543",
            "issn": "1234-5678",
            "keywords": ["drug x", "clinical trial"],
        }

    async def test_convert_to_latex_with_pylatexenc(self):
        """Test LaTeX conversion with pylatexenc."""
        from pubmed_search.application.export.formats import _convert_to_latex

        # Should handle special characters
        result = _convert_to_latex("café")
        assert result is not None

    async def test_convert_to_latex_fallback(self):
        """Test LaTeX conversion fallback without pylatexenc."""
        from pubmed_search.application.export.formats import _convert_to_latex

        # Test basic characters even if pylatexenc is available
        result = _convert_to_latex("test")
        assert result == "test"

    async def test_convert_to_latex_empty(self):
        """Test LaTeX conversion with empty string."""
        from pubmed_search.application.export.formats import _convert_to_latex

        assert _convert_to_latex("") == ""
        assert _convert_to_latex(None) is None

    async def test_strip_html_tags(self):
        """Test HTML tag stripping."""
        from pubmed_search.application.export.formats import _strip_html_tags

        # Superscript
        result = _strip_html_tags("H<sup>2</sup>O")
        assert "^2" in result

        # Subscript
        result = _strip_html_tags("CO<sub>2</sub>")
        assert "_2" in result

        # Bold/italic
        result = _strip_html_tags("<b>bold</b> <i>italic</i>")
        assert "<b>" not in result
        assert "bold" in result

    async def test_strip_html_tags_empty(self):
        """Test HTML tag stripping with empty string."""
        from pubmed_search.application.export.formats import _strip_html_tags

        assert _strip_html_tags("") == ""
        assert _strip_html_tags(None) is None

    async def test_format_author_ris_simple(self):
        """Test RIS author formatting - simple case."""
        from pubmed_search.application.export.formats import _format_author_ris

        assert _format_author_ris("Smith John") == "Smith, John"
        assert _format_author_ris("Doe Jane Mary") == "Doe, Jane Mary"

    async def test_format_author_ris_already_formatted(self):
        """Test RIS author formatting - already has comma."""
        from pubmed_search.application.export.formats import _format_author_ris

        assert _format_author_ris("Smith, John") == "Smith, John"

    async def test_format_author_ris_single_name(self):
        """Test RIS author formatting - single name."""
        from pubmed_search.application.export.formats import _format_author_ris

        assert _format_author_ris("Madonna") == "Madonna"

    async def test_format_author_ris_empty(self):
        """Test RIS author formatting - empty."""
        from pubmed_search.application.export.formats import _format_author_ris

        assert _format_author_ris("") == ""
        assert _format_author_ris(None) is None

    async def test_export_ris(self, sample_article):
        """Test RIS format export."""
        from pubmed_search.application.export.formats import export_ris

        result = export_ris([sample_article], include_abstract=True)

        assert "TY  - JOUR" in result
        assert "T1  -" in result
        assert "AU  -" in result
        assert sample_article["title"] in result
        assert "ER  -" in result

    async def test_export_ris_no_abstract(self, sample_article):
        """Test RIS format export without abstract."""
        from pubmed_search.application.export.formats import export_ris

        result = export_ris([sample_article], include_abstract=False)

        assert "TY  - JOUR" in result
        # Abstract tag should not be present or should be empty

    async def test_export_ris_empty(self):
        """Test RIS format export with empty list."""
        from pubmed_search.application.export.formats import export_ris

        result = export_ris([])
        assert result == ""


class TestExportBibTeX:
    """Tests for BibTeX export."""

    @pytest.fixture
    def sample_article(self):
        return {
            "pmid": "12345678",
            "title": "Test Article",
            "authors": ["Smith John", "Doe Jane"],
            "journal": "Test Journal",
            "year": "2024",
            "volume": "10",
            "pages": "1-10",
            "doi": "10.1000/test",
        }

    async def test_export_bibtex(self, sample_article):
        """Test BibTeX format export."""
        from pubmed_search.application.export.formats import export_bibtex

        result = export_bibtex([sample_article])

        assert "@article{" in result
        assert "title = {" in result
        assert "author = {" in result
        assert "}" in result

    async def test_export_bibtex_special_chars(self):
        """Test BibTeX export with special characters."""
        from pubmed_search.application.export.formats import export_bibtex

        article = {
            "pmid": "123",
            "title": "Effects of α-blockers on β-receptors",
            "authors": ["Müller Hans"],
            "journal": "Journal",
            "year": "2024",
        }

        result = export_bibtex([article])
        assert "@article{" in result


class TestExportCSV:
    """Tests for CSV export."""

    @pytest.fixture
    def sample_articles(self):
        return [
            {
                "pmid": "123",
                "title": "Article 1",
                "authors": ["Author A"],
                "journal": "Journal 1",
                "year": "2024",
            },
            {
                "pmid": "456",
                "title": "Article 2",
                "authors": ["Author B", "Author C"],
                "journal": "Journal 2",
                "year": "2023",
            },
        ]

    async def test_export_csv(self, sample_articles):
        """Test CSV format export."""
        from pubmed_search.application.export.formats import export_csv

        result = export_csv(sample_articles)

        assert "pmid" in result.lower() or "PMID" in result
        assert "123" in result
        assert "456" in result

    async def test_export_csv_empty(self):
        """Test CSV export with empty list."""
        from pubmed_search.application.export.formats import export_csv

        result = export_csv([])
        # Should still have headers or be empty
        assert result is not None


class TestExportMEDLINE:
    """Tests for MEDLINE export."""

    @pytest.fixture
    def sample_article(self):
        return {
            "pmid": "12345678",
            "title": "Test Article",
            "authors": ["Smith John"],
            "journal": "Test Journal",
            "year": "2024",
            "abstract": "Test abstract",
        }

    async def test_export_medline(self, sample_article):
        """Test MEDLINE format export."""
        from pubmed_search.application.export.formats import export_medline

        result = export_medline([sample_article])

        assert "PMID" in result
        assert "12345678" in result


class TestExportJSON:
    """Tests for JSON export."""

    @pytest.fixture
    def sample_article(self):
        return {
            "pmid": "12345678",
            "title": "Test Article",
            "authors": ["Smith John"],
            "journal": "Test Journal",
            "year": "2024",
        }

    async def test_export_json(self, sample_article):
        """Test JSON format export."""
        from pubmed_search.application.export.formats import export_json

        result = export_json([sample_article])

        # Should be valid JSON with wrapper
        parsed = json.loads(result)
        assert "articles" in parsed
        assert len(parsed["articles"]) == 1
        assert parsed["articles"][0]["pmid"] == "12345678"

    async def test_export_json_empty(self):
        """Test JSON export with empty list."""
        from pubmed_search.application.export.formats import export_json

        result = export_json([])
        parsed = json.loads(result)
        assert parsed["articles"] == []
        assert parsed["article_count"] == 0


class TestExportArticles:
    """Tests for main export_articles function."""

    @pytest.fixture
    def sample_article(self):
        return {
            "pmid": "12345678",
            "title": "Test Article",
            "authors": ["Smith John"],
            "journal": "Test Journal",
            "year": "2024",
        }

    async def test_export_articles_ris(self, sample_article):
        """Test export_articles with RIS format."""
        from pubmed_search.application.export.formats import export_articles

        result = export_articles([sample_article], fmt="ris")
        assert "TY  - JOUR" in result

    async def test_export_articles_bibtex(self, sample_article):
        """Test export_articles with BibTeX format."""
        from pubmed_search.application.export.formats import export_articles

        result = export_articles([sample_article], fmt="bibtex")
        assert "@article{" in result

    async def test_export_articles_csv(self, sample_article):
        """Test export_articles with CSV format."""
        from pubmed_search.application.export.formats import export_articles

        result = export_articles([sample_article], fmt="csv")
        assert "12345678" in result

    async def test_export_articles_json(self, sample_article):
        """Test export_articles with JSON format."""
        from pubmed_search.application.export.formats import export_articles

        result = export_articles([sample_article], fmt="json")
        parsed = json.loads(result)
        assert "articles" in parsed
        assert len(parsed["articles"]) == 1

    async def test_export_articles_invalid_format(self, sample_article):
        """Test export_articles with invalid format."""
        from pubmed_search.application.export.formats import export_articles

        # Should raise ValueError for unsupported format
        with pytest.raises(ValueError, match="Unsupported format"):
            export_articles([sample_article], fmt="invalid")


class TestFulltextLinks:
    """Tests for fulltext links functions."""

    @pytest.fixture
    def sample_article_with_pmc(self):
        return {"pmid": "12345678", "doi": "10.1000/test", "pmc_id": "PMC9876543"}

    @pytest.fixture
    def sample_article_no_pmc(self):
        return {"pmid": "12345678", "doi": "10.1000/test", "pmc_id": ""}

    async def test_get_fulltext_links_with_pmc(self, sample_article_with_pmc):
        """Test getting fulltext links with PMC available."""
        from pubmed_search.application.export.links import get_fulltext_links

        result = get_fulltext_links(sample_article_with_pmc)

        assert result["has_free_fulltext"] is True
        assert result["access_type"] == "open_access"
        assert "pmc" in result["pmc_url"].lower()
        assert result["pmc_pdf_url"] is not None

    async def test_get_fulltext_links_no_pmc(self, sample_article_no_pmc):
        """Test getting fulltext links without PMC."""
        from pubmed_search.application.export.links import get_fulltext_links

        result = get_fulltext_links(sample_article_no_pmc)

        assert result["has_free_fulltext"] is False
        assert result["access_type"] == "subscription"
        assert result["pmc_url"] is None
        assert result["doi_url"] is not None

    async def test_get_fulltext_links_no_doi_no_pmc(self):
        """Test getting fulltext links without DOI or PMC."""
        from pubmed_search.application.export.links import get_fulltext_links

        article = {"pmid": "12345678", "doi": "", "pmc_id": ""}
        result = get_fulltext_links(article)

        assert result["access_type"] == "abstract_only"

    async def test_get_batch_fulltext_links(self, sample_article_with_pmc, sample_article_no_pmc):
        """Test getting fulltext links for multiple articles."""
        from pubmed_search.application.export.links import get_batch_fulltext_links

        articles = [sample_article_with_pmc, sample_article_no_pmc]
        results = get_batch_fulltext_links(articles)

        assert len(results) == 2
        assert results[0]["has_free_fulltext"] is True
        assert results[1]["has_free_fulltext"] is False

    async def test_summarize_access(self, sample_article_with_pmc, sample_article_no_pmc):
        """Test summarizing fulltext access."""
        from pubmed_search.application.export.links import summarize_access

        articles = [
            sample_article_with_pmc,
            sample_article_no_pmc,
            {"pmid": "3", "doi": "", "pmc_id": ""},
        ]

        summary = summarize_access(articles)

        assert summary["total"] == 3
        assert summary["open_access"] == 1
        assert summary["subscription"] == 1
        assert summary["abstract_only"] == 1
        assert summary["pmc_percentage"] == pytest.approx(33.3, rel=0.1)

    async def test_summarize_access_empty(self):
        """Test summarizing access with empty list."""
        from pubmed_search.application.export.links import summarize_access

        summary = summarize_access([])

        assert summary["total"] == 0
        assert summary["pmc_percentage"] == 0
