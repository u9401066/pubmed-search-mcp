"""Official spec-backed source clients.

This module provides small typed adapters generated from the vendors' official
OpenAPI / Swagger definitions for the operations currently used by the repo.

The generated layer intentionally stays thin:
- request and response models are typed with pydantic
- operation metadata points back to official spec URLs
- transport remains delegated to the existing BaseAPIClient wrappers so retry,
  rate limiting, circuit breaker behavior, and httpx lifecycle stay unified
"""

# ruff: noqa: N815

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from pubmed_search.infrastructure.sources.base_client import BaseAPIClient


@dataclass(frozen=True, slots=True)
class OfficialSpecOperation:
    """Describe one operation traced back to an official vendor specification.

    Attributes:
        service: Human-readable service name.
        spec_url: Official downloadable OpenAPI/Swagger document URL.
        operation_id: Operation identifier published by the vendor spec.
        method: HTTP method for the operation.
        path: Relative request path including any vendor base path.
        listing_url: Optional secondary listing URL used by vendor docs.
    """

    service: str
    spec_url: str
    operation_id: str
    method: str
    path: str
    listing_url: str | None = None


SCOPUS_SEARCH_OPERATION = OfficialSpecOperation(
    service="Scopus",
    spec_url="https://dev.elsevier.com/elsdoc/scopus",
    listing_url="https://dev.elsevier.com/elsdoc/listings/Scopus_Search",
    operation_id="ScopusSearch",
    method="GET",
    path="/content/search/scopus",
)

WEB_OF_SCIENCE_SEARCH_OPERATION = OfficialSpecOperation(
    service="Web of Science",
    spec_url="https://developer.clarivate.com/apis/wos-starter/swagger",
    operation_id="documents.get",
    method="GET",
    path="/documents",
)

SEMANTIC_SCHOLAR_SEARCH_OPERATION = OfficialSpecOperation(
    service="Semantic Scholar",
    spec_url="https://api.semanticscholar.org/graph/v1/swagger.json",
    operation_id="get_graph_paper_relevance_search",
    method="GET",
    path="https://api.semanticscholar.org/graph/v1/paper/search",
)

SEMANTIC_SCHOLAR_PAPER_OPERATION = OfficialSpecOperation(
    service="Semantic Scholar",
    spec_url="https://api.semanticscholar.org/graph/v1/swagger.json",
    operation_id="get_graph_get_paper",
    method="GET",
    path="https://api.semanticscholar.org/graph/v1/paper/{paper_id}",
)

SEMANTIC_SCHOLAR_CITATIONS_OPERATION = OfficialSpecOperation(
    service="Semantic Scholar",
    spec_url="https://api.semanticscholar.org/graph/v1/swagger.json",
    operation_id="get_graph_get_paper_citations",
    method="GET",
    path="https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations",
)

SEMANTIC_SCHOLAR_REFERENCES_OPERATION = OfficialSpecOperation(
    service="Semantic Scholar",
    spec_url="https://api.semanticscholar.org/graph/v1/swagger.json",
    operation_id="get_graph_get_paper_references",
    method="GET",
    path="https://api.semanticscholar.org/graph/v1/paper/{paper_id}/references",
)

SEMANTIC_SCHOLAR_RECOMMENDATIONS_OPERATION = OfficialSpecOperation(
    service="Semantic Scholar",
    spec_url="https://api.semanticscholar.org/recommendations/v1/swagger.json",
    operation_id="get_papers_for_paper",
    method="GET",
    path="https://api.semanticscholar.org/recommendations/v1/papers/forpaper/{paper_id}",
)


class ScopusSearchRequest(BaseModel):
    """Typed request model for the official Scopus Search operation."""

    model_config = ConfigDict(populate_by_name=True)

    query: str
    api_key: str = Field(alias="apiKey")
    http_accept: str = Field(default="application/json", alias="httpAccept")
    insttoken: str | None = None
    access_token: str | None = None
    count: int = 10
    start: int = 0
    view: str = "COMPLETE"


