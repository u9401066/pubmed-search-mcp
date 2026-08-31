# Project Brief

## Purpose

**PubMed Search MCP Server** enables AI agents and Python applications to find,
trace, verify, and export biomedical literature through evidence-aware,
auditable workflows.

The project combines:

- MeSH-aware query construction and validation;
- PICO clinical-question workflows;
- PubMed-primary, multi-source literature discovery;
- related, citation, reference, full-text/access, and figure exploration;
- persistent research artifacts, pipelines, exports, and literature notes;
- a revisioned Research Chronicle for understanding how a topic developed.

## Research Chronicle Goal

A Chronicle should justify the claim that the system has reconstructed an
*observed research history*. Its canonical diagram therefore combines:

- a left-to-right year-anchor spine plus precision-aware evidence order;
- semantic topic branches for sufficiently supported recurring MeSH/keyword
  signals, with an explicit research-stage fallback when coverage is weak;
- cross-links for multi-topic papers;
- immutable revisions, evidence provenance, audit results, and forward diffs;
- separate requested/effective ranking plus typed iCite coverage, so an outage
  or empty response cannot be represented as zero citations or applied ranking;
- deterministic Mermaid repair and visible fallback diagnostics.

Nested themes must show both relationships at once: their parent thematic
branch and the year anchor that preserves the paper sequence. All Mermaid
features reuse the shared structured `rich -> safe -> minimal` repair kernel so
one malformed label or edge cannot blank an otherwise useful Chronicle.

This is an evidence map, not a causal genealogy. Branches do not prove causal
influence, chronology alone does not mean supersession, and absence from a later
revision does not mean that evidence has been refuted or retired.

## Target Users

- biomedical and translational researchers;
- clinicians preparing evidence reviews;
- systematic/scoping review teams;
- AI application developers and research-automation teams;
- users who need repeatable literature artifacts rather than chat-only answers.

## Success Criteria

- One documented MCP registry of 41 tools in 16 categories across stdio,
  Streamable HTTP, Copilot, and tests; removed public aliases do not survive as
  hidden compatibility surfaces. Profiling configuration cannot register a
  hidden tool, and canonical HTTP companion routes do not form a second
  registry.
- Stable Python SDK and Streamable HTTP contracts with documented trust and
  lifecycle boundaries; the SDK owns a lazy source runtime and exposes
  `async with`/`aclose()` cleanup. Its unified search composes the same
  application-owned use case as MCP but returns typed state without MCP
  formatting, journal, session, or artifact side effects.
- PubMed-primary retrieval with explicit provenance, provider errors, source
  coverage, and exact evidence identity.
- Typed source outcomes fail closed on source/operation mismatch, invalid
  runtime types, incoherent status/error state, or totals smaller than returned
  items. A provider outage or malformed payload cannot be represented as a
  successful empty page, and pagination metadata travels in the same typed
  result rather than client-side mutable state.
- Unified search planning/execution is application-owned and reached through
  explicit broker, registry, enrichment, progress, and observer ports;
  infrastructure clients and MCP persistence remain outer adapters.
- Optional enrichment uses immutable typed patches, stable candidate ties,
  fixed application order, final re-ranking, and sanitized diagnostics. There
  is no provider soft-fail flag, mutable last-error channel, duplicate rate
  limiter, or duplicate CORE/Europe PMC/Crossref/Unpaywall convenience facade.
- Persisted sessions use exact v1 schemas and first-class search runs. Runtime
  readers do not preserve or migrate legacy cache/history projections.
- Pipeline execution enforces aggregate run deadlines and external-call quotas;
  invalid definitions are rejected without an auto-repair surface.
- Pipeline templates accept only `template_params`; an explicit `kind` is never
  overwritten by inference. Action/template/dependency identifiers, enums, and
  all action-specific parameters reject fuzzy aliases and type/container
  coercion.
- Authenticated note export never returns a server filesystem path; it returns
  tenant-relative logical locators. Pipeline history never skips corrupt run
  records, and OpenURL configuration cannot embed query credentials or pretend
  ordinary search endpoints are link resolvers.
