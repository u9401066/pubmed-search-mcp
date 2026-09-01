# Active Context

## Current Focus

- The worktree is adding a post-release protocol regression gate on top of the
  published v0.7.0 boundary. The canonical MCP surface is **41 tools in 16
  registry categories**; removed public aliases, legacy wrappers, and alternate
  Copilot tool registries are not compatibility surfaces.
- The current post-v0.7.0 worktree passes 4,475 tests with 53 intentional
  skips, Ruff, format checking, mypy across 413 source files, the async-test
  audit, and all three complete MCP acceptance paths. The published v0.7.0
  release had separately passed its release, Mermaid-rendering, browser, and
  isolated-wheel gates.
- Preserve DDD boundaries: MCP tools adapt strict requests and delegate to
  application/domain services; source clients and outbound transport remain
  infrastructure concerns.

## Complete MCP Protocol Acceptance Contract

- Acceptance uses the official MCP client and real server processes. It must
  execute `tools/list` plus `tools/call` for all 41 public tools instead of
  importing or invoking tool functions directly.
- Each deterministic run performs 60 protocol calls so discriminated
  `read_session` and `read_research_chronicle` actions, repeat Chronicle
  revisions, saved-pipeline execution, and both Chronicle/citation Mermaid
  render paths are exercised in the same owning server process.
- Required paths are source-tree stdio, source-tree Streamable HTTP on loopback,
  and stdio from a freshly built and independently installed wheel.
- External-provider boundaries are replaced in the child process. Registry/schema
  validation, presentation adapters, application services, sessions, artifacts,
  note files, Chronicle revisions, pipelines, and scheduling stay real. A
  socket/DNS guard blocks and records any missed outbound dependency; the parent
  test fails on the sentinel even if the application catches the provider error.
- MCP-returned Mermaid source is checked against its declared digest and size.
  CI passes those exact Chronicle and citation sources to pinned Mermaid 11.16.1
  and requires successful SVG rendering.
- A separate real-stdio rejection pass protects the intentional breaking
  boundary: retired tool names, flat action bags, wrong scalar types, and
  stringified arrays/objects must remain rejected by the protocol server.
- Deterministic protocol acceptance is a PR CI/release gate; opt-in live-provider
  probes remain a separate availability and credential check.

## v0.7.0 Breaking Contract

- `read_session` accepts one action-discriminated `request` object. Removed
  session-reader aliases must not be restored.
- `read_research_chronicle` likewise accepts one discriminated `request` object
  for list/load/diff/narrative/milestones/compare operations.
- Topic Chronicle retrieval records `ranking_requested`, effective `ranking`,
  and `citation-metrics-coverage/v1`; an iCite ordering claim requires at least
  one validated citation count actually applied.
- Pipeline configuration has one canonical `output` contract and template
  pipelines have exactly one parameter field, `template_params`. The former
  `execution` shape, top-level template `params`, and loose PMID strings are
  rejected. An explicit pipeline `kind` is caller intent and is never
  overwritten by mode inference; it is inferred only when omitted, so a
  contradictory discriminator fails at the strict union boundary.
- Pipeline action/template names, step/dependency identifiers, enums, and every
  action-specific parameter use exact contracts. Unknown fields, wrong runtime
  types, fuzzy names, aliases, scalar-to-array conversion, string-to-number
  conversion, and other convenience coercion fail closed. Omitted fields may
  still receive documented defaults, and bounded safety limits remain explicit
  policy rather than caller-input repair.
- `unified_search` and every source path use typed adapter outcomes. Expected
  source/operation identity, runtime value types, status/items/errors
  coherence, nested error provenance, and
  `total_count >= len(items) >= 0` are validated fail-closed.
- Search-run inspect/replay handoffs return the exact nested
  `{"request": {...}}` arguments required by the canonical tool schema.
- Tool output is globally bounded and Markdown/code-span content is sanitized
  at the shared response boundary.
- Persisted session reads accept only `research-session/v1` and
  `research-session-index/v1`. Search runs are first-class records; legacy
  history projection, article-cache payload warmup, and unknown nested fields
  are not migrated.
- Pipeline execution has one aggregate wall-clock deadline and external-call
  quota for the complete DAG. Validation reports errors only; there is no
  auto-fix path that rewrites caller input.
- Full-text discovery has one immutable typed result with links,
  attempted/completed canonical source keys, sanitized source errors, and
  `complete`/`partial`/`unavailable` coverage. Partial success remains visible
  through download, extraction, tool output, and artifacts. Only HTTP 204/404
  or a successfully parsed zero-link response is absence; outage or parse
  failure yields sanitized `partial`/`unavailable` coverage.
