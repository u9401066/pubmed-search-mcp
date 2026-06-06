<!-- Generated from docs/RESEARCH_CHRONICLE_REFACTOR_SPEC.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# Research Chronicle, Timeline, And Graph Rebuild Spec

Status: Canonical pre-rebuild spec v2
Last updated: 2026-06-06
Scope: design/specification only; this document prepares the next implementation cycle.

## 1. Purpose

The project currently exposes useful research-evolution features, but the terms
`timeline`, `research tree`, `context graph`, `citation tree`, and `research
chronicle` have drifted across code and documentation. This spec consolidates
the current state and defines the target design for the next full rebuild.

The main decision is:

> A future **Research Chronicle** is the durable, versioned,
> evidence-backed source of truth. Timeline, lineage tree, context graph,
> citation graph, and narrative outputs are projections from chronicle or graph
> data, not separate competing source-of-truth models.

## 2. Canonical Terminology

| Term | Current status | Canonical meaning |
| --- | --- | --- |
| Research Timeline | Implemented | A chronological milestone view built from topic search or explicit PMIDs. |
| Research Lineage Tree | Implemented as `ResearchTree` | A deterministic branch projection from timeline events by milestone type. It is a tree/branch view, not a general knowledge graph. |
| Research Context Graph Preview | Implemented as `unified_search(options="context_graph")` | A lightweight preview synthesized from the current ranked PMID-backed search results. It is not persisted and is not a full graph. |
| Citation Tree | Implemented as `build_citation_tree` | A single-seed citation network using forward/backward citation relationships. |
| Research Chronicle | Planned | A persisted, versioned, evidence-backed research artifact with entries, evidence bundles, typed provenance graph, revisions, deltas, audit files, and projections. |

Documentation must not call the current timeline tool a complete Research
Chronicle. Until the rebuild lands, say "timeline/lineage tree" for current
features and "planned Research Chronicle" for this design.

## 3. Current Implementation Audit

### 3.1 MCP Surface

| Capability | Current entry point | Files | Notes |
| --- | --- | --- | --- |
| Timeline | `build_research_timeline` | `src/pubmed_search/presentation/mcp_server/tools/timeline.py` | Returns a string in `text`, `tree`, `mindmap`, `mermaid`, `json`, `json_tree`, `timeline_js`, or `d3`. |
| Timeline analysis | `analyze_timeline_milestones` | same | Returns JSON string with distribution, periods, diagnostics, optional landmark studies, and activity by year. |
| Timeline comparison | `compare_timelines` | same | Compares two to five topics. |
| Context graph preview | `unified_search(options="context_graph")` | `unified_helpers.py`, `unified_execution.py`, `unified_formatting.py` | Builds a temporary timeline/tree from up to 20 ranked PMIDs and includes preview text / JSON `research_context`. |
| Citation tree | `build_citation_tree` | `src/pubmed_search/presentation/mcp_server/tools/citation_tree.py` | Produces citation graph formats: `cytoscape`, `g6`, `d3`, `vis`, `graphml`, `mermaid`. |

### 3.2 Existing Domain And Application Types

- `domain/entities/timeline.py`
  - `MilestoneType`
  - `EvidenceLevel`
  - `LandmarkScore`
  - `TimelineEvent`
  - `TimelinePeriod`
  - `ResearchTimeline`
- `domain/entities/research_tree.py`
  - `ResearchBranch`
  - `ResearchTree`
- `application/timeline/`
  - `TimelineBuilder`
  - `MilestoneDetector`
  - `LandmarkScorer`
  - `build_research_tree`
  - milestone/landmark policies and diagnostics helpers

### 3.3 Current Known Gaps

These are rebuild inputs, not incidental polish:

- No `ChronicleSnapshot`, `ChronicleEntry`, `EvidenceBundle`, revision store,
  diff model, narrative model, or chronicle MCP tools exist in `src/`.
- `pmids="last"` is documented for timeline workflows but currently normalizes
  to `["last"]` and is passed to PMID fetch instead of resolving session PMIDs.
