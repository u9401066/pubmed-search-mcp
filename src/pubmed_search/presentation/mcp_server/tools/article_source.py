"""Schema-exact article identifier requests shared by MCP tools."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from pubmed_search.domain.value_objects import ArticleIdentifier, normalize_doi, normalize_pmcid, normalize_pmid


class _StrictSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PMIDSource(_StrictSource):
    """An explicit PubMed identifier."""

    kind: Literal["pmid"]
    value: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$", max_length=20)]


class PMCIDSource(_StrictSource):
    """An explicit PubMed Central identifier."""

    kind: Literal["pmcid"]
    value: Annotated[str, Field(pattern=r"^PMC[1-9][0-9]{0,19}$", max_length=23)]


class DOISource(_StrictSource):
    """An explicit DOI."""

    kind: Literal["doi"]
    value: Annotated[str, Field(pattern=r"^10\.[0-9]{4,9}/", min_length=7, max_length=512)]


ArticleSource = Annotated[PMIDSource | PMCIDSource | DOISource, Field(discriminator="kind")]
PubmedSource = Annotated[PMIDSource | PMCIDSource, Field(discriminator="kind")]


def normalize_article_source(source: ArticleSource | PubmedSource) -> ArticleIdentifier:
    """Return one strict domain identifier from a discriminated MCP request."""
    if isinstance(source, PMIDSource):
        return ArticleIdentifier("pmid", normalize_pmid(source.value))
    if isinstance(source, PMCIDSource):
        return ArticleIdentifier("pmcid", normalize_pmcid(source.value))
    return ArticleIdentifier("doi", normalize_doi(source.value))


__all__ = [
    "ArticleSource",
    "DOISource",
    "PMCIDSource",
    "PMIDSource",
    "PubmedSource",
    "normalize_article_source",
]