- `generate_search_queries` keeps successful unchanged spelling, zero MeSH
  matches, and genuine zero-result query analysis distinct from outages. Its
  spelling, MeSH, and query-analysis stages expose
  `completed`/`partial`/`failed` coverage plus generic warnings.
- Authenticated note responses use tenant-relative locators and disclose no
  host paths. OpenURL bases reject queries/credentials, PMID-to-DOI diagnosis
  distinguishes `not_found` from `error`, and one corrupt selected pipeline
  run record fails the complete history read.
- PubMed EFetch plus NCBI Extended ESearch/ESummary/ELink accept only validated
  provider envelopes and requested rows. Explicit ClinicalTrials.gov adjuncts
  run for Markdown/JSON/TOON and expose `clinical-trials-adjunct/v1` coverage
  across immediate output, source errors, and artifacts.
- Open-i image aggregation consumes only strict provider results and exposes
  `completed`/`empty`/`partial`/`failed` source coverage; failed sources have
  unknown totals and never appear in `sources_used` or as false no-results.
- The local browser broker requires an explicitly provisioned bearer token of
  at least 32 characters. It never generates or logs a secret; invalid token
  configuration aborts before the HTTP server starts.

## Unified Search Application Boundary

- Normal search orchestration is owned by `application/unified`: request
  normalization lives beside `UnifiedSearchUseCase`, which coordinates
  planning, source execution, enrichment, and the typed `UnifiedSearchOutcome`
  through explicit planner, executor, source-broker, source-registry,
  enrichment, progress, and plan-observer ports.
- `presentation/mcp_server/tools/unified_runner.py` is an MCP adapter only. It
  owns rejected-input handling, SearchRun journaling, host progress, response
  formatting, artifact persistence, and recovery hints around the application
  outcome; none of those concerns belongs inside the use case.
- `PubMedSearchClient.unified_search()` composes the same application use case
  directly and returns typed articles, per-source coverage, sanitized source
  errors, and result-filter counts. It does not import presentation code or
  create MCP strings, SearchRun records, sessions, or artifacts as a side
  effect.
- `UnifiedSourceBroker` and `UnifiedEnrichmentAdapter` are infrastructure
  implementations of application ports. Crossref, journal-metrics, and
  Unpaywall work produces immutable typed patches; patches apply in fixed
  provider/article order and final ranking runs after enrichment, so concurrent
  provider completion order cannot change the result.
- Provider failure is never authoritative emptiness. `BaseAPIClient` has no
  `strict_errors` switch, mutable last-error channel, second rate limiter, or
  raw-reason logging; duplicate CORE/Europe PMC search/getter and
  Crossref/Unpaywall lookup facades are removed in favor of the runtime-owned
  package boundary and typed source envelopes.
- ICD/MeSH validation, curated mappings, and lookups live in
  `application/search/icd.py`; the MCP registrar only selects a direction and
  formats the result. Biomedical image search depends on the application-level
  `ImageSourceAdapter`/`OpenIClientPort`, while the server composition root
  injects an Open-i factory backed by its own `SourceRuntime`.

## Tool Schema Audit

- The runtime-derived audit covers all **41 unique tool owners** in **16
  categories**, with no missing, extra, or duplicate registry owner.
- All **74 object schemas** are recursively closed, all **215 primitive/array
  schema nodes** have explicit bounds, and all **10 tagged unions** have an
  exact required discriminator and constant variant mapping.
- Required/default coherence and behavior annotations are checked from the
  registered runtime rather than maintained as a parallel hand-written list.

## Server and Source Runtime

- Each `PubMedMCPServer` owns its `ToolSessionRuntime`, tenant registry,
  session manager, strategy registry, application container, pipeline runtime,
  source contacts, and source-client lifecycle. Constructing or closing server
  B must not replace or close server A's state.
- `SourceRuntime` owns provider/full-text/preprint/figure/browser clients,
  PubTator and semantic-cache values, citation exporters, plus one
  `SharedAsyncClientRuntime`. Saved scheduler jobs bind that same runtime around
  the complete pipeline DAG, including semantic expansion and alternate-source
  work.
- `PubMedSearchClient` lazily owns an independent `SourceRuntime`; callers use
  `async with PubMedSearchClient(...)` or call `await client.aclose()` during
  shutdown. SDK calls bind both the source runtime and its shared HTTP pool
  around `unified_search`.
- Context-local injection is an execution bridge, not a process-global source
  of truth. Tool code obtains dependencies from the owning server runtime.
- Source-client instances and connection pools are reused only within their
  owning runtime. Provider rate limits, circuit breakers, and bulkheads remain
  explicitly event-loop/provider scoped policy; mutable contacts, caches,
  clients, exporters, and pools may not leak across servers or SDK clients.
