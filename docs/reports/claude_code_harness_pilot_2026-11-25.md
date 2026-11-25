# Claude Code harness pilot — 2026-11-25

This pilot compares native Claude Code (arm A) with Claude Code plus
pubmed-search-mcp (arm B). It was run to check that the benchmark pipeline works
and to measure cost. The sample is too small to support conclusions about
efficacy. The plan it feeds is in [AGENT_HARNESS_EVAL.md](../design/AGENT_HARNESS_EVAL.md).

## Setup

- **Host:** Claude Code 2.1.332 in headless mode (`claude -p`), subscription login.
- **Model:** `claude-haiku-5-5`, default effort. Each task × arm cell ran once.
- **Server:** pubmed-search-mcp 0.11.0 (PyPI) over stdio, with a fresh workspace per run.
- **Tools in both arms:** WebSearch, WebFetch, ToolSearch, Read, Glob, Grep. Arm B also had the 43 MCP tools.
- **Final answers:** structured output against a JSON Schema per task.
- **Grading:** deterministic, against live E-utilities and iCite. No model judge.

| Task | Question | Gold |
|---|---|---|
| T1 search | up to 15 studies of processed EEG in PACU/emergence (adults) | overlap with a 45-record reference boolean query; PMIDs must exist and titles must match |
| T2 verify | 7 references: 3 correct, 2 wrong year (one also wrong volume), 2 fabricated | statuses, PMIDs, wrong fields |
| T3 metrics | iCite citation count and RCR of PMID 12421743 | live iCite ±5% |
| T4 full text | ENGAGES (PMID 30721296): number screened, number enrolled, EEG device | 39 144; 1 400; BIS Quatro (Medtronic). These are body-only facts; the abstract reports 1 232 randomized, which serves as a trap |
| T5 MeSH | a PubMed strategy for the T1 question | valid `[Mesh]` terms, no phrase warnings, concept coverage, recall against the reference query |

The 2026-11-25 field benchmark asked T4 for a value (157/604) that the abstract
also contains, so it did not test full-text access. This pilot uses
body-only facts instead.

## Results

| Task | Arm | Score | Tool calls | Sec | Cost US$ (list) | Detail |
|---|---|---|---|---|---|---|
| T1 | A | 0.133 | 15 (WebSearch 4, WebFetch 10) | 53 | 0.0788 | 3 articles returned, 2 in reference set |
| T1 | B | 0.133 | 5 (unified_search 4) | 37 | 0.0095 | 5 returned, 2 in reference set; first search failed (see F2) |
| T2 | A | 1.000 | 23 (WebFetch 22) | 63 | 0.0162 | 7/7 statuses, 5/5 PMIDs, 2/2 field sets |
| T2 | B | 1.000 | 2 (verify_reference_list 1) | 21 | 0.0058 | same |
| T3 | A | 1.000 | 2 (WebFetch 1) | 11 | 0.0020 | 2730 citations, RCR 87.64 |
| T3 | B | 1.000 | 2 (get_citation_metrics 1) | 8 | 0.0029 | same |
| T4 | A | 1.000 | 3 (WebSearch 1, WebFetch 1) | 29 | 0.0205 | read the PMC HTML page |
| T4 | B | 1.000 | 3 (get_fulltext 1, WebFetch 1) | 85 | 0.0096 | get_fulltext returned `front_matter_only`; the agent then read the PMC HTML itself |
| T5 | A | 0.887 | 0 | 28 | 0.0062 | 468 hits; MeSH valid; 2 quoted phrases not found by PubMed |
| T5 | B | 0.900 | 6 (generate_search_queries 4, analyze_search_query 1) | 81 | 0.0128 | 448 hits; no warnings |

Tool-call counts include one ToolSearch call per run.

| Arm | Mean score | Hallucinated items | Ungrounded PMIDs | Mean tool calls | Mean sec | Total cost US$ |
|---|---|---|---|---|---|---|
| A native | 0.804 | 0 | 0 | 8.6 | 37 | 0.1237 |
| B + MCP | 0.807 | 0 | 0 | 3.6 | 46 | 0.0406 |

## Findings

- **F1 — under-delivery.** Both arms returned far fewer articles than the 15 requested (3 and 5). Arm A stopped after it could confirm only 3 titles through WebFetch. Arm B had more than 40 candidates in its tool output but chose 5.
- **F2 — error semantics.** Arm B's first call combined a boolean query with `filters="age_group:adult"`. NCBI raised a transient `URLError`, and the same call succeeded on two later reruns. The server reported this as `source_errors: kind=unexpected, retryable=false`, `message="Source adapter failed"`, and `next_tools` suggested generating MeSH variants. Haiku then dropped the precise boolean query for plain-language queries.
- **F3 — full-text latency.** `get_fulltext` spent about 64 s and returned only front matter for the JAMA bronze article. The agent's own WebFetch of the PMC HTML answered correctly. Release 0.12.0 adds a `pmc_html` source for single explicit requests.
- **F4 — unvalidated strategies.** Arm A built the T5 query from memory with no tool calls. PubMed reported two quoted phrases not found and drops such phrases from the search. Arm B validated its query and had no warnings.
- **F5 — tool discovery.** Discovery was not a problem: in every run Haiku loaded the right deferred tools with `ToolSearch select:`.
- **F6 — response size.** In a rerun of the F2 call, JSON output was 165–254 KB for 30 records, against 7–18 KB for the Markdown output the agent used. JSON responses need a compact default.

## Limitations

- Five tasks were run once each, so no intervals are reported. Three tasks hit the ceiling in both arms.
- The tasks, gold answers and T1/T5 reference query were written by the maintainer around this package's intended strengths. Suite S5 (general QA) is planned to offset this.
- Arms A and B ran with `--disable-slash-commands`, which also hides Claude Code's bundled skills. Formal runs keep the bundled skills in every arm.
- Costs are list-price estimates reported by Claude Code. The runs used a subscription login.
