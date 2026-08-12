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

- MCP: 45 tools in 16 registry categories, explained to users as eight
  capability families.
- Python SDK: `pubmed_search.api.PubMedSearchClient`.
- Deployment: stdio, trusted loopback Streamable HTTP, authenticated service
  mode, and Docker/Compose profiles.
- Durable outputs: tenant-scoped research artifacts, Chronicle revisions,
  pipelines, sessions, exports, and guided literature notes.

## Core Capabilities

- `unified_search`: PubMed-primary broker with explicit source plans, normalized
  provenance, partial-failure reporting, and durable evidence artifacts.
- Query strategy and PICO: MeSH-aware expansion, validation, and reproducible
  clinical-question pipelines.
- Discovery: related/citing/referenced articles and citation-tree inspection.
- Full text and figures: legal/access-aware retrieval and article-figure
  metadata with documented provider fallbacks.
- Research Chronicle: a revisioned evidence record with audit, diff, narrative,
  graph, milestones, and a canonical Mermaid research-history projection.
- Export and notes: RIS, BibTeX, CSV, MEDLINE, JSON/CSL, Markdown, Foam/wiki,
  and MedPaper-style profiles.
- Reference verification: PMID, DOI, ECitMatch, and title-based evidence paths.

## Research Chronicle User Promise (v0.6.2)

The Chronicle view lets a researcher see both order and thematic divergence:

- a horizontal year-anchor spine communicates the observed sequence, while
  date precision orders the full and within-branch entry lists;
- repeated MeSH/keyword signals form semantic branches only when at least two
  supported branches cover 60% of events; otherwise the view discloses its
  research-stage fallback;
- multi-topic papers retain matched signals/cross-links without duplicate
  identity;
- revisions and source metadata make the view auditable and reproducible;
- deterministic Mermaid repair and fallback prevent small syntax/data defects
  from blanking the entire diagram.

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

## Deployment and Trust Boundaries

- Stdio and explicit loopback HTTP are trusted single-user profiles with a
  durable local tenant.
- Remote/team service mode requires bearer principals and tenant-scoped state.
- Anonymous HTTP is request-scoped and non-durable; transport identifiers are
  not identity.
- Filesystem-backed service mode is single-process/single-replica. Distributed
  scaling requires a shared transactional store, distributed locking, object
  storage, and scheduler leadership.

## External-Service Reality

Search quality and live integration health depend on provider availability,
credentials, quotas, and access policy. CORE/Unpaywall opt-in tests can time out
when their upstream services are unavailable; these conditions must be reported
as provider diagnostics rather than fabricated empty evidence or Chronicle
entries.

---

*Last updated: 2026-08-12 — v0.6.2 release checkpoint*
