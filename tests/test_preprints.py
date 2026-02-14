"""
Tests for preprint sources (arXiv, medRxiv, bioRxiv).
"""

from __future__ import annotations

import pytest

from pubmed_search.infrastructure.sources.preprints import (
    ArXivClient,
    PreprintArticle,
    PreprintSearcher,
)


class TestArXivClient:
    """Tests for arXiv API client."""

    async def test_arxiv_search_basic(self):
        """Test basic arXiv search."""
        client = ArXivClient(timeout=30.0)
        results = await client.search("machine learning healthcare", limit=3)

        # Should return list (may be empty if API issues)
        assert isinstance(results, list)

        # If we got results, check structure
        if results:
            article = results[0]
            assert isinstance(article, PreprintArticle)
            assert article.source == "arxiv"
            assert article.title

    async def test_arxiv_search_with_categories(self):
        """Test arXiv search with category filter."""
        client = ArXivClient(timeout=30.0)
        results = await client.search("neural network", limit=3, categories=["q-bio", "cs.AI"])

        assert isinstance(results, list)

    async def test_preprint_article_to_dict(self):
        """Test PreprintArticle serialization."""
        article = PreprintArticle(
            id="2301.12345",
            title="Test Paper",
            abstract="This is a test abstract.",
            authors=["Author One", "Author Two"],
            published="2023-01-15",
            updated="2023-02-01",
            source="arxiv",
            categories=["q-bio.QM", "cs.AI"],
            pdf_url="https://arxiv.org/pdf/2301.12345.pdf",
            doi=None,
        )

        d = article.to_dict()

        assert d["id"] == "2301.12345"
        assert d["title"] == "Test Paper"
        assert d["source"] == "arxiv"
        assert d["source_url"] == "https://arxiv.org/abs/2301.12345"
        assert len(d["authors"]) == 2


class TestPreprintSearcher:
    """Tests for unified preprint searcher."""

    async def test_search_all_sources(self):
        """Test searching across all preprint sources."""
        searcher = PreprintSearcher()
        results = await searcher.search(
            query="COVID-19 vaccine",
            sources=["arxiv"],  # Just arXiv for faster test
            limit=3,
        )

        assert "query" in results
        assert "sources_searched" in results
        assert "articles" in results
        assert "by_source" in results
        assert "total" in results

    async def test_search_medical_preprints(self):
        """Test convenience method for medical preprints."""
        searcher = PreprintSearcher()
        results = await searcher.search_medical_preprints(
            query="anesthesia",
            limit=3,
        )

        assert "articles" in results
        # Medical preprints uses medRxiv + arXiv q-bio
        assert "medrxiv" in results["sources_searched"] or "arxiv" in results["sources_searched"]


class TestIcdDetection:
    """Test ICD code detection in unified search."""

    async def test_icd10_detection_regex(self):
        """Test ICD-10 pattern matching."""
        import re

        ICD10_PATTERN = re.compile(r"\b([A-Z]\d{2}(?:\.\d{1,4})?)\b", re.IGNORECASE)

        # Test various ICD-10 codes
        assert ICD10_PATTERN.findall("E11 diabetes") == ["E11"]
        assert ICD10_PATTERN.findall("I21.9 STEMI") == ["I21.9"]  # Full code with decimal
        assert ICD10_PATTERN.findall("U07.1 COVID") == ["U07.1"]
        assert ICD10_PATTERN.findall("C50 breast cancer") == ["C50"]

    async def test_icd9_detection_regex(self):
        """Test ICD-9 pattern matching."""
        import re

        ICD9_PATTERN = re.compile(r"\b(\d{3}(?:\.\d{1,2})?)\b")

        # Test ICD-9 codes (with decimals included)
        assert "250" in ICD9_PATTERN.findall("250 diabetes")
        assert "410.1" in ICD9_PATTERN.findall("410.1 MI")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
