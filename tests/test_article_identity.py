"""Edge contracts for deterministic article identity keys."""

from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.shared.article_identity import canonical_article_key


def test_provider_identifier_precedes_title_fallback() -> None:
    article = UnifiedArticle(
        title="",
        primary_source="openalex",
        openalex_id="https://openalex.org/W12345",
    )

    assert canonical_article_key(article) == "openalex:W12345"


def test_titleless_fallback_is_stable_and_uses_available_metadata() -> None:
    first = UnifiedArticle(
        title="",
        primary_source="core",
        journal="Example Journal",
        year=2024,
        abstract="First record",
    )
    equivalent = UnifiedArticle(
        title="",
        primary_source="core",
        journal="Example Journal",
        year=2024,
        abstract="First record",
    )
    different = UnifiedArticle(
        title="",
        primary_source="core",
        journal="Example Journal",
        year=2024,
        abstract="Second record",
    )

    assert canonical_article_key(first) == canonical_article_key(equivalent)
    assert canonical_article_key(first).startswith("fallback:")
    assert canonical_article_key(first) != canonical_article_key(different)
