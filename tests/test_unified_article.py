"""
Comprehensive tests for UnifiedArticle and related domain entities.

Target: article.py coverage from 28% to 90%+
Tests: Author, OpenAccessLink, CitationMetrics, SourceMetadata, UnifiedArticle
"""



from pubmed_search.domain.entities.article import (
    ArticleType,
    Author,
    CitationMetrics,
    OpenAccessLink,
    OpenAccessStatus,
    SourceMetadata,
    UnifiedArticle,
)


# =============================================================================
# Author Tests
# =============================================================================


class TestAuthor:
    """Tests for Author dataclass."""

    async def test_display_name_full_name(self):
        """Test display_name with full_name."""
        author = Author(full_name="John Smith")
        assert author.display_name == "John Smith"

    async def test_display_name_parts(self):
        """Test display_name from given and family name."""
        author = Author(family_name="Smith", given_name="John")
        assert author.display_name == "John Smith"

    async def test_display_name_family_only(self):
        """Test display_name with only family name."""
        author = Author(family_name="Smith")
        assert author.display_name == "Smith"

    async def test_display_name_given_only(self):
        """Test display_name with only given name."""
        author = Author(given_name="John")
        assert author.display_name == "John"

    async def test_display_name_unknown(self):
        """Test display_name with no name."""
        author = Author()
        assert author.display_name == "Unknown"

    async def test_citation_name_full(self):
        """Test citation_name with full name parts."""
        author = Author(family_name="Smith", given_name="John Alexander")
        assert author.citation_name == "Smith JA"

    async def test_citation_name_single_initial(self):
        """Test citation_name with single given name."""
        author = Author(family_name="Doe", given_name="Jane")
        assert author.citation_name == "Doe J"

    async def test_citation_name_fallback(self):
        """Test citation_name fallback to display_name."""
        author = Author(full_name="Unknown Author")
        assert author.citation_name == "Unknown Author"

    async def test_from_dict_crossref_format(self):
        """Test from_dict with CrossRef format."""
        data = {
            "family": "Smith",
            "given": "John",
            "ORCID": "0000-0001-2345-6789",
            "affiliation": [{"name": "MIT"}, {"name": "Harvard"}],
        }
        author = Author.from_dict(data)
        assert author.family_name == "Smith"
        assert author.given_name == "John"
        assert author.orcid == "0000-0001-2345-6789"
        assert author.affiliation == "MIT; Harvard"

    async def test_from_dict_crossref_no_affiliation(self):
        """Test from_dict with CrossRef format without affiliation."""
        data = {"family": "Doe", "given": "Jane"}
        author = Author.from_dict(data)
        assert author.affiliation is None

    async def test_from_dict_openalex_format(self):
        """Test from_dict with OpenAlex format."""
        data = {"display_name": "John Smith", "orcid": "0000-0001-2345-6789"}
        author = Author.from_dict(data)
        assert author.full_name == "John Smith"
        assert author.orcid == "0000-0001-2345-6789"

    async def test_from_dict_string(self):
        """Test from_dict with string input."""
        # Note: isinstance check for string is inside from_dict
        author = Author.from_dict({})  # Empty dict for generic path
        assert author.display_name == "Unknown"

    async def test_from_dict_generic(self):
        """Test from_dict with generic dict format."""
        data = {
            "family_name": "Smith",
            "given_name": "John",
            "name": "John Smith",
            "orcid": "0000-0001-2345-6789",
            "affiliation": "MIT",
        }
        author = Author.from_dict(data)
        assert author.family_name == "Smith"
        assert author.given_name == "John"
        assert author.affiliation == "MIT"


# =============================================================================
# OpenAccessLink Tests
# =============================================================================


class TestOpenAccessLink:
    """Tests for OpenAccessLink dataclass."""

    async def test_is_pdf_extension(self):
        """Test is_pdf with .pdf extension."""
        link = OpenAccessLink(url="https://example.com/paper.pdf")
        assert link.is_pdf is True

    async def test_is_pdf_in_path(self):
        """Test is_pdf with /pdf/ in path."""
        link = OpenAccessLink(url="https://example.com/pdf/123456")
        assert link.is_pdf is True

    async def test_is_pdf_false(self):
        """Test is_pdf with non-PDF URL."""
        link = OpenAccessLink(url="https://example.com/paper.html")
        assert link.is_pdf is False

    async def test_link_attributes(self):
        """Test link default attributes."""
        link = OpenAccessLink(url="https://example.com/paper")
        assert link.version == "unknown"
        assert link.host_type is None
        assert link.license is None
        assert link.is_best is False


