"""Mapping helpers from source-specific payloads to UnifiedArticle.

Design:
    This module isolates normalization of heterogeneous provider payloads into
    the shared UnifiedArticle entity. Each mapper should translate source quirks
    without leaking provider-specific shapes into the rest of the application.

Maintenance:
    When a source schema changes, update only its mapper function and preserve
    the normalized entity contract. Avoid adding network calls or persistence
    logic here so the mapping layer stays deterministic and easy to test.
"""

from __future__ import annotations

import contextlib
from datetime import date
from typing import Any

from pubmed_search.domain.entities.article import (
    _DATE_PARTS_FULL,
    ArticleType,
    Author,
    CitationMetrics,
    OpenAccessLink,
    OpenAccessStatus,
    SourceMetadata,
    UnifiedArticle,
    _parse_pubmed_date,
)


def article_from_pubmed(data: dict[str, Any]) -> UnifiedArticle:
    """Create UnifiedArticle from PubMed search/detail data."""
    authors: list[Author] = []
    if "authors" in data:
        for author_str in data["authors"]:
            if isinstance(author_str, str):
                authors.append(Author(full_name=author_str))
            elif isinstance(author_str, dict):
                authors.append(Author.from_dict(author_str))

    pub_date = None
    year = None
    if data.get("pub_date"):
        year, pub_date = _parse_pubmed_date(data["pub_date"])
    if not year and data.get("year"):
        year = int(data["year"])

    article_type = ArticleType.UNKNOWN
    if data.get("article_type"):
        type_map = {
            "Journal Article": ArticleType.JOURNAL_ARTICLE,
            "Review": ArticleType.REVIEW,
            "Meta-Analysis": ArticleType.META_ANALYSIS,
            "Systematic Review": ArticleType.SYSTEMATIC_REVIEW,
            "Clinical Trial": ArticleType.CLINICAL_TRIAL,
            "Randomized Controlled Trial": ArticleType.RANDOMIZED_CONTROLLED_TRIAL,
            "Case Reports": ArticleType.CASE_REPORT,
            "Letter": ArticleType.LETTER,
            "Editorial": ArticleType.EDITORIAL,
            "Comment": ArticleType.COMMENT,
        }
        for pub_type in data.get("article_type", []):
            if pub_type in type_map:
                article_type = type_map[pub_type]
                break

    oa_status = OpenAccessStatus.UNKNOWN
    oa_links: list[OpenAccessLink] = []
    is_oa = False
    if data.get("pmc"):
        is_oa = True
        oa_status = OpenAccessStatus.GREEN
        pmc_id = data["pmc"].replace("PMC", "")
        oa_links.append(
            OpenAccessLink(
                url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id}/",
                version="publishedVersion",
                host_type="repository",
                is_best=True,
            )
        )

    return UnifiedArticle(
        title=data.get("title", "Unknown Title"),
        primary_source="pubmed",
        pmid=data.get("pmid") or data.get("uid"),
        doi=data.get("doi"),
        pmc=data.get("pmc"),
        authors=authors,
        abstract=data.get("abstract"),
        journal=data.get("journal") or data.get("fulljournalname"),
        journal_abbrev=data.get("source"),
        volume=data.get("volume"),
        issue=data.get("issue"),
        pages=data.get("pages"),
        year=year,
        publication_date=pub_date,
        article_type=article_type,
        language=data.get("language"),
        keywords=data.get("keywords", []),
        mesh_terms=data.get("mesh_terms", []),
        oa_status=oa_status,
        oa_links=oa_links,
        is_open_access=is_oa,
        sources=[SourceMetadata(source="pubmed", raw_data=data)],
    )