- `build_research_timeline(output_format="d3")` returns timeline nodes but no
  links, so it is not a complete graph contract.
- `ResearchTree.to_text_tree()` still contains mojibake-like connector strings;
  tests do not assert clean tree connectors.
- `ResearchTimeline.to_mermaid()` / `to_json_timeline()` and
  `ResearchTree.to_text_tree()` / `to_mermaid_mindmap()` are presentation
  projections living on domain entities.
- `citation_tree.py` contains traversal, graph construction, and format
  converters inside the MCP presentation layer. This violates the DDD boundary:
  MCP tools should be thin wrappers over application services.
- Context graph preview is silently omitted when ranked results lack PMIDs,
  timeline building emits no events, or the builder raises an exception.
- Current timeline artifacts are not persisted with the research artifact
  envelope used by `unified_search`.

## 4. Target Architecture

### 4.1 Layering

The rebuild must preserve the repo's DDD direction:

```text
presentation/mcp_server/tools
  -> application/chronicle
  -> application/timeline and application/citation_graph ports
  -> domain/entities
  -> infrastructure adapters
```

Business logic must not live in MCP tool functions. Tool modules validate
inputs, call application services, format responses, and attach artifact
locators.

### 4.2 Proposed Modules

```text
src/pubmed_search/
  domain/entities/
    chronicle.py
    research_graph.py
  application/chronicle/
    __init__.py
    assembler.py
    audit.py
    differ.py
    narrator.py
    projectors.py
    service.py
    store.py
  application/citation_graph/
    __init__.py
    builder.py
    formatters.py
    models.py
  presentation/mcp_server/tools/
    chronicle.py
```

`application/citation_graph` extracts the current citation traversal and format
conversion logic from `presentation/mcp_server/tools/citation_tree.py`. The
existing MCP tool remains, but becomes a wrapper.

### 4.3 Application Ports

The chronicle service should depend on small ports, not concrete tool modules:

- `ArticleEvidenceProvider`
  - Search by topic.
  - Fetch details by PMID.
  - Resolve `pmids="last"` from session state.
  - Attach source-count and query-strategy metadata when available.
- `CitationGraphProvider`
  - Build citation neighborhoods from seed PMIDs.
  - Return typed graph nodes/edges.
- `SessionProvenanceProvider`
  - Read search history, artifact locators, and pipeline run identifiers.
- `ChronicleArtifactStore`
  - Persist chronicle artifact envelopes.
  - Read by `artifact_id` / `artifact_uri`.
  - Support remote-safe pagination through `read_session`.

## 5. Target Domain Model

### 5.1 ChronicleSnapshot

`ChronicleSnapshot` is the immutable source-of-truth object for one chronicle
revision.

Required fields:

- `schema_version: Literal["research-chronicle/v1"]`
- `chronicle_id: str`
- `topic: str`
- `revision: int`
- `created_at: str`
- `updated_at: str`
- `input_scope: ChronicleInputScope`
- `entries: list[ChronicleEntry]`
- `branches: list[ChronicleBranch]`
- `graph: ChronicleGraph`
- `audit: ChronicleAudit`
- `metadata: dict[str, Any]`

### 5.2 ChronicleInputScope

Captures how the chronicle was produced:

- `mode: Literal["topic", "pmids", "session", "artifact", "pipeline"]`
- `query: str | None`
- `pmids: list[str]`
- `source_artifact_uris: list[str]`
- `pipeline_run_ids: list[str]`
- `filters: dict[str, Any]`
- `source_counts: dict[str, Any]`

### 5.3 ChronicleEntry

One interpretable research event or claim.

Required fields:

- `entry_id: str`
- `entry_type: Literal["milestone", "evidence_shift", "guideline", "safety", "method", "controversy", "background"]`
- `title: str`
- `time_start: str`
- `time_end: str | None`
- `summary_claim: str`
- `branch_id: str | None`
- `confidence: float`
- `status: Literal["active", "superseded", "contested", "background"]`
- `evidence: EvidenceBundle`
- `tags: list[str]`
- `provenance: dict[str, Any]`