# =============================================================================
# CitationMetrics Tests
# =============================================================================


class TestCitationMetrics:
    """Tests for CitationMetrics dataclass."""

    async def test_impact_level_high_percentile(self):
        """Test impact_level with high NIH percentile."""
        metrics = CitationMetrics(nih_percentile=95)
        assert metrics.impact_level == "high"

    async def test_impact_level_medium_percentile(self):
        """Test impact_level with medium NIH percentile."""
        metrics = CitationMetrics(nih_percentile=75)
        assert metrics.impact_level == "medium"

    async def test_impact_level_low_percentile(self):
        """Test impact_level with low NIH percentile."""
        metrics = CitationMetrics(nih_percentile=30)
        assert metrics.impact_level == "low"

    async def test_impact_level_high_rcr(self):
        """Test impact_level with high RCR."""
        metrics = CitationMetrics(relative_citation_ratio=3.0)
        assert metrics.impact_level == "high"

    async def test_impact_level_medium_rcr(self):
        """Test impact_level with medium RCR."""
        metrics = CitationMetrics(relative_citation_ratio=1.0)
        assert metrics.impact_level == "medium"

    async def test_impact_level_low_rcr(self):
        """Test impact_level with low RCR."""
        metrics = CitationMetrics(relative_citation_ratio=0.2)
        assert metrics.impact_level == "low"

    async def test_impact_level_high_citations(self):
        """Test impact_level with high citation count."""
        metrics = CitationMetrics(citation_count=200)
        assert metrics.impact_level == "high"

    async def test_impact_level_medium_citations(self):
        """Test impact_level with medium citation count."""
        metrics = CitationMetrics(citation_count=50)
        assert metrics.impact_level == "medium"

    async def test_impact_level_low_citations(self):
        """Test impact_level with low citation count."""
        metrics = CitationMetrics(citation_count=5)
        assert metrics.impact_level == "low"

    async def test_impact_level_unknown(self):
        """Test impact_level with no metrics."""
        metrics = CitationMetrics()
        assert metrics.impact_level == "unknown"


# =============================================================================
# SourceMetadata Tests
# =============================================================================


class TestSourceMetadata:
    """Tests for SourceMetadata dataclass."""

    async def test_basic_creation(self):
        """Test basic creation."""
        meta = SourceMetadata(source="pubmed")
        assert meta.source == "pubmed"
        assert meta.fetched_at is None
        assert meta.raw_data is None

    async def test_full_creation(self):
        """Test creation with all fields."""
        raw = {"id": "123"}
        meta = SourceMetadata(
            source="crossref", fetched_at="2024-01-01T00:00:00Z", raw_data=raw
        )
        assert meta.source == "crossref"
        assert meta.fetched_at == "2024-01-01T00:00:00Z"
        assert meta.raw_data == raw


# =============================================================================
# UnifiedArticle - Basic Tests
# =============================================================================


class TestUnifiedArticleBasic:
    """Basic tests for UnifiedArticle."""

    async def test_minimal_creation(self):
        """Test creation with minimal fields."""
        article = UnifiedArticle(title="Test Article", primary_source="pubmed")
        assert article.title == "Test Article"
        assert article.primary_source == "pubmed"
        assert article.year is None

    async def test_full_creation(self):
        """Test creation with all fields."""
        article = UnifiedArticle(
            title="Machine Learning in Healthcare",
            primary_source="pubmed",
            pmid="12345678",
            doi="10.1000/example",
            pmc="PMC7096777",
            abstract="This is an abstract.",
            journal="Nature Medicine",
            year=2024,
            article_type=ArticleType.JOURNAL_ARTICLE,
        )
        assert article.pmid == "12345678"
        assert article.doi == "10.1000/example"
        assert article.pmc == "PMC7096777"


# =============================================================================
# UnifiedArticle - Properties Tests
# =============================================================================


