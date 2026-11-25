"""The unified_search MeSH corrector: fill-tier rewrites and size-capped disclosure.

MeSH evidence comes from the production ``NCBIMeshEvidenceGateway`` over the
deterministic Entrez boundary in ``tests.fixtures.mesh_entrez``; the
corrector and the disclosure helpers run for real.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pubmed_search.application.unified.mesh_correction import (
    PubMedMeshCorrector,
    compact_mesh_correction,
    describe_correction,
)
from pubmed_search.domain.value_objects.query_diagnostics import PubMedQueryDiagnostics
from tests.fixtures.mesh_entrez import PACU, PACU_QUERY, FakeEntrez, make_service

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def fake_entrez() -> Iterator[FakeEntrez]:
    entrez = FakeEntrez()
    with entrez.installed():
        yield entrez


def _flagged(query: str) -> dict[str, object]:
    diagnostics = PubMedQueryDiagnostics(query_translation=query, quoted_phrases_not_found=(PACU,))
    return {"provider_metadata": {"query_diagnostics": diagnostics.to_dict()}}


def test_completed_evidence_without_a_heading_keeps_the_no_heading_label() -> None:
    base = {"original": PACU, "tier": "text_words", "confidence": "low"}
    assert describe_correction({**base, "evidence_complete": True}).endswith("(low confidence, no MeSH heading found)")
    assert describe_correction(base).endswith("no MeSH heading found)")  # disclosures written before the flag
    assert describe_correction({**base, "evidence_complete": False}).endswith("MeSH evidence incomplete)")


async def test_compact_disclosure_keeps_warnings_rerun_status_and_suggestions(fake_entrez: FakeEntrez) -> None:
    # Before: the compact form (size-capped responses, artifact summary, audit details) had no
    # warnings or rerun_status, so a failed re-run looked like a clean correction.
    corrector = PubMedMeshCorrector(make_service())
    assert await corrector.propose(PACU_QUERY, _flagged(PACU_QUERY), 0)
    corrector.record_rerun(status="error", total=None, metadata=None)

    compact = compact_mesh_correction(corrector.disclosure())

    assert compact is not None
    assert compact["rerun_status"] == "error" and compact["applied"] is False
    assert any("corrected query failed at PubMed" in warning for warning in compact["warnings"])
    assert compact["suggestions"] == []

    excluded = PubMedMeshCorrector(make_service())
    query = f"delirium[tiab] NOT {PACU}"
    assert await excluded.propose(query, _flagged(query), 9) is None
    compact = compact_mesh_correction(excluded.disclosure())
    assert compact is not None and compact["rerun_status"] is None
    assert [item["original"] for item in compact["suggestions"]] == [PACU]
    assert any("NOT operand" in warning for warning in compact["warnings"])