Every entry must have at least one supporting, updating, or contradicting
article unless its status is explicitly `background`.

### 5.4 EvidenceBundle

Evidence must be structured so narratives can cite concrete sources.

Required fields:

- `supporting_articles: list[EvidenceArticle]`
- `contradicting_articles: list[EvidenceArticle]`
- `updating_articles: list[EvidenceArticle]`
- `verification_summary: dict[str, Any]`
- `source_coverage: dict[str, Any]`

`EvidenceArticle` fields:

- `pmid: str | None`
- `doi: str | None`
- `pmcid: str | None`
- `title: str`
- `year: int | None`
- `source: str`
- `journal: str | None`
- `article_type: str | None`
- `citation_count: int | None`
- `rcr: float | None`
- `claim_excerpt: str | None`
- `fulltext_artifact_uri: str | None`
- `figure_links: list[dict[str, str]]`
- `reference_verification_status: str | None`

### 5.5 ChronicleBranch

Branches organize entries into readable research lines.

Required fields:

- `branch_id: str`
- `name: str`
- `description: str`
- `parent_branch_id: str | None`
- `entry_ids: list[str]`
- `confidence: float`
- `tags: list[str]`

The initial implementation may keep deterministic branch policies from
`application/timeline/branch_detector.py`, but the interface must allow later
community detection or semantic clustering.

### 5.6 ChronicleGraph

The graph is typed and auditable. It is not a generic unbounded knowledge graph.

Node types:

- `Topic`
- `Branch`
- `ChronicleEntry`
- `EvidenceArticle`
- `SessionEvent`
- `PipelineRun`
- `Artifact`

Edge types:

- `precedes`
- `branches_from`
- `supports`
- `contradicts`
- `updates`
- `supersedes`
- `observed_in_session`
- `derived_from_pipeline_run`
- `persisted_as_artifact`

Invariants:

- `supports`, `contradicts`, and `updates` connect `EvidenceArticle` to
  `ChronicleEntry`.
- `precedes` and `supersedes` connect `ChronicleEntry` to `ChronicleEntry`.
- `branches_from` connects `Branch` to `Branch`.
- `observed_in_session` connects `SessionEvent` to evidence or entries.
- `persisted_as_artifact` connects snapshots/projections to artifact nodes.
- Graph builders must dedupe nodes by stable IDs.

## 6. Projection Contract

The chronicle is source of truth. These projections may be materialized:

| Projection | Purpose | Contract |
| --- | --- | --- |
| `timeline` | Chronological milestone/event list | JSON object plus text/mermaid renderers. |
| `lineage_tree` | Branch-oriented view | JSON tree plus text/mindmap renderers. |
| `context_preview` | Lightweight inline preview for `unified_search` | Max 20 PMID-backed records, never advertised as complete. |
| `citation_graph` | Seed or chronicle-wide citation relationships | Nodes + edges, all supported graph formats. |
| `narrative` | Evidence-backed prose | Every substantive claim cites entry IDs and PMIDs/DOIs. |
| `delta_report` | Revision comparison | Added/updated/retired entries, evidence flips, branch changes, unresolved conflicts. |

Existing timeline tools remain compatible. A future implementation may build
their output from chronicle projectors internally, but external tool names and
basic return shape should not break without a major release.

## 7. Artifact Envelope Contract

Chronicle outputs must use the existing artifact-as-token-offload pattern.
Inline MCP responses are index cards; full evidence belongs in files retrievable
through `read_session`.

Each persisted chronicle uses schema `research-chronicle-artifact/v1` and should
write:

- `manifest.json`
- `snapshot.json`
- `timeline.json`
- `lineage_tree.json`
- `graph.json`
- `evidence.json`
- `audit.json`
- `narrative.md` when requested
- `delta.json` when comparing revisions
- `response.md` when a Markdown response was generated

