# Research Chronicle, Timeline, And Graph Rebuild Spec

Status: Phases 0-6 implemented (snapshot, evidence, delta, narrative, graph, chronological lineage map, integrity hardening)
Last updated: 2026-08-12
Scope: this document is now both the design contract and the implementation reference.

## 0. Implementation Status

The Research Chronicle described below is implemented and shipped.

| Layer | Module |
| --- | --- |
| Domain | `src/pubmed_search/domain/entities/chronicle.py` |
| Application | `src/pubmed_search/application/chronicle/` (`assembler`, `lineage`, `ordering`, `graph`, `mermaid`, `audit`, `projectors`, `narrator`, `differ`, `store`, `service`) |
| Presentation | `src/pubmed_search/presentation/mcp_server/tools/chronicle.py` |
| Tests | `tests/test_chronicle.py`, `tests/test_chronicle_mermaid*.py`, `tests/test_chronicle_projection_robustness.py`, `tests/test_chronicle_semantic_hardening.py`, `tests/test_chronicle_revision_integrity.py`, and `tests/test_chronicle_cross_projection_integrity.py` |

The planned six chronicle tools were consolidated into two, matching the repo's
facade convention (`read_session`, `manage_pipeline`):

| Planned tool | Shipped as |
| --- | --- |
| `build_research_chronicle` | `build_research_chronicle(topic=..., pmids=..., chronicle_id=...)` |
| `update_research_chronicle` | `build_research_chronicle(chronicle_id=...)` — writes revision N+1 |
| `load_research_chronicle` | `read_research_chronicle(action="load", ...)` |
| `list_research_chronicles` | `read_research_chronicle(action="list", ...)` |
| `diff_research_chronicle` | `read_research_chronicle(action="diff", ...)` |
| `narrate_research_chronicle` | `read_research_chronicle(action="narrate", ...)` |

The three timeline tools were also folded in rather than kept alongside the
chronicle, superseding section 12's backward-compatibility note:

| Retired tool | Replacement |
| --- | --- |
| `build_research_timeline` | `build_research_chronicle` |
| `analyze_timeline_milestones` | `read_research_chronicle(action="milestones")` |
| `compare_timelines` | `read_research_chronicle(action="compare", topics="a,b")` |

Because chronicles are persisted, milestone analysis and comparison read stored
evidence instead of re-running a search, and comparison additionally reports the
evidence articles two topics share. Topic comparison uses a normalized exact
stored-topic match. If more than one Chronicle has that topic, the request is
reported as ambiguous and must use distinct Chronicle IDs instead. The hardened
`application/timeline/` components feed the chronicle assembler as its evidence
provider.

### Final Integrity Semantics

- Topic builds pass year filters to PubMed before bounded retrieval. Final
  selection pins the first and last observed events, ranks explicit landmark
  importance/citations, and fills remaining capacity by temporal spread.
  Source coverage records `returned` and `available`; capped samples,
  downstream selection, and unknown availability produce warnings.
- PubMed error sentinels and zero-article scopes publish no revision. Explicit
  PMID input accepts only ASCII digits with an optional `PMID:` prefix and
  supported separators; DOI or arbitrary mixed text is not coerced.
- Entry IDs use PMID, then DOI, as stable evidence identity across date and
  classifier corrections. Chronicle derivation, exact topic lookup,
  comparison, and continuity share one NFC/case-folded/whitespace-collapsed
  canonical topic key while preserving the stored display topic.
- Semantic lineage gives each paper one primary branch and retains other
  selected-signal matches as explicit cross-links. Overlap at or above 20% of
  all or assigned entries is an audit warning, not evidence of cleanly
  separated or causal lineages.
- Entry `confidence` is milestone-detection confidence. Landmark ranking uses
  explicit landmark importance and citation count fallback; detection
  confidence is excluded from scientific-importance ordering.
- Revision absence is always observational: `not_observed_in_revision` and
  `removed_from_view`. The legacy `retired` field is only a compatibility alias
  and is never conclusive retirement.
