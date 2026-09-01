"""Contracts for the runtime Mermaid fixtures consumed by CI."""

from __future__ import annotations

from scripts.export_mermaid_smoke_fixtures import build_smoke_fixtures

from pubmed_search.application.chronicle import validate_mermaid_source


def test_smoke_fixtures_cover_every_research_chronicle_mermaid_tier() -> None:
    fixtures = build_smoke_fixtures()

    assert set(fixtures) == {
        "citation-rich.mmd",
        "chronicle-byte-budget.mmd",
        "chronicle-rich.mmd",
        "chronicle-repaired.mmd",
        "chronicle-safe.mmd",
        "chronicle-minimal.mmd",
    }
    for filename in (
        "citation-rich.mmd",
        "chronicle-byte-budget.mmd",
        "chronicle-rich.mmd",
        "chronicle-repaired.mmd",
        "chronicle-safe.mmd",
        "chronicle-minimal.mmd",
    ):
        valid, issues = validate_mermaid_source(fixtures[filename])
        assert valid, (filename, issues)

    assert "classDef" in fixtures["chronicle-rich.mmd"]
    assert fixtures["citation-rich.mmd"].startswith("flowchart TD\n")
    assert "classDef shared" in fixtures["citation-rich.mmd"]
    assert "classDef" in fixtures["chronicle-byte-budget.mmd"]
    assert len(fixtures["chronicle-byte-budget.mmd"].encode("utf-8")) < 49_000
    assert "classDef" not in fixtures["chronicle-safe.mmd"]
    assert fixtures["chronicle-minimal.mmd"].count("[") == 2
