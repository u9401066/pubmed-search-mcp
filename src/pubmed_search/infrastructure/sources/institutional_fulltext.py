"""Institutional fulltext client — direct DOI / EZproxy retrieval.

Bridges the Phase 1 (IP-aware direct DOI fetch) and Phase 2 (EZproxy
hostname-rewrite + replayed session cookie) probes with HTML-to-text
extraction so the orchestration layer can return real fulltext content,
not just diagnostic metadata.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .institutional_extract import extract_fulltext
from .institutional_fetch import EZProxyConfig, fetch_direct, fetch_ezproxy

if TYPE_CHECKING:
    from .institutional_fetch import ProbeResult

logger = logging.getLogger(__name__)


@dataclass
class InstitutionalFulltextResult:
    """Outcome of an institutional fulltext attempt."""

    success: bool
    text: str | None = None
    title: str | None = None
    final_url: str | None = None
    source_used: str | None = None  # "direct" | "ezproxy"
    content_class: str | None = None
    error: str | None = None


def _success_with_body(probe: ProbeResult) -> bool:
    return bool(probe.success and probe.body and probe.content_class == "fulltext_html")


def _success_with_pdf(probe: ProbeResult) -> bool:
    return bool(probe.success and probe.body and probe.content_class == "pdf")


class InstitutionalFulltextClient:
    """Retrieve fulltext through direct DOI or EZproxy proxied access."""

    def __init__(self, *, config: EZProxyConfig | None = None) -> None:
        self._config = config or EZProxyConfig.from_env()

    async def get_fulltext_by_doi(self, doi: str) -> InstitutionalFulltextResult:
        """Try direct DOI first, then EZproxy when configured.

        Returns a result whose ``success`` is True only when a publisher page
        was retrieved AND HTML extraction yielded a sufficiently long body
        (paywall stubs and JS shims are rejected).
        """
        if not doi:
            return InstitutionalFulltextResult(success=False, error="no DOI")

        direct = await fetch_direct(doi)
        if _success_with_pdf(direct):
            return InstitutionalFulltextResult(
                success=True,
                final_url=direct.final_url,
                source_used="direct",
                content_class=direct.content_class,
            )
        extracted = self._extract_if_html(direct)
        if extracted is not None:
            return InstitutionalFulltextResult(
                success=True,
                text=extracted["text"],
                title=extracted["title"] or None,
                final_url=direct.final_url,
                source_used="direct",
                content_class=direct.content_class,
            )

        if self._config.is_configured:
            ezp = await fetch_ezproxy(doi, config=self._config)
            if _success_with_pdf(ezp):
                return InstitutionalFulltextResult(
                    success=True,
                    final_url=ezp.final_url,
                    source_used="ezproxy",
                    content_class=ezp.content_class,
                )
            extracted = self._extract_if_html(ezp)
            if extracted is not None:
                return InstitutionalFulltextResult(
                    success=True,
                    text=extracted["text"],
                    title=extracted["title"] or None,
                    final_url=ezp.final_url,
                    source_used="ezproxy",
                    content_class=ezp.content_class,
                )
            error = ezp.error or f"ezproxy returned content_class={ezp.content_class}"
        else:
            error = direct.error or f"direct returned content_class={direct.content_class}"

        return InstitutionalFulltextResult(success=False, error=error)

    @staticmethod
    def _extract_if_html(probe: ProbeResult) -> dict[str, str] | None:
        if not _success_with_body(probe) or probe.body is None or probe.final_url is None:
            return None
        return extract_fulltext(probe.body, probe.final_url)
