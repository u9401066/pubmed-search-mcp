<!-- Generated from docs/TOOLS_USAGE_GUIDE.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# PubMed Search MCP Tools Usage Guide

Capability-first guide for using the 45-tool PubMed Search MCP surface without treating the tool list as a menu to memorize.

**Language**: **English** | [繁體中文](#/tools-usage-guide-zh)

## Reading Order

1. Start with the capability family that matches the user intent.
2. Use session tools to reuse the latest result set instead of asking the model to remember PMIDs.
3. Export citations or notes only after the evidence set is clear.
4. Use the raw [tools index](#/quick-reference) only when you need exact tool names.

## The 8 Capability Families

![PubMed Search MCP capability map](images/tool-capability-map.svg)

| Capability | Primary Tools | Use When |
| --- | --- | --- |
| Search entry | `unified_search` | The user wants papers, articles, or a first pass over a topic. |
| Query intelligence | `analyze_search_query`, `parse_pico`, `generate_search_queries` | The query needs MeSH, agent-provided PICO handoff, synonym expansion, or strategy planning. |
| Discovery | `fetch_article_details`, `find_related_articles`, `find_citing_articles`, `get_article_references`, `build_citation_tree` | The user has seed PMIDs and wants context, related work, or citation lineage. |
| Full text and figures | `get_fulltext`, `get_text_mined_terms`, `get_article_figures` | The user needs article body text, evidence sections, entities, captions, or image URLs. |
| External biomedical data | `search_gene`, `get_gene_details`, `search_compound`, `get_compound_details`, `search_clinvar` | The research question moves from papers into NCBI gene, compound, or clinical variant data. |
| Evaluation and research evolution | `get_citation_metrics`, `build_research_chronicle`, `read_research_chronicle` | The user asks what matters, what changed over time, or how fields compare. |
| Persistence and sessions | `read_session`, `get_session_pmids`, `get_cached_article`, `get_session_summary`, pipeline tools | The user wants to resume, repeat, audit, schedule, or save a search workflow. |
| Export and local notes | `prepare_export`, `save_literature_notes` | The user wants Zotero/EndNote/BibTeX files or local Markdown/wiki notes. |

## Intent Routing

| User Intent | Recommended Flow |
| --- | --- |
| Quick literature search | `unified_search(query=..., limit=...)` |
| Clinical comparison | Agent P/I/C/O -> `parse_pico` -> `unified_search(pipeline="template: pico...")` |
| Systematic review seed | `analyze_search_query` -> `generate_search_queries` -> `unified_search(options="systematic")` -> `save_pipeline` |
| Provider-native semantic retrieval | `unified_search(sources="openalex", options="native_semantic")` |
| Important paper exploration | `fetch_article_details` -> `find_related_articles` / `find_citing_articles` / `get_article_references` |
| Full-text synthesis | `get_fulltext` -> `get_text_mined_terms` -> structured summary |
| Zotero handoff | `prepare_export(pmids="last", format="ris")` or Zotero Keeper import tools |
| Local knowledge-base notes | `save_literature_notes(pmids="last")` |
| Repeatable search workflow | `save_pipeline` -> `unified_search(pipeline="saved:<name>")` |

Zotero Keeper should remain an external integration boundary. PubMed Search MCP produces official RIS/MEDLINE/CSL JSON exports, local RIS/BibTeX/CSV/MEDLINE/JSON exports, and local wiki notes; Zotero Keeper or another client owns Zotero import, duplicate handling, and library-specific policies.

## Capability Workflow Diagrams

Each feature family has a workflow diagram so users and developers can see where a tool sits in the larger research path.

### Search Entry And Query Intelligence

![Search and query intelligence workflow](images/search-query-workflow.svg)

Use this path for `unified_search`, `parse_pico`, `generate_search_queries`, `analyze_search_query`, and ICD-aware search preparation. The important boundary is that the agent performs semantic PICO extraction, while `parse_pico` validates the structured handoff and returns a backend `template: pico` pipeline.

There is exactly one generic literature-search tool. Choose its retrieval
policy with `options` instead of looking for provider-specific search tools:

| Policy | Example | Contract |
| --- | --- | --- |
| Default | `unified_search(query="sepsis biomarkers")` | Relevance/keyword routing across the normal capable source plan. |
| Native semantic | `unified_search(query="mechanisms of resistance", sources="openalex", options="native_semantic")` | OpenAlex title/abstract semantic retrieval; provider maximum 50. |
| Systematic | `unified_search(query="melanoma AND immunotherapy", sources="pubmed,openalex,semantic_scholar", options="systematic")` | Deterministic, bounded provider execution: OpenAlex cursor and Semantic Scholar bulk where selected. |

`native_semantic` and `systematic` are mutually exclusive. Both disable the
multi-strategy deep-search expansion so the selected provider-native plan stays
auditable. An explicit unsupported source/mode combination fails before the
network call; automatic routing retains capable sources only. The public
`limit` remains at most 100 per source, so `systematic` is a reproducible
retrieval primitive, not proof of exhaustive systematic-review coverage.

Input validation is strict and occurs before provider I/O. `limit` must be an
integer in `1..100`; filter tokens must use supported `key:value` forms; year
bounds must be within 1000–2100 and ordered; and unknown option flags, ranking
modes, or output formats are rejected instead of silently ignored. In normal
deep mode, the same public `limit` is the **total budget for one source across
all of its generated strategies**. The broker allocates that budget across the
strategies, clips over-returning adapters, and applies bounded global and
per-source concurrency plus strategy deadlines.

JSON/TOON output and persistent artifacts preserve `retrieval_mode` and
per-source `source_metadata`, including requested/provider mode, canonical or
compiled query, opaque continuation token/cursor when returned, cost/rate
metadata, and warnings. Continuation data is currently provenance only: the
public facade has no cursor-resume argument. Consult
[Source Contracts](#/source-contracts),
[Semantic Scholar](#/semantic-scholar-api), and [OpenAlex](#/openalex-api)
before interpreting provider totals or continuing a search.

For agent decisions on a normal result envelope, prefer the structured
`search_status` object over rendered text length. It labels the retrieval as
bounded and non-exhaustive and
separates `completed`, valid `empty`, `partial`, and all-source `failed`
outcomes. It also reports returned count, attempted/successful/failed/retryable
sources, continuation sources, and sources whose completeness is unknown.

ClinicalTrials.gov is an explicit adjunct, not another literature-search leg.
Use `options="trials"` only when a Markdown response should include up to three
related registry records. The request is never made by default, does not affect
article ranking/source counts, and is recorded separately in the search
artifact. JSON/TOON output does not run the display-only adjunct.

### Article Discovery And Citation Mapping

![Article discovery and citation workflow](images/discovery-citation-workflow.svg)

Use this path once you have one or more seed PMIDs. It covers `fetch_article_details`, `find_related_articles`, `find_citing_articles`, `get_article_references`, `build_citation_tree`, and `get_citation_metrics`.

### Reference Verification

![Reference verification workflow](images/reference-verification-workflow.svg)

Use `verify_reference_list` when a manuscript, bibliography, or generated answer needs PubMed-backed citation checking. Treat matches and mismatches as an audit trail, not as prose-only summary.

### Full Text, Figures, And Image Evidence

![Full text, figures, and biomedical image workflow](images/visual-evidence-workflow.svg)

Use this path for `get_fulltext`, `get_text_mined_terms`, `get_article_figures`, `analyze_figure_for_search`, and `search_biomedical_images`. Full text, figure metadata, and image search are separate evidence channels with different availability limits.

Use `analyze_figure_for_search` when the user provides an image URL or uploaded image payload and wants the agent to infer search terms from the visual content. The tool returns MCP `ImageContent`; the LLM agent performs the visual interpretation and should immediately continue with `search_biomedical_images` or `unified_search`.

Use `search_biomedical_images` when the visual question is already textual. Open-i is the current primary source, supports filters such as `image_type`, `collection`, `article_type`, `specialty`, `license_type`, `search_fields`, and requires English medical terminology.

### External Biomedical Data

![NCBI extended biomedical data workflow](images/ncbi-extended-workflow.svg)

Use this path for `search_gene`, `get_gene_details`, `get_gene_literature`, `search_compound`, `get_compound_details`, `get_compound_literature`, and `search_clinvar` when the question moves beyond papers into NCBI biomedical records.

### Evaluation, Timeline, And Comparison

![Research Chronicle Architecture and Lineage Flow](images/research-chronicle-lineage-flow.svg)
![Evaluation and timeline workflow](images/timeline-evaluation-workflow.svg)

Use this path for `get_citation_metrics`, `build_research_chronicle`, and `read_research_chronicle` when the user asks what mattered, when the field changed, or how topics diverged.

`build_research_chronicle` is the single research-evolution tool. It accepts `topic=...`, explicit comma-separated `pmids=...`, or an existing `chronicle_id=...`, detects milestone-like papers, and can return `summary`, `chronicle_map`, `timeline`, `tree`, `graph`, `evidence`, `milestones`, `mermaid`, `timeline_mermaid`, `mindmap`, `narrative`, or `json`. `mermaid` combines a horizontal year spine and lineage branches; `chronicle_map` is its JSON coordinate contract. Use `read_research_chronicle(action="milestones")` for milestone distribution diagnostics and `read_research_chronicle(action="compare", topics="a,b")` for up to five topic tracks.

Use precise terms:

- **Timeline**: chronological milestone projection.
- **Lineage tree**: retrieval-bounded branch projection from timeline events, not a causal genealogy.
- **Chronicle map**: one horizontal time spine with observed lines anchored at their earliest dated papers in the retrieved scope. Semantic branches require a signal shared by multiple papers; singleton-only or insufficient MeSH/keyword support produces a warned research-stage fallback. Same-year layout does not imply precedence when date precision cannot establish it.
- **Context graph preview**: `unified_search(options="context_graph")`, a lightweight preview from the current PMID-backed ranked set.
- **Citation tree**: `build_citation_tree`, a single-seed forward/backward citation network.
- **Research Chronicle**: `build_research_chronicle` / `read_research_chronicle`, the persistent, versioned, evidence-backed record. See [Advanced Research Workflows](#/advanced-workflows) and [Research Chronicle Rebuild Spec](#/research-chronicle-rebuild-spec).

### Research Chronicle

Use `build_research_chronicle` whenever the user asks how a field evolved. It replaces the older one-shot timeline tools: each immutable revision is appended atomically with a monotonic number, so re-running it later lets you diff revisions and answer "what changed since last time".

Chronology is the primary axis and research branches are a secondary projection of the same stored entries. Branches describe patterns observed in the selected query/PMID/source/year scope, not causal descent. `earliest_observed_in_scope` identifies the earliest dated retrieved candidate only; it does not establish the field's true first report. Date-precision intervals must be disjoint before the graph can assert `precedes` or `supersedes`.

Each chronicle entry carries a one-sentence claim with inline citations, its supporting/contradicting/updating evidence, a branch (lineage) assignment, and a confidence score. A typed provenance graph links Topic → Branch → Entry → EvidenceArticle and is validated against edge invariants. The audit reports evidence coverage, identifier coverage, branch coverage, semantic-lineage basis/coverage, graph integrity, chronology gaps, and per-source retrieval counts.

Topic mode applies `min_year` / `max_year` in the PubMed request before the relevance-capped fetch. Final event selection pins the first and last observed papers, prioritizes explicit landmark importance/citations, then fills the remaining capacity across the largest temporal gaps. Audit source coverage distinguishes PubMed `returned` from `available` and warns for capped samples, downstream selection, or unknown availability. An upstream PubMed error or zero article evidence returns an error and publishes no Chronicle revision.

PMID input accepts only ASCII digits with an optional `PMID:` prefix and explicit separators; DOI or arbitrary mixed identifier text is rejected. Entry IDs use PMID, then DOI, as stable evidence identity so date and milestone reclassification becomes an update rather than false remove/add churn. Chronicle derivation, topic lookup, comparison, and continuity share a Unicode-normalized, case-folded, whitespace-collapsed topic key while preserving the stored display topic.

A paper matching several selected semantic signals has one primary branch and explicit secondary cross-links in lineage diagnostics. If at least 20% of all or assigned entries overlap, the audit warns that branches are not cleanly separated. `confidence` remains milestone-detection confidence; landmark ordering uses explicit landmark importance and falls back to citation count, never detection confidence.

- `build_research_chronicle(topic=...)` or `build_research_chronicle(pmids="last")` atomically creates revision N+1. When session artifact persistence is enabled, it also writes a `research-chronicle-artifact/v1` bundle; a write failure is visible in Markdown or as `artifact.status="failed"` in structured output, while the revision remains saved.
- `build_research_chronicle(chronicle_id=...)` re-runs the continued revision's own topic/PMID set and filters to produce revision N+1 reflecting research movement cleanly.
- `read_research_chronicle(action="list")` lists stored chronicles.
- `read_research_chronicle(chronicle_id=..., output="mermaid"|"mindmap"|"chronicle_map"|"tree"|"timeline"|"graph"|"evidence")` reads one revision or the combined map.
- `read_research_chronicle(action="diff", chronicle_id=..., from_revision=1)` reports added, updated, and absent entries plus evidence and branch churn. The legacy `retired` key is a compatibility alias for `not_observed_in_revision` / `removed_from_view`; absence is never conclusive retirement.
- `read_research_chronicle(action="narrate", chronicle_id=..., mode="full")` renders prose where every claim cites its entry ID and article identifiers.
- `read_research_chronicle(action="compare", topics="a,b")` uses normalized exact stored-topic names. Multiple chronicles with the same topic are reported as ambiguous; pass distinct `chronicle_ids` instead. Duplicate targets are not a valid comparison.

The public schema and runtime checks bound Chronicle requests: `max_events` is 1–200, an explicit set has at most 500 unique PMIDs, topic text has at most 500 characters, list limits are 1–100, and comparisons contain 2–5 distinct chronicles. JSON projections and structured read actions keep validation/not-found errors structured.

Artifact preflight audits the names produced by the actual artifact payload builder (plus the store-generated manifest), rather than trusting a parallel declared list. It validates preparation only; persistence success is reported separately by the artifact locator/status.

### Session, Pipeline, And Scheduled Reuse

![Session and pipeline workflow](images/session-pipeline-workflow.svg)

Use this path for `read_session`, `get_session_pmids`, `get_cached_article`, `get_session_summary`, `get_session_log`, `manage_pipeline`, `save_pipeline`, `list_pipelines`, `load_pipeline`, `delete_pipeline`, `get_pipeline_history`, and `schedule_pipeline`.

Local and service capabilities are intentionally different. A trusted local
caller may use workspace scope, `file:` pipeline sources, and the in-process
scheduler. An authenticated service caller can only read saved pipelines from
its tenant-derived store; process-wide workspace/file reads are blocked, and
the service Compose profile disables scheduling unless an operator supplies a
single external leader/lease.

### Institutional Access

![Institutional access workflow](images/institutional-access-workflow.svg)

Use this path for `configure_institutional_access`, `get_institutional_link`, `list_resolver_presets`, `test_institutional_access`, and `diagnose_institutional_access`. OpenURL is a browser handoff; direct DOI and EZproxy paths become agent-fetchable only when the environment is configured and access is permitted.

### Export And Local Notes

![Export and local notes workflow](images/export-notes-workflow.svg)

Use this path for `prepare_export` and `save_literature_notes`. Citation exports are for reference managers; local notes are editable literature-review artifacts with machine-readable metadata.

## Persistent Query Memory For Large Outputs

When session persistence is configured, `unified_search` and `get_fulltext`
write complete reusable outputs to artifacts and return a compact locator in
the tool response. Treat the response as an index card: it has enough counts,
warnings, and artifact hints for the agent to answer immediately, while the
complete evidence payload stays in retrievable files. Use the session facade for
remote clients, and set `PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS=true` only for
local MCP clients that should receive direct server paths:

```python
read_session(action="list_artifacts")
read_session(action="artifact", artifact_id="...")
read_session(action="artifact", artifact_uri="artifact://...")
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="audit.json")
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="results.json", offset=0, max_chars=200000)
```

When session management is active, every `unified_search` invocation includes a
stable `search_run.run_id`: normal search, validation/planning failure, inline
pipeline, `saved:<name>`, and pipeline `dry_run=true`. The tenant-scoped
`search-run/v1` journal is written before provider I/O or a terminal validation
response and retains a credential-sanitized replay request, normalized plan,
per-source or per-pipeline-step attempts, safe failure details, compact result
references, warnings, and an artifact locator when applicable. Structured
responses attach the handoff and Markdown adds a compact run note.

Successful, zero-result, partial, planning/execution failure, and cancelled
invocations therefore leave inspectable state. A valid zero-result run has
journal status `completed` while `search_status.state` is `empty`; an unfinished
active run is changed to `interrupted` once during restart recovery. A non-dry-
run saved pipeline additionally keeps its PipelineStore report/run history.
PipelineStore history and the invocation journal are complementary.

```python
read_session(action="search_runs")
read_session(action="search_runs", run_status="partial", history_limit=20)
read_session(action="search_run", run_id="...")
read_session(action="replay_search", run_id="...")
```

`replay_search` is intentionally read-only. It returns exact, credential-free
`unified_search` kwargs and `automatic_execution=false`; an agent must review
and explicitly call `unified_search` to run them. Pipeline replay includes its
inline or `saved:<name>` argument plus `dry_run` / `stop_at`. Pipeline text that
contains credentials is rejected as a failed run; use server environment
configuration for provider keys, tokens, cookies, and secrets. Because there is no public
cursor-resume input yet, opaque cursor/token provenance cannot resume a page in
place and replay begins a new bounded request.

If the terminal history commit cannot be recovered, the bounded handoff changes
to `status="history_unavailable"` with `history_available=false`, the intended
status, and a warning. Inspect/replay actions are omitted in that degraded state
because durable recovery cannot be promised.

`unified_search` artifacts use a research envelope. Start with `audit.json` to
check completeness warnings, then `query_strategy.json` for the exact query
plan, and `results.json` / `results.toon` for the full result list. This avoids
spending MCP response tokens on long article lists while still making the run
auditable and reproducible.

Artifact publication and session indexing are separate atomic boundaries. On
session reload, the store discovers only complete checksum-indexed manifests
that are missing from the session index and relinks a recovered search artifact
by `search_run_id`; a conservative same-query fallback exists for older
artifacts that predate that metadata.

`local_path` and `manifest_path` are paths on the MCP server host. `read_session`
redacts local paths by default unless `include_local_paths=true` is requested.
Large `get_fulltext` responses are capped inline when an artifact exists; use
the locator to read the saved full content. This is persistent query memory:
agents can reopen the exact saved search/fulltext output by artifact ID without
rerunning the external source call. Full-text artifacts can contain article body
text, so handle storage and sharing according to publisher, license, and
institutional access terms.

If a source fails but the search can continue, `unified_search` may return
`source_errors` in JSON or `Source warnings` in markdown. Semantic Scholar HTTP
429 warnings usually mean the workflow should set `S2_API_KEY` /
`SEMANTIC_SCHOLAR_API_KEY`, retry later, or exclude the source.

## Local Wiki Note Export

![Export and local notes workflow](images/export-notes-workflow.svg)

Use `save_literature_notes` when the user wants a guided, semi-structured file output after search. This is better than asking an agent to assemble a Markdown note with a generic write-file operation.

Default behavior:

```python
save_literature_notes(pmids="last")
```

The default `note_format` is `wiki`. It writes one `.md` file per article with:

- YAML frontmatter for title, PMID, DOI, PMCID, journal, year, citation key, aliases, and tags
- Foam-compatible wikilinks in the generated index note
- stable wiki/Foam link targets based on PMID, DOI, PMCID, or a fallback identifier; article titles stay as link labels and aliases
- a `wiki_validation` report showing emitted wikilinks and any unresolved targets
- triage fields for status, relevance, and decision
- summary, key findings, methods/population, limitations, and follow-up question sections
- source links to PubMed, DOI, and PMC when available
- by default, a collection-level `references.csl.json` sidecar when notes or index artifacts are created

When `unified_search` returns PMID-backed results, its next-tool suggestions include:

```python
save_literature_notes(pmids="last", note_format="wiki")
```

That gives agents a local LLM-wiki handoff without requiring them to invent filenames or wikilinks from the search response.

Supported note formats:

| Format | Link Style | Layout | Best For |
| --- | --- | --- | --- |
| `wiki` | `[[stable-id|title]]` | default guided literature note | Foam, Obsidian-style, and general wiki workflows |
| `foam` | `[[stable-id|title]]` | same compatible profile as `wiki` | existing Foam-specific users |
| `markdown` | `` `[title](note.md)` `` | same guided sections | plain Markdown repositories |
| `medpaper` | `[[citation_key|title]]` | per-reference directory containing `<citation_key>.md` plus `metadata.json` | MedPaper-style or Zotero Keeper-compatible reference libraries |

Local-mode directory resolution:

1. `output_dir`, if provided
2. `PUBMED_NOTES_DIR`
3. `PUBMED_WORKSPACE_DIR/references`
4. `PUBMED_DATA_DIR/references`
5. `~/.pubmed-search-mcp/references`

Authenticated service callers do not participate in that host-path resolution.
They cannot supply `output_dir` or `template_file`; notes use a built-in format
and stay below the current principal's isolated `references/` directory.

## Good Markdown Note Shape

A good literature note should separate verified bibliographic data from human or agent interpretation:

```markdown
---
title: "Article title"
pmid: "12345678"
doi: "10.xxxx/example"
citation_key: "smith2024_12345678"
source: "PubMed"
note_format: "wiki"
tags: ["literature", "pubmed"]
aliases: ["smith2024_12345678", "Article title", "12345678", "Smith 2024"]
---

# Article title

## Metadata
- PMID: [12345678](https://pubmed.ncbi.nlm.nih.gov/12345678/)
- DOI: [10.xxxx/example](https://doi.org/10.xxxx/example)
- Journal: Journal name
- Year: 2024
- Authors: Smith J; Doe J

## Triage
- Status:
- Relevance:
- Decision:

## Summary
-

## Key Findings
-

## Methods And Population
-

## Limitations
-

## Follow Up Questions
-

## Citation
- Smith J; Doe J. Article title. Journal name. 2024. doi:10.xxxx/example
```

Keep verified metadata machine-readable in frontmatter and sidecars. Keep interpretation editable in body sections.

## Custom Templates

In trusted local mode, use `template_file` when a user has a house style:

```python
save_literature_notes(
    pmids="last",
    output_dir="./references",
    template_file="./reference-template.md"
)
```

Available placeholders include `{title}`, `{pmid}`, `{doi}`, `{pmc_id}`, `{journal}`, `{journal_abbrev}`, `{year}`, `{volume}`, `{issue}`, `{pages}`, `{authors}`, `{abstract}`, `{citation_key}`, `{reference_id}`, `{note_format}`, `{created}`, `{pubmed_url}`, `{doi_url}`, `{citation}`, `{keywords}`, `{mesh_terms}`, and `{csl_json}`.

For an authenticated service, choose one of the built-in note formats instead;
reading an arbitrary template from the server filesystem is rejected.

## Pipeline And Packaged Agent References

Pipeline tutorials live canonically in:

- `docs/PIPELINE_MODE_TUTORIAL.en.md`
- `docs/PIPELINE_MODE_TUTORIAL.md`

`scripts/build_docs_site.py` also syncs those tutorials into `.claude/skills/pipeline-persistence/references/` so external agent bundles and VSIX packages that do not ship `docs/site-content/` can still read them.
