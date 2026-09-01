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

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any, Literal, cast

from pubmed_search.domain.value_objects.article_identifiers import (
    IdentifierValidationError,
    normalize_doi,
    normalize_pmcid,
    normalize_pmid,
    parse_article_identifier,
)

from .registry import FulltextRegistry, get_fulltext_registry

logger = logging.getLogger(__name__)
_SOURCE_KEY_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")

LogLevel = Literal["debug", "info", "warning", "error"]
ProgressCallback = Callable[[float, float, str], Awaitable[None]]
LogCallback = Callable[[LogLevel, str], Awaitable[None]]


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
class FulltextSourceError:
    """Sanitized source failure safe to expose in an MCP response."""

    source: str
    code: Literal["source_unavailable"] = "source_unavailable"
    message: str = "The upstream source was unavailable during this request."

    def __post_init__(self) -> None:
        _require_source_key(self.source)

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "code": self.code, "message": self.message}


@dataclass
class FulltextServiceResult:
    """Normalized result returned to the tool formatting layer."""

    identifier: str | None = None
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
    figures: list[dict[str, Any]] = field(default_factory=list)
    fulltext_source_name: str | None = None
    fulltext_canonical_host: str | None = None
    fulltext_provenance: Literal["direct", "indirect", "derived", "mixed"] | None = None
    extended_sources_attempted: bool = False

    def __post_init__(self) -> None:
        for field_name, sources in (
            ("sources_tried", self.sources_tried),
            ("sources_completed", self.sources_completed),
        ):
            for source in sources:
                _require_source_key(source)
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

    @property
    def coverage_status(self) -> Literal["complete", "partial", "unavailable"]:
        """Describe whether every attempted upstream source completed."""
        if not self.source_errors:
            return "complete"
        if self.sources_completed or self.fulltext_content or self.pdf_links or self.figures:
            return "partial"
        return "unavailable"

    def record_source_attempted(self, source: str) -> None:
        source = _require_source_key(source)
        if source not in self.sources_tried:
            self.sources_tried.append(source)

    def record_source_completed(self, source: str) -> None:
        source = _require_source_key(source)
        if source not in self.sources_tried:
            msg = "A fulltext source must be attempted before it can complete"
            raise ValueError(msg)
        if source not in self.sources_completed:
            self.sources_completed.append(source)

    def record_source_error(self, source: str) -> None:
        source = _require_source_key(source)
        if source not in self.sources_tried:
            msg = "A fulltext source must be attempted before it can fail"
            raise ValueError(msg)
        if all(issue.source != source for issue in self.source_errors):
            self.source_errors.append(FulltextSourceError(source=source))


