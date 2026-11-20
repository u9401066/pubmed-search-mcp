"""Paired, held-out MeSH decision experiment. See docs/reports/mesh-preflight-2017."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from pubmed_search.application.search.query_comparison import QueryComparison, compare_queries
from pubmed_search.infrastructure.evaluation.checkpoints import write_json
from pubmed_search.shared.exceptions import APIError

DEFAULT = Path(__file__).resolve().parents[1] / "docs/reports/mesh-preflight-2017"
ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(compact(value).encode()).hexdigest()


def verify_gold(protocol: dict, path: Path) -> bytes:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != protocol["qrels_sha256"]:
        raise ValueError("Wrong qrels revision or file encoding")
    return data


def chosen_query(case: dict, cutoff: str, choice: str) -> str:
    if choice != "keep" and choice not in case["blocks"]:
        raise ValueError(f"Unknown omission for {case['id']}")
    fixed = f"(({case['scope']}) AND {cutoff})"
    return " AND ".join([fixed, *(f"({v})" for k, v in sorted(case["blocks"].items()) if k != choice)])


def decode_result(payload: dict, limit: int) -> dict:
    result = payload["esearchresult"]
    count = int(result["count"])
    ids = result["idlist"]
    if count < 0 or not isinstance(ids, list) or len(ids) != min(count, limit):
        raise ValueError("Incomplete ESearch page")
    if not all(isinstance(p, str) and p.isascii() and p.isdecimal() for p in ids) or len(set(ids)) != len(ids):
        raise ValueError("Invalid ESearch identifiers")
    translation = result["querytranslation"]
    if not isinstance(translation, str) or not translation.strip() or result.get("ERROR"):
        raise ValueError("Missing ESearch interpretation")
    warnings = [
        str(message)
        for group in ("warninglist", "errorlist")
        for messages in result.get(group, {}).values()
        for message in messages
        if not (count == 0 and str(message).lower().rstrip(".") == "no items found")
    ]
    return {"count": count, "pmids": ids, "translation": translation, "warnings": warnings}


class Search:
    """One HTTP request per attempt, with a per-arm budget and no hidden retries."""

    def __init__(self, client: httpx.AsyncClient, protocol: dict, budget: int, email: str):
        self.client = client
        self.sort = protocol["sort"]
        self.budget = budget
        self.email = email
        self.calls = 0

    async def probe(self, query: str, limit: int) -> dict:
        if self.calls >= self.budget:
            raise ValueError("Search request budget exhausted")
        await asyncio.sleep(0.36)
        self.calls += 1
        try:
            response = await self.client.get(
                ESEARCH,
                params={
                    "db": "pubmed",
                    "term": query,
                    "retmode": "json",
                    "retmax": limit,
                    "sort": self.sort,
                    "email": self.email,
                    "tool": "pubmed_search_mcp_evaluation",
                },
            )
            response.raise_for_status()
            return decode_result(response.json(), limit)
        except (httpx.HTTPError, ValueError, TypeError, AttributeError, KeyError) as exc:
            # HTTP exception strings can contain the contact address.
            raise APIError(type(exc).__name__) from None


def load_stage(run: Path, name: str, parent: Any) -> dict:
    result = read(run / f"{name}.json")
    if result.get("status") == "interrupted":
        raise ValueError(f"{name} was interrupted")
    if result.get("parent_sha256") != digest(parent):
        raise ValueError(f"{name} does not match its frozen inputs")
    return result


def reserve(run: Path, name: str) -> Path:
    """Leave an interrupted stage visible and prevent replay into a measured budget."""
    run.mkdir(parents=True, exist_ok=True)
    target = run / f"{name}.json"
    with target.open("x", encoding="utf-8") as stream:
        json.dump({"status": "interrupted"}, stream)
    return target


async def preview(protocol: dict, run: Path, email: str) -> None:
    target = reserve(run, "preview")
    cases = {}
    async with httpx.AsyncClient(timeout=10) as client:
        for case in protocol["cases"]:
            search = Search(client, protocol, protocol["call_cap_per_arm"] - 1, email)
            summary, evidence = await compare_queries(
                f"({case['scope']}) AND {protocol['cutoff']}",
                QueryComparison(blocks=case["blocks"]),
                search.probe,
            )
            cases[case["id"]] = {"visible": summary, "evidence": evidence, "calls": search.calls}
    write_json(target, {"parent_sha256": digest(protocol), "cases": cases})
    print(compact({k: v["visible"] for k, v in cases.items()}))


def validate_choices(protocol: dict, previews: dict, choices: dict) -> None:
    if set(choices) != {case["id"] for case in protocol["cases"]}:
        raise ValueError("Lock exactly one decision for every case")
    for case in protocol["cases"]:
        key = case["id"]
        choice = choices[key]["choice"]
        chosen_query(case, protocol["cutoff"], choice)
        if not choices[key]["reason"].strip():
            raise ValueError("Record the blinded reason")
        if previews["cases"][key]["visible"]["status"] != "ok" and choice != "keep":
            raise ValueError("Partial preview requires the original query")


async def retrieve(protocol: dict, run: Path, email: str) -> None:
    previews = load_stage(run, "preview", protocol)
    decisions = load_stage(run, "decisions", previews)
    validate_choices(protocol, previews, decisions["cases"])
    target = reserve(run, "retrieval")
    cases: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=20) as client:
        for case in protocol["cases"]:
            key = case["id"]
            cases[key] = {}
            for arm, choice in [("original", "keep"), ("reviewed", decisions["cases"][key]["choice"])]:
                cost = previews["cases"][key]["calls"] if arm == "reviewed" else 0
                search = Search(client, protocol, protocol["call_cap_per_arm"] - cost, email)
                query = chosen_query(case, protocol["cutoff"], choice)
                event: dict[str, Any] = {"query": query, "observed_at": datetime.now(timezone.utc).isoformat()}
                try:
                    event.update(await search.probe(query, protocol["screen_cap"]))
                    event["status"] = "warning" if event["warnings"] else "ok"
                except APIError as exc:
                    event.update(status="unavailable", error=str(exc))
                cases[key][arm] = {**event, "calls": cost + search.calls}
                write_json(target, {"parent_sha256": digest(decisions), "cases": cases, "status": "running"})
    write_json(target, {"parent_sha256": digest(decisions), "cases": cases, "status": "finished"})


def score(protocol: dict, run: Path, qrels: Path) -> dict:
    previews = load_stage(run, "preview", protocol)
    decisions = load_stage(run, "decisions", previews)
    validate_choices(protocol, previews, decisions["cases"])
    records = load_stage(run, "retrieval", decisions)
    if records["status"] != "finished":
        raise ValueError("Retrieval interrupted")
    gold: dict[str, set[str]] = {case["id"]: set() for case in protocol["cases"]}
    for line in verify_gold(protocol, qrels).decode().splitlines():
        topic, _, pmid, label = line.split()
        if topic in gold and int(label) > 0:
            gold[topic].add(pmid)
    rows: dict[str, Any] = {}
    for key, included in gold.items():
        if not included:
            raise ValueError(f"Missing content-level positives for {key}")
        arms = records["cases"][key]
        original, reviewed = arms["original"], arms["reviewed"]
        row: dict[str, Any] = {
            "included": len(included),
            "choice": decisions["cases"][key]["choice"],
            "calls": [original["calls"], reviewed["calls"]],
            "preview_status": previews["cases"][key]["visible"]["status"],
        }
        rows[key] = row
        if original["status"] != "ok" or reviewed["status"] != "ok":
            row.update(status="incomplete", arm_status=[original["status"], reviewed["status"]])
            continue
        before, after = set(original["pmids"]), set(reviewed["pmids"])
        hits, new_hits = before & included, after & included
        row.update(
            status="paired",
            recovered=[len(hits), len(new_hits)],
            candidates=[len(before), len(after)],
            matched=[original["count"], reviewed["count"]],
            gained=sorted(new_hits - hits),
            lost=sorted(hits - new_hits),
            added_to_queue=len(after - before),
            displaced_from_queue=len(before - after),
        )
    return {"retrieval_sha256": digest(records), "cases": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["freeze", "preview", "show", "lock", "retrieve", "score"])
    parser.add_argument("--protocol", type=Path, default=DEFAULT / "protocol.json")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--qrels", type=Path)
    parser.add_argument("--choices", type=Path)
    parser.add_argument("--output", type=Path, help="Write the offline score as JSON")
    args = parser.parse_args()
    protocol = read(args.protocol)
    if args.stage == "freeze":
        if not args.qrels:
            parser.error("freeze needs --qrels")
        verify_gold(protocol, args.qrels)
        write_json(
            reserve(args.run, "freeze"), {"parent_sha256": digest(protocol), "qrels_sha256": protocol["qrels_sha256"]}
        )
        return
    load_stage(args.run, "freeze", protocol)
    if args.stage in {"preview", "retrieve"}:
        email = os.environ.get("NCBI_EMAIL")
        if not email:
            parser.error("Set NCBI_EMAIL for live ESearch")
        asyncio.run((preview if args.stage == "preview" else retrieve)(protocol, args.run, email))
    elif args.stage == "show":
        previews = load_stage(args.run, "preview", protocol)
        print(compact({k: v["visible"] for k, v in previews["cases"].items()}))
    elif args.stage == "lock":
        if not args.choices:
            parser.error("lock needs --choices")
        previews = load_stage(args.run, "preview", protocol)
        choices = read(args.choices)
        validate_choices(protocol, previews, choices)
        write_json(reserve(args.run, "decisions"), {"parent_sha256": digest(previews), "cases": choices})
    elif args.stage == "score":
        if not args.qrels:
            parser.error("score needs --qrels")
        result = score(protocol, args.run, args.qrels)
        if args.output:
            with args.output.open("x", encoding="utf-8", newline="\n") as output:
                output.write(json.dumps(result, indent=2) + "\n")
        else:
            print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
