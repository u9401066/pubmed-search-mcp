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


def _flagged(query: str, clause: str = PACU) -> dict[str, object]:
    diagnostics = PubMedQueryDiagnostics(query_translation=query, quoted_phrases_not_found=(clause,))
    return {"provider_metadata": {"query_diagnostics": diagnostics.to_dict()}}


EMERGENCE_PK = '"Emergence Deliriums/pharmacokinetics"[Mesh]'
"""Exact heading fix that must drop an invalid qualifier: not equivalent inside a NOT."""
EMERGENCE = '"Emergence Deliriums"[Mesh]'
"""Exact heading fix that keeps every restriction: equivalent, safe inside a NOT."""


@pytest.mark.parametrize(
    "clause",
    [
        pytest.param(PACU, id="related-heading-correction"),
        pytest.param(EMERGENCE_PK, id="exact-fix-dropping-a-qualifier"),
    ],
)
async def test_fill_and_relaxation_rewrites_never_widen_an_exclusion_of_the_same_clause(
    fake_entrez: FakeEntrez, clause: str
) -> None:
    # Before: rewrite() matched clauses by text alone, so the fill-tier and auto-relax
    # queries also rewrote the excluded copy, widening what the NOT removes.
    query = f"{clause} AND delirium[tiab] NOT ({clause} AND child[tiab])"
    corrector = PubMedMeshCorrector(make_service())
    corrected = await corrector.propose(query, _flagged(query, clause), 0)
    assert corrected is not None and not corrected.startswith(clause)
    assert corrected.endswith(f"NOT ({clause} AND child[tiab])")  # the exact tier only suggests here
    corrector.record_rerun(status="ok", total=12, metadata=None)

    # The relaxation path rewrites the caller's own query: it must equal the corrected exact tier.
    assert corrector.rewrite(query) == corrected
    fill = f"{clause} AND delirium[Title/Abstract] NOT ({clause} AND child[tiab])"
    rewritten = corrector.rewrite(fill)
    assert rewritten.endswith(f"NOT ({clause} AND child[tiab])")
    assert not rewritten.startswith(clause)  # the included copy is still corrected


async def test_equivalent_rewrites_still_apply_inside_an_exclusion(fake_entrez: FakeEntrez) -> None:
    query = f"{EMERGENCE} AND recovery[tiab]"
    corrector = PubMedMeshCorrector(make_service())
    assert (
        await corrector.propose(query, _flagged(query, EMERGENCE), 0) == '"Emergence Delirium"[Mesh] AND recovery[tiab]'
    )
    corrector.record_rerun(status="ok", total=12, metadata=None)

    fill = f"{EMERGENCE} AND recovery[Title/Abstract] NOT ({EMERGENCE} AND child[tiab])"

    assert corrector.rewrite(fill) == (
        '"Emergence Delirium"[Mesh] AND recovery[Title/Abstract] NOT ("Emergence Delirium"[Mesh] AND child[tiab])'
    )


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
