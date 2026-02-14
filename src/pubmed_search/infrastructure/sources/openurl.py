"""
OpenURL Link Resolver Integration

Provides integration with institutional link resolvers (SFX, 360 Link, etc.)
to help users find full text through their library subscriptions.

OpenURL is a NISO standard (Z39.88) for passing bibliographic metadata
between systems to enable full-text linking through library subscriptions.

Features:
- Build OpenURL from article metadata
- Support for custom institutional resolvers
- Common resolver presets (SFX, Serial Solutions, etc.)
- Generate "Find Full Text" links

Configuration:
    Set OPENURL_RESOLVER environment variable to your institution's resolver URL.
    Example: OPENURL_RESOLVER=https://resolver.library.example.edu/openurl

Usage:
    from pubmed_search.infrastructure.sources.openurl import OpenURLBuilder, get_openurl_link

    # Build OpenURL for an article
    builder = OpenURLBuilder(resolver_base="https://your.library.edu/openurl")
    url = builder.build_from_article(article_dict)

    # Or use the convenience function
    url = get_openurl_link(article_dict)
"""

from __future__ import annotations

import logging
import os
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# Common OpenURL resolver templates
RESOLVER_PRESETS: dict[str, str] = {
    # 台灣
    "ntu": "https://ntu.primo.exlibrisgroup.com/openurl/886UST_NTU/886UST_NTU:NTU",  # 台大
    "ncku": "https://ncku.primo.exlibrisgroup.com/openurl/886NCKU/886NCKU:NCKU",  # 成大
    "nthu": "https://nthu.primo.exlibrisgroup.com/openurl/886NTHU/886NTHU:NTHU",  # 清大
    "nycu": "https://nycu.primo.exlibrisgroup.com/openurl/886NYCU/886NYCU:NYCU",  # 陽明交大
    # 美國大學
    "harvard": "https://hollis.harvard.edu/openurl/HVD/HVD",
    "stanford": "https://searchworks.stanford.edu/openurl",
    "mit": "https://mit.primo.exlibrisgroup.com/openurl/01MIT_INST/01MIT",
    "yale": "https://yale.primo.exlibrisgroup.com/openurl/01YAL_INST/01YAL",
    # 英國
    "oxford": "https://solo.bodleian.ox.ac.uk/openurl/OXFOR",
    "cambridge": "https://idiscover.lib.cam.ac.uk/openurl",
    # 通用格式 (需要用戶設定 base URL)
    "sfx": "{base}/sfx_local",
    "360link": "{base}/aresolver",
    "primo": "{base}/openurl",
    # 免費/公開測試端點 (Free/Public test endpoints)
    # WorldCat 是公開的，可以用於測試 OpenURL 格式是否正確
    "worldcat": "https://worldcat.org/search?q=",  # 公開，但格式不同
    "pubmed_linkout": "https://www.ncbi.nlm.nih.gov/pubmed/?term=",  # PubMed 原生搜尋
    # 以下是免費/開放的 Link Resolver 測試端點
    # 這些可能有速率限制，僅供測試
    "test_free": "https://resolver.ebscohost.com/openurl",  # EBSCO (有些機構免費)
}


