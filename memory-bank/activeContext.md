# Active Context

## Current Focus

- Prepare the v0.6.2 corrective release for Research Chronicle integrity and
  visualization hardening. The implementation and documentation are complete;
  release metadata, segmented commits, push, tag, and publication are the next
  lifecycle steps.
- Chronicle is the durable, auditable research-evolution record. Its canonical
  visual projection is a left-to-right year-anchor spine with observational
  topic branches, not a causal tree and not a list sorted only by publication
  year.

## v0.6.2 Chronicle Contract

- `mermaid` renders a canonical `flowchart LR`: year anchors form the horizontal
  spine, while date-precision-aware ordering governs the complete and
  within-branch entry lists. Equal-time ties retain stable input order without
  implying `PRECEDES`; undated evidence is explicit and sorted last.
- Repeated MeSH/keyword signals create semantic topic branches only when at
  least two supported branches cover at least 60% of events. Otherwise the
  Chronicle records a `research_stage_fallback` instead of overstating semantic
  lineage.
- Branch membership is observational. A paper has one primary branch and may
  retain matched signals/cross-links; overlap does not assert causality,
  succession, or replacement.
- `PRECEDES` is emitted only where chronology is definite. The system does not
  infer `SUPERSEDES`; absence from a later revision means
  `not_observed_in_revision`, not that the study or idea was retired.
- Event selection preserves chronological boundaries, explicit landmarks,
  cited evidence, and temporal coverage before applying output caps. Empty or
  failed retrieval cannot publish an evidence-free revision.
- Mermaid source is normalized and deterministically repaired for unsafe
  labels, duplicate identifiers, orphaned parents, self-loops, cycles, malformed
  rows, invalid dates, and byte/node limits. Rendering degrades through
  `rich -> safe -> minimal` tiers with corrections, warnings, omissions, and
  fallback metadata exposed instead of failing silently.
- Chronicle revision JSON files are immutable and authoritative. The index is a
  rebuildable cache; atomic publication and process/thread locks protect local
  persistence, and index corruption or staleness is repaired from revisions.
- Blocking Chronicle-store operations run through `asyncio.to_thread` from
  async application and MCP paths. Inputs, exact PMID sets, topic identity,
  revision direction, source coverage, prepared artifact file sets, persisted
  artifact checksums, and Mermaid renderability are validated at their owning
  boundaries.

## Validation Snapshot

- Complete non-integration suite: `3909 passed, 24 skipped, 30 deselected`.
- Strict mypy: 355 source/test files clean; Ruff and the async-test checker pass.
- Pinned Mermaid 11.16.1 with jsdom 26.1.0 parsed and rendered 47 repository,
  documentation, and runtime-fixture diagrams to SVG.
- Seeded hostile-input coverage passed, including 1,000 structural/determinism
  fuzz cases and real-render checks for unsafe Unicode and malformed graphs.
- Documentation, generated handbook mirrors, skills, Copilot/Cline guidance,
  and Chronicle contracts are synchronized.
- Live-integration caveat: three opt-in CORE/Unpaywall cases timed out during one
  upstream-network run. The deterministic/offline Chronicle suite remained
  green; treat those results as provider availability, not a Chronicle failure.

## Broader Runtime Snapshot

- `mcp>=2,<3` resolves to MCP/mcp-types 2.0.0. The public surface remains 45
  tools in 16 registry categories, presented as eight capability families.
- Stdio and explicit loopback HTTP are trusted single-user contracts with a
  durable default tenant. Remote/team service mode is authenticated,
  tenant-scoped, and fail-closed.
- Anonymous modern HTTP is request-scoped and non-durable. Transport/session
  identifiers are correlation only, never identity or a storage boundary.
- Multi-user service remains intentionally single-process/single-replica while
  state is filesystem-backed; horizontal scaling still requires a shared
  transactional store, distributed locks, object storage, and scheduler leader
  election.

## Repository Notes

- v0.6.1 remains the last published baseline until the v0.6.2 release lifecycle
  completes; do not describe the Chronicle hardening as already published.
- Preserve unrelated user workspace files and changes during release commits.
- The docs website is generated from the human handbook sources and must remain
  synchronized with README, tool contracts, skills, and generated mirrors.

---

*Last updated: 2026-08-12 — v0.6.2 Research Chronicle release checkpoint*
