"""Fulltext discovery phase for collecting candidate links before download.

Design:
    This module owns source-specific link discovery only. It turns normalized
    identifiers such as PMID, PMCID, and DOI into ordered PDF/fulltext
    candidates, but does not download content or extract text.

Maintenance:
    Add new external sources here when they only contribute candidate URLs.
    Keep source priority and result shaping aligned with fulltext_models.py and
    leave HTTP transfer behavior to fulltext_fetch.py.
"""

from __future__ import annotations

import asyncio
import os
import re
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

from defusedxml import ElementTree

from pubmed_search.domain.value_objects import normalize_doi, normalize_pmcid, normalize_pmid
from pubmed_search.infrastructure.http.safe_outbound import SafeFetchPolicy, fetch_public_url
from pubmed_search.infrastructure.provider_payload import is_provider_error_envelope
from pubmed_search.infrastructure.sources.base_client import raise_provider_schema_error

from .contact import first_contact_email, get_source_contact_email
from .fulltext_models import PDFLink, PDFSource

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import httpx

PMC_LINK_LOOKUP_TIMEOUT_SECONDS = 15.0
NCBI_ELINK_ENDPOINT = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
DEFAULT_CROSSREF_MAILTO = "pubmed-search@example.com"
EXPECTED_ABSENCE_STATUS_CODES = frozenset({204, 404})


def _response_is_expected_absence(response: httpx.Response) -> bool:
    """Return whether a provider explicitly reported that no record exists.

    Every other non-success response is raised to the source-adapter boundary,
    which owns sanitized failure reporting and partial-coverage accounting.
    """
    if response.status_code in EXPECTED_ABSENCE_STATUS_CODES:
        return True
    response.raise_for_status()
    if response.status_code != 200:
        msg = "Fulltext discovery provider returned an unsupported success status"
        raise RuntimeError(msg)
    return False


def _lookup_pmc_links_from_entrez(pmid: str) -> list[PDFLink]:
    """Resolve PMC links via a timeout-bounded ELink request."""
    links: list[PDFLink] = []

    params = {
        "dbfrom": "pubmed",
        "db": "pmc",
        "id": normalize_pmid(pmid),
        "linkname": "pubmed_pmc",
        "retmode": "xml",
        "tool": "pubmed-search-mcp",
    }
    request_url = f"{NCBI_ELINK_ENDPOINT}?{urllib.parse.urlencode(params)}"

    # The URL is assembled from a fixed HTTPS NCBI endpoint plus encoded scalar parameters.
    with urllib.request.urlopen(  # noqa: S310  # nosec B310
        request_url, timeout=PMC_LINK_LOOKUP_TIMEOUT_SECONDS
    ) as response:
        payload = response.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024:
            raise_provider_schema_error("NCBI PMC links")

    root = ElementTree.fromstring(payload)
    if root.tag != "eLinkResult" or root.find(".//ERROR") is not None:
        raise_provider_schema_error("NCBI PMC links")
    for linkset in root.findall("./LinkSet/LinkSetDb"):
        link_name = linkset.findtext("LinkName", default="")
        if link_name != "pubmed_pmc":
            continue
        for link in linkset.findall("./Link"):
            pmc_id = link.findtext("Id", default="").strip()
            if not pmc_id:
                continue
            links.append(
                PDFLink(
                    url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/{normalize_pmcid(pmc_id)}/pdf/",
                    source=PDFSource.PMC,
                    access_type="open_access",
                    version="published",
                    is_direct_pdf=True,
                    confidence=0.95,
                )
            )
            break
    return links


