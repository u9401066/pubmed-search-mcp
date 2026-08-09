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

_EXPLICIT_TEST_TOKEN = "explicit-compatible-token"


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


def test_missing_token_is_generated_with_high_entropy(monkeypatch: pytest.MonkeyPatch) -> None:
    generated_value = "g" * 43
    requested_sizes: list[int] = []
    monkeypatch.setattr(
        broker.secrets,
        "token_urlsafe",
        lambda size: requested_sizes.append(size) or generated_value,
    )

    token, generated = broker._resolve_broker_token(None)

    assert token == generated_value
    assert generated is True
    assert requested_sizes == [broker.GENERATED_TOKEN_BYTES]


def test_explicit_token_is_preserved_for_compatibility() -> None:
    token, generated = broker._resolve_broker_token("local-dev-token")

    assert token == "local-dev-token"
    assert generated is False


def test_parser_has_no_public_fixed_token_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BROWSER_FETCH_BROKER_TOKEN", raising=False)
    monkeypatch.delenv("BROWSER_FETCH_TOKEN", raising=False)

    assert broker._build_parser().parse_args([]).token is None


def test_generated_runtime_token_is_shown_and_used(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    generated_token = "generated-high-entropy-runtime-token"
    run = MagicMock()
    monkeypatch.setattr(sys, "argv", ["pubmed-browser-fetch-broker"])
    monkeypatch.setattr(broker, "_resolve_broker_token", lambda _value: (generated_token, True))
    monkeypatch.setattr("uvicorn.run", run)

    with caplog.at_level(logging.WARNING, logger=broker.__name__):
        broker.main()

    app = run.call_args.args[0]
    assert app.state.config.token == generated_token
    assert generated_token in caplog.text


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
            headers={"Authorization": "Bearer explicit-compatible-token"},
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
                "Authorization": "Bearer explicit-compatible-token",
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
                "Authorization": "Bearer explicit-compatible-token",
                "Origin": "http://localhost:8766",
            },
            json={"mode": "pdf", "url": "https://publisher.example/private.pdf"},
        )

    assert response.status_code == 200
    fetch.assert_awaited_once()
