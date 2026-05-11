"""
MCP Tools for OpenURL / Institutional Link Resolver Integration

Provides tools for:
- Configuring institutional link resolver (with presets list and auto-test)
- Generating OpenURL links for articles
- Listing resolver presets and testing OpenURL configuration
- Diagnosing direct DOI / EZproxy / OpenURL institutional access paths
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pubmed_search.infrastructure.sources.openurl import (
    configure_openurl,
    get_openurl_config,
    list_presets,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_openurl_tools(mcp: FastMCP) -> None:
    """Register OpenURL-related MCP tools."""

    @mcp.tool()
    def configure_institutional_access(
        resolver_url: str | None = None,
        preset: str | None = None,
        enable: bool = True,
        test: bool = True,
    ) -> str:
        """
        Configure your institution's link resolver for full-text access.

        ═══════════════════════════════════════════════════════════════════════════════
        🏛️ INSTITUTIONAL ACCESS CONFIGURATION
        ═══════════════════════════════════════════════════════════════════════════════

        This tool configures OpenURL link resolver integration, allowing you to
        access paywalled articles through your institution's library subscription.

        ═══════════════════════════════════════════════════════════════════════════════
        HOW IT WORKS:
        ═══════════════════════════════════════════════════════════════════════════════

        1. Your library subscribes to journals through publishers
        2. Library provides a "Link Resolver" service (SFX, 360 Link, Primo, etc.)
        3. OpenURL passes article metadata to the resolver
        4. Resolver checks your subscriptions and provides full-text access

        ═══════════════════════════════════════════════════════════════════════════════
        USAGE:
        ═══════════════════════════════════════════════════════════════════════════════

        Option 1: Use a preset (easiest)
        ─────────────────────────────────
        configure_institutional_access(preset="ntu")

        Available presets:
        - 台灣: "ntu" (台大), "ncku" (成大), "nthu" (清大), "nycu" (陽明交大)
        - 美國: "harvard", "stanford", "mit", "yale"
        - 英國: "oxford", "cambridge"
        - 通用: "sfx", "360link", "primo" (需要 resolver_url)

        Option 2: Custom URL
        ─────────────────────
        configure_institutional_access(
            resolver_url="https://your.library.edu/openurl"
        )

        Option 3: Disable
        ─────────────────────
        configure_institutional_access(enable=False)

        ═══════════════════════════════════════════════════════════════════════════════
        FINDING YOUR RESOLVER URL:
        ═══════════════════════════════════════════════════════════════════════════════

        1. Go to your library's website
        2. Look for "Find Full Text", "Link Resolver", or "OpenURL"
        3. Or search: "[Your University] link resolver"
        4. The URL usually looks like:
           - https://resolver.library.edu/openurl
           - https://library.primo.exlibrisgroup.com/openurl/...
           - https://sfx.library.edu/sfx_local

        Args:
            resolver_url: Your institution's link resolver URL
            preset: Use a known institution's preset configuration
            enable: Whether to enable OpenURL links (default: True)
            test: Compatibility flag reserved for clients that still pass it.
                Use test_institutional_access() for an explicit resolver test.

        Returns:
            Configuration status message
        """
        try:
            if not enable:
                configure_openurl(enabled=False)
                return "🔒 Institutional access disabled. Only open access links will be shown."

            if preset:
                # List available presets if invalid
                available = list_presets()
                if preset.lower() not in [k.lower() for k in available]:
                    preset_list = "\n".join([f"  - {k}: {v}" for k, v in available.items()])
                    return f"❌ Unknown preset '{preset}'. Available presets:\n{preset_list}"

                configure_openurl(preset=preset, resolver_base=resolver_url, enabled=True)

                # Show the resolved URL
                config = get_openurl_config()
                builder = config.get_builder()
                base_url = builder.resolver_base if builder else "Not configured"

                return f"""✅ Institutional access configured!

📚 Preset: {preset}
🔗 Resolver URL: {base_url}

Now when you search for articles, you'll see "Library Access" links
that will check your subscription and provide full-text access.

