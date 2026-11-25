"""PubMed's own report on how it interpreted a query.

ESearch returns, alongside the count, the translation PubMed actually ran and
two diagnostic lists. ``WarningList`` names quoted phrases absent from the
phrase/MeSH index (``QuotedPhraseNotFound``), stopwords it dropped
(``PhraseIgnored``) and free-text output messages such as "No items found.".
``ErrorList`` names unquoted terms it could not find (``PhraseNotFound``) and
unknown field tags (``FieldNotFound``). A clause named in either list matched
nothing, so a single misspelled MeSH heading can silently zero an AND query.

This value object keeps those signals in a provider-neutral, JSON-safe shape
so search results, query correction and agents can see them instead of a log
line. Parsing of the Biopython payload lives in the NCBI infrastructure layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class TranslationEntry:
    """One automatic-term-mapping step: the text PubMed saw and what it ran."""

    source: str
    target: str


@dataclass(frozen=True, slots=True)
class PubMedQueryDiagnostics:
    """Structured ESearch diagnostics for one executed PubMed query."""

    query_translation: str | None = None
    translation_set: tuple[TranslationEntry, ...] = ()
    quoted_phrases_not_found: tuple[str, ...] = ()
    phrases_ignored: tuple[str, ...] = ()
    output_messages: tuple[str, ...] = ()
    phrases_not_found: tuple[str, ...] = ()
    fields_not_found: tuple[str, ...] = ()
    provider_error: str | None = None

    @property
    def has_issues(self) -> bool:
        """Whether PubMed dropped or failed to resolve part of the query.

        Output messages are informational ("No items found.") and do not count.
        """
        return bool(
            self.quoted_phrases_not_found
            or self.phrases_ignored
            or self.phrases_not_found
            or self.fields_not_found
            or self.provider_error
        )

    def issue_messages(self) -> list[str]:
        """Short human-readable warnings, one per reported issue."""
        messages = [
            f"PubMed did not find quoted phrase {phrase}; that clause matched nothing."
            for phrase in self.quoted_phrases_not_found
        ]
        messages.extend(
            f"PubMed did not find term {phrase!r}; that clause matched nothing." for phrase in self.phrases_not_found
        )
        messages.extend(f"PubMed does not recognize field tag [{field}]." for field in self.fields_not_found)
        messages.extend(f"PubMed ignored {phrase!r} (stopword)." for phrase in self.phrases_ignored)
        if self.provider_error:
            messages.append(f"PubMed reported an error: {self.provider_error}")
        return messages

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe form that mirrors NCBI's WarningList/ErrorList grouping."""
        return {
            "query_translation": self.query_translation,
            "translation_set": [{"from": item.source, "to": item.target} for item in self.translation_set],
            "warning_list": {
                "quoted_phrases_not_found": list(self.quoted_phrases_not_found),
                "phrases_ignored": list(self.phrases_ignored),
                "output_messages": list(self.output_messages),
            },
            "error_list": {
                "phrases_not_found": list(self.phrases_not_found),
                "fields_not_found": list(self.fields_not_found),
            },
            "provider_error": self.provider_error,
            "has_issues": self.has_issues,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PubMedQueryDiagnostics:
        """Rebuild diagnostics from :meth:`to_dict` output; unknown or malformed parts are dropped."""
        raw_warnings, raw_errors = data.get("warning_list"), data.get("error_list")
        warning_list: Mapping[str, Any] = raw_warnings if isinstance(raw_warnings, dict) else {}
        error_list: Mapping[str, Any] = raw_errors if isinstance(raw_errors, dict) else {}
        translation = data.get("query_translation")
        provider_error = data.get("provider_error")
        raw_set = data.get("translation_set")
        entries = tuple(
            TranslationEntry(str(item["from"]), str(item["to"]))
            for item in (raw_set if isinstance(raw_set, list) else [])
            if isinstance(item, dict) and "from" in item and "to" in item
        )
        return cls(
            query_translation=translation if isinstance(translation, str) else None,
            translation_set=entries,
            quoted_phrases_not_found=_strings(warning_list.get("quoted_phrases_not_found")),
            phrases_ignored=_strings(warning_list.get("phrases_ignored")),
            output_messages=_strings(warning_list.get("output_messages")),
            phrases_not_found=_strings(error_list.get("phrases_not_found")),
            fields_not_found=_strings(error_list.get("fields_not_found")),
            provider_error=provider_error if isinstance(provider_error, str) and provider_error else None,
        )


@dataclass(frozen=True, slots=True)
class QueryProbe:
    """A count-only PubMed ESearch and what PubMed said about the query."""

    query: str
    count: int
    diagnostics: PubMedQueryDiagnostics


def _strings(values: Iterable[Any] | None) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(str(value) for value in values if isinstance(value, str) and value.strip())


__all__ = ["PubMedQueryDiagnostics", "QueryProbe", "TranslationEntry"]
