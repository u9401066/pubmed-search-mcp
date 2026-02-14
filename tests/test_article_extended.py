"""Extended tests for article.py — Author, OpenAccessLink, CitationMetrics, UnifiedArticle."""

from __future__ import annotations

from datetime import date

from pubmed_search.domain.entities.article import (
    ArticleType,
    Author,
    CitationMetrics,
    OpenAccessLink,
    OpenAccessStatus,
    SourceMetadata,
    UnifiedArticle,
)

# ============================================================
# Author
# ============================================================


class TestAuthor:
    async def test_display_name_full_name(self):
        a = Author(full_name="John Smith")
        assert a.display_name == "John Smith"

    async def test_display_name_parts(self):
        a = Author(given_name="John", family_name="Smith")
        assert a.display_name == "John Smith"

    async def test_display_name_family_only(self):
        a = Author(family_name="Smith")
        assert a.display_name == "Smith"

    async def test_display_name_none(self):
        a = Author()
        assert a.display_name == "Unknown"

    async def test_citation_name(self):
        a = Author(given_name="John Robert", family_name="Smith")
        assert a.citation_name == "Smith JR"

    async def test_citation_name_single_initial(self):
        a = Author(given_name="John", family_name="Smith")
        assert a.citation_name == "Smith J"

    async def test_citation_name_fallback(self):
        a = Author(full_name="Smith J")
        assert a.citation_name == "Smith J"

    async def test_from_dict_crossref(self):
        data = {
            "family": "Smith",
            "given": "John",
            "ORCID": "0000-0001-2345-6789",
            "affiliation": [{"name": "MIT"}],
        }
        a = Author.from_dict(data)
        assert a.family_name == "Smith"
        assert a.orcid == "0000-0001-2345-6789"
        assert a.affiliation == "MIT"

    async def test_from_dict_openalex(self):
        data = {"display_name": "John Smith", "orcid": "0000-0001"}
        a = Author.from_dict(data)
        assert a.full_name == "John Smith"
        assert a.orcid == "0000-0001"

    async def test_from_dict_generic(self):
        data = {"family_name": "Smith", "given_name": "John"}
        a = Author.from_dict(data)
        assert a.family_name == "Smith"

    async def test_from_dict_string_handled_by_generic(self):
        # When a string is passed inside a dict access path
        data = {"name": "Smith J"}
        a = Author.from_dict(data)
        assert a.full_name == "Smith J"


# ============================================================
# OpenAccessLink
# ============================================================


class TestOpenAccessLink:
    async def test_is_pdf_true(self):
        link = OpenAccessLink(url="https://example.com/paper.pdf")
        assert link.is_pdf is True

    async def test_is_pdf_with_path(self):
        link = OpenAccessLink(url="https://example.com/pdf/12345")
        assert link.is_pdf is True

    async def test_is_pdf_false(self):
        link = OpenAccessLink(url="https://example.com/paper.html")
        assert link.is_pdf is False


# ============================================================
# CitationMetrics
# ============================================================


class TestCitationMetrics:
    async def test_impact_high_percentile(self):
        m = CitationMetrics(nih_percentile=95.0)
        assert m.impact_level == "high"

    async def test_impact_medium_percentile(self):
        m = CitationMetrics(nih_percentile=60.0)
        assert m.impact_level == "medium"

    async def test_impact_low_percentile(self):
        m = CitationMetrics(nih_percentile=30.0)
        assert m.impact_level == "low"

    async def test_impact_high_rcr(self):
        m = CitationMetrics(relative_citation_ratio=3.0)
        assert m.impact_level == "high"

    async def test_impact_medium_rcr(self):
        m = CitationMetrics(relative_citation_ratio=1.0)
        assert m.impact_level == "medium"

    async def test_impact_low_rcr(self):
        m = CitationMetrics(relative_citation_ratio=0.2)
        assert m.impact_level == "low"

    async def test_impact_high_citation_count(self):
        m = CitationMetrics(citation_count=200)
        assert m.impact_level == "high"

    async def test_impact_medium_citation_count(self):
        m = CitationMetrics(citation_count=50)
        assert m.impact_level == "medium"

    async def test_impact_low_citation_count(self):
        m = CitationMetrics(citation_count=5)
        assert m.impact_level == "low"

    async def test_impact_unknown(self):
        m = CitationMetrics()
        assert m.impact_level == "unknown"


