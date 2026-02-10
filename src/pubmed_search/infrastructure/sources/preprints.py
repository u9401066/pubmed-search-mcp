"""
Preprint Sources - arXiv, medRxiv, bioRxiv Integration

Provides search capabilities for preprint servers:
- arXiv: Physics, Math, CS, Q-Bio, Q-Fin, Stats, EE
- medRxiv: Medical preprints
- bioRxiv: Biology preprints
"""

import logging
import re

import defusedxml.ElementTree as ET  # Security: prevent XML attacks

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# API endpoints
ARXIV_API_URL = "http://export.arxiv.org/api/query"
MEDRXIV_API_URL = "https://api.medrxiv.org/details/medrxiv"
BIORXIV_API_URL = "https://api.biorxiv.org/details/biorxiv"

# arXiv category prefixes relevant to medicine/biology
ARXIV_MEDICAL_CATEGORIES = [
    "q-bio",  # Quantitative Biology
    "stat",  # Statistics (often medical)
    "cs.AI",  # AI in medicine
    "cs.LG",  # Machine Learning
    "physics.med-ph",  # Medical Physics
]


@dataclass
class PreprintArticle:
    """Standardized preprint article representation."""

    id: str
    title: str
    abstract: str
    authors: List[str]
    published: str
    updated: Optional[str]
    source: str  # "arxiv", "medrxiv", "biorxiv"
    categories: List[str]
    pdf_url: Optional[str]
    doi: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "title": self.title,
            "abstract": self.abstract[:500] + "..."
            if len(self.abstract) > 500
            else self.abstract,
            "authors": self.authors,
            "published": self.published,
            "updated": self.updated,
            "source": self.source,
            "categories": self.categories,
            "pdf_url": self.pdf_url,
            "doi": self.doi,
            "source_url": self._get_source_url(),
        }

    def _get_source_url(self) -> str:
        """Get URL to view article on source website."""
        if self.source == "arxiv":
            return f"https://arxiv.org/abs/{self.id}"
        elif self.source == "medrxiv":
            return f"https://www.medrxiv.org/content/{self.doi}" if self.doi else ""
        elif self.source == "biorxiv":
            return f"https://www.biorxiv.org/content/{self.doi}" if self.doi else ""
        return ""