Test it:
    get_institutional_link(pmid="12345678")
"""

            if resolver_url:
                configure_openurl(resolver_base=resolver_url, enabled=True)
                return f"""✅ Institutional access configured!

🔗 Resolver URL: {resolver_url}

Now when you search for articles, you'll see "Library Access" links
that will check your subscription and provide full-text access.

Test it:
    get_institutional_link(pmid="12345678")
"""

            # Show current config and available presets
            config = get_openurl_config()
            available = list_presets()
            preset_list = "\n".join([f"  - {k}" for k in available])

            status = "✅ Enabled" if config.enabled else "❌ Disabled"
            current = config.resolver_base or config.preset or "Not configured"

            return f"""📊 Current Configuration:
─────────────────────────────
Status: {status}
Resolver: {current}

📋 Available Presets:
{preset_list}

To configure, call:
    configure_institutional_access(preset="ntu")
    or
    configure_institutional_access(resolver_url="https://your.library.edu/openurl")
"""

        except Exception as e:
            logger.exception("Failed to configure institutional access")
            return f"❌ Configuration failed: {e}"

    @mcp.tool()
    def get_institutional_link(
        pmid: str | None = None,
        doi: str | None = None,
        title: str | None = None,
        journal: str | None = None,
        year: str | None = None,
        volume: str | None = None,
        issue: str | None = None,
        pages: str | None = None,
    ) -> str:
        """
        Generate institutional access link (OpenURL) for an article.

        ═══════════════════════════════════════════════════════════════════════════════
        🔗 GET LIBRARY ACCESS LINK
        ═══════════════════════════════════════════════════════════════════════════════

        Generate an OpenURL that will take you through your library's link resolver
        to access the full text of an article.

        PREREQUISITES:
        ─────────────────
        Must first call configure_institutional_access() to set up your resolver.

        USAGE:
        ─────────────────

        With PMID (easiest):
            get_institutional_link(pmid="38353755")

        With DOI:
            get_institutional_link(doi="10.1001/jama.2024.1234")

        With full metadata (most reliable):
            get_institutional_link(
                title="Some Article Title",
                journal="JAMA",
                year="2024",
                volume="331",
                issue="1",
                pages="45-52"
            )

        Args:
            pmid: PubMed ID
            doi: Digital Object Identifier
            title: Article title
            journal: Journal name
            year: Publication year
            volume: Volume number
            issue: Issue number
            pages: Page range (e.g., "45-52")

        Returns:
            OpenURL link or error message
        """
        config = get_openurl_config()
        builder = config.get_builder()

        if not builder:
            return """❌ Institutional access not configured!

Please first configure your library's link resolver:

    configure_institutional_access(preset="ntu")  # or your institution

    or

    configure_institutional_access(
        resolver_url="https://your.library.edu/openurl"
    )
"""

        # Build article metadata
        article = {}
        if pmid:
            article["pmid"] = pmid.replace("PMID:", "").strip()
        if doi:
            article["doi"] = doi.replace("doi:", "").strip()
        if title:
            article["title"] = title
        if journal:
            article["journal"] = journal
        if year:
            article["year"] = year
        if volume:
            article["volume"] = volume
        if issue:
            article["issue"] = issue
        if pages:
            article["pages"] = pages

        if not article:
            return "❌ Please provide at least one identifier (PMID, DOI, or title)"

        try:
            url = builder.build_from_article(article)
            if url:
                return f"""🔗 Library Access Link:
{url}

Click the link to check your library's subscription and access full text.

