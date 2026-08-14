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


def _openalex_abstract(data: dict[str, Any]) -> str | None:
    """Reconstruct OpenAlex's root-level inverted-index abstract."""

    abstract = data.get("abstract")
    if isinstance(abstract, str) and abstract:
        return abstract

    inverted_index = data.get("abstract_inverted_index")
    if not isinstance(inverted_index, dict):
        return None

    positioned_words: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        positioned_words.extend((position, word) for position in positions if isinstance(position, int))
    positioned_words.sort(key=lambda item: item[0])
    return " ".join(word for _, word in positioned_words) or None


def _normalize_pmc_identifier(value: object) -> str | None:
    """Return a stable ``PMC...`` identifier from provider URL or ID forms."""

    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().rstrip("/")
    marker = normalized.upper().rfind("PMC")
    if marker >= 0:
        suffix = normalized[marker + 3 :]
        return f"PMC{suffix}" if suffix else None
    return f"PMC{normalized}"


def article_from_openalex(data: dict[str, Any]) -> UnifiedArticle:
    """Create UnifiedArticle from OpenAlex work metadata."""
    authors = []
    for authorship in data.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") or {}
        if not isinstance(author, dict):
            continue
        authors.append(Author(full_name=author.get("display_name"), orcid=author.get("orcid")))

    year = data.get("publication_year")
    pub_date = None
    if data.get("publication_date"):
        with contextlib.suppress(ValueError):
            pub_date = date.fromisoformat(data["publication_date"])

    doi = None
    pmid = None
    pmc = None
    ids = data.get("ids") or {}
    doi_value = data.get("doi") or ids.get("doi")
    if isinstance(doi_value, str):
        doi = doi_value.replace("https://doi.org/", "")
    if ids.get("pmid"):
        pmid = ids["pmid"].replace("https://pubmed.ncbi.nlm.nih.gov/", "").rstrip("/")
    if ids.get("pmcid"):
        pmc = _normalize_pmc_identifier(ids["pmcid"])

    open_access = data.get("open_access") or {}
    best_oa_location = data.get("best_oa_location") or {}
    is_oa = open_access.get("is_oa", False)
    oa_url = open_access.get("oa_url") or best_oa_location.get("landing_page_url") or best_oa_location.get("pdf_url")
    oa_status_str = open_access.get("oa_status", "unknown")
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
        raw_license = best_oa_location.get("license")
        oa_links.append(
            OpenAccessLink(
                url=oa_url,
                license=raw_license if isinstance(raw_license, str) else None,
                is_best=True,
            )
        )

    journal = None
    location = data.get("primary_location") or {}
    source = location.get("source") or {}
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
        abstract=_openalex_abstract(data),
        journal=journal,
        year=year,
        publication_date=pub_date,
        article_type=article_type,
        is_open_access=is_oa,
        oa_status=oa_status,
        oa_links=oa_links,
        citation_metrics=CitationMetrics(citation_count=data.get("cited_by_count"))
        if data.get("cited_by_count")
        else None,
        sources=[SourceMetadata(source="openalex", raw_data=data)],
    )


def article_from_semantic_scholar(data: dict[str, Any]) -> UnifiedArticle:
    """Create UnifiedArticle from Semantic Scholar paper metadata."""
    authors = [Author(full_name=author.get("name")) for author in data.get("authors") or [] if isinstance(author, dict)]

    external_ids = data.get("externalIds") or {}
    doi = external_ids.get("DOI")
    pmid = external_ids.get("PubMed")
    pmc = _normalize_pmc_identifier(external_ids.get("PubMedCentral"))
    arxiv = external_ids.get("ArXiv")

    is_oa = data.get("isOpenAccess", False)
    oa_links: list[OpenAccessLink] = []
    open_access_pdf = data.get("openAccessPdf") or {}
    if open_access_pdf.get("url"):
        raw_license = open_access_pdf.get("license")
        oa_links.append(
            OpenAccessLink(
                url=open_access_pdf["url"],
                license=raw_license if isinstance(raw_license, str) else None,
                is_best=True,
            )
        )

    article_type = ArticleType.UNKNOWN
    publication_venue = data.get("publicationVenue") or {}
    venue_type = publication_venue.get("type", "").lower() if isinstance(publication_venue, dict) else ""
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
        pmc=pmc,
        arxiv_id=arxiv,
        authors=authors,
        abstract=data.get("abstract"),
        journal=(publication_venue.get("name") if isinstance(publication_venue, dict) else None) or data.get("venue"),
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
        citation_metrics=CitationMetrics(citation_count=data.get("citation_count"))
        if data.get("citation_count")
        else None,
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
        citation_metrics=CitationMetrics(citation_count=data.get("cited_by_count"))
        if data.get("cited_by_count")
        else None,
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
        citation_metrics=CitationMetrics(citation_count=data.get("cited_by_count"))
        if data.get("cited_by_count")
        else None,
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


def article_from_preprint(data: dict[str, Any]) -> UnifiedArticle:
    """Create UnifiedArticle from a preprint server payload.

    Accepts the dict produced by ``PreprintArticle.to_dict()`` (arXiv / medRxiv /
    bioRxiv). The ``source`` field on the payload selects the journal label and
    the primary_source attribution. arXiv IDs are stored on ``arxiv_id`` so that
    aggregation can dedupe by identifier where possible.
    """
    source_key = (data.get("source") or "preprint").lower()
    journal_map = {
        "arxiv": "arXiv (preprint)",
        "medrxiv": "medRxiv (preprint)",
        "biorxiv": "bioRxiv (preprint)",
    }
    journal_label = journal_map.get(source_key, "Preprint Server")

    authors = [Author(full_name=name) for name in data.get("authors", []) if name]

    year: int | None = None
    pub_date: date | None = None
    published = data.get("published") or ""
    if published:
        with contextlib.suppress(ValueError, TypeError):
            parts = published.split("-")
            year = int(parts[0])
            if len(parts) >= _DATE_PARTS_FULL:
                pub_date = date(int(parts[0]), int(parts[1]), int(parts[2]))

    arxiv_id = data.get("id") if source_key == "arxiv" else None
    doi = data.get("doi")

    landing_url = data.get("source_url") or ""
    pdf_url = data.get("pdf_url") or ""
    oa_links: list[OpenAccessLink] = []
    if pdf_url:
        oa_links.append(
            OpenAccessLink(
                url=pdf_url,
                version="submittedVersion",
                host_type="preprint",
                is_best=True,
            )
        )
    if landing_url and landing_url != pdf_url:
        oa_links.append(
            OpenAccessLink(
                url=landing_url,
                version="submittedVersion",
                host_type="preprint",
            )
        )

    return UnifiedArticle(
        title=data.get("title", "Unknown Title"),
        primary_source=source_key,
        doi=doi,
        arxiv_id=arxiv_id,
        authors=authors,
        abstract=data.get("abstract"),
        journal=journal_label,
        year=year,
        publication_date=pub_date,
        article_type=ArticleType.PREPRINT,
        keywords=data.get("categories", []),
        oa_status=OpenAccessStatus.GREEN,
        oa_links=oa_links,
        is_open_access=True,
        sources=[SourceMetadata(source=source_key, raw_data=data)],
    )


__all__ = [
    "article_from_core",
    "article_from_crossref",
    "article_from_europe_pmc",
    "article_from_openalex",
    "article_from_preprint",
    "article_from_pubmed",
    "article_from_scopus",
    "article_from_semantic_scholar",
    "article_from_web_of_science",
]
