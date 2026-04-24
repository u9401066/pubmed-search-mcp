"""
Tests for preprint sources (arXiv, medRxiv, bioRxiv).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from pubmed_search.infrastructure.sources import preprints as preprints_module
from pubmed_search.infrastructure.sources.preprints import (
    ArXivClient,
    MedBioRxivClient,
    PreprintArticle,
    PreprintSearcher,
)

ARXIV_ATOM_RESPONSE = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns='http://www.w3.org/2005/Atom' xmlns:arxiv='http://arxiv.org/schemas/atom'>
    <entry>
        <id>http://arxiv.org/abs/2301.12345v1</id>
        <updated>2023-02-01T00:00:00Z</updated>
        <published>2023-01-15T00:00:00Z</published>
        <title>Test Paper</title>
        <summary>This is a test abstract.</summary>
        <author><name>Author One</name></author>
        <author><name>Author Two</name></author>
        <category term='q-bio.QM' />
        <link title='pdf' href='https://arxiv.org/pdf/2301.12345.pdf' />
        <arxiv:doi>10.1000/test</arxiv:doi>
    </entry>
</feed>
"""


class TestArXivClient:
    """Tests for arXiv API client."""

    async def test_arxiv_search_basic(self):
        """Test basic arXiv search."""
        client = ArXivClient(timeout=30.0)
        with patch.object(ArXivClient, "_make_request", new=AsyncMock(return_value=ARXIV_ATOM_RESPONSE)):
            results = await client.search("machine learning healthcare", limit=3)

        assert isinstance(results, list)
        assert len(results) == 1
        article = results[0]
        assert isinstance(article, PreprintArticle)
        assert article.source == "arxiv"
        assert article.title == "Test Paper"

    async def test_arxiv_search_with_categories(self):
        """Test arXiv search with category filter."""
        client = ArXivClient(timeout=30.0)
        with patch.object(ArXivClient, "_make_request", new=AsyncMock(return_value=ARXIV_ATOM_RESPONSE)):
            results = await client.search("neural network", limit=3, categories=["q-bio", "cs.AI"])

        assert isinstance(results, list)
        assert len(results) == 1

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

    @patch.object(ArXivClient, "search", new_callable=AsyncMock)
    async def test_search_all_sources(self, mock_arxiv):
        """Test searching across all preprint sources."""
        mock_arxiv.return_value = [
            PreprintArticle(
                id="1",
                title="arXiv paper",
                abstract="",
                authors=[],
                published="2024-01-01",
                updated=None,
                source="arxiv",
                categories=["q-bio.QM"],
                pdf_url=None,
                doi=None,
            )
        ]
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
        assert results["total"] == 1

    @patch.object(MedBioRxivClient, "search_medrxiv", new_callable=AsyncMock)
    @patch.object(ArXivClient, "search", new_callable=AsyncMock)
    async def test_search_medical_preprints(self, mock_arxiv, mock_medrxiv):
        """Test convenience method for medical preprints."""
        mock_arxiv.return_value = []
        mock_medrxiv.return_value = [
            PreprintArticle(
                id="2",
                title="medRxiv paper",
                abstract="",
                authors=["Author One"],
                published="2024-01-02",
                updated=None,
                source="medrxiv",
                categories=["Anesthesiology"],
                pdf_url=None,
                doi="10.1101/2024.01.02.123456",
            )
        ]
        searcher = PreprintSearcher()
        results = await searcher.search_medical_preprints(
            query="anesthesia",
            limit=3,
        )

        assert "articles" in results
        assert results["total"] == 1
        assert "medrxiv" in results["sources_searched"]

    @patch.object(MedBioRxivClient, "search_medrxiv", new_callable=AsyncMock)
    @patch.object(ArXivClient, "search", new_callable=AsyncMock)
    async def test_search_soft_times_out_straggler_source(self, mock_arxiv, mock_medrxiv):
        mock_arxiv.return_value = [
            PreprintArticle(
                id="1",
                title="fast source",
                abstract="",
                authors=[],
                published="2024-01-01",
                updated=None,
                source="arxiv",
                categories=["q-bio.QM"],
                pdf_url=None,
                doi=None,
            )
        ]

        async def _hang(*args, **kwargs):
            await asyncio.Event().wait()

        mock_medrxiv.side_effect = _hang

        searcher = PreprintSearcher()
        with patch.object(preprints_module, "PREPRINT_SOURCE_TIMEOUT_SECONDS", 0.01):
            async with asyncio.timeout(0.2):
                results = await searcher.search(query="covid", sources=["arxiv", "medrxiv"], limit=3)

        assert results["total"] == 1
        assert any("timed out" in error.lower() for error in results["errors"])


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