class ScopusSearchEntry(BaseModel):
    """Minimal typed view of Scopus search entries used by normalization."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    title: str = Field(default="", alias="dc:title")
    abstract: str = Field(default="", alias="dc:description")
    creator: str = Field(default="", alias="dc:creator")
    publication_name: str = Field(default="", alias="prism:publicationName")
    doi: str | None = Field(default=None, alias="prism:doi")
    cover_date: str | None = Field(default=None, alias="prism:coverDate")
    identifier: str | None = Field(default=None, alias="dc:identifier")
    eid: str | None = None
    url: str | None = Field(default=None, alias="prism:url")
    open_access_flag: str | None = Field(default=None, alias="openaccessFlag")
    citedby_count: str | int | None = Field(default=0, alias="citedby-count")


class ScopusSearchResultsEnvelope(BaseModel):
    """Scopus search-results envelope."""

    model_config = ConfigDict(extra="allow")

    entry: list[ScopusSearchEntry] = Field(default_factory=list)


class ScopusSearchResponse(BaseModel):
    """Typed Scopus search response."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    search_results: ScopusSearchResultsEnvelope = Field(alias="search-results")

    def entries(self) -> list[ScopusSearchEntry]:
        """Return normalized typed entries from the official response envelope."""

        return self.search_results.entry


class OfficialScopusGeneratedClient:
    """Spec-backed Scopus operation adapter.

    The request shape is derived from Elsevier's published Swagger document and
    its linked Scopus_Search listing.
    """

    operation = SCOPUS_SEARCH_OPERATION

    def __init__(self, owner: BaseAPIClient) -> None:
        self._owner = owner

    async def search_documents(self, request: ScopusSearchRequest) -> ScopusSearchResponse | None:
        """Execute the official Scopus Search operation and parse its response."""

        payload = await self._owner._make_request(
            self.operation.path,
            method=self.operation.method,
            params=request.model_dump(by_alias=True, exclude_none=True),
        )
        if not isinstance(payload, dict):
            return None
        return ScopusSearchResponse.model_validate(payload)


class WebOfScienceSearchRequest(BaseModel):
    """Typed request model for the official Web of Science documents operation."""

    db: str = "WOS"
    q: str
    limit: int = 10
    page: int = 1
    sortField: str | None = None
    modifiedTimeSpan: str | None = None
    publishTimeSpan: str | None = None
    tcModifiedTimeSpan: str | None = None
    detail: str | None = None
    edition: str | None = None


class WebOfScienceAuthorName(BaseModel):
    """Typed author payload from the official Web of Science spec."""

    displayName: str = ""
    wosStandard: str | None = None
    researcherId: str | None = None


class WebOfScienceNames(BaseModel):
    """Names section in the document payload."""

    authors: list[WebOfScienceAuthorName] = Field(default_factory=list)


class WebOfScienceSource(BaseModel):
    """Source metadata from the document payload."""

    model_config = ConfigDict(extra="allow")

    sourceTitle: str = ""
    publishYear: int | None = None
    publishMonth: str | None = None
    volume: str | None = None
    issue: str | None = None


class WebOfScienceLinks(BaseModel):
    """Links section from the document payload."""

    model_config = ConfigDict(extra="allow")

    record: str | None = None
    citingArticles: str | None = None
    references: str | None = None
    related: str | None = None


class WebOfScienceCitationsEntry(BaseModel):
    """Times-cited entry from the official Web of Science spec."""

    db: str | None = None
    count: int = 0


class WebOfScienceIdentifiers(BaseModel):
    """Identifier payload from the official Web of Science spec."""

    model_config = ConfigDict(extra="allow")

    doi: str | None = None
    issn: str | None = None
    eissn: str | None = None
    isbn: str | None = None
    eisbn: str | None = None
    pmid: str | None = None


class WebOfScienceKeywords(BaseModel):
    """Keywords payload from the official Web of Science spec."""

    model_config = ConfigDict(extra="allow")

    authorKeywords: list[str] = Field(default_factory=list)


class WebOfScienceDocument(BaseModel):
    """Typed Web of Science document model."""

    model_config = ConfigDict(extra="allow")

    uid: str
    title: str = ""
    types: list[str] = Field(default_factory=list)
    sourceTypes: list[str] = Field(default_factory=list)
    source: WebOfScienceSource = Field(default_factory=WebOfScienceSource)
    names: WebOfScienceNames = Field(default_factory=WebOfScienceNames)
    links: WebOfScienceLinks = Field(default_factory=WebOfScienceLinks)
    citations: list[WebOfScienceCitationsEntry] | WebOfScienceCitationsEntry | int | None = Field(default_factory=list)
    identifiers: WebOfScienceIdentifiers = Field(default_factory=WebOfScienceIdentifiers)
    keywords: WebOfScienceKeywords = Field(default_factory=WebOfScienceKeywords)


class WebOfScienceMetadata(BaseModel):
    """Pagination metadata from the official Web of Science spec."""

    total: int = 0
    page: int = 1
    limit: int = 10


