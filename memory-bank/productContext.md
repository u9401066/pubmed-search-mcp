# Product Context

## Product Position

**PubMed Search MCP Server** gives AI agents and Python callers a professional,
auditable biomedical-literature workflow: query construction, multi-source
discovery, evidence inspection, full-text/access assistance, research-evolution
analysis, reference verification, pipelines, and reusable exports/artifacts.

Primary users are medical researchers, clinicians, systematic-review teams, AI
application developers, and teams automating evidence discovery. The product
helps them retrieve and organize evidence; it does not replace critical
appraisal, clinical judgment, or a systematic-review protocol.

## Product Surfaces

- MCP: 41 tools in 16 registry categories, explained to users as eight
  capability families. Stdio, HTTP, and Copilot launchers expose this same
  strict registry; removed aliases are not maintained as a second surface.
- Python SDK: `pubmed_search.api.PubMedSearchClient`, whose async context (or
  explicit `aclose()`) owns and closes its lazy provider/HTTP runtime. Its
  unified search returns typed articles, provider coverage/errors, and filter
  counts directly from the application use case; it does not create MCP
  response strings, sessions, SearchRun journals, or artifacts.
- Deployment: stdio, trusted loopback Streamable HTTP, authenticated service
  mode, and Docker/Compose profiles. Stdio never starts a background HTTP
  listener; canonical cache/session companion routes live on the supported HTTP
  application and are not a second registry.
- Durable outputs: tenant-scoped research artifacts, Chronicle revisions,
  pipelines, sessions, exports, and guided literature notes.

## Core Capabilities

- `unified_search`: PubMed-primary broker with explicit source plans, normalized
  provenance, typed source outcomes, fail-closed contract validation,
  partial-failure reporting, and durable evidence artifacts.
- Unified orchestration: MCP and SDK share the application-owned
  `UnifiedSearchUseCase` and explicit planner/executor/broker/registry/
  enrichment ports. MCP adds durable journal/artifact behavior; SDK use remains
  typed and side-effect-free with respect to MCP persistence.
- Search result semantics: successful empty pages are distinct from unavailable
  or malformed providers; page totals and continuation stay attached to their
  source result, so coverage claims cannot depend on mutable side channels.
- Query strategy and PICO: MeSH-aware expansion, validation, and reproducible
  clinical-question pipelines with one `template_params` contract,
  caller-authoritative mode discrimination, and schema-exact fail-closed action
  parameters. `generate_search_queries` separately reports spelling, MeSH, and
  query-analysis `completed`/`partial`/`failed` coverage, so provider failure
  cannot masquerade as unchanged spelling, no match, or a zero-result query.
- Discovery: related/citing/referenced articles and citation-tree inspection.
- Full text and figures: legal/access-aware retrieval and article-figure
  metadata with documented provider fallbacks. Typed attempted/completed
  source coverage makes partial access results and sanitized failures explicit;
  only HTTP 204/404 or a successfully parsed zero-link response means absence,
  while outage/parse failure yields `partial` or `unavailable`.
- Biomedical terminology and images: the curated ICD/MeSH policy is an
  application capability, and image search receives explicit provider ports
  plus a server-owned Open-i factory instead of constructing infrastructure
  clients inside the application service.
- Research Chronicle: a revisioned evidence record with audit, diff, narrative,
  graph, milestones, and a canonical Mermaid research-history projection.
- Export and notes: RIS, BibTeX, CSV, MEDLINE, JSON/CSL, Markdown, Foam/wiki,
  and MedPaper-style profiles. Authenticated responses expose tenant-relative
  logical locators rather than server paths.
- Reference verification: PMID, DOI, ECitMatch, and title-based evidence paths.
- Institutional access: credential-free/query-free OpenURL bases plus explicit
  PMID-to-DOI `resolved` / `not_found` / `error` diagnosis. Pipeline history
  fails closed when a selected persisted run is malformed.
- NCBI records: exact EFetch/ESearch/ESummary/ELink envelopes and requested-row
  identity. ClinicalTrials.gov remains opt-in and publishes one versioned
  coverage contract for Markdown, JSON/TOON, and persisted artifacts.
- Biomedical image evidence: strict Open-i page/row validation plus typed
  per-source `completed`/`empty`/`partial`/`failed` coverage; failed sources do
  not contribute a known total or `sources_used` claim.

## Research Chronicle User Promise (v0.7.0)

The Chronicle view lets a researcher see both order and thematic divergence:

- a horizontal year-anchor spine communicates the observed sequence, while
  date precision orders the full and within-branch entry lists;
- repeated MeSH/keyword signals form semantic branches only when at least two
  supported branches cover 60% of events; otherwise the view discloses its
  research-stage fallback;
- nested topics retain a link to their parent theme and to their own year
  anchor, making both the branch hierarchy and paper order visible;
- multi-topic papers retain matched signals/cross-links without duplicate
  identity;
- revisions and source metadata make the view auditable and reproducible;
- requested and effective ranking remain separate, while typed iCite coverage
  makes complete, partial, empty, and failed enrichment visible;
