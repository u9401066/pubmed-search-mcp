"""Offline pipeline latency: real executor and real in-memory MCP protocol.

Only the PubMed provider port is replaced. No live API or model calls. Run on
each revision with the same script/parameters; --baseline verifies identical
fixtures, article IDs, call counts and successful steps before comparing time.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import math
import os
import platform
import socket
import statistics
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from mcp import Client

from pubmed_search.application.pipeline.executor import PipelineExecutor
from pubmed_search.application.pipeline.store import _config_to_dict
from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.domain.entities.pipeline import PipelineConfig, PipelineOutput, PipelineStep
from pubmed_search.presentation.mcp_server.server import create_server, get_container

ROOT = Path(__file__).resolve().parents[2]


def block_network(event: str, args: tuple[Any, ...]) -> None:
    """Fail closed if a missed provider tries an external socket or DNS lookup."""
    if event == "socket.getaddrinfo" or (
        event == "socket.connect" and args[0].family != getattr(socket, "AF_UNIX", None)
    ):
        raise RuntimeError("Search execution benchmark forbids external networking")


def scenario(name: str) -> tuple[PipelineConfig, dict[str, float]]:
    """Fixed two-branch DAGs plus a single-call overhead control (seconds)."""
    timings = {
        "no_io": [0.0],
        "single": [0.04],
        "balanced": [0.06, 0.06, 0.06, 0.06],
        "staggered": [0.02, 0.10, 0.10, 0.02],
        "serial": [0.03, 0.03, 0.03, 0.03],
    }[name]
    delays = {f"q{index}": delay for index, delay in enumerate(timings)}
    steps = []
    for index in range(len(timings)):
        inputs = [f"s{index - 1}"] if name == "serial" and index else []
        if name not in {"serial", "single", "no_io"} and index >= 2:
            inputs = [f"s{index - 2}"]
        steps.append(
            PipelineStep(
                id=f"s{index}",
                action="search",
                inputs=inputs,
                params={"query": f"q{index}", "sources": ["pubmed"], "limit": 1},
            )
        )
    if len(steps) > 1 and name != "serial":
        steps.append(PipelineStep(id="merged", action="merge", inputs=["s2", "s3"]))
    return PipelineConfig(steps=steps, output=PipelineOutput(format="json")), delays


class TimedProvider:
    """Fixed one-row provider with observable logical operation concurrency."""

    def __init__(self, delays: dict[str, float]) -> None:
        self.delays = delays
        self.calls: list[str] = []
        self.active = 0
        self.peak = 0

    async def search_page(self, query: str, limit: int = 10, **_kwargs: Any) -> SourceSearchPage[dict[str, Any]]:
        self.calls.append(query)
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(self.delays[query])
            return SourceSearchPage(
                source="pubmed",
                query=query,
                total=1,
                items=[
                    {
                        "pmid": str(10000000 + int(query[1:])),
                        "title": f"Fixed article {query}",
                        "authors": [],
                        "journal": "Offline fixture",
                        "year": "2024",
                    }
                ][:limit],
            )
        finally:
            self.active -= 1


def summarize(samples: list[float]) -> dict[str, Any]:
    ordered = sorted(samples)
    return {
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3),
        "samples_ms": [round(value, 3) for value in samples],
    }


async def measure(repeats: int) -> dict[str, Any]:
    measurements: dict[str, Any] = {}
    with (
        TemporaryDirectory(prefix="pubmed-latency-") as temporary,
        patch.dict(
            os.environ,
            {
                "PUBMED_SCHEDULER_ENABLED": "false",
                "PUBMED_AUTH_REQUIRED": "false",
                "PUBMED_SERVER_MODE": "local",
                "PUBMED_DATA_DIR": temporary,
                "PUBMED_NOTES_DIR": temporary + "/notes",
                "PUBMED_WORKSPACE_DIR": "",
                "CLINICALKEY_AI_ENABLED": "false",
            },
        ),
    ):
        server = create_server(email="benchmark@example.invalid", data_dir=temporary, mode="local")
        searcher = get_container(server).searcher()
        async with Client(server) as client:
            for name in ("no_io", "single", "balanced", "staggered", "serial"):
                config, delays = scenario(name)
                signatures: list[dict[str, Any]] = []
                samples: dict[str, list[float]] = {"executor": [], "mcp": []}
                peaks: dict[str, list[int]] = {"executor": [], "mcp": []}
                # Warm both paths once; alternate order to reduce systematic drift.
                for repeat in range(repeats + 1):
                    paths = ("executor", "mcp") if repeat % 2 else ("mcp", "executor")
                    for path in paths:
                        provider = TimedProvider(delays)
                        started = time.perf_counter()
                        if path == "executor":
                            articles, results = await PipelineExecutor(searcher=provider).execute(config)
                            ids = sorted(article.pmid for article in articles)
                            successful = [step.id for step in config.steps if results[step.id].ok]
                        else:
                            with patch.object(searcher, "search_page", provider.search_page):
                                result = await client.call_tool(
                                    "unified_search",
                                    {"pipeline": json.dumps(_config_to_dict(config)), "output_format": "json"},
                                )
                            if result.is_error:
                                raise RuntimeError(f"MCP tool failed: {result.content}")
                            payload = json.loads(next(item.text for item in result.content if item.type == "text"))
                            ids = sorted(payload["steps"][-1]["pmids"])
                            successful = [step["id"] for step in payload["steps"] if step["status"] == "ok"]
                        elapsed = (time.perf_counter() - started) * 1000
                        signature = {"pmids": ids, "queries": sorted(provider.calls), "successful_steps": successful}
                        if successful != [step.id for step in config.steps] or sorted(provider.calls) != sorted(delays):
                            raise RuntimeError(f"Incomplete execution: {name}/{path}: {signature}")
                        if signatures and signature != signatures[0]:
                            raise RuntimeError(f"Non-equivalent output: {name}/{path}: {signature}")
                        signatures.append(signature)
                        if repeat:
                            samples[path].append(elapsed)
                            peaks[path].append(provider.peak)
                measurements[name] = {
                    "config": asdict(config),
                    "provider_delays_seconds": delays,
                    "signature": signatures[0],
                    "provider_operations": len(delays),
                    "mcp_calls_per_sample": 1,
                    **{path: {**summarize(values), "peak_operations": peaks[path]} for path, values in samples.items()},
                }
    return measurements


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--repeats", type=int, default=20)
    args = parser.parse_args()
    if not 2 <= args.repeats <= 100:
        parser.error("--repeats must be between 2 and 100")
    logging.disable(logging.WARNING)
    sys.addaudithook(block_network)
    report: dict[str, Any] = {
        "schema_version": 1,
        "scope": "Offline fixed-delay provider; real executor and in-memory MCP; no model, WAN or process startup",
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "executor_sha256": hashlib.sha256(
            (ROOT / "src/pubmed_search/application/pipeline/executor.py").read_bytes()
        ).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "repeats": args.repeats,
        "scenarios": asyncio.run(measure(args.repeats)),
    }
    if args.baseline:
        baseline = json.loads(args.baseline.read_text())
        for key in ("schema_version", "script_sha256", "python", "repeats"):
            if report[key] != baseline[key]:
                raise ValueError(f"Baseline mismatch: {key}")
        for name, current in report["scenarios"].items():
            previous = baseline["scenarios"][name]
            for key in ("config", "provider_delays_seconds", "signature", "provider_operations"):
                if current[key] != previous[key]:
                    raise ValueError(f"Baseline mismatch: {name}/{key}")
            current["comparison"] = {
                path: {
                    "baseline_p50_ms": previous[path]["p50_ms"],
                    "p50_reduction_percent": round((1 - current[path]["p50_ms"] / previous[path]["p50_ms"]) * 100, 2),
                }
                for path in ("executor", "mcp")
            }
        report["baseline_sha256"] = hashlib.sha256(args.baseline.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                name: {path: values[path]["p50_ms"] for path in ("executor", "mcp")}
                for name, values in report["scenarios"].items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