- Artifact-bundle preflight checks the names emitted by the actual payload
  builder plus the store-generated manifest. It verifies preparation, not
  persistence success.

### Chronology Is The Primary Axis

The chronicle stores entries, branches, and a typed graph; the linear timeline
and the branch tree are both *projections*, so there is no storage-level choice
between them. The product decision is that **chronology is the primary axis and
branches are the secondary organizing dimension** - that is what makes the
artifact a chronicle rather than a taxonomy. The default `output="summary"`
therefore leads with the chronological spine and lists research lines beneath it.

The canonical visual projection is now the **chronicle map**. It keeps one
horizontal year spine and anchors every observed research line at the year of
its earliest dated paper **within the retrieved scope**; this does not establish
the field's first publication. Entries within a branch retain both global
chronological order and branch-local order. These branches are explainable
groupings of the selected evidence, not causal ancestry. Semantic branches
prefer distinctive MeSH descriptors and author keywords shared by multiple
papers; a singleton term is not sufficient. If signals cannot support at least
two branches with adequate coverage, the system falls back to deterministic
research-stage branches and emits an audit warning. A stage fallback must not be
described as discovered semantic topic evolution.

Chronology preserves year/month/day precision. A deterministic display order
may place two records from the same year, but `precedes` or `supersedes` is only
asserted when their reported date intervals prove the relationship. The topic
query or PMID set, source availability, year filters, and result limits remain
part of the interpretation boundary for every Chronicle.

Also fixed during implementation: `build_research_timeline(pmids="last")`
resolved session PMIDs instead of passing the `"last"` sentinel through to PMID
fetch; the behavior carried over to `build_research_chronicle`.

## 1. Purpose

The project exposed useful research-evolution features, but the terms
`timeline`, `research tree`, `context graph`, `citation tree`, and `research
chronicle` had drifted across code and documentation. This spec records the
implemented consolidation and its compatibility boundaries.

The main decision is:

> **Research Chronicle** is the durable, versioned, evidence-backed source of
> truth for one retrieval-bounded snapshot. Timeline, lineage tree, context
> graph, citation graph, and narrative outputs are projections from chronicle or
> graph data, not separate competing source-of-truth models.

## 2. Canonical Terminology

| Term | Current status | Canonical meaning |
| --- | --- | --- |
| Research Timeline | Retired as an MCP tool | A chronological milestone view. Now the `timeline` projection of a chronicle. |
| Research Lineage Tree | Implemented as `ResearchTree` | A deterministic, retrieval-bounded branch projection using shared semantic signals or an explicit research-stage fallback. It is neither causal genealogy nor a general knowledge graph. |
| Research Context Graph Preview | Implemented as `unified_search(options="context_graph")` | A lightweight preview synthesized from the current ranked PMID-backed search results. It is not persisted and is not a full graph. |
| Citation Tree | Implemented as `build_citation_tree` | A single-seed citation network using forward/backward citation relationships. |
| Research Chronicle | Implemented | A persisted, versioned, evidence-backed record of the selected retrieval scope, with entries, evidence bundles, typed provenance graph, revisions, deltas, audit files, and projections. |

Documentation must reserve **Research Chronicle** for the persisted,
evidence-backed artifact. `timeline`, `tree`, and `chronicle_map` are projections;
`unified_search(options="context_graph")` remains a non-persisted preview.

## 3. Pre-Rebuild Implementation Audit (Historical)

> This section preserves the audit inputs that motivated the rebuild. It does
> not describe the current MCP surface; see Section 0 for the shipped modules
> and Section 8 for current tool outputs.

### 3.1 Historical MCP Surface