class WebOfScienceDocumentsResponse(BaseModel):
    """Typed Web of Science documents response."""

    metadata: WebOfScienceMetadata = Field(default_factory=WebOfScienceMetadata)
    hits: list[WebOfScienceDocument] = Field(default_factory=list)


class OfficialWebOfScienceGeneratedClient:
    """Spec-backed Web of Science documents adapter."""

    operation = WEB_OF_SCIENCE_SEARCH_OPERATION

    def __init__(self, owner: BaseAPIClient) -> None:
        self._owner = owner

    async def search_documents(
        self,
        request: WebOfScienceSearchRequest,
    ) -> WebOfScienceDocumentsResponse | None:
        """Execute the official Web of Science documents operation."""

        payload = await self._owner._make_request(
            self.operation.path,
            method=self.operation.method,
            params=request.model_dump(exclude_none=True),
        )
        if not isinstance(payload, dict):
            return None
        return WebOfScienceDocumentsResponse.model_validate(payload)


class SemanticScholarSearchRequest(BaseModel):
    """Typed request for the official Semantic Scholar paper search endpoint."""

    query: str
    limit: int = 10
    fields: str
    year: str | None = None
    openAccessPdf: str | None = None


class SemanticScholarPaperIdentifiers(BaseModel):
    """External identifiers published by Semantic Scholar."""

    model_config = ConfigDict(extra="allow")

    DOI: str | None = None
    PubMed: str | None = None
    PubMedCentral: str | None = None
    ArXiv: str | None = None


class SemanticScholarAuthor(BaseModel):
    """Minimal typed author payload for Semantic Scholar papers."""

    authorId: str | None = None
    name: str = ""


class SemanticScholarPublicationVenue(BaseModel):
    """Publication venue payload for Semantic Scholar papers."""

    id: str | None = None
    name: str | None = None
    type: str | None = None
    alternate_names: list[str] = Field(default_factory=list)
    url: str | None = None


class SemanticScholarOpenAccessPdf(BaseModel):
    """Open access PDF payload from the Semantic Scholar spec."""

    url: str | None = None
    status: str | None = None
    license: str | None = None
    disclaimer: str | None = None


class SemanticScholarPaperModel(BaseModel):
    """Typed paper model covering the repo's current Semantic Scholar usage."""

    model_config = ConfigDict(extra="allow")

    paperId: str = ""
    title: str = ""
    abstract: str | None = None
    year: int | None = None
    authors: list[SemanticScholarAuthor] = Field(default_factory=list)
    venue: str | None = None
    publicationVenue: SemanticScholarPublicationVenue | str | None = None
    citationCount: int = 0
    influentialCitationCount: int = 0
    isOpenAccess: bool = False
    openAccessPdf: SemanticScholarOpenAccessPdf | None = None
    externalIds: SemanticScholarPaperIdentifiers | None = None


class SemanticScholarSearchResponse(BaseModel):
    """Typed response for Semantic Scholar paper search."""

    total: int | str | None = None
    offset: int = 0
    next: int | None = None
    data: list[SemanticScholarPaperModel] = Field(default_factory=list)


class SemanticScholarCitationEntry(BaseModel):
    """Typed citation entry from the official Semantic Scholar spec."""

    contexts: list[str] = Field(default_factory=list)
    intents: list[str] = Field(default_factory=list)
    isInfluential: bool = False
    citingPaper: SemanticScholarPaperModel | None = None


class SemanticScholarCitationsResponse(BaseModel):
    """Typed citations batch from the official Semantic Scholar spec."""

    offset: int = 0
    next: int | None = None
    data: list[SemanticScholarCitationEntry] = Field(default_factory=list)


class SemanticScholarReferenceEntry(BaseModel):
    """Typed reference entry from the official Semantic Scholar spec."""

    contexts: list[str] = Field(default_factory=list)
    intents: list[str] = Field(default_factory=list)
    isInfluential: bool = False
    citedPaper: SemanticScholarPaperModel | None = None


class SemanticScholarReferencesResponse(BaseModel):
    """Typed references batch from the official Semantic Scholar spec."""

    offset: int = 0
    next: int | None = None
    data: list[SemanticScholarReferenceEntry] = Field(default_factory=list)


class SemanticScholarRecommendationsResponse(BaseModel):
    """Typed recommendations response from the official recommendations spec."""

    recommendedPapers: list[SemanticScholarPaperModel] = Field(default_factory=list)