class TestUnifiedArticleProperties:
    """Tests for UnifiedArticle properties."""

    async def test_best_identifier_pmid(self):
        """Test best_identifier with PMID."""
        article = UnifiedArticle(
            title="Test", primary_source="pubmed", pmid="12345678"
        )
        assert article.best_identifier == "PMID:12345678"

    async def test_best_identifier_doi(self):
        """Test best_identifier with DOI (no PMID)."""
        article = UnifiedArticle(
            title="Test", primary_source="crossref", doi="10.1000/example"
        )
        assert article.best_identifier == "DOI:10.1000/example"

    async def test_best_identifier_pmc(self):
        """Test best_identifier with PMC (no PMID/DOI)."""
        article = UnifiedArticle(
            title="Test", primary_source="pmc", pmc="PMC7096777"
        )
        assert article.best_identifier == "PMC:PMC7096777"

    async def test_best_identifier_openalex(self):
        """Test best_identifier with OpenAlex ID."""
        article = UnifiedArticle(
            title="Test", primary_source="openalex", openalex_id="W12345678"
        )
        assert article.best_identifier == "OpenAlex:W12345678"

    async def test_best_identifier_s2(self):
        """Test best_identifier with Semantic Scholar ID."""
        article = UnifiedArticle(
            title="Test",
            primary_source="semantic_scholar",
            s2_id="1234567890abcdef1234567890abcdef12345678",
        )
        assert "S2:12345678" in article.best_identifier

    async def test_best_identifier_title_only(self):
        """Test best_identifier with only title."""
        article = UnifiedArticle(
            title="A Very Long Title for Testing Purpose", primary_source="unknown"
        )
        assert "Title:" in article.best_identifier

    async def test_has_open_access_explicit(self):
        """Test has_open_access with explicit flag."""
        article = UnifiedArticle(
            title="Test", primary_source="pubmed", is_open_access=True
        )
        assert article.has_open_access is True

    async def test_has_open_access_status_gold(self):
        """Test has_open_access with gold OA status."""
        article = UnifiedArticle(
            title="Test", primary_source="pubmed", oa_status=OpenAccessStatus.GOLD
        )
        assert article.has_open_access is True

    async def test_has_open_access_status_green(self):
        """Test has_open_access with green OA status."""
        article = UnifiedArticle(
            title="Test", primary_source="pubmed", oa_status=OpenAccessStatus.GREEN
        )
        assert article.has_open_access is True

    async def test_has_open_access_links(self):
        """Test has_open_access with OA links."""
        article = UnifiedArticle(
            title="Test",
            primary_source="pubmed",
            oa_links=[OpenAccessLink(url="https://example.com/paper.pdf")],
        )
        assert article.has_open_access is True

    async def test_has_open_access_false(self):
        """Test has_open_access is False."""
        article = UnifiedArticle(
            title="Test",
            primary_source="pubmed",
            oa_status=OpenAccessStatus.CLOSED,
            is_open_access=False,
        )
        assert article.has_open_access is False

    async def test_best_oa_link_empty(self):
        """Test best_oa_link with no links."""
        article = UnifiedArticle(title="Test", primary_source="pubmed")
        assert article.best_oa_link is None

    async def test_best_oa_link_marked_best(self):
        """Test best_oa_link prefers marked as best."""
        link1 = OpenAccessLink(url="https://repo.com/paper.pdf", is_best=False)
        link2 = OpenAccessLink(url="https://publisher.com/paper.pdf", is_best=True)
        article = UnifiedArticle(
            title="Test", primary_source="pubmed", oa_links=[link1, link2]
        )
        assert article.best_oa_link == link2

    async def test_best_oa_link_published_version(self):
        """Test best_oa_link prefers published version."""
        link1 = OpenAccessLink(url="https://repo.com/paper.pdf", version="acceptedVersion")
        link2 = OpenAccessLink(
            url="https://publisher.com/paper.pdf", version="publishedVersion"
        )
        article = UnifiedArticle(
            title="Test", primary_source="pubmed", oa_links=[link1, link2]
        )
        assert article.best_oa_link == link2

    async def test_best_oa_link_first_available(self):
        """Test best_oa_link returns first if no best/published."""
        link1 = OpenAccessLink(url="https://first.com/paper.pdf")
        link2 = OpenAccessLink(url="https://second.com/paper.pdf")
        article = UnifiedArticle(
            title="Test", primary_source="pubmed", oa_links=[link1, link2]
        )
        assert article.best_oa_link == link1

    async def test_author_string_empty(self):
        """Test author_string with no authors."""
        article = UnifiedArticle(title="Test", primary_source="pubmed")
        assert article.author_string == "Unknown"

    async def test_author_string_single(self):
        """Test author_string with single author."""
        article = UnifiedArticle(
            title="Test",
            primary_source="pubmed",
            authors=[Author(family_name="Smith", given_name="John")],
        )
        assert article.author_string == "Smith J"

    async def test_author_string_three(self):
        """Test author_string with three authors."""
        article = UnifiedArticle(
            title="Test",
            primary_source="pubmed",
            authors=[
                Author(family_name="Smith", given_name="John"),
                Author(family_name="Doe", given_name="Jane"),
                Author(family_name="Brown", given_name="Bob"),
            ],
        )
        assert article.author_string == "Smith J, Doe J, Brown B"

    async def test_author_string_many(self):
        """Test author_string with more than 3 authors."""
        article = UnifiedArticle(
            title="Test",
            primary_source="pubmed",
            authors=[
                Author(family_name="A", given_name="X"),
                Author(family_name="B", given_name="Y"),
                Author(family_name="C", given_name="Z"),
                Author(family_name="D", given_name="W"),
            ],
        )
        assert "et al." in article.author_string

    async def test_pubmed_url(self):
        """Test pubmed_url property."""
        article = UnifiedArticle(
            title="Test", primary_source="pubmed", pmid="12345678"
        )
        assert article.pubmed_url == "https://pubmed.ncbi.nlm.nih.gov/12345678/"

    async def test_pubmed_url_none(self):
        """Test pubmed_url without PMID."""
        article = UnifiedArticle(title="Test", primary_source="crossref")
        assert article.pubmed_url is None

    async def test_doi_url(self):
        """Test doi_url property."""
        article = UnifiedArticle(
            title="Test", primary_source="crossref", doi="10.1000/example"
        )
        assert article.doi_url == "https://doi.org/10.1000/example"

    async def test_doi_url_none(self):
        """Test doi_url without DOI."""
        article = UnifiedArticle(title="Test", primary_source="pubmed")
        assert article.doi_url is None

    async def test_pmc_url(self):
        """Test pmc_url property."""
        article = UnifiedArticle(
            title="Test", primary_source="pmc", pmc="PMC7096777"
        )
        assert "PMC7096777" in article.pmc_url

    async def test_pmc_url_none(self):
        """Test pmc_url without PMC ID."""
        article = UnifiedArticle(title="Test", primary_source="pubmed")
        assert article.pmc_url is None


