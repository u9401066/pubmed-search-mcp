# ruff: noqa: INP001
"""Render one saved research_workspace read response as a human-readable UTF-8 handoff."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def read_page(raw: bytes) -> dict[str, Any]:
    page = json.loads(raw.decode("utf-8-sig"))
    if isinstance(page, dict) and "jsonrpc" in page:
        page = page.get("result")
    if isinstance(page, dict) and "content" in page:
        content = page["content"]
        if (
            page.get("isError")
            or not isinstance(content, list)
            or len(content) != 1
            or not isinstance(content[0], dict)
            or content[0].get("type") != "text"
            or not isinstance(content[0].get("text"), str)
        ):
            raise ValueError("Expected a successful MCP result containing one text block")
        page = json.loads(content[0]["text"])
    if not isinstance(page, dict) or "records" not in page or "open_actions" not in page:
        raise ValueError("Expected the JSON returned by research_workspace with action=read")
    return page


def field(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing or invalid {key}")
    # Keep each field on its own output line, including notes copied from formatted text.
    return "".join(char if char.isprintable() else " " for char in value).strip()


def strings(row: dict[str, Any], key: str) -> list[str]:
    values = row.get(key)
    if not isinstance(values, list) or any(not isinstance(item, str) or not item.isprintable() for item in values):
        raise ValueError(f"Invalid {key} list")
    return values


def count(row: dict[str, Any], key: str) -> int:
    value = row.get(key)
    if type(value) is not int or value < 0:
        raise ValueError(f"Missing or invalid {key}")
    return value


def rows(page: dict[str, Any], key: str, total: int) -> list[dict[str, Any]]:
    items = page[key]
    if not isinstance(items, list) or len(items) > total or any(not isinstance(item, dict) for item in items):
        raise ValueError(f"Invalid {key} page")
    return items


def render(page: dict[str, Any]) -> str:
    total = count(page, "record_count")
    open_total = count(page, "open_action_count")
    records = rows(page, "records", total)
    actions = rows(page, "open_actions", open_total)
    lines = [
        f"Research workspace  {field(page, 'workspace_id')}",
        f"Question  {field(page, 'question')}",
        "Verification status  unverified",
        "",
        f"Records ({len(records)} of {total})",
    ]
    for record in records:
        if field(record, "verification_status") != "unverified":
            raise ValueError("Unsupported verification_status")
        lines.extend(
            [
                f"[{field(record, 'record_id')}] {field(record, 'activity')} / {field(record, 'evidence_scope')}"
                f" / {field(record, 'actor')}",
                f"  {field(record, 'note')}",
            ]
        )
        for key, label in (("source_refs", "Sources"), ("parent_ids", "From"), ("resolves", "Closes")):
            values = strings(record, key)
            if values:
                lines.append(f"  {label}  {', '.join(values)}")
        if record.get("locator") is not None:
            lines.append(f"  Passage  {field(record, 'locator')}")
        if record.get("next_action") is not None:
            lines.append(f"  Originally requested  {field(record, 'next_action')}")
    if len(records) < total:
        lines.append("Partial history. Read with after=0 to start from the first record.")
        if page.get("next_after") is not None:
            lines.append(f"Continue this history page with after={count(page, 'next_after')}.")
    lines.extend(["", f"Open actions ({len(actions)} of {open_total})"])
    for action in actions:
        lines.append(f"[{field(action, 'record_id')}] {field(action, 'next_action')}")
        refs = strings(action, "source_refs")
        if refs:
            lines.append(f"  Sources  {', '.join(refs)}")
    if len(actions) < open_total:
        lines.append("Partial action list. Read with open_offset=0 to start from the first open action.")
        if page.get("next_open_offset") is not None:
            lines.append(f"Continue this action page with open_offset={count(page, 'next_open_offset')}.")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", nargs="?", default="-", help="UTF-8 JSON file, or - for stdin")
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read() if args.file == "-" else Path(args.file).read_bytes()
        text = render(read_page(raw))
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Cannot render research handoff: {exc}\n")
    sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    main()
