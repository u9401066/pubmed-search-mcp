"""Retraction, expression-of-concern, erratum and update detection.

The PubMed path parses a real EFetch-shaped XML document through
``Bio.Entrez`` (the bundled DTD, no network), so a regression in how
``CommentsCorrections`` attributes are read fails here rather than in
production. The Wakefield 1998 Lancet record (PMID 9500320) and its
retraction notice (PMID 20137807) are real; the erratum link is illustrative.
"""

from __future__ import annotations

import io
from typing import Any

from Bio import Entrez

from pubmed_search.application.reference_verification import ReferenceVerificationService
from pubmed_search.domain.entities.article import SourceMetadata, UnifiedArticle
from pubmed_search.domain.services.publication_integrity import (
    STATUS_CORRECTED,
    STATUS_EXPRESSION_OF_CONCERN,
    STATUS_NONE_FOUND,
    STATUS_RETRACTED,
    assess_integrity,
)
from pubmed_search.infrastructure.ncbi.search import SearchMixin
from pubmed_search.presentation.mcp_server.tools.tool_response import format_search_results
from pubmed_search.presentation.mcp_server.tools.unified_formatting import _summary_article_payload
from tests.test_reference_verification_corrections import FakePubMed, _record

RETRACTED_XML = b"""<?xml version="1.0" ?>
<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle, 1st January 2025//EN" \
"https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_250101.dtd">
<PubmedArticleSet><PubmedArticle><MedlineCitation Status="MEDLINE" Owner="NLM">
<PMID Version="1">9500320</PMID>
<Article PubModel="Print"><Journal><JournalIssue CitedMedium="Print"><Volume>351</Volume><Issue>9103</Issue>
<PubDate><Year>1998</Year><Month>Feb</Month><Day>28</Day></PubDate></JournalIssue>
<Title>Lancet (London, England)</Title><ISOAbbreviation>Lancet</ISOAbbreviation></Journal>
<ArticleTitle>Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive developmental disorder \
in children.</ArticleTitle>
<Pagination><MedlinePgn>637-41</MedlinePgn></Pagination>
<AuthorList><Author><LastName>Wakefield</LastName><ForeName>A J</ForeName><Initials>AJ</Initials></Author></AuthorList>
<Language>eng</Language>
<PublicationTypeList><PublicationType UI="D016428">Journal Article</PublicationType>
<PublicationType UI="D016441">Retracted Publication</PublicationType></PublicationTypeList></Article>
<CommentsCorrectionsList>
<CommentsCorrections RefType="CommentIn"><RefSource>Lancet. 1998;351(9103):611-2</RefSource>
<PMID Version="1">9500315</PMID></CommentsCorrections>
<CommentsCorrections RefType="RetractionIn"><RefSource>Lancet. 2010 Feb 6;375(9713):445</RefSource>
<PMID Version="1">20137807</PMID></CommentsCorrections>
<CommentsCorrections RefType="ErratumIn"><RefSource>Lancet. 2004;363(9411):750</RefSource>
<PMID Version="1">15016483</PMID></CommentsCorrections>
</CommentsCorrectionsList></MedlineCitation>
<PubmedData><ArticleIdList><ArticleId IdType="pubmed">9500320</ArticleId>
<ArticleId IdType="doi">10.1016/s0140-6736(97)11096-0</ArticleId></ArticleIdList></PubmedData>
</PubmedArticle></PubmedArticleSet>"""


def _parsed_retracted_row() -> dict[str, Any]:
    record = Entrez.read(io.BytesIO(RETRACTED_XML))
    return SearchMixin()._parse_pubmed_article(record["PubmedArticle"][0])


def test_efetch_parse_keeps_only_integrity_links() -> None:
    row = _parsed_retracted_row()

    assert row["comments_corrections"] == [
        {"ref_type": "RetractionIn", "pmid": "20137807", "ref_source": "Lancet. 2010 Feb 6;375(9713):445"},
        {"ref_type": "ErratumIn", "pmid": "15016483", "ref_source": "Lancet. 2004;363(9411):750"},
    ]


def test_retraction_link_outranks_erratum_and_names_the_notice() -> None:
    integrity = assess_integrity([("pubmed", _parsed_retracted_row())])

    assert integrity.status == STATUS_RETRACTED
    assert integrity.caution is True
    assert integrity.badge == "[RETRACTED: notice PMID 20137807]"
    kinds = [notice.kind for notice in integrity.notices]
    # The linked notice supersedes the bare "Retracted Publication" type.
    assert kinds == ["RetractionIn", "ErratumIn"]
    assert integrity.to_dict()["checked_sources"] == ["pubmed"]


