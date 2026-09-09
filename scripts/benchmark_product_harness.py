"""Native Codex versus native Codex plus the complete PubMed Search MCP package.

Both arms retain live web search and shell/API access. This is an online product
evaluation using public PaperSearchQA labels, not its fixed-corpus leaderboard.
Run on Linux with a logged-in Codex CLI. Only questions are passed to the agent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pubmed_search.application.search.agent_benchmark import score_factoid_answer, summarize_product_comparison
from pubmed_search.infrastructure.evaluation.checkpoints import PENDING_STATUSES, ExperimentStore, write_json
from pubmed_search.infrastructure.evaluation.provenance import source_fingerprint

SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "cited_pmids": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "source_urls": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "cited_pmids", "source_urls"],
    "additionalProperties": False,
}
TASK = """Answer the biomedical literature question below. Research with your available tools,
including built-in web search and direct access to PubMed or other scholarly sources as useful.
Give one canonical entity/phrase as the answer, without Markdown links, explanatory
sentences, or appended alternate names/abbreviations. Put citations only in their
separate fields. Give up to five supporting
PubMed IDs actually obtained from sources, and the source URLs you inspected.
Research the primary literature; do not look up benchmark datasets, answer keys, or mirrors.
Do not read files outside this task workspace. Do not change any external service or library.
You have {seconds} seconds; reserve time to submit the final JSON.

