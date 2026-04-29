"""Tests for export MCP tools — prepare_export, helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import pubmed_search.application.export.notes as notes_module
from pubmed_search.application.export import write_literature_notes
from pubmed_search.presentation.mcp_server.tools.export import (
    _format_export_response,
    _get_file_extension,
    _resolve_pmids,
    register_export_tools,
)

# ============================================================
# Pure helpers
# ============================================================


class TestGetFileExtension:
    async def test_ris(self):
        assert _get_file_extension("ris") == "ris"

    async def test_bibtex(self):
        assert _get_file_extension("bibtex") == "bib"

    async def test_csv(self):
        assert _get_file_extension("csv") == "csv"

    async def test_medline(self):
        assert _get_file_extension("medline") == "txt"

    async def test_json(self):
        assert _get_file_extension("json") == "json"

    async def test_csl(self):
        assert _get_file_extension("csl") == "json"

    async def test_unknown(self):
        assert _get_file_extension("xyz") == "txt"


class TestFormatExportResponse:
    async def test_small_export(self):
        result = _format_export_response("TY  - JOUR\n", "ris", 5, source="official")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["article_count"] == 5
        assert "export_text" in parsed

    async def test_large_export_saves_file(self):
        result = _format_export_response("content", "ris", 25, source="local")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert "file_path" in parsed


class TestResolvePmids:
    async def test_comma_separated(self):
        result = _resolve_pmids("111,222,333")
        assert result == ["111", "222", "333"]

    async def test_last_no_session(self):
        with patch(
            "pubmed_search.presentation.mcp_server.tools.export.get_session_manager",
            return_value=None,
        ):
            result = _resolve_pmids("last")
        assert result == []

    async def test_last_with_session(self):
        mock_sm = MagicMock()
        session = MagicMock()
        session.search_history = [{"pmids": ["111", "222"]}]
        mock_sm.get_or_create_session.return_value = session

        with patch(
            "pubmed_search.presentation.mcp_server.tools.export.get_session_manager",
            return_value=mock_sm,
        ):
            result = _resolve_pmids("last")
        assert result == ["111", "222"]


# ============================================================
# prepare_export tool
# ============================================================


def _capture_tools(mcp, searcher):
    tools = {}
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
    register_export_tools(mcp, searcher)
    return tools


class TestPrepareExport:
    @pytest.mark.asyncio
    async def test_no_pmids(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        tools = _capture_tools(mcp, searcher)

        result = await tools["prepare_export"](pmids="", format="ris")
        assert "error" in result.lower()


class TestSaveLiteratureNotes:
    @pytest.mark.asyncio
    async def test_save_literature_notes_default_wiki_profile(self, temp_dir, mock_article_data):
        mcp = MagicMock()
        searcher = AsyncMock()
        searcher.fetch_details.return_value = [mock_article_data]
        tools = _capture_tools(mcp, searcher)

        result = await tools["save_literature_notes"](
            pmids="12345678",
            output_dir=str(temp_dir),
            create_index=False,
        )

        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["note_format"] == "wiki"
        assert "[[12345678-" in parsed["files"][0]["wikilink"]
        note_text = Path(parsed["files"][0]["path"]).read_text(encoding="utf-8")
        assert 'note_format: "wiki"' in note_text

    @pytest.mark.asyncio
    async def test_save_literature_notes_foam(self, temp_dir, mock_article_data):
        mcp = MagicMock()
        searcher = AsyncMock()
        searcher.fetch_details.return_value = [mock_article_data]
        tools = _capture_tools(mcp, searcher)

        result = await tools["save_literature_notes"](
            pmids="12345678",
            output_dir=str(temp_dir),
            note_format="foam",
            collection_name="test search",
        )

        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["note_format"] == "foam"
        assert parsed["written_count"] == 1
        assert parsed["index_file"]["path"].endswith("test-search.md")
        note_path = parsed["files"][0]["path"]
        note_text = Path(note_path).read_text(encoding="utf-8")
        assert "## Triage" in note_text
        assert parsed["csl_file"]["path"].endswith("references.csl.json")
        assert "[[12345678-" in parsed["files"][0]["wikilink"]

    @pytest.mark.asyncio
    async def test_save_literature_notes_medpaper_profile(self, temp_dir, mock_article_data):
        mcp = MagicMock()
        searcher = AsyncMock()
        searcher.fetch_details.return_value = [mock_article_data]
        tools = _capture_tools(mcp, searcher)

        result = await tools["save_literature_notes"](
            pmids="12345678",
            output_dir=str(temp_dir),
            note_format="medpaper",
            collection_name="test search",
        )

        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["note_format"] == "medpaper"
        assert parsed["files"][0]["citation_key"] == "smith2024_12345678"
        note_path = Path(parsed["files"][0]["path"])
        assert note_path.parts[-2:] == ("12345678", "smith2024_12345678.md")
        assert parsed["files"][0]["wikilink"].startswith("[[smith2024_12345678|")

        note_text = note_path.read_text(encoding="utf-8")
        assert 'type: "reference"' in note_text
        assert "^key-findings" in note_text
        assert "```json" in note_text

        metadata_path = Path(parsed["files"][0]["metadata_path"])
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert metadata["citation_key"] == "smith2024_12345678"
        assert metadata["csl_json"]["type"] == "article-journal"
        assert metadata["csl_json"]["author"][0]["given"] == "John"

    def test_save_literature_notes_supports_real_pubmed_fore_name(self, temp_dir, mock_article_data):
        article = dict(mock_article_data)
        article["authors_full"] = [
            {"last_name": "Smith", "fore_name": "John", "initials": "J"},
            {"last_name": "Doe", "fore_name": "Jane", "initials": "J"},
        ]

        result = write_literature_notes(
            [article],
            temp_dir,
            note_format="foam",
            create_index=False,
        )

        csl_path = Path(result["csl_file"]["path"])
        csl_payload = json.loads(csl_path.read_text(encoding="utf-8"))
        assert csl_payload[0]["author"][0] == {"family": "Smith", "given": "John"}

    @pytest.mark.asyncio
    async def test_save_literature_notes_custom_template(self, temp_dir, mock_article_data):
        mcp = MagicMock()
        searcher = AsyncMock()
        searcher.fetch_details.return_value = [mock_article_data]
        tools = _capture_tools(mcp, searcher)
        template_path = temp_dir / "reference-template.md"
        template_path.write_text("# {title}\nPMID: {pmid}\nKey: {citation_key}\n{missing}\n", encoding="utf-8")

        result = await tools["save_literature_notes"](
            pmids="12345678",
            output_dir=str(temp_dir / "notes"),
            note_format="foam",
            template_file=str(template_path),
            create_index=False,
        )

        parsed = json.loads(result)
        note_text = Path(parsed["files"][0]["path"]).read_text(encoding="utf-8")
        assert note_text.startswith("# Test Article")
        assert "PMID: 12345678" in note_text
        assert "Key: smith2024_12345678" in note_text

    @pytest.mark.asyncio
    async def test_save_literature_notes_template_error_reports_template(self, temp_dir, mock_article_data):
        mcp = MagicMock()
        searcher = AsyncMock()
        searcher.fetch_details.return_value = [mock_article_data]
        tools = _capture_tools(mcp, searcher)
        template_path = temp_dir / "bad-template.md"
        template_path.write_text("# {title}\n{ literal json brace\n", encoding="utf-8")

        result = await tools["save_literature_notes"](
            pmids="12345678",
            output_dir=str(temp_dir / "notes"),
            template_file=str(template_path),
        )

        assert "template rendering failed" in result.lower()
        assert "template_file" in result

    def test_medpaper_profile_sanitizes_doi_directory_without_pmid(self, temp_dir, mock_article_data):
        article = dict(mock_article_data)
        article["pmid"] = ""

        result = write_literature_notes(
            [article],
            temp_dir,
            note_format="medpaper",
            create_index=False,
        )

        note_path = Path(result["files"][0]["path"])
        assert note_path.parent.name == "10-1000-test-2024-001"
        assert note_path.name == "smith2024_101000test2024001.md"

    def test_save_literature_notes_uses_available_collision_paths(self, temp_dir, mock_article_data, monkeypatch):
        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2024, 1, 1, 12, 0, 0, tzinfo=tz or timezone.utc)

        monkeypatch.setattr(notes_module, "datetime", FixedDateTime)
        (temp_dir / "references.csl.json").write_text("existing\n", encoding="utf-8")
        (temp_dir / "references-20240101-120000.csl.json").write_text("existing\n", encoding="utf-8")
        (temp_dir / "test-search.md").write_text("existing\n", encoding="utf-8")
        (temp_dir / "test-search-120000.md").write_text("existing\n", encoding="utf-8")

        result = write_literature_notes(
            [mock_article_data],
            temp_dir,
            note_format="foam",
            collection_name="test search",
        )

        assert result["csl_file"]["path"].endswith("references-20240101-120000-2.csl.json")
        assert result["index_file"]["path"].endswith("test-search-120000-2.md")

    @pytest.mark.asyncio
    async def test_save_literature_notes_skips_existing(self, temp_dir, mock_article_data):
        mcp = MagicMock()
        searcher = AsyncMock()
        searcher.fetch_details.return_value = [mock_article_data]
        tools = _capture_tools(mcp, searcher)

        first = await tools["save_literature_notes"](
            pmids="12345678",
            output_dir=str(temp_dir),
            create_index=False,
        )
        second = await tools["save_literature_notes"](
            pmids="12345678",
            output_dir=str(temp_dir),
            create_index=False,
        )

        assert json.loads(first)["written_count"] == 1
        parsed_second = json.loads(second)
        assert parsed_second["written_count"] == 0
        assert parsed_second["skipped_count"] == 1
        assert parsed_second["csl_file"] is None
        assert parsed_second["index_file"] is None
        assert len(list(temp_dir.glob("*.csl.json"))) == 1

    def test_save_literature_notes_repeat_export_keeps_named_collection_artifacts(self, temp_dir, mock_article_data):
        first = write_literature_notes(
            [mock_article_data],
            temp_dir,
            collection_name="named review",
        )
        second = write_literature_notes(
            [mock_article_data],
            temp_dir,
            collection_name="named review",
        )

        assert first["written_count"] == 1
        assert second["written_count"] == 0
        assert second["skipped_count"] == 1
        assert second["csl_file"]["path"].endswith(".csl.json")
        assert second["index_file"]["path"].endswith(".md")
        assert len(list(temp_dir.glob("*.csl.json"))) == 2

    def test_save_literature_notes_handles_author_string_payload(self, temp_dir, mock_article_data):
        article = dict(mock_article_data)
        article["authors"] = "Smith J; Doe J"
        article["authors_full"] = []

        result = write_literature_notes(
            [article],
            temp_dir,
            create_index=False,
        )

        note_text = Path(result["files"][0]["path"]).read_text(encoding="utf-8")
        assert "- Authors: Smith J; Doe J" in note_text

    @pytest.mark.asyncio
    async def test_save_literature_notes_invalid_format(self, temp_dir, mock_article_data):
        mcp = MagicMock()
        searcher = AsyncMock()
        searcher.fetch_details.return_value = [mock_article_data]
        tools = _capture_tools(mcp, searcher)

        result = await tools["save_literature_notes"](
            pmids="12345678",
            output_dir=str(temp_dir),
            note_format="unknown",
        )

        assert "unsupported note format" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_official_ris(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        tools = _capture_tools(mcp, searcher)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = "TY  - JOUR\nER  -\n"
        mock_result.pmid_count = 1

        with patch(
            "pubmed_search.presentation.mcp_server.tools.export.export_citations_official",
            return_value=mock_result,
        ):
            result = await tools["prepare_export"](pmids="12345678", format="ris", source="official")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["source"] == "official"

    @pytest.mark.asyncio
    async def test_local_bibtex(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        searcher.fetch_details.return_value = [{"pmid": "123", "title": "T", "authors": ["A"]}]
        tools = _capture_tools(mcp, searcher)

        with patch(
            "pubmed_search.presentation.mcp_server.tools.export.export_articles",
            return_value="@article{123,\n  title={T}\n}",
        ):
            result = await tools["prepare_export"](pmids="123", format="bibtex", source="local")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["format"] == "bibtex"

    @pytest.mark.asyncio
    async def test_unsupported_format(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        tools = _capture_tools(mcp, searcher)

        result = await tools["prepare_export"](pmids="123", format="xyz", source="official")
        assert "unsupported" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_official_api_failure_falls_back(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        searcher.fetch_details.return_value = [{"pmid": "123", "title": "T"}]
        tools = _capture_tools(mcp, searcher)

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "API down"

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.export.export_citations_official",
                return_value=mock_result,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.export.export_articles",
                return_value="TY  - JOUR\n",
            ),
        ):
            result = await tools["prepare_export"](pmids="123", format="ris", source="official")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["source"] == "local"

    @pytest.mark.asyncio
    async def test_exception_handling(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        tools = _capture_tools(mcp, searcher)

        with patch(
            "pubmed_search.presentation.mcp_server.tools.export.export_citations_official",
            side_effect=RuntimeError("network error"),
        ):
            result = await tools["prepare_export"](pmids="123", format="ris", source="official")
        assert "error" in result.lower()