- `ToolSessionRuntime` owns both host-callback and citation-expansion task
  supervisors. They share the reusable `BoundedTaskSupervisor` lifecycle
  primitive but keep independent capacities: 32 pending host callbacks and 128
  pending citation tasks. Server shutdown closes and reaps both owners.

## Canonical HTTP and Profiling Surface

- The environment-dependent profiling monkeypatch and hidden
  `get_performance_metrics` tool are deleted; environment configuration cannot
  silently change the 41-tool registry.
- The orphan standalone FastAPI presentation app and stdio background-HTTP
  launcher are deleted. Stdio never opens an HTTP listener.
- `pubmed-search-mcp-http` is the supported HTTP process. Its authenticated or
  loopback companion cache/session routes belong to the same canonical server,
  tenant/auth boundary, and runtime; they are not a second MCP registry or
  shadow application.

## Bounded Best-Effort Task Contract

- Progress, log, and resource-update callbacks are scheduled through the
  owning server's `HostCallbackRuntime` and observed with `asyncio.wait` under
  a hard deadline.
- At the deadline the callback is cancelled and control is yielded once; a
  cancellation-resistant callback is quarantined in the server-owned
  supervisor instead of blocking the tool. The quarantine is capped at 32
  tasks, and a full supervisor rejects and disposes each new callback.
- Host timeout/failure does not fail core tool work, while cancellation of the
  enclosing tool still propagates. Server lifespan shutdown invokes
  `HostCallbackRuntime.aclose()` to cancel owned callbacks and give cooperative
  callbacks bounded grace to exit.
- Citation expansion uses the same ownership/reaping primitive through a thin
  `CitationTaskSupervisor`, capped at 128 pending tasks and closed from the
  owning server lifespan. It does not maintain a second detached-task
  implementation.

## Safe Outbound Contract

- Full-text, figure, institutional-access, and other URL-following paths use the
  shared safe-outbound boundary.
- URL schemes, credentials, DNS results, private/local/reserved addresses, every
  redirect hop, response byte limits, and total deadlines are checked. DNS
  rebinding or a public-to-private redirect fails closed.
- Provider failures remain sanitized diagnostics; they do not become fabricated
  empty evidence or paper records.

## Research Chronicle Contract

- Chronicle is the durable, auditable research-evolution record. Its canonical
  `mermaid` projection is a left-to-right year-anchor spine with thematic
  branches and nested sub-branches. Each child retains its own chronological
  year anchor while parent-to-child edges expose thematic lineage.
- Date precision governs complete and within-branch ordering. Equal-time ties
  retain stable input order without implying `PRECEDES`; undated evidence is
  explicit and sorted last.
- Branch membership is observational. `PRECEDES` requires definite chronology;
  the system does not infer `SUPERSEDES`, causal descent, or scientific
  retirement from absence in a later revision.
- Chronicle revision JSON remains immutable and authoritative. The index is a
  rebuildable cache; empty or failed retrieval cannot publish an evidence-free
  revision.

## Mermaid Reliability Contract

- Chronicle and other Mermaid-producing features share the structured graph
  kernel rather than assembling untrusted syntax independently.
- Labels, identifiers, topology, cycles, orphan edges, malformed data,
  Unicode/control characters, and node/byte limits are normalized and repaired
  deterministically.
- Rendering degrades through auditable `rich -> safe -> minimal` tiers.
  Corrections, warnings, omissions, validation state, and selected fallback
  tier remain visible instead of returning a blank diagram.
- Pinned real-render smoke coverage must parse generated runtime fixtures and
  selected repository/documentation Mermaid blocks to SVG.

## Documentation and Release Notes

- README, bilingual handbook sources, generated website content, tool index,
  Copilot/Cline guidance, architecture inventory, and quality audit must all
  describe the same 41-tool strict registry.
- `docs/UNIFIED_SEARCH_ARCHITECTURE.md` inventories every class/function reached
  by unified search and documents the execution flow and improvement seams.
- `docs/TOOL_QUALITY_AUDIT.md` records every public tool, shared primitives,
  eliminated duplicate surfaces, and remaining architectural opportunities.
- Preserve unrelated user workspace files and changes during release commits.

## Release Status

- v0.7.0 is merged at `459eb28`, tagged, and published from the canonical
  `origin/master` history.
- The post-release MCP acceptance branch has passed local transport, package,
  static, documentation, and repository-wide gates. Segmented commits, remote
  push, and hosted CI results remain pending until those actions actually
  complete.

---

*Last updated: 2026-09-01 — complete MCP protocol acceptance hardening*
