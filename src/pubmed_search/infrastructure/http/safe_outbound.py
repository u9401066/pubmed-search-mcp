"""Fail-closed outbound HTTP fetching for user-influenced URLs.

The shared HTTP client provides connection pooling and lifecycle management,
but its normal redirect handling is intentionally unsuitable for URLs supplied
through MCP tools.  This module adds the security boundary required by those
callers: public-address validation before every hop, manual redirects, bounded
streaming, a total deadline, and URL-safe diagnostics.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from pubmed_search.shared.async_utils import get_shared_async_client
from pubmed_search.shared.logging_utils import harden_http_client_logging

logger = logging.getLogger(__name__)

_ALLOWED_SCHEME_PORTS: Mapping[str, int] = {"http": 80, "https": 443}
_FORBIDDEN_DNS_SUFFIXES = (
    ".home.arpa",
    ".internal",
    ".local",
    ".localhost",
)
_FORBIDDEN_DNS_NAMES = {
    "instance-data",
    "localhost",
    "metadata",
    "metadata.google.internal",
}
_MAX_URL_CHARS = 8_192
_SENSITIVE_FORWARD_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})
_IPV6_TRANSITION_NETWORKS = (
    ipaddress.ip_network("64:ff9b::/96"),
    ipaddress.ip_network("64:ff9b:1::/48"),
)

AddressResolver = Callable[[str, int], Awaitable[Sequence[str]]]
RedirectExtractor = Callable[[str, httpx.Response], str | None]


class SafeOutboundError(RuntimeError):
    """Base class for sanitized outbound-request failures."""

    def __init__(self, message: str, *, redirect_chain: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.redirect_chain = tuple(redirect_chain)


class UnsafeOutboundURLError(SafeOutboundError):
    """Raised when a URL can reach a non-public or unsupported destination."""


class OutboundResponseTooLargeError(SafeOutboundError):
    """Raised when declared or streamed response bytes exceed the hard cap."""


@dataclass(frozen=True, slots=True)
class SafeFetchPolicy:
    """Limits applied to one complete outbound fetch, including redirects."""

    max_bytes: int
    total_timeout: float = 20.0
    max_redirects: int = 5

    def __post_init__(self) -> None:
        if isinstance(self.max_bytes, bool) or not isinstance(self.max_bytes, int) or self.max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        if isinstance(self.total_timeout, bool) or not 0 < self.total_timeout <= 120:
            raise ValueError("total_timeout must be between 0 and 120 seconds")
        if (
            isinstance(self.max_redirects, bool)
            or not isinstance(self.max_redirects, int)
            or not 0 <= self.max_redirects <= 10
        ):
            raise ValueError("max_redirects must be between 0 and 10")


@dataclass(frozen=True, slots=True)
class SafeFetchResult:
    """A bounded response plus a redacted record of the followed route."""

    response: httpx.Response
    redirect_chain: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ValidatedOutboundTarget:
    url: httpx.URL
    addresses: tuple[str, ...]


def redact_url_for_log(url: str | httpx.URL | None, *, max_len: int = 120) -> str:
    """Return an origin-only URL preview without credentials, path, or query."""
    if not url:
        return ""
    try:
        parsed = httpx.URL(str(url))
        scheme = parsed.scheme.lower()
        host = parsed.host
        if not scheme or not host:
            return "[invalid URL]"
        rendered_host = f"[{host}]" if ":" in host else host
        port = parsed.port
        default_port = _ALLOWED_SCHEME_PORTS.get(scheme)
        authority = rendered_host if port is None or port == default_port else f"{rendered_host}:{port}"
        preview = f"{scheme}://{authority}/…"
    except (TypeError, ValueError, httpx.InvalidURL):
        return "[invalid URL]"
    if max_len < 2:
        return "…"[:max_len]
    return preview if len(preview) <= max_len else preview[: max_len - 1] + "…"


def _is_public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        elif (
            address.sixtofour is not None
            or address.teredo is not None
            or address.is_site_local
            or any(address in network for network in _IPV6_TRANSITION_NETWORKS)
        ):
            return False
    return bool(
        address.is_global
        and not address.is_loopback
        and not address.is_private
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )


async def resolve_host_addresses(host: str, port: int) -> tuple[str, ...]:
    """Resolve all stream addresses for a hostname without blocking the loop."""

    def _resolve() -> tuple[str, ...]:
        records = socket.getaddrinfo(host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
        return tuple(dict.fromkeys(str(record[4][0]) for record in records))

    try:
        return await asyncio.to_thread(_resolve)
    except (OSError, UnicodeError):
        raise UnsafeOutboundURLError("Outbound hostname could not be resolved") from None


async def _resolve_public_url(
    url: str | httpx.URL,
    *,
    resolver: AddressResolver = resolve_host_addresses,
) -> _ValidatedOutboundTarget:
    raw = str(url)
    if not raw or len(raw) > _MAX_URL_CHARS:
        raise UnsafeOutboundURLError("Outbound URL is empty or too long")
    if any(ord(char) < 0x20 or char == "\x7f" for char in raw):
        raise UnsafeOutboundURLError("Outbound URL contains control characters")
    try:
        parsed = httpx.URL(raw)
        port = parsed.port
    except (ValueError, httpx.InvalidURL):
        raise UnsafeOutboundURLError("Outbound URL is malformed") from None

    scheme = parsed.scheme.lower()
    expected_port = _ALLOWED_SCHEME_PORTS.get(scheme)
    if expected_port is None:
        raise UnsafeOutboundURLError("Outbound URL scheme is not allowed")
    if parsed.username or parsed.password:
        raise UnsafeOutboundURLError("Outbound URL credentials are not allowed")
    if parsed.fragment:
        raise UnsafeOutboundURLError("Outbound URL fragments are not allowed")
    host = (parsed.host or "").rstrip(".").lower()
    if not host or "%" in host:
        raise UnsafeOutboundURLError("Outbound URL hostname is invalid")
    if port is not None and port != expected_port:
        raise UnsafeOutboundURLError("Outbound URL port is not allowed")
    if host in _FORBIDDEN_DNS_NAMES or host.endswith(_FORBIDDEN_DNS_SUFFIXES):
        raise UnsafeOutboundURLError("Outbound URL hostname is not public")

    effective_port = port or expected_port
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        addresses = tuple(await resolver(host, effective_port))
    else:
        addresses = (str(literal),)
    if not addresses or any(not _is_public_address(address) for address in addresses):
        raise UnsafeOutboundURLError("Outbound URL resolved to a non-public address")
    return _ValidatedOutboundTarget(url=parsed, addresses=addresses)


async def validate_public_url(
    url: str | httpx.URL,
    *,
    resolver: AddressResolver = resolve_host_addresses,
) -> httpx.URL:
    """Validate URL syntax and require every resolved address to be public."""
    return (await _resolve_public_url(url, resolver=resolver)).url


def _origin(url: httpx.URL) -> tuple[str, str, int]:
    scheme = url.scheme.lower()
    return (scheme, (url.host or "").lower(), url.port or _ALLOWED_SCHEME_PORTS[scheme])


def _pinned_request_url(target: _ValidatedOutboundTarget) -> tuple[httpx.URL, str]:
    """Pin transport DNS to one validated address while preserving TLS SNI."""
    preferred = sorted(
        target.addresses,
        key=lambda value: isinstance(ipaddress.ip_address(value.split("%", 1)[0]), ipaddress.IPv6Address),
    )[0]
    return target.url.copy_with(host=preferred), target.url.raw_host.decode("ascii")


def _cookie_header(cookies: Mapping[str, str] | None) -> str:
    if not cookies:
        return ""
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def _discard_response_cookies(client: Any, response: httpx.Response) -> None:
    """Remove response cookies so the process-wide client never retains them."""
    client_cookies = getattr(client, "cookies", None)
    if client_cookies is None:
        return
    for cookie in response.cookies.jar:
        try:
            client_cookies.delete(cookie.name, domain=cookie.domain, path=cookie.path)
        except (KeyError, ValueError):
            continue


def _validate_peer_if_available(response: httpx.Response) -> None:
    """Reject a non-public connected peer when the transport exposes it."""
    stream = response.extensions.get("network_stream")
    if stream is None or not hasattr(stream, "get_extra_info"):
        return
    peer = stream.get_extra_info("server_addr")
    if isinstance(peer, tuple) and peer and not _is_public_address(str(peer[0])):
        raise UnsafeOutboundURLError("Outbound connection reached a non-public peer")


def _declared_length(response: httpx.Response) -> int | None:
    value = response.headers.get("content-length")
    if value is None:
        return None
    try:
        length = int(value)
    except ValueError:
        return None
    return length if length >= 0 else None


async def _read_bounded(response: httpx.Response, *, max_bytes: int, chain: Sequence[str]) -> bytes:
    content_encoding = response.headers.get("content-encoding", "").strip().lower()
    if content_encoding and content_encoding != "identity":
        raise SafeOutboundError("Encoded outbound responses are not allowed", redirect_chain=chain)
    declared = _declared_length(response)
    if declared is not None and declared > max_bytes:
        raise OutboundResponseTooLargeError(
            f"Outbound response exceeds the {max_bytes}-byte limit",
            redirect_chain=chain,
        )
    body = bytearray()
    async for chunk in response.aiter_bytes(min(64 * 1024, max_bytes + 1)):
        if len(body) + len(chunk) > max_bytes:
            raise OutboundResponseTooLargeError(
                f"Outbound response exceeds the {max_bytes}-byte limit",
                redirect_chain=chain,
            )
        body.extend(chunk)
    return bytes(body)


async def _fetch_public_url(
    url: str,
    *,
    policy: SafeFetchPolicy,
    headers: Mapping[str, str] | None,
    cookies: Mapping[str, str] | None,
    resolver: AddressResolver,
    redirect_extractor: RedirectExtractor | None,
    client: Any,
) -> SafeFetchResult:
    current: str | httpx.URL = url
    initial_origin: tuple[str, str, int] | None = None
    raw_seen: set[str] = set()
    chain: list[str] = []

    for hop in range(policy.max_redirects + 1):
        try:
            target = await _resolve_public_url(current, resolver=resolver)
        except UnsafeOutboundURLError as exc:
            raise UnsafeOutboundURLError(str(exc), redirect_chain=chain) from None
        current = target.url
        if initial_origin is None:
            initial_origin = _origin(current)
        raw_current = str(current)
        if raw_current in raw_seen:
            raise SafeOutboundError("Outbound redirect cycle detected", redirect_chain=chain)
        raw_seen.add(raw_current)
        chain.append(redact_url_for_log(current))

        request_headers = dict(headers or {})
        for name in tuple(request_headers):
            if name.lower() in {"accept-encoding", "connection", "cookie", "host"}:
                request_headers.pop(name, None)
        request_headers["Accept-Encoding"] = "identity"
        request_headers["Connection"] = "close"
        request_headers["Host"] = current.netloc.decode("ascii")
        if _origin(current) == initial_origin:
            request_headers["Cookie"] = _cookie_header(cookies)
        else:
            for name in tuple(request_headers):
                if name.lower() in _SENSITIVE_FORWARD_HEADERS:
                    request_headers.pop(name, None)
            request_headers["Cookie"] = ""

        logger.info("Fetching validated outbound resource (redirect hop %s)", hop)
        pinned_url, sni_hostname = _pinned_request_url(target)
        try:
            async with client.stream(
                "GET",
                pinned_url,
                headers=request_headers,
                follow_redirects=False,
                timeout=policy.total_timeout,
                extensions={"sni_hostname": sni_hostname},
            ) as streamed:
                try:
                    _validate_peer_if_available(streamed)
                    if streamed.is_redirect:
                        location = streamed.headers.get("location")
                        if location:
                            next_url = current.join(location)
                        else:
                            body = await _read_bounded(streamed, max_bytes=policy.max_bytes, chain=chain)
                            response = httpx.Response(
                                streamed.status_code,
                                headers=streamed.headers,
                                content=body,
                                request=httpx.Request("GET", current),
                            )
                            return SafeFetchResult(response=response, redirect_chain=tuple(chain))
                    else:
                        body = await _read_bounded(streamed, max_bytes=policy.max_bytes, chain=chain)
                        response = httpx.Response(
                            streamed.status_code,
                            headers=streamed.headers,
                            content=body,
                            request=httpx.Request("GET", current),
                        )
                        extracted = redirect_extractor(raw_current, response) if redirect_extractor else None
                        if not extracted:
                            return SafeFetchResult(response=response, redirect_chain=tuple(chain))
                        next_url = current.join(extracted)
                finally:
                    _discard_response_cookies(client, streamed)
        except SafeOutboundError:
            raise
        except (ValueError, httpx.HTTPError, httpx.InvalidURL):
            raise SafeOutboundError("Outbound request failed", redirect_chain=chain) from None

        if hop >= policy.max_redirects:
            raise SafeOutboundError(
                f"Outbound request exceeded {policy.max_redirects} redirects",
                redirect_chain=chain,
            )
        current = next_url

    raise SafeOutboundError("Outbound redirect limit reached", redirect_chain=chain)


async def fetch_public_url(
    url: str,
    *,
    policy: SafeFetchPolicy,
    headers: Mapping[str, str] | None = None,
    cookies: Mapping[str, str] | None = None,
    resolver: AddressResolver = resolve_host_addresses,
    redirect_extractor: RedirectExtractor | None = None,
    client: Any | None = None,
) -> SafeFetchResult:
    """Fetch one public URL through the shared client under strict limits."""
    harden_http_client_logging()
    selected_client = client if client is not None else get_shared_async_client()
    try:
        return await asyncio.wait_for(
            _fetch_public_url(
                url,
                policy=policy,
                headers=headers,
                cookies=cookies,
                resolver=resolver,
                redirect_extractor=redirect_extractor,
                client=selected_client,
            ),
            timeout=policy.total_timeout,
        )
    except asyncio.TimeoutError:
        raise SafeOutboundError("Outbound request exceeded its total deadline") from None


__all__ = [
    "OutboundResponseTooLargeError",
    "SafeFetchPolicy",
    "SafeFetchResult",
    "SafeOutboundError",
    "UnsafeOutboundURLError",
    "fetch_public_url",
    "redact_url_for_log",
    "resolve_host_addresses",
    "validate_public_url",
]
