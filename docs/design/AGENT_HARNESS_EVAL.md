# Agent harness evaluation — Claude Code with Haiku and Sonnet first

Status: R0 pilot completed and graded on 2026-11-25
([report](../reports/claude_code_harness_pilot_2026-11-25.md)). R1, the benchmark
build, is proposed and has not started. No release depends on this record.

## Goal

An agent that has this package should produce measurably better literature
results than the same agent without it. This applies on every supported host:
Claude Code, Cline, OpenCode and Codex. "Better" means a score on graded tasks,
not a demonstration.

The two earlier Codex pilots, both dated 2026-09-09, showed no difference:
- `native_codex_product_benchmark_2026-09-09.json` (3 PaperSearchQA questions);
- `frozen_agent_diagnostic_2026-09-09.json` (3 frozen BEIR queries).

Claude Code with small models comes first:
- weak models expose harness gaps quickly;
- Haiku runs are cheap enough to repeat;
- a headless CLI (`claude -p`) is available with structured output, a JSON transcript
  stream, and per-run usage and list-price cost.

## Arms

All arms get the same model, built-in tools, bundled skills and prompt. They
differ only in the pubmed components.

| Arm | Adds | Purpose |
|---|---|---|
| A | nothing (WebSearch, WebFetch, ToolSearch, Read, Glob, Grep) | native baseline |
| B | MCP server only | value of the tools |
| C0 | MCP + current `plugins/pubmed-search` skills (`--plugin-dir`) | value of today's skills |
| C1 | MCP + improved harness (skills, hooks, subagents, commands) | value of each harness change |

Every run is isolated:
- a fresh working directory;
- `--setting-sources ""` and `--strict-mcp-config`;
- `--no-session-persistence`;
- a per-run `PUBMED_WORKSPACE_DIR`;
- `--json-schema` for the final answer;
- `--output-format stream-json` for the transcript.

Two Claude Code constraints shape this setup:
- `--bare` cannot be used with a subscription login, because it accepts only an API key.
- `--disable-slash-commands` removes plugin skills as well as bundled ones, so formal runs keep it off in every arm.

## Models

- `claude-haiku-5-5` and `claude-sonnet-5-5` run the full matrix.
- `claude-opus-5-5` runs on a test-split subset as the ceiling.
- Effort stays at the default and is recorded per run.

## Task suites

Grading is deterministic and checks against live NCBI and iCite. No model acts
as a judge. Each suite has English and Traditional Chinese prompts and a fixed
train/test split. Improvements are tuned on train and reported on test.

| Suite | Content | Graded on |
|---|---|---|
| S1 reference verification | 30–50 references: real, wrong year/volume/pages/authors, fabricated, retracted | status, PMID, wrong fields; **accepted fabrications** is a critical metric |
| S2 systematic-search recall | topics with published included-study lists (CLEF TAR, Cochrane, after a licence check) plus the PACU topic | recall@N, reference-strategy overlap, query validity |
| S3 body-only full text | about 15 articles spanning PMC OA, author manuscripts, publisher-restricted PMC (e.g. JAMA bronze), Unpaywall green and closed | exact values; abstaining scores above a wrong answer; abstract traps |
| S4 MeSH strategy | building a strategy from a clinical question | MeSH validity, quoted-phrase/phrase-not-found warnings, concept coverage |
| S5 general QA | a PaperSearchQA subset (reuses the Codex loader) | exact match, source PMID hit; keeps the suite from favouring this package's strengths |
| S6 citation data | iCite values, citing-article sets | ±5% value agreement, set overlap |

## Metrics

Every run is measured on:
- **Quality:** task score.
- **Hallucinations:** nonexistent IDs, wrong values and invalid MeSH, counted as hallucinated items.
- **Grounding:** ungrounded IDs, meaning PMIDs in the answer that appear in no tool result and not in the prompt.
- **Honesty:** abstaining versus answering wrongly.
- **Effort and cost:** tool calls, turns, wall time, list-price cost and context tokens.

