"""Publication integrity: retractions, expressions of concern, errata and updates.

A record's integrity status is assembled from provider metadata that each
source already returns, so no extra request is needed:

* PubMed ``PublicationType`` (``Retracted Publication``, ``Expression of
  Concern`` ...), which marks the original article.
* PubMed ``CommentsCorrectionsList`` links (``RetractionIn``, ``ErratumIn``,
  ``ExpressionOfConcernIn``, ``UpdateIn`` ...), which name the notice PMID.
* OpenAlex ``is_retracted``.
* Crossref ``updated-by`` (Crossmark and Retraction Watch notices attached to
  the original DOI).

The status is a statement about indexing, not about scientific validity: a
``none_found`` result means no provider recorded a notice, never that the
article is sound. A notice record itself (an erratum or a retraction notice)
is reported as ``is_notice`` so it is not mistaken for the article it updates.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

INTEGRITY_SCHEMA_VERSION = 1

STATUS_RETRACTED = "retracted"
STATUS_PARTIALLY_RETRACTED = "partially_retracted"
STATUS_EXPRESSION_OF_CONCERN = "expression_of_concern"
STATUS_CORRECTED = "corrected"
STATUS_UPDATED = "updated"
STATUS_NONE_FOUND = "none_found"

#: Most severe first. The headline status is the most severe notice found.
STATUS_SEVERITY: tuple[str, ...] = (
    STATUS_RETRACTED,
    STATUS_PARTIALLY_RETRACTED,
    STATUS_EXPRESSION_OF_CONCERN,
    STATUS_CORRECTED,
    STATUS_UPDATED,
    STATUS_NONE_FOUND,
)

#: Statuses that should stop an agent from citing the work without comment.
CAUTION_STATUSES = frozenset({STATUS_RETRACTED, STATUS_PARTIALLY_RETRACTED, STATUS_EXPRESSION_OF_CONCERN})

# PubMed CommentsCorrections RefType -> status of the record carrying the link.
# Only links that point *from* the original article *to* a notice change the
# original's status. ``...Of``/``...For`` links mark the notice itself.
_PUBMED_INBOUND_REFTYPES: Mapping[str, str] = {
    "retractionin": STATUS_RETRACTED,
    "partialretractionin": STATUS_PARTIALLY_RETRACTED,
    "expressionofconcernin": STATUS_EXPRESSION_OF_CONCERN,
    "erratumin": STATUS_CORRECTED,
    "correctedandrepublishedin": STATUS_CORRECTED,
    "updatein": STATUS_UPDATED,
    "republishedin": STATUS_UPDATED,
}
_PUBMED_NOTICE_REFTYPES = frozenset(
    {
        "retractionof",
        "partialretractionof",
        "expressionofconcernfor",
        "erratumfor",
        "correctedandrepublishedfrom",
        "updateof",
        "republishedfrom",
    }
)

#: Every RefType the parser keeps; comments and reviews are not integrity links.
PUBMED_INTEGRITY_REFTYPES = frozenset(_PUBMED_INBOUND_REFTYPES) | _PUBMED_NOTICE_REFTYPES

_PUBMED_STATUS_TYPES: Mapping[str, str] = {
    "retracted publication": STATUS_RETRACTED,
    "expression of concern": STATUS_EXPRESSION_OF_CONCERN,
}
_PUBMED_NOTICE_TYPES = frozenset({"retraction of publication", "published erratum"})

# Crossref ``updated-by[].type`` (Crossmark / Retraction Watch vocabulary).
_CROSSREF_UPDATE_TYPES: Mapping[str, str] = {
    "retraction": STATUS_RETRACTED,
    "withdrawal": STATUS_RETRACTED,
    "removal": STATUS_RETRACTED,
    "partial_retraction": STATUS_PARTIALLY_RETRACTED,
    "expression_of_concern": STATUS_EXPRESSION_OF_CONCERN,
    "correction": STATUS_CORRECTED,
    "erratum": STATUS_CORRECTED,
    "corrigendum": STATUS_CORRECTED,
    "addendum": STATUS_UPDATED,
    "clarification": STATUS_UPDATED,
    "new_version": STATUS_UPDATED,
    "new_edition": STATUS_UPDATED,
}


@dataclass(frozen=True)
class IntegrityNotice:
    """One notice that changes how a work may be cited."""

    status: str
    source: str
    kind: str
    pmid: str | None = None
    doi: str | None = None
    citation: str | None = None
    date: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status, "source": self.source, "kind": self.kind}
        for key in ("pmid", "doi", "citation", "date"):
            value = getattr(self, key)
            if value:
                payload[key] = value
        return payload


@dataclass(frozen=True)
class PublicationIntegrity:
    """Integrity status of one work, with the notices that support it."""

    status: str = STATUS_NONE_FOUND
    notices: tuple[IntegrityNotice, ...] = ()
    is_notice: bool = False
    checked_sources: tuple[str, ...] = field(default_factory=tuple)

    @property
    def caution(self) -> bool:
        """Whether the work should not be cited without disclosing the notice."""
        return self.status in CAUTION_STATUSES

    @property
    def flagged(self) -> bool:
        """Whether anything worth showing was found."""
        return self.status != STATUS_NONE_FOUND or self.is_notice

    @property
    def badge(self) -> str | None:
        """Short Markdown-safe label, or ``None`` when nothing was found."""
        if self.status == STATUS_NONE_FOUND:
            return "[NOTICE RECORD]" if self.is_notice else None
        label = self.status.replace("_", " ").upper()
        pmids = [notice.pmid for notice in self.notices if notice.pmid and notice.status == self.status]
        if pmids:
            label += f": notice PMID {', '.join(dict.fromkeys(pmids))}"
        return f"[{label}]"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": INTEGRITY_SCHEMA_VERSION,
            "status": self.status,
            "caution": self.caution,
            "notices": [notice.to_dict() for notice in self.notices],
            "checked_sources": list(self.checked_sources),
        }
        if self.is_notice:
            payload["is_notice"] = True
        if self.status == STATUS_NONE_FOUND:
            payload["note"] = "No provider recorded a notice; this is not a validity judgement."
        return payload


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else str(value).strip() if value is not None else ""


def _pubmed_notices(raw: Mapping[str, Any]) -> tuple[list[IntegrityNotice], bool]:
    notices: list[IntegrityNotice] = []
    is_notice = False
    for publication_type in raw.get("publication_types") or ():
        key = _text(publication_type).casefold()
        if key in _PUBMED_STATUS_TYPES:
            notices.append(
                IntegrityNotice(status=_PUBMED_STATUS_TYPES[key], source="pubmed", kind=f"publication_type:{key}")
            )
        elif key in _PUBMED_NOTICE_TYPES:
            is_notice = True
    for link in raw.get("comments_corrections") or ():
        if not isinstance(link, Mapping):
            continue
        ref_type = _text(link.get("ref_type")).casefold()
        if ref_type in _PUBMED_NOTICE_REFTYPES:
            is_notice = True
            continue
        status = _PUBMED_INBOUND_REFTYPES.get(ref_type)
        if status is None:
            continue
        notices.append(
            IntegrityNotice(
                status=status,
                source="pubmed",
                kind=_text(link.get("ref_type")),
                pmid=_text(link.get("pmid")) or None,
                citation=_text(link.get("ref_source")) or None,
            )
        )
    # A notice record that is itself typed "Expression of Concern" is not an
    # expression of concern *about* itself.
    if is_notice:
        notices = [notice for notice in notices if not notice.kind.startswith("publication_type:")]
    # A linked notice (with its PMID) supersedes the bare publication type.
    linked_statuses = {notice.status for notice in notices if notice.pmid}
    notices = [
        notice
        for notice in notices
        if not (notice.kind.startswith("publication_type:") and notice.status in linked_statuses)
    ]
    return notices, is_notice


def _openalex_notices(raw: Mapping[str, Any]) -> list[IntegrityNotice]:
    if raw.get("is_retracted") is True:
        return [IntegrityNotice(status=STATUS_RETRACTED, source="openalex", kind="is_retracted")]
    return []


def _crossref_date(update: Mapping[str, Any]) -> str | None:
    updated = update.get("updated")
    if isinstance(updated, Mapping):
        parts = updated.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list):
            return "-".join(f"{int(part):02d}" if index else str(int(part)) for index, part in enumerate(parts[0]))
    return None


def _crossref_notices(raw: Mapping[str, Any]) -> tuple[list[IntegrityNotice], bool]:
    notices: list[IntegrityNotice] = []
    for update in raw.get("updated-by") or ():
        if not isinstance(update, Mapping):
            continue
        kind = _text(update.get("type")).casefold().replace("-", "_").replace(" ", "_")
        status = _CROSSREF_UPDATE_TYPES.get(kind)
        if status is None:
            continue
        notices.append(
            IntegrityNotice(
                status=status,
                source=f"crossref:{_text(update.get('source')) or 'publisher'}",
                kind=kind,
                doi=_text(update.get("DOI")) or None,
                date=_crossref_date(update),
            )
        )
    is_notice = any(isinstance(item, Mapping) for item in raw.get("update-to") or ())
    return notices, is_notice


def assess_integrity(records: Iterable[tuple[str, Mapping[str, Any]]]) -> PublicationIntegrity:
    """Combine per-source raw records into one integrity status.

    Args:
        records: ``(source_name, raw_record)`` pairs, e.g. from
            ``UnifiedArticle.sources``.
    """
    notices: list[IntegrityNotice] = []
    checked: list[str] = []
    is_notice = False
    for source, raw in records:
        if not isinstance(raw, Mapping):
            continue
        if source == "pubmed" or "comments_corrections" in raw:
            found, notice_record = _pubmed_notices(raw)
            notices.extend(found)
            is_notice = is_notice or notice_record
            if "comments_corrections" in raw:
                checked.append("pubmed")
        elif source == "openalex":
            notices.extend(_openalex_notices(raw))
            if "is_retracted" in raw:
                checked.append("openalex")
        elif source == "crossref":
            found, notice_record = _crossref_notices(raw)
            notices.extend(found)
            is_notice = is_notice or notice_record
            checked.append("crossref")
    unique = tuple(dict.fromkeys(notices))
    status = next(
        (candidate for candidate in STATUS_SEVERITY if any(notice.status == candidate for notice in unique)),
        STATUS_NONE_FOUND,
    )
    return PublicationIntegrity(
        status=status,
        notices=unique,
        is_notice=is_notice,
        checked_sources=tuple(dict.fromkeys(checked)),
    )
