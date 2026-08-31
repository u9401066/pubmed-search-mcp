"""Adversarial regression tests for repository-owned Markdown renderers."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from pubmed_search.application.chronicle.narrator import narrative_claim
from pubmed_search.application.export.notes import _render_article_note
from pubmed_search.application.pipeline.report_generator import _format_article, _section_header
from pubmed_search.application.timeline.timeline_builder import format_timeline_text
from pubmed_search.domain.entities.article import ArticleType
from pubmed_search.domain.entities.timeline import MilestoneType, ResearchTimeline, TimelineEvent
from pubmed_search.infrastructure.sources.clinical_trials import format_trials_section
from pubmed_search.presentation.mcp_server.tools.europe_pmc import _render_fulltext_content_for_artifact
from pubmed_search.shared.markdown import (
    escape_markdown_block,
    escape_markdown_text,
    markdown_code_block,
    markdown_link,
    safe_markdown_url,
)

_ATTACK = "# injected\n![pixel](javascript:alert(1)) [click](javascript:alert(2)) <script>\x00"


def _assert_inert(rendered: str) -> None:
    assert "\n# injected" not in rendered
    assert "![pixel]" not in rendered
    assert "](javascript:" not in rendered.lower()
    assert "<script>" not in rendered.lower()
    assert "\x00" not in rendered


def test_shared_markdown_primitives_preserve_structure_without_injection() -> None:
    inline = escape_markdown_text(_ATTACK)
    block = escape_markdown_block(f"first paragraph\n\n{_ATTACK}")

    assert "\n" not in inline
    assert block.startswith("first paragraph\n\n")
    _assert_inert(block)
    assert safe_markdown_url("javascript:alert(1)") is None
    assert safe_markdown_url("https://example.org/a path") is None
    assert markdown_link("click", "javascript:alert(1)") == "click"


def test_code_fence_expands_past_provider_backticks() -> None:
    rendered = markdown_code_block("before\n```\n# still code", language="json<script>")

    assert rendered.startswith("````jsonscript\n")
    assert rendered.endswith("\n````")


def test_pipeline_article_and_user_heading_are_inert() -> None:
    article = SimpleNamespace(
        title=_ATTACK,
        ranking_score=0,
        pmid="123\n# id",
        doi="10.1/x](javascript:alert(1))",
        pmc=None,
        article_type=ArticleType.UNKNOWN,
        author_string=_ATTACK,
        journal=_ATTACK,
        year=2024,
        volume=None,
        issue=None,
        pages=None,
        has_open_access=False,
        abstract=f"paragraph one\n\n{_ATTACK}",
        sources=[SimpleNamespace(source=_ATTACK)],
        citation_metrics=None,
        journal_metrics=None,
    )
    rendered = _section_header(SimpleNamespace(name=_ATTACK)) + _format_article(1, article)

    assert "# 📋 Pipeline Research Report:" in rendered
    assert "### 1." in rendered
    _assert_inert(rendered)


def test_provider_fulltext_preserves_paragraphs_but_not_markdown_or_html() -> None:
    rendered = _render_fulltext_content_for_artifact(
        [{"title": _ATTACK, "content": f"paragraph one\n\n{_ATTACK}"}],
        None,
    )

    assert rendered is not None
    assert rendered.startswith("### \\# injected")
    assert "paragraph one\n\n" in rendered
    _assert_inert(rendered)


def test_clinical_trials_fields_and_unsafe_url_are_inert() -> None:
    rendered = format_trials_section(
        [
            {
                "nct_id": _ATTACK,
                "url": "javascript:alert(1)",
                "status": _ATTACK,
                "phase": _ATTACK,
                "title": _ATTACK,
                "enrollment": _ATTACK,
            }
        ]
    )

    assert "clinicaltrials.gov" in rendered
    _assert_inert(rendered)


def test_legacy_timeline_and_chronicle_claim_fields_are_inert() -> None:
    timeline = ResearchTimeline(
        topic=_ATTACK,
        events=[
            TimelineEvent(
                pmid=_ATTACK,
                year=2024,
                milestone_type=MilestoneType.OTHER,
                title=_ATTACK,
                milestone_label=_ATTACK,
            )
        ],
    )
    rendered = format_timeline_text(timeline)
    claim = narrative_claim(
        SimpleNamespace(
            entry_id=_ATTACK,
            summary_claim=_ATTACK,
            evidence=SimpleNamespace(all_articles=[SimpleNamespace(evidence_id=_ATTACK)]),
        )
    )

    _assert_inert(rendered)
    _assert_inert(claim)


def test_default_and_medpaper_note_fields_are_inert() -> None:
    article = {
        "title": _ATTACK,
        "pmid": "12345678",
        "doi": "10.1/x](javascript:alert(1))",
        "pmc_id": "PMC123",
        "journal": _ATTACK,
        "year": "2024",
        "authors": [_ATTACK],
        "abstract": f"paragraph one\n\n{_ATTACK}",
    }
    created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

    for note_format in ("markdown", "medpaper"):
        rendered = _render_article_note(
            article,
            citation_key="safe-key",
            note_format=note_format,
            include_abstract=True,
            created_at=created_at,
        )
        assert "## Abstract" in rendered
        markdown_body = rendered.split("---", 2)[-1].split("## Citation Formats", 1)[0]
        _assert_inert(markdown_body)
