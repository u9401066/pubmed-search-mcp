"""Intake of fulltext obtained by the host agent or the user.

Design:
    ``register_fulltext`` accepts article text the server could not obtain
    itself: a page the host agent read with its own web tool, text from the
    user's institutional browser session, or a PDF/Markdown/JATS/HTML file the
    user owns. This service validates the request, reads an allowed local file
    with a hard byte budget, turns the content into the shared section model,
    and stores it as ``agent_supplied`` or ``user_supplied`` text in the
    tenant's fulltext store.

Safety:
    - Provenance is mandatory: retrieval method, retrieval time, and a source
      URL or file. A declared license is kept verbatim; none is inferred.
      Credentials and signed query values are removed from the source URL.
    - Local files are read only when the caller may use server paths at all,
      only from configured roots (workspace, notes directory, the tenant's
      fulltext intake folder, explicit intake roots). Network, device and
      drive-relative paths are refused by string inspection, and the path must
      lie lexically under a root, before the operating system is asked about
      it; ``..`` components are refused; symlinks are resolved and re-checked;
      the file is opened once and its identity, type and size are checked on
      the open handle.
    - Parsing is linear-time and bounded (characters, headings/sections, HTML
      elements and nesting depth); a breach fails with ``invalid_input``.
      Parsing and all file and store I/O run off the event loop.
    - A document that declares another article (PMC page canonical/citation
      ids, JATS ``<article-id>``) than the requested identifier is refused.
    - Supplied text is never labelled as provider-verified.

Maintenance:
    JATS, HTML and PDF parsing live in infrastructure and are injected through
    :class:`FulltextContentParser`; this module stays free of infrastructure
    imports and environment reads.
"""

from __future__ import annotations

import asyncio
import os
import re
import stat
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePath, PureWindowsPath
from typing import TYPE_CHECKING, Any, Literal, Protocol

