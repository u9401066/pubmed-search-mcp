# Active Context

## Current Focus

- v0.6.1 hardening release: MCP SDK v2 public APIs, a registry-backed
  multi-source broker, explicit local/service deployment contracts,
  tenant-safe persistence, refreshed bilingual handbook/site/wiki assets, and
  release-grade edge/smoke coverage.

## Validation Snapshot

- Non-integration suite: `3759 passed, 22 skipped, 30 deselected`.
- Opt-in live API suite: `28 passed, 2 skipped, 3768 deselected`; Europe PMC
  and CORE were the two unreachable-provider skips.
- Real stdio/modern HTTP/fresh-wheel entrypoint smoke: `33 passed`.
- Documentation/site/wiki integrity: `27 passed`.
- Ruff check/format, strict mypy over `src/` and `tests/`, async-test checker,
  lockfile check, and whitespace check pass.
- Browser QA passes at 1440×1000 and 390×844 with no console, page, or request
  errors; Mermaid renders to SVG, bilingual/mobile routes work, and routed
  cross-page anchors resolve to verified heading ids.
- The public MCP surface is 45 tools in 16 registry categories, documented as
  eight user-facing capability families.

## Architecture Snapshot

- `mcp>=2,<3` resolves to locked MCP/mcp-types 2.0.0. Production middleware,
  tool enumeration, Copilot helpers, and diagnostics use public SDK v2
  surfaces; modern HTTP does not depend on initialize/session lifecycle.
- Local stdio and explicit loopback HTTP are trusted single-user contracts
  with a durable default tenant. Service mode is a separate fail-closed bearer
  principal contract with tenant-scoped state and artifacts.
- Anonymous modern HTTP is request-scoped and non-durable. Legacy transport
  identifiers are correlation only, never identity or a storage boundary.
- Main HTTP auxiliary routes, opt-in stdio HTTP, and the browser fetch broker
  enforce Host/Origin boundaries. The browser broker binds to loopback and
  generates a high-entropy token when none is supplied.
- Copilot/ngrok public launchers always use authenticated service mode; local
  Copilot and HTTPS helpers bind only to loopback, and the HTTPS helper exposes
  both liveness and readiness probes.
- Tenant ids use an opaque normalized marker so raw principals cannot collide
  with an existing storage id or claim the reserved local default tenant.
- Exports use opaque tenant-bound identifiers. Service callers cannot read
  arbitrary pipeline files or choose note/template filesystem paths.
- Session/cache/pipeline/chronicle/artifact/note persistence is protected for
  MCP v2 worker-thread execution with locking, atomic publication, detached
  snapshots, containment checks, and concurrency regressions.
- The source broker preserves explicit/deep/preprint plans, honors disabled
  sources, constrains one shared upstream quota per provider, reports partial
  errors, and deterministically deduplicates provider identifiers. Token-bucket
  waits account for elapsed time exactly once, preventing post-wait bursts.
- No additional provider was added without a distinct corpus, identifier, or
  access-path contract. Optional licensed Scopus/Web of Science remain
  explicitly credential-gated.
- Multi-user service is intentionally single-process/single-replica until a
  shared transactional store, distributed locks, object storage, and scheduler
  leader election exist. Service Compose disables the local scheduler.

## Repository Notes

- The workspace was synchronized to upstream v0.6.0 before this release work.
- The user's pre-sync untracked harness assets remain recoverable in
  `stash@{0}: codex-pre-upstream-sync-2026-08-09`; do not drop it implicitly.
- The docs website is the complete human handbook extending README, with
  generated content checked against its source documents.

---

*Last updated: 2026-08-09 — v0.6.1 release hardening*
