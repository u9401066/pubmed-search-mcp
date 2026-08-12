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
- deterministic Mermaid repair and visible fallback diagnostics.

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

- Stable MCP, Python SDK, and Streamable HTTP contracts with documented trust
  boundaries.
- PubMed-primary retrieval with explicit provenance, provider errors, source
  coverage, and exact evidence identity.
- DDD separation: presentation adapters remain thin; business rules live in
  application/domain layers.
- Chronicle revisions are immutable/auditable, indexes recover from revisions,
  and async callers do not block on local persistence.
- Mermaid cannot fail wholesale because of a small label or topology defect;
  pinned CI parses and renders representative code/docs/runtime diagrams.
- Deterministic offline validation remains release-gating. Live-provider
  outages are reported separately and never converted into false evidence.
- Bilingual README/handbook, generated site content, skills, agent instructions,
  and tool contracts stay synchronized with behavior.

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

## Release State

- v0.6.1 is the last published baseline at this checkpoint.
- v0.6.2 is the prepared corrective release for Chronicle semantics,
  persistence integrity, validation, and Mermaid resilience; publication is a
  separate release-lifecycle step.

---

*Created: 2025-01 | Updated: 2026-08-12*
