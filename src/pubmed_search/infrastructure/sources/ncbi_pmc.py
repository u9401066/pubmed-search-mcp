"""NCBI PubMed Central adapter for structured fulltext and identifier lookup.

NCBI is the canonical host of PMC. This adapter is the official-channel
fallback used when Europe PMC cannot supply a JATS body:

- ``efetch db=pmc`` returns the PMC JATS record (one article per request).
- ``esummary db=pubmed`` resolves a PMID to its PMCID and DOI.

Both calls carry the configured NCBI ``tool``/``email``/``api_key`` and draw
from the same process-wide ``ncbi-entrez`` rate budget as Bio.Entrez, because
NCBI meters E-utilities per key/IP rather than per database or client.

Publishers may forbid XML redistribution of articles deposited in PMC. NCBI
then returns front matter only, with an explicit notice instead of a body.
The adapter reports that state as ``access_restricted`` and never presents the
remaining front matter or the notice itself as article body text.

E-utilities can answer HTTP 200 without answering the question: an
``<ERROR>`` envelope, an empty body, or an empty articleset. Only an
articleset whose entries are NCBI's per-ID ``<error>`` statements (for
example "The following PMCID is not available") means "no record"; anything
else is an invalid response, so a backend hiccup never reads as a completed,
empty check.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from defusedxml import ElementTree  # Security: prevent XML attacks

from pubmed_search.domain.value_objects.article_identifiers import (
    normalize_pmcid,
    normalize_pmid,
    try_normalize_doi,
    try_normalize_pmcid,
)
from pubmed_search.infrastructure.ncbi.base import DEFAULT_ENTREZ_TOOL
from pubmed_search.infrastructure.sources.base_client import (
    _CONTINUE,
    APIRequestError,
    BaseAPIClient,
    raise_provider_schema_error,
    raise_sanitized_retryable_error,
)
from pubmed_search.infrastructure.sources.jats import parse_jats_article
from pubmed_search.infrastructure.sources.ncbi_extended import _require_summary_item
from pubmed_search.shared.async_utils import RetryableOperationError

from .contact import first_contact_email, get_source_contact_email
from .runtime import get_source_runtime

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PMC_ARTICLE_PAGE = "https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
DEFAULT_EMAIL = "pubmed-search-mcp@example.com"
# Shared with every Bio.Entrez operation (see infrastructure/ncbi/base.py).
NCBI_EUTILS_RATE_LIMIT = "ncbi-entrez"

_ARTICLE_ELEMENT_RE = re.compile(r"<(?:[A-Za-z_][\w.-]*:)?article[\s>/]")
_RESTRICTED_XML_RE = re.compile(
    r"does\s+not\s+allow\s+downloading\s+of\s+the\s+full\s+text",
    re.IGNORECASE,
)
_XML_PROLOG_RE = re.compile(r"<\?xml[^>]*\?>|<!DOCTYPE[^>]*>")


def _local_name(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _states_missing_record(payload: str) -> bool:
    """Whether an article-free efetch answer is NCBI's explicit "not available" statement.

    That answer is a ``pmc-articleset`` whose every entry is a per-ID
    ``<error>`` element with text. An E-utilities ``<ERROR>`` envelope (the
    element name is case-sensitive), an empty body, an empty articleset or
    unparsable XML does not say whether the record exists.
    """
    try:
        root = ElementTree.fromstring(_XML_PROLOG_RE.sub("", payload))
    except (ElementTree.ParseError, ValueError):
        return False
    if _local_name(root.tag) != "pmc-articleset":
        return False
    entries = [child for child in root if isinstance(child.tag, str)]
    return bool(entries) and all(_local_name(entry.tag) == "error" and (entry.text or "").strip() for entry in entries)


class NCBIPMCClient(BaseAPIClient):
    """NCBI E-utilities client for PMC JATS records and PubMed ID resolution."""

    _service_name = "NCBI PMC"
    # A fallback must not multiply latency: one retry, then report the outage.
    _MAX_RETRIES = 1

    def __init__(
        self,
        email: str | None = None,
        api_key: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._email = email or DEFAULT_EMAIL
        self._api_key = api_key
        super().__init__(
            timeout=timeout,
            # Identical budget to build_ncbi_execution_policy(): 3 req/s, or 10 with a key.
            min_interval=1.0 / (10.0 if api_key else 3.0),
            headers={
                "User-Agent": f"pubmed-search-mcp/1.0 (mailto:{self._email})",
                "Accept": "application/xml",
            },
        )
        self._rate_limiter_name = NCBI_EUTILS_RATE_LIMIT

    def _handle_expected_status(self, response: httpx.Response, url: str) -> Any:
        if response.status_code == 404:
            return None
        return _CONTINUE

    def _eutils_params(self, **params: str) -> dict[str, str]:
        """Attach NCBI's required client identification to one request."""
        identified = {**params, "tool": DEFAULT_ENTREZ_TOOL, "email": self._email}
        if self._api_key:
            identified["api_key"] = self._api_key
        return identified

    async def get_article_xml(self, pmcid: str) -> str | None:
        """Fetch the PMC JATS record for one PMCID.

        Returns:
            The raw ``pmc-articleset`` XML, or ``None`` when NCBI states that
            it holds no article for the identifier (HTTP 404 or a per-ID
            "not available" entry).

        Raises:
            ProviderSchemaError: HTTP 200 carried neither an article nor that
                statement (``<ERROR>`` envelope, empty body or articleset).
        """
        normalized = normalize_pmcid(pmcid)
        try:
            result = await self._make_request(
                f"{EUTILS_BASE}/efetch.fcgi",
                params=self._eutils_params(db="pmc", id=normalized[3:], retmode="xml"),
                expect_json=False,
            )
            if result is None:
                return None
            if not isinstance(result, str):
                raise_provider_schema_error(self._service_name)
            if _ARTICLE_ELEMENT_RE.search(result) is not None:
                return result
            if _states_missing_record(result):
                return None
            logger.warning("NCBI PMC efetch answered without an article or a missing-record statement")
            raise_provider_schema_error(self._service_name)
        except APIRequestError:
            raise
        except RetryableOperationError as exc:
            raise_sanitized_retryable_error(self._service_name, exc)
        except Exception as exc:
            logger.warning("NCBI PMC fulltext lookup failed (%s)", type(exc).__name__)
            raise APIRequestError(self._service_name) from None

    def parse_article_xml(self, xml_content: str) -> dict[str, Any]:
        """Parse PMC JATS with the shared parser and flag publisher restrictions.

        The returned mapping has the shared JATS shape plus
        ``access_restricted``. When NCBI states that the publisher does not
        allow XML download, ``sections`` is emptied: whatever remains is front
        matter or the notice itself, not article body.
        """
        parsed = parse_jats_article(xml_content, source=self._service_name)
        if _RESTRICTED_XML_RE.search(xml_content) is None:
            parsed["access_restricted"] = False
            return parsed
        body_sections = [
            section
            for section in parsed.get("sections", [])
            if _RESTRICTED_XML_RE.search(str(section.get("content") or "")) is None
            and str(section.get("content") or "").strip()
        ]
        restricted = not body_sections
        parsed["sections"] = body_sections
        parsed["access_restricted"] = restricted
        return parsed

    @staticmethod
    def article_page_url(pmcid: str) -> str:
        """Return the human-readable PMC landing page for one PMCID."""
        return PMC_ARTICLE_PAGE.format(pmcid=normalize_pmcid(pmcid))

    async def resolve_article_ids(self, pmid: str) -> dict[str, str] | None:
        """Resolve one PMID to its PMCID and DOI through ESummary.

        Returns:
            ``{"pmc_id": ..., "doi": ...}`` with only the identifiers NCBI
            declares, or ``None`` when PubMed has no record for the PMID.
        """
        normalized = normalize_pmid(pmid)
        try:
            payload = await self._make_request(
                f"{EUTILS_BASE}/esummary.fcgi",
                params=self._eutils_params(db="pubmed", id=normalized, retmode="json"),
                headers={"Accept": "application/json"},
            )
            if payload is None:
                return None
            row = _require_summary_item(payload, normalized)
            if row is None:
                return None
            raw_ids = row.get("articleids")
            if not isinstance(raw_ids, list):
                raise_provider_schema_error(self._service_name)
            identifiers: dict[str, str] = {}
            for entry in raw_ids:
                if not isinstance(entry, dict):
                    continue
                id_type, value = entry.get("idtype"), entry.get("value")
                if id_type == "pmc" and "pmc_id" not in identifiers:
                    pmcid = try_normalize_pmcid(value)
                    if pmcid:
                        identifiers["pmc_id"] = pmcid
                elif id_type == "doi" and "doi" not in identifiers:
                    doi = try_normalize_doi(value)
                    if doi:
                        identifiers["doi"] = doi
            return identifiers
        except APIRequestError:
            raise
        except RetryableOperationError as exc:
            raise_sanitized_retryable_error(self._service_name, exc)
        except Exception as exc:
            logger.warning("NCBI PubMed identifier lookup failed (%s)", type(exc).__name__)
            raise APIRequestError(self._service_name) from None


def get_ncbi_pmc_client(email: str | None = None, api_key: str | None = None) -> NCBIPMCClient:
    """Return the runtime-owned NCBI PMC client for the configured identity."""
    from pubmed_search.shared.settings import load_settings

    settings = load_settings()
    resolved_email = first_contact_email(email, get_source_contact_email(), settings.ncbi_email)
    resolved_api_key = api_key or settings.ncbi_api_key

    def _factory() -> NCBIPMCClient:
        return NCBIPMCClient(email=resolved_email, api_key=resolved_api_key)

    return get_source_runtime().get_or_create_client(("ncbi_pmc", resolved_email, resolved_api_key), _factory)


__all__ = ["EUTILS_BASE", "NCBIPMCClient", "get_ncbi_pmc_client"]
