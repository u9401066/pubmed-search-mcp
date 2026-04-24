"""
Entrez PDF Module - PMC PDF Download Functionality

Provides functionality to download PDFs from PubMed Central Open Access.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from Bio import Entrez

from pubmed_search.shared.async_utils import get_shared_async_client

from .base import DEFAULT_ENTREZ_TOOL, execute_entrez_operation, run_entrez_callable

logger = logging.getLogger(__name__)


async def _read_entrez_handle(handle: Any) -> Any:
    """Read an Entrez handle and always close it."""
    try:
        return await asyncio.to_thread(Entrez.read, handle)
    finally:
        handle.close()


class PDFMixin:
    """
    Mixin providing PDF download functionality from PMC.

    Methods:
        get_pmc_fulltext_url: Get URL for PMC full text PDF
        download_pmc_pdf: Download PDF from PMC Open Access
    """

    async def _execute_entrez(self, operation, *, service_name: str, timeout: float = 45.0):
        """Execute one PDF-related Entrez operation through the shared transport."""
        if hasattr(self, "_execute_entrez_call"):
            return await self._execute_entrez_call(operation, service_name=service_name, timeout=timeout)
        return await execute_entrez_operation(
            operation,
            api_key=getattr(self, "_api_key", None),
            service_name=service_name,
            timeout=timeout,
        )

    def _entrez_runtime_kwargs(self) -> dict[str, Any]:
        """Return consistent Bio.Entrez runtime metadata for PDF lookups."""
        return {
            "email": getattr(self, "_email", None),
            "api_key": getattr(self, "_api_key", None),
            "tool": getattr(self, "_tool", DEFAULT_ENTREZ_TOOL),
        }

    async def _lookup_pmc_link_record(self, pmid: str) -> Any:
        """Resolve one PMID to an Entrez elink PMC record through the shared path."""

        async def _do_lookup() -> Any:
            handle = await asyncio.to_thread(
                run_entrez_callable,
                Entrez,
                Entrez.elink,
                dbfrom="pubmed",
                db="pmc",
                id=pmid,
                linkname="pubmed_pmc",
                **self._entrez_runtime_kwargs(),
            )
            return await _read_entrez_handle(handle)

        return await self._execute_entrez(_do_lookup, service_name="ncbi-pdf:elink")

    @staticmethod
    def _extract_pmc_id_from_record(record: Any) -> str | None:
        """Extract the first PMC id from an Entrez elink record."""
        if record and record[0].get("LinkSetDb"):
            for linkset in record[0]["LinkSetDb"]:
                if linkset.get("LinkName") == "pubmed_pmc":
                    links = linkset.get("Link", [])
                    if links:
                        return str(links[0]["Id"])
        return None

    async def get_pmc_fulltext_url(self, pmid: str) -> str | None:
        """
        Get the PubMed Central full text URL if available (Open Access).
        Uses elink to find PMC ID and constructs the download URL.

        Args:
            pmid: PubMed ID.

        Returns:
            URL to download full text PDF, or None if not available.
        """
        try:
            record = await self._lookup_pmc_link_record(pmid)
            pmc_id = self._extract_pmc_id_from_record(record)
            if pmc_id:
                return f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id}/pdf/"
            return None
        except Exception as e:
            logger.exception(f"Error getting PMC URL: {e}")
            return None

    async def download_pmc_pdf(self, pmid: str, output_path: str) -> bool:
        """
        Download PDF from PubMed Central if available.

        Args:
            pmid: PubMed ID.
            output_path: Path to save the PDF file.

        Returns:
            True if download successful, False otherwise.
        """
        try:
            # First, get PMC ID via elink
            pmc_id = await self._get_pmc_id(pmid)

            if not pmc_id:
                logger.info(f"PMID {pmid}: No PMC ID found - article not in PubMed Central Open Access")
                return False

            logger.info(f"PMID {pmid}: Found PMC ID {pmc_id}, attempting PDF download...")

            # Try to get the PDF from PMC
            oa_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id}/pdf/"

            headers = {"User-Agent": "Mozilla/5.0 (compatible; pubmed-search/1.0)"}

            client = get_shared_async_client()
            response = await client.get(
                oa_url,
                headers=headers,
            )

            content_type = response.headers.get("Content-Type", "")

            if response.status_code == 200 and "application/pdf" in content_type:
                await asyncio.to_thread(Path(output_path).write_bytes, response.content)
                logger.info(f"PMID {pmid}: PDF downloaded successfully ({len(response.content)} bytes)")
                return True

            logger.warning(
                f"PMID {pmid}: PDF download failed - status={response.status_code}, content_type={content_type}"
            )
            return False
        except Exception as e:
            logger.exception(f"PMID {pmid}: Error downloading PDF - {e}")
            return False

    async def download_pdf(self, pmid: str, output_path: str | None = None) -> bytes | None:
        """
        Download PDF and return as bytes.

        Args:
            pmid: PubMed ID.
            output_path: Optional path to save the PDF file.

        Returns:
            PDF content as bytes, or None if not available.
        """
        try:
            pmc_id = await self._get_pmc_id(pmid)

            if not pmc_id:
                return None

            oa_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id}/pdf/"

            headers = {"User-Agent": "Mozilla/5.0 (compatible; pubmed-search/1.0)"}

            client = get_shared_async_client()
            response = await client.get(
                oa_url,
                headers=headers,
            )

            content_type = response.headers.get("Content-Type", "")

            if response.status_code == 200 and "application/pdf" in content_type:
                if output_path:
                    await asyncio.to_thread(Path(output_path).write_bytes, response.content)
                return response.content

            return None
        except Exception as e:
            logger.exception(f"PMID {pmid}: Error downloading PDF - {e}")
            return None

    async def _get_pmc_id(self, pmid: str) -> str | None:
        """
        Get PMC ID for a given PMID using elink.

        Args:
            pmid: PubMed ID.

        Returns:
            PMC ID if available, None otherwise.
        """
        try:
            record = await self._lookup_pmc_link_record(pmid)
            pmc_id = self._extract_pmc_id_from_record(record)
            if pmc_id:
                logger.debug(f"PMID {pmid} -> PMC{pmc_id}")
                return pmc_id
            logger.debug(f"PMID {pmid}: No PMC link found")
            return None
        except Exception as e:
            logger.exception(f"PMID {pmid}: Error looking up PMC ID - {e}")
            return None