def article_from_crossref(data: dict[str, Any]) -> UnifiedArticle:
    """Create UnifiedArticle from CrossRef work metadata."""
    authors = [Author.from_dict(author_data) for author_data in data.get("author", [])]

    year = None
    pub_date = None
    date_parts = data.get("published", {}).get("date-parts", [[]])
    if date_parts and date_parts[0]:
        parts = date_parts[0]
        if len(parts) >= 1:
            year = parts[0]
        if len(parts) >= _DATE_PARTS_FULL:
            with contextlib.suppress(ValueError, TypeError):
                pub_date = date(parts[0], parts[1], parts[2])

    cr_type = data.get("type", "").lower()
    type_map = {
        "journal-article": ArticleType.JOURNAL_ARTICLE,
        "posted-content": ArticleType.PREPRINT,
        "book-chapter": ArticleType.BOOK_CHAPTER,
        "proceedings-article": ArticleType.CONFERENCE_PAPER,
        "dissertation": ArticleType.THESIS,
        "dataset": ArticleType.DATASET,
    }
    article_type = type_map.get(cr_type, ArticleType.UNKNOWN)

    journal = None
    journal_abbrev = None
    container = data.get("container-title", [])
    if container:
        journal = container[0]
    short_container = data.get("short-container-title", [])
    if short_container:
        journal_abbrev = short_container[0]

    pmc = None
    for alt_id in data.get("alternative-id", []):
        if str(alt_id).startswith("PMC"):
            pmc = alt_id
            break

    oa_links: list[OpenAccessLink] = []
    for link in data.get("link", []):
        if link.get("content-type") == "application/pdf":
            oa_links.append(
                OpenAccessLink(
                    url=link["URL"],
                    version="publishedVersion" if "publisher" in link.get("intended-application", "") else "unknown",
                    host_type="publisher",
                )
            )

    return UnifiedArticle(
        title=data.get("title", ["Unknown Title"])[0]
        if isinstance(data.get("title"), list)
        else data.get("title", "Unknown Title"),
        primary_source="crossref",
        doi=data.get("DOI"),
        pmc=pmc,
        authors=authors,
        abstract=data.get("abstract"),
        journal=journal,
        journal_abbrev=journal_abbrev,
        volume=data.get("volume"),
        issue=data.get("issue"),
        pages=data.get("page"),
        year=year,
        publication_date=pub_date,
        publisher=data.get("publisher"),
        article_type=article_type,
        oa_links=oa_links,
        citation_metrics=CitationMetrics(citation_count=data.get("is-referenced-by-count"))
        if data.get("is-referenced-by-count")
        else None,
        sources=[SourceMetadata(source="crossref", raw_data=data)],
    )


def article_from_openalex(data: dict[str, Any]) -> UnifiedArticle:
    """Create UnifiedArticle from OpenAlex work metadata."""
    authors = [
        Author(
            full_name=authorship.get("author", {}).get("display_name"),
            orcid=authorship.get("author", {}).get("orcid"),
        )
        for authorship in data.get("authorships", [])
    ]

    year = data.get("publication_year")
    pub_date = None
    if data.get("publication_date"):
        with contextlib.suppress(ValueError):
            pub_date = date.fromisoformat(data["publication_date"])

    doi = None
    pmid = None
    pmc = None
    if data.get("doi"):
        doi = data["doi"].replace("https://doi.org/", "")
    ids = data.get("ids", {})
    if ids.get("pmid"):
        pmid = ids["pmid"].replace("https://pubmed.ncbi.nlm.nih.gov/", "").rstrip("/")
    if ids.get("pmcid"):
        pmc = ids["pmcid"].replace("https://www.ncbi.nlm.nih.gov/pmc/articles/", "").rstrip("/")

    is_oa = data.get("open_access", {}).get("is_oa", False)
    oa_url = data.get("open_access", {}).get("oa_url")
    oa_status_str = data.get("open_access", {}).get("oa_status", "unknown")
    oa_status_map = {
        "gold": OpenAccessStatus.GOLD,
        "green": OpenAccessStatus.GREEN,
        "hybrid": OpenAccessStatus.HYBRID,
        "bronze": OpenAccessStatus.BRONZE,
        "closed": OpenAccessStatus.CLOSED,
    }
    oa_status = oa_status_map.get(oa_status_str, OpenAccessStatus.UNKNOWN)

    oa_links: list[OpenAccessLink] = []
    if oa_url:
        oa_links.append(OpenAccessLink(url=oa_url, is_best=True))

    journal = None
    location = data.get("primary_location", {})
    source = location.get("source", {})
    if source:
        journal = source.get("display_name")

    oa_type = data.get("type", "").lower()
    openalex_type_map = {
        "article": ArticleType.JOURNAL_ARTICLE,
        "review": ArticleType.REVIEW,
        "preprint": ArticleType.PREPRINT,
        "book-chapter": ArticleType.BOOK_CHAPTER,
        "proceedings-article": ArticleType.CONFERENCE_PAPER,
        "dissertation": ArticleType.THESIS,
        "dataset": ArticleType.DATASET,
        "editorial": ArticleType.EDITORIAL,
        "letter": ArticleType.LETTER,
        "erratum": ArticleType.OTHER,
        "paratext": ArticleType.OTHER,
        "peer-review": ArticleType.OTHER,
        "reference-entry": ArticleType.OTHER,
    }
    article_type = openalex_type_map.get(oa_type, ArticleType.UNKNOWN)

    return UnifiedArticle(
        title=data.get("title") or data.get("display_name", "Unknown Title"),
        primary_source="openalex",
        openalex_id=data.get("id", "").replace("https://openalex.org/", ""),
        doi=doi,
        pmid=pmid,
        pmc=pmc,
        authors=authors,
        abstract=data.get("abstract"),
        journal=journal,
        year=year,
        publication_date=pub_date,
        article_type=article_type,
        is_open_access=is_oa,
        oa_status=oa_status,
        oa_links=oa_links,
        citation_metrics=CitationMetrics(citation_count=data.get("cited_by_count")) if data.get("cited_by_count") else None,
        sources=[SourceMetadata(source="openalex", raw_data=data)],
    )


