# System Architect

> This file records the current architecture and durable architecture decisions.

## Current Runtime Contracts

- Canonical MCP registry: 41 tools in 16 categories. v0.7.0 intentionally
  removes public compatibility aliases, alternate tool registries, and legacy
  wrapper modules instead of routing them indefinitely.
- MCP tool surface: `uvx pubmed-search-mcp` for stdio and `/mcp` when served
  over Streamable HTTP.
- Python SDK facade: `pubmed_search.api.PubMedSearchClient` for in-process
  package and notebook callers. It lazily owns one `SourceRuntime`; use its
  async context manager or `aclose()` to close provider clients and HTTP pools.
  `unified_search()` composes the application use case directly and returns
  typed articles, source coverage/errors, and filter counts without creating
  MCP formatting, journal, session, or artifact side effects.
- Packaged HTTP launcher: `pubmed-search-mcp-http --transport streamable-http`.
- Canonical HTTP cache/session companion routes are convenience APIs on the
  same server/runtime, not the Python SDK contract and not another MCP tool
  registry. The orphan standalone FastAPI app and stdio background-HTTP bridge
  are removed; stdio opens no listener.
- MCP tools are thin presentation adapters. Business behavior belongs in the
  application/domain layers; infrastructure is reached through those
  boundaries.
- `read_session` and `read_research_chronicle` accept one strict,
  action-discriminated `request` object each. Pipeline configuration uses only
  canonical `output`, and template mode uses only `template_params`; retired
  `execution` and top-level template `params` inputs are rejected. Explicit
  pipeline `kind` is preserved and validated rather than overwritten by
  inference.
- PubMed, Scopus, and Web of Science expose one typed page result with items,
  total, offset/continuation, and warnings. Mutable metadata side channels,
  list-only search facades, and article-shaped failure sentinels are removed.
- External providers distinguish an authoritative empty page from transport,
  rate-limit, authentication, and malformed-payload failures. Provider outages
  must cross the application boundary as typed failures, never as `[]`.
- Full-text orchestration is owned by `application/fulltext`; duplicate
  infrastructure registry/service facades and downloader forwarding methods
  are not architectural seams. Extended link discovery uses one immutable
  `PDFLinkDiscoveryResult`; its attempted/completed source keys and sanitized
  failures remain attached through download and extraction. Only HTTP 204/404
  or a successfully parsed zero-link response completes as absence; outage and
  parse failure remain `partial`/`unavailable` coverage.
- Query intelligence treats spelling, MeSH, and PubMed query analysis as
  separately covered provider operations. Unchanged/no-match/zero are valid
  completed outcomes; failures publish `partial`/`failed` coverage and generic
  warnings rather than imitating those outcomes.
- Authenticated note-export presentation replaces all host paths with
  tenant-relative logical locators. OpenURL configuration admits only
  credential-free/query-free resolver bases, while DOI-resolution status is
  separate from access-probe status. Pipeline history is an all-or-error read:
  a selected corrupt run is never silently omitted.
- NCBI provider adapters validate EFetch/ESearch/ESummary/ELink envelopes before
  domain mapping. The optional ClinicalTrials.gov branch returns application-
  owned `clinical-trials-adjunct/v1` coverage; presentation renders Markdown or
  structured rows without changing the retrieval truth.
- Image source adapters return strict `ImageProviderSearchResult` values that
  the aggregation kernel projects into per-source coverage. Invalid pages or
  all-invalid rows are failed, mixed rows are partial, and presentation never
  invents empty/total/source-use claims.

## Current Layering

```text
Agent / SDK / HTTP client
           |
           v
presentation/  MCP registry, schemas, auth/request adapters, HTTP routes
           |
           v
application/   search, Chronicle, timeline, pipeline, export, sessions
           |
           v
domain/        evidence entities, value objects, domain services
           ^
           |
infrastructure/ NCBI and source clients, HTTP, cache, auth, scheduling
           |
           v
PubMed / PMC / Europe PMC / OpenAlex / Semantic Scholar / other providers
```

Dependencies point inward: presentation and infrastructure may depend on
application/domain contracts, but domain logic must not move into MCP tools,
hooks, or shell scripts.

## Research Chronicle Architecture (v0.7.0)