📝 Article Info:
{_format_article(article)}
"""
            return "❌ Could not generate link. Please check your configuration."

        except Exception as e:
            logger.exception("Failed to generate institutional link")
            return f"❌ Error: {e}"

    @mcp.tool()
    def list_resolver_presets() -> str:
        """
        List available institutional link resolver presets.

        ═══════════════════════════════════════════════════════════════════════════════
        📚 AVAILABLE RESOLVER PRESETS
        ═══════════════════════════════════════════════════════════════════════════════

        These presets contain pre-configured URLs for common institutions.
        Use them with configure_institutional_access(preset="name").

        Returns:
            List of available presets with URLs
        """
        presets = list_presets()

        lines = ["📚 Available Link Resolver Presets\n"]
        lines.append("═" * 60)

        # Group by region
        taiwan = {k: v for k, v in presets.items() if k in ["ntu", "ncku", "nthu", "nycu"]}
        usa = {k: v for k, v in presets.items() if k in ["harvard", "stanford", "mit", "yale"]}
        uk = {k: v for k, v in presets.items() if k in ["oxford", "cambridge"]}
        generic = {k: v for k, v in presets.items() if k in ["sfx", "360link", "primo"]}
        free_test = {k: v for k, v in presets.items() if k in ["worldcat", "pubmed_linkout", "test_free"]}

        if taiwan:
            lines.append("\n🇹🇼 台灣大學:")
            for k, v in taiwan.items():
                lines.append(f"  • {k}: {v}")

        if usa:
            lines.append("\n🇺🇸 美國大學:")
            for k, v in usa.items():
                lines.append(f"  • {k}: {v}")

        if uk:
            lines.append("\n🇬🇧 英國大學:")
            for k, v in uk.items():
                lines.append(f"  • {k}: {v}")

        if generic:
            lines.append("\n🔧 通用格式 (需要 resolver_url):")
            for k, v in generic.items():
                lines.append(f"  • {k}: {v}")

        if free_test:
            lines.append("\n🆓 免費/測試端點:")
            for k, v in free_test.items():
                lines.append(f"  • {k}: {v}")

        lines.append("\n" + "─" * 60)
        lines.append("""
Usage:
    configure_institutional_access(preset="ntu")

For generic presets, also provide your base URL:
    configure_institutional_access(
        preset="sfx",
        resolver_url="https://your.library.edu"
    )

Test your connection:
    test_institutional_access()
""")

        return "\n".join(lines)

    @mcp.tool()
    async def test_institutional_access(
        pmid: str = "38353755",
    ) -> str:
        """
        Test your institutional link resolver configuration.

        ═══════════════════════════════════════════════════════════════════════════════
        🧪 TEST INSTITUTIONAL ACCESS
        ═══════════════════════════════════════════════════════════════════════════════

        Tests if your configured link resolver is:
        1. Properly configured
        2. Reachable (network connection)
        3. Returns a valid response

        NOTE: This only tests if the resolver endpoint is reachable.
        Actual full-text access depends on your institution's subscriptions.

        ═══════════════════════════════════════════════════════════════════════════════
        FREE TEST OPTIONS:
        ═══════════════════════════════════════════════════════════════════════════════

        If you don't have institutional access, you can test with:

        1. Use "test_free" preset (EBSCO public resolver):
           configure_institutional_access(preset="test_free")
           test_institutional_access()

        2. Most university resolvers will respond even without VPN,
           they just won't provide full-text (shows "Access options" page)

        Args:
            pmid: PMID to use for testing (default: 38353755)

        Returns:
            Test results including:
            - Configuration status
            - Network reachability
            - Generated OpenURL
            - Link to test manually
        """
        config = get_openurl_config()
        builder = config.get_builder()

        output = ["## 🧪 Institutional Access Test\n"]

        # Step 1: Check configuration
        output.append("### 1️⃣ Configuration Status")
        if not builder:
            output.append("❌ **Not configured**")
            output.append("\nPlease configure first:")
            output.append("```")
            output.append('configure_institutional_access(preset="ntu")')
            output.append("```")
            output.append("\nOr for testing without institution:")
            output.append("```")
            output.append('configure_institutional_access(preset="test_free")')
            output.append("```")
            return "\n".join(output)

        output.append("✅ **Configured**")
        output.append(f"   Resolver: {builder.resolver_base}")

        # Step 2: Generate test URL
        output.append("\n### 2️⃣ Generated OpenURL")
        test_article = {
            "pmid": pmid,
            "title": "Test Article for OpenURL Verification",
            "journal": "Test Journal",
            "year": "2024",
        }

        test_url = builder.build_from_article(test_article)
        if test_url:
            output.append("✅ **URL Generated**")
            output.append(f"\n[🔗 Click to test in browser]({test_url})")
            output.append(f"\n<details><summary>Full URL</summary>\n\n```\n{test_url}\n```\n</details>")
        else:
            output.append("❌ Failed to generate URL")
            return "\n".join(output)

        # Step 3: Test network connection
        output.append("\n### 3️⃣ Network Test")
        output.append("Testing connection to resolver...")

        try:
            result = await _test_resolver_url(test_url)

            if result["reachable"]:
                output.append("✅ **Reachable**")
                if result["status_code"]:
                    output.append(f"   HTTP Status: {result['status_code']}")
                if result["response_time_ms"]:
                    output.append(f"   Response Time: {result['response_time_ms']}ms")
                if result["error"]:
                    output.append(f"   Note: {result['error']}")
                    output.append("\n   ℹ️ HTTP 4xx/5xx is normal - resolver responded but needs valid session")
            else:
                output.append("⚠️ **Not Reachable**")
                output.append(f"   Error: {result['error']}")
                output.append("\n   Possible causes:")
                output.append("   - Need VPN to access institutional network")
                output.append("   - Resolver URL may be incorrect")
                output.append("   - Network firewall blocking access")
        except Exception as e:
            output.append(f"⚠️ **Test Failed**: {e}")

        # Step 4: Summary
        output.append("\n### 📋 Summary")
        output.append("""