class OfficialSemanticScholarGeneratedClient:
    """Spec-backed Semantic Scholar adapter for graph and recommendations APIs."""

    search_operation = SEMANTIC_SCHOLAR_SEARCH_OPERATION
    paper_operation = SEMANTIC_SCHOLAR_PAPER_OPERATION
    citations_operation = SEMANTIC_SCHOLAR_CITATIONS_OPERATION
    references_operation = SEMANTIC_SCHOLAR_REFERENCES_OPERATION
    recommendations_operation = SEMANTIC_SCHOLAR_RECOMMENDATIONS_OPERATION

    def __init__(self, owner: BaseAPIClient) -> None:
        self._owner = owner

    @staticmethod
    def _build_url(base: str, params: dict[str, str | int | None]) -> str:
        """Build a URL string so existing tests can keep asserting on query text."""

        filtered = {key: value for key, value in params.items() if value is not None}
        if not filtered:
            return base
        return f"{base}?{urllib.parse.urlencode(filtered)}"

    async def search_papers(
        self,
        request: SemanticScholarSearchRequest,
    ) -> SemanticScholarSearchResponse | None:
        """Execute the official Semantic Scholar paper search operation."""

        url = self._build_url(self.search_operation.path, request.model_dump(exclude_none=True))
        payload = await self._owner._make_request(url, method=self.search_operation.method)
        if not isinstance(payload, dict):
            return None
        return SemanticScholarSearchResponse.model_validate(payload)

    async def get_paper(self, paper_id: str, fields: str) -> SemanticScholarPaperModel | None:
        """Execute the official Semantic Scholar paper detail operation."""

        encoded_id = urllib.parse.quote(paper_id, safe="")
        path = self.paper_operation.path.format(paper_id=encoded_id)
        url = self._build_url(path, {"fields": fields})
        payload = await self._owner._make_request(url, method=self.paper_operation.method)
        if not isinstance(payload, dict):
            return None
        return SemanticScholarPaperModel.model_validate(payload)

    async def get_citations(
        self,
        paper_id: str,
        *,
        limit: int,
        fields: str,
    ) -> SemanticScholarCitationsResponse | None:
        """Execute the official Semantic Scholar citations operation."""

        encoded_id = urllib.parse.quote(paper_id, safe="")
        path = self.citations_operation.path.format(paper_id=encoded_id)
        url = self._build_url(path, {"limit": min(limit, 100), "fields": fields})
        payload = await self._owner._make_request(url, method=self.citations_operation.method)
        if not isinstance(payload, dict):
            return None
        return SemanticScholarCitationsResponse.model_validate(payload)

    async def get_references(
        self,
        paper_id: str,
        *,
        limit: int,
        fields: str,
    ) -> SemanticScholarReferencesResponse | None:
        """Execute the official Semantic Scholar references operation."""

        encoded_id = urllib.parse.quote(paper_id, safe="")
        path = self.references_operation.path.format(paper_id=encoded_id)
        url = self._build_url(path, {"limit": min(limit, 100), "fields": fields})
        payload = await self._owner._make_request(url, method=self.references_operation.method)
        if not isinstance(payload, dict):
            return None
        return SemanticScholarReferencesResponse.model_validate(payload)

    async def get_recommendations(
        self,
        paper_id: str,
        *,
        limit: int,
        fields: str,
    ) -> SemanticScholarRecommendationsResponse | None:
        """Execute the official Semantic Scholar recommendations operation."""

        encoded_id = urllib.parse.quote(paper_id, safe="")
        path = self.recommendations_operation.path.format(paper_id=encoded_id)
        url = self._build_url(path, {"limit": min(limit, 500), "fields": fields})
        payload = await self._owner._make_request(url, method=self.recommendations_operation.method)
        if not isinstance(payload, dict):
            return None
        return SemanticScholarRecommendationsResponse.model_validate(payload)


__all__ = [
    "OfficialScopusGeneratedClient",
    "OfficialSemanticScholarGeneratedClient",
    "OfficialSpecOperation",
    "OfficialWebOfScienceGeneratedClient",
    "SCOPUS_SEARCH_OPERATION",
    "SEMANTIC_SCHOLAR_CITATIONS_OPERATION",
    "SEMANTIC_SCHOLAR_PAPER_OPERATION",
    "SEMANTIC_SCHOLAR_RECOMMENDATIONS_OPERATION",
    "SEMANTIC_SCHOLAR_REFERENCES_OPERATION",
    "SEMANTIC_SCHOLAR_SEARCH_OPERATION",
    "ScopusSearchRequest",
    "WEB_OF_SCIENCE_SEARCH_OPERATION",
    "WebOfScienceSearchRequest",
    "SemanticScholarSearchRequest",
]