- NCBI EFetch/ESearch/ESummary/ELink response identity is fail-closed, and an
  explicit ClinicalTrials.gov adjunct carries the same versioned retrieval and
  formatting coverage through Markdown, structured output, and artifacts.
- Image search treats only an explicit valid zero page as empty. Open-i schema
  or row failures remain typed partial/failed coverage in structured and
  Markdown output, with unknown totals and sanitized diagnostics.
- DDD separation: presentation adapters remain thin; business rules live in
  application/domain layers.
- Each MCP server owns its session, strategy, pipeline, container, source, and
  HTTP-client lifecycle state; creating or closing another server cannot
  overwrite it.
- Scheduled pipelines retain the creating server's source runtime for the
  complete DAG. Host callbacks have a hard tool deadline; cancellation-resistant
  work is quarantined in a server-owned supervisor capped at 32 tasks and
  rejected when full. Citation expansion uses a separate 128-task owner, and
  both thin supervisors share `BoundedTaskSupervisor` lifecycle semantics.
- All URL-following provider paths share redirect-aware SSRF/DNS validation,
  byte caps, and total deadlines.
- Full-text discovery preserves immutable attempted/completed source coverage
  and sanitized failures end to end; a usable link plus one failed source is
  reported as partial rather than complete or empty. Only HTTP 204/404 or a
  successfully parsed zero-link response counts as absence; outage/parse
  failure becomes sanitized partial or unavailable coverage.
- Query generation reports spelling, MeSH, and query-analysis
  `completed`/`partial`/`failed` coverage. Provider outage cannot be represented
  as unchanged spelling, a completed no-match lookup, or a genuine zero-result
  query, and public warnings remain generic.
- ICD/MeSH mapping policy lives in the application layer, while image search
  accepts application-defined provider ports and a server-owned Open-i factory;
  presentation code does not own the terminology data and application code
  does not construct provider clients.
- Chronicle revisions are immutable/auditable, indexes recover from revisions,
  and async callers do not block on local persistence.
- Mermaid cannot fail wholesale because of a small label or topology defect;
  pinned CI parses and renders representative code/docs/runtime diagrams.
- Deterministic offline validation remains release-gating. Live-provider
  outages are reported separately and never converted into false evidence.
- Bilingual README/handbook, generated site content, skills, agent instructions,
  and tool contracts stay synchronized with behavior.
- The runtime-derived contract audit confirms 41 unique owners/16 categories,
  74 recursively closed object schemas, 215 explicitly bounded primitive or
  array nodes, and 10 exact tagged unions, plus coherent defaults and truthful
  behavior annotations.

## Scope and Boundaries

- The server retrieves and organizes literature evidence; it does not make
  clinical decisions or replace human critical appraisal.
- Full text and figures are limited by lawful availability, provider contracts,
  credentials, and publisher access. The project does not bypass paywalls.
- Provider quotas and outages are external constraints. NCBI API credentials
  can increase permitted request rate, but all clients must still obey source
  policy.
- Durable local artifacts are supported, but filesystem-backed service mode is
  intentionally single-process/single-replica until shared transactional state,
  distributed locks, object storage, and scheduler leader election exist.
- Zotero library management remains an external integration; this project
  supplies stable export/note handoffs rather than owning Zotero policy.
- Stdio never opens a background HTTP listener. The deleted standalone FastAPI
  presentation app and profiling monkeypatch are not supported deployment or
  extension points; companion HTTP routes run only inside the canonical HTTP
  application and its tenant/auth boundary.

## Release State

- The repository worktree is prepared for the breaking v0.7.0 hardening
  release: 41 strict tools, typed source/pipeline/session/Chronicle contracts,
  application-owned unified orchestration, a typed side-effect-free SDK search
  path, server-owned runtime state, shared bounded-task and safe-outbound
  primitives, one canonical HTTP application, and the enhanced horizontal
  Chronicle projection.
- Local full-suite/static/Mermaid/browser/package gates are complete. Segmented
  commits, remote CI, push, tag, and publication verification must complete
  before memory records v0.7.0 as published. The last published release remains
  historical release metadata, not the current implementation contract.

---

*Created: 2025-01 | Updated: 2026-09-01*