Question: {question}
"""


def install_package_skills(repo_root: Path, job: Path) -> dict[str, str]:
    """Copy original packaged research skills intact into Codex's project skill path."""
    skills = repo_root / ".claude/skills"
    paths = [*sorted(skills.glob("pubmed-*")), skills / "pipeline-persistence"]
    hashes = {}
    for source in paths:
        if not (source / "SKILL.md").exists():
            continue
        destination = job / ".agents/skills" / source.name
        shutil.copytree(source, destination)
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                hashes[path.relative_to(job).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not hashes:
        raise ValueError("The selected revision has no packaged PubMed research skills")
    return hashes


def product_command(job: Path, repo_root: Path, arm: str, model: str, effort: str) -> list[str]:
    """Preserve the same native research tools in both arms; add the package only to B."""
    command = [
        "codex",
        "exec",
        "--ignore-user-config",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "workspace-write",
        "--cd",
        str(job / "workspace"),
        "--model",
        model,
        "--json",
        "--output-schema",
        str(job / "schema.json"),
        "--output-last-message",
        str(job / "answer.json"),
    ]
    overrides = [
        'approval_policy="never"',
        'web_search="live"',
        "sandbox_workspace_write.network_access=true",
        "features.shell_tool=true",
        "features.unified_exec=true",
        "features.code_mode_host=true",
        "features.apps=false",
        "features.plugins=false",
        "features.multi_agent=false",
        "features.skip_host_skill_discovery=true",
        "model_reasoning_effort=" + json.dumps(effort),
    ]
    if arm == "package":
        server = (
            "{command="
            + json.dumps(sys.executable)
            + ',args=["-m","pubmed_search.presentation.mcp_server.server"],env={PYTHONPATH='
            + json.dumps(str(repo_root / "src"))
            + ",PUBMED_DATA_DIR="
            + json.dumps(str(job / "workspace/state"))
            + ",PUBMED_WORKSPACE_DIR="
            + json.dumps(str(job / "workspace"))
            + '},required=true,startup_timeout_sec=60,tool_timeout_sec=90,default_tools_approval_mode="approve"}'
        )
        overrides.append("mcp_servers.pubmed_search=" + server)
    for override in overrides:
        command.extend(["-c", override])
    return [*command, "-"]


def validate_answer(answer: Any) -> None:
    """Reject malformed submissions rather than treating them as valid research."""
    if (
        not isinstance(answer, dict)
        or not isinstance(answer.get("answer"), str)
        or not isinstance(answer.get("cited_pmids"), list)
    ):
        raise TypeError("Invalid final answer schema")
    pmids = answer["cited_pmids"]
    if (
        len(pmids) > 5
        or any(not isinstance(pmid, str) or not pmid.isdigit() for pmid in pmids)
        or len(set(pmids)) != len(pmids)
    ):
        raise ValueError("Invalid cited IDs")
    if not isinstance(answer.get("source_urls"), list) or any(
        not isinstance(url, str) for url in answer["source_urls"]
    ):
        raise TypeError("Invalid source URLs")


def run_product_case(
    job: Path,
    row: dict[str, Any],
    repo_root: Path,
    arm: str,
    model: str,
    effort: str,
    timeout: int,
    *,
    experiment_fingerprint: str = "",
    repeat: int = 0,
) -> dict[str, Any]:
    job.mkdir(parents=True, exist_ok=False)
    (job / "workspace").mkdir()
    skills = install_package_skills(repo_root, job / "workspace") if arm == "package" else {}
    (job / "schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
    prompt = TASK.format(seconds=max(30, timeout - 30), question=row["question"])
    if arm == "package":
        prompt += "\nThe complete PubMed Search MCP and its packaged research skills are available for this task.\n"
    (job / "prompt.txt").write_text(prompt, encoding="utf-8")
    status = "completed"
    execution_error = None
    started = time.monotonic()
    command = product_command(job, repo_root, arm, model, effort)
    (job / "command.json").write_text(json.dumps(command), encoding="utf-8")
    with (job / "events.jsonl").open("w") as stdout, (job / "stderr.log").open("w") as stderr:
        try:
            process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, text=True, start_new_session=True
            )
            try:
                process.communicate(prompt, timeout=timeout)
                if process.returncode:
                    status = "process_failed"
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                status = "timeout" if isinstance(error, subprocess.TimeoutExpired) else "interrupted"
        except OSError as error:
            status = "process_failed"
            execution_error = str(error)
    elapsed = time.monotonic() - started
    usage = {}
    calls = []
    turn_completed = False
    errors = []
    malformed_trace = False
    for line in (job / "events.jsonl").read_text(errors="replace").splitlines():
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            malformed_trace = True
            continue
        if event.get("type") == "turn.completed":
            turn_completed = True
            candidate_usage = event.get("usage", {})
            if isinstance(candidate_usage, dict) and all(
                isinstance(value, int) and value >= 0 for value in candidate_usage.values()
            ):
                usage = candidate_usage
            else:
                malformed_trace = True
        if event.get("type") in {"turn.failed", "error"}:
            errors.append(str(event.get("error", event.get("message", ""))))
        item = event.get("item", {})
        if not isinstance(item, dict):
            malformed_trace = True
            continue
        if event.get("type") == "item.completed" and item.get("type") in {
            "web_search",
            "mcp_tool_call",
            "command_execution",
        }:
            calls.append(
                {
                    "type": item["type"],
                    "tool": item.get("tool"),
                    "status": item.get("status"),
                    "error": item.get("error"),
                }
            )
    if status == "completed" and (malformed_trace or not turn_completed):
        status = "invalid_trace"
    if not turn_completed and provider_limit_detected(
        "\n".join(errors) + (job / "stderr.log").read_text(errors="replace")
    ):
        status = "provider_limited"
    if errors:
        execution_error = "; ".join(errors)[:1000]
    answer: dict[str, Any] = {}
    try:
        answer = json.loads((job / "answer.json").read_text())
        validate_answer(answer)
    except (OSError, ValueError, KeyError, TypeError):
        if status == "completed":
            status = "invalid_answer"
    metrics = score_factoid_answer(
        answer.get("answer", "") if status == "completed" else "",
        row["golden_answers"],
        answer.get("cited_pmids", []) if status == "completed" else [],
        str(row["pmid"]),
    )
    result = {
        "arm": arm,
        "status": status,
        "experiment_fingerprint": experiment_fingerprint,
        "query_id": hashlib.sha256(row["question"].encode()).hexdigest(),
        "repeat": repeat,
        "execution_error": execution_error,
        "metrics": metrics,
        "answer": answer,
        "usage": usage,
        "usage_known": bool(usage),
        "elapsed_seconds": elapsed,
        "tool_calls": calls,
        "package_skills_sha256": skills,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "events_sha256": hashlib.sha256((job / "events.jsonl").read_bytes()).hexdigest(),
    }
    write_json(job / "result.json", result)
    return result


def provider_limit_detected(message: str) -> bool:
    """Recognize account/API exhaustion; a task timeout alone is not a quota error."""
    return any(
        marker in message.lower()
        for marker in (
            "usage limit",
            "insufficient_quota",
            "rate_limit_exceeded",
            "credits exhausted",
            "credit balance",
            "quota exceeded",
        )
    )


def load_questions(path: Path) -> list[dict[str, Any]]:
    """Validate the full dataset before spending any model calls."""
    rows = json.loads(path.read_text())
    if not isinstance(rows, list) or not rows:
        raise ValueError("Dataset must be a non-empty row array")
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("question"), str) or not row["question"].strip():
            raise ValueError("Every row must contain a non-empty question")
        if (
            not isinstance(row.get("golden_answers"), list)
            or not row["golden_answers"]
            or any(not isinstance(alias, str) or not alias.strip() for alias in row["golden_answers"])
        ):
            raise ValueError("Every row must contain non-empty answer aliases")
        if not isinstance(row.get("pmid"), str) or not row["pmid"].isascii() or not row["pmid"].isdigit():
            raise ValueError("Every row must contain an ASCII numeric source PMID")
    if len({row["question"] for row in rows}) != len(rows):
        raise ValueError("Duplicate questions would corrupt paired accounting")
    return sorted(rows, key=lambda row: hashlib.sha256(row["question"].encode()).hexdigest())


