"""Regression tests for the v0.12.0 pre-release review of supplied fulltext.

Each case comes from a reproduction of the review (scratchpad repro r1, r3,
r4, r6, r7, r9-r12): parser blow-ups and event-loop stalls (H1), body-less
registrations shadowing providers (M1), per-article "newest wins" (M2),
supplied documents that declare another article (M3), UNC/device paths
reaching the OS (M5), and the store/notes/provenance lows.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.fulltext import FulltextRequest, FulltextService
from pubmed_search.application.fulltext import supplied as supplied_module
from pubmed_search.application.fulltext.intake import (
    FulltextIntakeRequest,
    FulltextIntakeService,
    IntakePathPolicy,
    split_text_sections,
)
from pubmed_search.application.fulltext.supplied import SuppliedFulltextError, SuppliedFulltextStore
from pubmed_search.infrastructure.sources.fulltext_intake import IntakeContentParsers
from pubmed_search.infrastructure.sources.jats import parse_jats_article
from tests.fixtures.pmc_html import FIXTURE_DOI, FIXTURE_PMCID, FIXTURE_PMID, PMC_ARTICLE_PAGE
from tests.fixtures.pmc_jats import PMC_EFETCH_FULL_BODY

PROVENANCE = {
    "retrieval_method": "host_fetch",
    "source_url": "https://example.org/articles/1",
    "retrieved_at": "2026-11-25T08:00:00Z",
}
BODY_XML = (
    '<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta><title-group>'
    "<article-title>Provider copy</article-title></title-group></article-meta></front>"
    "<body><sec><title>Results</title><p>Provider body 11 of 100.</p></sec></body></article>"
)


def _intake(tmp_path: Path, **policy: Any) -> tuple[FulltextIntakeService, SuppliedFulltextStore]:
    store = SuppliedFulltextStore(tmp_path / "data" / "fulltext" / "supplied")
    service = FulltextIntakeService(store=store, parser=IntakeContentParsers(), path_policy=IntakePathPolicy(**policy))
    return service, store


def _request(kind: str = "pmid", value: str = "100", **fields: Any) -> FulltextIntakeRequest:
    fields.setdefault("content", "## Results\nSupplied body text.")
    return FulltextIntakeRequest(kind, value, dict(PROVENANCE), **fields)


# ----------------------------------------------------------------------------
# H1: linear-time parsing, hard caps, and no event-loop stalls
# ----------------------------------------------------------------------------


def test_markdown_heading_parsing_is_linear_time() -> None:
    started = time.perf_counter()
    parsed = split_text_sections("# a" + " " * 50_000 + "b\n## Results\n" + "x " * 10 + "\n")
    assert time.perf_counter() - started < 0.5
    # A 50,000-character line is never a heading; it stays body text.
    assert [section["title"] for section in parsed["sections"]] == ["Body", "Results"]


def test_html_stray_end_tags_and_deep_nesting_parse_or_fail_fast() -> None:
    parsers = IntakeContentParsers()
    started = time.perf_counter()
    with pytest.raises(SuppliedFulltextError) as deep:
        parsers.parse_html("<html><body><article>" + "<div>" * 50_000 + "</b>" * 50_000 + "</article></body></html>")
    stray = parsers.parse_html("<article><h2>Results</h2><p>kept</p>" + "</b>" * 200_000 + "</article>")
    assert time.perf_counter() - started < 1.0
    assert deep.value.code == "invalid_input"
    assert stray["sections"] == [{"title": "Results", "content": "kept"}]


def test_heading_flood_and_oversized_text_fail_with_a_typed_input_error() -> None:
    with pytest.raises(SuppliedFulltextError) as flood:
        split_text_sections("".join(f"## H{index}\nbody\n" for index in range(6_000)))
    assert flood.value.code == "invalid_input"


async def test_a_large_registration_keeps_the_event_loop_responsive(tmp_path: Path) -> None:
    service, _ = _intake(tmp_path)
    content = "".join(f"## Section {index}\n" + ("word " * 400) + "\n" for index in range(380))
    content = "# a" + " " * 2_000 + "b\n" + content
    gaps: list[float] = []

    async def heartbeat() -> None:
        last = time.perf_counter()
        while True:
            await asyncio.sleep(0.01)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    beat = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.05)
    try:
        outcome = await service.register(_request(content=content))
    finally:
        beat.cancel()
    assert [section["title"] for section in outcome.record.sections][1:3] == ["Section 0", "Section 1"]
    assert len(outcome.record.sections) == 381
    assert max(gaps) < 0.5, max(gaps)


# ----------------------------------------------------------------------------
# M1: a registration without a body never shadows providers
# ----------------------------------------------------------------------------


def _provider_service(store: SuppliedFulltextStore, xml_fetcher: AsyncMock) -> FulltextService:
    europe = MagicMock()
    europe.parse_fulltext_xml = lambda xml: parse_jats_article(xml, source="Europe PMC")

    async def lookup(identifiers: list[tuple[str, str]]) -> Any:
        return await asyncio.to_thread(store.find, identifiers)

    return FulltextService(
        europe_pmc_client_factory=lambda: europe,
        unpaywall_client_factory=MagicMock,
        core_client_factory=MagicMock,
        downloader_factory=MagicMock(side_effect=RuntimeError("no downloader")),
        structured_xml_fetcher=xml_fetcher,
        supplied_fulltext_lookup=lookup,
        deadline_seconds=30.0,
    )


async def test_abstract_only_registration_falls_through_to_providers_with_a_note(tmp_path: Path) -> None:
    intake, store = _intake(tmp_path)
    await intake.register(
        _request("pmcid", "PMC7000001", content="# Title\n\n## Abstract\nOnly the abstract was captured.\n")
    )
    xml_fetcher = AsyncMock(return_value=BODY_XML)

    result = await _provider_service(store, xml_fetcher).retrieve(
        FulltextRequest(pmcid="PMC7000001", explicit_article_read=True)
    )

    xml_fetcher.assert_awaited_once()
    assert result.has_retrieved_text
    assert result.fulltext_origin == "provider"
    assert ("registered_fulltext", "supplied_no_body") in [(n.source, n.code) for n in result.source_notices]
    assert result.supplied_fulltext is not None
    assert result.supplied_fulltext["origin"] == "agent_supplied"
    assert result.supplied_fulltext["has_body"] is False


async def test_body_less_registration_still_gets_a_plan_when_providers_fail(tmp_path: Path) -> None:
    intake, store = _intake(tmp_path)
    await intake.register(_request("pmcid", "PMC7000001", content="## Summary\nAbstract only.\n"))

    result = await _provider_service(store, AsyncMock(return_value=None)).retrieve(
        FulltextRequest(pmcid="PMC7000001", explicit_article_read=True)
    )

    assert not result.has_retrieved_text
    assert result.fulltext_plan, "a body-less registration must not suppress the plan"
    assert result.supplied_fulltext["has_body"] is False


# ----------------------------------------------------------------------------
# M2: newest registration wins per article, across identifiers
# ----------------------------------------------------------------------------


async def test_a_correction_under_one_identifier_is_served_under_all_known_identifiers(tmp_path: Path) -> None:
    intake, store = _intake(tmp_path)
    old = await intake.register(
        _request(content="## Results\nOLD wrong text", aliases=(("pmcid", "PMC200"), ("doi", "10.1000/ABC")))
    )
    new = await intake.register(_request(content="## Results\nNEW corrected text"))

    for identifier in (("pmid", "100"), ("pmcid", "PMC200"), ("doi", "10.1000/abc")):
        found = store.find([identifier])
        assert found is not None and found.record_id == new.record.record_id, identifier
    assert new.record.identifiers == {"pmid": "100", "pmcid": "PMC200", "doi": "10.1000/abc"}
    assert old.record.record_id != new.record.record_id


async def test_a_registration_under_another_identifier_of_the_same_article_supersedes(tmp_path: Path) -> None:
    intake, store = _intake(tmp_path)
    await intake.register(_request(aliases=(("pmcid", "PMC200"),)))
    newer = await intake.register(_request("pmcid", "PMC200", content="## Results\nPMCID correction"))

    assert store.find([("pmid", "100")]).record_id == newer.record.record_id


async def test_declared_identifiers_link_the_article_for_later_reads(tmp_path: Path) -> None:
    intake, store = _intake(tmp_path)
    outcome = await intake.register(_request("pmcid", FIXTURE_PMCID, content=PMC_ARTICLE_PAGE, content_format="html"))

    assert outcome.record.identifiers == {"pmcid": FIXTURE_PMCID, "pmid": FIXTURE_PMID, "doi": FIXTURE_DOI.lower()}
    assert store.find([("pmid", FIXTURE_PMID)]).record_id == outcome.record.record_id


# ----------------------------------------------------------------------------
# M3: supplied documents must describe the requested article
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "value", "content", "content_format"),
    [
        ("pmid", "12345", PMC_ARTICLE_PAGE, "html"),
        ("pmcid", "PMC1", PMC_ARTICLE_PAGE, "html"),
        ("pmcid", "PMC1", PMC_EFETCH_FULL_BODY, "jats"),
        ("doi", "10.9999/other", PMC_EFETCH_FULL_BODY, "jats"),
    ],
    ids=["html-pmid", "html-pmcid", "jats-pmcid", "jats-doi"],
)
async def test_a_document_declaring_another_article_is_refused(
    tmp_path: Path, kind: str, value: str, content: str, content_format: str
) -> None:
    intake, store = _intake(tmp_path)
    with pytest.raises(SuppliedFulltextError) as caught:
        await intake.register(_request(kind, value, content=content, content_format=content_format))

    assert caught.value.code == "invalid_input"
    assert "declares a different article" in str(caught.value)
    assert store.find([(kind, value)]) is None


async def test_a_document_without_declared_identifiers_is_accepted(tmp_path: Path) -> None:
    intake, _ = _intake(tmp_path)
    jats_without_ids = PMC_EFETCH_FULL_BODY.replace('<article-id pub-id-type="pmid">12345678</article-id>', "")
    jats_without_ids = jats_without_ids.replace('<article-id pub-id-type="pmc">7096777</article-id>', "")
    jats_without_ids = jats_without_ids.replace('<article-id pub-id-type="doi">10.1000/smoke</article-id>', "")
    outcome = await intake.register(_request("pmcid", "PMC1", content=jats_without_ids, content_format="jats"))

    assert outcome.record.identifiers == {"pmcid": "PMC1"}


def test_jats_parser_reports_declared_article_ids() -> None:
    parsed = parse_jats_article(PMC_EFETCH_FULL_BODY, source="test")
    assert parsed["article_ids"] == {"pmid": "12345678", "pmcid": "PMC7096777", "doi": "10.1000/smoke"}


# ----------------------------------------------------------------------------
# M5 / L10: paths are inspected as strings before the OS is touched
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        r"\\attacker.invalid\share\paper.pdf",
        "//attacker.invalid/share/paper.pdf",
        r"\\?\C:\workspace\paper.pdf",
        r"\\.\C:\workspace\paper.pdf",
        r"\\?\UNC\attacker.invalid\share\paper.pdf",
        "C:paper.pdf",
    ],
    ids=["unc", "forward-unc", "extended-length", "device", "extended-unc", "drive-relative"],
)
def test_network_device_and_drive_relative_paths_never_reach_the_filesystem(tmp_path: Path, raw: str) -> None:
    policy = IntakePathPolicy(roots=(tmp_path,))
    touched: list[str] = []
    real_resolve = Path.resolve
    real_stat = os.stat

    def spy_resolve(self: Path, strict: bool = False) -> Path:
        touched.append(f"resolve:{self}")
        return real_resolve(self, strict=strict)

    def spy_stat(path: Any, *args: Any, **kwargs: Any) -> Any:
        touched.append(f"stat:{path}")
        return real_stat(path, *args, **kwargs)

    with patch.object(Path, "resolve", spy_resolve), patch("os.stat", spy_stat):
        with pytest.raises(SuppliedFulltextError) as caught:
            policy.resolve(raw)
    assert caught.value.code == "file_not_allowed"
    assert not [entry for entry in touched if "attacker" in entry or entry.endswith(raw)], touched


def test_a_path_outside_the_roots_is_refused_before_resolution(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("x", encoding="utf-8")
    policy = IntakePathPolicy(roots=(root,))
    calls: list[str] = []
    real_resolve = Path.resolve

    def spy_resolve(self: Path, strict: bool = False) -> Path:
        calls.append(str(self))
        return real_resolve(self, strict=strict)

    with patch.object(Path, "resolve", spy_resolve):
        with pytest.raises(SuppliedFulltextError) as caught:
            policy.resolve(str(outside))
    assert caught.value.code == "file_not_allowed"
    assert str(outside) not in calls


def test_a_file_swapped_after_the_check_is_not_read(tmp_path: Path) -> None:
    from pubmed_search.application.fulltext.intake import read_checked_file

    first = tmp_path / "a.md"
    first.write_text("first", encoding="utf-8")
    expected = os.stat(first)
    first.unlink()
    first.write_text("second file with other identity", encoding="utf-8")
    replacement = os.stat(first)
    if (replacement.st_dev, replacement.st_ino) == (expected.st_dev, expected.st_ino):
        pytest.skip("filesystem reused the file identity")

    with pytest.raises(SuppliedFulltextError) as caught:
        read_checked_file(first, expected, limit=1_000)
    assert caught.value.code == "file_not_allowed"


@pytest.mark.skipif(os.name != "nt", reason="NTFS junctions")
def test_a_junction_escape_is_refused(tmp_path: Path) -> None:
    import subprocess

    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.md").write_text("secret", encoding="utf-8")
    shell = os.environ.get("COMSPEC") or r"C:\Windows\System32\cmd.exe"
    created = subprocess.run(
        [shell, "/c", "mklink", "/J", str(root / "j"), str(outside)], capture_output=True, check=False
    )
    if created.returncode:
        pytest.skip("junctions are not available")
    with pytest.raises(SuppliedFulltextError) as caught:
        IntakePathPolicy(roots=(root,)).resolve("j/secret.md")
    assert caught.value.code == "file_not_allowed"


# ----------------------------------------------------------------------------
# L7 / L8: store writes survive Windows sharing violations and stay bounded
# ----------------------------------------------------------------------------


async def test_a_transient_sharing_violation_is_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    intake, store = _intake(tmp_path)
    real_write = supplied_module.atomic_write_json
    failures = {"left": 2}

    def flaky(path: Any, payload: Any, **kwargs: Any) -> None:
        if failures["left"]:
            failures["left"] -= 1
            raise PermissionError(13, "sharing violation")
        real_write(path, payload, **kwargs)

    monkeypatch.setattr(supplied_module, "atomic_write_json", flaky)
    outcome = await intake.register(_request())

    assert store.find([("pmid", "100")]).record_id == outcome.record.record_id


async def test_a_failed_save_restores_the_previous_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    intake, store = _intake(tmp_path)
    original = await intake.register(_request(aliases=(("pmcid", "PMC200"),)))
    real_write = supplied_module.atomic_write_json
    writes = {"count": 0}

    def fail_on_second_pointer(path: Any, payload: Any, **kwargs: Any) -> None:
        writes["count"] += 1
        if writes["count"] >= 3:  # record, first pointer, then the second pointer fails for good
            raise PermissionError(13, "sharing violation")
        real_write(path, payload, **kwargs)

    monkeypatch.setattr(supplied_module, "atomic_write_json", fail_on_second_pointer)
    monkeypatch.setattr(supplied_module, "_RETRY_DELAYS", (0.0,))
    with pytest.raises(SuppliedFulltextError) as caught:
        await intake.register(_request(content="## Results\nreplacement"))

    assert caught.value.code == "storage_unavailable"
    for identifier in (("pmid", "100"), ("pmcid", "PMC200")):
        assert store.find([identifier]).record_id == original.record.record_id
    assert len(list((store.root / "records").glob("sft-*.json"))) == 1


async def test_eviction_removes_stale_pointers_and_honours_a_byte_quota(tmp_path: Path) -> None:
    store = SuppliedFulltextStore(tmp_path / "s", max_records=3, max_bytes=6_000)
    intake = FulltextIntakeService(store=store, parser=IntakeContentParsers(), path_policy=IntakePathPolicy())
    for pmid in range(1, 8):
        await intake.register(_request(value=str(pmid), content=f"## Results\nbody {pmid}"))
    pointers = list((tmp_path / "s" / "by_identifier").glob("*.json"))
    records = list((tmp_path / "s" / "records").glob("sft-*.json"))
    assert len(records) == 3
    assert len(pointers) == 3

    await intake.register(_request(value="50", content="## Results\n" + "x" * 5_000))
    sizes = sum(path.stat().st_size for path in (tmp_path / "s" / "records").glob("sft-*.json"))
    assert sizes <= 6_000
    assert store.find([("pmid", "50")]) is not None


# ----------------------------------------------------------------------------
# L9 / L12 / L14: notes lookups, labelling, PDF signature, URL redaction, roots
# ----------------------------------------------------------------------------


async def test_note_export_finds_registrations_by_a_raw_mixed_case_doi(tmp_path: Path, monkeypatch) -> None:
    from pubmed_search.presentation.mcp_server.tools import fulltext_runtime

    intake, store = _intake(tmp_path)
    await intake.register(_request("doi", "10.1000/ABC"))
    monkeypatch.setattr(fulltext_runtime, "supplied_fulltext_store", lambda: store)
    articles = [{"pmid": "", "doi": "10.1000/ABC", "pmc_id": ""}]

    fulltext_runtime.attach_registered_fulltext(articles)

    assert articles[0]["registered_fulltext"]["origin"] == "agent_supplied"


async def test_supplied_text_has_its_own_provenance_and_keeps_the_license_with_the_supplier(tmp_path: Path) -> None:
    intake, store = _intake(tmp_path)
    provenance = dict(PROVENANCE, license="CC BY 4.0 (as shown on the mirror)")
    await intake.register(FulltextIntakeRequest("pmid", "100", provenance, content="## Results\nbody"))

    result = await _provider_service(store, AsyncMock(return_value=None)).retrieve(FulltextRequest(pmid="100"))

    assert result.fulltext_provenance == "supplied"
    assert result.fulltext_license is None
    assert result.fulltext_retrieval["license"] == "CC BY 4.0 (as shown on the mirror)"


async def test_pdf_signature_may_follow_leading_bytes(tmp_path: Path) -> None:
    class _Parser(IntakeContentParsers):
        async def extract_pdf_text(self, data: bytes) -> str | None:
            return "Results\nPDF body."

    store = SuppliedFulltextStore(tmp_path / "s")
    intake = FulltextIntakeService(store=store, parser=_Parser(), path_policy=IntakePathPolicy(roots=(tmp_path,)))
    (tmp_path / "late.pdf").write_bytes(b"\r\n\x00junk" + b"%PDF-1.7\nrest")
    (tmp_path / "fake.pdf").write_bytes(b"x" * 2_000 + b"%PDF-1.7")

    outcome = await intake.register(FulltextIntakeRequest("pmid", "1", dict(PROVENANCE), file_path="late.pdf"))
    with pytest.raises(SuppliedFulltextError) as fake:
        await intake.register(FulltextIntakeRequest("pmid", "2", dict(PROVENANCE), file_path="fake.pdf"))

    assert outcome.record.content_format == "pdf"
    assert fake.value.code == "unsupported_file_type"


async def test_source_url_credentials_and_signed_query_values_are_redacted(tmp_path: Path) -> None:
    intake, _ = _intake(tmp_path)
    provenance = dict(
        PROVENANCE,
        source_url="https://user:pass@cdn.example.org/a.pdf?X-Amz-Signature=abc&token=xyz&pii=S0140&page=2#frag",
    )
    outcome = await intake.register(FulltextIntakeRequest("pmid", "1", provenance, content="## Results\nbody"))

    stored = outcome.record.provenance.source_url or ""
    assert "user" not in stored and "pass" not in stored
    assert "abc" not in stored and "xyz" not in stored and "frag" not in stored
    assert "pii=S0140" in stored and "page=2" in stored


def test_the_tenant_root_is_the_fulltext_intake_folder_not_the_whole_data_root(tmp_path: Path, monkeypatch) -> None:
    from pubmed_search.presentation.mcp_server.tools.fulltext_intake import _intake_path_policy
    from pubmed_search.shared.settings import reset_settings_cache

    for name in ("PUBMED_WORKSPACE_DIR", "PUBMED_NOTES_DIR", "PUBMED_FULLTEXT_INTAKE_ROOTS"):
        monkeypatch.delenv(name, raising=False)
    reset_settings_cache()
    try:
        policy = _intake_path_policy(tmp_path / "data" / "fulltext" / "supplied")
    finally:
        reset_settings_cache()
    assert policy.roots == (tmp_path / "data" / "fulltext" / "intake",)


def test_registration_annotations_disclose_replacement() -> None:
    from pubmed_search.presentation.mcp_server.tool_contracts import tool_annotations

    annotations = tool_annotations("register_fulltext")
    assert annotations.destructive_hint is True
    assert annotations.read_only_hint is False
    assert annotations.open_world_hint is False