- deterministic Mermaid repair and fallback prevent small syntax/data defects
  from blanking the entire diagram. Chronicle and other graph features reuse
  one structured `rich -> safe -> minimal` repair kernel.

The promise is intentionally evidence-bounded. A branch is an observational
classification, not proof that one research program caused another. The system
does not infer that a later paper supersedes an earlier one, nor that a paper
missing from a later retrieval is scientifically obsolete.

## Current Architecture and Stack

```text
presentation (MCP / HTTP / SDK adapters)
                 |
                 v
application (search / Chronicle / pipeline / export / session)
                 |
                 v
domain (evidence entities and rules)
                 ^
                 |
infrastructure (NCBI/source clients, HTTP, cache, auth, scheduling)
```

| Category | Current contract |
|----------|------------------|
| Language | Python >= 3.10 |
| Dependency management | `uv` / `uv run` |
| MCP | `mcp>=2,<3`, protocol 2026-07-28 era |
| HTTP | async `httpx`; sync Entrez isolated with `asyncio.to_thread` |
| Tests | pytest, pytest-asyncio, strict mypy, Ruff, custom contract checks |
| Visualization | Mermaid 11.16.1 + jsdom 26.1.0 pinned in real-render CI |
| Packaging/deployment | PyPI, stdio, Streamable HTTP, Docker/Compose |

The registered schema itself is audited as product behavior: 41 unique owners
in 16 categories, 74 recursively closed object schemas, 215 bounded primitive/
array nodes, and 10 exact tagged unions. This audit also checks parameter
defaults and side-effect annotations, so documentation is not the sole source
of the contract claim.

## Deployment and Trust Boundaries

- Stdio and explicit loopback HTTP are trusted single-user profiles with a
  durable local tenant.
- Remote/team service mode requires bearer principals and tenant-scoped state.
- Anonymous HTTP is request-scoped and non-durable; transport identifiers are
  not identity.
- Session, strategy, pipeline, container, source-contact, and source-client
  lifecycle state belongs to the server that created it. Starting or closing a
  second server cannot mutate the first server's state.
- Saved scheduler jobs rebind the owning server's source and shared-HTTP
  runtime around the whole pipeline DAG. An in-process SDK client owns a
  separate lazy `SourceRuntime` and must be closed with `async with` or
  `aclose()`.
- Host progress, log, and resource-update callbacks run under a hard deadline.
  A stalled callback is cancelled; if it suppresses cancellation, it remains in
  a server-owned quarantine capped at 32 tasks rather than blocking the tool.
  New callbacks are rejected when that supervisor is full, and server shutdown
  cancels owned callbacks with bounded grace.
- Host callbacks and citation expansion share the reusable
  `BoundedTaskSupervisor` ownership primitive while remaining independent
  server-owned pools: host capacity is 32 and citation capacity is 128. Server
  shutdown closes both.
- The environment-dependent profiling monkeypatch, hidden performance tool,
  orphan standalone FastAPI app, and stdio background-HTTP bridge are removed.
  Environment toggles therefore cannot change the public tool count or select
  a shadow presentation application.
- Filesystem-backed service mode is single-process/single-replica. Distributed
  scaling requires a shared transactional store, distributed locking, object
  storage, and scheduler leadership.

## External-Service Reality

Search quality and live integration health depend on provider availability,
credentials, quotas, and access policy. CORE/Unpaywall opt-in tests can time out
when their upstream services are unavailable; these conditions must be reported
as provider diagnostics rather than fabricated empty evidence or Chronicle
entries.

Every URL-following provider path uses the same safe-outbound policy: validate
scheme, credentials, DNS/IP destination, every redirect, byte budget, and total
deadline. Private/local/reserved destinations and public-to-private redirects
fail closed.

## v0.7.0 Contract Expectations

- Action families use one discriminated request envelope, including
  `read_session(request={...})` and
  `read_research_chronicle(request={...})`.
- Pipelines use canonical `output` and template `template_params` only. An
  explicit `kind` is never overwritten; action/template/dependency names,
  enums, containers, identifiers, and all action-specific parameters reject
  fuzzy aliases and type coercion. Defaults apply only when a documented field
  is omitted.
- Source outcomes expose coherent `ok`/`empty`/`partial`/`error` state with
  exact source/operation provenance and totals that cannot be smaller than the
  returned item count.
- Crossref, journal-metrics, and Unpaywall enrichment returns immutable typed
  patches and sanitized provider outcomes, applies them in deterministic order,
  and recomputes final rank. Provider completion timing cannot change the
  published ordering.
- Provider clients have no soft-fail switch. Duplicate CORE/Europe PMC
  search/getter and Crossref/Unpaywall lookup facades are gone; upstream faults
  cross the typed boundary and cannot be reinterpreted as authoritative empty
  evidence.
- Agent handoffs return directly executable canonical arguments; global output
  caps and shared Markdown sanitation protect every tool response.
- Breaking cleanup is intentional. Removed public aliases and presentation
  wrappers should not be reintroduced without a new product-level decision.
- HTTP companion routes share the canonical server registry and tenant/auth
  runtime; they must not grow into another MCP surface.

---

*Last updated: 2026-09-01 — v0.7.0 breaking-hardening release candidate*