from .supplied import (
    MAX_SUPPLIED_TEXT_CHARS,
    ContentFormat,
    SuppliedFulltextError,
    SuppliedFulltextProvenance,
    SuppliedFulltextRecord,
    SuppliedFulltextStore,
    content_digest,
    new_record_id,
    normalize_identifier,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

InlineContentFormat = Literal["text", "markdown", "jats", "html"]
SuppliedBy = Literal["agent", "user"]

_FILE_FORMATS: dict[str, ContentFormat] = {
    ".pdf": "pdf",
    ".txt": "text",
    ".text": "text",
    ".md": "markdown",
    ".markdown": "markdown",
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
    ".xml": "jats",
    ".nxml": "jats",
}
# Linear: one greedy run of blanks, then a non-blank; long lines are never headings.
_MARKDOWN_HEADING_RE = re.compile(r"(#{1,6})[ \t]+(\S.*)")
_MAX_HEADING_LINE_CHARS = 300
_NUMBERED_HEADING_RE = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[IVX]+\.)\s+")
_PLAIN_HEADINGS = frozenset(
    {
        "abstract",
        "summary",
        "key points",
        "background",
        "introduction",
        "methods",
        "method",
        "materials and methods",
        "patients and methods",
        "study design",
        "results",
        "findings",
        "discussion",
        "limitations",
        "conclusion",
        "conclusions",
        "references",
        "acknowledgments",
        "acknowledgements",
    }
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DRIVE_RE = re.compile(r"[A-Za-z]:")
_MAX_TITLE_CHARS = 500
_MAX_SECTION_TITLE_CHARS = 300
MAX_PARSE_TEXT_CHARS = 8_000_000
MAX_PARSED_SECTIONS = 5_000
_PDF_SIGNATURE_WINDOW = 1_024
_PDF_HINT = (
    "This text was extracted from a PDF without page or line locators. For citation-ready evidence spans, "
    "ingest the same PDF with asset-aware-mcp (ingest_documents / parse_pdf_structure) when that server is available."
)
_HOST_FETCH_HINT = (
    "Text came from the host agent's fetch; confirm it is the verbatim article text and not a model summary "
    "before quoting it."
)
_NO_BODY_HINT = (
    "The supplied text has no body sections (for example only an abstract); get_fulltext keeps querying "
    "providers and shows this registration as a note."
)


class FulltextContentParser(Protocol):
    """Format adapters supplied by infrastructure.

    Parse methods return the shared section model; they may add the declared
    article identifiers (``article_ids`` for JATS, or ``pmcid``/``pmid``/``doi``
    for HTML). A size, element or depth breach must raise
    ``SuppliedFulltextError("invalid_input", ...)``.
    """

    def parse_jats(self, xml: str) -> dict[str, Any]: ...

    def parse_html(self, html: str) -> dict[str, Any]: ...

    async def extract_pdf_text(self, data: bytes) -> str | None: ...


@dataclass(frozen=True)
class IntakeLimits:
    """Hard bounds for one registration."""

    max_inline_chars: int = 1_000_000
    max_text_file_bytes: int = 8 * 1024 * 1024
    max_pdf_file_bytes: int = 50 * 1024 * 1024
    max_stored_chars: int = MAX_SUPPLIED_TEXT_CHARS
    max_sections: int = 400
    parse_seconds: float = 30.0


def _refuse(message: str) -> SuppliedFulltextError:
    return SuppliedFulltextError("file_not_allowed", message)


def _lexically_under(candidate: str, roots: tuple[str, ...]) -> bool:
    """Containment on the normalized path text only; the filesystem is not consulted.

    ``abspath``/``normcase`` are lexical on purpose: ``Path.resolve()`` would ask
    the operating system, which for a share path opens a network connection.
    """
    target = os.path.normcase(os.path.abspath(candidate))  # noqa: PTH100
    for root in roots:
        base = os.path.normcase(os.path.abspath(root)).rstrip("\\/")  # noqa: PTH100
        if target == base or target.startswith(base + os.sep):
            return True
    return False


@dataclass(frozen=True)
class IntakePathPolicy:
    """Which local files a caller may hand to the server.

    ``allow_files`` is ``False`` for remote authenticated service callers: a
    path names a file on the *server*, which such callers must never read.
    """

    roots: tuple[Path, ...] = ()
    allow_files: bool = True

    def resolve(self, raw: str) -> Path:
        """Return the real path of an allowed regular file, or raise.

        The string is inspected first: network shares (``\\\\host\\share``,
        ``//host/share``), Windows device and extended-length prefixes
        (``\\\\.\\``, ``\\\\?\\``), drive-relative paths (``C:file``) and ``..``
        components are refused, and the path must lie lexically under a
        configured root, all before any filesystem call. Only then is it
        resolved (following symlinks) and checked again.
        """
        if not self.allow_files:
            raise _refuse("Remote service callers cannot register server files; send the text as content instead.")
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 4_096 or _CONTROL_RE.search(raw):
            raise _refuse("file_path must be a non-empty path without control characters")
        text = raw.strip()
        if text.startswith(("\\\\", "//", "\\/", "/\\")):
            raise _refuse("Network, device and extended-length paths are not allowed")
        windows = PureWindowsPath(text)
        if windows.drive and (not _DRIVE_RE.fullmatch(windows.drive) or not windows.root):
            raise _refuse("Only absolute paths on a local drive, or paths relative to the workspace, are allowed")
        if ".." in PurePath(text).parts or ".." in windows.parts:
            raise _refuse("file_path must not contain '..' components")
        if not self.roots:
            raise _refuse(
                "No intake directory is configured. Set PUBMED_WORKSPACE_DIR or PUBMED_FULLTEXT_INTAKE_ROOTS, "
                "or send the text as content."
            )
        lexical_roots = tuple(str(root.expanduser()) for root in self.roots)
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            candidate = Path(lexical_roots[0]) / candidate
        resolved_roots = tuple(root.expanduser().resolve() for root in self.roots)
        if not _lexically_under(str(candidate), lexical_roots + tuple(str(root) for root in resolved_roots)):
            raise _refuse(
                "file_path is outside the allowed intake directories (workspace, notes, tenant fulltext intake "
                "folder, PUBMED_FULLTEXT_INTAKE_ROOTS)"
            )
        try:
            resolved = candidate.resolve(strict=True)
        except (FileNotFoundError, NotADirectoryError):
            raise SuppliedFulltextError("file_not_found", "file_path does not exist") from None
        except (OSError, RuntimeError):
            raise SuppliedFulltextError("file_not_found", "file_path could not be resolved") from None
        if not any(resolved == root or resolved.is_relative_to(root) for root in resolved_roots):
            raise _refuse(
                "file_path resolves outside the allowed intake directories (workspace, notes, tenant fulltext "
                "intake folder, PUBMED_FULLTEXT_INTAKE_ROOTS)"
            )
        if not resolved.is_file():
            raise _refuse("file_path must name a regular file")
        if resolved.suffix.lower() not in _FILE_FORMATS:
            raise SuppliedFulltextError(
                "unsupported_file_type", f"file type must be one of: {', '.join(sorted(_FILE_FORMATS))}"
            )
        return resolved


def read_checked_file(path: Path, expected: os.stat_result, *, limit: int) -> bytes:
    """Open ``path`` once and read it only if it is still the file that was checked.

    The open handle must be a regular file with the identity (device and
    inode/file index) recorded when the path was checked, and at most
    ``limit`` bytes long, so a component swapped for a link, FIFO or another
    file between the check and the open is refused.
    """
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise SuppliedFulltextError("file_not_found", "file_path could not be opened") from None
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise _refuse("file_path must name a regular file")
        same_identity = (opened.st_dev, opened.st_ino) == (expected.st_dev, expected.st_ino)
        if expected.st_ino and opened.st_ino and not same_identity:
            raise _refuse("file_path changed while it was being checked")
        if opened.st_size > limit:
            raise SuppliedFulltextError("file_too_large", f"file must be at most {limit} bytes")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    except OSError:
        raise SuppliedFulltextError("file_not_found", "file_path could not be read") from None
    finally:
        os.close(descriptor)
    data = b"".join(chunks)
    if len(data) > limit:
        raise SuppliedFulltextError("file_too_large", f"file must be at most {limit} bytes")
    return data


@dataclass(frozen=True)
class FulltextIntakeRequest:
    """One registration as received from the tool layer."""

    identifier_kind: str
    identifier_value: str
    provenance: dict[str, Any]
    supplied_by: SuppliedBy = "agent"
    content: str | None = None
    content_format: InlineContentFormat = "markdown"
    file_path: str | None = None
    title: str | None = None
    aliases: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class FulltextIntakeResult:
    record: SuppliedFulltextRecord
    source_bytes: int
    file_name: str | None = None


def _clean_text(value: str) -> str:
    text = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    return _CONTROL_RE.sub("", text)


def _clean_title(value: object, max_chars: int = _MAX_TITLE_CHARS) -> str:
    return " ".join(str(value or "").split())[:max_chars]


def _invalid_input(message: str) -> SuppliedFulltextError:
    return SuppliedFulltextError("invalid_input", message)


def _markdown_heading(line: str) -> tuple[int, str] | None:
    if len(line) > _MAX_HEADING_LINE_CHARS or not line.startswith("#"):
        return None
    match = _MARKDOWN_HEADING_RE.match(line)
    if match is None:
        return None
    text = match.group(2).strip().rstrip("#").strip().strip("*_ ")
    return len(match.group(1)), text


def _plain_heading(line: str) -> str | None:
    if len(line) > _MAX_HEADING_LINE_CHARS:
        return None
    stripped = line.strip().rstrip(":").strip()
    if not stripped or len(stripped) > 60:
        return None
    candidate = _NUMBERED_HEADING_RE.sub("", stripped).strip()
    if candidate.lower() in _PLAIN_HEADINGS:
        return candidate.title() if candidate.isupper() else candidate
    return None


def split_text_sections(text: str) -> dict[str, Any]:
    """Split Markdown or plain text at headings into the shared section model.

    Markdown headings (``#`` .. ``######``) and stand-alone conventional
    article headings ("Methods", "2. Results", "DISCUSSION") start sections.
    A leading level-1 heading becomes the title; an "Abstract" section
    becomes the abstract. Text before the first heading is "Body".

    Runs in linear time: lines longer than 300 characters are never headings.

    Raises:
        SuppliedFulltextError: ``invalid_input`` when the text exceeds
            ``MAX_PARSE_TEXT_CHARS`` or yields more than ``MAX_PARSED_SECTIONS``.
    """
    if len(text) > MAX_PARSE_TEXT_CHARS:
        raise _invalid_input(f"text must be at most {MAX_PARSE_TEXT_CHARS} characters")
    title = ""
    abstract_parts: list[str] = []
    sections: list[dict[str, str]] = []
    current_title = "Body"
    buffer: list[str] = []

    def flush() -> None:
        content = "\n".join(buffer).strip()
        content = re.sub(r"\n{3,}", "\n\n", content)
        if content:
            if current_title.strip().lower() in {"abstract", "summary"}:
                abstract_parts.append(content)
            else:
                if len(sections) >= MAX_PARSED_SECTIONS:
                    raise _invalid_input(f"text has more than {MAX_PARSED_SECTIONS} sections")
                sections.append({"title": current_title, "content": content})
        buffer.clear()

    for line in text.split("\n"):
        markdown = _markdown_heading(line)
        if markdown is not None:
            level, heading_text = markdown
            heading = _clean_title(heading_text, _MAX_SECTION_TITLE_CHARS)
            if level == 1 and not title and not sections and not "".join(buffer).strip():
                title = heading
                continue
            flush()
            current_title = heading or "Body"
            continue
        plain = _plain_heading(line)
        if plain is not None:
            flush()
            current_title = plain
            continue
        buffer.append(line.rstrip())
    flush()
    return {"title": title, "abstract": "\n\n".join(abstract_parts), "sections": sections}


def _declared_identifiers(parsed: dict[str, Any]) -> dict[str, str]:
    """Identifiers a parsed document declares about itself, normalized."""
    raw: dict[str, Any] = {}
    article_ids = parsed.get("article_ids")
    if isinstance(article_ids, dict):
        raw.update(article_ids)
    for kind in ("pmid", "pmcid", "doi"):
        if parsed.get(kind) and kind not in raw:
            raw[kind] = parsed[kind]
    declared: dict[str, str] = {}
    for kind, value in raw.items():
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            normalized_kind, normalized_value = normalize_identifier(str(kind), value)
        except SuppliedFulltextError:
            continue
        declared[normalized_kind] = normalized_value
    return declared


class FulltextIntakeService:
    """Validate, normalize and store one supplied fulltext registration."""

    def __init__(
        self,
        *,
        store: SuppliedFulltextStore,
        parser: FulltextContentParser,
        path_policy: IntakePathPolicy,
        limits: IntakeLimits | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._parser = parser
        self._paths = path_policy
        self._limits = limits or IntakeLimits()
        self._clock = clock or (lambda: datetime.now(tz=timezone.utc))

    async def register(
        self,
        request: FulltextIntakeRequest,
        *,
        artifact_writer: Callable[[SuppliedFulltextRecord], Awaitable[str | None]] | None = None,
    ) -> FulltextIntakeResult:
        """Validate the request, store the record and return it.

        Parsing, file reads and store writes run in worker threads so a large
        or hostile payload never stalls the event loop.

        Raises:
            SuppliedFulltextError: The request breaks the intake contract; its
                ``code`` names the violated rule. Nothing is stored.
        """
        kind, value = normalize_identifier(request.identifier_kind, request.identifier_value)
        identifiers: dict[str, str] = {kind: value}
        for alias_kind, alias_value in request.aliases:
            try:
                normalized_kind, normalized_value = normalize_identifier(alias_kind, alias_value)
            except SuppliedFulltextError:
                continue
            identifiers.setdefault(normalized_kind, normalized_value)
        if request.supplied_by not in {"agent", "user"}:
            raise SuppliedFulltextError("invalid_request", "supplied_by must be 'agent' or 'user'")
        if (request.content is None) == (request.file_path is None):
            raise SuppliedFulltextError("content_required", "provide exactly one of content or file_path")
        # Validate provenance before any expensive work.
        provenance_fields = dict(request.provenance or {})
        if request.file_path is not None and not provenance_fields.get("source_file"):
            provenance_fields["source_file"] = PureWindowsPath(str(request.file_path).strip()).name or None
        provenance = SuppliedFulltextProvenance.create(
            retrieval_method=provenance_fields.get("retrieval_method"),
            retrieved_at=provenance_fields.get("retrieved_at"),
            source_url=provenance_fields.get("source_url"),
            source_file=provenance_fields.get("source_file"),
            license=provenance_fields.get("license"),
            note=provenance_fields.get("note"),
        )

        file_name: str | None = None
        if request.file_path is not None:
            path, data = await asyncio.to_thread(self._read_file, request.file_path)
            file_name = path.name
            content_format = _FILE_FORMATS[path.suffix.lower()]
            source_bytes = len(data)
            parsed = await self._parse_file(data, content_format)
        else:
            content = request.content or ""
            if len(content) > self._limits.max_inline_chars:
                raise SuppliedFulltextError(
                    "content_too_large", f"content must be at most {self._limits.max_inline_chars} characters"
                )
            if request.content_format not in {"text", "markdown", "jats", "html"}:
                raise SuppliedFulltextError("invalid_request", "content_format must be text, markdown, jats or html")
            content_format = request.content_format
            source_bytes = len(content.encode("utf-8"))
            parsed = await self._off_loop(self._parse_inline, content, content_format)

        declared = _declared_identifiers(parsed)
        for declared_kind, declared_value in declared.items():
            if identifiers.get(declared_kind, declared_value) != declared_value:
                raise _invalid_input(
                    f"The supplied document declares a different article ({declared_kind} {declared_value}) "
                    f"than requested ({declared_kind} {identifiers[declared_kind]})."
                )
        for declared_kind, declared_value in declared.items():
            identifiers.setdefault(declared_kind, declared_value)

        sections, abstract, truncated = await asyncio.to_thread(self._bound_sections, parsed)
        if not sections and not abstract:
            code = "extraction_failed" if content_format == "pdf" else "empty_content"
            message = (
                "No text could be extracted from the PDF (it may be scanned or no PDF text backend is installed). "
                "Use asset-aware-mcp OCR/ingest, or send the text as content."
                if content_format == "pdf"
                else "The supplied content contained no article text."
            )
            raise SuppliedFulltextError(code, message)

        hints: list[str] = []
        if content_format == "pdf":
            hints.append(_PDF_HINT)
        if provenance.retrieval_method == "host_fetch":
            hints.append(_HOST_FETCH_HINT)
        if not sections:
            hints.append(_NO_BODY_HINT)
        identifiers = await asyncio.to_thread(self._store.related_identifiers, identifiers)
        record = SuppliedFulltextRecord(
            record_id=new_record_id(),
            origin="user_supplied" if request.supplied_by == "user" else "agent_supplied",
            identifiers=identifiers,
            provenance=provenance,
            content_format=content_format,
            sections=sections,
            registered_at=self._clock()
            .astimezone(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            content_sha256=await asyncio.to_thread(content_digest, sections, abstract),
            title=_clean_title(request.title or parsed.get("title") or ""),
            abstract=abstract,
            truncated=truncated,
            hints=tuple(hints),
        )
        if artifact_writer is not None:
            artifact_uri = await artifact_writer(record)
            if artifact_uri:
                record = replace(record, artifact_uri=artifact_uri)
        try:
            record = await asyncio.to_thread(self._store.save, record)
        except OSError:
            raise SuppliedFulltextError(
                "storage_unavailable", "The tenant fulltext store could not be written."
            ) from None
        return FulltextIntakeResult(record=record, source_bytes=source_bytes, file_name=file_name)

    async def _off_loop(self, function: Callable[..., dict[str, Any]], *args: Any) -> dict[str, Any]:
        """Run a parser in a worker thread under a wall-clock budget."""
        try:
            return await asyncio.wait_for(asyncio.to_thread(function, *args), timeout=self._limits.parse_seconds)
        except (asyncio.TimeoutError, TimeoutError):
            raise _invalid_input("The supplied content took too long to parse.") from None

    def _read_file(self, raw_path: str) -> tuple[Path, bytes]:
        path = self._paths.resolve(raw_path)
        content_format = _FILE_FORMATS[path.suffix.lower()]
        limit = self._limits.max_pdf_file_bytes if content_format == "pdf" else self._limits.max_text_file_bytes
        try:
            checked = path.stat()
        except OSError:
            raise SuppliedFulltextError("file_not_found", "file_path could not be read") from None
        data = read_checked_file(path, checked, limit=limit)
        if content_format == "pdf" and b"%PDF-" not in data[:_PDF_SIGNATURE_WINDOW]:
            raise SuppliedFulltextError("unsupported_file_type", "the .pdf file is not a PDF document")
        return path, data

    async def _parse_file(self, data: bytes, content_format: ContentFormat) -> dict[str, Any]:
        if content_format == "pdf":
            text = await self._parser.extract_pdf_text(data)
            return await self._off_loop(lambda: split_text_sections(_clean_text(text or "")))
        return await self._off_loop(self._parse_inline, data.decode("utf-8-sig", errors="replace"), content_format)

    def _parse_inline(self, raw: str, content_format: ContentFormat) -> dict[str, Any]:
        return self._parse_text(_clean_text(raw), content_format)

    def _parse_text(self, text: str, content_format: ContentFormat) -> dict[str, Any]:
        if content_format == "jats":
            try:
                return self._parser.parse_jats(text)
            except SuppliedFulltextError:
                raise
            except Exception:
                raise SuppliedFulltextError("invalid_content", "The JATS content could not be parsed as XML.") from None
        if content_format == "html":
            try:
                return self._parser.parse_html(text)
            except SuppliedFulltextError:
                raise
            except Exception:
                raise SuppliedFulltextError("invalid_content", "The HTML content could not be read.") from None
        return split_text_sections(text)

    def _bound_sections(self, parsed: dict[str, Any]) -> tuple[tuple[dict[str, str], ...], str, bool]:
        budget = self._limits.max_stored_chars
        abstract = _clean_text(str(parsed.get("abstract") or "")).strip()[:budget]
        budget -= len(abstract)
        truncated = False
        sections: list[dict[str, str]] = []
        for raw in parsed.get("sections") or []:
            if not isinstance(raw, dict):
                continue
            content = _clean_text(str(raw.get("content") or "")).strip()
            if not content:
                continue
            if len(sections) >= self._limits.max_sections or budget <= 0:
                truncated = True
                break
            if len(content) > budget:
                content = content[:budget]
                truncated = True
            budget -= len(content)
            sections.append(
                {
                    "title": _clean_title(raw.get("title") or "Body", _MAX_SECTION_TITLE_CHARS) or "Body",
                    "content": content,
                }
            )
        return tuple(sections), abstract, truncated


__all__ = [
    "MAX_PARSED_SECTIONS",
    "MAX_PARSE_TEXT_CHARS",
    "FulltextContentParser",
    "FulltextIntakeRequest",
    "FulltextIntakeResult",
    "FulltextIntakeService",
    "InlineContentFormat",
    "IntakeLimits",
    "IntakePathPolicy",
    "SuppliedBy",
    "read_checked_file",
    "split_text_sections",
]