# ============================================================
# UnifiedArticle — Properties
# ============================================================


class TestUnifiedArticleProperties:
    async def test_best_identifier_pmid(self):
        a = UnifiedArticle(title="T", primary_source="pubmed", pmid="12345")
        assert "PMID:12345" in a.best_identifier

    async def test_best_identifier_doi(self):
        a = UnifiedArticle(title="T", primary_source="crossref", doi="10.1/x")
        assert "DOI:10.1/x" in a.best_identifier

    async def test_best_identifier_pmc(self):
        a = UnifiedArticle(title="T", primary_source="pubmed", pmc="PMC123")
        assert "PMC" in a.best_identifier

    async def test_best_identifier_openalex(self):
        a = UnifiedArticle(title="T", primary_source="openalex", openalex_id="W123")
        assert "OpenAlex" in a.best_identifier

    async def test_best_identifier_s2(self):
        a = UnifiedArticle(title="T", primary_source="s2", s2_id="abc12345" * 5)
        assert "S2:" in a.best_identifier

    async def test_best_identifier_title_fallback(self):
        a = UnifiedArticle(title="My Research Paper", primary_source="other")
        assert "Title:" in a.best_identifier

    async def test_has_open_access_true_flag(self):
        a = UnifiedArticle(title="T", primary_source="p", is_open_access=True)
        assert a.has_open_access is True

    async def test_has_open_access_gold(self):
        a = UnifiedArticle(title="T", primary_source="p", oa_status=OpenAccessStatus.GOLD)
        assert a.has_open_access is True

    async def test_has_open_access_links(self):
        a = UnifiedArticle(
            title="T",
            primary_source="p",
            oa_links=[OpenAccessLink(url="https://x.com/1.pdf")],
        )
        assert a.has_open_access is True

    async def test_has_open_access_false(self):
        a = UnifiedArticle(title="T", primary_source="p")
        assert a.has_open_access is False

    async def test_best_oa_link_none(self):
        a = UnifiedArticle(title="T", primary_source="p")
        assert a.best_oa_link is None

    async def test_best_oa_link_is_best(self):
        link1 = OpenAccessLink(url="https://a.com")
        link2 = OpenAccessLink(url="https://b.com", is_best=True)
        a = UnifiedArticle(title="T", primary_source="p", oa_links=[link1, link2])
        assert a.best_oa_link.url == "https://b.com"

    async def test_best_oa_link_published_version(self):
        link1 = OpenAccessLink(url="https://a.com", version="acceptedVersion")
        link2 = OpenAccessLink(url="https://b.com", version="publishedVersion")
        a = UnifiedArticle(title="T", primary_source="p", oa_links=[link1, link2])
        assert a.best_oa_link.url == "https://b.com"

    async def test_best_oa_link_first_fallback(self):
        link = OpenAccessLink(url="https://a.com")
        a = UnifiedArticle(title="T", primary_source="p", oa_links=[link])
        assert a.best_oa_link.url == "https://a.com"

    async def test_author_string(self):
        a = UnifiedArticle(
            title="T",
            primary_source="p",
            authors=[Author(full_name="Smith J"), Author(full_name="Doe A")],
        )
        assert "Smith J" in a.author_string

    async def test_author_string_et_al(self):
        authors = [Author(full_name=f"Author{i}") for i in range(5)]
        a = UnifiedArticle(title="T", primary_source="p", authors=authors)
        assert "et al." in a.author_string

    async def test_author_string_unknown(self):
        a = UnifiedArticle(title="T", primary_source="p")
        assert a.author_string == "Unknown"

    async def test_pubmed_url(self):
        a = UnifiedArticle(title="T", primary_source="p", pmid="12345")
        assert "12345" in a.pubmed_url

    async def test_pubmed_url_none(self):
        a = UnifiedArticle(title="T", primary_source="p")
        assert a.pubmed_url is None

    async def test_doi_url(self):
        a = UnifiedArticle(title="T", primary_source="p", doi="10.1/x")
        assert "doi.org/10.1/x" in a.doi_url

    async def test_doi_url_none(self):
        a = UnifiedArticle(title="T", primary_source="p")
        assert a.doi_url is None

    async def test_pmc_url(self):
        a = UnifiedArticle(title="T", primary_source="p", pmc="PMC12345")
        assert "PMC12345" in a.pmc_url

    async def test_pmc_url_none(self):
        a = UnifiedArticle(title="T", primary_source="p")
        assert a.pmc_url is None