**How to verify full-text access:**
1. Click the test link above
2. If prompted, login with your institution credentials
3. You should see options to access the article

**If test shows 'Not Reachable':**
- Connect to your institution's VPN
- Or access from campus network

**If you don't have institutional access:**
- OpenURL links will still work, but may show paywalled content
- Use Unpaywall/OA links for free alternatives
""")

        return "\n".join(output)

    @mcp.tool()
    async def diagnose_institutional_access(
        pmid: str | None = None,
        doi: str | None = None,
        try_direct: bool = True,
        try_ezproxy: bool = True,
    ) -> str:
        """
        Diagnose why institutional fulltext access succeeds or fails for an article.

        Runs up to three probes and reports each path's outcome:

        1. **Direct fetch** (Phase 1, IP-aware) — follows ``https://doi.org/<doi>``
           and classifies whether the publisher served fulltext, a paywall, or a
           login page. Works automatically when your network IP is on the
           publisher's institutional allow-list (campus / VPN).

        2. **EZproxy fetch** (Phase 2, BYO-cookie) — rewrites the publisher
           hostname to your library's EZproxy host and replays your exported
           browser session cookie. Configured via env vars:
           - ``EZPROXY_HOST`` (e.g. ``ezproxy.lib.ntu.edu.tw``)
           - ``EZPROXY_COOKIE_FILE`` (path to browser-exported cookies.json)
           - ``EZPROXY_ENABLED=1``

        3. **OpenURL handoff** — generated for you to open manually in a browser
           when the automated paths fail.

        Args:
            pmid: PubMed ID (used to enrich the OpenURL).
            doi: DOI (required for the direct + EZproxy probes).
            try_direct: Run the Phase 1 direct probe (default True).
            try_ezproxy: Run the Phase 2 EZproxy probe (default True).

        Returns:
            Markdown report listing every probe's status, classification, and
            advice on the next action to take.
        """
        from pubmed_search.infrastructure.sources.institutional_fetch import (
            diagnose_access,
            safe_url_preview,
        )

        if not pmid and not doi:
            return "❌ Please supply at least one of pmid or doi."

        # Resolve DOI from PMID if needed so the probes have something to follow.
        if not doi and pmid:
            try:
                from pubmed_search.infrastructure.ncbi import LiteratureSearcher

                searcher = LiteratureSearcher()
                details = await searcher.fetch_details([pmid])
                if details:
                    doi = details[0].get("doi") or None
            except Exception:  # pragma: no cover - PMID->DOI resolution is best-effort
                logger.debug("PMID->DOI resolution skipped", exc_info=True)

        diag = await diagnose_access(
            pmid=pmid,
            doi=doi,
            try_direct=try_direct,
            try_ezproxy=try_ezproxy,
        )

        lines: list[str] = ["## 🩺 Institutional Access Diagnosis\n"]
        if pmid:
            lines.append(f"- **PMID**: {pmid}")
        if doi:
            lines.append(f"- **DOI**: {doi}")
        lines.append(f"- **Summary**: {diag.summary}")
        if diag.recommended_path:
            lines.append(f"- **Recommended path**: `{diag.recommended_path}`")
        if diag.openurl:
            lines.append(f"- **OpenURL handoff**: [open in browser]({diag.openurl})")
        lines.append("")

        for probe in diag.probes:
            icon = "✅" if probe.success else ("⚠️" if probe.attempted else "⏭️")
            lines.append(f"### {icon} `{probe.path}` probe")
            if not probe.attempted:
                lines.append(f"_Skipped_: {probe.error or 'not configured'}")
                if probe.advice:
                    lines.append(f"\n> {probe.advice}")
                lines.append("")
                continue
            lines.append(f"- status: `{probe.status_code}`")
            lines.append(f"- content_class: `{probe.content_class}`")
            if probe.final_url:
                lines.append(f"- final_url: `{safe_url_preview(probe.final_url)}`")
            if probe.content_length is not None:
                lines.append(f"- bytes: {probe.content_length}")
            if probe.duration_ms is not None:
                lines.append(f"- duration: {probe.duration_ms} ms")
            if probe.redirect_chain and len(probe.redirect_chain) > 1:
                lines.append(f"- redirects: {len(probe.redirect_chain) - 1}")
            if probe.error:
                lines.append(f"- error: {probe.error}")
            if probe.advice:
                lines.append(f"\n> {probe.advice}")
            lines.append("")

        return "\n".join(lines)


def _format_article(article: dict) -> str:
    """Format article metadata for display."""
    parts = []
    if article.get("pmid"):
        parts.append(f"  PMID: {article['pmid']}")
    if article.get("doi"):
        parts.append(f"  DOI: {article['doi']}")
    if article.get("title"):
        parts.append(f"  Title: {article['title'][:80]}...")
    if article.get("journal"):
        parts.append(f"  Journal: {article['journal']}")
    if article.get("year"):
        parts.append(f"  Year: {article['year']}")
    return "\n".join(parts) if parts else "  (No metadata provided)"


async def _test_resolver_url(url: str, timeout: int = 10) -> dict:
    """Test if a resolver URL is reachable."""
    import time
    import urllib.parse

    import httpx

    from pubmed_search.shared.async_utils import get_shared_async_client

    result: dict[str, Any] = {
        "reachable": False,
        "status_code": None,
        "error": None,
        "response_time_ms": None,
    }

    # Security: Validate URL scheme to prevent SSRF attacks
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        result["error"] = f"Invalid URL scheme: {parsed.scheme}. Only http/https allowed."
        return result

    try:
        start = time.time()

        client = get_shared_async_client()
        response = await client.get(
            url,
            headers={"User-Agent": "PubMed-Search-MCP/0.1.25 (OpenURL Test)"},
            timeout=timeout,
        )

        result["reachable"] = True
        result["status_code"] = response.status_code
        result["response_time_ms"] = int((time.time() - start) * 1000)

        # Check if status indicates server error but still reachable
        if response.status_code >= 400:
            result["error"] = f"HTTP {response.status_code}: {response.reason_phrase}"

    except httpx.ConnectError as e:
        result["reachable"] = False
        result["error"] = f"Connection failed: {e}"

    except httpx.HTTPError as e:
        result["reachable"] = False
        result["error"] = str(e)

    except Exception as e:
        result["reachable"] = False
        result["error"] = str(e)

    return result
