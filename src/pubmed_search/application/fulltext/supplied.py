"""Fulltext supplied by the host agent or the user, kept in the tenant fulltext store.

Design:
    The server cannot always read an article itself: a publisher may forbid
    XML reuse, the copy may sit behind the user's own institutional session,
    or the user may simply have the PDF. A host agent (with its own web or
    browser tools) or the user can then hand the text to the server once,
    with provenance, and later ``get_fulltext`` reads reuse it.

    Supplied text is never presented as provider-verified fulltext. Every
    record carries its origin (``agent_supplied`` or ``user_supplied``), how and
    when it was obtained, the URL or file it came from, and any license the
    supplier declared. The server does not check that the text matches the
    article; that is stated wherever the text is returned.

Storage:
    One directory per tenant storage root (the tenant's session data
    directory). Each record is one JSON file named by an opaque id; each
    identifier (PMID, PMCID, DOI) points to the newest record through a small
    pointer file named by a digest of the identifier. Writes are atomic per
    file and there is no shared index, so concurrent writers cannot corrupt
    each other's entries; the newest registration for an identifier wins.
    The store is bounded: the oldest records beyond ``max_records`` are
    removed, and a pointer to a removed record reads as a miss.

Maintenance:
    This module performs local file I/O only. It never imports
    infrastructure and never reads environment variables; roots and limits
    are injected by the presentation layer.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pubmed_search.domain.value_objects.article_identifiers import (
    IdentifierValidationError,
    normalize_doi,
    normalize_pmcid,
    normalize_pmid,
)
from pubmed_search.shared.file_io import atomic_write_json, atomic_write_text

logger = logging.getLogger(__name__)

SuppliedOrigin = Literal["agent_supplied", "user_supplied"]
RetrievalMethod = Literal[
    "host_fetch",
    "host_browser",
    "user_upload",
    "zotero_attachment",
    "asset_aware_ingest",
    "manual_entry",
    "other",
]
ContentFormat = Literal["text", "markdown", "jats", "html", "pdf"]
IdentifierKind = Literal["pmid", "pmcid", "doi"]

RETRIEVAL_METHODS: tuple[str, ...] = (
    "host_fetch",
    "host_browser",
    "user_upload",
    "zotero_attachment",
    "asset_aware_ingest",
    "manual_entry",
    "other",
)
SUPPLIED_RECORD_SCHEMA = "supplied-fulltext/v1"
DEFAULT_MAX_SUPPLIED_RECORDS = 500
DEFAULT_MAX_SUPPLIED_BYTES = 256 * 1024 * 1024
MAX_SUPPLIED_TEXT_CHARS = 2_000_000
_RECORD_ID_RE = re.compile(r"^sft-[0-9a-f]{32}$")
_MAX_URL_CHARS = 2_048
_MAX_LABEL_CHARS = 500
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Host-agent clocks may run slightly ahead of the server.
_FUTURE_TOLERANCE = timedelta(minutes=10)
# Windows refuses os.replace/unlink while another handle has the file open.
_RETRY_DELAYS: tuple[float, ...] = (0.05, 0.1, 0.2, 0.4)
_SECRET_QUERY_RE = re.compile(
    r"(token|sig|signature|secret|password|passwd|pass|auth|session|sid|key|apikey|api_key|credential"
    r"|policy|expires|x-amz-.*|x-goog-.*)",
    re.IGNORECASE,
)


def _redact_url(url: str) -> str:
    """Drop credentials, fragments and secret-looking query values from a stored URL."""
    try:
        parts = urlsplit(url)
    except ValueError:
        raise SuppliedFulltextError("invalid_provenance", "source_url must be an http(s) URL") from None
    host = parts.hostname or ""
    netloc = f"[{host}]" if ":" in host else host
    try:
        port = parts.port
    except ValueError:
        raise SuppliedFulltextError("invalid_provenance", "source_url must be an http(s) URL") from None
    if port:
        netloc = f"{netloc}:{port}"
    query = urlencode(
        [
            (name, "REDACTED" if _SECRET_QUERY_RE.fullmatch(name) else value)
            for name, value in parse_qsl(parts.query, keep_blank_values=True)
        ]
    )
    return urlunsplit((parts.scheme, netloc, parts.path, query, ""))


class SuppliedFulltextError(ValueError):
    """A supplied-fulltext request or record violates the intake contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _clean_label(value: object, *, name: str, max_chars: int = _MAX_LABEL_CHARS) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SuppliedFulltextError("invalid_provenance", f"{name} must be a string")
    cleaned = " ".join(_CONTROL_RE.sub(" ", value).split())
    if len(cleaned) > max_chars:
        raise SuppliedFulltextError("invalid_provenance", f"{name} must be at most {max_chars} characters")
    return cleaned or None