| Capability | Current entry point | Files | Notes |
| --- | --- | --- | --- |
| Timeline | `build_research_timeline` | `src/pubmed_search/presentation/mcp_server/tools/timeline.py` | Returns a string in `text`, `tree`, `mindmap`, `mermaid`, `json`, `json_tree`, `timeline_js`, or `d3`. |
| Timeline analysis | `analyze_timeline_milestones` | same | Returns JSON string with distribution, periods, diagnostics, optional landmark studies, and activity by year. |
| Timeline comparison | `compare_timelines` | same | Compares two to five topics. |
| Context graph preview | `unified_search(options="context_graph")` | `unified_helpers.py`, `unified_execution.py`, `unified_formatting.py` | Builds a temporary timeline/tree from up to 20 ranked PMIDs and includes preview text / JSON `research_context`. |
| Citation tree | `build_citation_tree` | `src/pubmed_search/presentation/mcp_server/tools/citation_tree.py` | Produces citation graph formats: `cytoscape`, `g6`, `d3`, `vis`, `graphml`, `mermaid`. |

### 3.2 Historical Domain And Application Types

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

### 3.3 Pre-Rebuild Gaps

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

## 4. Implemented Architecture

### 4.1 Layering

The implementation preserves the repo's DDD direction:

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

### 4.2 Modules

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
    graph.py
    lineage.py
    mermaid.py
    narrator.py
    ordering.py
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
revision. Stored revisions are never overwritten; next-revision allocation and
publication occur under a per-Chronicle process/thread-safe lock with atomic
file publication.

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

This scope is a scientific interpretation boundary. In particular,
`earliest_observed_in_scope` means the earliest dated record among the retrieved
candidates after these constraints; it is not a claim about the first paper in
the full field.

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

`entry_id` is evidence-identity-stable: PMID is preferred, DOI is the secondary
identity, and publication date or milestone classification is excluded from the
seed. Continuing an older Chronicle reuses unambiguous historical IDs by
evidence identity so corrections appear as updates.

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

Semantic branches require a distinguishing MeSH/keyword signal observed in more
than one paper. Singleton-only or otherwise insufficient signals use the
deterministic research-stage fallback and must produce an audit warning. Branch
membership is observational organization, not evidence of causal descent; the
interface may later support additional clustering methods without changing that
interpretation rule.

When one paper matches several selected signals, the tree records one primary
assignment and retains secondary memberships as explicit `cross_signal_links`
in lineage diagnostics. An overlap ratio at or above 0.20, measured over all
entries or assigned entries, produces a warning that the branches are not
cleanly separated.

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
- `precedes` and `supersedes` are emitted only when reported date precision
  proves the temporal order; stable display order is not sufficient.
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
| `chronicle_map` | Combined chronological and lineage view | Horizontal year anchors, ordered entry IDs, earliest-observed-in-scope branch points, global/branch display order, lineage basis, and Mermaid `flowchart LR` renderer. It does not assert causal branching or same-year precedence. |
| `context_preview` | Lightweight inline preview for `unified_search` | Max 20 PMID-backed records, never advertised as complete. |
| `citation_graph` | Seed or chronicle-wide citation relationships | Nodes + edges, all supported graph formats. |
| `narrative` | Evidence-backed prose | Every substantive claim cites entry IDs and PMIDs/DOIs. |
| `delta_report` | Revision comparison | Added/updated/not-observed entries, evidence flips, branch changes, unresolved conflicts. `retired` is a compatibility alias for `not_observed_in_revision` / `removed_from_view`, not a conclusive lifecycle claim. |

The retired timeline tool concepts remain available through Chronicle output
modes. `timeline_mermaid` is the bounded flat compatibility view; `mermaid` is
the canonical combined chronological-lineage map.

## 7. Artifact Envelope Contract

When session artifact persistence is enabled, Chronicle outputs use the existing
artifact-as-token-offload pattern. Inline MCP responses are index cards; full
evidence belongs in files retrievable through `read_session`. The immutable
Chronicle revision store is separate: a revision may be saved successfully even
if preparation or persistence of the optional session artifact later fails.

Preflight derives its file-name evidence from the concrete artifact payload
builder, then adds the manifest generated by the artifact store. Passing
preflight means the payload was prepared completely; only the persistence
result/locator can establish that it was written.

Each successfully persisted Chronicle artifact uses schema
`research-chronicle-artifact/v1` and writes:

