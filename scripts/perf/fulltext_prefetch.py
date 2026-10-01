"""Offline XML wait/call-count comparison; no providers, model calls or real documents.

Run with uv run python scripts/perf/fulltext_prefetch.py --output build/fulltext-prefetch.json.
The controlled delays illustrate overlap and unused work, not real-world speedup.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pubmed_search.application.fulltext.cache import FulltextCache
from pubmed_search.domain.entities.article import UnifiedArticle

ROOT = Path(__file__).resolve().parents[2]
FETCH_SECONDS = 0.08
THINK_SECONDS = 0.10
REPEATS = 5


async def measure(mode: str, reads: list[str]) -> dict[str, Any]:
    """Measure foreground wait and let all admitted speculative I/O finish."""
    calls: list[str] = []
    complete = asyncio.Event()

    async def fetch(pmcid: str) -> str:
        calls.append(pmcid)
        await asyncio.sleep(FETCH_SECONDS)
        if len(calls) == 3:
            complete.set()
        return f"<article>{pmcid}</article>"

    cache = FulltextCache()
    try:
        if mode == "prefetch":
            cache.prefetch(
                [
                    UnifiedArticle(title="Fixture", primary_source="pubmed", pmc=f"PMC{i}", is_open_access=True)
                    for i in range(1, 4)
                ],
                tenant="offline",
                fetch=fetch,
            )
        await asyncio.sleep(THINK_SECONDS)
        started = time.perf_counter()
        contents = []
        for pmcid in reads:
            contents.append(
                await fetch(pmcid) if mode == "uncached" else await cache.get(pmcid, tenant="offline", fetch=fetch)
            )
        wait_ms = (time.perf_counter() - started) * 1000
        if mode == "prefetch":
            await asyncio.wait_for(complete.wait(), timeout=2)
        return {
            "foreground_wait_ms": wait_ms,
            "upstream_xml_calls": len(calls),
            "unused_xml_calls": sum(pmcid not in reads for pmcid in calls),
            "content_sha256": hashlib.sha256(json.dumps(contents).encode()).hexdigest(),
        }
    finally:
        await cache.aclose()


async def run() -> dict[str, Any]:
    rows = []
    for name, reads in (
        ("read_one_twice", ["PMC1", "PMC1"]),
        ("read_all_three", ["PMC1", "PMC2", "PMC3"]),
        ("read_queued_third_twice", ["PMC3", "PMC3"]),
    ):
        expected_hash = None
        for mode in ("uncached", "demand_cache", "prefetch"):
            samples = [await measure(mode, reads) for _ in range(REPEATS)]
            hashes = {sample["content_sha256"] for sample in samples}
            if len(hashes) != 1 or (expected_hash is not None and expected_hash not in hashes):
                raise RuntimeError("Comparison returned unequal article content")
            expected_hash = samples[0]["content_sha256"]
            rows.append(
                {
                    "scenario": name,
                    "mode": mode,
                    "foreground_wait_p50_ms": round(statistics.median(s["foreground_wait_ms"] for s in samples), 3),
                    "upstream_xml_calls": samples[0]["upstream_xml_calls"],
                    "unused_xml_calls": samples[0]["unused_xml_calls"],
                    "content_sha256": expected_hash,
                }
            )
    return {
        "scope": "Offline XML cache/scheduling only; excludes search, network, parsing, model tokens and real article availability.",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_revision": (
            await asyncio.to_thread(subprocess.check_output, ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True)
        ).strip(),
        "working_tree_changes": bool(
            (
                await asyncio.to_thread(subprocess.check_output, ["git", "status", "--porcelain"], cwd=ROOT, text=True)
            ).strip()
        ),
        "source_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ("src/pubmed_search/application/fulltext/cache.py", "scripts/perf/fulltext_prefetch.py")
        },
        "fixture": {
            "xml_fetch_ms": FETCH_SECONDS * 1000,
            "selection_delay_ms": THINK_SECONDS * 1000,
            "repeats": REPEATS,
        },
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(run())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
