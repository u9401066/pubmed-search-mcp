"""Contracts for fulltext supplied by the host agent or user (``register_fulltext``).

The application intake service and store run for real against temporary
directories; JATS/HTML parsing uses the production infrastructure adapters.
Only PDF text extraction is injected, because no PDF backend is a project
dependency.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pubmed_search.application.fulltext import FulltextRequest, FulltextService
from pubmed_search.application.fulltext.intake import (
    FulltextIntakeRequest,
    FulltextIntakeService,
    IntakeLimits,
    IntakePathPolicy,
    split_text_sections,
)
from pubmed_search.application.fulltext.supplied import (
    SuppliedFulltextError,
    SuppliedFulltextStore,
)
from pubmed_search.infrastructure.sources.fulltext_intake import IntakeContentParsers
from tests.fixtures.pmc_html import PMC_ARTICLE_PAGE
from tests.fixtures.pmc_jats import PMC_EFETCH_FULL_BODY

if TYPE_CHECKING:
    from pathlib import Path

PAGE_URL = "https://pmc.ncbi.nlm.nih.gov/articles/PMC7000001/"
MARKDOWN = """# Guided anesthesia fixture trial

## Abstract
Fixture abstract sentence.

## Methods
Fixture methods paragraph.

## Results
Delirium occurred in 11 of 100 versus 9 of 101 (fixture numbers).
"""


def _provenance(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "retrieval_method": "host_fetch",
        "source_url": PAGE_URL,
        "retrieved_at": "2026-11-25T08:00:00Z",
    }
    base.update(overrides)
    return {key: value for key, value in base.items() if value is not None}


class _Parser(IntakeContentParsers):
    """Production JATS/HTML adapters with an injected PDF text result."""

    def __init__(self, pdf_text: str | None = "1. Methods\nPDF methods.\nRESULTS\nPDF results 4 of 40.\n") -> None:
        super().__init__()
        self.pdf_text = pdf_text
        self.pdf_calls = 0

    async def extract_pdf_text(self, data: bytes) -> str | None:
        self.pdf_calls += 1
        assert data.startswith(b"%PDF-")
        return self.pdf_text


def _service(
    tmp_path: Path,
    *,
    parser: _Parser | None = None,
    roots: tuple[Path, ...] | None = None,
    allow_files: bool = True,
    limits: IntakeLimits | None = None,
) -> tuple[FulltextIntakeService, SuppliedFulltextStore]:
    store = SuppliedFulltextStore(tmp_path / "data" / "fulltext" / "supplied")
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    service = FulltextIntakeService(
        store=store,
        parser=parser or _Parser(),
        path_policy=IntakePathPolicy(roots=roots if roots is not None else (workspace,), allow_files=allow_files),
        limits=limits,
    )
    return service, store


def _request(**overrides: Any) -> FulltextIntakeRequest:
    fields: dict[str, Any] = {
        "identifier_kind": "pmid",
        "identifier_value": "39000001",
        "provenance": _provenance(),
        "content": MARKDOWN,
    }
    fields.update(overrides)
    return FulltextIntakeRequest(**fields)


# ----------------------------------------------------------------------------
# Content normalization
# ----------------------------------------------------------------------------


def test_markdown_and_plain_headings_become_the_shared_section_model() -> None:
    parsed = split_text_sections(MARKDOWN + "\nDISCUSSION\nPlain-text discussion line.\n2. Limitations\nLimits.\n")

    assert parsed["title"] == "Guided anesthesia fixture trial"
    assert parsed["abstract"] == "Fixture abstract sentence."
    assert [section["title"] for section in parsed["sections"]] == ["Methods", "Results", "Discussion", "Limitations"]
    assert parsed["sections"][1]["content"].startswith("Delirium occurred in 11 of 100")


async def test_markdown_registration_is_stored_with_provenance_and_never_verified(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    outcome = await service.register(_request(aliases=(("doi", "10.5555/Fixture.2024.001"), ("pmcid", "bad"))))
    record = outcome.record

    assert record.origin == "agent_supplied"
    assert record.identifiers == {"pmid": "39000001", "doi": "10.5555/fixture.2024.001"}
    assert record.provenance.to_dict() == _provenance()
    assert [section["title"] for section in record.sections] == ["Methods", "Results"]
    assert record.retrieval_summary()["provider_verified"] is False
    assert any("verbatim" in hint for hint in record.hints)
    assert store.find([("doi", "10.5555/fixture.2024.001")]) == record
    assert store.find([("pmcid", "PMC1")]) is None


async def test_jats_and_pmc_html_content_reuse_the_provider_parsers(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    jats = await service.register(_request(content=PMC_EFETCH_FULL_BODY, content_format="jats"))
    html = await service.register(
        _request(identifier_value="39000002", content=PMC_ARTICLE_PAGE, content_format="html", supplied_by="user")
    )

    assert "Abstract-only result sentence" not in json.dumps(jats.record.sections)
    assert [section["title"] for section in jats.record.sections][:2] == ["Introduction", "Trial Design"]
    assert html.record.origin == "user_supplied"
    assert "Primary Outcome" in [section["title"] for section in html.record.sections]
    assert "Search in PMC" not in json.dumps(html.record.sections)


async def test_malformed_jats_is_rejected_without_storing(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    with pytest.raises(SuppliedFulltextError) as caught:
        await service.register(_request(content="<article><body>", content_format="jats"))

    assert caught.value.code == "invalid_content"
    assert store.find([("pmid", "39000001")]) is None


# ----------------------------------------------------------------------------
# Provenance and bounds
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("provenance", "fragment"),
    [
        (_provenance(source_url=None), "source_url or a file"),
        (_provenance(retrieved_at="yesterday"), "ISO-8601"),
        (_provenance(retrieved_at=(datetime.now(tz=timezone.utc) + timedelta(days=2)).isoformat()), "future"),
        (_provenance(retrieval_method="scraper"), "retrieval_method"),
        (_provenance(source_url="file:///etc/passwd"), "http(s)"),
        (_provenance(license="x" * 501), "at most 500"),
    ],
    ids=["no-source", "bad-time", "future", "method", "scheme", "license-size"],
)
async def test_provenance_is_mandatory_and_validated(tmp_path: Path, provenance: dict[str, Any], fragment: str) -> None:
    service, store = _service(tmp_path)
    with pytest.raises(SuppliedFulltextError) as caught:
        await service.register(_request(provenance=provenance))

    assert caught.value.code == "invalid_provenance"
    assert fragment in str(caught.value)
    assert store.find([("pmid", "39000001")]) is None


async def test_content_and_section_bounds_are_enforced(tmp_path: Path) -> None:
    limits = IntakeLimits(max_inline_chars=5_000, max_stored_chars=60, max_sections=2)
    service, _ = _service(tmp_path, limits=limits)
    with pytest.raises(SuppliedFulltextError) as too_large:
        await service.register(_request(content="x" * 5_001))
    outcome = await service.register(_request(content="## A\n" + "a" * 40 + "\n## B\n" + "b" * 40 + "\n## C\nc\n"))

    assert too_large.value.code == "content_too_large"
    assert outcome.record.truncated is True
    assert outcome.record.char_count == 60
    assert [section["title"] for section in outcome.record.sections] == ["A", "B"]


async def test_exactly_one_of_content_or_file_and_a_non_empty_body(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    with pytest.raises(SuppliedFulltextError) as both:
        await service.register(_request(file_path="paper.md"))
    with pytest.raises(SuppliedFulltextError) as empty:
        await service.register(_request(content="# Only a title\n"))

    assert both.value.code == "content_required"
    assert empty.value.code == "empty_content"


# ----------------------------------------------------------------------------
# Local files: roots, traversal, symlinks, types and sizes
# ----------------------------------------------------------------------------


async def test_relative_file_inside_the_workspace_is_read_with_its_name_as_provenance(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    (tmp_path / "workspace" / "papers").mkdir()
    (tmp_path / "workspace" / "papers" / "trial.md").write_text(MARKDOWN, encoding="utf-8")

    outcome = await service.register(
        _request(
            content=None,
            file_path="papers/trial.md",
            provenance=_provenance(source_url=None, retrieval_method="user_upload"),
        )
    )

    assert outcome.file_name == "trial.md"
    assert outcome.record.provenance.source_file == "trial.md"
    assert outcome.record.content_format == "markdown"


@pytest.mark.parametrize(
    ("path_factory", "code"),
    [
        (lambda tmp: "papers/../../outside.md", "file_not_allowed"),
        (lambda tmp: str(tmp / "outside.md"), "file_not_allowed"),
        (lambda tmp: str(tmp / "workspace" / "missing.md"), "file_not_found"),
        (lambda tmp: str(tmp / "workspace" / "notes.docx"), "unsupported_file_type"),
        (lambda tmp: str(tmp / "workspace" / "fake.pdf"), "unsupported_file_type"),
        (lambda tmp: str(tmp / "workspace"), "file_not_allowed"),
    ],
    ids=["traversal", "outside-root", "missing", "extension", "not-a-pdf", "directory"],
)
async def test_file_paths_are_confined_to_allowed_roots_and_types(tmp_path: Path, path_factory: Any, code: str) -> None:
    service, store = _service(tmp_path)
    (tmp_path / "outside.md").write_text(MARKDOWN, encoding="utf-8")
    (tmp_path / "workspace" / "notes.docx").write_bytes(b"PK\x03\x04")
    (tmp_path / "workspace" / "fake.pdf").write_text("not really a pdf", encoding="utf-8")

    with pytest.raises(SuppliedFulltextError) as caught:
        await service.register(_request(content=None, file_path=path_factory(tmp_path)))

    assert caught.value.code == code
    assert store.find([("pmid", "39000001")]) is None


async def test_symlink_that_escapes_the_root_is_rejected(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    secret = tmp_path / "secret.md"
    secret.write_text(MARKDOWN, encoding="utf-8")
    link = tmp_path / "workspace" / "linked.md"
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available to this test process")

    with pytest.raises(SuppliedFulltextError) as caught:
        await service.register(_request(content=None, file_path=str(link)))

    assert caught.value.code == "file_not_allowed"


async def test_remote_callers_cannot_register_server_files(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, allow_files=False)
    (tmp_path / "workspace" / "trial.md").write_text(MARKDOWN, encoding="utf-8")

    with pytest.raises(SuppliedFulltextError) as caught:
        await service.register(_request(content=None, file_path=str(tmp_path / "workspace" / "trial.md")))

    assert caught.value.code == "file_not_allowed"
    assert "send the text as content" in str(caught.value)


async def test_no_configured_root_means_no_file_reads(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, roots=())
    with pytest.raises(SuppliedFulltextError) as caught:
        await service.register(_request(content=None, file_path=str(tmp_path / "workspace" / "trial.md")))

    assert caught.value.code == "file_not_allowed"


async def test_oversized_files_are_rejected_before_parsing(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, limits=IntakeLimits(max_text_file_bytes=10))
    (tmp_path / "workspace" / "big.txt").write_text("x" * 11, encoding="utf-8")

    with pytest.raises(SuppliedFulltextError) as caught:
        await service.register(_request(content=None, file_path="big.txt"))

    assert caught.value.code == "file_too_large"


async def test_pdf_text_is_extracted_with_a_citation_ready_hint(tmp_path: Path) -> None:
    parser = _Parser()
    service, _ = _service(tmp_path, parser=parser)
    (tmp_path / "workspace" / "trial.pdf").write_bytes(b"%PDF-1.7\nfixture")

    outcome = await service.register(
        _request(
            content=None,
            file_path="trial.pdf",
            supplied_by="user",
            provenance=_provenance(source_url=None, retrieval_method="zotero_attachment"),
        )
    )

    assert parser.pdf_calls == 1
    assert outcome.record.content_format == "pdf"
    assert [section["title"] for section in outcome.record.sections] == ["Methods", "Results"]
    assert any("asset-aware-mcp" in hint for hint in outcome.record.hints)


async def test_pdf_without_extractable_text_points_to_asset_aware_ingest(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, parser=_Parser(pdf_text=None))
    (tmp_path / "workspace" / "scanned.pdf").write_bytes(b"%PDF-1.4\nscanned")

    with pytest.raises(SuppliedFulltextError) as caught:
        await service.register(_request(content=None, file_path="scanned.pdf"))

    assert caught.value.code == "extraction_failed"
    assert "asset-aware-mcp" in str(caught.value)


# ----------------------------------------------------------------------------
# Store
# ----------------------------------------------------------------------------


async def test_newest_registration_wins_and_the_store_is_bounded(tmp_path: Path) -> None:
    store = SuppliedFulltextStore(tmp_path / "supplied", max_records=3)
    service = FulltextIntakeService(store=store, parser=_Parser(), path_policy=IntakePathPolicy())
    first = await service.register(_request(content="## Results\nfirst version"))
    second = await service.register(_request(content="## Results\nsecond version"))

    assert store.find([("pmid", "39000001")]) == second.record
    assert store.load(first.record.record_id) == first.record

    others = [await service.register(_request(identifier_value=f"3900010{index}")) for index in range(2)]

    # Oldest first: the bound keeps the three newest records.
    assert store.load(first.record.record_id) is None
    assert store.load(second.record.record_id) == second.record
    assert [store.load(other.record.record_id) for other in others] == [other.record for other in others]
    assert len(list((tmp_path / "supplied" / "records").glob("sft-*.json"))) == 3
    await service.register(_request(identifier_value="39000200"))
    # A pointer to an evicted record reads as a miss, never as stale text.
    assert store.find([("pmid", "39000001")]) is None


def test_tampered_or_unsafe_store_entries_read_as_misses(tmp_path: Path) -> None:
    store = SuppliedFulltextStore(tmp_path / "supplied")
    pointer_dir = tmp_path / "supplied" / "by_identifier"
    pointer_dir.mkdir(parents=True)
    pointer = pointer_dir / store._pointer_name("pmid", "39000001")
    pointer.write_text(json.dumps({"kind": "pmid", "value": "39000001", "record_id": "../../escape"}), encoding="utf-8")
    assert store.find([("pmid", "39000001")]) is None
    pointer.write_text("not json", encoding="utf-8")
    assert store.find([("pmid", "39000001")]) is None


# ----------------------------------------------------------------------------
# Reuse by get_fulltext (application service)
# ----------------------------------------------------------------------------


def _fulltext_service(store: SuppliedFulltextStore, *, europe_pmc: Any = None) -> FulltextService:
    async def lookup(identifiers: list[tuple[str, str]]) -> Any:
        return store.find(identifiers)

    return FulltextService(
        europe_pmc_client_factory=lambda: europe_pmc or MagicMock(),
        unpaywall_client_factory=MagicMock(side_effect=AssertionError("Unpaywall must not run")),
        core_client_factory=MagicMock(side_effect=AssertionError("CORE must not run")),
        downloader_factory=MagicMock(side_effect=AssertionError("downloader must not run")),
        supplied_fulltext_lookup=lookup,
        deadline_seconds=30.0,
    )


async def test_get_fulltext_serves_registered_text_first_and_labels_it(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    registered = (await service.register(_request())).record

    result = await _fulltext_service(store).retrieve(FulltextRequest(pmid="39000001", sections="results"))

    assert result.sources_tried == ["registered_fulltext"]
    assert result.policy_key == "registered_fulltext"
    assert [(notice.source, notice.code) for notice in result.source_notices] == [
        ("registered_fulltext", "supplied_not_verified")
    ]
    assert [section["title"] for section in result.content_sections] == ["Results"]
    assert result.fulltext_origin == "agent_supplied"
    assert result.fulltext_source_name == "Agent-supplied fulltext (unverified)"
    assert result.fulltext_provenance == "indirect"
    assert result.fulltext_retrieval is not None
    assert result.fulltext_retrieval["record_id"] == registered.record_id
    assert result.fulltext_retrieval["provider_verified"] is False
    assert result.fulltext_retrieval["source_url"] == PAGE_URL
    assert result.fulltext_plan == []


async def test_registered_text_is_found_through_resolved_identifiers(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    await service.register(_request(identifier_kind="doi", identifier_value="10.5555/fixture.2024.001"))
    europe_pmc = MagicMock()
    europe_pmc.get_article = AsyncMock(return_value={"doi": "10.5555/FIXTURE.2024.001"})

    result = await _fulltext_service(store, europe_pmc=europe_pmc).retrieve(FulltextRequest(pmid="39000001"))

    assert result.sources_tried == ["europe_pmc_metadata", "registered_fulltext"]
    assert result.fulltext_origin == "agent_supplied"
    assert result.doi == "10.5555/fixture.2024.001"


async def test_opting_out_requeries_providers(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    await service.register(_request(identifier_kind="pmcid", identifier_value="PMC7000001"))
    europe_pmc = MagicMock()
    xml_fetcher = AsyncMock(return_value=None)
    provider_service = FulltextService(
        europe_pmc_client_factory=lambda: europe_pmc,
        unpaywall_client_factory=MagicMock,
        core_client_factory=MagicMock,
        downloader_factory=MagicMock(side_effect=RuntimeError("no downloader")),
        structured_xml_fetcher=xml_fetcher,
        supplied_fulltext_lookup=AsyncMock(side_effect=AssertionError("lookup must be skipped")),
        deadline_seconds=30.0,
    )

    result = await provider_service.retrieve(FulltextRequest(pmcid="PMC7000001", use_registered_fulltext=False))

    xml_fetcher.assert_awaited_once_with("PMC7000001")
    assert "registered_fulltext" not in result.sources_tried
    assert result.fulltext_origin is None


async def test_a_broken_store_never_fails_a_provider_read(tmp_path: Path) -> None:
    xml_fetcher = AsyncMock(return_value=None)
    service = FulltextService(
        europe_pmc_client_factory=MagicMock,
        unpaywall_client_factory=MagicMock,
        core_client_factory=MagicMock,
        downloader_factory=MagicMock(side_effect=RuntimeError("no downloader")),
        structured_xml_fetcher=xml_fetcher,
        supplied_fulltext_lookup=AsyncMock(side_effect=OSError("disk gone")),
        deadline_seconds=30.0,
    )

    result = await service.retrieve(FulltextRequest(pmcid="PMC7000001"))

    xml_fetcher.assert_awaited_once()
    assert "registered_fulltext" not in result.sources_tried


# ----------------------------------------------------------------------------
# Tool boundary: tenant rules, path policy and note reuse
# ----------------------------------------------------------------------------


def _intake_tool() -> Any:
    from pubmed_search.presentation.mcp_server.tools.fulltext_intake import register_fulltext_intake_tools

    tools: dict[str, Any] = {}
    mcp = MagicMock()
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
    register_fulltext_intake_tools(mcp)
    return tools["register_fulltext"]


async def test_tool_refuses_callers_that_cannot_own_durable_storage() -> None:
    from pubmed_search.presentation.mcp_server.tools.article_source import PMIDSource
    from pubmed_search.presentation.mcp_server.tools.fulltext_intake import SuppliedProvenanceInput
    from pubmed_search.shared.tenancy import ANONYMOUS_HTTP_TENANT, bind_tenant

    register = _intake_tool()
    with bind_tenant(ANONYMOUS_HTTP_TENANT):
        response = await register(
            source=PMIDSource(kind="pmid", value="39000001"),
            provenance=SuppliedProvenanceInput(**_provenance()),
            content=MARKDOWN,
            output_format="json",
        )

    payload = json.loads(response)
    assert payload["success"] is False
    assert "authenticated caller" in payload["error"]


def test_path_policy_follows_identity_and_configured_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pubmed_search.presentation.mcp_server.tools.fulltext_intake import _intake_path_policy
    from pubmed_search.shared.settings import reset_settings_cache
    from pubmed_search.shared.tenancy import TenantIdentity, bind_tenant

    zotero = tmp_path / "Zotero" / "storage"
    monkeypatch.setenv("PUBMED_WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("PUBMED_NOTES_DIR", str(tmp_path / "notes"))
    monkeypatch.setenv("PUBMED_FULLTEXT_INTAKE_ROOTS", os.pathsep.join([str(zotero), " "]))
    reset_settings_cache()
    store_root = tmp_path / "data" / "fulltext" / "supplied"
    try:
        local = _intake_path_policy(store_root)
        with bind_tenant(TenantIdentity.for_principal("researcher@example.org")):
            remote = _intake_path_policy(store_root)
    finally:
        reset_settings_cache()

    assert local.allow_files is True
    assert local.roots == (tmp_path / "workspace", tmp_path / "notes", zotero, tmp_path / "data")
    assert remote.allow_files is False


def test_notes_record_registered_fulltext_without_copying_it(tmp_path: Path) -> None:
    from pubmed_search.application.export.notes import write_literature_notes

    article = {"pmid": "39000001", "title": "Fixture trial", "authors": ["Fixture A"], "year": "2024"}
    registered = {
        **article,
        "pmid": "39000002",
        "registered_fulltext": {
            "origin": "user_supplied",
            "record_id": "sft-0",
            "artifact_uri": "artifact://session/abc",
            "retrieved_at": "2026-11-25T08:00:00Z",
        },
    }
    write_literature_notes([article, registered], tmp_path / "wiki", note_format="wiki", create_index=False)
    write_literature_notes([article, registered], tmp_path / "medpaper", note_format="medpaper", create_index=False)

    plain_wiki = (tmp_path / "wiki" / "39000001.md").read_text(encoding="utf-8")
    supplied_wiki = (tmp_path / "wiki" / "39000002.md").read_text(encoding="utf-8")
    assert "fulltext_state" not in plain_wiki
    assert 'fulltext_state: "user_supplied"' in supplied_wiki
    assert "fulltext_provider_verified: false" in supplied_wiki
    assert 'fulltext_artifact_uri: "artifact://session/abc"' in supplied_wiki
    assert "not provider-verified" in supplied_wiki
    medpaper = {path.name: path.read_text(encoding="utf-8") for path in (tmp_path / "medpaper").rglob("*.md")}
    assert sum('fulltext_state: "missing"' in text for text in medpaper.values()) == 1
    assert sum('fulltext_state: "user_supplied"' in text for text in medpaper.values()) == 1