@dataclass
class OpenURLBuilder:
    """
    Build OpenURL links for institutional access.

    OpenURL (NISO Z39.88) is a standard for encoding bibliographic metadata
    in a URL format that can be passed to a link resolver.

    Example:
        builder = OpenURLBuilder(resolver_base="https://your.library.edu/openurl")
        url = builder.build_from_article({
            "pmid": "12345678",
            "doi": "10.1001/jama.2024.1234",
            "title": "Article Title",
            "journal": "JAMA",
            "year": "2024",
            "volume": "331",
            "issue": "1",
            "pages": "45-52"
        })

    Attributes:
        resolver_base: Base URL of your institution's link resolver.
        rfr_id: Referrer ID (identifies the source system).
        ctx_ver: OpenURL context version (default: Z39.88-2004).
    """

    resolver_base: str = ""
    rfr_id: str = "info:sid/pubmed-search-mcp"
    ctx_ver: str = "Z39.88-2004"

    # Additional parameters for specific resolvers
    extra_params: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        """Initialize with environment variable if not set."""
        if not self.resolver_base:
            self.resolver_base = os.environ.get("OPENURL_RESOLVER", "")

    @classmethod
    def from_preset(cls, preset_name: str, base_url: str | None = None) -> OpenURLBuilder:
        """
        Create builder from a preset resolver template.

        Args:
            preset_name: Name of preset (e.g., "ntu", "harvard", "sfx")
            base_url: Base URL for resolvers that require it

        Returns:
            Configured OpenURLBuilder instance
        """
        preset = RESOLVER_PRESETS.get(preset_name.lower())
        if not preset:
            available = ", ".join(RESOLVER_PRESETS.keys())
            raise ValueError(f"Unknown preset '{preset_name}'. Available: {available}")

        if "{base}" in preset:
            if not base_url:
                raise ValueError(f"Preset '{preset_name}' requires base_url parameter")
            preset = preset.replace("{base}", base_url.rstrip("/"))

        return cls(resolver_base=preset)

    def build_from_article(self, article: dict[str, Any]) -> str | None:
        """
        Build OpenURL from article metadata.

        Args:
            article: Dictionary with article metadata (pmid, doi, title, etc.)

        Returns:
            Complete OpenURL string or None if resolver not configured
        """
        if not self.resolver_base:
            logger.debug("OpenURL resolver not configured")
            return None

        params = self._build_params(article)
        if not params:
            return None

        query_string = urllib.parse.urlencode(params, safe=":/")

        # Check if resolver_base already has query params
        separator = "&" if "?" in self.resolver_base else "?"
        return f"{self.resolver_base}{separator}{query_string}"

    def _build_params(self, article: dict[str, Any]) -> dict[str, str]:
        """Build OpenURL parameters from article metadata."""
        params: dict[str, str] = {
            "ctx_ver": self.ctx_ver,
            "rfr_id": self.rfr_id,
            "rft_val_fmt": "info:ofi/fmt:kev:mtx:journal",  # Journal article
        }

        # PMID
        pmid = article.get("pmid")
        if pmid:
            params["rft_id"] = f"info:pmid/{pmid}"
            params["pmid"] = str(pmid)

        # DOI
        doi = article.get("doi")
        if doi:
            params["rft_id"] = f"info:doi/{doi}"
            params["rft.doi"] = doi

        # Title
        title = article.get("title")
        if title:
            params["rft.atitle"] = title

        # Journal
        journal = article.get("journal") or article.get("journal_title")
        if journal:
            params["rft.jtitle"] = journal

        # Year
        year = article.get("year") or article.get("pub_year")
        if year:
            params["rft.date"] = str(year)

        # Volume
        volume = article.get("volume")
        if volume:
            params["rft.volume"] = str(volume)

        # Issue
        issue = article.get("issue")
        if issue:
            params["rft.issue"] = str(issue)

        # Pages
        pages = article.get("pages")
        if pages:
            if "-" in str(pages):
                start, end = str(pages).split("-", 1)
                params["rft.spage"] = start.strip()
                params["rft.epage"] = end.strip()
            else:
                params["rft.spage"] = str(pages)

        # ISSN
        issn = article.get("issn")
        if issn:
            params["rft.issn"] = issn

        # eISSN
        eissn = article.get("eissn")
        if eissn:
            params["rft.eissn"] = eissn

        # Authors
        authors = article.get("authors", [])
        if authors:
            if isinstance(authors[0], dict):
                first_author = authors[0]
                if first_author.get("last_name"):
                    params["rft.aulast"] = first_author["last_name"]
                if first_author.get("fore_name"):
                    params["rft.aufirst"] = first_author["fore_name"]
            elif isinstance(authors[0], str):
                # Simple string format
                params["rft.au"] = authors[0]

        # Add extra params
        params.update(self.extra_params)

        return params

    def build_from_pmid(self, pmid: str) -> str | None:
        """Build minimal OpenURL from PMID only."""
        return self.build_from_article({"pmid": pmid})

    def build_from_doi(self, doi: str) -> str | None:
        """Build minimal OpenURL from DOI only."""
        return self.build_from_article({"doi": doi})


