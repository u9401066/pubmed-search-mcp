"""Translate Biopython ESearch payloads into :class:`PubMedQueryDiagnostics`.

Biopython parses ``<WarningList>`` and ``<ErrorList>`` into dictionaries of
string lists and ``<TranslationSet>`` into a list of ``{"From", "To"}`` items.
Diagnostics are advisory: a malformed part is dropped, never raised, so a
schema drift in NCBI's warnings cannot turn a successful search into a
failure. Lists are bounded to keep result envelopes small.
"""

from __future__ import annotations

import logging
from typing import Any

from pubmed_search.domain.value_objects.query_diagnostics import PubMedQueryDiagnostics, TranslationEntry

logger = logging.getLogger(__name__)

MAX_DIAGNOSTIC_ITEMS = 50
MAX_DIAGNOSTIC_CHARS = 2_000
MAX_TRANSLATION_CHARS = 20_000


def _text(value: Any, limit: int = MAX_DIAGNOSTIC_CHARS) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _values(group: Any, key: str) -> tuple[str, ...]:
    if not hasattr(group, "get"):
        return ()
    raw = group.get(key)
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return ()
    values = [text for item in raw[:MAX_DIAGNOSTIC_ITEMS] if (text := _text(item))]
    return tuple(dict.fromkeys(values))


def _translation_set(raw: Any) -> tuple[TranslationEntry, ...]:
    if not isinstance(raw, list):
        return ()
    entries: list[TranslationEntry] = []
    for item in raw[:MAX_DIAGNOSTIC_ITEMS]:
        if not hasattr(item, "get"):
            continue
        source, target = _text(item.get("From")), _text(item.get("To"))
        if source and target:
            entries.append(TranslationEntry(source, target))
    return tuple(entries)


def parse_esearch_diagnostics(record: Any) -> PubMedQueryDiagnostics:
    """Extract PubMed's translation, WarningList and ErrorList from one ESearch record."""
    if not hasattr(record, "get"):
        return PubMedQueryDiagnostics()
    warnings = record.get("WarningList") or {}
    errors = record.get("ErrorList") or {}
    diagnostics = PubMedQueryDiagnostics(
        query_translation=_text(record.get("QueryTranslation"), MAX_TRANSLATION_CHARS),
        translation_set=_translation_set(record.get("TranslationSet")),
        quoted_phrases_not_found=_values(warnings, "QuotedPhraseNotFound"),
        phrases_ignored=_values(warnings, "PhraseIgnored"),
        output_messages=_values(warnings, "OutputMessage"),
        phrases_not_found=_values(errors, "PhraseNotFound"),
        fields_not_found=_values(errors, "FieldNotFound"),
        provider_error=_text(record.get("ERROR")),
    )
    if diagnostics.has_issues:
        # Counts only: the phrases themselves may carry the user's query.
        logger.warning(
            "NCBI query diagnostics: quoted_not_found=%s not_found=%s fields_not_found=%s ignored=%s",
            len(diagnostics.quoted_phrases_not_found),
            len(diagnostics.phrases_not_found),
            len(diagnostics.fields_not_found),
            len(diagnostics.phrases_ignored),
        )
    return diagnostics


__all__ = ["parse_esearch_diagnostics"]