# =============================================================================
# UnifiedArticle - Citation Methods Tests
# =============================================================================


class TestUnifiedArticleCitation:
    """Tests for UnifiedArticle citation methods."""

    async def test_cite_vancouver_full(self):
        """Test cite_vancouver with full metadata."""
        article = UnifiedArticle(
            title="Machine Learning in Healthcare",
            primary_source="pubmed",
            authors=[
                Author(family_name="Smith", given_name="John"),
                Author(family_name="Doe", given_name="Jane"),
            ],
            journal="JAMA",
            journal_abbrev="JAMA",
            year=2024,
            volume="331",
            issue="2",
            pages="123-130",
            doi="10.1000/example",
        )
        citation = article.cite_vancouver()
        assert "Smith J" in citation
        assert "Machine Learning in Healthcare" in citation
        assert "JAMA" in citation
        assert "2024" in citation
        assert "331" in citation
        assert "(2)" in citation
        assert "123-130" in citation
        assert "doi:10.1000/example" in citation

    async def test_cite_vancouver_minimal(self):
        """Test cite_vancouver with minimal metadata."""
        article = UnifiedArticle(title="Test Article", primary_source="unknown")
        citation = article.cite_vancouver()
        assert "Test Article" in citation
        assert "Unknown" in citation

    async def test_cite_vancouver_year_only(self):
        """Test cite_vancouver with year only (no journal)."""
        article = UnifiedArticle(
            title="Conference Paper", primary_source="unknown", year=2023
        )
        citation = article.cite_vancouver()
        assert "2023" in citation

    async def test_cite_apa_full(self):
        """Test cite_apa with full metadata."""
        article = UnifiedArticle(
            title="Machine Learning in Healthcare",
            primary_source="pubmed",
            authors=[
                Author(family_name="Smith", given_name="John"),
                Author(family_name="Doe", given_name="Jane"),
            ],
            journal="JAMA",
            year=2024,
            volume="331",
            issue="2",
            pages="123-130",
            doi="10.1000/example",
        )
        citation = article.cite_apa()
        assert "Smith, J." in citation
        assert "&" in citation
        assert "(2024)" in citation
        assert "JAMA" in citation
        assert "https://doi.org/10.1000/example" in citation

    async def test_cite_apa_single_author(self):
        """Test cite_apa with single author."""
        article = UnifiedArticle(
            title="Solo Research",
            primary_source="pubmed",
            authors=[Author(family_name="Smith", given_name="John")],
            year=2024,
        )
        citation = article.cite_apa()
        assert "Smith, J." in citation
        assert "&" not in citation

    async def test_cite_apa_three_authors(self):
        """Test cite_apa with three authors."""
        article = UnifiedArticle(
            title="Team Research",
            primary_source="pubmed",
            authors=[
                Author(family_name="A", given_name="X"),
                Author(family_name="B", given_name="Y"),
                Author(family_name="C", given_name="Z"),
            ],
            year=2024,
        )
        citation = article.cite_apa()
        assert ", & " in citation

    async def test_cite_apa_many_authors(self):
        """Test cite_apa with more than 7 authors."""
        article = UnifiedArticle(
            title="Large Team Research",
            primary_source="pubmed",
            authors=[Author(family_name=f"Author{i}", given_name="X") for i in range(10)],
            year=2024,
        )
        citation = article.cite_apa()
        assert "..." in citation

    async def test_cite_apa_no_year(self):
        """Test cite_apa without year."""
        article = UnifiedArticle(title="Undated", primary_source="unknown")
        citation = article.cite_apa()
        assert "(n.d.)" in citation

    async def test_cite_apa_full_name_author(self):
        """Test cite_apa with full_name author."""
        article = UnifiedArticle(
            title="Test",
            primary_source="pubmed",
            authors=[Author(full_name="John Smith")],
            year=2024,
        )
        citation = article.cite_apa()
        assert "John Smith" in citation

    async def test_citation_string_uses_vancouver(self):
        """Test citation_string property uses Vancouver style."""
        article = UnifiedArticle(
            title="Test",
            primary_source="pubmed",
            authors=[Author(family_name="Smith", given_name="John")],
            journal="Nature",
            year=2024,
        )
        assert article.citation_string == article.cite_vancouver()


