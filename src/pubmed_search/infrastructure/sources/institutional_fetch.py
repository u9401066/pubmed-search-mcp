"""Institutional fulltext access: IP-aware direct fetch + EZproxy BYO-cookie.

Design:
    Two complementary paths for retrieving paywalled fulltext that the OpenURL
    handoff alone cannot deliver to an autonomous agent:

    1. Direct publisher fetch (Phase 1) — follow ``https://doi.org/<doi>`` and
       classify whether the landing page reveals fulltext content (works when
       the host is on the institution's IP allow-list, e.g. campus network or
       institutional VPN).

    2. EZproxy hostname rewriting + session cookie (Phase 2) — rewrite the
       publisher hostname to the institution's EZproxy proxy host and replay a
       user-exported session cookie. Modeled after the openevidence-mcp
       BYO-cookie pattern so we do not need a browser broker.

    A diagnostic helper composes both probes plus the existing OpenURL handoff
    so users can see exactly which mechanism failed and why.

Security model:
    - Direct publisher fetch is gated by ``INSTITUTIONAL_DIRECT_FETCH`` in the
      fulltext orchestration layer and defaults to enabled.
    - EZproxy fetch remains explicit opt-in: it requires ``EZPROXY_ENABLED``,
      ``EZPROXY_HOST``, and user-supplied cookies.
    - Cookies are read from a file path the user controls and never stored
      in repository state.
    - Only http(s) URLs are followed, redirect chain depth is bounded, and
      the response classification never echoes back raw cookie values.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from pubmed_search.shared.settings import load_settings

logger = logging.getLogger(__name__)

_MAX_REDIRECTS = 8
_DEFAULT_TIMEOUT = 15.0
_PROBE_BYTES = 96 * 1024  # only sniff first 96KB for content classification
_USER_AGENT = (
    "Mozilla/5.0 (compatible; PubMed-Search-MCP/institutional-fetch; +https://github.com/u9401066/pubmed-search-mcp)"
)

# Heuristics for response classification. Order matters: paywall signals win
# over fulltext signals because publishers often render fulltext-looking
# snippets above the paywall.
_PAYWALL_PHRASES: tuple[str, ...] = (
    "purchase access",
    "purchase pdf",
    "buy this article",
    "subscribe to access",
    "subscribe to read",
    "sign in to read",
    "institutional access required",
    "your institution does not have access",
    "access through your institution",
    "you do not currently have access",
    "this article is available to subscribers",
    "rent or purchase",
    "register for free access",
)

_LOGIN_PHRASES: tuple[str, ...] = (
    "shibboleth",
    "openathens",
    "sign in via your institution",
    "log in to your account",
    "ezproxy.login",
    "/login?",
    "saml/login",
)

_FULLTEXT_PHRASES: tuple[str, ...] = (
    "full text",
    "fulltext",
    "<section",
    'class="article-body"',
    'id="article-body"',
    'class="fulltext"',
    "doi.org/10.",
    "references</",
    "acknowledgments</",
    "<article",
)

ContentClass = str  # one of: "fulltext_html", "paywall", "login_required",
# "pdf", "unknown", "empty"


# ---------------------------------------------------------------------------
# EZproxy configuration
# ---------------------------------------------------------------------------


@dataclass
class EZProxyConfig:
    """Configuration for EZproxy hostname rewriting + cookie replay.

    Attributes:
        proxy_host: The institution's EZproxy hostname suffix that gets
            appended to publisher hostnames. Example:
            ``ezproxy.lib.ntu.edu.tw``.
        cookie_file: Path to a JSON file containing exported browser cookies.
            Accepts either a raw cookies array (``[{name, value, domain, ...}]``)
            or a Playwright/Puppeteer storage-state object with a ``cookies``
            array. Same format conventions as openevidence-mcp.
        cookie_string: Raw ``Cookie:`` header value, alternative to
            ``cookie_file`` when a single inline cookie is enough.
        enabled: Master toggle.
    """

    proxy_host: str = ""
    cookie_file: str = ""
    cookie_string: str = ""
    enabled: bool = False

    @classmethod
    def from_env(cls) -> EZProxyConfig:
        """Load EZproxy configuration from app settings (env vars)."""
        settings = load_settings()
        proxy_host = (settings.ezproxy_host or "").strip()
        cookie_file = (settings.ezproxy_cookie_file or "").strip()
        cookie_string = (settings.ezproxy_cookie or "").strip()
        enabled = bool(settings.ezproxy_enabled and proxy_host and (cookie_file or cookie_string))
        return cls(
            proxy_host=proxy_host,
            cookie_file=cookie_file,
            cookie_string=cookie_string,
            enabled=enabled,
        )

    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.proxy_host) and bool(self.cookie_file or self.cookie_string)


def rewrite_to_ezproxy(publisher_url: str, proxy_host: str) -> str | None:
    """Rewrite a publisher URL hostname for EZproxy redirection.

    EZproxy uses two URL schemes depending on the institution's config:
    - Hostname-based: ``www.sciencedirect.com`` -> ``www-sciencedirect-com.ezproxy.lib.x.edu``
    - URL-based: ``https://ezproxy.lib.x.edu/login?url=https://...``

    We use the hostname-based form because it preserves the cookie domain in
    a single request and is what the openevidence-mcp pattern relies on.
    Returns ``None`` if the URL is not a fetchable http(s) URL.
    """
    if not proxy_host:
        return None
    parsed = urlparse(publisher_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    rewritten_host = parsed.netloc.replace(".", "-")
    proxy_clean = proxy_host.strip().lstrip(".").rstrip("/")
    new_netloc = f"{rewritten_host}.{proxy_clean}"
    return parsed._replace(netloc=new_netloc).geturl()


# ---------------------------------------------------------------------------
# Cookie loading (mirrors openevidence-mcp accepted formats)
# ---------------------------------------------------------------------------


def _normalize_cookies(raw: Any) -> dict[str, str]:
    """Convert a browser cookies export into a flat ``{name: value}`` dict.

    Accepts:
    - ``[{"name": ..., "value": ..., "domain": ...}, ...]``
    - ``{"cookies": [...]}`` (Playwright/Puppeteer storage state)
    - ``{"name": "value", ...}`` (already flat)
    """
    if isinstance(raw, dict) and "cookies" in raw:
        raw = raw["cookies"]
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if v is not None}
    if isinstance(raw, list):
        out: dict[str, str] = {}
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            value = entry.get("value")
            if name and value is not None:
                out[str(name)] = str(value)
        return out
    return {}


def load_cookies(cookie_file: str = "", cookie_string: str = "") -> dict[str, str]:
    """Load cookies from a file or inline ``Cookie:`` header string."""
    cookies: dict[str, str] = {}
    if cookie_file:
        path = Path(cookie_file).expanduser()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                cookies.update(_normalize_cookies(data))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to load EZproxy cookies from %s: %s", path, exc)
    if cookie_string:
        for raw_piece in cookie_string.split(";"):
            piece = raw_piece.strip()
            if not piece or "=" not in piece:
                continue
            name, _, value = piece.partition("=")
            cookies[name.strip()] = value.strip()
    return cookies


# ---------------------------------------------------------------------------
# Response classification
# ---------------------------------------------------------------------------


def classify_content(content_type: str, body: bytes) -> ContentClass:
    """Heuristically classify a fetched response.

    Returns one of ``fulltext_html``, ``paywall``, ``login_required``, ``pdf``,
    ``unknown``, or ``empty``. The classification is deliberately conservative:
    paywall signals beat fulltext signals because publishers commonly render
    the abstract + 'Buy access' on the same page.
    """
    ct = (content_type or "").lower()
    if not body:
        return "empty"
    if "application/pdf" in ct or body[:5] == b"%PDF-":
        return "pdf"
    if "html" not in ct and not body[:1024].lower().lstrip().startswith(b"<"):
        return "unknown"

    text = body[:_PROBE_BYTES].decode("utf-8", errors="ignore").lower()

    if any(phrase in text for phrase in _PAYWALL_PHRASES):
        return "paywall"
    if any(phrase in text for phrase in _LOGIN_PHRASES):
        return "login_required"
    if any(phrase in text for phrase in _FULLTEXT_PHRASES) and len(text) >= 4000:
        return "fulltext_html"
    return "unknown"


# ---------------------------------------------------------------------------
# Probe machinery
# ---------------------------------------------------------------------------


@dataclass
class ProbeResult:
    """Single-path access probe result.

    The ``body`` and ``content_type`` fields are only populated when the caller
    requests them via ``return_body=True``. Diagnostic callers leave them empty
    so memory stays bounded.
    """

    path: str  # "direct", "ezproxy", "openurl"
    attempted: bool = False
    success: bool = False
    final_url: str | None = None
    status_code: int | None = None
    content_class: ContentClass | None = None
    content_length: int | None = None
    redirect_chain: list[str] = field(default_factory=list)
    duration_ms: int | None = None
    error: str | None = None
    advice: str | None = None
    body: bytes | None = None
    content_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "attempted": self.attempted,
            "success": self.success,
            "final_url": self.final_url,
            "status_code": self.status_code,
            "content_class": self.content_class,
            "content_length": self.content_length,
            "redirect_chain": self.redirect_chain,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "advice": self.advice,
            # Intentionally exclude `body` from the JSON payload — diagnostic
            # tools should never echo full publisher HTML to the client.
        }


_SUCCESS_CLASSES = {"fulltext_html", "pdf"}

# Patterns for JS / meta-refresh redirect shims that pure HTTP redirects miss.
# Elsevier's linkinghub.elsevier.com is the most common case — it serves a
# tiny HTML page that uses window.location.replace() to bounce to
# www.sciencedirect.com. We extract the target so the probe can keep going.
_META_REFRESH_RE = re.compile(
    rb"""<meta[^>]+http-equiv=["']?refresh["']?[^>]+url=["']?([^"'>\s]+)""",
    re.IGNORECASE,
)
_JS_LOCATION_RE = re.compile(
    rb"""(?:window\.)?location(?:\.(?:replace|assign|href))?\s*[=\(]\s*["']([^"']+)["']""",
    re.IGNORECASE,
)


# Query params that publishers commonly use to embed the next-hop URL on
# cookie-consent / preferences interstitials (e.g. Elsevier's
# linkinghub.elsevier.com/retrieve/articleSelectPrefsPerm?Redirect=...).
_REDIRECT_QUERY_KEYS: tuple[str, ...] = (
    "Redirect",
    "redirect",
    "url",
    "URL",
    "target",
    "Target",
    "destination",
    "next",
)

# Hosts whose interstitials are known to expose the real URL only via a
# query parameter — for these we skip the slow body scan and read the URL.
_INTERSTITIAL_HOSTS: tuple[str, ...] = ("linkinghub.elsevier.com",)


def _extract_redirect_from_query(url: str) -> str | None:
    """Pull a fully-qualified next-hop URL out of the current URL's query string."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if not parsed.query:
        return None
    qs = parse_qs(parsed.query, keep_blank_values=False)
    for key in _REDIRECT_QUERY_KEYS:
        values = qs.get(key)
        if not values:
            continue
        candidate = unquote(values[0]).strip()
        if candidate.startswith(("http://", "https://")):
            return candidate
    return None


def _extract_soft_redirect(body: bytes) -> str | None:
    """Return a redirect target URL embedded in HTML/JS, if any."""
    if not body:
        return None
    snippet = body[: 32 * 1024]
    m = _META_REFRESH_RE.search(snippet)
    if m:
        return m.group(1).decode("utf-8", errors="ignore").strip()
    m = _JS_LOCATION_RE.search(snippet)
    if m:
        target = m.group(1).decode("utf-8", errors="ignore").strip()
        # Filter out trivial same-page anchors and javascript: URLs.
        if target and not target.startswith(("#", "javascript:", "mailto:")):
            return target
    return None


async def _probe_url(
    url: str,
    *,
    cookies: dict[str, str] | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> tuple[httpx.Response | None, list[str], str | None]:
    """Issue a GET, follow up to ``_MAX_REDIRECTS`` redirects (HTTP + soft)."""
    chain: list[str] = []
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5",
    }
    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=timeout,
            cookies=cookies or None,
        ) as client:
            current = url
            for _ in range(_MAX_REDIRECTS):
                chain.append(current)
                response = await client.get(current, headers=headers)
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        return response, chain, None
                    current = str(httpx.URL(current).join(location))
                    continue
                # Detect JS / meta-refresh redirects on small HTML responses,
                # or known interstitial hosts that embed the real URL as a
                # query param (Elsevier's articleSelectPrefsPerm, etc.).
                soft: str | None = None
                host = (httpx.URL(current).host or "").lower()
                if host in _INTERSTITIAL_HOSTS:
                    soft = _extract_redirect_from_query(current)
                if soft is None:
                    ct = response.headers.get("content-type", "").lower()
                    if "html" in ct and len(response.content) < 16 * 1024:
                        soft = _extract_soft_redirect(response.content)
                        if soft is None:
                            # Last-resort: maybe the URL query has the target
                            # even on hosts we did not pre-classify.
                            soft = _extract_redirect_from_query(current)
                if soft:
                    joined = str(httpx.URL(current).join(soft))
                    if joined != current and joined not in chain:
                        current = joined
                        continue
                return response, chain, None
            return None, chain, f"Exceeded {_MAX_REDIRECTS} redirects"
    except httpx.HTTPError as exc:
        return None, chain, f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # defensive: never propagate to MCP tool layer
        return None, chain, f"unexpected: {exc}"


async def probe_direct(
    doi: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT,
    return_body: bool = False,
) -> ProbeResult:
    """Phase 1: probe DOI -> publisher landing page using ambient identity.

    Args:
        doi: DOI to resolve.
        timeout: per-request timeout in seconds.
        return_body: when True, attaches the full publisher response body to
            ``ProbeResult.body`` so callers can extract fulltext from it. Off
            by default so diagnostic callers never buffer large pages.
    """
    result = ProbeResult(path="direct", attempted=True)
    if not doi:
        result.error = "no DOI"
        return result

    start = time.monotonic()
    response, chain, error = await _probe_url(f"https://doi.org/{doi.strip()}", timeout=timeout)
    result.duration_ms = int((time.monotonic() - start) * 1000)
    result.redirect_chain = chain

    if error or response is None:
        result.error = error or "no response"
        result.advice = (
            "Direct DOI fetch failed. If you are off-campus, connect to your "
            "institutional VPN, or configure EZproxy via EZPROXY_HOST + "
            "EZPROXY_COOKIE_FILE."
        )
        return result

    sniff = response.content[:_PROBE_BYTES] if response.content else b""
    content_type = response.headers.get("content-type", "")
    content_class = classify_content(content_type, sniff)
    result.final_url = str(response.url)
    result.status_code = response.status_code
    result.content_class = content_class
    result.content_type = content_type
    result.content_length = int(response.headers.get("content-length") or len(response.content) or 0)
    result.success = response.status_code < 400 and content_class in _SUCCESS_CLASSES
    if return_body:
        result.body = response.content

    if result.success:
        result.advice = "Publisher served fulltext directly. Likely IP-allowlisted."
    elif content_class == "paywall":
        result.advice = (
            "Publisher returned a paywall page. Your current network IP is not "
            "recognized by the publisher's institutional allow-list. Try VPN or "
            "configure EZproxy."
        )
    elif content_class == "login_required":
        result.advice = (
            "Publisher demands SSO/Shibboleth login. Either authenticate in a "
            "browser first and export the cookie for EZproxy mode, or use the "
            "OpenURL handoff."
        )
    else:
        result.advice = (
            f"Inconclusive direct fetch (status {response.status_code}, class "
            f"{content_class}). Inspect final_url manually."
        )
    return result


async def probe_ezproxy(
    doi: str,
    *,
    config: EZProxyConfig | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    return_body: bool = False,
) -> ProbeResult:
    """Phase 2: probe via EZproxy hostname rewrite + replayed session cookie.

    See ``probe_direct`` for ``return_body`` semantics.
    """
    cfg = config or EZProxyConfig.from_env()
    result = ProbeResult(path="ezproxy")

    if not cfg.is_configured:
        result.error = "EZproxy not configured"
        result.advice = (
            "Set EZPROXY_HOST (e.g. ezproxy.lib.ntu.edu.tw) and either "
            "EZPROXY_COOKIE_FILE (path to browser-exported cookies.json) or "
            "EZPROXY_COOKIE (inline header string), then enable EZPROXY_ENABLED=1."
        )
        return result

    if not doi:
        result.attempted = True
        result.error = "no DOI"
        return result

    # Resolve DOI to publisher URL first so we know which host to rewrite.
    start = time.monotonic()
    base_response, base_chain, base_error = await _probe_url(f"https://doi.org/{doi.strip()}", timeout=timeout)
    if base_error or base_response is None or not base_response.url:
        result.attempted = True
        result.error = f"DOI resolution failed: {base_error or 'no response'}"
        result.redirect_chain = base_chain
        result.duration_ms = int((time.monotonic() - start) * 1000)
        return result

    publisher_url = str(base_response.url)
    proxy_url = rewrite_to_ezproxy(publisher_url, cfg.proxy_host)
    if not proxy_url:
        result.attempted = True
        result.error = f"Could not rewrite {publisher_url} for EZproxy"
        return result

    result.attempted = True
    cookies = load_cookies(cfg.cookie_file, cfg.cookie_string)
    if not cookies:
        result.error = "EZproxy cookies are empty or unreadable"
        result.advice = "Export cookies from a logged-in browser session to cookie_file."
        return result

    response, chain, error = await _probe_url(proxy_url, cookies=cookies, timeout=timeout)
    result.duration_ms = int((time.monotonic() - start) * 1000)
    result.redirect_chain = base_chain + chain

    if error or response is None:
        result.error = error or "no response"
        result.advice = (
            "EZproxy fetch failed. Common causes: cookie expired, EZPROXY_HOST "
            "incorrect, or this publisher is not proxied by your institution."
        )
        return result

    sniff = response.content[:_PROBE_BYTES] if response.content else b""
    content_type = response.headers.get("content-type", "")
    content_class = classify_content(content_type, sniff)
    result.final_url = str(response.url)
    result.status_code = response.status_code
    result.content_class = content_class
    result.content_type = content_type
    result.content_length = int(response.headers.get("content-length") or len(response.content) or 0)
    result.success = response.status_code < 400 and content_class in _SUCCESS_CLASSES
    if return_body:
        result.body = response.content

    if result.success:
        result.advice = "EZproxy session delivered fulltext."
    elif content_class == "login_required":
        result.advice = (
            "EZproxy returned a login page. Your session cookie has likely "
            "expired — re-export cookies from a fresh logged-in browser session."
        )
    elif content_class == "paywall":
        result.advice = (
            "EZproxy reached the publisher but returned a paywall page. Your "
            "institution may not subscribe to this journal."
        )
    else:
        result.advice = (
            f"Inconclusive EZproxy fetch (status {response.status_code}, class "
            f"{content_class}). Inspect final_url manually."
        )
    return result


# ---------------------------------------------------------------------------
# Top-level diagnostic composition
# ---------------------------------------------------------------------------


@dataclass
class AccessDiagnosis:
    """Combined diagnosis across direct, EZproxy, and OpenURL paths."""

    pmid: str | None = None
    doi: str | None = None
    summary: str = ""
    probes: list[ProbeResult] = field(default_factory=list)
    openurl: str | None = None
    recommended_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pmid": self.pmid,
            "doi": self.doi,
            "summary": self.summary,
            "probes": [p.to_dict() for p in self.probes],
            "openurl": self.openurl,
            "recommended_path": self.recommended_path,
        }


async def fetch_direct(doi: str, *, timeout: float = _DEFAULT_TIMEOUT) -> ProbeResult:
    """Retrieve publisher landing page via direct DOI, keeping the full body.

    Convenience wrapper around ``probe_direct(..., return_body=True)`` so
    callers that need fulltext content can express intent without juggling
    keyword arguments.
    """
    return await probe_direct(doi, timeout=timeout, return_body=True)


async def fetch_ezproxy(
    doi: str,
    *,
    config: EZProxyConfig | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> ProbeResult:
    """Retrieve publisher page via EZproxy proxy, keeping the full body."""
    return await probe_ezproxy(doi, config=config, timeout=timeout, return_body=True)


async def diagnose_access(
    *,
    pmid: str | None = None,
    doi: str | None = None,
    try_direct: bool = True,
    try_ezproxy: bool = True,
) -> AccessDiagnosis:
    """Run a layered access probe and return a structured diagnosis."""
    diag = AccessDiagnosis(pmid=pmid, doi=doi)

    # Lazy import to avoid a circular dependency with the OpenURL module.
    from pubmed_search.infrastructure.sources.openurl import get_openurl_link

    article: dict[str, Any] = {}
    if pmid:
        article["pmid"] = pmid
    if doi:
        article["doi"] = doi
    diag.openurl = get_openurl_link(article) if article else None

    if not doi:
        diag.summary = "No DOI supplied. Direct/EZproxy fetch needs a DOI; only the OpenURL handoff was generated."
        return diag

    if try_direct:
        diag.probes.append(await probe_direct(doi))
    if try_ezproxy:
        diag.probes.append(await probe_ezproxy(doi))

    success = next((p for p in diag.probes if p.success), None)
    if success:
        diag.recommended_path = success.path
        diag.summary = (
            f"Fulltext reachable via {success.path} path (status {success.status_code}, {success.content_class})."
        )
    else:
        # Pick the most informative failure for the summary.
        ezproxy_probe = next((p for p in diag.probes if p.path == "ezproxy"), None)
        direct_probe = next((p for p in diag.probes if p.path == "direct"), None)
        if ezproxy_probe and ezproxy_probe.attempted:
            diag.recommended_path = "ezproxy"
            diag.summary = ezproxy_probe.advice or "EZproxy attempt failed."
        elif direct_probe and direct_probe.attempted:
            diag.recommended_path = "openurl" if diag.openurl else "direct"
            diag.summary = direct_probe.advice or "Direct fetch failed."
        else:
            diag.recommended_path = "openurl" if diag.openurl else None
            diag.summary = "No automated path succeeded; use OpenURL handoff in a browser."

    return diag


_SAFE_PREVIEW_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def safe_url_preview(url: str | None, *, max_len: int = 120) -> str:
    """Sanitize a URL for logging/display (strip control chars, truncate)."""
    if not url:
        return ""
    cleaned = _SAFE_PREVIEW_PATTERN.sub("", url)
    return cleaned if len(cleaned) <= max_len else cleaned[: max_len - 1] + "…"