```text
retrieval + metadata
        |
        v
TimelineBuilder ---- sanitizes provider outcomes and date precision
        |
        v
Chronicle assembler ---- stable evidence identity + conservative lineage
        |
        +--> immutable authoritative revision JSON
        |          `--> rebuildable index cache
        |
        +--> audit / diff / narrative / graph projections
        |
        `--> structured Mermaid projection
                  |
                  +--> rich repair/validation
                  +--> safe fallback
                  `--> minimal fallback
```

The canonical Mermaid projection is `flowchart LR`. Year anchors form the
horizontal chronological spine; date precision orders the full and
within-branch entry lists. Repeated MeSH/keyword signals produce semantic topic
branches only when at least two supported branches cover at least 60% of
events; otherwise diagnostics disclose `research_stage_fallback`. Nested
sub-branches keep their own year-anchor attachment and also link to their
thematic parent, so the diagram exposes both sequence and divergence. A paper
keeps one primary branch and may expose matched signals/cross-links. The
structure communicates chronology and thematic development, not causality or
replacement.

Chronicle semantics are deliberately conservative:

- `PRECEDES` requires definite date ordering.
- `SUPERSEDES` is not inferred automatically.
- Missing evidence in a later snapshot is `not_observed_in_revision`.
- Importance ranking uses explicit landmark provenance (with documented
  citation fallback), not classifier detection confidence.
- Empty/failed retrieval cannot publish a revision.
- Topic retrieval separates requested from effective ranking. Its typed iCite
  coverage distinguishes complete, partial, empty, error, and not-requested;
  only validated, applied citation counts may activate iCite ordering, and the
  audit rejects contradictory provenance.

Mermaid is produced through the shared structured graph kernel, not
feature-specific concatenation of user text. The kernel normalizes labels,
repairs identifiers/topology, applies node, label, character, and UTF-8 byte
caps, and degrades deterministically through `rich -> safe -> minimal`.
Validation metadata records corrections, omissions, warnings, and fallback
tier. CI pins Mermaid 11.16.1 with jsdom 26.1.0 and requires real SVG rendering
of generated runtime fixtures plus selected repository and documentation
Mermaid blocks.

## Server-Owned Runtime Isolation

```text
PubMedMCPServer
  |
  +--> ToolSessionRuntime / tenant registry / session manager
  |          +--> HostCallbackRuntime / BoundedTaskSupervisor (max 32)
  |          `--> CitationTaskSupervisor / BoundedTaskSupervisor (max 128)
  +--> strategy registry / application container / pipeline runtime
  +--> scheduler -- binds owning runtime around the complete DAG
  `--> SourceRuntime / source contacts / source clients / shared HTTP pool

PubMedSearchClient
  `--> lazy independent SourceRuntime -- async with / aclose()
```

Server construction captures these dependencies once. A context-local token
binds them while one tool call executes, but process globals do not own or
replace them. Closing one server closes only its clients and cannot invalidate
another server or event loop. This keeps parallel stdio, HTTP, SDK, and test
servers deterministic and prevents tenant/source configuration bleed.

Upstream rate limiters, circuit breakers, and bulkheads remain deliberately
event-loop/provider scoped policy; mutable clients, contact identity, semantic
caches, citation exporters, and connection pools are runtime-owned.

The old profiling monkeypatch and hidden `get_performance_metrics` registration
are absent. Profiling configuration cannot mutate the public registry. HTTP
companion routes execute inside the canonical HTTP application with its
tenant/auth/runtime ownership; they do not recreate the deleted FastAPI
presentation app or maintain an alternate registry.

## Shared Bounded Task Ownership

`BoundedTaskSupervisor` is the shared ownership/reaping/capacity primitive for
best-effort asynchronous work. `HostCallbackRuntime` is a thin specialization
capped at 32 tasks: progress, log, and resource-update bridges observe the host
coroutine with `asyncio.wait` under a hard deadline, request cancellation on
timeout, and yield once rather than waiting indefinitely for a coroutine that
suppresses cancellation. `CitationTaskSupervisor` is a separate thin owner
capped at 128 pending citation expansions. Each server lifespan closes both;
capacity saturation disposes unstarted work instead of creating unbounded
detached tasks. Host timeout/failure remains best-effort, while cancellation of
the enclosing tool is re-raised.

## Unified Source Contract

- `SourceAdapterCall`, `SourceAdapterResult`, and `SourceAdapterError` are the
  canonical source execution envelope for shallow, relaxed, deep, full-text,
  preprint, and image paths.
