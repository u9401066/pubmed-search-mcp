"""Tests for staged Unicode mojibake guard hook."""

from __future__ import annotations

from scripts.hooks.check_unicode_mojibake import (
    check_diff,
    find_mojibake_issues,
    iter_added_lines,
)


def test_valid_emoji_is_allowed() -> None:
    line = "## " + "\U0001f680" + " Quick Install"

    assert find_mojibake_issues(line) == []


def test_private_use_glyph_is_rejected() -> None:
    line = "## ?" + "\ue949" + "? Configuration"

    issues = find_mojibake_issues(line)

    assert any("Private Use Area" in issue for issue in issues)


def test_common_cp1252_mojibake_is_rejected() -> None:
    line = "Fran" + "\u00c3\u00a7" + "ais " + "\u00e2\u20ac\u201d" + " test"

    issues = find_mojibake_issues(line)

    assert any("decoded as Windows-1252" in issue for issue in issues)


def test_diff_parser_reports_only_added_lines() -> None:
    rocket = "\U0001f680"
    private_use = "\ue949"
    diff_text = f"""diff --git a/docs/demo.md b/docs/demo.md
index 1111111..2222222 100644
--- a/docs/demo.md
+++ b/docs/demo.md
@@ -2,0 +3,2 @@
+Good {rocket}
+Broken {private_use}
@@ -10 +12 @@
-Old broken {private_use}
+Plain text
"""

    added = list(iter_added_lines(diff_text))

    assert [(line.path, line.line_number, line.text) for line in added] == [
        ("docs/demo.md", 3, f"Good {rocket}"),
        ("docs/demo.md", 4, f"Broken {private_use}"),
        ("docs/demo.md", 12, "Plain text"),
    ]


def test_check_diff_returns_actionable_location() -> None:
    replacement = "\ufffd"
    diff_text = f"""diff --git a/README.md b/README.md
index 1111111..2222222 100644
--- a/README.md
+++ b/README.md
@@ -5,0 +6 @@
+Bad {replacement} heading
"""

    issues = check_diff(diff_text)

    assert len(issues) == 1
    assert issues[0].path == "README.md"
    assert issues[0].line_number == 6
    assert "replacement character" in issues[0].reason
