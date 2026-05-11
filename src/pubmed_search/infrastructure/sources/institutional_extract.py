"""HTML-to-text extraction for publisher landing pages.

Used by the institutional direct/EZproxy fetch path. Tries trafilatura when
available (best results across Elsevier, Wiley, Springer, Nature, etc.) and
falls back to a conservative stdlib parser so the feature still works in
minimal installs.
"""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser

logger = logging.getLogger(__name__)


_MIN_TEXT_LENGTH = 500  # below this, treat extraction as failed
_MAX_HTML_BYTES = 8 * 1024 * 1024  # hard cap for safety


def _decode(html_bytes: bytes) -> str:
    if not html_bytes:
        return ""
    capped = html_bytes[:_MAX_HTML_BYTES]
    for encoding in ("utf-8", "latin-1"):
        try:
            return capped.decode(encoding)
        except UnicodeDecodeError:
            continue
    return capped.decode("utf-8", errors="replace")


def _extract_via_trafilatura(html_text: str, base_url: str) -> tuple[str | None, str | None]:
    """Return (text, title) using trafilatura, or (None, None) if unavailable."""
    try:
        import trafilatura  # type: ignore[import-not-found]
    except ImportError:
        return None, None

    try:
        extracted = trafilatura.extract(
            html_text,
            url=base_url,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
        if not extracted or len(extracted) < _MIN_TEXT_LENGTH:
            return None, None
        title: str | None = None
        try:
            metadata = trafilatura.extract_metadata(html_text)
            if metadata is not None:
                title = getattr(metadata, "title", None)
        except Exception:
            title = None
        return extracted, title
    except Exception as exc:
        logger.warning("trafilatura extraction failed: %s", exc)
        return None, None


class _TextOnlyParser(HTMLParser):
    """Fallback stdlib extractor — strip scripts/styles, collect visible text."""

    _SKIP_TAGS = {"script", "style", "noscript", "head", "nav", "footer", "aside", "form"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._title_parts: list[str] = []
        self._in_title = False
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title:
            self._title_parts.append(data)
            return
        stripped = data.strip()
        if stripped:
            self._chunks.append(stripped)

    @property
    def title(self) -> str | None:
        joined = " ".join(part.strip() for part in self._title_parts if part.strip())
        return joined or None

    @property
    def text(self) -> str:
        return "\n".join(self._chunks)


_WS_RE = re.compile(r"[ \t]+")
_NEWLINES_RE = re.compile(r"\n{3,}")


def _extract_via_stdlib(html_text: str) -> tuple[str | None, str | None]:
    parser = _TextOnlyParser()
    try:
        parser.feed(html_text)
    except Exception as exc:
        logger.warning("stdlib HTML parse failed: %s", exc)
        return None, None
    text = _NEWLINES_RE.sub("\n\n", _WS_RE.sub(" ", parser.text)).strip()
    if len(text) < _MIN_TEXT_LENGTH:
        return None, parser.title
    return text, parser.title


def extract_fulltext(html_bytes: bytes, base_url: str) -> dict[str, str] | None:
    """Extract title + readable text from publisher HTML.

    Returns a dict with ``title`` and ``text`` keys, or ``None`` when the
    extracted body is below ``_MIN_TEXT_LENGTH`` (treated as paywall/landing
    stub rather than fulltext).
    """
    html_text = _decode(html_bytes)
    if not html_text:
        return None

    text, title = _extract_via_trafilatura(html_text, base_url)
    if not text:
        text, fallback_title = _extract_via_stdlib(html_text)
        title = title or fallback_title
    if not text:
        return None

    return {
        "title": (title or "").strip(),
        "text": text,
    }