- The shared validator requires exact expected source/operation identity,
  supported runtime types, matching nested error provenance, coherent
  `ok`/`empty`/`partial`/`error` state, and
  `total_count >= len(items) >= 0`; malformed outcomes become bounded source
  errors instead of leaking ambiguous data.
- Typed results preserve counts, cursor/cost/provenance, retryability, and
  partial failure. Presentation tools do not reinterpret provider dictionaries
  independently.
- `BaseAPIClient` has one transport-kernel rate/retry path and always raises a
  sanitized typed failure. The retired `strict_errors` switch, mutable
  last-error state, duplicate rate limiter, raw upstream reason logging, and
  duplicate CORE/Europe PMC search/getter and Crossref/Unpaywall lookup facades
  are not supported.

## Unified Search Application Boundary (v0.7.0)

```text
MCP registrar -> unified_runner -----------+
  journal / progress / format / artifact   |
                                            v
Python SDK ----------------------> UnifiedSearchUseCase
  typed result, no MCP side effects        |
                                  +---------+----------+
                                  |                    |
                                  v                    v
                         planner / executor     application ports
                                                       |
                                  +--------------------+------------------+
                                  v                    v                  v
                         UnifiedSourceBroker  UnifiedEnrichmentAdapter  registry
                             infrastructure      infrastructure       infrastructure
```

`application/unified` owns normalized requests, plans, execution policy,
deterministic ranking, outcomes, and the ports for progress, plan observation,
source selection/brokering, and enrichment. For `unified_search`, the MCP
runner owns SearchRun journaling and research-artifact adaptation; the SDK
projects the same typed application outcome without importing presentation.
Source and enrichment implementations remain outside the application layer and
are injected at the composition root.

Optional Crossref, journal-metrics, and Unpaywall work returns immutable typed
patches and sanitized outcome diagnostics. Candidate order uses the selected
ranking policy with a canonical identity tie-break, patches apply in fixed
provider/article order, and the final rank is recomputed after enrichment.
Provider completion timing therefore cannot change public ordering.

ICD/MeSH mappings, code validation, and lookup behavior live under
`application/search/icd.py`; `presentation/.../tools/icd.py` only registers and
formats the call. Image search similarly depends on the application-defined
`ImageSourceAdapter` and `OpenIClientPort`. `tool_registry.py` supplies the
server-owned Open-i client factory through `SourceRuntime`, so the application
service neither imports nor constructs infrastructure clients.

## Safe Outbound Boundary

All provider-directed or article-directed URL fetching passes through one
infrastructure boundary. It rejects unsupported schemes and embedded
credentials, resolves and validates destinations, blocks private/local/reserved
addresses, revalidates every redirect, and enforces response-byte and total
deadline limits. Full-text, figures, institutional access, and browser-assisted
paths therefore share the same SSRF, DNS-rebinding, redirect, and resource-cap
policy.

## Persistence and Concurrency

- Revision JSON is immutable and authoritative; the Chronicle index is a
  derived cache that can be rebuilt from revisions when missing, stale, or
  corrupt.
- Appends and index publication are atomic and guarded by process/thread locks.
- Blocking local-store reads/writes are invoked with `asyncio.to_thread` from
  async application and MCP paths so the event loop remains responsive.
- Session, cache, pipeline, Chronicle, artifact, and note state is tenant-bound.
  Service mode remains single-process/single-replica while persistence is local.
- Horizontal service scaling requires a shared transactional store, distributed
  locks, object storage, and scheduler leader election.

## Validation Boundaries

- Presentation schemas forbid unknown fields and constrain enumerations/ranges.
- Action-union tools validate their single nested request before dispatch;
  removed flat/alias shapes do not pass through a compatibility normalizer.
- Application services independently validate topic/id types, canonical topic
  identity, years, event limits, and positive ASCII PMID lists.
- Chronicle audits verify evidence identity, explicit PMID equality, lineage
  semantics, source coverage, graph completeness, Mermaid renderability, and
  the prepared artifact file set. The session artifact subsystem separately
  validates persisted locators, containment, and SHA-256 checksums.
- Provider errors and metadata-only rows remain retrieval diagnostics; they are
  never converted into evidence entries.
- A shared response boundary sanitizes Markdown/code spans and applies the
  global MCP output cap before content crosses the protocol boundary.
- A runtime-derived registry audit proves 41 unique tool owners in 16
  categories. It recursively closes all 74 object schemas, verifies explicit
  bounds on all 215 primitive/array nodes, and checks exact discriminator,
  required tag, and constant variant values for all 10 tagged unions. It also
  checks required/default coherence and annotation/side-effect agreement.