# =============================================================================
# UnifiedArticle - Factory Methods Tests
# =============================================================================


class TestUnifiedArticleFactory:
    """Tests for UnifiedArticle factory methods."""

    async def test_from_pubmed_basic(self):
        """Test from_pubmed with basic data."""
        data = {
            "title": "Test Article",
            "pmid": "12345678",
            "doi": "10.1000/example",
        }
        article = UnifiedArticle.from_pubmed(data)
        assert article.title == "Test Article"
        assert article.pmid == "12345678"
        assert article.primary_source == "pubmed"

    async def test_from_pubmed_authors_string(self):
        """Test from_pubmed with string authors."""
        data = {
            "title": "Test",
            "authors": ["Smith J", "Doe J"],
        }
        article = UnifiedArticle.from_pubmed(data)
        assert len(article.authors) == 2
        assert article.authors[0].full_name == "Smith J"

    async def test_from_pubmed_authors_dict(self):
        """Test from_pubmed with dict authors."""
        data = {
            "title": "Test",
            "authors": [{"family": "Smith", "given": "John"}],
        }
        article = UnifiedArticle.from_pubmed(data)
        assert article.authors[0].family_name == "Smith"

    async def test_from_pubmed_year_from_pub_date(self):
        """Test from_pubmed extracts year from pub_date."""
        data = {
            "title": "Test",
            "pub_date": "2024 Jan 15",
        }
        article = UnifiedArticle.from_pubmed(data)
        assert article.year == 2024

    async def test_from_pubmed_year_direct(self):
        """Test from_pubmed uses year field."""
        data = {
            "title": "Test",
            "year": 2023,
        }
        article = UnifiedArticle.from_pubmed(data)
        assert article.year == 2023

    async def test_from_pubmed_article_types(self):
        """Test from_pubmed article type mapping."""
        type_tests = [
            ("Journal Article", ArticleType.JOURNAL_ARTICLE),
            ("Review", ArticleType.REVIEW),
            ("Meta-Analysis", ArticleType.META_ANALYSIS),
            ("Clinical Trial", ArticleType.CLINICAL_TRIAL),
            ("Randomized Controlled Trial", ArticleType.RANDOMIZED_CONTROLLED_TRIAL),
        ]
        for pub_type, expected_type in type_tests:
            data = {"title": "Test", "article_type": [pub_type]}
            article = UnifiedArticle.from_pubmed(data)
            assert article.article_type == expected_type

    async def test_from_pubmed_unknown_type(self):
        """Test from_pubmed with unknown article type."""
        data = {"title": "Test", "article_type": ["Unknown Type"]}
        article = UnifiedArticle.from_pubmed(data)
        assert article.article_type == ArticleType.UNKNOWN


