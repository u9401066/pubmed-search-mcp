"""
Pytest configuration and shared fixtures.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

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
    searcher.search.return_value = [mock_article_data]

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
        "topic": "diabetes treatment",
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
        "article_cache": {},
        "search_history": [],
        "reading_list": {},
        "excluded_pmids": [],
        "notes": {},
    }