def _require_source_key(source: str) -> str:
    """Reject display labels and unstable aliases in coverage fields."""
    if not isinstance(source, str) or _SOURCE_KEY_RE.fullmatch(source) is None:
        msg = "Fulltext coverage sources must use stable lowercase underscore keys"
        raise ValueError(msg)
    return source


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
    ) -> None:
        self._registry = registry or get_fulltext_registry()
        self._europe_pmc_client_factory = europe_pmc_client_factory
        self._unpaywall_client_factory = unpaywall_client_factory
        self._core_client_factory = core_client_factory
        self._downloader_factory = downloader_factory
        self._figure_client_factory = figure_client_factory
        self._institutional_client_factory = institutional_client_factory

    async def retrieve(
        self,
        request: FulltextRequest,
        *,
        progress: ProgressCallback | None = None,
        log: LogCallback | None = None,
    ) -> FulltextServiceResult:
        """Execute fulltext retrieval according to registry policy."""
        request = request.normalized()
        request, metadata_status = await self._resolve_identifiers(request, log)
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
        )
        if metadata_status != "not_attempted":
            source = "europe_pmc_metadata"
            result.record_source_attempted(source)
            if metadata_status == "failed":
                result.record_source_error(source)
            else:
                result.record_source_completed(source)

        if request.pmcid and "europe_pmc" in policy.sources:
            await self._report_progress(progress, 2, 6, "Trying Europe PMC fulltext...")
            result.record_source_attempted("europe_pmc")
            await self._collect_europe_pmc(request, result, log)

        if request.doi and "unpaywall" in policy.sources:
            await self._report_progress(progress, 3, 6, "Checking Unpaywall open-access locations...")
            result.record_source_attempted("unpaywall")
            await self._collect_unpaywall(request, result, log)

        if (
            request.doi
            and not result.fulltext_content
            and "institutional" in policy.sources
            and self._institutional_client_factory is not None
        ):
            await self._report_progress(progress, 3, 6, "Trying institutional direct/EZproxy fetch...")
            result.record_source_attempted("institutional")
            await self._collect_institutional(request, result, log)

        if request.doi and not result.fulltext_content and "core" in policy.sources:
            await self._report_progress(progress, 4, 6, "Trying CORE fallback...")
            result.record_source_attempted("core")
            await self._collect_core(request, result, log)

        if request.extended_sources and "extended" in policy.sources:
            await self._report_progress(progress, 5, 6, "Checking extended fulltext sources...")
            result.record_source_attempted("extended")
            await self._collect_extended_sources(request, result, log)

        if request.include_figures and request.pmcid:
            await self._collect_figures(request, result, log)

        result.pdf_links = self._deduplicate_link_rows(result.pdf_links)
        return result

    async def _resolve_identifiers(
        self,
        request: FulltextRequest,
        log: LogCallback | None,
    ) -> tuple[FulltextRequest, Literal["not_attempted", "completed", "failed"]]:
        """Resolve PMID metadata before policy selection so DOI-only sources can run."""
        normalized_doi = request.doi
        if not request.pmid or (request.pmcid and normalized_doi):
            if normalized_doi == request.doi:
                return request, "not_attempted"
            return replace(request, doi=normalized_doi), "not_attempted"

        try:
            client = self._europe_pmc_client_factory()
            article = await client.get_article("MED", str(request.pmid), result_type="core")
        except Exception as exc:
            logger.warning("PMID metadata resolution failed (%s)", type(exc).__name__)
            await self._report_log(log, "warning", "PMID metadata source unavailable")
            article = None
            source_status: Literal["completed", "failed"] = "failed"
        else:
            source_status = "completed"

        resolved_pmcid = request.pmcid
        resolved_doi = normalized_doi
        if not isinstance(article, dict):
            article = None

        if article:
            raw_pmcid = article.get("pmc_id") or article.get("pmcid")
            if not resolved_pmcid and raw_pmcid:
                try:
                    resolved_pmcid = normalize_pmcid(str(raw_pmcid))
                except IdentifierValidationError:
                    logger.info("Europe PMC returned a malformed PMCID; ignoring it")
            if not resolved_doi:
                raw_doi = article.get("doi")
                if raw_doi:
                    try:
                        resolved_doi = normalize_doi(str(raw_doi))
                    except IdentifierValidationError:
                        logger.info("Europe PMC returned a malformed DOI; ignoring it")

        return replace(request, pmcid=resolved_pmcid, doi=resolved_doi), source_status

    async def _collect_europe_pmc(
        self,
        request: FulltextRequest,
        result: FulltextServiceResult,
        log: LogCallback | None,
    ) -> None:
        source = "europe_pmc"
        try:
            client = self._europe_pmc_client_factory()
            xml = await client.get_fulltext_xml(request.pmcid)
            if not xml:
                result.record_source_completed(source)
                return

            parsed = client.parse_fulltext_xml(xml)
            if not parsed:
                result.record_source_completed(source)
                return

            result.content_sections = self._select_sections(parsed, request.sections)
            result.fulltext_content = self._render_selected_sections(parsed, result.content_sections)
            result.raw_fulltext_content = result.fulltext_content
            result.title = parsed.get("title") or result.title
            result.fulltext_source_name = self._registry.label_for("europe_pmc")
            result.fulltext_canonical_host = "PubMed Central"
            result.fulltext_provenance = "indirect"
            result.record_source_completed(source)

            pmc_num = str(request.pmcid).replace("PMC", "")
            result.pdf_links.append(
                {
                    "source": "PubMed Central",
                    "url": f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_num}/pdf/",
                    "type": "pdf",
                    "access": "open_access",
                }
            )
        except Exception as exc:
            logger.warning("Europe PMC fulltext failed (%s)", type(exc).__name__)
            result.record_source_error(source)
            await self._report_log(log, "warning", "Europe PMC fulltext source unavailable")

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
            logger.warning("Unpaywall lookup failed (%s)", type(exc).__name__)
            result.record_source_error(source)
            await self._report_log(log, "warning", "Unpaywall source unavailable")

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
            logger.warning("Institutional fetch failed (%s)", type(exc).__name__)
            result.record_source_error(source)
            await self._report_log(log, "warning", "Institutional fulltext source unavailable")
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
                result.fulltext_content = self._format_core_fulltext(work, request.sections)
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
            logger.warning("CORE fulltext lookup failed (%s)", type(exc).__name__)
            result.record_source_error(source)
            await self._report_log(log, "warning", "CORE fulltext source unavailable")

    async def _collect_extended_sources(
        self,
        request: FulltextRequest,
        result: FulltextServiceResult,
        log: LogCallback | None,
    ) -> None:
        result.extended_sources_attempted = True
        source = "extended"
        downloader: Any | None = None
        try:
            downloader = self._downloader_factory()
            extended_result = await downloader.get_fulltext(
                pmid=request.pmid,
                pmcid=request.pmcid,
                doi=request.doi,
                strategy="links_only" if result.fulltext_content else "extract_text",
                allow_browser_session=request.allow_browser_session,
            )
            link_discovery = extended_result.require_link_discovery()

            for attempted_source in link_discovery.attempted_sources:
                result.record_source_attempted(attempted_source)
            for completed_source in link_discovery.completed_sources:
                result.record_source_completed(completed_source)
            for source_error in link_discovery.source_errors:
                result.record_source_error(source_error.source)

            if not result.fulltext_content and extended_result.text_content:
                result.raw_fulltext_content = extended_result.text_content
                extracted_text = self.truncate_extracted_text(extended_result.text_content)
                result.fulltext_content = extracted_text
                result.content_sections = [{"title": "Extracted PDF Text", "content": extracted_text}]
                if not result.title and extended_result.title:
                    result.title = extended_result.title
                result.fulltext_source_name = (
                    extended_result.source_used.display_name
                    if extended_result.source_used
                    else "Extended fulltext download"
                )
                result.fulltext_canonical_host = result.fulltext_source_name
                result.fulltext_provenance = "derived"

            seen_urls = {link["url"] for link in result.pdf_links}
            for ext_link in link_discovery.links:
                if ext_link.url in seen_urls:
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
            logger.warning("Extended fulltext sources failed (%s)", type(exc).__name__)
            result.record_source_error(source)
            await self._report_log(log, "warning", "Extended fulltext sources unavailable")
        finally:
            if downloader is not None and hasattr(downloader, "close"):
                try:
                    await downloader.close()
                except Exception as exc:
                    logger.warning("Extended source cleanup failed (%s)", type(exc).__name__)

    async def _collect_figures(
        self,
        request: FulltextRequest,
        result: FulltextServiceResult,
        log: LogCallback | None,
    ) -> None:
        if self._figure_client_factory is None:
            return
        source = "pmc_figures"
        result.record_source_attempted(source)
        try:
            figure_client = self._figure_client_factory()
            figure_result = await figure_client.get_article_figures(
                pmcid=request.pmcid,
                pmid=request.pmid,
            )
            if figure_result.figures:
                result.figures = [figure.to_dict() for figure in figure_result.figures]
            result.record_source_completed(source)
        except Exception as exc:
            logger.warning("Figure extraction in fulltext service failed (%s)", type(exc).__name__)
            result.record_source_error(source)
            await self._report_log(log, "warning", "Figure extraction source unavailable")

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
    def _select_sections(parsed: dict[str, Any], sections_filter: str | None) -> list[dict[str, Any]]:
        all_sections = cast("list[dict[str, Any]]", parsed.get("sections", []))
        if sections_filter:
            requested = [section.strip().lower() for section in sections_filter.split(",")]
            filtered: list[dict[str, Any]] = []
            for section in all_sections:
                section_title = str(section.get("title", "")).lower()
                if any(
                    requested_name in section_title or section_title in requested_name for requested_name in requested
                ):
                    filtered.append(section)
            all_sections = filtered
        return all_sections

    @staticmethod
    def _render_selected_sections(parsed: dict[str, Any], sections: list[dict[str, Any]]) -> str:
        if not sections:
            if parsed.get("abstract"):
                return f"**Abstract**\n{parsed['abstract']}\n\n"
            return ""

        output = ""
        for section in sections:
            title = section.get("title", "Untitled Section")
            content = section.get("content", "")
            if not content:
                continue
            output += f"### {title}\n\n"
            if len(content) > 5000:
                output += content[:5000]
                output += f"\n\n_... {len(content) - 5000} characters truncated_\n\n"
            else:
                output += content + "\n\n"

        references = parsed.get("references", [])
        if references:
            output += f"---\n📚 **References**: {len(references)} citations\n"
        return output

    @staticmethod
    def _format_core_fulltext(work: dict[str, Any], sections_filter: str | None) -> str:
        fulltext = str(work.get("full_text", ""))
        if not fulltext:
            return ""

        if sections_filter:
            output = ""
            for section in sections_filter.split(","):
                section_name = section.strip().lower()
                if section_name in fulltext.lower():
                    output += f"_Contains '{section_name}' section_\n"
            if output:
                output += "\n"

        if len(fulltext) > 10000:
            return fulltext[:10000] + f"\n\n_... {len(fulltext) - 10000} characters truncated_"
        return fulltext
