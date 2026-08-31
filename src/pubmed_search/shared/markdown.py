"""Context-specific primitives for rendering untrusted values in Markdown.

Repository-owned renderers must keep their structural Markdown in source code
and pass provider/user-controlled field values through the primitive matching
the destination context.  This module deliberately does not accept a complete
Markdown document and try to sanitize it after interpolation.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote, urlsplit

_INLINE_MARKDOWN_CHARS = frozenset("\\`*_{}[]()<>|#!~")
_DANGEROUS_SCHEME_RE = re.compile(r"(?i)\b(?:javascript|data|vbscript):")
_ORDERED_LIST_RE = re.compile(r"^(\d{1,9})([.)])(\s+)")
_LANGUAGE_RE = re.compile(r"[^A-Za-z0-9_+.-]")
_BACKTICK_RUN_RE = re.compile(r"`+")
_RELATIVE_URL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*\Z")


def _string(value: object) -> str:
    return "" if value is None else str(value)


def _without_controls(value: object, *, preserve_newlines: bool) -> str:
    """Remove invisible controls while normalizing whitespace deterministically."""
    raw = _string(value).replace("\r\n", "\n").replace("\r", "\n")
    cleaned: list[str] = []
    for character in raw:
        if character == "\n":
            cleaned.append("\n" if preserve_newlines else " ")
        elif character == "\t":
            cleaned.append(" ")
        elif unicodedata.category(character) in {"Cc", "Cf"}:
            continue
        elif character.isspace():
            cleaned.append(" ")
        else:
            cleaned.append(character)
    return "".join(cleaned)


def _escape_inline(value: object, *, preserve_embedded_underscores: bool) -> str:
    text = re.sub(r"\s+", " ", _without_controls(value, preserve_newlines=False)).strip()
    escaped_parts: list[str] = []
    for index, character in enumerate(text):
        embedded_underscore = (
            preserve_embedded_underscores
            and character == "_"
            and index > 0
            and index + 1 < len(text)
            and text[index - 1].isalnum()
            and text[index + 1].isalnum()
        )
        escaped_parts.append(
            character if character not in _INLINE_MARKDOWN_CHARS or embedded_underscore else f"\\{character}"
        )
    escaped = "".join(escaped_parts)
    return _DANGEROUS_SCHEME_RE.sub(lambda match: f"{match.group(0)[:-1]}\\:", escaped)


def escape_markdown_text(value: object) -> str:
    """Render an untrusted value as one inert Markdown inline text span."""
    return _escape_inline(value, preserve_embedded_underscores=False)


def escape_markdown_identifier(value: object) -> str:
    """Render an identifier while preserving underscores embedded in words."""
    return _escape_inline(value, preserve_embedded_underscores=True)


def escape_markdown_block(value: object) -> str:
    """Preserve plain-text paragraphs while preventing Markdown block injection."""
    normalized = _without_controls(value, preserve_newlines=True)
    rendered: list[str] = []
    for raw_line in normalized.split("\n"):
        line = re.sub(r"[ \f\v]+", " ", raw_line).strip()
        if not line:
            rendered.append("")
            continue
        safe_line = escape_markdown_text(line)
        ordered = _ORDERED_LIST_RE.match(safe_line)
        if ordered:
            marker_start, marker_end = ordered.span(2)
            safe_line = f"{safe_line[:marker_start]}\\{safe_line[marker_start:marker_end]}{safe_line[marker_end:]}"
        elif safe_line.startswith(("-", "+", "=")):
            safe_line = f"\\{safe_line}"
        rendered.append(safe_line)
    return "\n".join(rendered).strip()


def escape_markdown_code(value: object) -> str:
    """Render an untrusted value inside a single-backtick code span."""
    text = re.sub(r"\s+", " ", _without_controls(value, preserve_newlines=False)).strip()
    return text.replace("`", "ˋ")


def safe_markdown_url(value: object) -> str | None:
    """Return an encoded HTTP(S) link destination or reject the value."""
    raw = _string(value).strip()
    if not raw or any(character.isspace() or unicodedata.category(character) in {"Cc", "Cf"} for character in raw):
        return None
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        _port = parsed.port
    except (TypeError, ValueError):
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    return quote(raw, safe=":/?&=#%+@;,$~-._")


def markdown_link(label: object, url: object) -> str:
    """Render an intentional link, falling back to inert label text if unsafe."""
    safe_label = escape_markdown_text(label)
    safe_url = safe_markdown_url(url)
    return f"[{safe_label}]({safe_url})" if safe_url else safe_label


def markdown_relative_link(label: object, path: object) -> str:
    """Render a link to a repository-generated relative path."""
    safe_label = escape_markdown_text(label)
    raw_path = _string(path).strip()
    if not _RELATIVE_URL_RE.fullmatch(raw_path) or raw_path.startswith(("/", ".")) or ".." in raw_path.split("/"):
        return safe_label
    return f"[{safe_label}]({quote(raw_path, safe='/._-')})"


def markdown_code_block(value: object, *, language: str = "") -> str:
    """Render inert fenced code while allowing arbitrary backticks in content."""
    content = _without_controls(value, preserve_newlines=True)
    longest_run = max((len(match.group(0)) for match in _BACKTICK_RUN_RE.finditer(content)), default=0)
    fence = "`" * max(3, longest_run + 1)
    safe_language = _LANGUAGE_RE.sub("", language)[:32]
    return f"{fence}{safe_language}\n{content}\n{fence}"


def markdown_indented_code_block(value: object) -> str:
    """Render inert indented code, preserving the existing line-oriented layout."""
    content = _without_controls(value, preserve_newlines=True)
    return "\n".join(f"    {line}" for line in content.split("\n"))


def escape_markdown_wikilink_label(value: object) -> str:
    """Render a Foam wikilink label without allowing ``]]`` or ``|`` escape."""
    label = escape_markdown_text(value)
    return label.replace(r"\[", "&#91;").replace(r"\]", "&#93;").replace(r"\|", "&#124;")


__all__ = [
    "escape_markdown_block",
    "escape_markdown_code",
    "escape_markdown_identifier",
    "escape_markdown_text",
    "escape_markdown_wikilink_label",
    "markdown_code_block",
    "markdown_indented_code_block",
    "markdown_link",
    "markdown_relative_link",
    "safe_markdown_url",
]