# ============================================================
# UnifiedArticle — Citation Formatting
# ============================================================


class TestCiteVancouver:
    async def test_full_citation(self):
        a = UnifiedArticle(
            title="Machine Learning in Healthcare",
            primary_source="pubmed",
            authors=[Author(full_name="Smith J"), Author(full_name="Doe A")],
            journal="JAMA",
            journal_abbrev="JAMA",
            year=2024,
            volume="331",
            issue="2",
            pages="123-130",
            doi="10.1000/example",
        )
        cite = a.cite_vancouver()
        assert "Smith J" in cite
        assert "JAMA" in cite
        assert "2024" in cite
        assert "10.1000/example" in cite

    async def test_minimal_citation(self):
        a = UnifiedArticle(title="Paper", primary_source="other")
        cite = a.cite_vancouver()
        assert "Paper" in cite


class TestCiteApa:
    async def test_full_apa(self):
        a = UnifiedArticle(
            title="Test Paper",
            primary_source="pubmed",
            authors=[
                Author(given_name="John", family_name="Smith"),
                Author(given_name="Anna", family_name="Doe"),
            ],
            year=2024,
            journal="Nature",
            volume="12",
            doi="10.1/x",
        )
        cite = a.cite_apa()
        assert "Smith, J." in cite
        assert "(2024)" in cite
        assert "doi.org" in cite

    async def test_apa_no_year(self):
        a = UnifiedArticle(title="T", primary_source="p")
        cite = a.cite_apa()
        assert "(n.d.)" in cite

    async def test_apa_many_authors(self):
        authors = [Author(given_name=f"Author{i}", family_name=f"Last{i}") for i in range(10)]
        a = UnifiedArticle(title="T", primary_source="p", authors=authors, year=2024)
        cite = a.cite_apa()
        assert "..." in cite  # APA truncates after 7

    async def test_apa_three_authors(self):
        authors = [
            Author(given_name="A", family_name="X"),
            Author(given_name="B", family_name="Y"),
            Author(given_name="C", family_name="Z"),
        ]
        a = UnifiedArticle(title="T", primary_source="p", authors=authors, year=2024)
        cite = a.cite_apa()
        assert ", &" in cite  # Oxford comma


# ============================================================
# UnifiedArticle — Factory Methods
# ============================================================


class TestFromPubmed:
    async def test_basic(self):
        data = {
            "pmid": "12345",
            "title": "Test Paper",
            "authors": ["Smith J", "Doe A"],
            "journal": "JAMA",
            "year": "2024",
            "doi": "10.1/x",
            "pmc": "PMC999",
            "abstract": "An abstract",
        }
        a = UnifiedArticle.from_pubmed(data)
        assert a.pmid == "12345"
        assert a.primary_source == "pubmed"
        assert len(a.authors) == 2
        assert a.has_open_access  # PMC = green OA

    async def test_article_type_parsing(self):
        data = {
            "title": "T",
            "article_type": ["Randomized Controlled Trial", "Journal Article"],
        }
        a = UnifiedArticle.from_pubmed(data)
        assert a.article_type == ArticleType.RANDOMIZED_CONTROLLED_TRIAL

    async def test_date_parsing_year_string(self):
        data = {"title": "T", "pub_date": "2024 Jan 15"}
        a = UnifiedArticle.from_pubmed(data)
        assert a.year == 2024

    async def test_dict_authors(self):
        data = {"title": "T", "authors": [{"family": "Smith", "given": "John"}]}
        a = UnifiedArticle.from_pubmed(data)
        assert a.authors[0].family_name == "Smith"


