"""Contracts for explicitly opting into external API integration tests."""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

INTEGRATION_MODULE = Path(__file__).with_name("test_integration.py")


def _live_skip_condition() -> bool:
    namespace = runpy.run_path(str(INTEGRATION_MODULE))
    markers = namespace["pytestmark"]
    skipif = next(marker for marker in markers if marker.name == "skipif")
    return bool(skipif.args[0])


def test_live_integrations_are_disabled_without_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PUBMED_RUN_LIVE_TESTS", raising=False)
    monkeypatch.delenv("SKIP_INTEGRATION", raising=False)

    assert _live_skip_condition() is True


def test_live_integrations_can_be_enabled_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBMED_RUN_LIVE_TESTS", "1")
    monkeypatch.delenv("SKIP_INTEGRATION", raising=False)

    assert _live_skip_condition() is False
