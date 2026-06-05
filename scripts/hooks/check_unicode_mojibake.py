#!/usr/bin/env python3
"""Pre-commit hook: block newly staged Unicode mojibake.

The guard scans added diff lines only. Valid emoji and non-ASCII text are
allowed; replacement characters, Private Use Area glyphs, and common
Windows-1252/Latin-1 mojibake patterns are rejected.
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

# Force UTF-8 output on Windows consoles that default to legacy code pages.
if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
PRIVATE_USE_START = 0xE000
PRIVATE_USE_END = 0xF8FF
MAX_REPORTED_ISSUES = 25


MOJIBAKE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile("\u00c3[\u0080-\u00bf]"),
        "likely UTF-8 text decoded as Windows-1252/Latin-1 (C3 lead byte)",
    ),
    (
        re.compile("\u00c2[\u0080-\u00bf ]"),
        "likely UTF-8 text decoded as Windows-1252/Latin-1 (C2 lead byte)",
    ),
    (
        re.compile("\u00e2[\u0080-\u00bf\u0152\u0153\u20ac]"),
        "likely punctuation or symbol text decoded as Windows-1252 mojibake",
    ),
    (
        re.compile("\u00f0[\u0080-\u00bf\u0178]"),
        "likely emoji text decoded as Windows-1252 mojibake",
    ),
)


@dataclass(frozen=True)
class AddedLine:
    """A line added in the staged diff."""

    path: str
    line_number: int
    text: str


@dataclass(frozen=True)
class MojibakeIssue:
    """A suspicious Unicode sequence found in a staged line."""

    path: str
    line_number: int
    reason: str
    text: str


def find_mojibake_issues(text: str) -> list[str]:
    """Return mojibake reasons found in one line of text."""
    reasons: list[str] = []

    def add(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    if "\ufffd" in text:
        add("contains Unicode replacement character (U+FFFD)")

    private_use_codepoints = sorted(
        {f"U+{ord(char):04X}" for char in text if PRIVATE_USE_START <= ord(char) <= PRIVATE_USE_END}
    )
    if private_use_codepoints:
        sample = ", ".join(private_use_codepoints[:3])
        suffix = "" if len(private_use_codepoints) <= 3 else ", ..."
        add(f"contains Unicode Private Use Area glyph(s): {sample}{suffix}")

    for pattern, reason in MOJIBAKE_PATTERNS:
        if pattern.search(text):
            add(reason)

    return reasons


def iter_added_lines(diff_text: str) -> Iterator[AddedLine]:
    """Yield added lines from a unified git diff with new-file line numbers."""
    current_path: str | None = None
    next_new_line: int | None = None

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            current_path = None
            next_new_line = None
            continue

        if raw_line.startswith("+++ "):
            current_path = _parse_new_path(raw_line)
            continue

        hunk_match = HUNK_RE.match(raw_line)
        if hunk_match:
            next_new_line = int(hunk_match.group(1))
            continue

        if current_path is None or next_new_line is None:
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            yield AddedLine(current_path, next_new_line, raw_line[1:])
            next_new_line += 1
            continue

        if raw_line.startswith("-") and not raw_line.startswith("---"):
            continue

        if raw_line.startswith(" "):
            next_new_line += 1


def check_diff(diff_text: str) -> list[MojibakeIssue]:
    """Return all mojibake issues found in added lines of a staged diff."""
    issues: list[MojibakeIssue] = []

    for added_line in iter_added_lines(diff_text):
        for reason in find_mojibake_issues(added_line.text):
            issues.append(
                MojibakeIssue(
                    path=added_line.path,
                    line_number=added_line.line_number,
                    reason=reason,
                    text=added_line.text,
                )
            )

    return issues


def get_staged_diff() -> str:
    """Return staged textual diff with zero context."""
    result = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--no-color",
            "--no-ext-diff",
            "--unified=0",
            "--diff-filter=ACMR",
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git diff failed"
        raise RuntimeError(detail)
    return result.stdout


def main(argv: Sequence[str] | None = None) -> int:
    """Run the staged Unicode mojibake guard."""
    del argv

    try:
        diff_text = get_staged_diff()
    except RuntimeError as exc:
        print(f"unicode-mojibake guard could not read staged diff: {exc}", file=sys.stderr)
        return 2

    issues = check_diff(diff_text)
    if not issues:
        return 0

    print("Unicode mojibake guard found suspicious staged text:")
    print()
    for issue in issues[:MAX_REPORTED_ISSUES]:
        print(f"  {issue.path}:{issue.line_number}: {issue.reason}")
        print(f"    {format_snippet(issue.text)}")

    if len(issues) > MAX_REPORTED_ISSUES:
        print(f"  ... {len(issues) - MAX_REPORTED_ISSUES} more issue(s) omitted")

    print()
    print("Fix: restore the text as UTF-8 and re-stage it.")
    print("Note: normal emoji are allowed; corrupted emoji/PUA/replacement glyphs are blocked.")
    return 1


def format_snippet(text: str) -> str:
    """Return a compact ASCII-safe snippet for terminal output."""
    stripped = text.strip()
    if len(stripped) > 120:
        stripped = stripped[:117] + "..."
    return stripped.encode("unicode_escape", errors="backslashreplace").decode("ascii")


def _parse_new_path(diff_line: str) -> str | None:
    if diff_line == "+++ /dev/null":
        return None
    if diff_line.startswith("+++ b/"):
        return diff_line[6:]
    return diff_line[4:]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