class TestFromCrossref:
    async def test_basic(self):
        data = {
            "DOI": "10.1/x",
            "title": ["CrossRef Paper"],
            "author": [{"family": "Smith", "given": "J"}],
            "published": {"date-parts": [[2024, 1, 15]]},
            "container-title": ["Nature"],
            "short-container-title": ["Nat."],
            "type": "journal-article",
            "is-referenced-by-count": 50,
            "volume": "1",
            "page": "100-110",
        }
        a = UnifiedArticle.from_crossref(data)
        assert a.doi == "10.1/x"
        assert a.year == 2024
        assert a.publication_date == date(2024, 1, 15)
        assert a.article_type == ArticleType.JOURNAL_ARTICLE
        assert a.citation_metrics.citation_count == 50

    async def test_title_string(self):
        data = {"title": "Simple Title", "DOI": "10.1/y"}
        a = UnifiedArticle.from_crossref(data)
        assert a.title == "Simple Title"

    async def test_pmc_from_alt_id(self):
        data = {"title": ["T"], "alternative-id": ["PMC12345"]}
        a = UnifiedArticle.from_crossref(data)
        assert a.pmc == "PMC12345"

    async def test_oa_links_from_crossref(self):
        data = {
            "title": ["T"],
            "link": [
                {
                    "URL": "https://x.com/1.pdf",
                    "content-type": "application/pdf",
                    "intended-application": "publisher",
                }
            ],
        }
        a = UnifiedArticle.from_crossref(data)
        assert len(a.oa_links) == 1


class TestFromOpenalex:
    async def test_basic(self):
        data = {
            "id": "https://openalex.org/W123",
            "title": "OA Paper",
            "doi": "https://doi.org/10.1/x",
            "publication_year": 2024,
            "publication_date": "2024-01-15",
            "authorships": [{"author": {"display_name": "Smith J"}}],
            "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/12345/"},
            "open_access": {
                "is_oa": True,
                "oa_url": "https://oa.com",
                "oa_status": "gold",
            },
            "cited_by_count": 100,
            "primary_location": {"source": {"display_name": "Nature"}},
        }
        a = UnifiedArticle.from_openalex(data)
        assert a.openalex_id == "W123"
        assert a.doi == "10.1/x"
        assert a.pmid == "12345"
        assert a.is_open_access is True
        assert a.oa_status == OpenAccessStatus.GOLD
        assert a.journal == "Nature"

    async def test_no_location(self):
        data = {"title": "T", "id": "https://openalex.org/W1"}
        a = UnifiedArticle.from_openalex(data)
        assert a.journal is None

    async def test_article_type_mapping(self):
        """OpenAlex 'type' field should map to ArticleType."""
        # Journal article
        data = {"title": "T", "id": "https://openalex.org/W1", "type": "article"}
        a = UnifiedArticle.from_openalex(data)
        assert a.article_type == ArticleType.JOURNAL_ARTICLE

        # Preprint
        data = {"title": "T", "id": "https://openalex.org/W2", "type": "preprint"}
        a = UnifiedArticle.from_openalex(data)
        assert a.article_type == ArticleType.PREPRINT

        # Review
        data = {"title": "T", "id": "https://openalex.org/W3", "type": "review"}
        a = UnifiedArticle.from_openalex(data)
        assert a.article_type == ArticleType.REVIEW

        # Book chapter
        data = {"title": "T", "id": "https://openalex.org/W4", "type": "book-chapter"}
        a = UnifiedArticle.from_openalex(data)
        assert a.article_type == ArticleType.BOOK_CHAPTER

        # Unknown type defaults to UNKNOWN
        data = {"title": "T", "id": "https://openalex.org/W5", "type": "some-new-type"}
        a = UnifiedArticle.from_openalex(data)
        assert a.article_type == ArticleType.UNKNOWN

        # Missing type defaults to UNKNOWN
        data = {"title": "T", "id": "https://openalex.org/W6"}
        a = UnifiedArticle.from_openalex(data)
        assert a.article_type == ArticleType.UNKNOWN


