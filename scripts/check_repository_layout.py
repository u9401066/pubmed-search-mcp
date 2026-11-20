"""Account for every Git-visible file using the documented ownership map.

This is a file-placement check, not semantic code review. Ignored local output
and credentials are excluded by Git; missing tracked files represent deletions.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LAYOUT = ROOT / "docs/repository-layout.json"


def inventory(root: Path, layout: dict[str, Any], *, documents_only: bool = False) -> dict[str, Any]:
    """Reject unowned/ambiguous paths, including newly added untracked files."""
    selection = ["--", "*.md"] if documents_only else ["--others", "--exclude-standard"]
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", *selection],
        cwd=root,
        check=True,
        capture_output=True,
    )
    paths = sorted({name for name in result.stdout.decode().split("\0") if name and (root / name).is_file()})
    records, errors = [], []
    for path in paths:
        owners = [
            rule
            for rule in layout["categories"]
            if path in rule.get("files", []) or any(path.startswith(prefix) for prefix in rule.get("prefixes", []))
        ]
        if len(owners) != 1:
            errors.append({"path": path, "matching_categories": [rule["name"] for rule in owners]})
            continue
        records.append({"path": path, "category": owners[0]["name"], "status": owners[0]["status"]})
    return {
        "scope": "Tracked Markdown" if documents_only else "Existing Git-tracked and non-ignored untracked files",
        "total_files": len(paths),
        "classified_files": len(records),
        "counts": dict(sorted(Counter(row["category"] for row in records).items())),
        "errors": errors,
        "files": records,
    }


def write_document_catalog(root: Path, output: Path, records: list[dict[str, str]]) -> None:
    """Record the edit source for every tracked Markdown file, including portable copies."""
    migrations = json.loads((root / "docs/document-migrations.json").read_text(encoding="utf-8"))["moves"]
    tool_indexes = {
        "src/pubmed_search/presentation/mcp_server/TOOLS_INDEX.md",
        ".claude/skills/pubmed-mcp-tools-reference/SKILL.md",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["path", "owner", "status", "source"])
        for record in records:
            path, status = record["path"], record["status"]
            source = path
            if path.startswith("plugins/pubmed-search/skills/"):
                source = path.replace("plugins/pubmed-search/", ".claude/", 1)
                status = "generated"
            if source in tool_indexes:
                source, status = "scripts/count_mcp_tools.py", "generated"
            elif status == "compatibility-pointer":
                if source in ("docs/arxiv-paper/README.md", "docs/paper-draft.md"):
                    source = "docs/publication/README.md"
                else:
                    source = migrations.get(source, "docs/archive/phases/" + Path(source).name)
            else:
                with (root / source).open(encoding="utf-8") as doc:
                    origin = re.match(
                        r"<!-- (?:Generated|Synced) from (.+?) by scripts/build_docs_site.py -->", doc.readline()
                    )
                if origin:
                    source, status = origin[1], "generated"
            if not (root / source).is_file():
                raise ValueError(f"{path} has missing source {source}")
            writer.writerow([path, record["category"], status, source])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional inventory JSON; prefer ignored build/ output")
    parser.add_argument("--document-catalog", type=Path, help="Write ownership and sources for tracked Markdown as CSV")
    args = parser.parse_args()
    result = inventory(ROOT, json.loads(LAYOUT.read_text(encoding="utf-8")), documents_only=bool(args.document_catalog))
    if args.document_catalog and not result["errors"]:
        write_document_catalog(ROOT, args.document_catalog, result["files"])
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "files"}, indent=2))
    return int(bool(result["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
