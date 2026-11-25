"""Application service for policy-driven fulltext retrieval orchestration.

Design:
    This module chooses retrieval policy, coordinates source adapters, and
    shapes a tool-friendly result object. It sits above infrastructure clients
    and below the MCP presentation layer, making DDD boundaries explicit.

Maintenance:
    Add policy or orchestration changes here, not in the presentation layer.
    Keep source-specific transport logic delegated to infrastructure factories
    so this service remains testable with pure doubles.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from functools import partial
from typing import Any, Literal

from pubmed_search.domain.value_objects.article_identifiers import (
    IdentifierValidationError,
    normalize_doi,
    normalize_pmcid,
    normalize_pmid,
    parse_article_identifier,
)
from pubmed_search.shared.exceptions import ParseError

from .coverage import (
    FulltextSkippedSource,
    FulltextSourceError,
    FulltextSourceNotice,
    FulltextSourceNoticeCode,
    classify_link_discovery_error,
    classify_source_failure,
    deadline_exceeded,
    make_notice,
    require_source_key,
)
from .racing import FulltextDeadline, HedgedAttempt, HedgedOutcome, run_hedged
from .registry import FulltextRegistry, get_fulltext_registry
from .sections import SectionSelection, select_sections

logger = logging.getLogger(__name__)

LogLevel = Literal["debug", "info", "warning", "error"]
ProgressCallback = Callable[[float, float, str], Awaitable[None]]
LogCallback = Callable[[LogLevel, str], Awaitable[None]]

# Mirrors shared.settings.DEFAULT_FULLTEXT_DEADLINE_SECONDS; importing settings here
# would load pydantic-settings on every tool import (see tests/test_import_surface.py).
DEFAULT_FULLTEXT_DEADLINE_SECONDS = 90.0
"""Overall get_fulltext budget; sources not started in time are reported as skipped."""
DEFAULT_STRUCTURED_HEDGE_SECONDS = 6.0
"""Wait this long for the preferred structured source before also asking the fallback."""
_STRUCTURED_SOURCES = frozenset({"europe_pmc", "ncbi_pmc"})
_METADATA_SOURCES = ("europe_pmc_metadata", "ncbi_metadata")


@dataclass(frozen=True)
class FulltextRequest:
    """Normalized request envelope consumed by the fulltext application service."""

    identifier: str | None = None
    pmcid: str | None = None
    pmid: str | None = None
    doi: str | None = None
    sections: str | None = None
    include_figures: bool = False
    extended_sources: bool = False
    allow_browser_session: bool | None = None
    include_pdf_links: bool = True

    def normalized(self) -> FulltextRequest:
        """Return a strict, canonical request with exactly one public identifier.

        A bare numeric ``identifier`` is always a PMID.  PMCID auto-detection
        therefore requires an explicit ``PMC`` prefix; this prevents long
        PMIDs from silently being reinterpreted as PMC identifiers.
        """
        supplied = [
            name
            for name, value in (
                ("identifier", self.identifier),
                ("pmcid", self.pmcid),
                ("pmid", self.pmid),
                ("doi", self.doi),
            )
            if value is not None
        ]
        if len(supplied) != 1:
            raise IdentifierValidationError("provide exactly one of identifier, pmcid, pmid, or doi")
        if not isinstance(getattr(self, supplied[0]), str):
            raise IdentifierValidationError("article identifiers must be strings")

        if self.identifier is not None:
            parsed = parse_article_identifier(self.identifier)
            return replace(
                self,
                identifier=None,
                pmcid=parsed.value if parsed.kind == "pmcid" else None,
                pmid=parsed.value if parsed.kind == "pmid" else None,
                doi=parsed.value if parsed.kind == "doi" else None,
            )
        if self.pmcid is not None:
            return replace(self, pmcid=normalize_pmcid(self.pmcid))
        if self.pmid is not None:
            return replace(self, pmid=normalize_pmid(self.pmid))
        if self.doi is not None:
            return replace(self, doi=normalize_doi(self.doi))
        raise AssertionError("identifier one-of validation is exhaustive")


@dataclass(frozen=True, slots=True)
class FulltextDownloadNotice:
    """Download facts for presentation; no Markdown or infrastructure types."""

    source: str | None
    source_name: str | None
    retrieved_url: str | None
    has_text: bool
    error: bool


@dataclass
class FulltextServiceResult:
    """Normalized result returned to the tool formatting layer."""

    identifier: str | None = None
    section_selection: SectionSelection | None = None
    pmcid: str | None = None
    pmid: str | None = None
    doi: str | None = None
    policy_key: str | None = None
    title: str | None = None
    fulltext_content: str | None = None
    raw_fulltext_content: str | None = None
    content_sections: list[dict[str, Any]] = field(default_factory=list)
    pdf_links: list[dict[str, Any]] = field(default_factory=list)
    sources_tried: list[str] = field(default_factory=list)
    sources_completed: list[str] = field(default_factory=list)
    source_errors: list[FulltextSourceError] = field(default_factory=list)
    source_notices: list[FulltextSourceNotice] = field(default_factory=list)
    sources_skipped: list[FulltextSkippedSource] = field(default_factory=list)
    figures: list[dict[str, Any]] = field(default_factory=list)
    fulltext_source_name: str | None = None
    fulltext_canonical_host: str | None = None
    fulltext_provenance: Literal["direct", "indirect", "derived", "mixed"] | None = None
    fulltext_license: dict[str, str] | None = None
    extended_sources_attempted: bool = False
    fallback_notice: FulltextDownloadNotice | None = None
    deadline_seconds: float | None = None

    def __post_init__(self) -> None:
        for field_name, sources in (
            ("sources_tried", self.sources_tried),
            ("sources_completed", self.sources_completed),
        ):
            for source in sources:
                require_source_key(source)
            if len(sources) != len(set(sources)):
                msg = f"FulltextServiceResult.{field_name} must not contain duplicate source keys"
                raise ValueError(msg)
        attempted = set(self.sources_tried)
        if not set(self.sources_completed).issubset(attempted):
            msg = "Completed fulltext sources must be a subset of attempted sources"
            raise ValueError(msg)
        if any(error.source not in attempted for error in self.source_errors):
            msg = "Fulltext source errors must belong to attempted sources"
            raise ValueError(msg)
        if any(notice.source not in attempted for notice in self.source_notices):
            msg = "Fulltext source notices must belong to attempted sources"
            raise ValueError(msg)
        if any(skipped.source in attempted for skipped in self.sources_skipped):
            msg = "Skipped fulltext sources cannot also be attempted"
            raise ValueError(msg)

    @property
    def has_retrieved_text(self) -> bool:
        """A missing section is not a failed download and must not fan out to PDFs."""
        return bool(self.fulltext_content or (self.section_selection and self.section_selection.body_available))

    @property
    def coverage_status(self) -> Literal["complete", "partial", "unavailable"]:
        """Describe whether every source the policy wanted actually completed.

        A source skipped at the deadline is unchecked, so coverage cannot be
        complete even though nothing failed.
        """
        if not self.source_errors and not self.sources_skipped:
            return "complete"
        if self.sources_completed or self.fulltext_content or self.pdf_links or self.figures:
            return "partial"
        return "unavailable"

    def record_source_attempted(self, source: str) -> None:
        source = require_source_key(source)
        if any(skipped.source == source for skipped in self.sources_skipped):
            msg = "A skipped fulltext source cannot be attempted"
            raise ValueError(msg)
        if source not in self.sources_tried:
            self.sources_tried.append(source)

    def record_source_completed(self, source: str) -> None:
        source = require_source_key(source)
        if source not in self.sources_tried:
            msg = "A fulltext source must be attempted before it can complete"
            raise ValueError(msg)
        if source not in self.sources_completed:
            self.sources_completed.append(source)

    def record_source_error(self, source: str, error: FulltextSourceError | None = None) -> None:
        """Record the first classified failure of an attempted source."""
        source = require_source_key(source)
        if source not in self.sources_tried:
            msg = "A fulltext source must be attempted before it can fail"
            raise ValueError(msg)
        if error is not None and error.source != source:
            msg = "A fulltext source error must describe the failing source"
            raise ValueError(msg)
        if all(issue.source != source for issue in self.source_errors):
            self.source_errors.append(error or FulltextSourceError(source=source))

    def record_source_notice(self, source: str, code: FulltextSourceNoticeCode) -> None:
        """Record a non-error outcome the agent must not misread as fulltext."""
        source = require_source_key(source)
        if source not in self.sources_tried:
            msg = "A fulltext source must be attempted before it can carry a notice"
            raise ValueError(msg)
        if all(notice.source != source or notice.code != code for notice in self.source_notices):
            self.source_notices.append(make_notice(source, code))

    def record_source_skipped(self, source: str) -> None:
        """Record a policy source that was never started because time ran out."""
        source = require_source_key(source)
        if source in self.sources_tried:
            msg = "An attempted fulltext source cannot be skipped"
            raise ValueError(msg)
        if all(skipped.source != source for skipped in self.sources_skipped):
            self.sources_skipped.append(FulltextSkippedSource(source=source))


@dataclass(frozen=True, slots=True)
class _StructuredDocument:
    """Parsed JATS from one structured source, before section selection."""

    parsed: dict[str, Any] | None
    restricted: bool = False

    @property
    def has_body(self) -> bool:
        if not self.parsed or self.restricted:
            return False
        return any(str(section.get("content") or "").strip() for section in self.parsed.get("sections", []))


class FulltextService:
    """Policy-driven fulltext orchestration application service."""

    def __init__(
        self,
        *,
        registry: FulltextRegistry | None = None,
        europe_pmc_client_factory: Callable[[], Any],
        unpaywall_client_factory: Callable[[], Any],
        core_client_factory: Callable[[], Any],
        downloader_factory: Callable[[], Any],
        figure_client_factory: Callable[[], Any] | None = None,
        institutional_client_factory: Callable[[], Any] | None = None,
        structured_xml_fetcher: Callable[[str], Awaitable[str | None]] | None = None,
        ncbi_pmc_client_factory: Callable[[], Any] | None = None,
        deadline_seconds: float | None = DEFAULT_FULLTEXT_DEADLINE_SECONDS,
        structured_hedge_seconds: float = DEFAULT_STRUCTURED_HEDGE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            isinstance(structured_hedge_seconds, bool)
            or not isinstance(structured_hedge_seconds, (int, float))
            or not 0 <= structured_hedge_seconds < float("inf")
        ):
            raise ValueError("structured_hedge_seconds must be a finite, non-negative number")
        FulltextDeadline(deadline_seconds, clock=clock)  # validate eagerly
        self._registry = registry or get_fulltext_registry()
        self._europe_pmc_client_factory = europe_pmc_client_factory
        self._unpaywall_client_factory = unpaywall_client_factory
        self._core_client_factory = core_client_factory
        self._downloader_factory = downloader_factory
        self._figure_client_factory = figure_client_factory
        self._institutional_client_factory = institutional_client_factory
        self._structured_xml_fetcher = structured_xml_fetcher
        self._ncbi_pmc_client_factory = ncbi_pmc_client_factory
        self._deadline_seconds = deadline_seconds
        self._hedge_seconds = float(structured_hedge_seconds)
        self._clock = clock

    async def retrieve(
        self,
        request: FulltextRequest,
        *,
        progress: ProgressCallback | None = None,
        log: LogCallback | None = None,
    ) -> FulltextServiceResult:
        """Execute fulltext retrieval according to registry policy.

        Structured PMC sources run first. Europe PMC is preferred; NCBI PMC is
        hedged in when Europe PMC fails, has no body, or is slow. Optional
        link/PDF sources then run only while the overall deadline allows, and
        every source's fate (completed, failed with a typed reason, superseded,
        skipped at the deadline) is recorded for the agent.
        """
        request = request.normalized()
        deadline = FulltextDeadline(self._deadline_seconds, clock=self._clock)
        request, metadata_outcomes = await self._resolve_identifiers(request, log, deadline)
        policy = self._registry.resolve_policy(
            pmcid=request.pmcid,
            pmid=request.pmid,
            doi=request.doi,
            extended_sources=request.extended_sources,
        )
        result = FulltextServiceResult(
            identifier=request.identifier,
            pmcid=request.pmcid,
            pmid=request.pmid,
            doi=request.doi,
            policy_key=policy.key,
            deadline_seconds=deadline.seconds,
        )
        await self._record_hedged_outcomes(result, metadata_outcomes, log, deadline)

        structured_done = False
        for source in policy.sources:
            if source in _STRUCTURED_SOURCES:
                if not structured_done and request.pmcid:
                    structured_done = True
                    await self._collect_structured(request, result, policy.sources, progress, log, deadline)
            elif source == "unpaywall" and request.doi and (request.include_pdf_links or not result.has_retrieved_text):
                await self._report_progress(progress, 3, 6, "Checking Unpaywall open-access locations...")
                await self._run_bounded(
                    source, result, deadline, partial(self._collect_unpaywall, request, result, log)
                )
            elif (
                source == "institutional"
                and request.doi
                and not result.has_retrieved_text
                and self._institutional_client_factory is not None
            ):
                await self._report_progress(progress, 3, 6, "Trying institutional direct/EZproxy fetch...")
                await self._run_bounded(
                    source, result, deadline, partial(self._collect_institutional, request, result, log)
                )
            elif source == "core" and request.doi and not result.has_retrieved_text:
                await self._report_progress(progress, 4, 6, "Trying CORE fallback...")
                await self._run_bounded(source, result, deadline, partial(self._collect_core, request, result, log))
            elif source == "extended" and request.extended_sources:
                await self._report_progress(progress, 5, 6, "Checking extended fulltext sources...")
                await self._run_bounded(
                    source,
                    result,
                    deadline,
                    partial(self._collect_download, request, result, log, source="extended"),
                    before=partial(setattr, result, "extended_sources_attempted", True),
                )
            elif (
                source == "pdf_retrieval_fallback"
                and not result.has_retrieved_text
                and not result.extended_sources_attempted
            ):
                await self._report_progress(progress, 5.5, 6, "Trying multi-source PDF retrieval fallback...")
                await self._run_bounded(
                    source,
                    result,
                    deadline,
                    partial(self._collect_download, request, result, log, source="pdf_retrieval_fallback"),
                )

        if request.include_figures and request.pmcid and self._figure_client_factory is not None:
            await self._run_bounded(
                "pmc_figures", result, deadline, partial(self._collect_figures, request, result, log)
            )

        result.pdf_links = self._deduplicate_link_rows(result.pdf_links)
        return result

    async def _run_bounded(
        self,
        source: str,
        result: FulltextServiceResult,
        deadline: FulltextDeadline,
        operation: Callable[[], Awaitable[None]],
        *,
        before: Callable[[], object] | None = None,
    ) -> None:
        """Run one optional source inside the remaining request budget."""
        if deadline.expired:
            result.record_source_skipped(source)
            return
        remaining = deadline.remaining()
        result.record_source_attempted(source)
        if before is not None:
            before()
        try:
            if remaining is None:
                await operation()
            else:
                await asyncio.wait_for(operation(), timeout=remaining)
        except asyncio.TimeoutError:
            # Collectors classify their own provider failures; only the
            # request deadline escapes them as a timeout here.
            logger.warning("Fulltext source %s stopped at the request deadline", source)
            result.record_source_error(source, deadline_exceeded(source, deadline.seconds))

    async def _resolve_identifiers(
        self,
        request: FulltextRequest,
        log: LogCallback | None,
        deadline: FulltextDeadline,
    ) -> tuple[FulltextRequest, list[HedgedOutcome[dict[str, Any] | None]]]:
        """Resolve PMID metadata before policy selection so DOI-only sources can run.

        Europe PMC metadata is preferred; NCBI ESummary is hedged in when it
        fails, has no record, or is slow, so a Europe PMC outage cannot hide
        the PMCID that the PMC fallback needs.
        """
        if not request.pmid or (request.pmcid and request.doi):
            return request, []

        pmid = str(request.pmid)
        attempts: list[HedgedAttempt[dict[str, Any] | None]] = [
            HedgedAttempt("europe_pmc_metadata", partial(self._fetch_europe_pmc_metadata, pmid))
        ]
        if self._ncbi_pmc_client_factory is not None:
            attempts.append(HedgedAttempt("ncbi_metadata", partial(self._fetch_ncbi_metadata, pmid)))
        outcomes = await run_hedged(
            attempts,
            usable=lambda article: isinstance(article, dict),
            hedge_after=self._hedge_seconds,
            deadline=deadline,
        )
        article = next(
            (outcome.value for outcome in outcomes if outcome.answered and isinstance(outcome.value, dict)),
            None,
        )

        resolved_pmcid = request.pmcid
        resolved_doi = request.doi
        if article:
            raw_pmcid = article.get("pmc_id") or article.get("pmcid")
            if not resolved_pmcid and raw_pmcid:
                try:
                    resolved_pmcid = normalize_pmcid(str(raw_pmcid))
                except IdentifierValidationError:
                    logger.info("Metadata source returned a malformed PMCID; ignoring it")
            if not resolved_doi:
                raw_doi = article.get("doi")
                if raw_doi:
                    try:
                        resolved_doi = normalize_doi(str(raw_doi))
                    except IdentifierValidationError:
                        logger.info("Metadata source returned a malformed DOI; ignoring it")

        return replace(request, pmcid=resolved_pmcid, doi=resolved_doi), outcomes

    async def _fetch_europe_pmc_metadata(self, pmid: str) -> dict[str, Any] | None:
        client = self._europe_pmc_client_factory()
        article = await client.get_article("MED", pmid, result_type="core")
        return article if isinstance(article, dict) else None

    async def _fetch_ncbi_metadata(self, pmid: str) -> dict[str, Any] | None:
        if self._ncbi_pmc_client_factory is None:
            return None
        client = self._ncbi_pmc_client_factory()
        article = await client.resolve_article_ids(pmid)
        return article if isinstance(article, dict) else None

    async def _record_hedged_outcomes(
        self,
        result: FulltextServiceResult,
        outcomes: list[HedgedOutcome[Any]],
        log: LogCallback | None,
        deadline: FulltextDeadline,
    ) -> None:
        """Translate hedged attempt outcomes into coverage facts."""
        for outcome in outcomes:
            if outcome.skipped_by_deadline:
                result.record_source_skipped(outcome.source)
                continue
            if not outcome.started:
                continue
            result.record_source_attempted(outcome.source)
            if outcome.stopped == "superseded":
                result.record_source_notice(outcome.source, "superseded")
            elif outcome.stopped == "deadline":
                result.record_source_error(outcome.source, deadline_exceeded(outcome.source, deadline.seconds))
            elif outcome.error is not None:
                await self._record_failure(result, outcome.source, outcome.error, log)
            else:
                result.record_source_completed(outcome.source)

    async def _record_failure(
        self,
        result: FulltextServiceResult,
        source: str,
        error: BaseException,
        log: LogCallback | None,
    ) -> None:
        """Classify one sanitized source failure and tell the client why."""
        failure = classify_source_failure(source, error)
        logger.warning("Fulltext source %s failed (%s: %s)", source, failure.code, type(error).__name__)
        result.record_source_error(source, failure)
        await self._report_log(log, "warning", f"Fulltext source {source}: {failure.message}")

    async def _collect_structured(
        self,
        request: FulltextRequest,
        result: FulltextServiceResult,
        policy_sources: tuple[str, ...],
        progress: ProgressCallback | None,
        log: LogCallback | None,
        deadline: FulltextDeadline,
    ) -> None:
        """Race the PMC-family JATS sources and apply the first usable body."""
        pmcid = str(request.pmcid)
        attempts: list[HedgedAttempt[_StructuredDocument]] = []
        for source in policy_sources:
            if source == "europe_pmc":
                attempts.append(HedgedAttempt(source, partial(self._fetch_europe_pmc_document, pmcid)))
            elif source == "ncbi_pmc" and self._ncbi_pmc_client_factory is not None:
                attempts.append(HedgedAttempt(source, partial(self._fetch_ncbi_pmc_document, pmcid)))
        if not attempts:
            return

        async def on_start(source: str) -> None:
            if source == "europe_pmc":
                await self._report_progress(progress, 2, 6, "Trying Europe PMC fulltext...")
            else:
                await self._report_progress(progress, 2.5, 6, "Trying NCBI PMC (E-utilities) fulltext...")

        outcomes = await run_hedged(
            attempts,
            # Only a body ends the race. NCBI's publisher restriction applies to
            # NCBI's XML copy; Europe PMC licenses and serves its own copy (for
            # example funder author manuscripts), so an attempt already running
            # there may still return the body. It keeps running until it
            # answers, fails, or the request deadline stops it -- and is never
            # reported as "superseded" by an answer that had no body.
            usable=lambda document: document.has_body,
            hedge_after=self._hedge_seconds,
            deadline=deadline,
            on_start=on_start,
        )
        await self._record_hedged_outcomes(result, outcomes, log, deadline)

        chosen: tuple[str, _StructuredDocument] | None = None
        chosen_rank = 0
        for outcome in outcomes:
            document = outcome.value
            if not outcome.answered or document is None:
                continue
            if document.restricted:
                result.record_source_notice(outcome.source, "front_matter_only")
            elif not document.has_body:
                result.record_source_notice(outcome.source, "no_body")
            # Prefer the first body; then a publisher restriction (it decides
            # the links shown); then the first parsed record (title,
            # abstract-only XML) exactly as before the fallback existed.
            rank = 3 if document.has_body else 2 if document.restricted else 1 if document.parsed else 0
            if rank > chosen_rank:
                chosen, chosen_rank = (outcome.source, document), rank
        if chosen is not None:
            self._apply_structured_document(chosen[0], chosen[1], request, result)

    async def _fetch_europe_pmc_document(self, pmcid: str) -> _StructuredDocument:
        client = self._europe_pmc_client_factory()
        xml = (
            await self._structured_xml_fetcher(pmcid)
            if self._structured_xml_fetcher is not None
            else await client.get_fulltext_xml(pmcid)
        )
        if not xml:
            return _StructuredDocument(None)
        parsed = client.parse_fulltext_xml(xml)
        if not parsed:
            return _StructuredDocument(None)
        if not isinstance(parsed, dict):
            raise ParseError("Structured fulltext parser returned no mapping", source="Europe PMC")
        return _StructuredDocument(parsed)

    async def _fetch_ncbi_pmc_document(self, pmcid: str) -> _StructuredDocument:
        if self._ncbi_pmc_client_factory is None:
            return _StructuredDocument(None)
        client = self._ncbi_pmc_client_factory()
        xml = await client.get_article_xml(pmcid)
        if not xml:
            return _StructuredDocument(None)
        parsed = client.parse_article_xml(xml)
        if not isinstance(parsed, dict):
            raise ParseError("Structured fulltext parser returned no mapping", source="NCBI PMC")
        return _StructuredDocument(parsed, restricted=bool(parsed.get("access_restricted")))

    def _apply_structured_document(
        self,
        source: str,
        document: _StructuredDocument,
        request: FulltextRequest,
        result: FulltextServiceResult,
    ) -> None:
        """Project one parsed JATS document into the result without inventing body text."""
        parsed = document.parsed or {}
        result.section_selection = select_sections(parsed, request.sections)
        result.content_sections = list(result.section_selection.sections)
        result.fulltext_content = self._render_selected_sections(parsed, result.content_sections)
        result.raw_fulltext_content = self._render_selected_sections(parsed, result.content_sections, truncate=False)
        result.title = parsed.get("title") or result.title
        if result.section_selection.body_available:
            result.fulltext_source_name = self._registry.label_for(source)
            result.fulltext_canonical_host = "PubMed Central"
            # NCBI is PMC's canonical host; Europe PMC mirrors the same record.
            result.fulltext_provenance = "direct" if source == "ncbi_pmc" else "indirect"
            license_info = parsed.get("license")
            result.fulltext_license = dict(license_info) if isinstance(license_info, dict) else None

        pmc_num = str(request.pmcid).replace("PMC", "")
        if document.restricted:
            # Readable on the PMC site, but the publisher withholds XML reuse:
            # point the reader there rather than presenting front matter.
            result.pdf_links.append(
                {
                    "source": "PubMed Central (article page)",
                    "url": f"https://pmc.ncbi.nlm.nih.gov/articles/PMC{pmc_num}/",
                    "type": "landing_page",
                    "access": "free_to_read",
                }
            )
            return
        result.pdf_links.append(
            {
                "source": "PubMed Central",
                "url": f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_num}/pdf/",
                "type": "pdf",
                "access": "open_access",
            }
        )

    async def _collect_unpaywall(
        self,
        request: FulltextRequest,
        result: FulltextServiceResult,
        log: LogCallback | None,
    ) -> None:
        source = "unpaywall"
        try:
            unpaywall = self._unpaywall_client_factory()
            oa_info = await unpaywall.get_oa_status(request.doi)
            if not oa_info or not oa_info.get("is_oa"):
                result.record_source_completed(source)
                return

            if not result.title:
                result.title = oa_info.get("title")

            best_loc = oa_info.get("best_oa_location", {})
            if best_loc:
                if best_loc.get("url_for_pdf"):
                    result.pdf_links.append(
                        {
                            "source": f"Unpaywall ({best_loc.get('host_type', 'unknown')})",
                            "url": best_loc["url_for_pdf"],
                            "type": "pdf",
                            "access": oa_info.get("oa_status", "open_access"),
                            "version": best_loc.get("version", "unknown"),
                            "license": best_loc.get("license"),
                        }
                    )
                elif best_loc.get("url"):
                    result.pdf_links.append(
                        {
                            "source": f"Unpaywall ({best_loc.get('host_type', 'unknown')})",
                            "url": best_loc["url"],
                            "type": "landing_page",
                            "access": oa_info.get("oa_status", "open_access"),
                        }
                    )

            for loc in oa_info.get("oa_locations", [])[:3]:
                if loc != best_loc and loc.get("url_for_pdf"):
                    result.pdf_links.append(
                        {
                            "source": f"Unpaywall ({loc.get('host_type', 'repository')})",
                            "url": loc["url_for_pdf"],
                            "type": "pdf",
                            "access": "alternative",
                            "version": loc.get("version"),
                        }
                    )
            result.record_source_completed(source)
        except Exception as exc:
            await self._record_failure(result, source, exc, log)

    async def _collect_institutional(
        self,
        request: FulltextRequest,
        result: FulltextServiceResult,
        log: LogCallback | None,
    ) -> None:
        if self._institutional_client_factory is None or not request.doi:
            return
        source = "institutional"
        try:
            client = self._institutional_client_factory()
            outcome = await client.get_fulltext_by_doi(request.doi)
        except Exception as exc:
            await self._record_failure(result, source, exc, log)
            return

        result.record_source_completed(source)
        if not getattr(outcome, "success", False):
            return
        text = getattr(outcome, "text", None)
        if not text:
            return

        result.fulltext_content = text
        result.content_sections = [{"title": "Publisher Article (institutional)", "content": text}]
        title = getattr(outcome, "title", None)
        if title and not result.title:
            result.title = title

        source_used = getattr(outcome, "source_used", None) or "direct"
        result.fulltext_source_name = f"Institutional ({source_used})"
        result.fulltext_canonical_host = "Publisher (institutional access)"
        result.fulltext_provenance = "direct"

        final_url = getattr(outcome, "final_url", None)
        if final_url:
            result.pdf_links.append(
                {
                    "source": result.fulltext_source_name,
                    "url": final_url,
                    "type": "landing_page",
                    "access": "institutional",
                }
            )

    async def _collect_core(
        self,
        request: FulltextRequest,
        result: FulltextServiceResult,
        log: LogCallback | None,
    ) -> None:
        source = "core"
        try:
            core = self._core_client_factory()
            matches = await core.search(f'doi:"{request.doi}"', limit=1)
            if not matches or not matches.get("results"):
                result.record_source_completed(source)
                return

            work = matches["results"][0]
            if not result.title:
                result.title = work.get("title")

            if work.get("full_text") and not result.fulltext_content:
                result.raw_fulltext_content = str(work.get("full_text", ""))
                result.fulltext_content = self._format_core_fulltext(work)
                result.fulltext_source_name = self._registry.label_for("core")
                result.fulltext_canonical_host = "Repository / OA host"
                result.fulltext_provenance = "indirect"

            if work.get("download_url"):
                result.pdf_links.append(
                    {
                        "source": "CORE",
                        "url": work["download_url"],
                        "type": "pdf",
                        "access": "open_access",
                    }
                )
            if work.get("source_fulltext_urls"):
                for url in work["source_fulltext_urls"][:2]:
                    result.pdf_links.append(
                        {
                            "source": "CORE (source)",
                            "url": url,
                            "type": "fulltext",
                            "access": "open_access",
                        }
                    )
            result.record_source_completed(source)
        except Exception as exc:
            await self._record_failure(result, source, exc, log)

    async def _collect_download(
        self,
        request: FulltextRequest,
        result: FulltextServiceResult,
        log: LogCallback | None,
        *,
        source: Literal["extended", "pdf_retrieval_fallback"],
    ) -> None:
        """Share discovery, extraction, coverage, and cleanup across both policies."""
        downloader: Any | None = None
        try:
            downloader = self._downloader_factory()
            extended_result = await downloader.get_fulltext(
                pmid=request.pmid,
                pmcid=request.pmcid,
                doi=request.doi,
                strategy="links_only" if result.has_retrieved_text else "extract_text",
                allow_browser_session=request.allow_browser_session,
            )
            link_discovery = extended_result.require_link_discovery()
            if source == "pdf_retrieval_fallback":
                result.fallback_notice = FulltextDownloadNotice(
                    source=extended_result.source_used.source_id if extended_result.source_used else None,
                    source_name=extended_result.source_used.display_name if extended_result.source_used else None,
                    retrieved_url=extended_result.retrieved_url,
                    has_text=bool(extended_result.text_content),
                    error=bool(extended_result.error),
                )

            for attempted_source in link_discovery.attempted_sources:
                result.record_source_attempted(attempted_source)
            for completed_source in link_discovery.completed_sources:
                result.record_source_completed(completed_source)
            for source_error in link_discovery.source_errors:
                result.record_source_error(
                    source_error.source,
                    classify_link_discovery_error(
                        source_error.source,
                        kind=getattr(source_error, "kind", None),
                        status_code=getattr(source_error, "status_code", None),
                    ),
                )

            if not result.has_retrieved_text and extended_result.text_content:
                result.raw_fulltext_content = extended_result.text_content
                extracted_text = self.truncate_extracted_text(extended_result.text_content)
                result.fulltext_content = extracted_text
                result.content_sections = [{"title": "Extracted PDF Text", "content": extracted_text}]
                result.fulltext_source_name = (
                    extended_result.source_used.display_name
                    if extended_result.source_used
                    else "Extended fulltext download"
                )
                result.fulltext_canonical_host = result.fulltext_source_name
                result.fulltext_provenance = "derived"

            if not result.title and extended_result.title:
                result.title = extended_result.title
            seen_urls = {link["url"] for link in result.pdf_links}
            for ext_link in link_discovery.links:
                if not ext_link.url or ext_link.url in seen_urls:
                    continue
                seen_urls.add(ext_link.url)
                result.pdf_links.append(
                    {
                        "source": ext_link.source.display_name,
                        "url": ext_link.url,
                        "type": "pdf" if ext_link.is_direct_pdf else "landing_page",
                        "access": ext_link.access_type,
                        "version": ext_link.version,
                        "license": ext_link.license,
                    }
                )
            if link_discovery.coverage_status != "unavailable" or extended_result.text_content:
                result.record_source_completed(source)
        except Exception as exc:
            await self._record_failure(result, source, exc, log)
        finally:
            if downloader is not None and hasattr(downloader, "close"):
                try:
                    await downloader.close()
                except Exception as exc:
                    logger.warning("Extended source cleanup failed (%s)", type(exc).__name__)
                    await self._report_log(log, "warning", "Extended fulltext cleanup failed")

    async def _collect_figures(
        self,
        request: FulltextRequest,
        result: FulltextServiceResult,
        log: LogCallback | None,
    ) -> None:
        if self._figure_client_factory is None:
            return
        source = "pmc_figures"
        try:
            figure_client = self._figure_client_factory()
            figure_result = await figure_client.get_article_figures(
                pmcid=request.pmcid,
                pmid=request.pmid,
            )
            if figure_result.figures:
                result.figures = [figure.to_dict() for figure in figure_result.figures]
            if figure_result.error:
                result.record_source_error(source)
            else:
                result.record_source_completed(source)
        except Exception as exc:
            await self._record_failure(result, source, exc, log)

    @staticmethod
    async def _report_progress(
        callback: ProgressCallback | None,
        progress: float,
        total: float,
        message: str,
    ) -> None:
        if callback is not None:
            await callback(progress, total, message)

    @staticmethod
    async def _report_log(callback: LogCallback | None, level: LogLevel, message: str) -> None:
        if callback is not None:
            await callback(level, message)

    @staticmethod
    def _deduplicate_link_rows(pdf_links: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for link in pdf_links:
            url = str(link.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            deduped.append(link)
        return deduped

    @staticmethod
    def truncate_extracted_text(text: str, max_chars: int = 10000) -> str:
        """Bound extracted PDF text for inline service responses."""
        if len(text) <= max_chars:
            return text
        truncated_count = len(text) - max_chars
        return text[:max_chars] + f"\n\n_... {truncated_count} characters truncated from extracted PDF text_"

    @staticmethod
    def _render_selected_sections(
        parsed: dict[str, Any], sections: list[dict[str, Any]], *, truncate: bool = True
    ) -> str:
        if not sections:
            return ""

        output = ""
        for section in sections:
            title = section.get("title", "Untitled Section")
            content = section.get("content", "")
            if not content:
                continue
            output += f"### {title}\n\n"
            if truncate and len(content) > 5000:
                output += content[:5000]
                output += f"\n\n_... {len(content) - 5000} characters truncated_\n\n"
            else:
                output += content + "\n\n"

        references = parsed.get("references", [])
        if references:
            output += f"---\n📚 **References**: {len(references)} citations\n"
        return output

    @staticmethod
    def _format_core_fulltext(work: dict[str, Any]) -> str:
        """Preview unstructured CORE text; section filtering requires structured sections."""
        fulltext = str(work.get("full_text", ""))
        if len(fulltext) > 10000:
            return fulltext[:10000] + f"\n\n_... {len(fulltext) - 10000} characters truncated_"
        return fulltext
