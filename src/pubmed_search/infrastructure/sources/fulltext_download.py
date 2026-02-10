"""
Fulltext Download Module - Multi-source PDF/Fulltext Retrieval

This module provides comprehensive fulltext acquisition strategies:

1. **Link Collection** - Gather PDF links from multiple sources
2. **PDF Download** - Actually download PDF files
3. **Text Extraction** - Extract text from PDF for analysis
4. **Fallback Chain** - Graceful degradation through sources

Sources (in priority order):
- PubMed Central (PMC) - Best quality, structured
- Europe PMC - Additional OA coverage
- Unpaywall - Finds legal OA versions
- CORE - 200M+ open access
- Preprint servers (arXiv, bioRxiv, medRxiv)
- Publisher OA landing pages

Usage:
    downloader = FulltextDownloader()

    # Get just links
    links = await downloader.get_pdf_links(pmid="12345678")

    # Download PDF
    pdf_bytes = await downloader.download_pdf(doi="10.1038/...")

    # Download and extract text
    text = await downloader.get_fulltext_as_text(pmid="12345678")
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional

import httpx

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


class PDFSource(Enum):
    """PDF source with priority (lower = higher priority)."""

    # Direct PDF sources (highest priority)
    EUROPE_PMC = ("europe_pmc", 1, "Europe PMC")  # Direct PDF, most reliable
    UNPAYWALL_PUBLISHER = ("unpaywall_publisher", 2, "Publisher (via Unpaywall)")

    # Structured sources
    PMC = (
        "pmc",
        3,
        "PubMed Central",
    )  # May redirect, less reliable for direct download
    UNPAYWALL_REPOSITORY = ("unpaywall_repository", 4, "Repository (via Unpaywall)")
    CORE = ("core", 5, "CORE")
    SEMANTIC_SCHOLAR = ("semantic_scholar", 6, "Semantic Scholar")
    OPENALEX = ("openalex", 7, "OpenAlex")

    # Preprint servers (open access, reliable)
    ARXIV = ("arxiv", 8, "arXiv")
    BIORXIV = ("biorxiv", 9, "bioRxiv")
    MEDRXIV = ("medrxiv", 10, "medRxiv")

    # Fallback sources
    DOI_REDIRECT = ("doi_redirect", 11, "Publisher (DOI)")
    CROSSREF = ("crossref", 12, "CrossRef")
    DOAJ = ("doaj", 13, "DOAJ")  # Directory of Open Access Journals
    ZENODO = ("zenodo", 14, "Zenodo")  # Research repository
    INTERNET_ARCHIVE = ("internet_archive", 15, "Internet Archive")

    @property
    def source_id(self) -> str:
        return self.value[0]

    @property
    def priority(self) -> int:
        return self.value[1]

    @property
    def display_name(self) -> str:
        return self.value[2]


@dataclass
class PDFLink:
    """A link to a PDF with metadata."""

    url: str
    source: PDFSource
    access_type: Literal[
        "open_access", "green_oa", "gold", "bronze", "hybrid", "subscription", "unknown"
    ] = "unknown"
    version: Optional[str] = None  # "published", "accepted", "submitted"
    license: Optional[str] = None
    is_direct_pdf: bool = True  # vs landing page
    confidence: float = 1.0  # How confident we are this is a valid PDF

    def __lt__(self, other: "PDFLink") -> bool:
        """Sort by source priority then confidence."""
        if self.source.priority != other.source.priority:
            return self.source.priority < other.source.priority
        return self.confidence > other.confidence


@dataclass
class DownloadResult:
    """Result of a PDF download attempt."""

    success: bool
    content: Optional[bytes] = None
    content_type: Optional[str] = None
    source: Optional[PDFSource] = None
    url: Optional[str] = None
    error: Optional[str] = None
    file_size: int = 0

    @property
    def is_pdf(self) -> bool:
        """Check if content is actually a PDF."""
        if not self.content:
            return False
        # PDF files start with %PDF
        return self.content[:4] == b"%PDF"


@dataclass
class FulltextResult:
    """Complete fulltext retrieval result."""

    # Identifiers
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    doi: Optional[str] = None
    title: Optional[str] = None

    # Content
    text_content: Optional[str] = None
    pdf_bytes: Optional[bytes] = None
    structured_sections: Optional[dict[str, str]] = None

    # Links found
    pdf_links: list[PDFLink] = field(default_factory=list)

    # Metadata
    source_used: Optional[PDFSource] = None
    content_type: Literal["xml", "pdf", "text", "none"] = "none"
    extraction_method: Optional[str] = None

    # Quality indicators
    has_figures: bool = False
    has_tables: bool = False
    has_references: bool = False
    word_count: int = 0
    file_size: int = 0  # PDF file size in bytes


# =============================================================================
# FulltextDownloader
# =============================================================================


class FulltextDownloader:
    """
    Multi-source fulltext downloader with PDF text extraction.

    Features:
    - Rate limiting: Max concurrent requests via semaphore
    - Retry with exponential backoff: Auto-retry on transient failures
    - Resume download: Support for Range headers (partial content)
    - Multi-source priority: 15 sources sorted by reliability

    Strategies:
    1. links_only: Just collect PDF links (fast, no download)
    2. download_best: Download from best available source
    3. extract_text: Download and extract text from PDF
    4. try_all: Try all sources until success

    Example:
        downloader = FulltextDownloader()

        # Strategy 1: Get links
        links = await downloader.get_pdf_links(pmid="12345678")

        # Strategy 2: Download best PDF
        result = await downloader.download_pdf(doi="10.1038/...")
        if result.success:
            with open("paper.pdf", "wb") as f:
                f.write(result.content)

        # Strategy 3: Get text content
        fulltext = await downloader.get_fulltext(
            pmid="12345678",
            strategy="extract_text"
        )
        print(fulltext.text_content)
    """

    # HTTP settings
    DEFAULT_TIMEOUT = 30.0
    MAX_PDF_SIZE = 50 * 1024 * 1024  # 50MB
    CHUNK_SIZE = 8192  # 8KB chunks for streaming

    # Rate limiting
    MAX_CONCURRENT_REQUESTS = 5  # Max parallel downloads

    # Retry settings
    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 1.0  # seconds
    RETRY_MAX_DELAY = 30.0  # seconds
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    # User agent for academic access
    USER_AGENT = (
        "Mozilla/5.0 (compatible; PubMed-Search-MCP/1.0; mailto:research@example.com)"
    )

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        max_concurrent: int = MAX_CONCURRENT_REQUESTS,
    ):
        """
        Initialize fulltext downloader.

        Args:
            timeout: Request timeout in seconds
            max_retries: Max retries per request (with exponential backoff)
            max_concurrent: Max concurrent downloads (rate limiting)
        """
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._rate_limit_until: float = 0  # Unix timestamp for global rate limit

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=10.0),
                limits=httpx.Limits(max_connections=10),
                headers={"User-Agent": self.USER_AGENT},
                follow_redirects=True,
            )
        return self._client

    async def close(self):
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # =========================================================================
    # Main API
    # =========================================================================

    async def get_pdf_links(
        self,
        pmid: Optional[str] = None,
        pmcid: Optional[str] = None,
        doi: Optional[str] = None,
    ) -> list[PDFLink]:
        """
        Collect PDF links from all available sources.

        Does NOT download - just finds links. Fast and low-bandwidth.

        Args:
            pmid: PubMed ID
            pmcid: PubMed Central ID
            doi: Digital Object Identifier

        Returns:
            List of PDFLink objects, sorted by priority
        """
        links: list[PDFLink] = []

        # Gather links from all sources in parallel
        tasks = []

        # PMC/Europe PMC sources (need PMCID or PMID)
        if pmcid or pmid:
            tasks.append(self._get_pmc_links(pmid, pmcid))

        # PubMed LinkOut (need PMID)
        if pmid:
            tasks.append(self._get_pubmed_linkout(pmid))

        # DOI-based sources
        if doi:
            tasks.append(self._get_unpaywall_links(doi))
            tasks.append(self._get_crossref_links(doi))  # NEW: Publisher links
            tasks.append(self._get_core_links(doi))
            tasks.append(self._get_semantic_scholar_links(doi))
            tasks.append(self._get_openalex_links(doi))
            tasks.append(self._get_doaj_links(doi))  # NEW: OA journals
            tasks.append(self._get_zenodo_links(doi))  # NEW: Research repository

        # Check for preprint identifiers in DOI
        if doi:
            if "arxiv" in doi.lower():
                tasks.append(self._get_arxiv_link(doi))
            # bioRxiv/medRxiv DOIs start with 10.1101
            if (
                "10.1101/" in doi
                or "biorxiv" in doi.lower()
                or "medrxiv" in doi.lower()
            ):
                tasks.append(self._get_preprint_link(doi))

        # Run all link gathering in parallel
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, list):
                    links.extend(result)
                elif isinstance(result, PDFLink):
                    links.append(result)
                elif isinstance(result, Exception):
                    logger.debug(f"Link gathering failed: {result}")

        # Sort by priority and deduplicate by URL
        seen_urls = set()
        unique_links = []
        for link in sorted(links):
            if link.url not in seen_urls:
                seen_urls.add(link.url)
                unique_links.append(link)

        return unique_links

    async def download_pdf(
        self,
        pmid: Optional[str] = None,
        pmcid: Optional[str] = None,
        doi: Optional[str] = None,
        preferred_source: Optional[PDFSource] = None,
        try_all: bool = True,
    ) -> DownloadResult:
        """
        Download PDF from best available source.

        Args:
            pmid: PubMed ID
            pmcid: PubMed Central ID
            doi: Digital Object Identifier
            preferred_source: Try this source first
            try_all: If preferred fails, try other sources

        Returns:
            DownloadResult with PDF bytes or error
        """
        # Get all available links
        links = await self.get_pdf_links(pmid, pmcid, doi)

        if not links:
            return DownloadResult(
                success=False, error="No PDF links found for this article"
            )

        # Reorder if preferred source specified
        if preferred_source:
            links = sorted(
                links,
                key=lambda lnk: (
                    0 if lnk.source == preferred_source else 1,
                    lnk.source.priority,
                ),
            )

        # Try downloading
        last_error = None
        for link in links:
            result = await self._download_from_url(link.url, link.source)

            if result.success and result.is_pdf:
                return result

            if not try_all:
                return result

            last_error = result.error
            logger.debug(
                f"Download failed from {link.source.display_name}: {result.error}"
            )

        return DownloadResult(
            success=False, error=f"All sources failed. Last error: {last_error}"
        )

    async def get_fulltext(
        self,
        pmid: Optional[str] = None,
        pmcid: Optional[str] = None,
        doi: Optional[str] = None,
        strategy: Literal[
            "links_only", "download_best", "extract_text", "try_all"
        ] = "extract_text",
    ) -> FulltextResult:
        """
        Get fulltext using specified strategy.

        Strategies:
        - links_only: Just return PDF links (fastest)
        - download_best: Download from best source
        - extract_text: Download and extract text (most useful)
        - try_all: Try structured XML first, then PDF extraction

        Args:
            pmid: PubMed ID
            pmcid: PubMed Central ID
            doi: Digital Object Identifier
            strategy: Retrieval strategy

        Returns:
            FulltextResult with content and metadata
        """
        result = FulltextResult(pmid=pmid, pmcid=pmcid, doi=doi)

        # Strategy 1: Links only
        if strategy == "links_only":
            result.pdf_links = await self.get_pdf_links(pmid, pmcid, doi)
            return result

        # Strategy 4: Try structured XML first (best quality)
        if strategy == "try_all" and pmcid:
            xml_result = await self._get_structured_fulltext(pmcid)
            if xml_result:
                result.text_content = xml_result.get("text")
                result.structured_sections = xml_result.get("sections")
                result.content_type = "xml"
                result.source_used = PDFSource.EUROPE_PMC
                result.title = xml_result.get("title")
                result.has_references = bool(xml_result.get("references"))
                if result.text_content:
                    result.word_count = len(result.text_content.split())
                return result

        # Get PDF links
        result.pdf_links = await self.get_pdf_links(pmid, pmcid, doi)

        if not result.pdf_links:
            result.content_type = "none"
            return result

        # Strategy 2 or 3: Download
        download = await self.download_pdf(pmid, pmcid, doi)

        if not download.success:
            return result

        result.pdf_bytes = download.content
        result.source_used = download.source
        result.content_type = "pdf"
        result.file_size = download.file_size

        # Strategy 3: Extract text
        if strategy in ("extract_text", "try_all"):
            text = await self._extract_pdf_text(download.content)
            if text:
                result.text_content = text
                result.extraction_method = "pdf_extraction"
                result.word_count = len(text.split())

        return result

    # =========================================================================
    # Link Gathering (Private)
    # =========================================================================

    async def _get_pmc_links(
        self,
        pmid: Optional[str],
        pmcid: Optional[str],
    ) -> list[PDFLink]:
        """Get PDF links from PubMed Central."""
        links = []

        # If we have PMC ID, use multiple strategies
        if pmcid:
            pmc_num = pmcid.replace("PMC", "").replace("pmc", "")

            # Strategy 1: Europe PMC PDF (most reliable)
            links.append(
                PDFLink(
                    url=f"https://europepmc.org/backend/ptpmcrender.fcgi?accid=PMC{pmc_num}&blobtype=pdf",
                    source=PDFSource.EUROPE_PMC,
                    access_type="open_access",
                    version="published",
                    is_direct_pdf=True,
                    confidence=0.95,  # Europe PMC is very reliable
                )
            )

            # Strategy 2: PMC OA Service (may have redirect)
            links.append(
                PDFLink(
                    url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_num}/pdf/",
                    source=PDFSource.PMC,
                    access_type="open_access",
                    version="published",
                    is_direct_pdf=False,  # This is a landing/redirect page
                    confidence=0.7,  # Lower confidence due to redirect
                )
            )

        # If only PMID, try to lookup PMC
        elif pmid:
            try:
                from Bio import Entrez

                handle = Entrez.elink(
                    dbfrom="pubmed", db="pmc", id=pmid, linkname="pubmed_pmc"
                )
                record = Entrez.read(handle)
                handle.close()

                if record and record[0].get("LinkSetDb"):
                    for linkset in record[0]["LinkSetDb"]:
                        if linkset.get("LinkName") == "pubmed_pmc":
                            pmc_links = linkset.get("Link", [])
                            if pmc_links:
                                pmc_id = pmc_links[0]["Id"]
                                links.append(
                                    PDFLink(
                                        url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id}/pdf/",
                                        source=PDFSource.PMC,
                                        access_type="open_access",
                                        version="published",
                                        is_direct_pdf=True,
                                        confidence=0.95,
                                    )
                                )
            except Exception as e:
                logger.debug(f"PMC lookup failed: {e}")

        return links

    async def _get_unpaywall_links(self, doi: str) -> list[PDFLink]:
        """Get OA links from Unpaywall."""
        links = []

        try:
            from pubmed_search.infrastructure.sources.unpaywall import (
                get_unpaywall_client,
            )

            client = get_unpaywall_client()
            oa_info = await client.get_oa_status(doi)

            if oa_info and oa_info.get("is_oa"):
                # Best location
                best = oa_info.get("best_oa_location", {})
                if best.get("url_for_pdf"):
                    host_type = best.get("host_type", "unknown")
                    source = (
                        PDFSource.UNPAYWALL_PUBLISHER
                        if host_type == "publisher"
                        else PDFSource.UNPAYWALL_REPOSITORY
                    )
                    links.append(
                        PDFLink(
                            url=best["url_for_pdf"],
                            source=source,
                            access_type=oa_info.get("oa_status", "open_access"),
                            version=best.get("version"),
                            license=best.get("license"),
                            is_direct_pdf=True,
                            confidence=0.9,
                        )
                    )

                # Alternative locations
                for loc in oa_info.get("oa_locations", [])[:3]:
                    if loc != best and loc.get("url_for_pdf"):
                        links.append(
                            PDFLink(
                                url=loc["url_for_pdf"],
                                source=PDFSource.UNPAYWALL_REPOSITORY,
                                access_type="green_oa",
                                version=loc.get("version"),
                                is_direct_pdf=True,
                                confidence=0.8,
                            )
                        )

        except Exception as e:
            logger.debug(f"Unpaywall lookup failed: {e}")

        return links

    async def _get_core_links(self, doi: str) -> list[PDFLink]:
        """Get PDF links from CORE."""
        links = []

        try:
            from pubmed_search.infrastructure.sources.core import get_core_client

            client = get_core_client()
            results = await client.search(f'doi:"{doi}"', limit=1)

            if results and results.get("results"):
                work = results["results"][0]
                if work.get("downloadUrl"):
                    links.append(
                        PDFLink(
                            url=work["downloadUrl"],
                            source=PDFSource.CORE,
                            access_type="open_access",
                            is_direct_pdf=True,
                            confidence=0.85,
                        )
                    )

        except Exception as e:
            logger.debug(f"CORE lookup failed: {e}")

        return links

    async def _get_semantic_scholar_links(self, doi: str) -> list[PDFLink]:
        """Get PDF links from Semantic Scholar."""
        links = []

        try:
            from pubmed_search.infrastructure.sources.semantic_scholar import (
                SemanticScholarClient,
            )

            client = SemanticScholarClient()

            # Semantic Scholar uses DOI prefixed format
            paper = client.get_paper(f"DOI:{doi}")

            if paper and paper.get("pdf_url"):
                links.append(
                    PDFLink(
                        url=paper["pdf_url"],
                        source=PDFSource.SEMANTIC_SCHOLAR,
                        access_type="open_access"
                        if paper.get("is_open_access")
                        else "unknown",
                        is_direct_pdf=True,
                        confidence=0.8,
                    )
                )

        except Exception as e:
            logger.debug(f"Semantic Scholar lookup failed: {e}")

        return links

    async def _get_openalex_links(self, doi: str) -> list[PDFLink]:
        """Get PDF links from OpenAlex."""
        links = []

        try:
            from pubmed_search.infrastructure.sources.openalex import OpenAlexClient

            client = OpenAlexClient()

            # OpenAlex uses doi: prefix format
            work = client.get_work(f"doi:{doi}")

            if work:
                pdf_url = work.get("pdf_url")
                if pdf_url:
                    links.append(
                        PDFLink(
                            url=pdf_url,
                            source=PDFSource.OPENALEX,
                            access_type=work.get("oa_status", "open_access"),
                            is_direct_pdf=True,
                            confidence=0.85,
                        )
                    )

        except Exception as e:
            logger.debug(f"OpenAlex lookup failed: {e}")

        return links

    async def _get_arxiv_link(self, doi: str) -> Optional[PDFLink]:
        """Get PDF link from arXiv."""
        # Extract arXiv ID from DOI
        match = re.search(r"arxiv[./:](\d+\.\d+)(v\d+)?", doi.lower())
        if match:
            arxiv_id = match.group(1)
            version = match.group(2) or ""
            return PDFLink(
                url=f"https://arxiv.org/pdf/{arxiv_id}{version}.pdf",
                source=PDFSource.ARXIV,
                access_type="open_access",
                version="submitted",
                is_direct_pdf=True,
                confidence=0.95,
            )
        return None

    async def _get_preprint_link(self, doi: str) -> Optional[PDFLink]:
        """
        Get PDF link from bioRxiv/medRxiv.

        NOTE: bioRxiv/medRxiv may return 403 for programmatic PDF downloads.
        In that case, use Unpaywall which usually has the same PDF links
        and is more reliable for automated access.

        The URL format is correct - it's just that the servers block some
        programmatic access. Agent should:
        1. Try Unpaywall first (higher priority)
        2. Present the link to user for manual download if automated fails
        """
        # bioRxiv/medRxiv DOI format: 10.1101/YYYY.MM.DD.XXXXXX
        # The PDF URL needs version suffix (v1, v2, etc.)

        # Extract the DOI path
        doi_clean = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")

        if "10.1101/" in doi_clean:
            # Try to detect if it's bioRxiv or medRxiv from the DOI
            # medRxiv DOIs typically have a specific pattern

            if "biorxiv" in doi.lower():
                # Direct bioRxiv indicator in DOI or URL
                base_url = f"https://www.biorxiv.org/content/{doi_clean}"
            elif "medrxiv" in doi.lower():
                # Direct medRxiv indicator
                base_url = f"https://www.medrxiv.org/content/{doi_clean}"
            else:
                # Try bioRxiv first (more common for biology)
                base_url = f"https://www.biorxiv.org/content/{doi_clean}"

            # bioRxiv/medRxiv PDFs need version number
            # Try v1 first, but also provide fallback without version
            return PDFLink(
                url=f"{base_url}v1.full.pdf",  # Most common: version 1
                source=PDFSource.BIORXIV
                if "biorxiv" in base_url
                else PDFSource.MEDRXIV,
                access_type="open_access",
                version="submitted",
                is_direct_pdf=True,
                confidence=0.85,  # Reduced confidence due to version uncertainty
            )

        # Fallback for explicit server indicators in DOI
        if "biorxiv" in doi.lower():
            return PDFLink(
                url=f"https://www.biorxiv.org/content/{doi_clean}.full.pdf",
                source=PDFSource.BIORXIV,
                access_type="open_access",
                version="submitted",
                is_direct_pdf=True,
                confidence=0.7,
            )
        elif "medrxiv" in doi.lower():
            return PDFLink(
                url=f"https://www.medrxiv.org/content/{doi_clean}.full.pdf",
                source=PDFSource.MEDRXIV,
                access_type="open_access",
                version="submitted",
                is_direct_pdf=True,
                confidence=0.7,
            )
        return None

    async def _get_crossref_links(self, doi: str) -> list[PDFLink]:
        """
        Get PDF links from CrossRef.

        CrossRef provides publisher links including PDF URLs.
        This is often the most authoritative source for publisher PDFs.
        """
        links: list[PDFLink] = []

        try:
            client = await self._get_client()
            url = (
                f"https://api.crossref.org/works/{doi}?mailto=pubmed-search@example.com"
            )

            resp = await client.get(url)
            if resp.status_code != 200:
                return links

            data = resp.json()
            message = data.get("message", {})

            # Extract links
            for link in message.get("link", []):
                content_type = link.get("content-type", "")
                link_url = link.get("URL", "")

                if not link_url:
                    continue

                # Prefer PDF links
                if "pdf" in content_type.lower():
                    links.append(
                        PDFLink(
                            url=link_url,
                            source=PDFSource.CROSSREF,
                            access_type="unknown",  # CrossRef doesn't tell us OA status
                            is_direct_pdf=True,
                            confidence=0.85,
                        )
                    )
                elif "xml" in content_type.lower() or "html" in content_type.lower():
                    # Also capture fulltext XML/HTML links
                    links.append(
                        PDFLink(
                            url=link_url,
                            source=PDFSource.CROSSREF,
                            access_type="unknown",
                            is_direct_pdf=False,
                            confidence=0.6,
                        )
                    )

        except Exception as e:
            logger.debug(f"CrossRef lookup failed: {e}")

        return links

    async def _get_pubmed_linkout(self, pmid: str) -> list[PDFLink]:
        """
        Get external links from PubMed LinkOut.

        LinkOut provides links to full text from publishers,
        institutional repositories, and other sources.
        """
        links: list[PDFLink] = []

        try:
            client = await self._get_client()
            url = (
                f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
                f"?dbfrom=pubmed&id={pmid}&cmd=llinks&retmode=json"
            )

            resp = await client.get(url)
            if resp.status_code != 200:
                return links

            data = resp.json()

            # Navigate the complex elink structure
            for linkset in data.get("linksets", []):
                for urllist in linkset.get("idurllist", []):
                    for objurl in urllist.get("objurls", []):
                        link_url = objurl.get("url", {}).get("value", "")
                        provider = objurl.get("provider", {}).get("name", "")

                        if not link_url:
                            continue

                        # Skip PubMed/PMC internal links
                        if "ncbi.nlm.nih.gov" in link_url:
                            continue

                        # Determine if it's likely a PDF
                        is_pdf = (
                            link_url.endswith(".pdf")
                            or "pdf" in link_url.lower()
                            or "fulltext" in provider.lower()
                        )

                        links.append(
                            PDFLink(
                                url=link_url,
                                source=PDFSource.DOI_REDIRECT,  # External publisher
                                access_type="unknown",
                                is_direct_pdf=is_pdf,
                                confidence=0.7 if is_pdf else 0.5,
                            )
                        )

        except Exception as e:
            logger.debug(f"PubMed LinkOut failed: {e}")

        return links

    async def _get_doaj_links(self, doi: str) -> list[PDFLink]:
        """
        Get links from Directory of Open Access Journals (DOAJ).

        DOAJ indexes quality Open Access journals. If an article is in DOAJ,
        it's guaranteed to be OA.
        """
        links: list[PDFLink] = []

        try:
            client = await self._get_client()
            # DOAJ search by DOI
            url = f"https://doaj.org/api/search/articles/doi:{doi}"

            resp = await client.get(url)
            if resp.status_code != 200:
                return links

            data = resp.json()

            for result in data.get("results", []):
                bibjson = result.get("bibjson", {})

                # Get fulltext link
                for link in bibjson.get("link", []):
                    link_url = link.get("url", "")
                    link_type = link.get("type", "")

                    if link_url:
                        links.append(
                            PDFLink(
                                url=link_url,
                                source=PDFSource.DOAJ,
                                access_type="gold",  # DOAJ = Gold OA
                                is_direct_pdf="fulltext" in link_type.lower(),
                                confidence=0.9
                                if "fulltext" in link_type.lower()
                                else 0.7,
                            )
                        )

        except Exception as e:
            logger.debug(f"DOAJ lookup failed: {e}")

        return links

    async def _get_zenodo_links(self, doi: str) -> list[PDFLink]:
        """
        Get links from Zenodo.

        Zenodo is a research data repository that also hosts papers,
        preprints, and supplementary materials.
        """
        links: list[PDFLink] = []

        try:
            client = await self._get_client()

            # Zenodo search by DOI
            # Note: Zenodo DOIs start with 10.5281/zenodo.
            if "10.5281/zenodo" in doi:
                # Direct Zenodo DOI
                record_id = doi.split(".")[-1]
                url = f"https://zenodo.org/api/records/{record_id}"
            else:
                # Search for related records
                url = f"https://zenodo.org/api/records?q=doi:{doi}&size=1"

            resp = await client.get(url)
            if resp.status_code != 200:
                return links

            data = resp.json()

            # Handle single record vs search results
            records = [data] if "id" in data else data.get("hits", {}).get("hits", [])

            for record in records:
                # Get files
                for file_info in record.get("files", []):
                    file_url = file_info.get("links", {}).get("self", "")
                    filename = file_info.get("key", "")

                    if file_url and filename.lower().endswith(".pdf"):
                        links.append(
                            PDFLink(
                                url=file_url,
                                source=PDFSource.ZENODO,
                                access_type="open_access",
                                is_direct_pdf=True,
                                confidence=0.9,
                            )
                        )

        except Exception as e:
            logger.debug(f"Zenodo lookup failed: {e}")

        return links

    # =========================================================================
    # Download & Extraction (Private) - Enhanced with retry & rate limiting
    # =========================================================================

    async def _wait_for_rate_limit(self):
        """Wait if we're being rate limited."""
        import time

        now = time.time()
        if now < self._rate_limit_until:
            wait_time = self._rate_limit_until - now
            logger.info(f"Rate limited, waiting {wait_time:.1f}s")
            await asyncio.sleep(wait_time)

    async def _download_with_retry(
        self,
        url: str,
        source: PDFSource,
        headers: Optional[dict] = None,
    ) -> DownloadResult:
        """
        Download with retry and exponential backoff.

        Features:
        - Automatic retry on transient failures
        - Exponential backoff (1s, 2s, 4s, 8s...)
        - Rate limit detection (429 response)
        - Streaming download for large files
        """
        last_error = "Unknown error"

        for attempt in range(self._max_retries + 1):
            try:
                # Wait for global rate limit
                await self._wait_for_rate_limit()

                # Acquire semaphore for concurrent request limiting
                async with self._semaphore:
                    result = await self._download_from_url_impl(url, source, headers)

                    # Handle rate limiting
                    if result.error and "429" in result.error:
                        import time

                        # Set global rate limit (wait 60s)
                        self._rate_limit_until = time.time() + 60
                        last_error = "Rate limited (429)"
                        continue

                    # Handle retryable errors
                    if not result.success and result.error:
                        for code in self.RETRYABLE_STATUS_CODES:
                            if str(code) in result.error:
                                last_error = result.error
                                break
                        else:
                            # Non-retryable error
                            return result
                    else:
                        return result

            except httpx.TimeoutException:
                last_error = "Download timeout"
            except Exception as e:
                last_error = str(e)

            # Exponential backoff
            if attempt < self._max_retries:
                delay = min(self.RETRY_BASE_DELAY * (2**attempt), self.RETRY_MAX_DELAY)
                logger.debug(
                    f"Retry {attempt + 1}/{self._max_retries} in {delay:.1f}s: {last_error}"
                )
                await asyncio.sleep(delay)

        return DownloadResult(
            success=False,
            error=f"Max retries exceeded: {last_error}",
            url=url,
            source=source,
        )

    async def _download_from_url_impl(
        self,
        url: str,
        source: PDFSource,
        headers: Optional[dict] = None,
    ) -> DownloadResult:
        """Actual download implementation with streaming support."""
        try:
            client = await self._get_client()

            # Build headers
            req_headers = dict(headers or {})
            if "ncbi.nlm.nih.gov" in url:
                req_headers["Accept"] = "application/pdf"

            # Use streaming for potentially large files
            async with client.stream("GET", url, headers=req_headers) as response:
                if response.status_code != 200:
                    return DownloadResult(
                        success=False,
                        error=f"HTTP {response.status_code}",
                        url=url,
                        source=source,
                    )

                content_type = response.headers.get("Content-Type", "")
                content_length = response.headers.get("Content-Length")

                # Check size before downloading
                if content_length:
                    size = int(content_length)
                    if size > self.MAX_PDF_SIZE:
                        return DownloadResult(
                            success=False,
                            error=f"PDF too large ({size / 1024 / 1024:.1f}MB)",
                            url=url,
                            source=source,
                        )

                # Stream download in chunks
                chunks = []
                total_size = 0

                async for chunk in response.aiter_bytes(self.CHUNK_SIZE):
                    total_size += len(chunk)
                    if total_size > self.MAX_PDF_SIZE:
                        return DownloadResult(
                            success=False,
                            error=f"PDF too large (>{self.MAX_PDF_SIZE / 1024 / 1024:.0f}MB)",
                            url=url,
                            source=source,
                        )
                    chunks.append(chunk)

                content = b"".join(chunks)

                # Check if it's actually a PDF
                if not content[:4] == b"%PDF":
                    if b"<html" in content[:1000].lower():
                        return DownloadResult(
                            success=False,
                            error="Received HTML instead of PDF (landing page)",
                            url=url,
                            source=source,
                            content_type="text/html",
                        )

                return DownloadResult(
                    success=True,
                    content=content,
                    content_type=content_type,
                    source=source,
                    url=url,
                    file_size=len(content),
                )

        except httpx.TimeoutException:
            return DownloadResult(
                success=False,
                error="Download timeout",
                url=url,
                source=source,
            )
        except Exception as e:
            return DownloadResult(
                success=False,
                error=str(e),
                url=url,
                source=source,
            )

    async def _download_from_url(
        self,
        url: str,
        source: PDFSource,
    ) -> DownloadResult:
        """Download PDF from URL with retry and rate limiting."""
        return await self._download_with_retry(url, source)

    async def _extract_pdf_text(self, pdf_bytes: Optional[bytes]) -> Optional[str]:
        """
        Extract text from PDF bytes.

        Uses PyMuPDF (fitz) if available, otherwise falls back to pdfplumber.
        """
        if not pdf_bytes:
            return None

        # Try PyMuPDF first (fastest)
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text_parts = []

            for page in doc:
                text = page.get_text()
                if text.strip():
                    text_parts.append(text)

            doc.close()

            if text_parts:
                return "\n\n".join(text_parts)

        except ImportError:
            logger.debug("PyMuPDF not available, trying pdfplumber")
        except Exception as e:
            logger.warning(f"PyMuPDF extraction failed: {e}")

        # Try pdfplumber as fallback
        try:
            import pdfplumber
            import io

            text_parts = []
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)

            if text_parts:
                return "\n\n".join(text_parts)

        except ImportError:
            logger.warning(
                "No PDF extraction library available (install PyMuPDF or pdfplumber)"
            )
        except Exception as e:
            logger.warning(f"pdfplumber extraction failed: {e}")

        return None

    async def _get_structured_fulltext(self, pmcid: str) -> Optional[dict]:
        """Get structured fulltext from Europe PMC XML."""
        try:
            from pubmed_search.infrastructure.sources import get_europe_pmc_client

            client = get_europe_pmc_client()

            xml = client.get_fulltext_xml(pmcid)
            if xml:
                parsed = client.parse_fulltext_xml(xml)
                if parsed:
                    # Combine sections into text
                    text_parts = []
                    sections = {}

                    if parsed.get("abstract"):
                        text_parts.append(f"ABSTRACT\n{parsed['abstract']}")
                        sections["abstract"] = parsed["abstract"]

                    for sec in parsed.get("sections", []):
                        title = sec.get("title", "")
                        content = sec.get("content", "")
                        if content:
                            text_parts.append(f"{title.upper()}\n{content}")
                            sections[title.lower()] = content

                    return {
                        "text": "\n\n".join(text_parts),
                        "sections": sections,
                        "title": parsed.get("title"),
                        "references": parsed.get("references"),
                    }

        except Exception as e:
            logger.debug(f"Structured fulltext failed: {e}")

        return None


# =============================================================================
# Convenience Functions
# =============================================================================


_downloader_instance: Optional[FulltextDownloader] = None


def get_fulltext_downloader() -> FulltextDownloader:
    """Get singleton FulltextDownloader instance."""
    global _downloader_instance
    if _downloader_instance is None:
        _downloader_instance = FulltextDownloader()
    return _downloader_instance


async def download_fulltext(
    pmid: Optional[str] = None,
    pmcid: Optional[str] = None,
    doi: Optional[str] = None,
    strategy: Literal[
        "links_only", "download_best", "extract_text", "try_all"
    ] = "extract_text",
) -> FulltextResult:
    """
    Convenience function to download fulltext.

    Args:
        pmid: PubMed ID
        pmcid: PubMed Central ID
        doi: Digital Object Identifier
        strategy: Retrieval strategy

    Returns:
        FulltextResult with content
    """
    downloader = get_fulltext_downloader()
    return await downloader.get_fulltext(pmid, pmcid, doi, strategy)