def test_clean_record_reports_none_found_without_validity_claim() -> None:
    integrity = assess_integrity([("pubmed", {"publication_types": ["Journal Article"], "comments_corrections": []})])

    assert integrity.status == STATUS_NONE_FOUND
    assert integrity.flagged is False
    assert integrity.badge is None
    assert "not a validity judgement" in integrity.to_dict()["note"]


def test_notice_record_is_not_reported_as_the_concern_itself() -> None:
    notice = {
        "publication_types": ["Expression of Concern"],
        "comments_corrections": [{"ref_type": "ExpressionOfConcernFor", "pmid": "111"}],
    }

    integrity = assess_integrity([("pubmed", notice)])

    assert integrity.status == STATUS_NONE_FOUND
    assert integrity.is_notice is True
    assert integrity.badge == "[NOTICE RECORD]"


def test_openalex_and_crossref_notices_are_merged() -> None:
    crossref = {
        "updated-by": [
            {
                "type": "expression_of_concern",
                "DOI": "10.1000/eoc",
                "source": "retraction-watch",
                "updated": {"date-parts": [[2024, 3, 5]]},
            },
            {"type": "correction", "DOI": "10.1000/corr", "source": "publisher"},
        ]
    }

    integrity = assess_integrity([("crossref", crossref), ("openalex", {"is_retracted": False})])

    assert integrity.status == STATUS_EXPRESSION_OF_CONCERN
    first = integrity.notices[0].to_dict()
    assert first == {
        "status": STATUS_EXPRESSION_OF_CONCERN,
        "source": "crossref:retraction-watch",
        "kind": "expression_of_concern",
        "doi": "10.1000/eoc",
        "date": "2024-03-05",
    }
    assert integrity.checked_sources == ("crossref", "openalex")

    retracted = assess_integrity([("openalex", {"is_retracted": True})])
    assert retracted.status == STATUS_RETRACTED


def test_unified_article_surfaces_integrity_in_full_and_summary_records() -> None:
    article = UnifiedArticle.from_pubmed(_parsed_retracted_row())

    assert article.to_dict()["integrity"]["status"] == STATUS_RETRACTED
    summary = _summary_article_payload(article, rank=1, include_rank_scores=False)
    assert summary["integrity"]["notices"][0]["pmid"] == "20137807"

    clean = UnifiedArticle(
        title="Clean",
        primary_source="pubmed",
        pmid="1",
        sources=[SourceMetadata(source="pubmed", raw_data={"comments_corrections": []})],
    )
    # Clean summary rows stay small: no integrity block at all.
    assert "integrity" not in _summary_article_payload(clean, rank=1, include_rank_scores=False)


def test_fetch_markdown_shows_integrity_line() -> None:
    text = format_search_results([_parsed_retracted_row()])

    assert "Integrity: ⛔ \\[RETRACTED: notice PMID 20137807\\]" in text


async def test_reference_list_raises_integrity_alerts() -> None:
    record = _record(
        "9500320",
        title="Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive developmental disorder in children.",
        authors=["Wakefield AJ"],
        journal="Lancet (London, England)",
        journal_abbrev="Lancet",
        year="1998",
        volume="351",
        issue="9103",
        pages="637-41",
    )
    record["publication_types"] = ["Journal Article", "Retracted Publication"]
    record["comments_corrections"] = [{"ref_type": "RetractionIn", "pmid": "20137807"}]
    corrected = _record(
        "7772368",
        title="The post-anesthesia recovery score revisited.",
        authors=["Aldrete JA"],
        journal="Journal of clinical anesthesia",
        journal_abbrev="J Clin Anesth",
        year="1995",
        volume="7",
        issue="1",
        pages="89-91",
    )
    corrected["comments_corrections"] = [{"ref_type": "ErratumIn", "pmid": "8000000"}]
    references = (
        "1. Wakefield AJ. Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive developmental "
        "disorder in children. Lancet. 1998;351(9103):637-41.\n"
        "2. Aldrete JA. The post-anesthesia recovery score revisited. J Clin Anesth. 1995;7(1):89-91.\n"
    )

    report = await ReferenceVerificationService(FakePubMed([record, corrected])).verify_reference_list(references)

    alerts = {alert["pmid"]: alert for alert in report["integrity_alerts"]}
    assert alerts["9500320"]["status"] == STATUS_RETRACTED
    assert alerts["7772368"]["status"] == STATUS_CORRECTED
    retracted_row = report["results"][0]
    assert retracted_row["status"] == "verified"
    assert retracted_row["notes"][0].startswith("Cited work is flagged retracted")
