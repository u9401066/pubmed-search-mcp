"""
Pytest configuration and shared fixtures.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import tempfile
from pathlib import Path
from typing import Any, NoReturn
from unittest.mock import AsyncMock, Mock

import pytest

from pubmed_search.application.search.source_models import SourceSearchPage

_TRUE_ENV_VALUES = frozenset({"1", "true", "yes"})
_LIVE_TEST_OPT_IN = "PUBMED_RUN_LIVE_TESTS"
_LIVE_TEST_OPT_OUT = "SKIP_INTEGRATION"


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE_ENV_VALUES


def live_tests_enabled() -> bool:
    """Return whether external-API tests were explicitly enabled."""
    return _env_flag(_LIVE_TEST_OPT_IN) and not _env_flag(_LIVE_TEST_OPT_OUT)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Keep every integration test out of the default, offline test run."""
    if live_tests_enabled():
        return

    skip_live = pytest.mark.skip(
        reason=("external integration test; set PUBMED_RUN_LIVE_TESTS=1 and select -m integration to run it")
    )
    for item in items:
        if item.get_closest_marker("integration") is not None:
            item.add_marker(skip_live)


def _is_local_address(host: object) -> bool:
    if host is None:
        return True
    value = host.decode() if isinstance(host, bytes) else str(host)
    if value.lower().rstrip(".") in {"localhost", "localhost.localdomain"}:
        return True
    try:
        address = ipaddress.ip_address(value.strip("[]"))
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


@pytest.fixture(autouse=True)
def _block_unmarked_external_network(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail fast if a default-suite test accidentally reaches the Internet."""
    if request.node.get_closest_marker("integration") is not None and live_tests_enabled():
        return

    original_getaddrinfo = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded_getaddrinfo(host: object, port: object, *args: Any, **kwargs: Any) -> Any:
        if _is_local_address(host):
            return original_getaddrinfo(host, port, *args, **kwargs)
        raise AssertionError(
            f"Offline test attempted external DNS resolution for {host!r}; "
            "mock the transport or mark the test integration"
        )

    def guarded_connect(sock: socket.socket, address: object) -> Any:
        if not isinstance(address, tuple) or not address or _is_local_address(address[0]):
            return original_connect(sock, address)  # type: ignore[arg-type]
        _reject_external_connection(address)

    def guarded_connect_ex(sock: socket.socket, address: object) -> int:
        if not isinstance(address, tuple) or not address or _is_local_address(address[0]):
            return original_connect_ex(sock, address)  # type: ignore[arg-type]
        _reject_external_connection(address)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)


def _reject_external_connection(address: object) -> NoReturn:
    raise AssertionError(
        f"Offline test attempted external socket connection to {address!r}; "
        "mock the transport or mark the test integration"
    )


# ============================================================
# Environment Fixtures
# ============================================================


@pytest.fixture
def temp_dir():
    """Provide a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_email():
    """Provide a mock email for NCBI API."""
    return "test@example.com"


# ============================================================
# Mock NCBI API Responses
# ============================================================


@pytest.fixture
def mock_search_response():
    """Mock response from NCBI ESearch."""
    return {
        "IdList": ["12345678", "23456789", "34567890"],
        "Count": "3",
        "QueryKey": "1",
        "WebEnv": "MOCK_WEB_ENV",
    }


@pytest.fixture
def mock_article_data():
    """Mock article data from NCBI EFetch."""
    return {
        "pmid": "12345678",
        "title": "Test Article: Effects of Drug X on Condition Y",
        "authors": ["Smith J", "Doe J", "Johnson A"],
        "authors_full": [
            {"lastname": "Smith", "forename": "John", "initials": "J"},
            {"lastname": "Doe", "forename": "Jane", "initials": "J"},
            {"lastname": "Johnson", "forename": "Alice", "initials": "A"},
        ],
        "abstract": "Background: This is a test abstract. Methods: We conducted a study. Results: We found significant results. Conclusion: Drug X is effective.",
        "journal": "Journal of Test Medicine",
        "journal_abbrev": "J Test Med",
        "year": "2024",
        "month": "Jan",
        "day": "15",
        "volume": "10",
        "issue": "1",
        "pages": "100-110",
        "doi": "10.1000/test.2024.001",
        "pmc_id": "PMC9876543",
        "keywords": ["drug x", "condition y", "treatment"],
        "mesh_terms": ["Drug Therapy", "Clinical Trial"],
    }


@pytest.fixture
def mock_mesh_response():
    """Mock response from MeSH database search."""
    return {
        "IdList": ["D003920"],  # Diabetes Mellitus
        "TranslationSet": [{"From": "diabetes", "To": '"Diabetes Mellitus"[MeSH Terms]'}],
    }


@pytest.fixture
def mock_espell_response():
    """Mock response from ESpell."""
    return {"Query": "diabetis", "CorrectedQuery": "diabetes"}


# ============================================================
# Mock Searcher
# ============================================================


@pytest.fixture
def mock_searcher(mock_article_data, mock_search_response):
    """Create a mock LiteratureSearcher."""
    searcher = AsyncMock()
    searcher.search_page.return_value = SourceSearchPage(
        source="pubmed",
        items=[mock_article_data],
        total=1,
        query="mock query",
        metadata={"physical_query": "mock query", "query_executed": True},
    )

    # Mock fetch_details
    searcher.fetch_details.return_value = [mock_article_data]

    # Mock spell_check_query
    searcher.spell_check_query.return_value = "corrected query"

    # Mock mesh_lookup (from strategy module)
    searcher.mesh_lookup = Mock(
        return_value={
            "term": "diabetes",
            "mesh_terms": ["Diabetes Mellitus", "Diabetes Mellitus, Type 2"],
            "entry_terms": ["diabetic", "diabetes mellitus"],
        }
    )

    return searcher


# ============================================================
# Session Fixtures
# ============================================================


@pytest.fixture
def sample_session_data():
    """Sample session data for testing."""
    return {
        "session_id": "test-session-001",
        "schema_version": "research-session/v1",
        "topic": "diabetes treatment",
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
        "cached_pmids": [],
        "search_history": [],
        "search_runs": [],
        "event_log": [],
        "reading_list": {},
        "excluded_pmids": [],
        "notes": {},
        "artifacts": [],
    }