def article_from_semantic_scholar(data: dict[str, Any]) -> UnifiedArticle:
    """Create UnifiedArticle from Semantic Scholar paper metadata."""
    authors = [Author(full_name=author.get("name")) for author in data.get("authors", [])]

    doi = data.get("externalIds", {}).get("DOI")
    pmid = data.get("externalIds", {}).get("PubMed")
    pmc = data.get("externalIds", {}).get("PubMedCentral")
    arxiv = data.get("externalIds", {}).get("ArXiv")

    is_oa = data.get("isOpenAccess", False)
    oa_links: list[OpenAccessLink] = []
    if data.get("openAccessPdf", {}).get("url"):
        oa_links.append(OpenAccessLink(url=data["openAccessPdf"]["url"], is_best=True))

    article_type = ArticleType.UNKNOWN
    venue_type = (data.get("publicationVenue", {}) or {}).get("type", "").lower()
    if venue_type == "journal":
        article_type = ArticleType.JOURNAL_ARTICLE
    elif venue_type == "conference":
        article_type = ArticleType.CONFERENCE_PAPER
    elif arxiv and not pmid:
        article_type = ArticleType.PREPRINT

    return UnifiedArticle(
        title=data.get("title", "Unknown Title"),
        primary_source="semantic_scholar",
        s2_id=data.get("paperId"),
        doi=doi,
        pmid=pmid,
        pmc=f"PMC{pmc}" if pmc else None,
        arxiv_id=arxiv,
        authors=authors,
        abstract=data.get("abstract"),
        journal=data.get("venue"),
        year=data.get("year"),
        article_type=article_type,
        is_open_access=is_oa,
        oa_links=oa_links,
        citation_metrics=CitationMetrics(
            citation_count=data.get("citationCount"),
            influential_citation_count=data.get("influentialCitationCount"),
        )
        if data.get("citationCount")
        else None,
        sources=[SourceMetadata(source="semantic_scholar", raw_data=data)],
    )