def _parse_timestamp(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SuppliedFulltextError("invalid_provenance", "retrieved_at must be an ISO-8601 date or date-time")
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise SuppliedFulltextError(
            "invalid_provenance", "retrieved_at must be an ISO-8601 date or date-time"
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed.astimezone(timezone.utc) > datetime.now(tz=timezone.utc) + _FUTURE_TOLERANCE:
        raise SuppliedFulltextError("invalid_provenance", "retrieved_at cannot be in the future")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SuppliedFulltextProvenance:
    """Where supplied text came from; at least a URL or a file is required."""

    retrieval_method: RetrievalMethod
    retrieved_at: str
    source_url: str | None = None
    source_file: str | None = None
    license: str | None = None
    note: str | None = None

    @classmethod
    def create(
        cls,
        *,
        retrieval_method: object,
        retrieved_at: object,
        source_url: object = None,
        source_file: object = None,
        license: object = None,  # noqa: A002 - public field name
        note: object = None,
    ) -> SuppliedFulltextProvenance:
        """Validate and normalize provenance supplied with a registration."""
        if retrieval_method not in RETRIEVAL_METHODS:
            raise SuppliedFulltextError(
                "invalid_provenance", f"retrieval_method must be one of: {', '.join(RETRIEVAL_METHODS)}"
            )
        url = _clean_label(source_url, name="source_url", max_chars=_MAX_URL_CHARS)
        if url is not None and not re.match(r"^https?://[^\s/]+", url, flags=re.IGNORECASE):
            raise SuppliedFulltextError("invalid_provenance", "source_url must be an http(s) URL")
        if url is not None:
            url = _redact_url(url)
        file_label = _clean_label(source_file, name="source_file")
        if url is None and file_label is None:
            raise SuppliedFulltextError(
                "invalid_provenance", "provenance requires source_url or a file (file_path or source_file)"
            )
        return cls(
            retrieval_method=retrieval_method,  # type: ignore[arg-type]
            retrieved_at=_parse_timestamp(retrieved_at),
            source_url=url,
            source_file=file_label,
            license=_clean_label(license, name="license"),
            note=_clean_label(note, name="note"),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "retrieval_method": self.retrieval_method,
            "retrieved_at": self.retrieved_at,
            "source_url": self.source_url,
            "source_file": self.source_file,
            "license": self.license,
            "note": self.note,
        }
        return {key: value for key, value in payload.items() if value is not None}


def normalize_identifier(kind: str, value: str) -> tuple[IdentifierKind, str]:
    """Return a canonical ``(kind, value)`` pair or raise ``SuppliedFulltextError``."""
    try:
        if kind == "pmid":
            return "pmid", normalize_pmid(value)
        if kind == "pmcid":
            return "pmcid", normalize_pmcid(value)
        if kind == "doi":
            return "doi", normalize_doi(value)
    except IdentifierValidationError as exc:
        raise SuppliedFulltextError("invalid_identifier", str(exc)) from None
    raise SuppliedFulltextError("invalid_identifier", "identifier kind must be pmid, pmcid or doi")


@dataclass(frozen=True)
class SuppliedFulltextRecord:
    """One registered body of article text with its provenance."""

    record_id: str
    origin: SuppliedOrigin
    identifiers: dict[str, str]
    provenance: SuppliedFulltextProvenance
    content_format: ContentFormat
    sections: tuple[dict[str, str], ...]
    registered_at: str
    content_sha256: str
    title: str = ""
    abstract: str = ""
    truncated: bool = False
    artifact_uri: str | None = None
    hints: tuple[str, ...] = field(default_factory=tuple)

    @property
    def char_count(self) -> int:
        return sum(len(section.get("content", "")) for section in self.sections)

    @property
    def has_body(self) -> bool:
        """Whether the record holds body sections (not only a title or abstract)."""
        return any(section.get("content", "").strip() for section in self.sections)

    def as_parsed_document(self) -> dict[str, Any]:
        """Project onto the shared fulltext section model used by structured sources.

        A license the supplier declared is provenance of the copy, not the
        article's license, so it stays in :meth:`retrieval_summary` only.
        """
        return {
            "title": self.title,
            "abstract": self.abstract,
            "sections": [dict(section) for section in self.sections],
            "references": [],
            "figures": [],
            "license": None,
        }

    def note_summary(self) -> dict[str, Any]:
        """Short description of a registration that was not served as the body."""
        return {
            "origin": self.origin,
            "record_id": self.record_id,
            "registered_at": self.registered_at,
            "has_body": self.has_body,
            "provider_verified": False,
            **{key: value for key, value in self.provenance.to_dict().items() if key != "note"},
        }

    def retrieval_summary(self) -> dict[str, Any]:
        """Provenance block exposed wherever this text is returned."""
        summary: dict[str, Any] = {
            "source": self.origin,
            "record_id": self.record_id,
            "registered_at": self.registered_at,
            "content_format": self.content_format,
            "content_sha256": self.content_sha256,
            "provider_verified": False,
            "verification_note": (
                "Registered by the host agent or user; the server did not retrieve or verify this text "
                "against a provider copy."
            ),
            **self.provenance.to_dict(),
        }
        if self.artifact_uri:
            summary["artifact_uri"] = self.artifact_uri
        if self.truncated:
            summary["truncated"] = True
        if self.hints:
            summary["hints"] = list(self.hints)
        return summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SUPPLIED_RECORD_SCHEMA,
            "record_id": self.record_id,
            "origin": self.origin,
            "identifiers": dict(self.identifiers),
            "provenance": self.provenance.to_dict(),
            "content_format": self.content_format,
            "title": self.title,
            "abstract": self.abstract,
            "sections": [dict(section) for section in self.sections],
            "registered_at": self.registered_at,
            "content_sha256": self.content_sha256,
            "truncated": self.truncated,
            "artifact_uri": self.artifact_uri,
            "hints": list(self.hints),
        }

    @classmethod
    def from_dict(cls, payload: Any) -> SuppliedFulltextRecord:
        """Load a stored record; anything malformed is rejected, never repaired."""
        if not isinstance(payload, dict) or payload.get("schema") != SUPPLIED_RECORD_SCHEMA:
            raise SuppliedFulltextError("invalid_record", "stored supplied-fulltext record has an unknown schema")
        record_id = payload.get("record_id")
        origin = payload.get("origin")
        identifiers = payload.get("identifiers")
        sections = payload.get("sections")
        provenance = payload.get("provenance")
        if (
            not isinstance(record_id, str)
            or _RECORD_ID_RE.fullmatch(record_id) is None
            or origin not in {"agent_supplied", "user_supplied"}
            or not isinstance(identifiers, dict)
            or not isinstance(sections, list)
            or not isinstance(provenance, dict)
        ):
            raise SuppliedFulltextError("invalid_record", "stored supplied-fulltext record is malformed")
        clean_sections = tuple(
            {"title": str(section.get("title") or ""), "content": str(section.get("content") or "")}
            for section in sections
            if isinstance(section, dict)
        )
        return cls(
            record_id=record_id,
            origin=origin,
            identifiers={str(key): str(value) for key, value in identifiers.items()},
            provenance=SuppliedFulltextProvenance(
                retrieval_method=provenance.get("retrieval_method", "other"),
                retrieved_at=str(provenance.get("retrieved_at") or ""),
                source_url=provenance.get("source_url"),
                source_file=provenance.get("source_file"),
                license=provenance.get("license"),
                note=provenance.get("note"),
            ),
            content_format=payload.get("content_format", "text"),
            sections=clean_sections,
            registered_at=str(payload.get("registered_at") or ""),
            content_sha256=str(payload.get("content_sha256") or ""),
            title=str(payload.get("title") or ""),
            abstract=str(payload.get("abstract") or ""),
            truncated=bool(payload.get("truncated")),
            artifact_uri=payload.get("artifact_uri") if isinstance(payload.get("artifact_uri"), str) else None,
            hints=tuple(str(hint) for hint in payload.get("hints") or () if isinstance(hint, str)),
        )


_ID_CLOCK_LOCK = threading.Lock()
_last_id_ns = 0


def new_record_id() -> str:
    """Return an opaque id whose hex prefix sorts by creation order (newest wins, oldest evicted).

    The time prefix is strictly increasing within the process even when the
    wall clock is coarse (Windows) or two registrations share a tick.
    """
    global _last_id_ns
    with _ID_CLOCK_LOCK:
        _last_id_ns = max(time.time_ns(), _last_id_ns + 1)
        stamp = _last_id_ns
    return f"sft-{stamp:016x}{uuid.uuid4().hex[:16]}"


def content_digest(sections: tuple[dict[str, str], ...], abstract: str) -> str:
    digest = hashlib.sha256()
    digest.update(abstract.encode("utf-8"))
    for section in sections:
        digest.update(b"\x1e")
        digest.update(section.get("title", "").encode("utf-8"))
        digest.update(b"\x1f")
        digest.update(section.get("content", "").encode("utf-8"))
    return digest.hexdigest()


_ROOT_LOCKS: dict[str, threading.RLock] = {}
_ROOT_LOCKS_GUARD = threading.Lock()


def _root_lock(root: Path) -> threading.RLock:
    key = os.path.normcase(str(root.resolve()))
    with _ROOT_LOCKS_GUARD:
        lock = _ROOT_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _ROOT_LOCKS[key] = lock
        return lock


def _retrying(operation: Any, *args: Any) -> None:
    """Run a file replace/unlink, retrying Windows sharing violations with backoff."""
    for delay in (*_RETRY_DELAYS, None):
        try:
            operation(*args)
            return
        except PermissionError:
            if delay is None:
                raise
            time.sleep(delay)


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)


