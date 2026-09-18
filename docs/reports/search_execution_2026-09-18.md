# Search scheduling, upstream safety and repository organization — 2026-09-18

This measurement snapshot builds on `3cf1127` (published package was v0.7.3).
The subsequent [v0.7.4 release review](release_v074_2026-09-18.md) records further
concurrency/cancellation fixes and final validation. Counts below preserve the
pre-release measurement snapshot.
It improves the academic search integration layer; no autonomous agent or paid
public benchmark run was added. Provider protection takes priority over latency.

## Scope and boundaries

Reviewed the pipeline executor/budget path, unified planning/execution, deep
search broker, enrichment fan-out and shared provider transport. Normal search
and enrichment already run independent work concurrently. Deep search already
acquires source slots before global slots. These mechanisms and request rates
were not increased. This is a focused follow-up to the completed
[core review](core_review_2026-09-15.md), not a new claim to have reread every test
and script in the repository.

## Changes and safety findings

- Extracted task ownership and dependency-ready scheduling into the application
  `pipeline/scheduling.py` module. The executor retains action/error policy,
  output ranking and budgets. A fast branch may progress without waiting for an
  unrelated root. Inputs are copied, reports preserve the former topological
  order, and abort/cancellation cleans up all active branches.
- Reproduced a cooldown notification blocked behind the rate limiter's sleeping
  lock. Rate consumers now sleep outside that lock and recheck cooldowns on wake.
  The regression failed on the original implementation and passes after repair.
- Rate admission now happens **after** concurrency admission. Permits cannot
  accumulate behind a busy concurrency queue and then release as a burst.
- A first header-less 429 pauses sibling callers, even on the final attempt.
  Full server `Retry-After` is retained. If it exceeds the local retry wait cap,
  fail the current operation instead of shortening the server's requested wait.
  Cooldown expiration releases one token, then resumes ordinary pacing.
- Bio.Entrez's urllib HTTP errors now carry their status and Retry-After into
  that same kernel, close the failed response and preserve runtime restoration.
  Actual 429/503-shaped fixtures verify no early retry and no private URL leakage.
- NCBI now shares one operation slot across Entrez operation names. REST sources
  using BaseAPIClient default to two shared slots per service; explicit provider
  limits remain. No requests-per-period budget was raised.
- Moved three superseded Phase documents into `docs/archive/phases/`, repaired
  relative links and retained short old-path pointers. Added one documentation
  map, report index and script map; root discovery files and historical evidence
  remain at stable paths. Website content is generated from those sources.

The shared quota/concurrency registries are scoped to an event loop. Separate
workers/processes or other apps on the same IP/key need deployment-level quota
coordination; this change is not a distributed limiter and cannot promise zero
429s. Requests already received upstream and synchronous threads already running
cannot be recalled by task cancellation. Slow/rate-limited sources may take
longer or return typed partial errors rather than exceeding their budget.

The whole-source import audit still finds six evaluation/operator-only modules:
agent benchmark, frozen corpus/checkpoints/provenance, ClinicalKey AI and Semantic
Scholar datasets. Their references and intended non-runtime roles are explicit;
they were retained, rather than deleted based on static reachability alone.

## Reproducible latency experiment

```bash
uv run python scripts/perf/search_execution.py --output scripts/_tmp/before.json
# Apply the source change; use the identical benchmark script and lockfile.
uv run python scripts/perf/search_execution.py --baseline scripts/_tmp/before.json --output scripts/_tmp/after.json
```

The committed [before](search_execution_2026-09-18_before.json) and
[after](search_execution_2026-09-18_after.json) files contain 20 timed repetitions
per scenario/path plus one excluded warm-up, alternating executor/MCP order,
nearest-rank p95, raw samples, fixed configs, Python version and script/executor
hashes. The comparator rejects differing configs, delays, PMID sets, successful
steps or provider-operation counts. One MCP call executes each complete DAG.

Only the provider port is replaced by a fixed-delay, fixed-article fixture.
The executor, real in-memory MCP protocol, validation, formatting, reports and
session persistence run normally; outbound socket/DNS access is blocked. This
fixture intentionally does not exercise live provider throttling. Separate safety
regressions exercise the actual transport and client admission paths.