@dataclass
class OpenURLConfig:
    """
    Configuration for OpenURL link resolver.

    Store in environment or VS Code settings.

    Attributes:
        resolver_base: Base URL of link resolver
        preset: Preset name (overrides resolver_base)
        enabled: Whether OpenURL links are enabled
    """

    resolver_base: str = ""
    preset: str = ""
    enabled: bool = True

    @classmethod
    def from_env(cls) -> OpenURLConfig:
        """Load configuration from environment variables."""
        return cls(
            resolver_base=os.environ.get("OPENURL_RESOLVER", ""),
            preset=os.environ.get("OPENURL_PRESET", ""),
            enabled=os.environ.get("OPENURL_ENABLED", "true").lower() != "false",
        )

    def get_builder(self) -> OpenURLBuilder | None:
        """Get configured OpenURLBuilder or None if not configured."""
        if not self.enabled:
            return None

        if self.preset:
            try:
                return OpenURLBuilder.from_preset(self.preset, self.resolver_base)
            except ValueError as e:
                logger.warning(f"Invalid OpenURL preset: {e}")
                # Fall through to try resolver_base

        if self.resolver_base:
            return OpenURLBuilder(resolver_base=self.resolver_base)

        return None


# Singleton config
_openurl_config: OpenURLConfig | None = None


def get_openurl_config() -> OpenURLConfig:
    """Get OpenURL configuration singleton."""
    global _openurl_config
    if _openurl_config is None:
        _openurl_config = OpenURLConfig.from_env()
    return _openurl_config


def configure_openurl(
    resolver_base: str | None = None,
    preset: str | None = None,
    enabled: bool = True,
) -> None:
    """
    Configure OpenURL integration.

    Call this at startup to configure your institution's resolver.

    Args:
        resolver_base: Base URL of your link resolver
        preset: Preset name (e.g., "ntu", "harvard", "sfx")
        enabled: Whether to generate OpenURL links

    Example:
        # Use preset
        configure_openurl(preset="ntu")

        # Use custom URL
        configure_openurl(resolver_base="https://your.library.edu/openurl")

        # Disable
        configure_openurl(enabled=False)
    """
    global _openurl_config
    _openurl_config = OpenURLConfig(
        resolver_base=resolver_base or "",
        preset=preset or "",
        enabled=enabled,
    )


def get_openurl_link(article: dict[str, Any]) -> str | None:
    """
    Get OpenURL link for an article.

    Convenience function that uses the configured resolver.

    Args:
        article: Article metadata dictionary

    Returns:
        OpenURL string or None if not configured
    """
    config = get_openurl_config()
    builder = config.get_builder()
    if builder:
        return builder.build_from_article(article)
    return None


def get_openurl_from_pmid(pmid: str) -> str | None:
    """Get OpenURL link from PMID."""
    return get_openurl_link({"pmid": pmid})


def get_openurl_from_doi(doi: str) -> str | None:
    """Get OpenURL link from DOI."""
    return get_openurl_link({"doi": doi})


def list_presets() -> dict[str, str]:
    """List available resolver presets."""
    return RESOLVER_PRESETS.copy()


# Utility: Generate link with fallback chain
def get_fulltext_link_with_fallback(
    article: dict[str, Any],
    include_openurl: bool = True,
) -> dict[str, Any]:
    """
    Get best fulltext link with fallback chain.

    Priority:
    1. PMC (free, authoritative)
    2. OpenURL (institutional access)
    3. Unpaywall OA link
    4. DOI link (may be paywalled)

    Args:
        article: Article metadata
        include_openurl: Whether to include institutional link

    Returns:
        Dict with link info: {"url": ..., "source": ..., "type": ...}
    """
    result: dict[str, Any] = {
        "url": None,
        "source": None,
        "type": "unknown",
        "alternatives": [],
    }

    # 1. PMC (always free)
    pmc_id = article.get("pmc_id")
    if pmc_id:
        pmc_num = str(pmc_id).replace("PMC", "")
        result["url"] = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_num}/"
        result["source"] = "PubMed Central"
        result["type"] = "open_access"
        result["pdf_url"] = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_num}/pdf/"

    # 2. OpenURL (institutional)
    if include_openurl:
        openurl = get_openurl_link(article)
        if openurl:
            if result["url"]:
                result["alternatives"].append(
                    {
                        "url": openurl,
                        "source": "Library (OpenURL)",
                        "type": "institutional",
                    }
                )
            else:
                result["url"] = openurl
                result["source"] = "Library (OpenURL)"
                result["type"] = "institutional"

    # 3. DOI link (fallback)
    doi = article.get("doi")
    if doi and not result["url"]:
        result["url"] = f"https://doi.org/{doi}"
        result["source"] = "Publisher (DOI)"
        result["type"] = "unknown"  # May be paywalled
    elif doi:
        result["alternatives"].append(
            {
                "url": f"https://doi.org/{doi}",
                "source": "Publisher (DOI)",
                "type": "unknown",
            }
        )

    return result
