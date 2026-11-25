"""
Tests for Search Strategy Generator and related functions.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pubmed_search.domain.services.mesh_phrase_matching import MeshRecord
from pubmed_search.infrastructure.ncbi.base import NCBIInfrastructureError


def _ncbi_failure(operation: str = "strategy test") -> NCBIInfrastructureError:
    return NCBIInfrastructureError(operation, upstream_type="RuntimeError", retryable=False)


class TestSearchStrategyGenerator:
    """Tests for SearchStrategyGenerator class."""

    @pytest.fixture
    def strategy_generator(self):
        """Create a strategy generator for testing."""
        from pubmed_search.infrastructure.ncbi.strategy import SearchStrategyGenerator

        return SearchStrategyGenerator(email="test@example.com")

    async def test_init(self, strategy_generator):
        """Test strategy generator initialization."""
        assert strategy_generator is not None

    async def test_spell_check_no_correction(self, strategy_generator):
        """Test spell check when no correction needed."""
        with (
            patch("pubmed_search.infrastructure.ncbi.strategy.Entrez.espell") as mock_espell,
            patch("pubmed_search.infrastructure.ncbi.strategy.Entrez.read") as mock_read,
        ):
            mock_read.return_value = {"CorrectedQuery": "diabetes"}
            mock_espell.return_value = MagicMock()

            corrected, was_corrected = await strategy_generator.spell_check("diabetes")

            assert corrected == "diabetes"
            assert was_corrected is False

    async def test_spell_check_with_correction(self, strategy_generator):
        """Test spell check when correction is made."""
        with (
            patch("pubmed_search.infrastructure.ncbi.strategy.Entrez.espell") as mock_espell,
            patch("pubmed_search.infrastructure.ncbi.strategy.Entrez.read") as mock_read,
        ):
            mock_read.return_value = {"CorrectedQuery": "diabetes"}
            mock_espell.return_value = MagicMock()

            corrected, was_corrected = await strategy_generator.spell_check("diabetis")

            assert corrected == "diabetes"
            assert was_corrected is True

    async def test_spell_check_error(self, strategy_generator):
        """Provider failure is not represented as an unchanged spelling result."""
        with (
            patch("pubmed_search.infrastructure.ncbi.strategy.MAX_RETRIES", 1),
            patch("pubmed_search.infrastructure.ncbi.strategy.Entrez.espell") as mock_espell,
        ):
            mock_espell.side_effect = Exception("API Error")

            with pytest.raises(NCBIInfrastructureError) as exc_info:
                await strategy_generator.spell_check("test")
            assert "API Error" not in str(exc_info.value)

    async def test_spell_check_closes_handle_when_read_fails(self, strategy_generator):
        """Spell check should close the Entrez handle even when parsing fails."""
        mock_handle = MagicMock()

        with (
            patch("pubmed_search.infrastructure.ncbi.strategy.MAX_RETRIES", 1),
            patch("pubmed_search.infrastructure.ncbi.strategy.Entrez.espell", return_value=mock_handle),
            patch("pubmed_search.infrastructure.ncbi.strategy.Entrez.read", side_effect=ValueError("bad xml")),
        ):
            with pytest.raises(NCBIInfrastructureError) as exc_info:
                await strategy_generator.spell_check("test")

        mock_handle.close.assert_called_once()
        assert "bad xml" not in str(exc_info.value)

    async def test_get_mesh_info_found(self, strategy_generator):
        """An entry-term match returns the record with its match evidence."""
        summary = [
            {
                "Id": "68003920",
                "DS_MeshTerms": ["Diabetes Mellitus", "Diabetes", "Type 2 Diabetes"],
                "DS_IdxLinks": [{"TreeNum": "C18.452.394.750"}],
                "DS_HeadingMappedToList": [],
            }
        ]
        with (
            patch("pubmed_search.infrastructure.ncbi.strategy.Entrez.esearch") as mock_esearch,
            patch("pubmed_search.infrastructure.ncbi.strategy.Entrez.esummary") as mock_esummary,
            patch("pubmed_search.infrastructure.ncbi.strategy.Entrez.read") as mock_read,
        ):
            mock_read.side_effect = [{"Count": "1", "IdList": ["68003920"]}, summary]
            mock_esearch.return_value = MagicMock()
            mock_esummary.return_value = MagicMock()

            result = await strategy_generator.get_mesh_info("diabetes")

            assert result is not None
            assert result["mesh_id"] == "68003920"
            assert result["preferred_term"] == "Diabetes Mellitus"
            assert result["matched_on"] == "entry_term"
            assert result["matched_term"] == "Diabetes"
            assert result["tree_numbers"] == ["C18.452.394.750"]
            term = mock_esearch.call_args.kwargs["term"]
            assert '"diabetes"[MeSH Terms]' in term
            assert "[All Fields]" not in term
            assert mock_esummary.call_args.kwargs["id"] == "68003920"

    async def test_get_mesh_info_not_found(self, strategy_generator):
        """Test getting MeSH info when term is not found."""
        with (
            patch("pubmed_search.infrastructure.ncbi.strategy.Entrez.esearch") as mock_esearch,
            patch("pubmed_search.infrastructure.ncbi.strategy.Entrez.read") as mock_read,
        ):
            mock_read.return_value = {"Count": "0", "IdList": []}
            mock_esearch.return_value = MagicMock()

            result = await strategy_generator.get_mesh_info("nonexistentterm12345")

            assert result is None

    async def test_get_mesh_info_error(self, strategy_generator):
        """Provider failure is distinct from a successful no-match response."""
        with (
            patch("pubmed_search.infrastructure.ncbi.strategy.MAX_RETRIES", 1),
            patch("pubmed_search.infrastructure.ncbi.strategy.Entrez.esearch") as mock_esearch,
        ):
            mock_esearch.side_effect = Exception("API Error")

            with pytest.raises(NCBIInfrastructureError) as exc_info:
                await strategy_generator.get_mesh_info("test")
            assert "API Error" not in str(exc_info.value)

    async def test_analyze_query(self, strategy_generator):
        """Test query analysis."""
        with (
            patch("pubmed_search.infrastructure.ncbi.strategy.Entrez.esearch") as mock_esearch,
            patch("pubmed_search.infrastructure.ncbi.strategy.Entrez.read") as mock_read,
        ):
            mock_read.return_value = {
                "Count": "1234",
                "QueryTranslation": '"diabetes mellitus"[MeSH Terms]',
                "TranslationSet": [],
                "TranslationStack": [],
            }
            mock_esearch.return_value = MagicMock()

            result = await strategy_generator.analyze_query("diabetes")

            assert result["original"] == "diabetes"
            assert result["count"] == 1234
            assert "MeSH Terms" in result["translated_query"]

    async def test_analyze_query_error(self, strategy_generator):
        """Provider failure is distinct from a real zero-result query."""
        with (
            patch("pubmed_search.infrastructure.ncbi.strategy.MAX_RETRIES", 1),
            patch("pubmed_search.infrastructure.ncbi.strategy.Entrez.esearch") as mock_esearch,
        ):
            mock_esearch.side_effect = Exception("API Error")

            with pytest.raises(NCBIInfrastructureError) as exc_info:
                await strategy_generator.analyze_query("test")
            assert "API Error" not in str(exc_info.value)

    async def test_generate_strategies_basic(self, strategy_generator):
        """Test generating search strategies."""
        with (
            patch.object(strategy_generator, "spell_check", return_value=("diabetes", False)),
            patch.object(strategy_generator, "get_mesh_info", return_value=None),
            patch.object(strategy_generator, "analyze_query", return_value={"count": 100}),
        ):
            result = await strategy_generator.generate_strategies(
                topic="diabetes treatment",
                use_mesh=False,
                check_spelling=True,
                include_suggestions=True,
            )

            assert "topic" in result
            assert "corrected_topic" in result
            assert "suggested_queries" in result
            assert result["coverage"]["spelling"]["status"] == "completed"
            assert result["coverage"]["query_analysis"]["status"] == "completed"

    async def test_generate_strategies_with_mesh(self, strategy_generator):
        """Test generating strategies with MeSH lookup."""
        record = MeshRecord(
            uid="68003920",
            preferred="Diabetes Mellitus",
            entry_terms=("Diabetes", "Type 2 Diabetes"),
            tree_numbers=("C18.452",),
        )

        with (
            patch.object(strategy_generator, "spell_check", return_value=("diabetes", False)),
            patch.object(strategy_generator, "lookup_mesh_records", return_value={"diabete": (record,)}),
            patch.object(strategy_generator, "analyze_query", return_value={"count": 100}),
        ):
            result = await strategy_generator.generate_strategies(
                topic="diabetes", use_mesh=True, include_suggestions=True
            )

            assert [mesh["preferred"] for mesh in result["mesh_terms"]] == ["Diabetes Mellitus"]
            assert result["mesh_terms"][0]["matched_on"] == "entry_term"
            assert result["coverage"]["mesh"]["status"] == "completed"
            assert result["coverage"]["mesh"]["failed"] == 0
            assert '"Diabetes Mellitus"[MeSH Terms]' in [q["query"] for q in result["suggested_queries"]]

    async def test_generate_strategies_reports_optional_source_outages(self, strategy_generator):
        """Optional enrichments retain usable queries with explicit, sanitized coverage."""
        secret = "token=private-strategy-secret"
        with (
            patch.object(strategy_generator, "spell_check", side_effect=_ncbi_failure("spelling")),
            patch.object(strategy_generator, "lookup_mesh_records", side_effect=_ncbi_failure("mesh")),
            patch.object(strategy_generator, "analyze_query", side_effect=_ncbi_failure("query")),
        ):
            result = await strategy_generator.generate_strategies(topic="diabetes treatment")

        assert result["suggested_queries"]
        assert result["coverage"]["spelling"]["status"] == "failed"
        assert result["coverage"]["mesh"] == {
            "status": "failed",
            "attempted": 1,
            "completed": 0,
            "failed": 1,
            "matched": 0,
            "unconfirmed": 0,
            "phrases_checked": 0,
        }
        assert result["coverage"]["pubmed_atm"]["status"] == "failed"
        assert result["mesh_terms"] == []
        assert result["unmapped_phrases"] == ["diabetes treatment"]
        analysis = result["coverage"]["query_analysis"]
        assert analysis["status"] == "failed"
        assert analysis["attempted"] == analysis["failed"] > 0
        assert analysis["completed"] == 0
        assert all(query["estimated_count"] is None for query in result["suggested_queries"])
        assert len(result["warnings"]) == 3
        assert secret not in str(result)

    async def test_generate_strategies_reports_partial_query_analysis(self, strategy_generator):
        """Successful and failed query translations are counted independently."""
        with (
            patch.object(strategy_generator, "spell_check", return_value=("diabetes", False)),
            patch.object(strategy_generator, "get_mesh_info", return_value=None),
            patch.object(
                strategy_generator,
                "analyze_query",
                side_effect=[
                    {"count": 12, "translated_query": "translated"},
                    _ncbi_failure(),
                    {"count": 3, "translated_query": "translated rct"},
                ],
            ),
        ):
            result = await strategy_generator.generate_strategies(
                topic="diabetes",
                use_mesh=False,
                strategy="focused",
            )

        analysis = result["coverage"]["query_analysis"]
        assert analysis == {"status": "partial", "attempted": 3, "completed": 2, "failed": 1}
        assert result["suggested_queries"][0]["estimated_count"] == 12
        assert result["suggested_queries"][1]["estimated_count"] is None