class TestFromSemanticScholar:
    async def test_basic(self):
        data = {
            "paperId": "abc123",
            "title": "S2 Paper",
            "authors": [{"name": "Smith J"}],
            "externalIds": {"DOI": "10.1/x", "PubMed": "12345", "PubMedCentral": "999"},
            "venue": "Nature",
            "year": 2024,
            "citationCount": 50,
            "influentialCitationCount": 5,
            "isOpenAccess": True,
            "openAccessPdf": {"url": "https://oa.com/pdf"},
        }
        a = UnifiedArticle.from_semantic_scholar(data)
        assert a.s2_id == "abc123"
        assert a.pmid == "12345"
        assert a.pmc == "PMC999"
        assert a.citation_metrics.influential_citation_count == 5

    async def test_preprint_detection_arxiv_no_pmid(self):
        """ArXiv paper without PubMed ID should be detected as preprint."""
        data = {
            "paperId": "abc",
            "title": "ArXiv Paper",
            "authors": [],
            "externalIds": {"ArXiv": "2301.12345"},
            "year": 2023,
        }
        a = UnifiedArticle.from_semantic_scholar(data)
        assert a.article_type == ArticleType.PREPRINT
        assert a.arxiv_id == "2301.12345"

    async def test_arxiv_with_pmid_not_preprint(self):
        """ArXiv paper that also has PubMed ID is published, not preprint."""
        data = {
            "paperId": "abc",
            "title": "Published Paper",
            "authors": [],
            "externalIds": {"ArXiv": "2301.12345", "PubMed": "12345"},
            "year": 2023,
        }
        a = UnifiedArticle.from_semantic_scholar(data)
        # Has PMID → not a preprint (venue detection or fallback)
        assert a.article_type != ArticleType.PREPRINT

    async def test_venue_type_journal(self):
        """S2 publicationVenue.type='journal' should map to JOURNAL_ARTICLE."""
        data = {
            "paperId": "abc",
            "title": "Journal Paper",
            "authors": [],
            "externalIds": {},
            "publicationVenue": {"type": "journal"},
            "year": 2023,
        }
        a = UnifiedArticle.from_semantic_scholar(data)
        assert a.article_type == ArticleType.JOURNAL_ARTICLE

    async def test_venue_type_conference(self):
        """S2 publicationVenue.type='conference' should map to CONFERENCE_PAPER."""
        data = {
            "paperId": "abc",
            "title": "Conf Paper",
            "authors": [],
            "externalIds": {},
            "publicationVenue": {"type": "conference"},
            "year": 2023,
        }
        a = UnifiedArticle.from_semantic_scholar(data)
        assert a.article_type == ArticleType.CONFERENCE_PAPER


# ============================================================
# UnifiedArticle — merge_from
# ============================================================


class TestMergeFrom:
    async def test_fills_missing_identifiers(self):
        a = UnifiedArticle(title="T", primary_source="pubmed", pmid="12345")
        b = UnifiedArticle(title="T", primary_source="crossref", doi="10.1/x", pmc="PMC999")
        a.merge_from(b)
        assert a.doi == "10.1/x"
        assert a.pmc == "PMC999"

    async def test_does_not_overwrite_existing(self):
        a = UnifiedArticle(title="T", primary_source="pubmed", pmid="12345", doi="10.1/orig")
        b = UnifiedArticle(title="T", primary_source="crossref", doi="10.1/other")
        a.merge_from(b)
        assert a.doi == "10.1/orig"

    async def test_merges_authors_if_empty(self):
        a = UnifiedArticle(title="T", primary_source="pubmed")
        b = UnifiedArticle(title="T", primary_source="crossref", authors=[Author(full_name="Smith")])
        a.merge_from(b)
        assert len(a.authors) == 1

    async def test_keeps_existing_authors(self):
        a = UnifiedArticle(title="T", primary_source="pubmed", authors=[Author(full_name="Doe")])
        b = UnifiedArticle(title="T", primary_source="crossref", authors=[Author(full_name="Smith")])
        a.merge_from(b)
        assert len(a.authors) == 1
        assert a.authors[0].full_name == "Doe"

    async def test_merges_keywords(self):
        a = UnifiedArticle(title="T", primary_source="pubmed", keywords=["A"])
        b = UnifiedArticle(title="T", primary_source="crossref", keywords=["A", "B"])
        a.merge_from(b)
        assert set(a.keywords) == {"A", "B"}

    async def test_merges_oa_links_deduped(self):
        link = OpenAccessLink(url="https://x.com/1.pdf")
        a = UnifiedArticle(title="T", primary_source="p", oa_links=[link])
        b = UnifiedArticle(
            title="T",
            primary_source="p",
            oa_links=[link, OpenAccessLink(url="https://y.com/2.pdf")],
        )
        a.merge_from(b)
        assert len(a.oa_links) == 2

    async def test_merges_citation_metrics(self):
        a = UnifiedArticle(
            title="T",
            primary_source="p",
            citation_metrics=CitationMetrics(citation_count=10),
        )
        b = UnifiedArticle(
            title="T",
            primary_source="p",
            citation_metrics=CitationMetrics(citation_count=50, nih_percentile=80.0),
        )
        a.merge_from(b)
        assert a.citation_metrics.citation_count == 50  # Higher wins
        assert a.citation_metrics.nih_percentile == 80.0

    async def test_fills_citation_metrics_from_none(self):
        a = UnifiedArticle(title="T", primary_source="p")
        b = UnifiedArticle(
            title="T",
            primary_source="p",
            citation_metrics=CitationMetrics(citation_count=10),
        )
        a.merge_from(b)
        assert a.citation_metrics.citation_count == 10

    async def test_tracks_sources(self):
        a = UnifiedArticle(
            title="T",
            primary_source="pubmed",
            sources=[SourceMetadata(source="pubmed")],
        )
        b = UnifiedArticle(
            title="T",
            primary_source="crossref",
            sources=[SourceMetadata(source="crossref")],
        )
        a.merge_from(b)
        source_names = [s.source for s in a.sources]
        assert "pubmed" in source_names
        assert "crossref" in source_names

    async def test_updates_article_type(self):
        a = UnifiedArticle(title="T", primary_source="p", article_type=ArticleType.UNKNOWN)
        b = UnifiedArticle(title="T", primary_source="p", article_type=ArticleType.REVIEW)
        a.merge_from(b)
        assert a.article_type == ArticleType.REVIEW


