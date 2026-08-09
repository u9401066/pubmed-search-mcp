"""Local browser-session fetch broker for authenticated PDF downloads."""

from __future__ import annotations

import argparse
import asyncio
import base64
import ipaddress
import logging
import os
import secrets
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8766
DEFAULT_TIMEOUT_SECONDS = 45
DEFAULT_MAX_BYTES = 50 * 1024 * 1024
GENERATED_TOKEN_BYTES = 32

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable


@dataclass(frozen=True)
class BrokerConfig:
    """Runtime settings for the local browser broker."""

    host: str
    port: int
    token: str
    headless: bool
    user_data_dir: Path
    download_dir: Path
    timeout_seconds: int
    max_bytes: int


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, *, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _default_path(env_name: str, suffix: str) -> Path:
    return Path(os.environ.get(env_name, Path.home() / ".pubmed-search-mcp" / suffix)).expanduser()


def _is_loopback_host(host: str) -> bool:
    """Return whether *host* names a literal loopback or localhost."""
    normalized = host.strip().lower().removeprefix("[").removesuffix("]").rstrip(".")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _is_loopback_authority(authority: str | None) -> bool:
    """Validate an HTTP Host/authority without resolving attacker-controlled DNS."""
    if not authority:
        return False
    try:
        parsed = urlsplit(f"//{authority}")
        if parsed.username is not None or parsed.password is not None or parsed.path:
            return False
        # Accessing ``port`` also rejects malformed and out-of-range ports.
        _ = parsed.port
    except ValueError:
        return False
    return _is_loopback_host(parsed.hostname or "")


def _is_loopback_origin(origin: str) -> bool:
    """Return whether a browser Origin is an explicit local HTTP(S) origin."""
    try:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or parsed.username is not None or parsed.password is not None:
            return False
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            return False
        _ = parsed.port
    except ValueError:
        return False
    return _is_loopback_host(parsed.hostname or "")