- Pipeline parsing uses a strict discriminated union. `kind` is inferred only
  when absent and an explicit value is never rewritten. Template pipelines
  accept only `template_params`; action/template/dependency identifiers and all
  action parameters reject aliases, fuzzy matching, and type/container
  coercion. Defaults apply only to omitted documented fields.

## Durable Architecture Decisions

### ADR-001: MCP as the Primary Agent Interface (2025-01)

Use MCP as the main agent protocol. The original SSE transport was later
superseded by stdio plus Streamable HTTP; the Python SDK facade is a separate
supported contract.

### ADR-002: Biopython Entrez Behind Infrastructure (2025-01)

Use Biopython Entrez for NCBI access, isolated behind infrastructure adapters.
Because Entrez is synchronous, async callers use `asyncio.to_thread` and share
the project rate-limiting policy.

### ADR-003: PubMed-Primary Multi-Source Evidence (2025-01 onward)

PubMed remains the primary biomedical corpus. Semantic Scholar, OpenAlex,
Europe PMC, and other admitted providers supplement citation, access, or corpus
coverage through normalized source contracts. A provider is admitted only when
it has a distinct evidence role and documented rate/provenance behavior.

### ADR-004: Chronicle as Persisted Source of Truth (2026-06 to 2026-08)

Chronicle is not a synonym for a timeline. It is an auditable, revisioned
evidence record whose timeline, graph, narrative, milestone, diff, and Mermaid
views are projections. The 2026-08-12 hardening makes immutable revisions the
authority and defines the canonical horizontal-spine/topic-branch projection.

### ADR-005: One Strict Tool and Source Contract (2026-08-31)

Publish one 41-tool/16-category registry across stdio, HTTP, Copilot, and tests.
Remove compatibility aliases and wrapper modules. Require discriminated request
objects, canonical pipeline `output`/`template_params`, caller-authoritative
discriminators, schema-exact action parameters, and validated typed source
outcomes so every execution surface fails the same way. Delete hidden profiling
registration and shadow presentation applications; supported HTTP companion
routes stay inside the canonical application and do not define another
registry.

### ADR-006: Runtime State Belongs to the Server That Created It (2026-08-31)

Make session, strategy, pipeline, container, source-contact, source-client, and
HTTP lifecycle state server-owned. Context-local binding may transport that
state through thin tools, but no mutable process-global registry is allowed to
overwrite another server.

The saved-pipeline runner binds the owning source/HTTP runtime around its full
DAG. The Python SDK is a separate lifecycle owner and closes its lazy runtime
through `async with` or `aclose()`.

### ADR-007: Await Host Callbacks Under a Real Deadline (2026-08-31)

Run progress, log, and resource-update callbacks through a server-owned bounded
supervisor. Observe each with a hard `asyncio.wait` deadline; on timeout,
request cancellation and yield once. Quarantine a callback that suppresses
cancellation, cap the quarantine at 32 tasks, reject new callbacks at capacity,
and close the supervisor from server lifespan. Treat host failure as
best-effort while preserving caller cancellation. Reuse the same
`BoundedTaskSupervisor` primitive for the independently owned citation-task
pool, capped at 128, rather than maintaining two task-lifecycle engines.

### ADR-008: Own Unified Search in the Application Layer (2026-09-01)

Use `UnifiedSearchUseCase` plus explicit planner, executor, source-broker,
source-registry, enrichment, progress, and observer ports as the shared normal
search boundary. MCP owns only protocol formatting, SearchRun journaling,
artifacts, and recovery; the Python SDK composes the same use case and returns
typed state without presentation imports or MCP side effects. Keep
`UnifiedSourceBroker`, enrichment, PubTator resolution, caches, and provider
clients as injected infrastructure adapters.

### ADR-009: Audit the Registered Schema and Close Feature DI Seams (2026-09-01)

Derive the schema audit from the actual 41-tool runtime instead of a parallel
manifest: require one owner per tool, recursive object closure, bounded
primitive/array nodes, exact discriminated unions, coherent defaults, and
truthful annotations. Keep ICD mapping policy in the application layer and
inject image-provider capabilities/factories into image search, so neither MCP
registrar contains domain data nor application service constructs Open-i.

---

*Last updated: 2026-09-01 — v0.7.0 strict runtime and Chronicle architecture*
