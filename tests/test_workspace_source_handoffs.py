"""Research handoffs identify the source the researcher recorded."""

from __future__ import annotations

from typing import Any

import pytest

from pubmed_search.application.workspace_handoff import source_handoffs


@pytest.mark.parametrize(
    ("source", "tool", "arguments"),
    [
        ("pmid:3878092", "fetch_article_details", {"pmids": "3878092", "output_format": "json"}),
        (
            "doi:10.1234/TRIAL",
            "get_fulltext",
            {"source": {"kind": "doi", "value": "10.1234/trial"}, "output_format": "json"},
        ),
        (
            "pmcid:PMC100",
            "get_fulltext",
            {"source": {"kind": "pmcid", "value": "PMC100"}, "output_format": "json"},
        ),
        (
            "artifact://s1/a1",
            "read_session",
            {"request": {"action": "artifact", "locator": {"kind": "artifact_uri", "value": "artifact://s1/a1"}}},
        ),
        (
            "run:s1/r1",
            "read_session",
            {"request": {"action": "search_run", "session_id": "s1", "run_id": "r1"}},
        ),
        ("pipeline:implant_history", "load_pipeline", {"source": "saved:implant_history"}),
        (
            "chronicle:implant-history@2",
            "read_research_chronicle",
            {"request": {"action": "load", "chronicle_id": "implant-history", "revision": 2}},
        ),
    ],
)
def test_handoffs_address_recorded_sources(source: str, tool: str, arguments: dict[str, Any]) -> None:
    assert source_handoffs([source]) == [{"source_ref": source, "tool": tool, "arguments": arguments}]


def test_private_and_ambiguous_references_do_not_produce_calls() -> None:
    refs = [
        "zotero:private-key",
        "artifact:../secret",
        "pipeline:file:test",
        "run:unscoped",
        "pmid:no",
        "chronicle:unversioned",
        "chronicle:test@9999999999",
    ]
    assert source_handoffs(refs) == []