Paired bootstrap intervals are computed per suite, as the Codex reports do.

## R0 pilot findings that set lever priority

Setup: 5 tasks × arms A/B × Haiku 5.5, pubmed-search-mcp 0.11.0, Claude Code 2.1.332.

- **Quality:** the two arms tied (mean 0.804 vs 0.807), with zero hallucinated items and zero ungrounded IDs in either.
- **Efficiency:** the MCP arm used 58% fewer tool calls (3.6 vs 8.6) at 33% of the list cost. Reference verification took 2 calls instead of 23 WebFetch calls.
- **Ceiling effect:** the pilot tasks are too easy to separate the arms. R1 suites must be larger and harder.
- **Tool discovery is not a bottleneck.** Haiku loaded the right tools with `ToolSearch select:` in 10/10 runs. Tool-profile changes therefore drop in priority.

## Harness levers (ordered by evidence)

1. **Error semantics and retry.** A transient NCBI failure (`URLError`, which reruns cleanly) was reported as `kind: unexpected, retryable: false`. `next_tools` then suggested MeSH generation instead of a retry, and Haiku abandoned its boolean query for weaker plain-language queries. Fix: classify transient failures as retryable, auto-retry them, and point `next_tools` at the same call.
2. **Response shaping.** `output_format=json` returned 165–254 KB for 30 records. A compact default (about 1 KB per record) plus artifact handles is needed before any model reads it.
3. **Completion contract.** Both arms returned 3 and 5 of the 15 requested articles. A ranked, verified list should come from one tool call, and the skill should state "return N or explain the shortfall".
4. **Validate before answering.** The native arm wrote its T5 strategy without any tool. PubMed silently dropped two quoted phrases (`QuotedPhraseNotFound`). Server-side validation should be paired with a skill rule, or a PostToolUse hook, that reports warnings.
5. **Full-text path.** `get_fulltext` took 64–85 s and returned `front_matter_only` for a JAMA bronze article, after which Haiku fetched the PMC HTML itself. The 0.12.0 `pmc_html` source and a latency budget address this.
6. **Hooks as guardrails.** A Stop hook would reject PMIDs and DOIs that appear in no tool result. Ship it only once harder suites show ungrounded-ID events (zero so far).
7. **Shorter skills.** The current 12 skills total 2,581 lines. Rewrite them as decision-tree playbooks and measure C0 against C1.
8. **Model-specific subagents.** A Haiku screener or verifier with a Sonnet planner, measured for cost per correct item.

## Improvement loop

Change one lever per iteration, aimed at the most frequent failure class in the
train-split transcripts. Keep a change only if the test split improves without
a rise in hallucinations. Each iteration is recorded in `docs/reports/`.

## Hosts after Claude Code

The task suites, graders and report schema are shared across hosts. Each host
gets its own driver:
- Codex already has `scripts/benchmark_product_harness.py`.
- Cline and OpenCode will use their headless modes, once their structured-output and transcript support is confirmed.

## Operations

- **Auth:** runs use the maintainer's Claude Code subscription login. No API key or credential enters the repository, and run configs that carry `NCBI_EMAIL` stay outside it.
- **Rate limits:** NCBI limits requests per second, so runs are sequential without an API key. With a key (10 requests/s) two to three runs can go in parallel.
- **Budget:** the pilot cost US$0.16 at list price for 10 Haiku runs (A: 0.0247 per run, B: 0.0081 per run). Per-suite estimates go to the maintainer before a full matrix runs.
- **Transcripts:** they hold queries and tool output and stay local. Reports keep aggregates only.

## R1 deliverables

1. `scripts/benchmark_claude_code_harness.py`, with tests, sharing grading and report code with the Codex runners.
2. Suite files S1–S6 with provenance and licences, plus train/test manifests.
3. Server fixes for levers 1–4, each with a regression test reproduced from a pilot transcript.
4. A C1 harness iteration report comparing A, B, C0 and C1 for Haiku and Sonnet.
