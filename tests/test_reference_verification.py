"""Tests for MCP-native reference verification.

This covers the first-stage workflow:
plain-text reference list -> parser -> PubMed evidence -> MCP JSON report.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from pubmed_search.application.reference_verification import ReferenceVerificationService
from pubmed_search.presentation.mcp_server.tools.reference_verification import register_reference_verification_tools


def _capture_tools(register_fn, *args):
    tools: dict[str, object] = {}
    mcp = MagicMock()

    def _tool(*decorator_args, **decorator_kwargs):
        del decorator_args, decorator_kwargs

        def _decorator(func):
            tools[func.__name__] = func
            return func

        return _decorator

    mcp.tool = _tool
    register_fn(mcp, *args)
    return tools


class TestReferenceVerificationService:
    def setup_method(self):
        self.searcher = MagicMock()
        self.searcher.find_by_citation = AsyncMock(return_value=None)
        self.searcher.verify_references = AsyncMock(return_value=[])
        self.searcher.fetch_details = AsyncMock(return_value=[])
        self.searcher.search = AsyncMock(return_value=[])
        self.service = ReferenceVerificationService(self.searcher)

    def test_extract_references_from_numbered_block(self):
        reference_text = """
        1. Smith J. Example title. N Engl J Med. 2024;390(1):12-18.
        continuation line.

        2. Doe A. Another title. JAMA. 2023;330(4):44-50.
        """

        entries = self.service.extract_references(reference_text)

        assert len(entries) == 2
        assert entries[0].startswith("Smith J.")
        assert "continuation line" in entries[0]
        assert entries[1].startswith("Doe A.")

    def test_parse_reference_extracts_core_fields(self):
        parsed = self.service.parse_reference(
            "1. Smith J, Doe A. Example title. N Engl J Med. 2024;390(1):12-18. doi:10.1056/NEJMoa2400001 PMID:12345678",
            index=1,
        )

        assert parsed.first_author == "Smith"
        assert parsed.journal == "N Engl J Med"
        assert parsed.year == "2024"
        assert parsed.volume == "390"
        assert parsed.first_page == "12"
        assert parsed.doi == "10.1056/nejmoa2400001"
        assert parsed.pmid == "12345678"

    @pytest.mark.asyncio
    async def test_verify_reference_prefers_explicit_pmid(self):
        self.searcher.fetch_details = AsyncMock(
            return_value=[
                {
                    "pmid": "12345678",
                    "doi": "10.1056/NEJMoa2400001",
                    "title": "Example title",
                    "journal": "New England Journal of Medicine",
                    "journal_abbrev": "N Engl J Med",
                    "year": "2024",
                    "volume": "390",
                    "pages": "12-18",
                    "authors": ["Smith John", "Doe Alice"],
                    "authors_full": [{"last_name": "Smith", "fore_name": "John"}],
                }
            ]
        )

        result = await self.service.verify_reference(
            "Smith J, Doe A. Example title. N Engl J Med. 2024;390(1):12-18. doi:10.1056/NEJMoa2400001 PMID:12345678",
            index=1,
        )

        assert result["status"] == "verified"
        assert result["resolution_method"] == "pmid"
        assert result["matched_article"]["pmid"] == "12345678"
        assert "doi" in result["matched_fields"]

    @pytest.mark.asyncio
    async def test_verify_reference_uses_ecitmatch_when_no_pmid(self):
        self.searcher.find_by_citation = AsyncMock(return_value="23456789")
        self.searcher.fetch_details = AsyncMock(
            return_value=[
                {
                    "pmid": "23456789",
                    "doi": "",
                    "title": "Another title",
                    "journal": "Journal of the American Medical Association",
                    "journal_abbrev": "JAMA",
                    "year": "2023",
                    "volume": "330",
                    "pages": "44-50",
                    "authors": ["Doe Alice"],
                    "authors_full": [{"last_name": "Doe", "fore_name": "Alice"}],
                }
            ]
        )

        result = await self.service.verify_reference(
            "Doe A. Another title. JAMA. 2023;330(4):44-50.",
            index=1,
        )

        assert result["status"] == "verified"
        assert result["resolution_method"] == "ecitmatch"
        assert result["comparison"]["journal"] is True
        assert result["comparison"]["first_page"] is True

    @pytest.mark.asyncio
    async def test_verify_reference_list_uses_batch_ecitmatch_workflow(self):
        self.searcher.verify_references = AsyncMock(
            return_value=[
                {
                    "journal": "JAMA",
                    "year": "2023",
                    "volume": "330",
                    "first_page": "44",
                    "author": "Doe",
                    "title": "Another title",
                    "pmid": "23456789",
                    "verified": True,
                }
            ]
        )
        self.searcher.find_by_citation = AsyncMock(side_effect=AssertionError("batch ECitMatch should be reused"))
        self.searcher.fetch_details = AsyncMock(
            return_value=[
                {
                    "pmid": "23456789",
                    "doi": "",
                    "title": "Another title",
                    "journal": "Journal of the American Medical Association",
                    "journal_abbrev": "JAMA",
                    "year": "2023",
                    "volume": "330",
                    "pages": "44-50",
                    "authors": ["Doe Alice"],
                    "authors_full": [{"last_name": "Doe", "fore_name": "Alice"}],
                }
            ]
        )

        result = await self.service.verify_reference_list("Doe A. Another title. JAMA. 2023;330(4):44-50.")

        assert result["success"] is True
        assert result["summary"]["verified"] == 1
        assert result["results"][0]["resolution_method"] == "ecitmatch"
        self.searcher.verify_references.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_verify_reference_is_unresolved_when_no_candidate_found(self):
        self.searcher.search = AsyncMock(return_value=[])

        result = await self.service.verify_reference(
            "Unstructured reference with no matchable metadata",
            index=1,
        )

        assert result["status"] == "unresolved"
        assert result["matched_article"] is None
        assert result["review_required"] is True
        assert result["review_strategy"]["review_checklist"]

    @pytest.mark.asyncio
    async def test_verify_reference_list_includes_review_workflow_queue(self):
        report = await self.service.verify_reference_list(
            "Smith J. Unknown findings in rare disease cohort. 2024.",
        )

        assert report["success"] is True
        assert "review_workflow" in report
        workflow = report["review_workflow"]
        assert workflow["requires_manual_review"] is True
        assert workflow["review_count"] == 1
        assert workflow["review_queue"][0]["status"] == "unresolved"
        assert workflow["review_queue"][0]["retry_queries"]
        assert workflow["review_queue"][0]["review_checklist"]

    @pytest.mark.asyncio
    async def test_partial_match_row_exposes_review_strategy(self):
        self.searcher.find_by_citation = AsyncMock(return_value=None)
        self.searcher.search = AsyncMock(
            return_value=[
                {
                    "pmid": "45678901",
                    "doi": "10.1000/example-doi",
                    "title": "Close but not exact title",
                    "journal": "N Engl J Med",
                    "journal_abbrev": "N Engl J Med",
                    "year": "2022",
                    "volume": "390",
                    "pages": "100-110",
                    "authors": ["Smith John"],
                    "authors_full": [{"last_name": "Smith", "fore_name": "John"}],
                }
            ]
        )

        result = await self.service.verify_reference(
            "Smith J. Original trial title. N Engl J Med. 2024;390(1):12-18.",
            index=1,
        )

        assert result["status"] == "partial_match"
        assert result["review_required"] is True
        assert result["review_strategy"]["retry_queries"]
        assert result["review_strategy"]["review_checklist"]
        assert any(item["label"] == "journal_year_author" for item in result["review_strategy"]["retry_queries"])

    @pytest.mark.asyncio
    async def test_resolve_by_title_escapes_embedded_quotes(self):
        parsed = self.service.parse_reference(
            'Smith J. Alpha "beta" gamma trial results. N Engl J Med. 2024;390(1):12-18.',
            index=1,
        )
        self.searcher.search = AsyncMock(return_value=[])

        await self.service._resolve_by_title(parsed)

        called_query = self.searcher.search.await_args.args[0]
        assert called_query == '"Alpha beta gamma trial results"[Title]'


class TestReferenceVerificationTool:
    def test_registers_verify_reference_list(self):
        searcher = MagicMock()
        tools = _capture_tools(register_reference_verification_tools, searcher)

        assert "verify_reference_list" in tools

    @pytest.mark.asyncio
    async def test_verify_reference_list_tool_returns_json_report(self):
        searcher = MagicMock()
        searcher.fetch_details = AsyncMock(
            return_value=[
                {
                    "pmid": "12345678",
                    "doi": "10.1056/NEJMoa2400001",
                    "title": "Example title",
                    "journal": "New England Journal of Medicine",
                    "journal_abbrev": "N Engl J Med",
                    "year": "2024",
                    "volume": "390",
                    "pages": "12-18",
                    "authors": ["Smith John"],
                    "authors_full": [{"last_name": "Smith", "fore_name": "John"}],
                }
            ]
        )
        tools = _capture_tools(register_reference_verification_tools, searcher)

        result = json.loads(
            await tools["verify_reference_list"](
                reference_text="Smith J. Example title. N Engl J Med. 2024;390(1):12-18. PMID:12345678",
                source_name="references.txt",
            )
        )

        assert result["success"] is True
        assert result["source_name"] == "references.txt"
        assert result["summary"]["verified"] == 1
        assert result["results"][0]["status"] == "verified"
        assert "review_workflow" in result
