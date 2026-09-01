"""Contracts for explicitly opting into external API integration tests."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

INTEGRATION_MODULE = Path(__file__).with_name("test_integration.py")
CONFTEST_MODULE = Path(__file__).with_name("conftest.py")


def _live_skip_condition() -> bool:
    namespace = runpy.run_path(str(INTEGRATION_MODULE))
    markers = namespace["pytestmark"]
    skipif = next(marker for marker in markers if marker.name == "skipif")
    return bool(skipif.args[0])


def _central_live_gate_enabled() -> bool:
    namespace = runpy.run_path(str(CONFTEST_MODULE))
    return bool(namespace["live_tests_enabled"]())


def test_live_integrations_are_disabled_without_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PUBMED_RUN_LIVE_TESTS", raising=False)
    monkeypatch.delenv("SKIP_INTEGRATION", raising=False)

    assert _live_skip_condition() is True


def test_live_integrations_can_be_enabled_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBMED_RUN_LIVE_TESTS", "1")
    monkeypatch.delenv("SKIP_INTEGRATION", raising=False)

    assert _live_skip_condition() is False


def test_central_live_gate_is_disabled_without_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PUBMED_RUN_LIVE_TESTS", raising=False)
    monkeypatch.delenv("SKIP_INTEGRATION", raising=False)

    assert _central_live_gate_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "YES"])
def test_central_live_gate_accepts_explicit_true_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("PUBMED_RUN_LIVE_TESTS", value)
    monkeypatch.delenv("SKIP_INTEGRATION", raising=False)

    assert _central_live_gate_enabled() is True


@pytest.mark.parametrize("value", ["1", "true", "YES"])
def test_explicit_skip_overrides_live_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("PUBMED_RUN_LIVE_TESTS", "1")
    monkeypatch.setenv("SKIP_INTEGRATION", value)

    assert _central_live_gate_enabled() is False


def test_unmarked_external_dns_is_blocked_by_default() -> None:
    import socket

    with pytest.raises(AssertionError, match="Offline test attempted external DNS"):
        socket.getaddrinfo("example.com", 443)


def test_loopback_dns_remains_available() -> None:
    import socket

    assert socket.getaddrinfo("127.0.0.1", 80)
    assert socket.getaddrinfo(None, 0)