def build_manifest(args: argparse.Namespace, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Freeze the protocol, dependencies, source, skills and scoring before execution."""
    root = Path(__file__).resolve().parents[1]
    skill_root = args.repo_root / ".claude/skills"
    skills = {}
    for directory in [*sorted(skill_root.glob("pubmed-*")), skill_root / "pipeline-persistence"]:
        if (directory / "SKILL.md").exists():
            skills.update(
                {
                    path.relative_to(skill_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in directory.rglob("*")
                    if path.is_file()
                }
            )
    if not skills:
        raise ValueError("Selected revision has no packaged research skills")
    dependencies = [
        Path(__file__).resolve(),
        root / "uv.lock",
        root / "src/pubmed_search/application/search/agent_benchmark.py",
        root / "src/pubmed_search/infrastructure/evaluation/checkpoints.py",
        root / "src/pubmed_search/infrastructure/evaluation/provenance.py",
    ]
    qids = [hashlib.sha256(row["question"].encode()).hexdigest() for row in rows]
    return {
        "schema_version": 2,
        "evaluation": "native_codex_vs_complete_package_online",
        "dataset": "jmhb/PaperSearchQA test",
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "query_ids": qids,
        "development_query_ids": qids[: args.development_query_count],
        "repeats": args.repeats,
        "model": args.model,
        "effort": args.effort,
        "repo_root": str(args.repo_root),
        "repo_revision_label": args.revision_label,
        "repo_source_sha256": source_fingerprint(args.repo_root),
        "package_skills_sha256": skills,
        "evaluator_sha256": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in dependencies
        },
        "python_version": sys.version,
        "codex_version": subprocess.check_output(["codex", "--version"], text=True).strip(),
        "task_sha256": hashlib.sha256(TASK.encode()).hexdigest(),
        "schema_sha256": hashlib.sha256(json.dumps(SCHEMA, sort_keys=True).encode()).hexdigest(),
        "native_web_search": "live_in_both_arms",
        "timeout_seconds": args.timeout,
        "token_budget_enforced": False,
        "backend_call_budget_enforced": False,
        "frozen_corpus": False,
        "official_leaderboard_score": False,
        "primary_metrics": ["answer_exact_match", "source_pmid_hit"],
        "pair_order": "alternate_by_query_and_repeat",
    }


def write_progress(
    store: ExperimentStore,
    manifest: dict[str, Any],
    results: dict[str, Any],
    state: str,
    attempts: list[dict[str, Any]],
    unfinished_attempts: int,
) -> dict[str, Any]:
    """Keep unfinished pairs out of quality estimates, and all attempts in costs."""
    complete = sum(
        len(runs) == manifest["repeats"] and all(len(pair) == 2 for pair in runs) for runs in results.values()
    )
    progress = {
        "state": state,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "planned_queries": len(manifest["query_ids"]),
        "planned_agent_runs": len(manifest["query_ids"]) * manifest["repeats"] * 2,
        "completed_queries": complete,
        "scored_agent_runs": sum(len(pair) for runs in results.values() for pair in runs),
        "attempts": len(attempts) + unfinished_attempts,
        "unfinished_attempts": unfinished_attempts,
        "unknown_usage_attempts": unfinished_attempts
        + sum(not result.get("usage_known", bool(result["usage"])) for result in attempts),
        "status_counts": {
            arm: dict(Counter(result["status"] for result in attempts if result["arm"] == arm))
            for arm in ("native", "package")
        },
        "resources": {
            arm: {
                "total_usage": dict(
                    sum((Counter(result["usage"]) for result in attempts if result["arm"] == arm), Counter())
                ),
                "total_elapsed_seconds": sum(result["elapsed_seconds"] for result in attempts if result["arm"] == arm),
            }
            for arm in ("native", "package")
        },
    }
    write_json(store.root / "progress.json", progress)
    return progress


def execute_experiment(
    store: ExperimentStore, manifest: dict[str, Any], rows: list[dict[str, Any]], args: argparse.Namespace
) -> dict[str, Any]:
    """Resume only missing arms; stop the batch on infrastructure failures."""
    results = {
        qid: [
            {arm: result for arm in ("native", "package") if (result := store.outcome(qid, repeat, arm)) is not None}
            for repeat in range(args.repeats)
        ]
        for qid in manifest["query_ids"]
    }
    state = "prepared" if args.prepare_only else "running"
    attempts = store.attempts()
    unfinished_attempts = store.unfinished_attempts()
    new_queries = 0
    write_progress(store, manifest, results, state, attempts, unfinished_attempts)
    if not args.prepare_only:
        for index, (qid, row) in enumerate(zip(manifest["query_ids"], rows, strict=True)):
            if args.batch_size is not None and new_queries >= args.batch_size:
                state = "paused_batch"
                break
            ran_query = False
            for repeat in range(args.repeats):
                for arm in ("native", "package") if (index + repeat) % 2 == 0 else ("package", "native"):
                    if arm in results[qid][repeat]:
                        continue
                    print(f"Evaluating {index + 1}/{len(rows)} repeat {repeat + 1}: {arm}", flush=True)
                    result = run_product_case(
                        store.next_attempt(qid, repeat, arm),
                        row,
                        args.repo_root,
                        arm,
                        args.model,
                        args.effort,
                        args.timeout,
                        experiment_fingerprint=store.fingerprint,
                        repeat=repeat,
                    )
                    attempts.append(result)
                    print(f"  {result['status']}: {result['metrics']}", flush=True)
                    if result["status"] in PENDING_STATUSES:
                        state = "paused_" + result["status"]
                        break
                    results[qid][repeat][arm] = result
                    ran_query = True
                    write_progress(store, manifest, results, state, attempts, unfinished_attempts)
                if state != "running":
                    break
            if state != "running":
                break
            if ran_query:
                new_queries += 1
        else:
            state = "completed"
    progress = write_progress(store, manifest, results, state, attempts, unfinished_attempts)
    summary = {
        **manifest,
        **progress,
        "formal_efficacy_conclusion": False,
        "comparison_scope": "complete_paired_queries_excluding_development_questions",
        **summarize_product_comparison(
            results, repeats=args.repeats, development_query_ids=manifest["development_query_ids"]
        ),
        "results": results,
    }
    write_json(store.root / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="Local JSON array exported from the full PaperSearchQA test split")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--revision-label", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", default="xhigh")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--query-limit", type=int, default=3)
    scope.add_argument("--all", action="store_true", help="Schedule every question in the dataset")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--development-query-count",
        type=int,
        default=0,
        help="Exclude this many leading SHA-sorted pilot questions from the primary comparison",
    )
    parser.add_argument("--batch-size", type=int, help="Pause after this many newly completed paired questions")
    parser.add_argument(
        "--prepare-only", action="store_true", help="Validate and freeze the full manifest without running any agents"
    )
    parser.add_argument(
        "--resume", action="store_true", help="Resume an identical manifest, preserving completed arms and attempts"
    )
    args = parser.parse_args()
    if args.query_limit <= 0 or args.timeout < 60 or args.repeats <= 0 or args.development_query_count < 0:
        parser.error("Invalid query count, timeout, repeat count, or development count")
    if args.batch_size is not None and args.batch_size <= 0:
        parser.error("batch-size must be positive")
    args.repo_root = args.repo_root.resolve()
    args.dataset = args.dataset.resolve()
    rows = load_questions(args.dataset)
    if not args.all:
        rows = rows[: args.query_limit]
    if args.development_query_count >= len(rows):
        parser.error("At least one non-development question must remain")
    manifest = build_manifest(args, rows)
    store = ExperimentStore(args.output_dir.resolve(), manifest, resume=args.resume)
    try:
        summary = execute_experiment(store, manifest, rows, args)
        print(
            json.dumps(
                {
                    key: summary[key]
                    for key in ("state", "planned_queries", "planned_agent_runs", "complete_query_count", "comparison")
                },
                indent=2,
            )
        )
    finally:
        store.close()


if __name__ == "__main__":
    main()
