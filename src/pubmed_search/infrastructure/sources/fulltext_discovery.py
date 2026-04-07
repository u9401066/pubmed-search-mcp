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

import logging
import re
from typing import TYPE_CHECKING, Any, cast

from .fulltext_models import PDFLink, PDFSource

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import httpx

logger = logging.getLogger(__name__)


class FulltextDiscoveryPhase:
    """Discovery phase for candidate fulltext links across external sources."""

    def __init__(self, client_getter: Callable[[], Awaitable[httpx.AsyncClient]]) -> None:
        self._get_client = client_getter

    async def get_pmc_links(self, pmid: str | None, pmcid: str | None) -> list[PDFLink]:
        links: list[PDFLink] = []

        if pmcid:
            pmc_num = pmcid.replace("PMC", "").replace("pmc", "")
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

        try:
            from Bio import Entrez

            handle = Entrez.elink(dbfrom="pubmed", db="pmc", id=pmid, linkname="pubmed_pmc")
            record = Entrez.read(handle)
            handle.close()
            record_any = cast("Any", record)
            first_record = record_any[0] if record_any else None

            if first_record and first_record.get("LinkSetDb"):
                for linkset in first_record["LinkSetDb"]:
                    if linkset.get("LinkName") != "pubmed_pmc":
                        continue
                    pmc_links = linkset.get("Link", [])
                    if not pmc_links:
                        continue
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
        except Exception as exc:
            logger.debug("PMC lookup failed: %s", exc)

        return links

    async def get_unpaywall_links(self, doi: str) -> list[PDFLink]:
        links: list[PDFLink] = []

        try:
            from pubmed_search.infrastructure.sources.unpaywall import get_unpaywall_client

            client = get_unpaywall_client()
            oa_info = await client.get_oa_status(doi)

            if oa_info and oa_info.get("is_oa"):
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
        except Exception as exc:
            logger.debug("Unpaywall lookup failed: %s", exc)

        return links

    async def get_core_links(self, doi: str) -> list[PDFLink]:
        links: list[PDFLink] = []

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
        except Exception as exc:
            logger.debug("CORE lookup failed: %s", exc)

        return links

    async def get_semantic_scholar_links(self, doi: str) -> list[PDFLink]:
        links: list[PDFLink] = []

        try:
            from pubmed_search.infrastructure.sources.semantic_scholar import SemanticScholarClient

            client = SemanticScholarClient()
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
        except Exception as exc:
            logger.debug("Semantic Scholar lookup failed: %s", exc)

        return links

    async def get_openalex_links(self, doi: str) -> list[PDFLink]:
        links: list[PDFLink] = []

        try:
            from pubmed_search.infrastructure.sources.openalex import OpenAlexClient

            client = OpenAlexClient()
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
        except Exception as exc:
            logger.debug("OpenAlex lookup failed: %s", exc)

        return links

    async def get_openurl_links(self, pmid: str | None, doi: str | None) -> list[PDFLink]:
        try:
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
        except Exception as exc:
            logger.debug("OpenURL resolver lookup failed: %s", exc)
            return []

    async def get_doi_redirect_link(self, doi: str) -> list[PDFLink]:
        doi_clean = doi.replace("https://doi.org/", "").replace("http://doi.org/", "").strip()
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

        try:
            client = await self._get_client()
            url = f"https://api.crossref.org/works/{doi}?mailto=pubmed-search@example.com"
            resp = await client.get(url)
            if resp.status_code != 200:
                return links

            message = resp.json().get("message", {})
            for link in message.get("link", []):
                content_type = link.get("content-type", "")
                link_url = link.get("URL", "")
                if not link_url:
                    continue

                if "pdf" in content_type.lower():
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
        except Exception as exc:
            logger.debug("CrossRef lookup failed: %s", exc)

        return links

    async def get_pubmed_linkout(self, pmid: str) -> list[PDFLink]:
        links: list[PDFLink] = []

        try:
            client = await self._get_client()
            url = (
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
                f"?dbfrom=pubmed&id={pmid}&cmd=llinks&retmode=json"
            )
            resp = await client.get(url)
            if resp.status_code != 200:
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
        except Exception as exc:
            logger.debug("PubMed LinkOut failed: %s", exc)

        return links

    async def get_doaj_links(self, doi: str) -> list[PDFLink]:
        links: list[PDFLink] = []

        try:
            client = await self._get_client()
            url = f"https://doaj.org/api/search/articles/doi:{doi}"
            resp = await client.get(url)
            if resp.status_code != 200:
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
        except Exception as exc:
            logger.debug("DOAJ lookup failed: %s", exc)

        return links

    async def get_zenodo_links(self, doi: str) -> list[PDFLink]:
        links: list[PDFLink] = []

        try:
            client = await self._get_client()
            if "10.5281/zenodo" in doi:
                record_id = doi.rsplit(".", maxsplit=1)[-1]
                url = f"https://zenodo.org/api/records/{record_id}"
            else:
                url = f"https://zenodo.org/api/records?q=doi:{doi}&size=1"

            resp = await client.get(url)
            if resp.status_code != 200:
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
        except Exception as exc:
            logger.debug("Zenodo lookup failed: %s", exc)

        return links


__all__ = ["FulltextDiscoveryPhase"]