The inline response must include:

- `chronicle_id`
- `revision`
- `topic`
- event/entry counts
- source coverage summary
- audit status
- warnings
- artifact locator with `artifact_id`, `artifact_uri`, file inventory, read
  order, and paged `read_session(...)` examples

Remote clients and sandboxed agents must be able to retrieve every file via:

```text
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="audit.json")
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="snapshot.json", offset=0, max_chars=200000)
```

Local filesystem paths remain optional debug metadata and are redacted by
default.

## 8. MCP API Design

### 8.1 Preserve Current Tools

Current tools remain:

- `build_research_timeline`
- `analyze_timeline_milestones`
- `compare_timelines`
- `unified_search(options="context_graph")`
- `build_citation_tree`

Required fixes before or during rebuild:

- Resolve `pmids="last"` through session PMIDs or remove the claim from docs and
  tool examples until it is supported.
- Validate `output_format` explicitly and return actionable errors for invalid
  values.
- Move format rendering out of domain entities.
- Move citation graph traversal/formatting out of presentation.

### 8.2 Planned Chronicle Tools

Introduce these only after the application/domain layer exists:

- `build_research_chronicle(topic=None, pmids=None, artifact_uri=None, pipeline=None, output="summary")`
- `load_research_chronicle(chronicle_id, revision="latest", artifact_file=None, offset=0, max_chars=200000)`
- `list_research_chronicles(topic=None, limit=20)`
- `update_research_chronicle(chronicle_id, topic=None, pmids=None, artifact_uri=None)`
- `diff_research_chronicle(chronicle_id, from_revision, to_revision="latest")`
- `narrate_research_chronicle(chronicle_id, revision="latest", mode="brief")`

Tool wrappers must stay thin. Business logic belongs in
`application/chronicle/service.py`.

### 8.3 Output Modes

Structured modes should be parseable without stripping prose:

- `summary`: compact Markdown + artifact locator
- `json`: `ChronicleSnapshot` JSON
- `timeline`: timeline projection JSON
- `tree`: lineage tree projection JSON
- `graph`: typed graph JSON
- `narrative`: evidence-backed Markdown
- `delta`: revision delta JSON

If a tool returns Markdown plus JSON for compatibility, the structured payload
must also be saved to artifacts.

## 9. Audit And Completeness Requirements

`ChronicleAudit` must report:

- input counts: requested PMIDs, retrieved articles, excluded articles
- source coverage: returned/available counts per source where known
- evidence coverage: entries with supporting evidence, conflicting evidence,
  missing identifiers, missing year, missing DOI/PMID
- branch coverage: empty branches, orphan entries, unassigned entries
- graph integrity: invalid edge endpoints, duplicate node IDs, invariant
  violations
- chronology checks: impossible dates, unordered supersedes/precedes edges
- narrative checks: claims without entry IDs or evidence IDs
- artifact checks: required files present, schema versions, read order

Audit findings use `pass`, `warn`, or `fail` with actionable messages.

## 10. Rebuild Phases

### Phase 0: Documentation And Contract Alignment

- Rewrite this spec as the single source of truth.
- Update README, user docs, docs site, memory-bank notes, and agent routing
  language to distinguish current timeline/tree features from planned
  chronicle.
- Stop advertising unsupported `pmids="last"` timeline behavior until fixed.

### Phase 1: Current Feature Hardening

- Add tests and fix `pmids="last"` resolution.
- Add timeline output-format matrix tests.
- Clean ResearchTree mojibake connector output.
- Move timeline/tree formatters out of domain entities.
- Extract citation graph builder/formatters into application services.
- Add citation tree response contract tests for all supported formats.

### Phase 2: Chronicle Snapshot Foundation

- Add chronicle domain entities and serialization tests.
- Add chronicle store/index/revision persistence.
- Assemble snapshots from topic searches, explicit PMIDs, and session/artifact
  inputs.
- Persist `research-chronicle-artifact/v1` envelopes.
- Add build/load/list MCP wrappers.

