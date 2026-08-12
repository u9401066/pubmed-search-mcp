# System Architect

> This file records the current architecture and durable architecture decisions.

## Current Runtime Contracts

- MCP tool surface: `uvx pubmed-search-mcp` for stdio and `/mcp` when served
  over Streamable HTTP.
- Python SDK facade: `pubmed_search.api.PubMedSearchClient` for in-process
  package and notebook callers.
- Packaged HTTP launcher: `pubmed-search-mcp-http --transport streamable-http`.
- Auxiliary HTTP cache/session routes are convenience APIs, not the Python SDK
  contract.
- MCP tools are thin presentation adapters. Business behavior belongs in the
  application/domain layers; infrastructure is reached through those
  boundaries.

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

## Research Chronicle Architecture (v0.6.2)

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
events; otherwise diagnostics disclose `research_stage_fallback`. A paper keeps
one primary branch and may expose matched signals/cross-links. The structure
communicates chronology and thematic divergence, not causality or replacement.

Chronicle semantics are deliberately conservative:

- `PRECEDES` requires definite date ordering.
- `SUPERSEDES` is not inferred automatically.
- Missing evidence in a later snapshot is `not_observed_in_revision`.
- Importance ranking uses explicit landmark provenance (with documented
  citation fallback), not classifier detection confidence.
- Empty/failed retrieval cannot publish a revision.

Mermaid is produced from structured nodes/edges, not concatenated user text.
The renderer normalizes labels, repairs identifiers/topology, applies node,
label, character, and UTF-8 byte caps, and degrades deterministically through
`rich -> safe -> minimal`. Validation metadata records corrections, omissions,
warnings, and fallback tier. CI pins Mermaid 11.16.1 with jsdom 26.1.0 and
requires real SVG rendering of generated runtime fixtures plus selected
repository and documentation Mermaid blocks.

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
- Application services independently validate topic/id types, canonical topic
  identity, years, event limits, and positive ASCII PMID lists.
- Chronicle audits verify evidence identity, explicit PMID equality, lineage
  semantics, source coverage, graph completeness, Mermaid renderability, and
  the prepared artifact file set. The session artifact subsystem separately
  validates persisted locators, containment, and SHA-256 checksums.
- Provider errors and metadata-only rows remain retrieval diagnostics; they are
  never converted into evidence entries.

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

---

*Last updated: 2026-08-12 — v0.6.2 Research Chronicle architecture*
