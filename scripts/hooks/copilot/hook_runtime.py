#!/usr/bin/env python3
"""Privacy-safe, recoverable runtime shared by the Copilot hook wrappers.

The hook API still provides free-form prompts and rendered tool text.  This
module treats both as transient input: persistent state contains only opaque
fingerprints, bounded counters, source status, and artifact locators.  Bash and
PowerShell wrappers delegate here so their decisions cannot drift.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import tempfile
import uuid
from collections.abc import Iterable, Mapping
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SCHEMA_VERSION = 2
MAX_INPUT_CHARS = 2_000_000
MAX_AUDIT_ENTRIES = 500
MAX_SAFE_NAME_CHARS = 80
SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_.:-]+")
JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)
SOURCE_NAMES = {
    "arxiv",
    "biorxiv",
    "core",
    "crossref",
    "europe_pmc",
    "medrxiv",
    "openalex",
    "pubmed",
    "scopus",
    "semantic_scholar",
    "web_of_science",
}
STEP_TERMINAL_STATUSES = {"completed", "completed_with_warnings", "skipped"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_name(value: object, *, default: str = "unknown") -> str:
    text = SAFE_NAME_RE.sub("_", str(value or "").strip())[:MAX_SAFE_NAME_CHARS]
    return text or default


def _state_dir() -> Path:
    configured = os.environ.get("PUBMED_COPILOT_HOOK_STATE_DIR", "").strip()
    path = Path(configured) if configured else Path(".github/hooks/_state")
    path.mkdir(parents=True, exist_ok=True)
    with suppress(OSError):
        path.chmod(0o700)
    return path


def _policy_path() -> Path:
    configured = os.environ.get("PUBMED_COPILOT_HOOK_POLICY", "").strip()
    return Path(configured) if configured else Path(".github/hooks/copilot-tool-policy.json")


def _read_stdin_payload() -> dict[str, Any]:
    raw = sys.stdin.read(MAX_INPUT_CHARS + 1)
    if not raw or len(raw) > MAX_INPUT_CHARS:
        return {}
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _atomic_write_json(path: Path, payload: Mapping[str, Any], *, backup: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n"
    previous = _read_json(path) if backup and path.exists() else None
    if previous is not None:
        backup_path = path.with_suffix(".previous.json")
        _atomic_write_json(backup_path, previous)
    file_descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        with suppress(OSError):
            temporary_path.chmod(0o600)
        temporary_path.replace(path)
    finally:
        with suppress(OSError):
            temporary_path.unlink(missing_ok=True)


def _fingerprint_key(state_dir: Path) -> bytes:
    path = state_dir / ".fingerprint_key"
    for _attempt in range(3):
        try:
            encoded = path.read_text(encoding="ascii").strip()
            key = bytes.fromhex(encoded)
            if len(key) == 32:
                return key
        except (OSError, ValueError):
            pass

        key = secrets.token_bytes(32)
        try:
            file_descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        except OSError:
            return key
        with os.fdopen(file_descriptor, "w", encoding="ascii", newline="\n") as handle:
            handle.write(key.hex() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return key

    # A concurrently created but invalid key must not make the hook block. Its
    # bytes still provide a stable local fallback without persisting input.
    try:
        return hashlib.sha256(path.read_bytes()).digest()
    except OSError:
        return secrets.token_bytes(32)


def _fingerprint(value: object, state_dir: Path) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    digest = hmac.digest(_fingerprint_key(state_dir), text.encode("utf-8", errors="replace"), hashlib.sha256)
    return f"h1:{digest.hex()[:24]}"


def _load_policy() -> dict[str, Any]:
    return _read_json(_policy_path()) or {}


def _policy_tools(policy: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    groups = policy.get("toolGroups")
    if isinstance(groups, Mapping):
        for tools in groups.values():
            if isinstance(tools, list):
                result.update(str(tool) for tool in tools)
    return result


def _tools_for_rule(policy: Mapping[str, Any], rule_name: str) -> set[str]:
    rules = policy.get("rules")
    if not isinstance(rules, Mapping):
        return set()
    tools = rules.get(rule_name)
    return {str(tool) for tool in tools} if isinstance(tools, list) else set()


def _workflow_steps(policy: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw_steps = policy.get("workflowSteps")
    if not isinstance(raw_steps, Mapping):
        return {}
    return {str(name): dict(metadata) for name, metadata in raw_steps.items() if isinstance(metadata, Mapping)}


def _new_step_state() -> dict[str, Any]:
    return {"status": "not_started", "completed_at": None, "last_tool": None, "outcome": None}


def _normalize_step_state(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        status = value.replace("-", "_")
        return {**_new_step_state(), "status": status}
    if isinstance(value, Mapping):
        status = _safe_name(value.get("status"), default="not_started").replace("-", "_")
        return {
            "status": status,
            "completed_at": value.get("completed_at") if isinstance(value.get("completed_at"), str) else None,
            "last_tool": _safe_name(value.get("last_tool")) if value.get("last_tool") else None,
            "outcome": _safe_name(value.get("outcome")) if value.get("outcome") else None,
        }
    return _new_step_state()


def _next_step(tracker: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[str | None, str | None]:
    states = tracker.get("steps")
    if not isinstance(states, Mapping):
        return None, None
    for step_name, metadata in _workflow_steps(policy).items():
        state = _normalize_step_state(states.get(step_name))
        if state["status"] not in STEP_TERMINAL_STATUSES:
            instruction = metadata.get("nextInstruction")
            return step_name, str(instruction) if instruction else None
    return None, None


def _refresh_resume(tracker: dict[str, Any], policy: Mapping[str, Any]) -> None:
    step_name, instruction = _next_step(tracker, policy)
    tracker["resume"] = {
        "next_step": step_name,
        "next_instruction": instruction,
        "updated_at": _utc_now(),
    }
    tracker["status"] = "completed" if step_name is None else "active"
    tracker["updated_at"] = _utc_now()


def _migrate_tracker(payload: Mapping[str, Any], policy: Mapping[str, Any], state_dir: Path) -> dict[str, Any]:
    raw_steps = payload.get("steps") if isinstance(payload.get("steps"), Mapping) else {}
    steps = {step_name: _normalize_step_state(raw_steps.get(step_name)) for step_name in _workflow_steps(policy)}
    legacy_topic = payload.get("topic")
    tracker = {
        "schema_version": SCHEMA_VERSION,
        "workflow_id": _safe_name(payload.get("workflow_id"), default=uuid.uuid4().hex),
        "status": _safe_name(payload.get("status"), default="active"),
        "intent": _safe_name(payload.get("intent")),
        "complexity": _safe_name(payload.get("complexity"), default="unknown"),
        "template": _safe_name(payload.get("template"), default="comprehensive"),
        "prompt_fingerprint": payload.get("prompt_fingerprint")
        if isinstance(payload.get("prompt_fingerprint"), str)
        else _fingerprint(legacy_topic, state_dir),
        "created_at": payload.get("created_at") if isinstance(payload.get("created_at"), str) else _utc_now(),
        "updated_at": payload.get("updated_at") if isinstance(payload.get("updated_at"), str) else _utc_now(),
        "steps": steps,
        "last_result": (
            payload.get("last_result")
            if payload.get("schema_version") == SCHEMA_VERSION and isinstance(payload.get("last_result"), Mapping)
            else None
        ),
    }
    _refresh_resume(tracker, policy)
    return tracker


def _load_tracker(policy: Mapping[str, Any], state_dir: Path) -> dict[str, Any] | None:
    path = state_dir / "workflow_tracker.json"
    payload = _read_json(path)
    restored_from_previous = False
    if payload is None:
        previous = _read_json(state_dir / "workflow_tracker.previous.json")
        if previous is None:
            return None
        payload = previous
        restored_from_previous = True

    migrated = _migrate_tracker(payload, policy, state_dir)
    steps = payload.get("steps")
    needs_migration = (
        payload.get("schema_version") != SCHEMA_VERSION
        or "topic" in payload
        or not isinstance(steps, Mapping)
        or any(not isinstance(value, Mapping) for value in steps.values())
    )
    if restored_from_previous or needs_migration:
        # Do not back up legacy state because it may contain a raw topic.
        _atomic_write_json(path, migrated, backup=False)
        if needs_migration:
            (state_dir / "workflow_tracker.previous.json").unlink(missing_ok=True)
    return migrated


def _save_tracker(tracker: dict[str, Any], policy: Mapping[str, Any], state_dir: Path) -> None:
    _refresh_resume(tracker, policy)
    _atomic_write_json(state_dir / "workflow_tracker.json", tracker, backup=True)


def _sanitize_audit_entry(payload: Mapping[str, Any], state_dir: Path) -> dict[str, Any]:
    safe: dict[str, Any] = {"timestamp": str(payload.get("timestamp") or _utc_now())}
    for key in (
        "event",
        "workflow_id",
        "intent",
        "complexity",
        "tool_name",
        "tool_group",
        "outcome",
        "quality",
        "tier",
        "session_reason",
    ):
        if payload.get(key) not in (None, ""):
            safe[key] = _safe_name(payload[key])
    for key in ("result_count", "source_count"):
        value = payload.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            safe[key] = max(0, value)
    for fingerprint_name, raw_name in (("query_fingerprint", "query"), ("prompt_fingerprint", "prompt")):
        existing = payload.get(fingerprint_name)
        if isinstance(existing, str) and existing.startswith("h1:"):
            safe[fingerprint_name] = existing
        elif payload.get(raw_name):
            safe[fingerprint_name] = _fingerprint(payload[raw_name], state_dir)
    failed_sources = payload.get("failed_sources")
    if isinstance(failed_sources, list):
        safe["failed_sources"] = sorted({_safe_name(source) for source in failed_sources})
    artifact_uri = _safe_artifact_uri(payload.get("artifact_uri"))
    if artifact_uri:
        safe["artifact_uri"] = artifact_uri
    return safe


def _rewrite_legacy_audit(state_dir: Path) -> None:
    path = state_dir / "search_audit.jsonl"
    if not path.exists():
        return
    entries: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for line in lines[-MAX_AUDIT_ENTRIES:]:
        try:
            payload = json.loads(line)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(payload, Mapping):
            entries.append(_sanitize_audit_entry(payload, state_dir))
    encoded = "".join(json.dumps(entry, ensure_ascii=True, separators=(",", ":")) + "\n" for entry in entries)
    try:
        path.write_text(encoded, encoding="utf-8", newline="\n")
        path.chmod(0o600)
    except OSError:
        pass


def _append_audit(state_dir: Path, payload: Mapping[str, Any]) -> None:
    path = state_dir / "search_audit.jsonl"
    safe = _sanitize_audit_entry(payload, state_dir)
    line = json.dumps(safe, ensure_ascii=True, separators=(",", ":")) + "\n"
    try:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
        path.chmod(0o600)
    except OSError:
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > MAX_AUDIT_ENTRIES:
            path.write_text("\n".join(lines[-MAX_AUDIT_ENTRIES:]) + "\n", encoding="utf-8", newline="\n")
    except OSError:
        pass


def _parse_tool_args(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def _classify_intent(prompt: str, payload: Mapping[str, Any]) -> tuple[str, str, str]:
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        explicit = str(metadata.get("researchIntent") or metadata.get("workflowIntent") or "").strip().lower()
        if explicit in {"chronicle", "comparison", "systematic", "exploration", "gene_drug", "quick_search"}:
            template = (
                "pico" if explicit == "comparison" else ("gene_drug" if explicit == "gene_drug" else "comprehensive")
            )
            complexity = "complex" if explicit in {"comparison", "systematic"} else "moderate"
            return explicit, complexity, template

    if re.search(
        r"chronicle|time.?line|research (?:evolution|history|trajectory)|milestone|"
        r"\u7814\u7a76\u7de8\u5e74\u53f2|\u7814\u7a76\u8108\u7d61|\u7814\u7a76\u6f14\u8b8a|\u91cc\u7a0b\u7891|\u6642\u9593\u8ef8",
        prompt,
        re.IGNORECASE,
    ):
        return "chronicle", "moderate", "comprehensive"
    if re.search(r"\bvs\.?\b|versus|compared?\s+(?:to|with)", prompt, re.IGNORECASE):
        return "comparison", "complex", "pico"
    if re.search(
        r"systematic|comprehensive|review|meta.?analysis|\u7cfb\u7d71\u6027|\u6587\u737b\u56de\u9867",
        prompt,
        re.IGNORECASE,
    ):
        return "systematic", "complex", "comprehensive"
    if re.search(r"related|citation|PMID|DOI|explore", prompt, re.IGNORECASE):
        return "exploration", "moderate", "exploration"
    if re.search(r"\b(?:gene|BRCA|TP53|EGFR|drug|compound|PubChem)\b", prompt, re.IGNORECASE):
        return "gene_drug", "moderate", "gene_drug"
    if re.search(r"search|find|paper|article|literature|\u641c\u5c0b|\u8ad6\u6587|\u6587\u737b", prompt, re.IGNORECASE):
        return "quick_search", "simple", "comprehensive"
    return "unknown", "simple", "comprehensive"


def _query_complexity(query: str) -> tuple[int, str, str]:
    score = 0
    if re.search(r"\bvs\.?\b|versus|compared?\s+(?:to|with)|better\s+than|non-?inferior", query, re.IGNORECASE):
        score += 3
    if re.search(r"\b(?:patient|population|intervention|comparison|outcome)\b", query, re.IGNORECASE):
        score += 2
    if re.search(r"\b(?:efficacy|safety|mortality|morbidity|adverse)\b", query, re.IGNORECASE):
        score += 1
    if re.search(r"\b(?:systematic|comprehensive|meta-?analysis|review|all\s+studies)\b", query, re.IGNORECASE):
        score += 2
    if len(query.split()) > 6:
        score += 1
    if re.search(r"\b(?:AND|OR|NOT)\b", query):
        score += 1
    if re.search(r"\[(?:MeSH|Mesh|tiab|Title/Abstract)\]", query):
        score += 1
    tier = "complex" if score >= 5 else ("moderate" if score >= 3 else "simple")
    template = (
        "pico" if re.search(r"\bvs\.?\b|versus|compared?\s+(?:to|with)", query, re.IGNORECASE) else "comprehensive"
    )
    if re.search(r"\b(?:gene|BRCA|TP53|EGFR|PubChem|compound|drug)\b", query, re.IGNORECASE):
        template = "gene_drug"
    return score, tier, template


def _emit(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))


def _step_progress(tracker: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[int, int, list[str]]:
    states = tracker.get("steps") if isinstance(tracker.get("steps"), Mapping) else {}
    lines: list[str] = []
    completed = 0
    step_defs = _workflow_steps(policy)
    next_name, _ = _next_step(tracker, policy)
    for name, metadata in step_defs.items():
        state = _normalize_step_state(states.get(name))
        is_complete = state["status"] in STEP_TERMINAL_STATUSES
        completed += int(is_complete)
        marker = "[x]" if is_complete else "[ ]"
        label = str(metadata.get("label") or name)
        next_instruction = str(metadata.get("nextInstruction") or "")
        suffix = f" <-- NEXT: {next_instruction}" if name == next_name else ""
        lines.append(f"{marker} {label}{suffix}")
    return completed, len(step_defs), lines


def _session_init(payload: Mapping[str, Any]) -> None:
    state_dir = _state_dir()
    _rewrite_legacy_audit(state_dir)
    policy = _load_policy()
    tracker = _load_tracker(policy, state_dir)
    _read_evaluation(state_dir)
    (state_dir / "last_search_eval.json").unlink(missing_ok=True)
    (state_dir / "pending_complexity.json").unlink(missing_ok=True)
    _append_audit(
        state_dir,
        {
            "timestamp": _utc_now(),
            "event": "session_start",
            "workflow_id": tracker.get("workflow_id") if tracker else None,
        },
    )
    if tracker and tracker.get("status") == "active":
        completed, total, _ = _step_progress(tracker, policy)
        resume = tracker.get("resume") if isinstance(tracker.get("resume"), Mapping) else {}
        next_instruction = resume.get("next_instruction") or "inspect stored session/artifact state"
        _emit(
            {
                "instructions": (
                    f"Recovered research workflow {tracker['workflow_id']} ({completed}/{total} steps complete). "
                    f"Resume with: {next_instruction}. The tracker stores fingerprints and artifact locators only."
                )
            }
        )


def _analyze_prompt(payload: Mapping[str, Any]) -> None:
    prompt = str(payload.get("prompt") or "")
    if not prompt.strip():
        return
    state_dir = _state_dir()
    policy = _load_policy()
    intent, complexity, template = _classify_intent(prompt, payload)
    prompt_fingerprint = _fingerprint(prompt, state_dir)
    tracker = _load_tracker(policy, state_dir)
    if intent != "unknown" and (tracker is None or tracker.get("status") == "completed"):
        tracker = {
            "schema_version": SCHEMA_VERSION,
            "workflow_id": uuid.uuid4().hex,
            "status": "active",
            "intent": intent,
            "complexity": complexity,
            "template": template,
            "prompt_fingerprint": prompt_fingerprint,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "steps": {name: _new_step_state() for name in _workflow_steps(policy)},
            "last_result": None,
        }
    elif tracker is not None and intent != "unknown":
        tracker["prompt_fingerprint"] = prompt_fingerprint
        tracker["updated_at"] = _utc_now()
    if tracker is not None:
        _save_tracker(tracker, policy, state_dir)
        completed, total, lines = _step_progress(tracker, policy)
        instructions = [
            f"RESEARCH WORKFLOW {tracker['workflow_id']} ({completed}/{total} steps complete)",
            f"Intent: {tracker['intent']} | Template: {tracker['template']}",
            *lines,
            "Treat complexity classification as advice. Prefer structured source status and artifact audit evidence.",
        ]
        _emit({"instructions": "\n".join(instructions)})
    _append_audit(
        state_dir,
        {
            "timestamp": _utc_now(),
            "event": "prompt_submitted",
            "workflow_id": tracker.get("workflow_id") if tracker else None,
            "prompt_fingerprint": prompt_fingerprint,
            "intent": intent,
            "complexity": complexity,
        },
    )


def _tracker_has_evidence(tracker: Mapping[str, Any] | None) -> bool:
    if tracker is None or not isinstance(tracker.get("steps"), Mapping):
        return False
    for name in ("initial_search", "pipeline_search", "result_evaluation", "deep_exploration"):
        if _normalize_step_state(tracker["steps"].get(name))["status"] in STEP_TERMINAL_STATUSES:
            return True
    return False


def _has_explicit_context(args: Mapping[str, Any]) -> bool:
    context_keys = {
        "article_ids",
        "chronicle_id",
        "cid",
        "code",
        "doi",
        "gene_id",
        "identifier",
        "mesh_term",
        "name",
        "pipeline",
        "pmcid",
        "pmid",
        "pmids",
        "query",
        "source",
        "term",
        "topic",
    }
    return any(key in args and str(args[key] or "").strip() for key in context_keys)


def _safe_artifact_uri(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 500:
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme != "artifact"
        or re.fullmatch(r"[a-zA-Z0-9._-]{1,128}", parsed.netloc or "") is None
        or parsed.query
        or parsed.fragment
    ):
        return None
    if not re.fullmatch(r"/[a-zA-Z0-9._/-]+", parsed.path or ""):
        return None
    if any(segment in {".", ".."} for segment in parsed.path.split("/")):
        return None
    return value


def _read_evaluation(state_dir: Path) -> dict[str, Any] | None:
    payload = _read_json(state_dir / "last_research_eval.json")
    if payload is None:
        return None
    # Migrate the legacy raw query field in place.
    if payload.get("query"):
        payload["query_fingerprint"] = _fingerprint(payload.pop("query"), state_dir)
        _atomic_write_json(state_dir / "last_research_eval.json", payload)
    return payload


def _feedback_reason(evaluation: Mapping[str, Any]) -> str:
    outcome = _safe_name(evaluation.get("outcome"), default="unknown")
    count = evaluation.get("result_count") if isinstance(evaluation.get("result_count"), int) else 0
    failed = evaluation.get("failed_sources") if isinstance(evaluation.get("failed_sources"), list) else []
    artifact = evaluation.get("artifact") if isinstance(evaluation.get("artifact"), Mapping) else {}
    artifact_uri = _safe_artifact_uri(artifact.get("artifact_uri"))
    search_run = evaluation.get("search_run") if isinstance(evaluation.get("search_run"), Mapping) else {}
    run_id = _safe_name(search_run.get("run_id"), default="")
    parts = [f"Previous research result: {outcome} ({count} records)."]
    if artifact_uri:
        parts.append(
            "Recover the complete audit first with "
            f'read_session(action="artifact", artifact_uri="{artifact_uri}", artifact_file="audit.json").'
        )
    if run_id:
        parts.append(
            "Inspect or replay the durable run with "
            f'read_session(action="search_run", run_id="{run_id}") and '
            f'read_session(action="replay_search", run_id="{run_id}").'
        )
    if failed:
        parts.append(f"Partial provider failures: {', '.join(_safe_name(source) for source in failed)}.")
    parts.append("This is guidance only; the requested tool call remains allowed.")
    return " ".join(parts)


def _enforce_pipeline(payload: Mapping[str, Any]) -> None:
    tool_name = _safe_name(payload.get("toolName"), default="")
    if not tool_name:
        return
    args = _parse_tool_args(payload.get("toolArgs"))
    state_dir = _state_dir()
    policy = _load_policy()
    if tool_name not in _policy_tools(policy):
        return
    tracker = _load_tracker(policy, state_dir)
    evaluation = _read_evaluation(state_dir)

    if tool_name in _tools_for_rule(policy, "feedbackRemediation") and evaluation is not None:
        (state_dir / "last_research_eval.json").unlink(missing_ok=True)
        evaluation = None

    if evaluation is not None and not bool(evaluation.get("nudged")):
        evaluation["nudged"] = True
        _atomic_write_json(state_dir / "last_research_eval.json", evaluation)
        _emit({"permissionDecision": "allow", "permissionDecisionReason": _feedback_reason(evaluation)})
        return

    if tool_name == "unified_search":
        query = str(args.get("query") or "")
        _score, tier, template = _query_complexity(query)
        has_pipeline = bool(str(args.get("pipeline") or "").strip())
        options = {item.strip().lower() for item in str(args.get("options") or "").split(",") if item.strip()}
        if tier in {"moderate", "complex"} and not has_pipeline and "systematic" not in options:
            pending = {
                "schema_version": SCHEMA_VERSION,
                "workflow_id": tracker.get("workflow_id") if tracker else None,
                "tool_name": tool_name,
                "query_fingerprint": _fingerprint(query, state_dir),
                "tier": tier,
                "template": template,
                "created_at": _utc_now(),
            }
            _atomic_write_json(state_dir / "pending_complexity.json", pending)
            _emit(
                {
                    "permissionDecision": "allow",
                    "permissionDecisionReason": (
                        f"Complexity hint ({tier}): consider a {template} pipeline or options=systematic when "
                        "the user needs review-grade coverage. The current unified_search is allowed."
                    ),
                }
            )
            return

    if (
        tool_name in _tools_for_rule(policy, "requiresEvidenceOrIdentifiers")
        and tracker is not None
        and not _tracker_has_evidence(tracker)
        and not _has_explicit_context(args)
    ):
        _emit(
            {
                "permissionDecision": "allow",
                "permissionDecisionReason": (
                    f"Context hint for {tool_name}: no completed evidence step or explicit identifier was found. "
                    "Run unified_search or provide an identifier if the server response confirms context is missing."
                ),
            }
        )


def _decode_json_text(value: object) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    candidates = [text]
    fenced = JSON_FENCE_RE.search(text)
    if fenced:
        candidates.insert(0, fenced.group(1))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _structured_tool_payload(tool_result: object) -> dict[str, Any] | None:
    if not isinstance(tool_result, Mapping):
        return None
    for key in ("structuredContent", "structured_content", "json", "data"):
        value = tool_result.get(key)
        if isinstance(value, Mapping):
            return dict(value)
        decoded = _decode_json_text(value)
        if decoded is not None:
            return decoded
    content = tool_result.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, Mapping):
                decoded = _decode_json_text(block.get("text"))
                if decoded is not None:
                    return decoded
    return _decode_json_text(tool_result.get("textResultForLlm"))


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and value.is_integer():
        return max(0, int(value))
    return None


def _result_count(structured: Mapping[str, Any] | None) -> int | None:
    if structured is None:
        return None
    articles = structured.get("articles")
    if isinstance(articles, list):
        return len(articles)
    for key in ("returned_articles", "article_count", "result_count", "count"):
        count = _non_negative_int(structured.get(key))
        if count is not None:
            return count
    statistics = structured.get("statistics")
    if isinstance(statistics, Mapping):
        for key in ("unique_articles", "total_articles", "count"):
            count = _non_negative_int(statistics.get(key))
            if count is not None:
                return count
    return None


def _source_status(
    structured: Mapping[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
    if structured is None:
        return [], [], [], []
    rows: list[dict[str, Any]] = []
    counts = structured.get("source_counts")
    iterable: Iterable[object]
    if isinstance(counts, list):
        iterable = counts
    elif isinstance(counts, Mapping):
        iterable = ({"source": source, "returned": value} for source, value in counts.items())
    else:
        iterable = ()
    for row in iterable:
        if not isinstance(row, Mapping):
            continue
        source = _safe_name(row.get("source"), default="")
        if not source:
            continue
        returned = _non_negative_int(row.get("returned"))
        total = _non_negative_int(row.get("total_available"))
        if total is None:
            total = _non_negative_int(row.get("available"))
        if total is None:
            total = _non_negative_int(row.get("total"))
        has_more = row.get("has_more") if isinstance(row.get("has_more"), bool) else None
        rows.append({"source": source, "returned": returned, "total_available": total, "has_more": has_more})

    failures: list[dict[str, Any]] = []
    errors = structured.get("source_errors")
    if isinstance(errors, list):
        for error in errors:
            if not isinstance(error, Mapping):
                continue
            source = _safe_name(error.get("source"), default="unknown")
            failure = {
                "source": source,
                "status": _safe_name(error.get("status"), default="failed"),
                "retryable": bool(error.get("retryable")),
            }
            status_code = _non_negative_int(error.get("status_code"))
            if status_code is not None:
                failure["status_code"] = status_code
            failures.append(failure)
    failed_sources = sorted({failure["source"] for failure in failures})
    metadata_by_source = structured.get("source_metadata")
    metadata_by_source = metadata_by_source if isinstance(metadata_by_source, Mapping) else {}
    rows_by_source = {row["source"]: row for row in rows}
    for source, row in rows_by_source.items():
        metadata = metadata_by_source.get(source)
        metadata = metadata if isinstance(metadata, Mapping) else {}
        row["status"] = next((failure["status"] for failure in failures if failure["source"] == source), None) or (
            "ok" if (row.get("returned") or 0) > 0 else "empty"
        )
        row["provider_mode"] = _safe_name(metadata.get("provider_mode"), default="unknown")
        row["query_executed"] = bool(metadata.get("query_executed"))
        warnings = metadata.get("warnings")
        row["warning_count"] = len(warnings) if isinstance(warnings, list) else 0
    for failure in failures:
        source = failure["source"]
        if source not in rows_by_source:
            rows.append(
                {
                    "source": source,
                    "returned": 0,
                    "total_available": None,
                    "has_more": None,
                    "status": failure["status"],
                    "provider_mode": "unknown",
                    "query_executed": False,
                    "warning_count": 0,
                }
            )
    rows = rows[:50]
    attempted_sources = sorted({row["source"] for row in rows} | set(failed_sources))
    return rows, failures, failed_sources, attempted_sources


def _artifact_status(structured: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if structured is None:
        return None
    summary = structured.get("artifact_summary")
    artifact = structured.get("artifact")
    candidates = [value for value in (summary, artifact) if isinstance(value, Mapping)]
    if not candidates:
        return None
    merged: dict[str, Any] = {}
    for candidate in reversed(candidates):
        merged.update(candidate)
    uri = _safe_artifact_uri(merged.get("artifact_uri"))
    raw_artifact_id = str(merged.get("artifact_id") or "").strip()
    artifact_id = raw_artifact_id if re.fullmatch(r"[a-zA-Z0-9._:-]{1,128}", raw_artifact_id) else ""
    files = merged.get("available_files") or merged.get("files")
    safe_files = []
    if isinstance(files, list):
        safe_files = [
            name
            for value in files
            if (name := _safe_name(Path(str(value)).name, default="")) and name not in safe_files
        ][:20]
    result = {
        "artifact_uri": uri,
        "artifact_id": artifact_id or None,
        "audit_status": _safe_name(merged.get("audit_status"), default="unknown"),
        "available_files": safe_files,
    }
    return result if uri or artifact_id else None


def _search_run_status(structured: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if structured is None:
        return None
    raw = structured.get("search_run") or structured.get("search_run_handoff")
    if not isinstance(raw, Mapping):
        return None
    run_id = str(raw.get("run_id") or "").strip()
    if re.fullmatch(r"[a-zA-Z0-9._:-]{1,128}", run_id) is None:
        return None
    result: dict[str, Any] = {
        "run_id": run_id,
        "status": _safe_name(raw.get("status"), default="unknown"),
        "recoverable": bool(raw.get("recoverable")),
        "inspect": {
            "tool": "read_session",
            "arguments": {"action": "search_run", "run_id": run_id},
        },
        "replay": {
            "tool": "read_session",
            "arguments": {"action": "replay_search", "run_id": run_id},
        },
    }
    artifact_uri = _safe_artifact_uri(raw.get("artifact_uri"))
    if artifact_uri:
        result["artifact_uri"] = artifact_uri
    return result


def _workflow_step_for_tool(policy: Mapping[str, Any], tool_name: str, args: Mapping[str, Any]) -> str | None:
    if tool_name == "unified_search" and str(args.get("pipeline") or "").strip():
        return "pipeline_search"
    for name, metadata in _workflow_steps(policy).items():
        tools = metadata.get("tools")
        if isinstance(tools, list) and tool_name in tools:
            return name
    return None


def _tool_group(policy: Mapping[str, Any], tool_name: str) -> str:
    groups = policy.get("toolGroups")
    if isinstance(groups, Mapping):
        for name, tools in groups.items():
            if isinstance(tools, list) and tool_name in tools:
                return _safe_name(name)
    return "unknown"


def _outcome(
    result_type: str,
    structured: Mapping[str, Any] | None,
    count: int | None,
    failed: list[str],
    attempted: list[str],
) -> str:
    if result_type.lower() in {"failure", "error"}:
        return "failed"
    if failed:
        if count in {None, 0} and attempted and set(attempted) <= set(failed):
            return "failed"
        return "partial"
    if structured is not None and count == 0:
        return "empty"
    if structured is not None:
        return "complete"
    if result_type.lower() in {"success", "ok"}:
        return "complete_unstructured"
    return "unknown"


def _recovery_payload(
    artifact: Mapping[str, Any] | None,
    search_run: Mapping[str, Any] | None,
    failed_sources: list[str],
) -> dict[str, Any]:
    recovery: dict[str, Any] = {}
    if artifact:
        uri = _safe_artifact_uri(artifact.get("artifact_uri"))
        if uri:
            recovery["artifact_handoff"] = {
                "tool": "read_session",
                "arguments": {"action": "artifact", "artifact_uri": uri, "artifact_file": "audit.json"},
            }
    if search_run:
        recovery["search_run"] = {
            "inspect": search_run.get("inspect"),
            "replay": search_run.get("replay"),
        }
    if failed_sources:
        recovery["provider_retry"] = {
            "tool": "unified_search",
            "sources": failed_sources,
            "note": "Recover query_strategy.json first when an artifact locator is available; do not reconstruct raw queries from hook state.",
        }
    return recovery


def _evaluate_results(payload: Mapping[str, Any]) -> None:
    tool_name = _safe_name(payload.get("toolName"), default="")
    if not tool_name:
        return
    state_dir = _state_dir()
    policy = _load_policy()
    if tool_name not in _tools_for_rule(policy, "qualityEvaluation"):
        return
    args = _parse_tool_args(payload.get("toolArgs"))
    tool_result = payload.get("toolResult")
    result_type = "unknown"
    if isinstance(tool_result, Mapping):
        result_type = _safe_name(tool_result.get("resultType"), default="unknown")
    structured = _structured_tool_payload(tool_result)
    count = _result_count(structured)
    rows, failures, failed_sources, attempted_sources = _source_status(structured)
    artifact = _artifact_status(structured)
    search_run = _search_run_status(structured)
    outcome = _outcome(result_type, structured, count, failed_sources, attempted_sources)
    quality = {
        "failed": "poor",
        "partial": "acceptable",
        "empty": "acceptable",
        "unknown": "unknown",
    }.get(outcome, "good")
    query_fingerprint = _fingerprint(args.get("query"), state_dir)
    pending = _read_json(state_dir / "pending_complexity.json") or {}
    (state_dir / "pending_complexity.json").unlink(missing_ok=True)
    recovery = _recovery_payload(artifact, search_run, failed_sources)
    evaluation = {
        "schema_version": SCHEMA_VERSION,
        "tool_name": tool_name,
        "tool_group": _tool_group(policy, tool_name),
        "query_fingerprint": query_fingerprint,
        "outcome": outcome,
        "quality": quality,
        "result_count": count if count is not None else 0,
        "count_known": count is not None,
        "attempted_sources": attempted_sources,
        "source_counts": rows,
        "failed_sources": failed_sources,
        "source_failures": failures,
        "artifact": artifact,
        "search_run": search_run,
        "recovery": recovery,
        "tier": _safe_name(pending.get("tier"), default="none"),
        "template": _safe_name(pending.get("template"), default="comprehensive"),
        "nudged": False,
        "created_at": _utc_now(),
    }

    tracker = _load_tracker(policy, state_dir)
    step_name = _workflow_step_for_tool(policy, tool_name, args)
    if tracker is not None and step_name and isinstance(tracker.get("steps"), dict):
        state = _normalize_step_state(tracker["steps"].get(step_name))
        state["status"] = {
            "failed": "failed",
            "partial": "completed_with_warnings",
        }.get(outcome, "completed")
        state["completed_at"] = _utc_now() if state["status"] in STEP_TERMINAL_STATUSES else None
        state["last_tool"] = tool_name
        state["outcome"] = outcome
        tracker["steps"][step_name] = state
        tracker["last_result"] = {
            "tool_name": tool_name,
            "query_fingerprint": query_fingerprint,
            "outcome": outcome,
            "result_count": evaluation["result_count"],
            "failed_sources": failed_sources,
            "source_counts": rows,
            "artifact": artifact,
            "search_run": search_run,
            "recovery": recovery,
            "created_at": evaluation["created_at"],
        }
        _save_tracker(tracker, policy, state_dir)

    if outcome in {"failed", "partial", "empty", "unknown"} or recovery:
        _atomic_write_json(state_dir / "last_research_eval.json", evaluation)
    else:
        (state_dir / "last_research_eval.json").unlink(missing_ok=True)
    _append_audit(
        state_dir,
        {
            "timestamp": _utc_now(),
            "event": "tool_result",
            "workflow_id": tracker.get("workflow_id") if tracker else None,
            "tool_name": tool_name,
            "tool_group": evaluation["tool_group"],
            "query_fingerprint": query_fingerprint,
            "outcome": outcome,
            "quality": quality,
            "result_count": evaluation["result_count"],
            "source_count": len(attempted_sources),
            "failed_sources": failed_sources,
            "artifact_uri": artifact.get("artifact_uri") if artifact else None,
            "tier": evaluation["tier"],
        },
    )


def _session_cleanup(payload: Mapping[str, Any]) -> None:
    state_dir = _state_dir()
    policy = _load_policy()
    tracker = _load_tracker(policy, state_dir)
    (state_dir / "pending_complexity.json").unlink(missing_ok=True)
    (state_dir / "last_search_eval.json").unlink(missing_ok=True)
    reason = _safe_name(payload.get("reason"), default="unknown")
    if tracker is not None:
        tracker["last_session_end"] = {"timestamp": _utc_now(), "reason": reason}
        _save_tracker(tracker, policy, state_dir)
    _append_audit(
        state_dir,
        {
            "timestamp": _utc_now(),
            "event": "session_end",
            "workflow_id": tracker.get("workflow_id") if tracker else None,
            "session_reason": reason,
        },
    )


HANDLERS = {
    "session-init": _session_init,
    "analyze-prompt": _analyze_prompt,
    "enforce-pipeline": _enforce_pipeline,
    "evaluate-results": _evaluate_results,
    "session-cleanup": _session_cleanup,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one PubMed Search Copilot hook phase")
    parser.add_argument("phase", choices=sorted(HANDLERS))
    args = parser.parse_args()
    try:
        HANDLERS[args.phase](_read_stdin_payload())
    except Exception:
        # Hooks are advisory and must fail open. Never echo an exception because
        # it can include a prompt, query, URL credential, or rendered result.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
