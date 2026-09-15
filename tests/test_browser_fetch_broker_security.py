"""Security boundary tests for the local browser-session broker."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from pubmed_search.presentation import browser_fetch_broker as broker

if TYPE_CHECKING:
    from pathlib import Path

_EXPLICIT_TEST_TOKEN = "explicit-test-token-0123456789abcdef"


def _config(tmp_path: Path, *, host: str = "127.0.0.1", token: str | None = None) -> broker.BrokerConfig:
    return broker.BrokerConfig(
        host=host,
        port=8766,
        token=token or _EXPLICIT_TEST_TOKEN,
        headless=True,
        user_data_dir=tmp_path / "profile",
        download_dir=tmp_path / "downloads",
        timeout_seconds=1,
        max_bytes=1024,
    )


@pytest.mark.parametrize(
    "authority",
    ["localhost", "localhost:8766", "127.0.0.1:8766", "127.10.20.30:1", "[::1]:8766"],
)
def test_loopback_authority_accepts_only_explicit_local_names(authority: str) -> None:
    assert broker._is_loopback_authority(authority) is True


@pytest.mark.parametrize(
    "authority",
    [None, "", "0.0.0.0:8766", "attacker.example:8766", "localhost.attacker.example", "user@127.0.0.1"],
)
def test_loopback_authority_rejects_remote_or_malformed_names(authority: str | None) -> None:
    assert broker._is_loopback_authority(authority) is False


@pytest.mark.parametrize("token", [None, "", "short-token", "x" * 31, "x" * 31 + " ", "x" * 16 + " " + "x" * 16])
def test_missing_weak_or_whitespace_token_is_rejected(token: str | None) -> None:
    with pytest.raises(ValueError, match="token"):
        broker._require_broker_token(token)


def test_explicit_shared_token_is_preserved_exactly() -> None:
    token = "local-dev-token-0123456789abcdefgh"

    assert broker._require_broker_token(token) == token


def test_parser_has_no_public_fixed_token_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BROWSER_FETCH_BROKER_TOKEN", raising=False)
    monkeypatch.delenv("BROWSER_FETCH_TOKEN", raising=False)

    assert broker._build_parser().parse_args([]).token is None


def test_missing_runtime_token_aborts_before_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = MagicMock()
    monkeypatch.setattr(sys, "argv", ["pubmed-browser-fetch-broker"])
    monkeypatch.setattr("uvicorn.run", run)

    with pytest.raises(SystemExit, match="2"):
        broker.main()

    run.assert_not_called()


def test_explicit_runtime_token_is_used_without_logging_secret(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    run = MagicMock()
    monkeypatch.setattr(sys, "argv", ["pubmed-browser-fetch-broker", "--token", _EXPLICIT_TEST_TOKEN])
    monkeypatch.setattr("uvicorn.run", run)

    with caplog.at_level(logging.WARNING, logger=broker.__name__):
        broker.main()

    app = run.call_args.args[0]
    assert app.state.config.token == _EXPLICIT_TEST_TOKEN
    assert _EXPLICIT_TEST_TOKEN not in caplog.text


def test_remote_bind_is_rejected_by_app_factory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="loopback"):
        broker.create_app(_config(tmp_path, host="0.0.0.0"))  # noqa: S104


def test_remote_bind_is_rejected_by_cli_before_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["pubmed-browser-fetch-broker", "--host", "192.168.1.10"])

    with pytest.raises(SystemExit, match="2"):
        broker.main()


@pytest.mark.asyncio
async def test_global_guard_rejects_dns_rebinding_host_before_browser_fetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(broker, "_fetch_pdf_with_browser", fetch)
    app = broker.create_app(_config(tmp_path))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://attacker.example:8766",
    ) as client:
        response = await client.post(
            "/fetch",
            headers={"Authorization": f"Bearer {_EXPLICIT_TEST_TOKEN}"},
            json={"mode": "pdf", "url": "https://publisher.example/private.pdf"},
        )

    assert response.status_code == 421
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_global_guard_rejects_remote_origin_on_loopback_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(broker, "_fetch_pdf_with_browser", fetch)
    app = broker.create_app(_config(tmp_path))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:8766",
    ) as client:
        response = await client.post(
            "/fetch",
            headers={
                "Authorization": f"Bearer {_EXPLICIT_TEST_TOKEN}",
                "Origin": "https://attacker.example",
            },
            json={"mode": "pdf", "url": "https://publisher.example/private.pdf"},
        )

    assert response.status_code == 403
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_loopback_origin_and_explicit_token_reach_browser_fetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch = AsyncMock(return_value={"success": True, "content_b64": "c2VjcmV0"})
    monkeypatch.setattr(broker, "_fetch_pdf_with_browser", fetch)
    app = broker.create_app(_config(tmp_path))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:8766",
    ) as client:
        response = await client.post(
            "/fetch",
            headers={
                "Authorization": f"Bearer {_EXPLICIT_TEST_TOKEN}",
                "Origin": "http://localhost:8766",
            },
            json={"mode": "pdf", "url": "https://publisher.example/private.pdf"},
        )

    assert response.status_code == 200
    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_download_fallback_ignores_publisher_filename_and_checks_pdf(tmp_path: Path) -> None:
    from pathlib import Path

    destination = tmp_path / "existing.txt"
    destination.write_bytes(b"keep")
    download = MagicMock(suggested_filename=str(destination))
    download.path = AsyncMock(return_value=None)

    async def save(path: str) -> None:
        Path(path).write_bytes(b"%PDF-test")

    download.save_as = AsyncMock(side_effect=save)
    assert await broker._download_pdf_bytes(download, max_bytes=64) == b"%PDF-test"
    assert destination.read_bytes() == b"keep"
    with pytest.raises(broker.HTTPException):
        broker._ensure_size(b"<html>login</html>", max_bytes=64)


@pytest.mark.asyncio
async def test_navigation_cancellation_releases_download_listener() -> None:
    import asyncio

    started = asyncio.Event()
    released = asyncio.Event()

    async def wait_download(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            released.set()

    page = MagicMock()
    page.wait_for_event = wait_download

    async def cancelled_navigation(*args, **kwargs):
        await started.wait()
        raise asyncio.CancelledError

    page.goto = cancelled_navigation
    task = asyncio.create_task(
        broker._goto_with_download_capture(page, "https://publisher.example", timeout_ms=100, max_bytes=64)
    )
    await started.wait()
    with pytest.raises(asyncio.CancelledError):
        await task
    try:
        assert released.is_set()
    finally:
        # Failed original implementation leaves an orphan task; reclaim it in the test.
        for pending in asyncio.all_tasks():
            if pending is not asyncio.current_task() and pending.get_coro().__name__ == "wait_download":
                pending.cancel()
                try:
                    await pending
                except asyncio.CancelledError:
                    pass
