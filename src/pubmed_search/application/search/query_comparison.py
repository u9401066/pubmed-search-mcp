"""Bounded PubMed set comparisons for an agent's explicit Boolean concept blocks."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from pubmed_search.application.search.query_validator import MAX_QUERY_LENGTH, validate_query
from pubmed_search.shared.credential_sanitizer import contains_credential_material
from pubmed_search.shared.exceptions import APIError

BlockId = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,15}$")]
BlockText = Annotated[str, Field(min_length=1, max_length=512)]
SeedPmid = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$", max_length=20)]
Probe = Callable[[str, int], Awaitable[dict[str, Any]]]


class QueryComparison(BaseModel):
    """The query argument fixes scope. Every named block is required in the baseline."""

    model_config = ConfigDict(extra="forbid", strict=True)
    blocks: Annotated[dict[BlockId, BlockText], Field(min_length=2, max_length=5)]
    seed_pmids: Annotated[list[SeedPmid], Field(max_length=16)] = Field(default_factory=list)


def _checked_clause(clause: str) -> str:
    if contains_credential_material(clause):
        raise ValueError("A comparison clause contains credential material")
    validation = validate_query(clause)
    if not validation.is_valid:
        raise ValueError("; ".join(validation.errors))
    return f"({clause.strip()})"


async def compare_queries(
    fixed: str, spec: QueryComparison, probe: Probe, *, timeout: float = 15.0
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Observe the all-block set and each mutually exclusive single-omission set."""
    fixed = _checked_clause(fixed)
    blocks = {key: _checked_clause(value) for key, value in sorted(spec.blocks.items())}
    if len({key.casefold() for key in blocks}) != len(blocks):
        raise ValueError("Block identifiers must be distinct ignoring case")
    if len({value.casefold() for value in blocks.values()}) != len(blocks):
        raise ValueError("Adjustable blocks must be distinct")
    baseline = " AND ".join([fixed, *blocks.values()])
    seeds = sorted(set(spec.seed_pmids))
    seed_clause = " OR ".join(f"{pmid}[uid]" for pmid in seeds)
    if len(baseline) + len(seed_clause) + 32 > MAX_QUERY_LENGTH:
        raise ValueError("The combined PubMed comparison exceeds the query length limit")
    deadline = asyncio.get_running_loop().time() + timeout
    calls = 0

    async def measure(query: str, limit: int) -> dict[str, Any]:
        nonlocal calls
        observed: dict[str, Any] = {"query": query, "observed_at": datetime.now(timezone.utc).isoformat()}
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return {**observed, "status": "deadline"}
        calls += 1
        try:
            result = await asyncio.wait_for(probe(query, limit), remaining)
        except (asyncio.TimeoutError, APIError):
            return {**observed, "status": "unavailable"}
        return {**observed, **result, "status": "warning" if result["warnings"] else "ok"}

    initial = await measure(baseline, 3)
    files: dict[str, Any] = {}
    changes: list[dict[str, Any]] = []
    failed: list[str] = []
    for key, block in blocks.items():
        relaxed = " AND ".join([fixed, *(term for label, term in blocks.items() if label != key)])
        difference = f"({relaxed}) NOT {block}"
        item = await measure(difference, 3)
        files[f"drop-{key}.json"] = {"relaxed_query": relaxed, "difference": item}
        if item["status"] != "ok":
            failed.append(key)
            continue
        if not item["count"]:
            continue
        changes.append({"drop": key, "add": item["count"]})

    for change in changes:
        if seeds:
            key = change["drop"]
            evidence = files[f"drop-{key}.json"]
            item = evidence["difference"]
            # A complete small sample already settles membership for every seed.
            hits = sorted(set(item["pmids"]) & set(seeds))
            if item["count"] > len(item["pmids"]) and len(hits) < len(seeds):
                known = await measure(f"({item['query']}) AND ({seed_clause})", len(seeds))
                evidence["seed_probe"] = known
                if known["status"] == "ok" and set(known["pmids"]).issubset(seeds):
                    hits = known["pmids"]
                else:
                    failed.append(f"{key}:seeds")
            if hits:
                change["seed_hits"] = hits

    changes.sort(key=lambda change: (not bool(change.get("seed_hits")), -change["add"], change["drop"]))
    summary: dict[str, Any] = {
        "status": "partial" if failed or initial["status"] != "ok" else "ok",
        "baseline": initial.get("count") if initial["status"] == "ok" else None,
        "changes": changes[:2],
        "relevance": "unassessed",
    }
    if failed or initial["status"] != "ok":
        summary["incomplete"] = ([] if initial["status"] == "ok" else ["baseline"]) + failed
    if len(changes) > 2:
        summary["more"] = len(changes) - 2
    plan = {
        "source": "pubmed",
        "fixed": fixed,
        "blocks": blocks,
        "seed_pmids": seeds,
        "baseline": initial,
        "changes": changes,
        "calls": calls,
        "difference_files": list(files),
    }
    if len(blocks) == 2:
        plan["either_query"] = f"{fixed} AND ({' OR '.join(blocks.values())})"
        if summary["baseline"] is not None and all(key not in failed for key in blocks):
            summary["either_total"] = summary["baseline"] + sum(item["add"] for item in changes)
    files["plan.json"] = {**plan, "summary": dict(summary)}
    return summary, files
