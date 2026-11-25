"""PubMed ESearch diagnostics reach callers instead of only the log.

Record shapes mirror Biopython ``Entrez.read`` output observed live on
2026-11-25: a quoted MeSH heading that does not exist is reported under
``WarningList.QuotedPhraseNotFound`` with its field tag, while an unquoted
unknown term is reported under ``ErrorList.PhraseNotFound`` without it.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from pubmed_search.domain.value_objects.query_diagnostics import PubMedQueryDiagnostics
from pubmed_search.infrastructure.ncbi.diagnostics import MAX_DIAGNOSTIC_ITEMS, parse_esearch_diagnostics
from pubmed_search.infrastructure.ncbi.search import ESearchIdList, SearchMixin
from pubmed_search.presentation.mcp_server.tools.unified_runner import run_unified_search

if TYPE_CHECKING:
    import pytest

SEARCH = "pubmed_search.infrastructure.ncbi.search"
BAD_MESH_QUERY = '"Post-Anesthesia Care Units"[Mesh] AND delirium[tiab]'

QUOTED_NOT_FOUND_RECORD: dict[str, Any] = {
    "Count": "0",
    "RetMax": "0",
    "RetStart": "0",
    "IdList": [],
    "TranslationSet": [],
    "QueryTranslation": BAD_MESH_QUERY,
    "WarningList": {
        "OutputMessage": ["No items found."],
        "QuotedPhraseNotFound": ['"Post-Anesthesia Care Units"[Mesh]'],
        "PhraseIgnored": [],
    },
}
UNQUOTED_NOT_FOUND_RECORD: dict[str, Any] = {
    "Count": "0",
    "IdList": [],
    "TranslationSet": [],
    "QueryTranslation": "PACU[mh]",
    "ErrorList": {"PhraseNotFound": ["PACU"], "FieldNotFound": []},
    "WarningList": {"OutputMessage": ["No items found."], "QuotedPhraseNotFound": [], "PhraseIgnored": []},
}


class _Handle:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def close(self) -> None:
        return None


class _Searcher(SearchMixin):
    async def fetch_details(self, id_list: list[str]) -> list[dict[str, Any]]:
        return [{"pmid": pmid, "title": f"Article {pmid}"} for pmid in id_list]


def _install(record: dict[str, Any]) -> Any:
    return (
        patch(f"{SEARCH}.Entrez.esearch", return_value=_Handle(record)),
        patch(f"{SEARCH}.Entrez.read", side_effect=lambda handle: handle.payload),
    )


def test_quoted_mesh_heading_not_found_is_parsed_with_its_field_tag() -> None:
    diagnostics = parse_esearch_diagnostics(QUOTED_NOT_FOUND_RECORD)

    assert diagnostics.quoted_phrases_not_found == ('"Post-Anesthesia Care Units"[Mesh]',)
    assert diagnostics.output_messages == ("No items found.",)
    assert diagnostics.query_translation == BAD_MESH_QUERY
    assert diagnostics.has_issues
    assert diagnostics.issue_messages() == [
        'PubMed did not find quoted phrase "Post-Anesthesia Care Units"[Mesh]; that clause matched nothing.'
    ]


def test_unquoted_unknown_term_is_an_error_list_entry() -> None:
    diagnostics = parse_esearch_diagnostics(UNQUOTED_NOT_FOUND_RECORD)

    assert diagnostics.phrases_not_found == ("PACU",)
    assert diagnostics.to_dict()["error_list"] == {"phrases_not_found": ["PACU"], "fields_not_found": []}


def test_no_items_message_alone_is_not_an_issue_and_translation_set_is_kept() -> None:
    record = {
        "Count": "0",
        "QueryTranslation": '"delirium"[MeSH Terms] OR "delirium"[All Fields]',
        "TranslationSet": [{"From": "delirium", "To": '"delirium"[MeSH Terms] OR "delirium"[All Fields]'}],
        "WarningList": {"OutputMessage": ["No items found."], "QuotedPhraseNotFound": [], "PhraseIgnored": []},
    }

    diagnostics = parse_esearch_diagnostics(record)

    assert not diagnostics.has_issues and diagnostics.issue_messages() == []
    assert diagnostics.to_dict()["translation_set"] == [
        {"from": "delirium", "to": '"delirium"[MeSH Terms] OR "delirium"[All Fields]'}
    ]


def test_diagnostics_round_trip_and_tolerate_malformed_payloads() -> None:
    diagnostics = parse_esearch_diagnostics(QUOTED_NOT_FOUND_RECORD)
    assert PubMedQueryDiagnostics.from_dict(json.loads(json.dumps(diagnostics.to_dict()))) == diagnostics

    malformed = parse_esearch_diagnostics(
        {"WarningList": "unexpected", "ErrorList": {"PhraseNotFound": "single"}, "TranslationSet": [{"From": "x"}]}
    )
    assert malformed.phrases_not_found == ("single",)
    assert malformed.translation_set == ()
    assert parse_esearch_diagnostics(None) == PubMedQueryDiagnostics()
    assert PubMedQueryDiagnostics.from_dict({"warning_list": [], "translation_set": "x"}) == PubMedQueryDiagnostics()

    flood = parse_esearch_diagnostics({"ErrorList": {"PhraseNotFound": [f"t{i}" for i in range(500)]}})
    assert len(flood.phrases_not_found) == MAX_DIAGNOSTIC_ITEMS


async def test_search_page_returns_diagnostics_and_warnings_while_ids_still_unpack() -> None:
    searcher = _Searcher()
    esearch, read = _install(QUOTED_NOT_FOUND_RECORD)
    with esearch, read:
        ids = await searcher._search_ids(BAD_MESH_QUERY, 5, "relevance")
        page = await searcher.search_page(BAD_MESH_QUERY, limit=5)

    assert isinstance(ids, ESearchIdList)
    assert ids == ([], 0, "", "")  # four-way unpacking contract is unchanged
    assert page.items == [] and page.total == 0
    diagnostics = page.metadata["query_diagnostics"]
    assert diagnostics["warning_list"]["quoted_phrases_not_found"] == ['"Post-Anesthesia Care Units"[Mesh]']
    assert diagnostics["has_issues"] is True
    assert page.warnings == [
        'PubMed did not find quoted phrase "Post-Anesthesia Care Units"[Mesh]; that clause matched nothing.'
    ]


async def test_clean_search_has_diagnostics_without_warnings() -> None:
    record = {
        "Count": "2",
        "IdList": ["111", "222"],
        "QueryTranslation": '"delirium"[MeSH Terms]',
        "TranslationSet": [],
    }
    esearch, read = _install(record)
    with esearch, read:
        page = await _Searcher().search_page('"Delirium"[Mesh]', limit=2)

    assert [item["pmid"] for item in page.items] == ["111", "222"]
    assert page.warnings == []
    assert page.metadata["query_diagnostics"]["has_issues"] is False
    assert page.metadata["query_diagnostics"]["query_translation"] == '"delirium"[MeSH Terms]'


async def test_diagnostics_are_logged_as_counts_without_query_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    esearch, read = _install(QUOTED_NOT_FOUND_RECORD)
    with esearch, read:
        await _Searcher().search_page(BAD_MESH_QUERY, limit=5)

    assert "quoted_not_found=1" in caplog.text
    assert "Post-Anesthesia" not in caplog.text


async def test_unified_search_source_metadata_carries_pubmed_warnings() -> None:
    esearch, read = _install(QUOTED_NOT_FOUND_RECORD)
    with esearch, read:
        result = await run_unified_search(
            searcher=_Searcher(),  # type: ignore[arg-type]
            query=BAD_MESH_QUERY,
            sources="pubmed",
            output_format="json",
            options="shallow,no_relax,no_analysis,no_scores",
        )

    metadata = json.loads(result)["source_metadata"]["pubmed"]
    assert any("Post-Anesthesia Care Units" in warning for warning in metadata["warnings"])