def _resolve_broker_token(explicit_token: str | None) -> tuple[str, bool]:
    """Keep explicit tokens compatible, otherwise create a high-entropy token."""
    if explicit_token is not None and explicit_token.strip():
        return explicit_token, False
    return secrets.token_urlsafe(GENERATED_TOKEN_BYTES), True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the local PubMed Search browser-session PDF fetch broker.",
    )
    parser.add_argument("--host", default=os.environ.get("BROWSER_FETCH_BROKER_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=_env_int("BROWSER_FETCH_BROKER_PORT", default=DEFAULT_PORT))
    parser.add_argument(
        "--token",
        default=os.environ.get("BROWSER_FETCH_BROKER_TOKEN") or os.environ.get("BROWSER_FETCH_TOKEN") or None,
        help="Bearer token required by MCP requests. A high-entropy runtime token is generated when omitted.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=_env_bool("BROWSER_FETCH_BROKER_HEADLESS", default=False),
        help="Run Chromium headless. Default keeps a visible browser for institutional login.",
    )
    parser.add_argument(
        "--user-data-dir",
        default=str(_default_path("BROWSER_FETCH_BROKER_USER_DATA_DIR", "browser-broker-profile")),
        help="Persistent Chromium profile directory for login state.",
    )
    parser.add_argument(
        "--download-dir",
        default=str(_default_path("BROWSER_FETCH_BROKER_DOWNLOAD_DIR", "browser-broker-downloads")),
        help="Directory for Playwright-intercepted downloads.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=_env_int("BROWSER_FETCH_TIMEOUT", default=DEFAULT_TIMEOUT_SECONDS),
        help="Navigation and download timeout in seconds.",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=_env_int("BROWSER_FETCH_MAX_BYTES", default=DEFAULT_MAX_BYTES),
        help="Maximum PDF payload size returned to the MCP server.",
    )
    return parser


def _candidate_score(link: dict[str, str]) -> int:
    href = link.get("href", "").lower()
    text = link.get("text", "").lower()
    score = 0
    if ".pdf" in href or "pdf" in href:
        score += 4
    if "download" in href or "download" in text:
        score += 2
    if "full text" in text or "full-text" in text:
        score += 1
    return score


def _ensure_size(content: bytes, *, max_bytes: int) -> bytes:
    if len(content) > max_bytes:
        msg = f"PDF exceeds max_bytes ({len(content)} > {max_bytes})"
        raise HTTPException(status_code=413, detail=msg)
    return content


async def _response_pdf_bytes(response: Any, *, max_bytes: int) -> bytes | None:
    if response is None:
        return None
    content_type = (response.headers or {}).get("content-type", "")
    if "application/pdf" not in content_type.lower():
        return None
    return _ensure_size(await response.body(), max_bytes=max_bytes)


async def _download_pdf_bytes(download: Any, *, max_bytes: int) -> bytes:
    path = await download.path()
    if not path:
        target = Path(download.suggested_filename or "download.pdf")
        await download.save_as(str(target))
        path = str(target)
    return _ensure_size(Path(path).read_bytes(), max_bytes=max_bytes)


async def _find_pdf_links(page: Any) -> list[str]:
    raw_links = await page.eval_on_selector_all(
        "a[href]",
        """
        links => links.map(link => ({
          href: link.href || "",
          text: (link.textContent || "").trim()
        }))
        """,
    )
    links = [link for link in raw_links if isinstance(link, dict)]
    ranked = sorted(links, key=_candidate_score, reverse=True)
    return [str(link.get("href")) for link in ranked if _candidate_score(link) > 0 and link.get("href")]


async def _goto_with_download_capture(
    page: Any, url: str, *, timeout_ms: int, max_bytes: int
) -> tuple[bytes | None, str]:
    download_task = asyncio.create_task(page.wait_for_event("download", timeout=timeout_ms))
    response = None
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception:
        with suppress(Exception):
            download = await download_task
            return await _download_pdf_bytes(download, max_bytes=max_bytes), getattr(download, "url", url)
        raise

    with suppress(Exception):
        download = await asyncio.wait_for(download_task, timeout=1.0)
        return await _download_pdf_bytes(download, max_bytes=max_bytes), getattr(download, "url", url)

    if not download_task.done():
        download_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await download_task

    pdf_bytes = await _response_pdf_bytes(response, max_bytes=max_bytes)
    return pdf_bytes, page.url


async def _fetch_pdf_with_browser(app: FastAPI, payload: dict[str, Any]) -> dict[str, Any]:
    context = app.state.browser_context
    config: BrokerConfig = app.state.config
    url = str(payload.get("url", "")).strip()
    if not url.startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="Payload must include an http(s) url")

    max_bytes = min(int(payload.get("max_bytes") or config.max_bytes), config.max_bytes)
    timeout_ms = config.timeout_seconds * 1000
    page = await context.new_page()
    try:
        content, final_url = await _goto_with_download_capture(page, url, timeout_ms=timeout_ms, max_bytes=max_bytes)
        if not content and payload.get("follow_pdf_links", True):
            for candidate in await _find_pdf_links(page):
                content, final_url = await _goto_with_download_capture(
                    page,
                    candidate,
                    timeout_ms=timeout_ms,
                    max_bytes=max_bytes,
                )
                if content:
                    break

        if not content:
            return {
                "success": False,
                "error": "No PDF response or PDF download was detected",
                "final_url": page.url,
            }

        return {
            "success": True,
            "content_b64": base64.b64encode(content).decode("ascii"),
            "content_type": "application/pdf",
            "final_url": final_url,
            "status_code": 200,
        }
    finally:
        await page.close()


def create_app(config: BrokerConfig) -> FastAPI:
    """Create the broker FastAPI app."""
    if not _is_loopback_host(config.host):
        msg = "Browser fetch broker may only bind a loopback host"
        raise ValueError(msg)
    if not config.token.strip():
        msg = "Browser fetch broker requires a non-empty bearer token"
        raise ValueError(msg)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            msg = "Install browser broker dependencies with `uv sync --extra browser-broker`."
            raise RuntimeError(msg) from exc

        config.user_data_dir.mkdir(parents=True, exist_ok=True)
        config.download_dir.mkdir(parents=True, exist_ok=True)
        playwright = await async_playwright().start()
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(config.user_data_dir),
            headless=config.headless,
            accept_downloads=True,
            downloads_path=str(config.download_dir),
        )
        app.state.playwright = playwright
        app.state.browser_context = context
        try:
            yield
        finally:
            await context.close()
            await playwright.stop()

    app = FastAPI(title="PubMed Search Browser Fetch Broker", lifespan=lifespan)
    app.state.config = config

    @app.middleware("http")
    async def enforce_local_boundary(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Block DNS rebinding before health, auth, or browser state is reached."""
        if not _is_loopback_authority(request.headers.get("host")):
            return PlainTextResponse("Invalid Host header", status_code=421)
        origin = request.headers.get("origin")
        if origin is not None and not _is_loopback_origin(origin):
            return PlainTextResponse("Invalid Origin header", status_code=403)
        return await call_next(request)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "pubmed-browser-fetch-broker"}

    @app.post("/fetch")
    async def fetch(request: Request) -> JSONResponse:
        auth_header = request.headers.get("authorization", "")
        if not secrets.compare_digest(auth_header, f"Bearer {config.token}"):
            raise HTTPException(status_code=401, detail="Invalid bearer token")

        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="JSON object payload required")
        if payload.get("mode", "pdf") != "pdf":
            raise HTTPException(status_code=400, detail='Only mode="pdf" is supported')

        result = await _fetch_pdf_with_browser(request.app, payload)
        status_code = 200 if result.get("success") else 502
        return JSONResponse(result, status_code=status_code)

    return app


def main() -> None:
    """Run the browser fetch broker."""
    parser = _build_parser()
    args = parser.parse_args()
    if not _is_loopback_host(args.host):
        parser.error("browser fetch broker is local-only; --host must be a loopback address")
    token, generated = _resolve_broker_token(args.token)
    if generated:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
        logger.warning(
            "No browser broker token was configured. Generated runtime token (copy it to BROWSER_FETCH_TOKEN): %s",
            token,
        )
    config = BrokerConfig(
        host=args.host,
        port=args.port,
        token=token,
        headless=args.headless,
        user_data_dir=Path(args.user_data_dir).expanduser(),
        download_dir=Path(args.download_dir).expanduser(),
        timeout_seconds=args.timeout,
        max_bytes=args.max_bytes,
    )

    import uvicorn

    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        server_header=False,
    )


if __name__ == "__main__":
    main()
