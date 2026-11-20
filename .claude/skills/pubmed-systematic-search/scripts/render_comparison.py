# ruff: noqa: INP001
"""Render a saved PubMed comparison and a reader's choice as an offline Markdown table."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def cell(value: object) -> str:
    return str(value).replace("\n", " ").replace("|", r"\|")


def render(path: Path, choice: str, reason: str) -> str:
    plan = json.loads(path.read_text(encoding="utf-8"))
    blocks = plan["blocks"]
    if not all(re.fullmatch("[A-Za-z][A-Za-z0-9_]{0,15}", key) for key in blocks):
        raise ValueError("Invalid block ID")
    if choice and choice != "keep" and choice not in blocks:
        raise ValueError("Choose keep or one of the saved block IDs")
    baseline = plan["baseline"]
    rows = [
        "# PubMed query review",
        "",
        f"Baseline status: {baseline['status']}. Observed matches: {baseline.get('count', 'unknown')}.",
        "",
        "| Omitted block | Difference status | Additional candidates | Sample PMIDs |",
        "| --- | --- | ---: | --- |",
    ]
    selected = baseline["query"] if choice == "keep" else None
    for key in sorted(blocks):
        diff_path = path.with_name(f"drop-{key}.json")
        evidence = json.loads(diff_path.read_text(encoding="utf-8")) if diff_path.exists() else {}
        item = evidence.get("difference", {})
        sample = ", ".join(str(pmid) for pmid in item.get("pmids", [])) or "—"
        rows.append(
            f"| {key} | {cell(item.get('status', 'missing'))} | {cell(item.get('count', 'unknown'))} | {cell(sample)} |"
        )
        if choice == key:
            selected = evidence.get("relaxed_query")
    if choice:
        if not selected:
            raise ValueError("The selected query is missing from the saved evidence")
        rows.extend(["", f"Selected: {choice}", "", selected, "", f"Reason: {reason}"])
    rows.extend(["", "Samples illustrate membership in the difference set. Eligibility requires review."])
    return "\n".join(rows) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--choice", default="", help="keep or the ID of a block to omit")
    parser.add_argument("--reason", default="")
    args = parser.parse_args()
    if bool(args.choice) != bool(args.reason.strip()):
        parser.error("Record --choice and --reason together")
    sys.stdout.buffer.write(render(args.plan, args.choice, args.reason).encode("utf-8"))
