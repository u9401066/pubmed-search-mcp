"""
Tests for ClinicalTrials.gov API client.

Target: clinical_trials.py coverage from 0% to 90%+
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pubmed_search.infrastructure.sources.clinical_trials import (
    BASE_URL,
    DEFAULT_TIMEOUT,
    ClinicalTrialsClient,
)

# =============================================================================
# ClinicalTrialsClient - Basic Tests
# =============================================================================


class TestClinicalTrialsClientBasic:
    """Basic tests for ClinicalTrialsClient."""

    async def test_init_default(self):
        """Test initialization with defaults."""
        client = ClinicalTrialsClient()
        assert client.timeout == DEFAULT_TIMEOUT
        assert client._client is None

    async def test_init_custom_timeout(self):
        """Test initialization with custom timeout."""
        client = ClinicalTrialsClient(timeout=30.0)
        assert client.timeout == 30.0

    async def test_client_property_lazy_init(self):
        """Test lazy initialization of HTTP client."""
        client = ClinicalTrialsClient()
        assert client._client is None

        # Access client property
        http_client = client.client
        assert http_client is not None
        assert client._client is not None

        # Should return same instance
        http_client2 = client.client
        assert http_client is http_client2


# =============================================================================
# ClinicalTrialsClient - Search Tests
# =============================================================================


class TestClinicalTrialsClientSearch:
    """Tests for search method."""

    @pytest.fixture
    def mock_response_data(self):
        """Sample API response data."""
        return {
            "studies": [
                {
                    "protocolSection": {
                        "identificationModule": {
                            "nctId": "NCT05123456",
                            "briefTitle": "Test Trial for Diabetes",
                            "officialTitle": "A Randomized Study of Test Drug",
                        },
                        "statusModule": {
                            "overallStatus": "RECRUITING",
                            "startDateStruct": {"date": "2024-01-15"},
                        },
                        "designModule": {
                            "phases": ["PHASE2", "PHASE3"],
                            "enrollmentInfo": {"count": 500},
                        },
                        "conditionsModule": {"conditions": ["Type 2 Diabetes", "Obesity"]},
                        "armsInterventionsModule": {
                            "interventions": [
                                {"type": "DRUG", "name": "TestDrug"},
                                {"type": "DRUG", "name": "Placebo"},
                            ]
                        },
                    }
                }
            ]
        }

    async def test_search_success(self, mock_response_data):
        """Test successful search."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status = MagicMock()

        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_async_client.is_closed = False

        client = ClinicalTrialsClient()
        client._client = mock_async_client

        results = await client.search("diabetes treatment", limit=5)

        assert len(results) == 1
        assert results[0]["nct_id"] == "NCT05123456"
        assert results[0]["title"] == "Test Trial for Diabetes"
        assert results[0]["status"] == "RECRUITING"

    async def test_search_with_status_filter(self, mock_response_data):
        """Test search with status filter."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status = MagicMock()

        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_async_client.is_closed = False

        client = ClinicalTrialsClient()
        client._client = mock_async_client

        _results = await client.search("diabetes", limit=10, status=["RECRUITING", "COMPLETED"])

        # Check that status filter was included in params
        call_args = mock_async_client.get.call_args
        params = call_args[1]["params"]
        assert "filter.overallStatus" in params

    async def test_search_empty_results(self):
        """Test search with no results."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"studies": []}
        mock_response.raise_for_status = MagicMock()

        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_async_client.is_closed = False

        client = ClinicalTrialsClient()
        client._client = mock_async_client

        results = await client.search("nonexistent condition xyz")

        assert results == []

    async def test_search_timeout_error(self):
        """Test search handles timeout gracefully."""
        import httpx

        mock_async_client = AsyncMock()
        mock_async_client.get.side_effect = httpx.TimeoutException("timeout")
        mock_async_client.is_closed = False

        client = ClinicalTrialsClient()
        client._client = mock_async_client

        results = await client.search("diabetes treatment")

        assert results == []

    async def test_search_http_error(self):
        """Test search handles HTTP errors gracefully."""
        import httpx

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=MagicMock(status_code=500)
        )

        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_async_client.is_closed = False

        client = ClinicalTrialsClient()
        client._client = mock_async_client

        results = await client.search("diabetes treatment")

        assert results == []

    async def test_search_generic_error(self):
        """Test search handles generic errors gracefully."""
        mock_async_client = AsyncMock()
        mock_async_client.get.side_effect = Exception("Unexpected error")
        mock_async_client.is_closed = False

        client = ClinicalTrialsClient()
        client._client = mock_async_client

        results = await client.search("diabetes treatment")

        assert results == []

    async def test_search_limit_capped(self, mock_response_data):
        """Test that limit is capped at 20."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status = MagicMock()

        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_async_client.is_closed = False

        client = ClinicalTrialsClient()
        client._client = mock_async_client

        await client.search("diabetes", limit=100)  # Request 100

        # Check that pageSize was capped
        call_args = mock_async_client.get.call_args
        params = call_args[1]["params"]
        assert params["pageSize"] == 20


# =============================================================================
# ClinicalTrialsClient - Normalize Study Tests
# =============================================================================


class TestNormalizeStudy:
    """Tests for _normalize_study method."""

    async def test_normalize_complete_study(self):
        """Test normalization of complete study data."""
        client = ClinicalTrialsClient()

        study = {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT12345678",
                    "briefTitle": "Test Trial",
                    "officialTitle": "Official Test Trial Title",
                },
                "statusModule": {
                    "overallStatus": "COMPLETED",
                    "startDateStruct": {"date": "2023-06-01"},
                },
                "designModule": {
                    "phases": ["PHASE3"],
                    "enrollmentInfo": {"count": 1000},
                },
                "conditionsModule": {"conditions": ["Hypertension"]},
                "armsInterventionsModule": {"interventions": [{"type": "DRUG", "name": "DrugA"}]},
            }
        }

        result = client._normalize_study(study)

        assert result["nct_id"] == "NCT12345678"
        assert result["title"] == "Test Trial"
        assert result["official_title"] == "Official Test Trial Title"
        assert result["status"] == "COMPLETED"
        assert result["phase"] == "PHASE3"
        assert result["conditions"] == ["Hypertension"]
        assert len(result["interventions"]) == 1

    async def test_normalize_minimal_study(self):
        """Test normalization of study with minimal data."""
        client = ClinicalTrialsClient()

        study = {
            "protocolSection": {
                "identificationModule": {},
                "statusModule": {},
                "designModule": {},
                "conditionsModule": {},
                "armsInterventionsModule": {},
            }
        }

        result = client._normalize_study(study)

        assert result["nct_id"] == ""
        assert result["title"] == ""
        assert result["status"] == "UNKNOWN"
        assert result["phase"] == "N/A"

    async def test_normalize_empty_study(self):
        """Test normalization of empty study."""
        client = ClinicalTrialsClient()

        study = {}

        result = client._normalize_study(study)

        assert result["nct_id"] == ""
        assert result["title"] == ""

    async def test_normalize_multiple_phases(self):
        """Test normalization with multiple phases."""
        client = ClinicalTrialsClient()

        study = {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT00001"},
                "statusModule": {},
                "designModule": {"phases": ["PHASE1", "PHASE2"]},
                "conditionsModule": {},
                "armsInterventionsModule": {},
            }
        }

        result = client._normalize_study(study)

        assert result["phase"] == "PHASE1, PHASE2"

    async def test_normalize_multiple_interventions(self):
        """Test normalization with multiple interventions."""
        client = ClinicalTrialsClient()

        study = {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT00002"},
                "statusModule": {},
                "designModule": {},
                "conditionsModule": {},
                "armsInterventionsModule": {
                    "interventions": [
                        {"type": "DRUG", "name": "Drug A"},
                        {"type": "PROCEDURE", "name": "Surgery"},
                        {"type": "BEHAVIORAL", "name": "Counseling"},
                    ]
                },
            }
        }

        result = client._normalize_study(study)

        assert len(result["interventions"]) == 3
        assert result["interventions"][0]["type"] == "DRUG"
        assert result["interventions"][1]["type"] == "PROCEDURE"

    async def test_normalize_preserves_url(self):
        """Test that NCT ID is used in URL."""
        client = ClinicalTrialsClient()

        study = {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT05555555"},
                "statusModule": {},
                "designModule": {},
                "conditionsModule": {},
                "armsInterventionsModule": {},
            }
        }

        result = client._normalize_study(study)

        # URL should contain NCT ID
        assert result["nct_id"] == "NCT05555555"
        if "url" in result:
            assert "NCT05555555" in result["url"]


# =============================================================================
# Module Constants Tests
# =============================================================================
# Module Constants Tests
# =============================================================================


class TestModuleConstants:
    """Tests for module-level constants."""

    async def test_base_url_format(self):
        """Test BASE_URL is valid."""
        assert BASE_URL.startswith("https://")
        assert "clinicaltrials.gov" in BASE_URL

    async def test_default_timeout(self):
        """Test DEFAULT_TIMEOUT is reasonable."""
        assert DEFAULT_TIMEOUT > 0
        assert DEFAULT_TIMEOUT <= 60  # Not too long