# ============================================================
# UnifiedArticle — to_dict
# ============================================================


class TestToDict:
    async def test_basic_structure(self):
        a = UnifiedArticle(title="T", primary_source="pubmed", pmid="12345")
        d = a.to_dict()
        assert d["title"] == "T"
        assert d["identifiers"]["pmid"] == "12345"
        assert "open_access" in d

    async def test_with_citation_metrics(self):
        a = UnifiedArticle(
            title="T",
            primary_source="p",
            citation_metrics=CitationMetrics(citation_count=50),
        )
        d = a.to_dict()
        assert d["citation_metrics"]["citation_count"] == 50

    async def test_with_ranking_score(self):
        a = UnifiedArticle(title="T", primary_source="p")
        a.ranking_score = 0.85
        d = a.to_dict()
        assert d["_ranking_score"] == 0.85

    async def test_with_similarity(self):
        a = UnifiedArticle(title="T", primary_source="p", similarity_score=0.95, similarity_source="s2")
        d = a.to_dict()
        assert d["similarity"]["score"] == 0.95


# ============================================================
# UnifiedArticle — matches_identifier
# ============================================================


class TestMatchesIdentifier:
    async def test_doi_match(self):
        a = UnifiedArticle(title="T", primary_source="p", doi="10.1/x")
        b = UnifiedArticle(title="T", primary_source="p", doi="10.1/x")
        assert a.matches_identifier(b)

    async def test_doi_normalized(self):
        a = UnifiedArticle(title="T", primary_source="p", doi="10.1/X")
        b = UnifiedArticle(title="T", primary_source="p", doi="https://doi.org/10.1/x")
        assert a.matches_identifier(b)

    async def test_pmid_match(self):
        a = UnifiedArticle(title="T", primary_source="p", pmid="12345")
        b = UnifiedArticle(title="T", primary_source="p", pmid="12345")
        assert a.matches_identifier(b)

    async def test_no_match(self):
        a = UnifiedArticle(title="T1", primary_source="p")
        b = UnifiedArticle(title="T2", primary_source="p")
        assert a.matches_identifier(b) is False

    async def test_pmc_match(self):
        a = UnifiedArticle(title="T", primary_source="p", pmc="PMC123")
        b = UnifiedArticle(title="T", primary_source="p", pmc="123")
        assert a.matches_identifier(b)

    async def test_s2_match(self):
        a = UnifiedArticle(title="T", primary_source="p", s2_id="ABC123")
        b = UnifiedArticle(title="T", primary_source="p", s2_id="abc123")
        assert a.matches_identifier(b)
