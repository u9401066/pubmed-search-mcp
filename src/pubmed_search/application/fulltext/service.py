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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from .registry import FulltextRegistry, get_fulltext_registry

logger = logging.getLogger(__name__)

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
    content_sections: list[dict[str, Any]] = field(default_factory=list)
    pdf_links: list[dict[str, Any]] = field(default_factory=list)
    sources_tried: list[str] = field(default_factory=list)
    figures: list[dict[str, Any]] = field(default_factory=list)
    fulltext_source_name: str | None = None
    fulltext_canonical_host: str | None = None
    fulltext_provenance: Literal["direct", "indirect", "derived", "mixed"] | None = None


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
    ) -> None:
        self._registry = registry or get_fulltext_registry()
        self._europe_pmc_client_factory = europe_pmc_client_factory
        self._unpaywall_client_factory = unpaywall_client_factory
        self._core_client_factory = core_client_factory
        self._downloader_factory = downloader_factory
        self._figure_client_factory = figure_client_factory

    async def retrieve(
        self,
        request: FulltextRequest,
        *,
        progress: ProgressCallback | None = None,
        log: LogCallback | None = None,
    ) -> FulltextServiceResult:
        """Execute fulltext retrieval according to registry policy."""
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

        if request.pmcid and "europe_pmc" in policy.sources:
            await self._report_progress(progress, 2, 6, "Trying Europe PMC fulltext...")
            result.sources_tried.append(self._registry.label_for("europe_pmc"))
            await self._collect_europe_pmc(request, result, log)

        if request.doi and "unpaywall" in policy.sources:
            await self._report_progress(progress, 3, 6, "Checking Unpaywall open-access locations...")
            result.sources_tried.append(self._registry.label_for("unpaywall"))
            await self._collect_unpaywall(request, result, log)

        if request.doi and not result.fulltext_content and "core" in policy.sources:
            await self._report_progress(progress, 4, 6, "Trying CORE fallback...")
            result.sources_tried.append(self._registry.label_for("core"))
            await self._collect_core(request, result, log)

        if request.extended_sources and "extended" in policy.sources:
            await self._report_progress(progress, 5, 6, "Checking extended fulltext sources...")
            result.sources_tried.append(self._registry.label_for("extended"))
            await self._collect_extended_sources(request, result, log)

        if request.include_figures and request.pmcid:
            await self._collect_figures(request, result, log)

        result.pdf_links = self._deduplicate_link_rows(result.pdf_links)
        return result

    async def _collect_europe_pmc(
        self,
        request: FulltextRequest,
        result: FulltextServiceResult,
        log: LogCallback | None,
    ) -> None:
        try:
            client = self._europe_pmc_client_factory()
            xml = await client.get_fulltext_xml(request.pmcid)
            if not xml:
                return

            parsed = client.parse_fulltext_xml(xml)
            if not parsed:
                return

            result.content_sections = self._select_sections(parsed, request.sections)
            result.fulltext_content = self._render_selected_sections(parsed, result.content_sections)
            result.title = parsed.get("title") or result.title
            result.fulltext_source_name = self._registry.label_for("europe_pmc")
            result.fulltext_canonical_host = "PubMed Central"
            result.fulltext_provenance = "indirect"

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
            logger.warning("Europe PMC failed: %s", exc)
            await self._report_log(log, "warning", f"Europe PMC fulltext failed: {exc!s}")

    async def _collect_unpaywall(
        self,
        request: FulltextRequest,
        result: FulltextServiceResult,
        log: LogCallback | None,
    ) -> None:
        try:
            unpaywall = self._unpaywall_client_factory()
            oa_info = await unpaywall.get_oa_status(request.doi)
            if not oa_info or not oa_info.get("is_oa"):
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
        except Exception as exc:
            logger.warning("Unpaywall failed: %s", exc)
            await self._report_log(log, "warning", f"Unpaywall lookup failed: {exc!s}")

    async def _collect_core(
        self,
        request: FulltextRequest,
        result: FulltextServiceResult,
        log: LogCallback | None,
    ) -> None:
        try:
            core = self._core_client_factory()
            matches = await core.search(f'doi:"{request.doi}"', limit=1)
            if not matches or not matches.get("results"):
                return

            work = matches["results"][0]
            if not result.title:
                result.title = work.get("title")

            if work.get("fullText") and not result.fulltext_content:
                result.fulltext_content = self._format_core_fulltext(work, request.sections)
                result.fulltext_source_name = self._registry.label_for("core")
                result.fulltext_canonical_host = "Repository / OA host"
                result.fulltext_provenance = "indirect"

            if work.get("downloadUrl"):
                result.pdf_links.append(
                    {
                        "source": "CORE",
                        "url": work["downloadUrl"],
                        "type": "pdf",
                        "access": "open_access",
                    }
                )
            if work.get("sourceFulltextUrls"):
                for url in work["sourceFulltextUrls"][:2]:
                    result.pdf_links.append(
                        {
                            "source": "CORE (source)",
                            "url": url,
                            "type": "fulltext",
                            "access": "open_access",
                        }
                    )
        except Exception as exc:
            logger.warning("CORE failed: %s", exc)
            await self._report_log(log, "warning", f"CORE fulltext lookup failed: {exc!s}")

    async def _collect_extended_sources(
        self,
        request: FulltextRequest,
        result: FulltextServiceResult,
        log: LogCallback | None,
    ) -> None:
        downloader = self._downloader_factory()
        try:
            extended_result = await downloader.get_fulltext(
                pmid=request.pmid,
                pmcid=request.pmcid,
                doi=request.doi,
                strategy="links_only" if result.fulltext_content else "extract_text",
            )

            if not result.fulltext_content and extended_result.text_content:
                extracted_text = self._truncate_extracted_text(extended_result.text_content)
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
            for ext_link in extended_result.pdf_links:
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
        except Exception as exc:
            logger.warning("Extended sources failed: %s", exc)
            await self._report_log(log, "warning", f"Extended fulltext sources failed: {exc!s}")
        finally:
            if hasattr(downloader, "close"):
                await downloader.close()

    async def _collect_figures(
        self,
        request: FulltextRequest,
        result: FulltextServiceResult,
        log: LogCallback | None,
    ) -> None:
        if self._figure_client_factory is None:
            return
        try:
            figure_client = self._figure_client_factory()
            figure_result = await figure_client.get_article_figures(
                pmcid=request.pmcid,
                pmid=request.pmid,
            )
            if figure_result.figures:
                result.figures = [figure.to_dict() for figure in figure_result.figures]
        except Exception as exc:
            logger.warning("Figure extraction in fulltext service failed: %s", exc)
            await self._report_log(log, "warning", f"Figure extraction skipped: {exc!s}")

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
    def _truncate_extracted_text(text: str, max_chars: int = 10000) -> str:
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
                if any(requested_name in section_title or section_title in requested_name for requested_name in requested):
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
        fulltext = str(work.get("fullText", ""))
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