class ArXivClient:
    """Client for arXiv API."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy-init async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def search(
        self,
        query: str,
        limit: int = 10,
        categories: Optional[List[str]] = None,
        sort_by: str = "relevance",  # relevance, lastUpdatedDate, submittedDate
    ) -> List[PreprintArticle]:
        """
        Search arXiv for preprints.

        Args:
            query: Search query
            limit: Maximum results (max 100)
            categories: Filter by categories (e.g., ["q-bio", "cs.AI"])
            sort_by: Sort order

        Returns:
            List of PreprintArticle objects
        """
        try:
            # Build search query
            search_parts = []

            # Add main query
            if query:
                # Escape special characters
                escaped_query = (
                    query.replace(":", " ").replace("(", " ").replace(")", " ")
                )
                search_parts.append(f"all:{escaped_query}")

            # Add category filters
            if categories:
                cat_query = " OR ".join([f"cat:{cat}*" for cat in categories])
                search_parts.append(f"({cat_query})")

            full_query = " AND ".join(search_parts) if search_parts else "all:*"

            # Map sort parameter
            sort_map = {
                "relevance": "relevance",
                "date": "lastUpdatedDate",
                "submitted": "submittedDate",
                "lastUpdatedDate": "lastUpdatedDate",
                "submittedDate": "submittedDate",
            }
            sort_param = sort_map.get(sort_by, "relevance")

            params = {
                "search_query": full_query,
                "start": 0,
                "max_results": min(limit, 100),
                "sortBy": sort_param,
                "sortOrder": "descending",
            }

            logger.info(f"arXiv search: {full_query}")

            response = await self.client.get(ARXIV_API_URL, params=params)
            response.raise_for_status()

            return self._parse_atom_response(response.text)

        except Exception as e:
            logger.error(f"arXiv search error: {e}")
            return []

    def _parse_atom_response(self, xml_text: str) -> List[PreprintArticle]:
        """Parse Atom XML response from arXiv."""
        articles = []

        try:
            # Define namespaces
            ns = {
                "atom": "http://www.w3.org/2005/Atom",
                "arxiv": "http://arxiv.org/schemas/atom",
            }

            root = ET.fromstring(xml_text)

            for entry in root.findall("atom:entry", ns):
                try:
                    # Extract ID (arxiv ID from URL)
                    id_elem = entry.find("atom:id", ns)
                    arxiv_id = ""
                    if id_elem is not None and id_elem.text:
                        # Extract ID from URL like http://arxiv.org/abs/1234.5678v1
                        match = re.search(r"arxiv.org/abs/(.+)", id_elem.text)
                        if match:
                            arxiv_id = match.group(1)

                    # Extract title
                    title_elem = entry.find("atom:title", ns)
                    title = (
                        title_elem.text.strip().replace("\n", " ")
                        if title_elem is not None and title_elem.text
                        else ""
                    )

                    # Extract abstract
                    summary_elem = entry.find("atom:summary", ns)
                    abstract = (
                        summary_elem.text.strip().replace("\n", " ")
                        if summary_elem is not None and summary_elem.text
                        else ""
                    )

                    # Extract authors
                    authors = []
                    for author in entry.findall("atom:author", ns):
                        name_elem = author.find("atom:name", ns)
                        if name_elem is not None and name_elem.text:
                            authors.append(name_elem.text)

                    # Extract dates
                    published_elem = entry.find("atom:published", ns)
                    published = (
                        published_elem.text[:10]
                        if published_elem is not None and published_elem.text
                        else ""
                    )

                    updated_elem = entry.find("atom:updated", ns)
                    updated = (
                        updated_elem.text[:10]
                        if updated_elem is not None and updated_elem.text
                        else None
                    )

                    # Extract categories
                    categories = []
                    for cat in entry.findall("atom:category", ns):
                        term = cat.get("term")
                        if term:
                            categories.append(term)

                    # Extract PDF link
                    pdf_url = None
                    for link in entry.findall("atom:link", ns):
                        if link.get("title") == "pdf":
                            pdf_url = link.get("href")
                            break

                    # Extract DOI if available
                    doi = None
                    doi_elem = entry.find("arxiv:doi", ns)
                    if doi_elem is not None and doi_elem.text:
                        doi = doi_elem.text

                    articles.append(
                        PreprintArticle(
                            id=arxiv_id,
                            title=title,
                            abstract=abstract,
                            authors=authors,
                            published=published,
                            updated=updated,
                            source="arxiv",
                            categories=categories,
                            pdf_url=pdf_url,
                            doi=doi,
                        )
                    )

                except Exception as e:
                    logger.warning(f"Error parsing arXiv entry: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error parsing arXiv XML: {e}")

        return articles

    async def get_by_id(self, arxiv_id: str) -> Optional[PreprintArticle]:
        """Get article by arXiv ID."""
        try:
            params = {"id_list": arxiv_id}
            response = await self.client.get(ARXIV_API_URL, params=params)
            response.raise_for_status()

            articles = self._parse_atom_response(response.text)
            return articles[0] if articles else None

        except Exception as e:
            logger.error(f"arXiv get by ID error: {e}")
            return None


class MedBioRxivClient:
    """Client for medRxiv and bioRxiv APIs."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy-init async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def search_medrxiv(
        self,
        query: str,
        limit: int = 10,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> List[PreprintArticle]:
        """
        Search medRxiv for medical preprints.

        Note: medRxiv API is date-based, not full-text search.
        We fetch recent papers and filter client-side.

        Args:
            query: Search terms to filter results
            limit: Maximum results
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
        """
        return await self._search_rxiv(
            base_url=MEDRXIV_API_URL,
            source="medrxiv",
            query=query,
            limit=limit,
            from_date=from_date,
            to_date=to_date,
        )

    async def search_biorxiv(
        self,
        query: str,
        limit: int = 10,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> List[PreprintArticle]:
        """Search bioRxiv for biology preprints."""
        return await self._search_rxiv(
            base_url=BIORXIV_API_URL,
            source="biorxiv",
            query=query,
            limit=limit,
            from_date=from_date,
            to_date=to_date,
        )

    async def _search_rxiv(
        self,
        base_url: str,
        source: str,
        query: str,
        limit: int,
        from_date: Optional[str],
        to_date: Optional[str],
    ) -> List[PreprintArticle]:
        """Common search logic for medRxiv/bioRxiv."""
        try:
            # Default date range: last 30 days
            if not to_date:
                to_date = datetime.now().strftime("%Y-%m-%d")
            if not from_date:
                # Go back 90 days to get more results for filtering
                from datetime import timedelta

                from_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

            # API format: /details/{server}/{from}/{to}/{cursor}
            url = f"{base_url}/{from_date}/{to_date}/0"

            logger.info(f"{source} search: {query} ({from_date} to {to_date})")

            response = await self.client.get(url)
            response.raise_for_status()

            data = response.json()

            articles = []
            query_lower = query.lower()
            query_terms = query_lower.split()

            for item in data.get("collection", []):
                try:
                    title = item.get("title", "")
                    abstract = item.get("abstract", "")

                    # Filter by query terms
                    text = f"{title} {abstract}".lower()
                    if query_terms and not all(term in text for term in query_terms):
                        continue

                    # Extract authors
                    authors_str = item.get("authors", "")
                    authors = (
                        [a.strip() for a in authors_str.split(";")]
                        if authors_str
                        else []
                    )

                    # Get category
                    category = item.get("category", "")

                    articles.append(
                        PreprintArticle(
                            id=item.get("doi", ""),
                            title=title,
                            abstract=abstract,
                            authors=authors,
                            published=item.get("date", ""),
                            updated=None,
                            source=source,
                            categories=[category] if category else [],
                            pdf_url=None,  # Construct from DOI if needed
                            doi=item.get("doi"),
                        )
                    )

                    if len(articles) >= limit:
                        break

                except Exception as e:
                    logger.warning(f"Error parsing {source} entry: {e}")
                    continue

            return articles[:limit]

        except Exception as e:
            logger.error(f"{source} search error: {e}")
            return []


class PreprintSearcher:
    """Unified preprint searcher for arXiv, medRxiv, bioRxiv."""

    def __init__(self):
        self.arxiv = ArXivClient()
        self.rxiv = MedBioRxivClient()

    async def search(
        self,
        query: str,
        sources: Optional[List[str]] = None,
        limit: int = 10,
        categories: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Search across preprint servers.

        Args:
            query: Search query
            sources: Which sources to search. Default: all.
                     Options: ["arxiv", "medrxiv", "biorxiv"]
            limit: Max results per source
            categories: arXiv category filter (e.g., ["q-bio", "cs.AI"])

        Returns:
            Dictionary with results from each source
        """
        if sources is None:
            sources = ["arxiv", "medrxiv", "biorxiv"]

        results = {
            "query": query,
            "sources_searched": sources,
            "articles": [],
            "by_source": {},
        }

        # Search arXiv
        if "arxiv" in sources:
            arxiv_results = await self.arxiv.search(
                query=query,
                limit=limit,
                categories=categories or ARXIV_MEDICAL_CATEGORIES,
            )
            results["by_source"]["arxiv"] = [a.to_dict() for a in arxiv_results]
            results["articles"].extend(results["by_source"]["arxiv"])

        # Search medRxiv
        if "medrxiv" in sources:
            medrxiv_results = await self.rxiv.search_medrxiv(query=query, limit=limit)
            results["by_source"]["medrxiv"] = [a.to_dict() for a in medrxiv_results]
            results["articles"].extend(results["by_source"]["medrxiv"])

        # Search bioRxiv
        if "biorxiv" in sources:
            biorxiv_results = await self.rxiv.search_biorxiv(query=query, limit=limit)
            results["by_source"]["biorxiv"] = [a.to_dict() for a in biorxiv_results]
            results["articles"].extend(results["by_source"]["biorxiv"])

        results["total"] = len(results["articles"])

        return results

    async def search_medical_preprints(
        self,
        query: str,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """
        Convenience method for medical/health preprint search.
        Searches medRxiv + arXiv q-bio.
        """
        return await self.search(
            query=query,
            sources=["medrxiv", "arxiv"],
            limit=limit,
            categories=["q-bio", "stat.AP", "stat.ML"],
        )

    async def get_arxiv_paper(self, arxiv_id: str) -> Optional[Dict[str, Any]]:
        """Get specific arXiv paper by ID."""
        article = await self.arxiv.get_by_id(arxiv_id)
        return article.to_dict() if article else None