### Phase 3: Evidence And Delta

- Add `EvidenceBundle` enrichment from citation metrics, reference
  verification, fulltext artifacts, and figure links where available.
- Add revision update and diff services.
- Add `update_research_chronicle` and `diff_research_chronicle`.

### Phase 4: Narrative And Graph Analytics

- Add evidence-backed narrative generation with strict citation IDs.
- Add graph analytics behind application services, not MCP wrappers.
- Add `narrate_research_chronicle`.
- Consider community detection only after deterministic branch projections are
  stable.

## 11. Acceptance Tests For The Next Rebuild

### Current Feature Regression Tests

- `build_research_timeline(pmids="last")` resolves the previous search PMID
  list or returns a clear error when no last search exists.
- `build_research_timeline` supports every documented output format:
  `text`, `tree`, `mermaid`, `mindmap`, `json`, `json_tree`, `timeline_js`,
  `d3`.
- Invalid timeline `output_format` returns an actionable error.
- `ResearchTimeline` and `ResearchTree` projections are tested with real domain
  fixtures, not only fake timeline objects.
- Context graph preview covers: no PMID results, empty timeline, builder
  exception, 20-PMID cap, JSON `research_context`, and provenance metadata.
- Citation tree tool-level tests cover: `forward`, `backward`, `both`, depth
  recursion, duplicate suppression, invalid direction, invalid format,
  `cytoscape`, `g6`, `d3`, `vis`, `graphml`, and `mermaid`.

### Chronicle Tests

- Chronicle entities round-trip through JSON without losing required fields.
- Chronicle graph invariants reject invalid edges.
- Store creates monotonic revisions and stable `chronicle_id`.
- Snapshot assembly preserves source counts, query strategy, PMIDs, and
  artifact provenance.
- Projection outputs are generated from the same snapshot and reference the same
  entry IDs.
- Audit catches missing evidence, duplicate IDs, missing required artifact
  files, and narrative claims without evidence IDs.
- MCP wrappers return compact summaries with artifact locators and remote-safe
  `read_session` hints.

## 12. Backward Compatibility

- Keep existing timeline and citation tree tool names.
- Keep existing MCP string responses unless a caller requests structured output.
- Keep `unified_search(options="context_graph")` as preview-only.
- Add chronicle tools as new capabilities, not as silent behavior changes.
- If `pmids="last"` cannot be fixed immediately, remove it from examples until
  it is implemented and tested.

## 13. Documentation Rules

After this spec lands:

- `README.md` and `README.zh-TW.md` are entry points, not detailed specs.
- `docs/TOOLS_USAGE_GUIDE*.md` define current tool routing.
- `docs/ADVANCED_RESEARCH_WORKFLOWS*.md` show user workflows.
- This file defines the planned chronicle rebuild.
- Generated docs in `docs/site-content/` and `docs/site-content.js` must be
  rebuilt from canonical sources.
- Agent instructions should use this terminology:
  - "timeline/lineage tree" for current `build_research_timeline`
  - "context graph preview" for `unified_search(options="context_graph")`
  - "citation tree" for `build_citation_tree`
  - "Research Chronicle" only for the planned persisted/versioned artifact

## 14. Subagent Audit Inputs

This spec incorporates three independent read-only audits:

- Implementation/API audit: confirmed current MCP surfaces, lack of chronicle
  code, DDD boundary issues, `pmids="last"` gap, and context graph preview
  semantics.
- Documentation audit: found stale format lists, overloaded chronicle wording,
  context graph wording that needs constraints, and stale public draft/tool
  counts.
- Test audit: found missing output-format, context graph boundary, citation tree
  contract, real projection, and chronicle persistence tests.

## 15. Decision Summary

The next rebuild should not grow another mode-heavy timeline tool. It should
create a chronicle bounded context with typed, persisted, auditable artifacts.
Timeline, tree, graph, and narrative views become projections from that source
of truth, while existing MCP tools remain stable wrappers for compatibility.