def article_from_core(data: dict[str, Any]) -> UnifiedArticle:
    """Create UnifiedArticle from CORE normalized response."""
    authors: list[Author] = []
    for author in data.get("authors", []):
        if isinstance(author, str):
            authors.append(Author(full_name=author))
        elif isinstance(author, dict):
            authors.append(Author(full_name=author.get("name", "")))

    oa_links: list[OpenAccessLink] = []
    for url_key in ("download_url", "pdf_url", "reader_url"):
        url = data.get(url_key)
        if url:
            oa_links.append(OpenAccessLink(url=url, is_best=(url_key == "download_url")))

    return UnifiedArticle(
        title=data.get("title") or "Unknown Title",
        primary_source="core",
        core_id=str(data["core_id"]) if data.get("core_id") else None,
        doi=data.get("doi"),
        pmid=data.get("pmid"),
        arxiv_id=data.get("arxiv_id"),
        authors=authors,
        abstract=data.get("abstract"),
        journal=data.get("journal"),
        year=data.get("year"),
        publisher=data.get("publisher"),
        language=data.get("language"),
        is_open_access=bool(data.get("has_fulltext") or data.get("download_url")),
        oa_links=oa_links,
        citation_metrics=CitationMetrics(citation_count=data.get("citation_count")) if data.get("citation_count") else None,
        sources=[SourceMetadata(source="core", raw_data=data)],
    )


def article_from_scopus(data: dict[str, Any]) -> UnifiedArticle:
    """Create UnifiedArticle from Scopus normalized response."""
    authors: list[Author] = []
    for author in data.get("authors", []):
        if isinstance(author, str):
            authors.append(Author(full_name=author))
        elif isinstance(author, dict):
            authors.append(Author(full_name=author.get("name", "")))

    oa_links: list[OpenAccessLink] = []
    link = data.get("link")
    if data.get("is_open_access") and link:
        oa_links.append(OpenAccessLink(url=link, is_best=True))

    return UnifiedArticle(
        title=data.get("title") or "Unknown Title",
        primary_source="scopus",
        doi=data.get("doi"),
        authors=authors,
        abstract=data.get("abstract"),
        journal=data.get("journal") or data.get("journal_abbrev"),
        year=data.get("year"),
        is_open_access=bool(data.get("is_open_access")),
        oa_links=oa_links,
        citation_metrics=CitationMetrics(citation_count=data.get("cited_by_count")) if data.get("cited_by_count") else None,
        sources=[SourceMetadata(source="scopus", raw_data=data)],
    )


def article_from_web_of_science(data: dict[str, Any]) -> UnifiedArticle:
    """Create UnifiedArticle from Web of Science normalized response."""
    authors: list[Author] = []
    for author in data.get("authors", []):
        if isinstance(author, str):
            authors.append(Author(full_name=author))
        elif isinstance(author, dict):
            authors.append(Author(full_name=author.get("name", "")))

    oa_links: list[OpenAccessLink] = []
    link = data.get("link")
    if data.get("is_open_access") and link:
        oa_links.append(OpenAccessLink(url=link, is_best=True))

    return UnifiedArticle(
        title=data.get("title") or "Unknown Title",
        primary_source="web_of_science",
        doi=data.get("doi"),
        authors=authors,
        abstract=data.get("abstract"),
        journal=data.get("journal") or data.get("journal_abbrev"),
        year=data.get("year"),
        is_open_access=bool(data.get("is_open_access")),
        oa_links=oa_links,
        citation_metrics=CitationMetrics(citation_count=data.get("cited_by_count")) if data.get("cited_by_count") else None,
        sources=[SourceMetadata(source="web_of_science", raw_data=data)],
    )


def article_from_europe_pmc(data: dict[str, Any]) -> UnifiedArticle:
    """Create UnifiedArticle from Europe PMC normalized response."""
    normalized = dict(data)
    if "pmc_id" in normalized and not normalized.get("pmc"):
        normalized["pmc"] = normalized["pmc_id"]
    if "journal_abbrev" in normalized and not normalized.get("source"):
        normalized["source"] = normalized["journal_abbrev"]
    article = article_from_pubmed(normalized)
    article.primary_source = "europe_pmc"
    article.sources = [SourceMetadata(source="europe_pmc", raw_data=normalized)]
    return article


__all__ = [
    "article_from_core",
    "article_from_crossref",
    "article_from_europe_pmc",
    "article_from_openalex",
    "article_from_pubmed",
    "article_from_scopus",
    "article_from_semantic_scholar",
    "article_from_web_of_science",
]