- `manifest.json`
- `snapshot.json`
- `chronicle_map.json`
- `chronicle.mmd`
- `mermaid_validation.json`
- `timeline.json`
- `lineage_tree.json`
- `graph.json`
- `evidence.json`
- `milestones.json`
- `audit.json`
- `narrative.md`
- `response.md`

On artifact success, the inline response includes:

- `chronicle_id`
- `revision`
- `topic`
- event/entry counts
- source coverage summary
- audit status
- warnings
- artifact locator with `artifact_id`, `artifact_uri`, file inventory, read
  order, and paged `read_session(...)` examples

If artifact persistence was enabled but returns no locator or raises after the
revision was saved, Markdown exposes a warning and structured output includes
`artifact.status="failed"`. The response must not imply that the artifact exists.

Remote clients and sandboxed agents must be able to retrieve every file via:

```text
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="audit.json")
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="snapshot.json", offset=0, max_chars=200000)
```

Local filesystem paths remain optional debug metadata and are redacted by
default.

## 8. MCP API Design

### 8.1 Current Tools

Current tools remain:

- `build_research_chronicle`
- `read_research_chronicle`
- `unified_search(options="context_graph")`
- `build_citation_tree`

The Chronicle wrappers validate arguments, call `ChronicleService`, format the
requested projection, and attach artifact locators. Retrieval, assembly,
lineage inference, repair, audit, persistence, and comparison remain in the
application layer.

### 8.2 Chronicle Tool Surface

- `build_research_chronicle(topic=None, pmids=None, max_events=30,
  min_year=None, max_year=None, chronicle_id=None, output="summary")`
- `read_research_chronicle(action="load", chronicle_id=None, revision=None,
  from_revision=None, to_revision=None, topic=None, topics=None,
  chronicle_ids=None, output="summary", mode="brief", limit=20)`

Read actions are `load`, `list`, `diff`, `narrate`, `milestones`, and `compare`.
Rebuilding with an existing `chronicle_id` writes revision N+1, so separate
update/diff/narrate MCP tools are unnecessary.

Current bounds are enforced in both the MCP schema and runtime validation:
`max_events` 1–200, up to 500 unique explicit PMIDs, topic text up to 500
characters, list limits 1–100, positive revisions, and comparisons of 2–5
distinct Chronicles. `topics=...` comparison uses normalized exact stored-topic
matching; zero matches are not found, multiple matches are ambiguous, and
callers can disambiguate with `chronicle_ids=...`.

Topic-mode `min_year` / `max_year` filters are sent to PubMed before the bounded
fetch and are also defended locally. Zero usable articles and PubMed error
sentinels return an error without allocating a revision. Explicit PMID tokens
are strict and never inferred by stripping non-digits from DOI or mixed text.

### 8.3 Output Modes

Structured modes should be parseable without stripping prose:

- `summary`: compact Markdown + artifact locator
- `json`: `ChronicleSnapshot` JSON
- `chronicle_map`: combined horizontal-spine/lineage projection JSON
- `timeline`: timeline projection JSON
- `tree`: lineage tree projection JSON
- `graph`: typed graph JSON
- `narrative`: evidence-backed Markdown
- `delta`: revision delta JSON
- `mermaid`: combined horizontal-spine/lineage Mermaid flowchart
- `timeline_mermaid`: legacy flat Mermaid timeline

If a tool returns Markdown plus JSON for compatibility, the structured payload
must also be present in the prepared artifact bundle and, on successful
persistence, in the stored artifact.

Validation and not-found errors for JSON projections and structured read actions
remain JSON rather than switching to prose.

## 9. Audit And Completeness Requirements

`ChronicleAudit` must report:

- input counts: requested PMIDs, retrieved articles, excluded articles
- source coverage: returned/available counts per source where known
- evidence coverage: entries with supporting evidence, conflicting evidence,
  missing identifiers, missing year, missing DOI/PMID
