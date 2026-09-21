"""Account for every Git-visible file using the documented ownership map.

This is a file-placement check, not semantic code review. Ignored local output
and credentials are excluded by Git; missing tracked files represent deletions.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LAYOUT = ROOT / "docs/repository-layout.json"


def inventory(root: Path, layout: dict[str, Any]) -> dict[str, Any]:
    """Reject unowned/ambiguous paths, including newly added untracked files."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
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
        "scope": "Existing Git-tracked and non-ignored untracked files; placement, not semantic review",
        "total_files": len(paths),
        "classified_files": len(records),
        "counts": dict(sorted(Counter(row["category"] for row in records).items())),
        "errors": errors,
        "files": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional inventory JSON; prefer ignored build/ output")
    args = parser.parse_args()
    result = inventory(ROOT, json.loads(LAYOUT.read_text(encoding="utf-8")))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "files"}, indent=2))
    return int(bool(result["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
