<!-- Generated from docs/USER_GUIDE.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# PubMed Search MCP User Guide

This guide is for people using PubMed Search MCP through an AI client such as VS Code, Claude Desktop, Claude Code, Cursor, Cline, Zed, or Copilot Studio. It explains how to move from a research question to reusable evidence without memorizing every MCP tool.

Use this as the practical entry point, then keep the [Tools Usage Guide](#/tools-usage-guide) and [Quick Reference](#/quick-reference) nearby when you need exact tool names.

## What This Server Is Good For

PubMed Search MCP is an agent-facing literature research server. It is strongest when you want the AI client to plan and execute a biomedical literature workflow instead of only calling PubMed once.

Typical jobs:

- turn a clinical or biomedical question into a PubMed-ready search strategy
- search multiple scholarly sources through `unified_search`
- inspect seed papers, related articles, citing articles, references, and citation trees
- retrieve full text, text-mined terms, article figures, and open-access image links when available
- export citations or save guided local Markdown/wiki notes
- save, review, rerun, or schedule repeatable research pipelines

It is not a replacement for human judgment, institutional access policy, systematic-review protocol design, or clinical decision-making.

## Setup Checklist

Minimum local setup:

```bash
uvx pubmed-search-mcp
```

Minimum environment:

```bash
NCBI_EMAIL=your@email.com
```

`NCBI_EMAIL` is required because NCBI asks API users to identify themselves. Add `NCBI_API_KEY` when you want higher NCBI rate limits. Add optional source keys only when you use those sources.
OpenAlex, CrossRef, and Unpaywall reuse the runtime server contact email unless you set `OPENALEX_API_KEY`, `CROSSREF_EMAIL`, or `UNPAYWALL_EMAIL`.

Common optional values:

```bash
NCBI_API_KEY=your_ncbi_api_key
CORE_API_KEY=your_core_api_key
CROSSREF_EMAIL=your@email.com      # optional override; defaults to server/NCBI email
UNPAYWALL_EMAIL=your@email.com     # optional override; defaults to server/NCBI email
PUBMED_NOTES_DIR=/path/to/references
```

For client-specific setup, see the [Integration Guide](#/troubleshooting). For HTTP, Docker, Copilot Studio, and GitHub Pages deployment notes, see [Deployment](#/deployment).

## Choose The Right Path

![PubMed Search MCP research workflow](images/research-workflow.svg)

| Goal | Start With | Then Use |
| --- | --- | --- |
| Quick search for papers | `unified_search` | `fetch_article_details`, `read_session` |
| Clinical question | Agent extracts P/I/C/O, then `parse_pico` | `generate_search_queries`, `unified_search` |
| Improve a noisy query | `analyze_search_query` | `generate_search_queries`, `unified_search` |
| Explore one important article | `fetch_article_details` | `find_related_articles`, `find_citing_articles`, `get_article_references`, `build_citation_tree` |
| Read deeper evidence | `get_fulltext` | `get_text_mined_terms`, `get_article_figures` |
| Search from visual evidence | `analyze_figure_for_search` | `search_biomedical_images`, `unified_search` |
| Build a research chronicle / lineage tree | `build_research_chronicle` | `read_research_chronicle` |
| Reopen large outputs | `read_session(action="artifact")` | `read_session(action="list_artifacts")` |
| Build a local literature library | `prepare_export` | `save_literature_notes` |
| Reuse a workflow | `manage_pipeline` | `save_pipeline`, `load_pipeline`, `schedule_pipeline` |

The most important rule: start with the research intent, not the tool menu.

`unified_search` parameters are intentionally agent-friendly strings. Use comma-separated values for `sources`, `filters`, and `options` instead of JSON objects. Examples: `sources="auto"`, `sources="auto,-semantic_scholar"`, `filters="year:2020-, clinical:therapy"`, or `options="counts_first,context_graph"`.

## Daily Workflow

### 1. Start Broad, Then Narrow

![Search and query intelligence workflow](images/search-query-workflow.svg)

Ask the client to run a modest first pass:

```text
Use PubMed Search MCP to search for recent literature on SGLT2 inhibitors and heart failure with preserved ejection fraction. Start with a broad search, show the query strategy, and keep the result set in session.
```

The agent should normally begin with `unified_search`. A good result includes the query used, article identifiers, source provenance, and enough metadata to decide whether to fetch details or refine.

Prefer `read_session` or `get_session_pmids` for follow-up work. Do not ask the model to remember a long PMID list in conversation.

### 2. Use PICO For Clinical Questions

For clinical comparisons, ask the agent to extract P/I/C/O first and validate that structured handoff:

```text
Extract P/I/C/O, validate the handoff with parse_pico, propose PubMed search queries, then run the most specific one:
In adults with type 2 diabetes and CKD, do SGLT2 inhibitors reduce heart failure hospitalization compared with placebo?
```

Expected flow:

1. Agent extracts P/I/C/O from the user's clinical question.
2. `parse_pico(description=..., p=..., i=..., c=..., o=...)` validates the schema and returns a `template: pico` pipeline.
3. Optional `generate_search_queries` calls expand P/I/C/O into MeSH/synonym fragments.
4. `unified_search` runs either the returned PICO pipeline or the agent-built Boolean query.
5. optional `analyze_search_query` if the first query is too broad or too narrow

The server can validate the PICO handoff, build the backend PICO search plan, and help with MeSH, synonyms, and ICD-to-MeSH expansion. The agent remains responsible for the semantic PICO extraction and should explain why it chose a final query.

### 3. Explore Seed Papers

![Article discovery and citation workflow](images/discovery-citation-workflow.svg)

Once you have an important PMID, move from search to discovery:

```text
For PMID 12345678, fetch details, then find related papers, citing papers, and key references. Summarize why each group matters.
```

Useful tools:

- `fetch_article_details`
- `find_related_articles`
- `find_citing_articles`
- `get_article_references`
- `build_citation_tree`
- `get_citation_metrics`

Use this path when you already trust one seed paper and want to map the surrounding evidence.

### 4. Retrieve Full Text And Figures

![Full text retrieval flow](images/fulltext-retrieval-flow.svg)

![Full text, figures, and biomedical image workflow](images/visual-evidence-workflow.svg)

Use `get_fulltext` when abstracts are not enough. Prefer explicit identifiers such as `pmid=`, `pmcid=`, or `doi=` so the agent does not need to infer identifier type from a raw string. The full-text service follows an identifier-aware policy: Europe PMC XML when a PMCID is available, Unpaywall OA locations for DOI-backed articles, institutional direct/EZproxy when configured, CORE, then optional downloader/browser-session fallbacks. CrossRef is a metadata and publisher-link route, not a hosted full-text source.

Use `get_article_figures` for PMC Open Access articles when the task needs captions, image URLs, or PDF links. Figure extraction depends on open-access availability; a missing figure result is not proof that the article has no figures.

For image-first work, use the visual tools as a two-step agent workflow:

```text
Analyze this uploaded microscopy image with analyze_figure_for_search, extract English search terms, then search related papers and similar biomedical images.
```

`analyze_figure_for_search` accepts either an image URL or a base64/data-URI image supplied by the MCP client. It returns MCP `ImageContent` plus instructions for the agent to use its own vision capability, extract English biomedical terms, and continue with `search_biomedical_images` or `unified_search`. The server does not perform deep visual diagnosis by itself; the LLM agent performs the image interpretation step.

Use `search_biomedical_images` when the query is already textual and the goal is open biomedical image evidence:

```python
search_biomedical_images("chest X-ray pneumonia", sources="openi", image_type="x", limit=10)
search_biomedical_images("histology liver fibrosis", sources="openi", image_type="mc", license_type="by")
```

Open-i expects English medical terms. For non-English user prompts, ask the agent to translate the visual finding or anatomy into English first, then search.

Optional browser fallback requires a separate local broker:

```bash
uv sync --extra browser-broker
uv run playwright install chromium
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
uv run pubmed-browser-fetch-broker --token "<same-random-32-byte-token>"
```

Copy the generated value into both the broker command and MCP configuration;
never use a token copied from public documentation. The broker also enforces a
loopback bind plus loopback Host and Origin headers.

Only enable browser-session fallback for hosts you trust and are allowed to access:

```json
{
  "enabled": true,
  "auto_enabled": true,
  "broker_url": "http://127.0.0.1:8766/fetch",
  "token": "<same-random-32-byte-token>",
  "allowed_hosts": ["jamanetwork.com", "*.jamanetwork.com"]
}
```

### 5. Build A Research Chronicle Or Lineage Tree

![Evaluation and timeline workflow](images/timeline-evaluation-workflow.svg)

Use the chronicle tools when the question is not just "what papers exist?" but "how did this field develop?"

```python
build_research_chronicle(topic="remimazolam ICU sedation", output="tree", max_events=20)
build_research_chronicle(pmids="12345678,23456789", topic="Selected studies", output="mermaid")
read_research_chronicle(action="milestones", chronicle_id="car-t-therapy-...")
read_research_chronicle(action="compare", topics="remimazolam,propofol,dexmedetomidine")
```

`build_research_chronicle` can search by topic or use an explicit PMID set. Its primary axis is chronological and research branches are a secondary projection of the same entries. Use `output="mermaid"` for the canonical horizontal year spine with observed research lines branching at their earliest dated papers in the retrieved scope, or `output="chronicle_map"` for the same coordinate contract as JSON. Topic branches prefer MeSH descriptors and author keywords shared by multiple papers; singleton-only or insufficient signals produce a warned research-stage fallback. `timeline_mermaid` keeps the flat legacy diagram. Other outputs are `summary`, `timeline`, `tree`, `graph`, `evidence`, `milestones`, `mindmap`, `narrative`, and `json`. Use `options="context_graph"` in `unified_search` only for a lightweight preview from the current ranked PMID-backed results. The chronicle is persistent and versioned; see [Research Chronicle Rebuild Spec](#/research-chronicle-rebuild-spec).

Lineage is an explainable grouping of the retrieved snapshot, not causal ancestry. `earliest_observed_in_scope` does not establish the first publication in the field, and the query, PMID set, year filters, source availability, and result cap all constrain what can be observed. Date precision is retained: same-year or overlapping date intervals can be displayed deterministically, but do not create an inferred `precedes` or `supersedes` relationship.

Revisions are immutable and appended atomically. `action="compare"` resolves normalized exact stored-topic names; ambiguous same-name chronicles require explicit `chronicle_ids`, and duplicate targets are rejected. Build inputs are bounded (`max_events` 1–200, at most 500 unique explicit PMIDs, topic text up to 500 characters), and structured actions return structured errors. If enabled session artifact persistence fails after the Chronicle revision is saved, the response exposes the failure instead of returning a misleading locator.

Topic year filters are applied by PubMed before bounded retrieval. The cap preserves the first and last observed papers, explicit landmarks, and temporal spread; audit output distinguishes `returned` from `available` and warns when coverage is capped or unknown. PubMed errors and zero-evidence results save no revision. Explicit PMID strings are strict, while PMID/DOI-based entry identity remains stable across date or classifier corrections. Diff absence is always `not_observed_in_revision` / `removed_from_view`, not proven retirement. Multi-signal papers retain one primary branch plus cross-links, with an overlap warning at 20%; landmark ranking never treats detection confidence as scientific importance. Artifact preflight checks the payload actually prepared for persistence.

Mermaid labels, IDs, parent links, cycles, duplicates, and visual size are repaired deterministically. If rich syntax is rejected, rendering falls back to safe and then minimal syntax. Inspect `mermaid_validation.json` for corrections, fallback tier, and omitted-item counts; the full coordinate data remains in `chronicle_map.json`.

### 6. Reopen Persistent Query Memory

When session persistence is configured through `PUBMED_DATA_DIR`, large reusable outputs from `unified_search` and `get_fulltext` are saved as artifacts. The immediate tool response includes a compact locator instead of forcing the agent to receive every token inline.

```python
read_session(action="list_artifacts")
read_session(action="artifact", artifact_id="...")
read_session(action="artifact", artifact_uri="artifact://...")
read_session(action="artifact", artifact_id="...", artifact_file="payload.json", offset=0, max_chars=200000)
```

Local paths are redacted by default because remote clients cannot read the server filesystem. Set `PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS=true` only for local MCP clients that should receive `local_path` and `manifest_path`. Artifact reads never rerun the search; they read the persisted query/fulltext memory.

### 7. Export Citations Or Local Notes

![Export and local notes workflow](images/export-notes-workflow.svg)

Use `prepare_export` for citation manager handoff. Official PubMed-backed formats are `ris`, `medline`, and `csl`; local rendered formats include `bibtex`, `csv`, and `json`.

Common examples:

```python
prepare_export(pmids="last", format="ris")
prepare_export(pmids="last", format="bibtex", source="local")
prepare_export(pmids="last", format="csl")
```

Use `save_literature_notes` when the goal is a note library rather than a citation file:

```python
save_literature_notes(pmids="last")
save_literature_notes(pmids="last", note_format="wiki")
save_literature_notes(pmids="last", note_format="medpaper")
save_literature_notes(pmids="last", output_dir="./references")
```

The default `note_format` is `wiki`. `unified_search` suggests `save_literature_notes(pmids="last", note_format="wiki")` for PMID-backed result sets, and the generated LLM wiki/Foam links use stable `[[stable-id|title]]` targets based on PMID, DOI, or PMCID instead of title-derived filenames. The response includes `wiki_validation` so agents can detect unresolved wikilinks before editing the note library.

The `output_dir` example and custom `template_file` are **local-mode features**.
An authenticated service caller cannot select a server-host path or read an
arbitrary template file. It omits both arguments, chooses a built-in
`note_format`, and the server writes below that principal's isolated
`references/` directory.

In local mode, directory resolution is:

1. `output_dir`
2. `PUBMED_NOTES_DIR`
3. `PUBMED_WORKSPACE_DIR/references`
4. `PUBMED_DATA_DIR/references`
5. `~/.pubmed-search-mcp/references`

Local notes keep verified metadata in frontmatter and sidecar files, then leave summary, relevance, limitations, and follow-up sections editable.

### 8. Save Repeatable Pipelines

![Session and pipeline workflow](images/session-pipeline-workflow.svg)

Use pipelines when a research process should be rerun or audited. Start with the [Pipeline Tutorial](#/pipeline-tutorial).

Typical pipeline jobs:

- rerun a search every week
- keep a search strategy in versioned text
- compare pipeline history across runs
- schedule a recurring literature watch

The server exposes pipeline operations through `manage_pipeline` and compatibility tools such as `save_pipeline`, `load_pipeline`, `list_pipelines`, `delete_pipeline`, `get_pipeline_history`, and `schedule_pipeline`.

Saved pipelines can be reused from search with `unified_search(pipeline="saved:<name>")`. Pipeline `config` values should be YAML or JSON strings, and scheduled pipelines use standard five-field cron strings.

Runtime boundary: local callers may use `workspace` scope and
`load_pipeline(source="file:...")`. Authenticated service callers use only their
tenant-derived saved-pipeline store; it does not inherit the process-wide
workspace path, and `file:` sources are rejected. The service Compose profile
also disables the in-process scheduler. A service operator must use manual runs
or design a single external leader/lease before enabling recurring execution.

## Copilot Studio Notes

![Client integration and deployment workflow](images/integration-deployment-workflow.svg)

There are two Copilot routes:

- public primary MCP surface through authenticated `pubmed-search-mcp-http --mode service --transport streamable-http --copilot-compatible`
- loopback-only schema smoke: a smaller 11-tool schema through `run_copilot.py`

Only the full authenticated service is publishable. Use the simplified surface locally to inspect Copilot Studio schema compatibility, then return to the service launcher for any public endpoint; never tunnel `run_copilot.py`.

## Ask The Agent Well

Good prompts give the agent a task, a scope, and an output shape:

```text
Find recent systematic reviews about GLP-1 receptor agonists and cardiovascular outcomes in type 2 diabetes. Use PubMed Search MCP, show the search strategy, keep the result PMIDs in session, then export the final set as RIS.
```

```text
Build a citation tree for this seed PMID, separate direct references from citing papers, and identify which papers look like clinical guidelines, RCTs, or meta-analyses.
```

```text
Save local wiki notes for the last result set. Use the default wiki format and include a collection-level CSL JSON sidecar.
```

Avoid vague requests such as "find everything about cancer." Ask for population, intervention, outcome, date range, article type, or the decision you need to make.

## Reliability Boundaries

Keep these limits in mind:

- Search results reflect external source behavior and available metadata.
- Full text depends on open access, source APIs, publisher pages, and your configured credentials or browser session.
- Citation counts and citation networks vary by provider and update cadence.
- Generated summaries are agent interpretation. Bibliographic metadata and source links are the evidence anchor.
- Commercial connectors should be default-off and credential-gated.
- Clinical use requires domain review; this server helps gather evidence but does not decide care.

## Troubleshooting First Steps

| Symptom | First Check |
| --- | --- |
| Server does not start | Confirm `uvx pubmed-search-mcp` runs in a terminal. |
| Client cannot find tools | Check the client config path and JSON syntax in [Integration Guide](#/troubleshooting). |
| NCBI warning or slow responses | Set `NCBI_EMAIL`; optionally add `NCBI_API_KEY`. |
| Tool call shows `Canceled: Canceled` while progress is updating | Use a build with non-cancelling best-effort progress callbacks; for genuinely long searches, retry with `options="shallow"` or narrower `sources`. |
| Empty or sparse full text | Try `get_fulltext` on a PMC Open Access article, then check source availability. |
| A Chronicle Mermaid diagram is simplified or does not render in the client | Read `mermaid_validation.json`; use the pure `chronicle.mmd` source and inspect `chronicle_map.json` for any omitted visual items. |
| Local notes saved somewhere unexpected | Check `output_dir`, `PUBMED_NOTES_DIR`, `PUBMED_WORKSPACE_DIR`, and `PUBMED_DATA_DIR`. |
| Service rejects a note path, template, pipeline file, or workspace scope | Omit server-host paths; use built-in note formats and save pipelines by name in the authenticated tenant store. |
| A scheduled pipeline is saved but does not run in service Compose | The service scheduler is intentionally disabled; run it manually or provide one external leader/lease. |
| GitHub Pages docs look stale | Run `uv run python scripts/build_docs_site.py` locally, then check the Pages workflow. |

## Where To Go Next

- [Tools Usage Guide](#/tools-usage-guide): capability-first tool routing
- [Pipeline Tutorial](#/pipeline-tutorial): saved and scheduled workflows
- [Integration Guide](#/troubleshooting): client configuration and troubleshooting
- [Deployment](#/deployment): HTTP, Docker, Copilot Studio, and Pages
- [Developer Guide](#/developer-guide): architecture, contribution flow, and validation