- branch coverage: empty branches, orphan entries, unassigned entries
- lineage semantics: MeSH/keyword basis, semantic coverage, selected signals,
  singleton rejection, and explicit research-stage fallback warnings
- Mermaid renderability: deterministic structural validation, correction list,
  rich/safe/minimal tier, source digest, and omitted visual item counts
- graph integrity: invalid edge endpoints, duplicate node IDs, invariant
  violations
- chronology checks: impossible dates, earliest-observed scope provenance, and
  supersedes/precedes edges unsupported by reported date precision
- narrative checks: claims without entry IDs or evidence IDs
- artifact bundle/preflight checks: required prepared files, schema versions,
  and read order (not a claim that persistence itself succeeded)
- selection semantics: chronological boundaries, landmark/citation priority,
  temporal spread, and warnings whenever retrieval or output caps prevent an
  exhaustive view
- lineage overlap: primary assignment, secondary cross-links, and a warning at
  20% overlap among all or assigned entries
- ranking semantics: milestone-detection confidence is reported separately and
  excluded from landmark-importance ordering

Audit findings use `pass`, `warn`, or `fail` with actionable messages.

### 9.1 Mermaid repair contract

The canonical renderer consumes the structured `chronicle_map` instead of
concatenating user text into Mermaid syntax. It normalizes controls and bidi
characters, entity-escapes delimiters inside quoted labels, assigns opaque
collision-resistant node IDs, removes cyclic parents, repairs orphan branches,
deduplicates repeated visual entries, and caps graph size. Serialization then
falls through `rich -> safe -> minimal`; a rendering failure must never abort
chronicle creation. Any omitted content or fallback tier is disclosed in
`mermaid_validation.json`, while the complete records remain in JSON artifacts.

`chronicle.mmd` is pure Mermaid source. Markdown fences and persistent-artifact
notes belong only in `response.md` or the inline response. CI uses Mermaid
11.16.1 to parse and render current rich, repaired, safe, minimal, timeline, and
mindmap fixtures to SVG; documentation rendering isolates failures per diagram
and preserves the failed source visibly.

## 10. Completed Rebuild Phases

The following phase list records the shipped Chronicle implementation. Earlier
proposals for six separate MCP tools were consolidated into the two-tool facade.

### Phase 0: Documentation And Contract Alignment

- Align the spec, README, user docs, docs site, and agent routing language.
- Distinguish Chronicle projections from context-graph previews and citation trees.

### Phase 1: Current Feature Hardening

- Resolve `pmids="last"` through session state and validate output modes.
- Preserve article MeSH, keyword, publication, and identifier context across the
  timeline boundary.
- Add regression coverage for timeline, tree, graph, and citation projections.

### Phase 2: Chronicle Snapshot Foundation

- Add Chronicle domain entities, serialization, store/index, and monotonic revisions.
- Assemble snapshots from topic searches, explicit PMIDs, and session PMIDs.
- Persist `research-chronicle-artifact/v1` envelopes and expose build/read facades.

### Phase 3: Evidence And Delta

- Preserve evidence bundles and source coverage.
- Add revision update and diff services behind build/read actions.

### Phase 4: Narrative And Graph Analytics

- Add evidence-backed narrative generation with strict citation IDs.
- Add typed graph and milestone analytics behind application services.
- Expose narrative, milestones, and comparisons as read actions.

### Phase 5: Chronological Lineage Map And Mermaid Hardening

- Derive explainable topic branches from MeSH descriptors and author keywords,
  with an explicit research-stage fallback.
- Add the horizontal `chronicle_map` coordinate contract and canonical Mermaid
  flowchart.
- Add deterministic repair, bounded output, rich/safe/minimal fallback,
  validation artifacts, per-diagram docs isolation, and real Mermaid SVG CI.

### Phase 6: Scientific And Persistence Integrity Hardening

- Treat the first dated record as earliest-observed-in-scope provenance without
  masking its actual milestone type; preserve ordinary papers from explicit
  PMID sets.
- Reject singleton semantic signals, preserve biomedical slash terms, and make
  stage fallback warnings explicit.