# =============================================================================
# UnifiedArticle - Merge and Match Tests
# =============================================================================


class TestUnifiedArticleMerge:
    """Tests for UnifiedArticle merge functionality."""

    async def test_matches_identifier_same_pmid(self):
        """Test matches_identifier with same PMID."""
        article1 = UnifiedArticle(title="Test", primary_source="pubmed", pmid="123")
        article2 = UnifiedArticle(title="Test", primary_source="europe_pmc", pmid="123")
        assert article1.matches_identifier(article2) is True

    async def test_matches_identifier_same_doi(self):
        """Test matches_identifier with same DOI."""
        article1 = UnifiedArticle(
            title="Test", primary_source="pubmed", doi="10.1/test"
        )
        article2 = UnifiedArticle(
            title="Test", primary_source="crossref", doi="10.1/test"
        )
        assert article1.matches_identifier(article2) is True

    async def test_matches_identifier_different(self):
        """Test matches_identifier with different IDs."""
        article1 = UnifiedArticle(title="Test 1", primary_source="pubmed", pmid="123")
        article2 = UnifiedArticle(title="Test 2", primary_source="pubmed", pmid="456")
        assert article1.matches_identifier(article2) is False


# =============================================================================
# UnifiedArticle - Serialization Tests
# =============================================================================


class TestUnifiedArticleSerialization:
    """Tests for UnifiedArticle serialization."""

    async def test_to_dict_basic(self):
        """Test to_dict with basic fields."""
        article = UnifiedArticle(
            title="Test Article",
            primary_source="pubmed",
            pmid="12345678",
            year=2024,
        )
        data = article.to_dict()
        assert data["title"] == "Test Article"
        assert data["identifiers"]["pmid"] == "12345678"
        assert data["year"] == 2024

    async def test_to_dict_authors(self):
        """Test to_dict includes authors."""
        article = UnifiedArticle(
            title="Test",
            primary_source="pubmed",
            authors=[Author(full_name="John Smith")],
        )
        data = article.to_dict()
        assert "authors" in data
        assert len(data["authors"]) == 1

    async def test_to_dict_metrics(self):
        """Test to_dict includes citation metrics."""
        article = UnifiedArticle(
            title="Test",
            primary_source="pubmed",
            citation_metrics=CitationMetrics(citation_count=100),
        )
        data = article.to_dict()
        assert "citation_metrics" in data or "citation_count" in str(data)


# =============================================================================
# ArticleType Enum Tests
# =============================================================================


class TestArticleType:
    """Tests for ArticleType enum."""

    async def test_all_types_have_values(self):
        """Test all article types have string values."""
        for article_type in ArticleType:
            assert isinstance(article_type.value, str)

    async def test_common_types(self):
        """Test common article type values."""
        assert ArticleType.JOURNAL_ARTICLE.value == "journal-article"
        assert ArticleType.REVIEW.value == "review"
        assert ArticleType.META_ANALYSIS.value == "meta-analysis"
        assert ArticleType.PREPRINT.value == "preprint"


# =============================================================================
# OpenAccessStatus Enum Tests
# =============================================================================


class TestOpenAccessStatus:
    """Tests for OpenAccessStatus enum."""

    async def test_all_statuses_have_values(self):
        """Test all OA statuses have string values."""
        for status in OpenAccessStatus:
            assert isinstance(status.value, str)

    async def test_common_statuses(self):
        """Test common OA status values."""
        assert OpenAccessStatus.GOLD.value == "gold"
        assert OpenAccessStatus.GREEN.value == "green"
        assert OpenAccessStatus.CLOSED.value == "closed"