Measurements are **milliseconds**:

| Scenario | Executor p50 before → after | MCP p50 before → after | MCP p95 before → after | MCP p50 reduction |
| --- | ---: | ---: | ---: | ---: |
| no_io | 0.216 → 0.216 | 24.375 → 23.326 | 30.348 → 31.353 | 4.30% |
| single | 40.545 → 40.493 | 91.594 → 87.366 | 97.594 → 95.694 | 4.62% |
| balanced | 121.673 → 121.460 | 268.985 → 255.170 | 320.601 → 275.331 | 5.14% |
| staggered | 202.067 → 121.889 | 391.957 → 314.257 | 425.152 → 348.595 | 19.82% |
| serial | 121.812 → 122.049 | 336.959 → 344.882 | 364.692 → 369.153 | -2.35% |

The staggered fixture has branches of 20+100 ms and 100+20 ms. The old
whole-layer barrier costs about 100+100=200 ms; readiness scheduling approaches
the 120 ms critical path. The final two PMIDs, all five steps and four provider
operations remain identical. Executor p50 falls 39.68%; MCP p50 falls 19.82%.
Serial and balanced executor controls are essentially unchanged. The serial
MCP control is 2.35% slower, so these measurements do not support a general claim
that all searches become faster.

MCP times include accumulating history/filesystem work in one temporary server
per run; they are not pure protocol overhead and scenarios should not be
compared as if they had identical history size. Server startup, stdio/HTTP
network transport, live APIs, model reasoning, token usage and retrieval quality
are outside this latency experiment. Provider quota waits can dominate live
runs; the measured speedup must not be extrapolated to production QPS.

## Verification

- Focused regression coverage includes readiness with either root order, fail-fast
  abort and sibling cancellation, existing deadline/partial/budget/branch-isolation
  contracts, concurrent pipeline instances sharing a capacity limit, and actual
  NCBI/REST client defaults sharing admission across instances.
- Transport regressions cover an already queued token waiter receiving cooldown,
  pacing after cooldown, admission order, full long Retry-After, and header-less
  429 cooling sibling callers. No live load was sent to provider APIs.
- Final `uv run --frozen python scripts/check_repo.py full`: **4,748 passed,
  23 skipped, 30 integration cases deselected**, 111.77 seconds for pytest;
  Ruff/format, async consistency and mypy (432 files) pass. Includes source
  stdio, Streamable HTTP and fresh-wheel acceptance for the 41-tool registry.
- The earlier full gate passed 4,746 cases; the final rerun includes the two
  added Entrez HTTP-header regressions. Only 12 regression cases were added in
  total; existing tests and cloud CI scope were retained.
- DDD checks were explicitly applied to all 224 source Python files (the normal
  hook alone checks staged paths); zero violations. Bandit medium/high on changed
  scheduling/transport modules, Cline/Codex skill validation, JavaScript syntax,
  documentation link/generation checks and `git diff --check` pass.
- `uv run python scripts/perf/symbol_inventory.py --require-reviewed src/`
  passes. No live provider load, cloud CI job, tag or publication was initiated.

## Review reconciliation

The current core has **224 Python files, 456 classes and 2,446 functions/methods/
nested functions: 2,902 definitions**. The per-definition ledger has zero core
pending/follow-up/stale entries and no orphan reviews; the completion gate passes.

This change records 16 authored reviews for changed/new definitions. For 139
unchanged definitions in touched files, prior authored reviews are carried
forward only after verifying their AST is unchanged from `3cf1127`; the ledger
records that provenance explicitly rather than claiming a new semantic review.
The old nested outcome callback review was removed after its move into the
scheduler. Tests/scripts remain inventoried, not all semantically reviewed.

## Follow-up priorities

Optimize local history/serialization only after profiling growing session state
separately from protocol transport. Consider cache/single-flight deduplication
only with exact query/filter/credential/tenant identity and explicit freshness
semantics. Do not replace complete retrieval with first-N-provider returns or
increase fan-out to obtain a lower latency number. Multi-process service scaling
requires an actual shared quota coordinator before raising worker counts.