- Share precision-aware chronology across projections, graph, audit, and
  narrative; do not infer temporal edges for equal or overlapping precision.
- Make revisions immutable and atomically allocated, use exact topic comparison
  with explicit ambiguity, expand revision diffs, and surface artifact failure.
- Bound MCP inputs and keep structured-action errors machine-readable.

## 11. Acceptance And Regression Tests

### Surface Regression Tests

- `build_research_chronicle(pmids="last")` resolves the previous search PMID
  list or returns a clear error when no last search exists.
- Build/read support every documented output mode and reject unknown modes.
- Timeline, lineage tree, Chronicle map, and graph projections share stable
  Chronicle entry IDs.
- Context graph preview covers: no PMID results, empty timeline, builder
  exception, 20-PMID cap, JSON `research_context`, and provenance metadata.
- Citation tree tool-level tests cover: `forward`, `backward`, `both`, depth
  recursion, duplicate suppression, invalid direction, invalid format,
  `cytoscape`, `g6`, `d3`, `vis`, `graphml`, and `mermaid`.

### Chronicle Tests

- Chronicle entities round-trip through JSON without losing required fields.
- Chronicle graph invariants reject invalid edges.
- Store creates monotonic revisions and stable `chronicle_id`.
- Concurrent revision allocation is atomic and stored revisions cannot be
  overwritten.
- Snapshot assembly preserves source counts, query strategy, PMIDs, and
  artifact provenance.
- PubMed errors/no-results publish no revision; year filters reach PubMed;
  returned/available counts and capped/unknown coverage remain auditable.
- Event caps preserve chronological boundaries, landmark importance, and
  temporal spread without using detection confidence as importance.
- PMID/DOI entry identity and canonical topic normalization remain stable across
  reclassification, correction, lookup, comparison, and continuation.
- Diff absence is non-conclusive and semantic overlap preserves cross-links,
  warning at the 20% threshold.
- Projection outputs are generated from the same snapshot and reference the same
  entry IDs.
- Audit catches missing evidence, duplicate IDs, missing required artifact
  bundle files, unsupported chronology edges, projection membership mismatch,
  and narrative claims without evidence IDs.
- Earliest-observed provenance, singleton fallback, exact/ambiguous comparison,
  and structured validation errors have focused regression coverage.
- MCP wrappers reject malformed PMID strings, return compact summaries with
  artifact locators and remote-safe `read_session` hints, and preflight the
  actual artifact payload.

## 12. Backward Compatibility

- The retired one-shot timeline MCP tools are replaced by
  `build_research_chronicle` and `read_research_chronicle`; their concepts remain
  available as chronicle projections.
- Keep citation-tree tool names and formats stable.
- Keep MCP Markdown responses readable and structured modes parseable.
- Keep `unified_search(options="context_graph")` as preview-only.
- Resolve `pmids="last"` through session state before Chronicle retrieval.

## 13. Documentation Rules

After this spec lands:

- `README.md` and `README.zh-TW.md` are entry points, not detailed specs.
- `docs/TOOLS_USAGE_GUIDE*.md` define current tool routing.
- `docs/ADVANCED_RESEARCH_WORKFLOWS*.md` show user workflows.
- This file defines the implemented Chronicle contract and its historical rationale.
- Generated docs in `docs/site-content/` and `docs/site-content.js` must be
  rebuilt from canonical sources.
- Agent instructions should use this terminology:
  - "timeline/lineage tree" for Chronicle projections
  - "context graph preview" for `unified_search(options="context_graph")`
  - "citation tree" for `build_citation_tree`
  - "Research Chronicle" only for the persisted/versioned artifact

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

The implementation does not grow another mode-heavy timeline tool. It uses a
Chronicle bounded context with typed, persisted, auditable, retrieval-bounded
snapshots. Timeline, tree, chronological-lineage map, graph, and narrative views
are projections from that source of truth; their branches remain observational,
not causal claims, while MCP tools remain thin application wrappers.