class SuppliedFulltextStore:
    """Durable, bounded store of supplied fulltext for one tenant storage root."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_records: int = DEFAULT_MAX_SUPPLIED_RECORDS,
        max_bytes: int = DEFAULT_MAX_SUPPLIED_BYTES,
    ) -> None:
        for name, limit in (("max_records", max_records), ("max_bytes", max_bytes)):
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                raise ValueError(f"{name} must be a positive integer")
        self._root = Path(root)
        self._records = self._root / "records"
        self._pointers = self._root / "by_identifier"
        self._max_records = max_records
        self._max_bytes = max_bytes

    @property
    def root(self) -> Path:
        return self._root

    @staticmethod
    def _pointer_name(kind: str, value: str) -> str:
        return hashlib.sha256(f"{kind}:{value}".encode()).hexdigest()[:40] + ".json"

    def _record_path(self, record_id: str) -> Path:
        if _RECORD_ID_RE.fullmatch(record_id) is None:
            raise SuppliedFulltextError("invalid_record", "unsafe supplied-fulltext record id")
        return self._records / f"{record_id}.json"

    def related_identifiers(self, identifiers: dict[str, str]) -> dict[str, str]:
        """Identifiers known for the same article: the given ones plus those of earlier registrations.

        A value given for a kind always wins over an older record's value.
        """
        with _root_lock(self._root):
            merged = dict(identifiers)
            for kind, value in list(identifiers.items()):
                record = self._record_for(kind, value)
                if record is not None:
                    for other_kind, other_value in record.identifiers.items():
                        merged.setdefault(other_kind, other_value)
            return merged

    def save(self, record: SuppliedFulltextRecord) -> SuppliedFulltextRecord:
        """Persist one record as the newest text for every identifier of its article.

        The record's identifiers are merged with those of earlier
        registrations for the same article, and every one of them is pointed
        at the new record, so a correction made under one identifier is
        served under all of them. If any write fails, already-moved pointers
        are restored and the new record is removed.

        Returns:
            The stored record (with the merged identifiers).

        Raises:
            OSError: The store could not be written; its previous state is kept.
        """
        with _root_lock(self._root):
            record = replace(record, identifiers=self.related_identifiers(record.identifiers))
            record_path = self._record_path(record.record_id)
            previous: dict[Path, str | None] = {}
            try:
                _retrying(atomic_write_json, record_path, record.to_dict())
                for kind, value in record.identifiers.items():
                    pointer = self._pointers / self._pointer_name(kind, value)
                    previous[pointer] = self._read_text(pointer)
                    _retrying(atomic_write_json, pointer, {"kind": kind, "value": value, "record_id": record.record_id})
            except OSError:
                self._rollback(previous, record_path)
                raise
            self._enforce_bound(keep=record.record_id)
            return record

    def _rollback(self, previous: dict[Path, str | None], record_path: Path) -> None:
        for pointer, text in previous.items():
            try:
                if text is None:
                    _retrying(_unlink, pointer)
                else:
                    _retrying(atomic_write_text, pointer, text)
            except OSError:
                logger.warning("Could not restore a supplied-fulltext pointer after a failed save")
        try:
            _retrying(_unlink, record_path)
        except OSError:
            logger.warning("Could not remove a partially saved supplied-fulltext record")

    @staticmethod
    def _read_text(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def _record_for(self, kind: str, value: str) -> SuppliedFulltextRecord | None:
        pointer = self._pointers / self._pointer_name(kind, value)
        try:
            payload = json.loads(pointer.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            logger.warning("Ignoring an unreadable supplied-fulltext pointer")
            return None
        record_id = payload.get("record_id") if isinstance(payload, dict) else None
        if not isinstance(record_id, str) or payload.get("kind") != kind or payload.get("value") != value:
            return None
        record = self.load(record_id)
        if record is None or record.identifiers.get(kind) != value:
            return None
        return record

    def find(self, identifiers: list[tuple[str, str]]) -> SuppliedFulltextRecord | None:
        """Return the newest record for the article behind any of the given identifiers.

        Records found directly are expanded once through their own
        identifiers, so a newer registration made under another identifier of
        the same article is preferred.
        """
        with _root_lock(self._root):
            found: dict[str, SuppliedFulltextRecord] = {}
            for kind, value in identifiers:
                record = self._record_for(kind, value)
                if record is not None:
                    found[record.record_id] = record
            for record in list(found.values()):
                for kind, value in record.identifiers.items():
                    related = self._record_for(kind, value)
                    if related is not None:
                        found.setdefault(related.record_id, related)
            if not found:
                return None
            return found[max(found)]

    def load(self, record_id: str) -> SuppliedFulltextRecord | None:
        try:
            path = self._record_path(record_id)
            return SuppliedFulltextRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            logger.warning("Ignoring an unreadable supplied-fulltext record")
            return None

    def _enforce_bound(self, *, keep: str) -> None:
        """Evict the oldest records beyond the count and byte quotas, then drop their pointers."""
        try:
            records = sorted(self._records.glob("sft-*.json"), key=lambda path: path.name)
            sizes = {path: path.stat().st_size for path in records}
        except OSError:
            return
        total = sum(sizes.values())
        evicted = False
        for stale in records:
            if len(records) <= self._max_records and total <= self._max_bytes:
                break
            if stale.stem == keep:
                continue
            try:
                _retrying(_unlink, stale)
            except OSError:
                logger.warning("Could not remove an old supplied-fulltext record")
                continue
            records = [path for path in records if path != stale]
            total -= sizes[stale]
            evicted = True
        if evicted:
            self._drop_dangling_pointers()

    def _drop_dangling_pointers(self) -> None:
        try:
            pointers = list(self._pointers.glob("*.json"))
        except OSError:
            return
        for pointer in pointers:
            try:
                payload = json.loads(pointer.read_text(encoding="utf-8"))
                record_id = payload.get("record_id") if isinstance(payload, dict) else None
                dangling = not isinstance(record_id, str) or not self._record_path(record_id).exists()
            except (OSError, ValueError):
                dangling = True
            if dangling:
                try:
                    _retrying(_unlink, pointer)
                except OSError:
                    logger.warning("Could not remove a stale supplied-fulltext pointer")


__all__ = [
    "DEFAULT_MAX_SUPPLIED_BYTES",
    "DEFAULT_MAX_SUPPLIED_RECORDS",
    "MAX_SUPPLIED_TEXT_CHARS",
    "RETRIEVAL_METHODS",
    "ContentFormat",
    "RetrievalMethod",
    "SuppliedFulltextError",
    "SuppliedFulltextProvenance",
    "SuppliedFulltextRecord",
    "SuppliedFulltextStore",
    "SuppliedOrigin",
    "content_digest",
    "new_record_id",
    "normalize_identifier",
]