class FulltextDiscoveryPhase:
    """Discovery phase for candidate fulltext links across external sources."""

    def __init__(self, client_getter: Callable[[], Awaitable[httpx.AsyncClient]]) -> None:
        self._get_client = client_getter

    async def _request_metadata(self, url: str) -> httpx.Response:
        """Bound provider metadata transfers with the common outbound policy."""
        fetched = await fetch_public_url(
            url,
            client=await self._get_client(),
            policy=SafeFetchPolicy(max_bytes=8 * 1024 * 1024, total_timeout=15.0),
        )
        response = fetched.response
        if response.status_code == 200:
            payload = response.json()
            if not isinstance(payload, dict) or is_provider_error_envelope(payload):
                raise_provider_schema_error("Fulltext link discovery")
        return response

    async def get_pmc_links(self, pmid: str | None, pmcid: str | None) -> list[PDFLink]:
        links: list[PDFLink] = []

        if pmcid:
            pmc_num = normalize_pmcid(pmcid).removeprefix("PMC")
            links.append(
                PDFLink(
                    url=f"https://europepmc.org/backend/ptpmcrender.fcgi?accid=PMC{pmc_num}&blobtype=pdf",
                    source=PDFSource.EUROPE_PMC,
                    access_type="open_access",
                    version="published",
                    is_direct_pdf=True,
                    confidence=0.95,
                )
            )
            links.append(
                PDFLink(
                    url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_num}/pdf/",
                    source=PDFSource.PMC,
                    access_type="open_access",
                    version="published",
                    is_direct_pdf=False,
                    confidence=0.7,
                )
            )
            return links

        if not pmid:
            return links

        links.extend(
            await asyncio.wait_for(
                asyncio.to_thread(_lookup_pmc_links_from_entrez, pmid),
                timeout=PMC_LINK_LOOKUP_TIMEOUT_SECONDS,
            )
        )

        return links

    async def get_unpaywall_links(self, doi: str) -> list[PDFLink]:
        links: list[PDFLink] = []

        from pubmed_search.infrastructure.sources import get_unpaywall_client

        client = get_unpaywall_client()
        oa_info = await client.get_oa_status(doi)

        if oa_info and oa_info.get("is_oa"):
            best = oa_info.get("best_oa_location") or {}
            if best.get("url_for_pdf"):
                host_type = best.get("host_type", "unknown")
                source = PDFSource.UNPAYWALL_PUBLISHER if host_type == "publisher" else PDFSource.UNPAYWALL_REPOSITORY
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

            for loc in (oa_info.get("oa_locations") or [])[:3]:
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

        return links

    async def get_core_links(self, doi: str) -> list[PDFLink]:
        links: list[PDFLink] = []

        from pubmed_search.infrastructure.sources import get_core_client

        client = get_core_client()
        results = await client.search(f'doi:"{doi}"', limit=1)

        if results.get("results"):
            work = results["results"][0]
            if work.get("download_url"):
                links.append(
                    PDFLink(
                        url=work["download_url"],
                        source=PDFSource.CORE,
                        access_type="open_access",
                        is_direct_pdf=True,
                        confidence=0.85,
                    )
                )

        return links

    async def get_semantic_scholar_links(self, doi: str) -> list[PDFLink]:
        links: list[PDFLink] = []

        from pubmed_search.infrastructure.sources import get_semantic_scholar_client

        client = get_semantic_scholar_client()
        paper = await client.get_paper(f"DOI:{doi}")

        if paper and paper.get("pdf_url"):
            links.append(
                PDFLink(
                    url=paper["pdf_url"],
                    source=PDFSource.SEMANTIC_SCHOLAR,
                    access_type="open_access" if paper.get("is_open_access") else "unknown",
                    is_direct_pdf=True,
                    confidence=0.8,
                )
            )

        return links

    async def get_openalex_links(self, doi: str) -> list[PDFLink]:
        links: list[PDFLink] = []

        from pubmed_search.infrastructure.sources import get_openalex_client

        client = get_openalex_client()
        work = await client.get_work(f"doi:{doi}")

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

        return links

    async def get_openurl_links(self, pmid: str | None, doi: str | None) -> list[PDFLink]:
        from pubmed_search.infrastructure.sources.openurl import get_openurl_link

        article: dict[str, str] = {}
        if pmid:
            article["pmid"] = pmid
        if doi:
            article["doi"] = doi
        if not article:
            return []

        resolver_url = get_openurl_link(article)
        if not resolver_url:
            return []

        return [
            PDFLink(
                url=resolver_url,
                source=PDFSource.INSTITUTIONAL_RESOLVER,
                access_type="subscription",
                is_direct_pdf=False,
                confidence=0.8,
            )
        ]

    async def get_doi_redirect_link(self, doi: str) -> list[PDFLink]:
        doi_clean = normalize_doi(doi)
        if not doi_clean:
            return []

        return [
            PDFLink(
                url=f"https://doi.org/{doi_clean}",
                source=PDFSource.DOI_REDIRECT,
                access_type="unknown",
                is_direct_pdf=False,
                confidence=0.55,
            )
        ]

    async def get_arxiv_link(self, doi: str) -> PDFLink | None:
        match = re.search(r"arxiv[./:](\d+\.\d+)(v\d+)?", doi.lower())
        if not match:
            return None

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

    async def get_preprint_link(self, doi: str) -> PDFLink | None:
        doi_clean = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")

        if "10.1101/" in doi_clean:
            if "biorxiv" in doi.lower():
                base_url = f"https://www.biorxiv.org/content/{doi_clean}"
            elif "medrxiv" in doi.lower():
                base_url = f"https://www.medrxiv.org/content/{doi_clean}"
            else:
                base_url = f"https://www.biorxiv.org/content/{doi_clean}"

            return PDFLink(
                url=f"{base_url}v1.full.pdf",
                source=PDFSource.BIORXIV if "biorxiv" in base_url else PDFSource.MEDRXIV,
                access_type="open_access",
                version="submitted",
                is_direct_pdf=True,
                confidence=0.85,
            )

        if "biorxiv" in doi.lower():
            return PDFLink(
                url=f"https://www.biorxiv.org/content/{doi_clean}.full.pdf",
                source=PDFSource.BIORXIV,
                access_type="open_access",
                version="submitted",
                is_direct_pdf=True,
                confidence=0.7,
            )
        if "medrxiv" in doi.lower():
            return PDFLink(
                url=f"https://www.medrxiv.org/content/{doi_clean}.full.pdf",
                source=PDFSource.MEDRXIV,
                access_type="open_access",
                version="submitted",
                is_direct_pdf=True,
                confidence=0.7,
            )
        return None

    async def get_crossref_links(self, doi: str) -> list[PDFLink]:
        links: list[PDFLink] = []

        encoded_doi = urllib.parse.quote(normalize_doi(doi), safe="")
        mailto = first_contact_email(
            os.environ.get("CROSSREF_EMAIL"),
            get_source_contact_email(),
            os.environ.get("NCBI_EMAIL"),
            DEFAULT_CROSSREF_MAILTO,
        )
        url = f"https://api.crossref.org/works/{encoded_doi}?mailto={urllib.parse.quote(mailto or DEFAULT_CROSSREF_MAILTO)}"
        resp = await self._request_metadata(url)
        if _response_is_expected_absence(resp):
            return links

        message = resp.json().get("message")
        if not isinstance(message, dict):
            raise_provider_schema_error("Crossref link discovery")
        for link in message.get("link") or []:
            content_type = link.get("content-type", "")
            link_url = link.get("URL", "")
            if not link_url:
                continue

            looks_like_pdf_url = (
                link_url.lower().endswith(".pdf")
                or "articlepdf" in link_url.lower()
                or "/pdf/" in link_url.lower()
                or "content/pdf/" in link_url.lower()
            )

            if "pdf" in content_type.lower() or (content_type.lower() == "unspecified" and looks_like_pdf_url):
                links.append(
                    PDFLink(
                        url=link_url,
                        source=PDFSource.CROSSREF,
                        access_type="unknown",
                        is_direct_pdf=True,
                        confidence=0.85,
                    )
                )
            elif "xml" in content_type.lower() or "html" in content_type.lower():
                links.append(
                    PDFLink(
                        url=link_url,
                        source=PDFSource.CROSSREF,
                        access_type="unknown",
                        is_direct_pdf=False,
                        confidence=0.6,
                    )
                )

        return links

    async def get_pubmed_linkout(self, pmid: str) -> list[PDFLink]:
        links: list[PDFLink] = []

        url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?dbfrom=pubmed&id={normalize_pmid(pmid)}&cmd=llinks&retmode=json"
        resp = await self._request_metadata(url)
        if _response_is_expected_absence(resp):
            return links

        data = resp.json()
        for linkset in data.get("linksets", []):
            for urllist in linkset.get("idurllist", []):
                for objurl in urllist.get("objurls", []):
                    link_url = objurl.get("url", {}).get("value", "")
                    provider = objurl.get("provider", {}).get("name", "")
                    if not link_url or "ncbi.nlm.nih.gov" in link_url:
                        continue

                    is_pdf = link_url.endswith(".pdf") or "pdf" in link_url.lower() or "fulltext" in provider.lower()
                    links.append(
                        PDFLink(
                            url=link_url,
                            source=PDFSource.DOI_REDIRECT,
                            access_type="unknown",
                            is_direct_pdf=is_pdf,
                            confidence=0.7 if is_pdf else 0.5,
                        )
                    )

        return links

    async def get_doaj_links(self, doi: str) -> list[PDFLink]:
        links: list[PDFLink] = []

        url = f"https://doaj.org/api/search/articles/{urllib.parse.quote('doi:' + normalize_doi(doi), safe='')}"
        resp = await self._request_metadata(url)
        if _response_is_expected_absence(resp):
            return links

        for result in resp.json().get("results", []):
            bibjson = result.get("bibjson", {})
            for link in bibjson.get("link", []):
                link_url = link.get("url", "")
                link_type = link.get("type", "")
                if not link_url:
                    continue
                links.append(
                    PDFLink(
                        url=link_url,
                        source=PDFSource.DOAJ,
                        access_type="gold",
                        is_direct_pdf="fulltext" in link_type.lower(),
                        confidence=0.9 if "fulltext" in link_type.lower() else 0.7,
                    )
                )

        return links

    async def get_zenodo_links(self, doi: str) -> list[PDFLink]:
        links: list[PDFLink] = []

        if "10.5281/zenodo" in doi:
            record_id = doi.rsplit(".", maxsplit=1)[-1]
            url = f"https://zenodo.org/api/records/{urllib.parse.quote(record_id, safe='')}"
        else:
            url = "https://zenodo.org/api/records?" + urllib.parse.urlencode(
                {"q": f'doi:"{normalize_doi(doi)}"', "size": 1}
            )

        resp = await self._request_metadata(url)
        if _response_is_expected_absence(resp):
            return links

        data = resp.json()
        records = [data] if "id" in data else data.get("hits", {}).get("hits", [])
        for record in records:
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

        return links


__all__ = ["FulltextDiscoveryPhase"]
