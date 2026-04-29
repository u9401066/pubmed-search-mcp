<!-- Synced from docs/PIPELINE_MODE_TUTORIAL.en.md by scripts/build_docs_site.py -->

# Pipeline Mode Tutorial

> Status: current API tutorial
> Last updated: 2026-04-29
> Language: **English** | [繁體中文](pipeline-tutorial.zh-TW.md)

This document only describes pipeline mode behavior that is currently implemented and supported. It does not repeat older RFC or design-draft material. The focus is what you can execute now, save now, schedule now, and inspect through history now.

## Pipeline Mode Quick Start

Pipeline mode currently has 3 practical entry points:

1. Pass YAML or JSON directly into `unified_search(..., pipeline="...")`
2. Save the config first with `manage_pipeline` or `save_pipeline`, then run it with `saved:<name>`
3. Save it first, then schedule recurring runs with `schedule_pipeline` or `manage_pipeline(action="schedule")`

### Smallest usable example: inline template

```python
unified_search(
    query="",
    pipeline="""
template: pico
params:
  P: ICU patients requiring mechanical ventilation
  I: remimazolam
  C: propofol
  O: sedation adequacy
output:
  format: markdown
  limit: 20
  ranking: balanced
""",
)
```

Notes:

- `unified_search` still requires `query` in the function signature, but once `pipeline` is set, ordinary search parameters are generally ignored. The safe pattern is `query=""`.
- `output_format="json"` forces structured JSON. `output.format: json` inside the pipeline also returns structured JSON.
- `dry_run=True` previews the resolved DAG without external searches. `stop_at="<step_id>"` executes only through that step.

### Smallest usable example: save first, then execute

```python
manage_pipeline(
    action="save",
    name="icu_remi_vs_propofol",
    config="""
template: pico
params:
  P: ICU patients requiring mechanical ventilation
  I: remimazolam
  C: propofol
  O: delirium, sedation quality
output:
  limit: 25
  ranking: quality
""",
    tags="icu,sedation,remimazolam",
    description="ICU sedation comparison",
)

unified_search(query="", pipeline="saved:icu_remi_vs_propofol")
```

### Structured output and continuation tools

Pipeline reports now include filter diagnostics and next-step handoffs. At the bottom of a Markdown report, the recommended continuation tools are:

- `get_session_pmids()` for the run PMID set
- `prepare_export(pmids="last", format="ris")` for Zotero/EndNote/Mendeley-style citation handoff
- `save_literature_notes(pmids="last", format="wiki")` for local wiki/Foam-compatible Markdown notes

Use structured JSON when another agent or extension should consume articles directly:

```yaml
output:
  format: json
  limit: 20
  ranking: quality
```

The JSON response contains `summary`, `steps`, per-step `metadata`, and structured `articles`.

### Which entry point to use

| Situation | Recommended entry point |
| ---- | -------- |
| You only want to run it once quickly | inline `unified_search(..., pipeline="...")` |
| You want to reuse the same search strategy | `manage_pipeline(action="save")` |
| You want history diffs or scheduling | save first, then use `saved:<name>` or `schedule_pipeline` |
| You want to load a local YAML file and adjust it | `load_pipeline(source="file:path/to/pipeline.yaml")` |

## Template Pipeline Tutorial

Template pipelines cover roughly 80% of normal use cases. The YAML is not sent directly into the executor as-is. It is first expanded into a real step DAG.

### 4 templates currently available

| Template | Required parameters | Common optional parameters | Purpose |
| -------- | -------- | ------------ | ---- |
| `pico` | `P`, `I` | `C`, `O`, `sources`, `limit` | Clinical comparison question |
| `comprehensive` | `query` | `sources`, `limit`, `min_year`, `max_year` | Broad multi-source search |
| `exploration` | `pmid` | `limit` | Explore outward from one seed paper |
| `gene_drug` | `term` | `sources`, `limit`, `min_year`, `max_year` | Gene- or drug-focused search |

### `params` vs `template_params`

- The shortest inline YAML usually uses `params`
- `save_pipeline`, `manage_pipeline(save)`, and `load_pipeline` also accept `template_params`
- When a saved pipeline is loaded, the system will often output it as `template_params`

Recommendation:

- Use `params` for handwritten inline pipelines
- Use `template_params` for YAML that you want to save long term or review more formally

### `pico`

```yaml
template: pico
params:
  P: ICU patients requiring sedation
  I: remimazolam
  C: propofol
  O: delirium incidence, time to extubation
  sources: pubmed,europe_pmc
  limit: 30
output:
  ranking: quality
```

This expands automatically into:

```text
pico -> search_p
     -> search_i
     -> search_c   # Only appears when C is provided
     -> merged -> enriched
```

### `comprehensive`

```yaml
template: comprehensive
template_params:
  query: CRISPR gene therapy clinical trials
  sources: pubmed,openalex,europe_pmc
  limit: 30
  min_year: 2020
output:
  ranking: quality
```

The correct field today is `query`, not `topic`.

This runs `expand` first, then launches the original query and expanded query in parallel, and finally performs merge + metrics.

### `exploration`

```yaml
template: exploration
params:
  pmid: "37076210"
  limit: 25
output:
  ranking: impact
```

This pulls `related`, `citing`, and `references` from the same seed paper.

### `gene_drug`

```yaml
template: gene_drug
template_params:
  term: BRCA1 targeted therapy PARP inhibitors
  sources: pubmed,openalex
  limit: 20
  min_year: 2020
output:
  ranking: recency
```

The correct field today is `term`, not `topic`.

### Example files

You can directly inspect these examples:

- `data/pipeline_examples/pico_remimazolam_vs_propofol.yaml`
- `data/pipeline_examples/comprehensive_crispr_therapy.yaml`
- `data/pipeline_examples/exploration_seed_paper.yaml`
- `data/pipeline_examples/gene_drug_brca1.yaml`

## Custom DAG Tutorial

When templates are not enough, define `steps` directly.

### Minimum structure

```yaml
name: ai_anesthesiology_scan
steps:
  - id: expand
    action: expand
    params:
      topic: artificial intelligence anesthesiology

  - id: search_original
    action: search
    params:
      query: artificial intelligence anesthesiology
      sources: pubmed,openalex
      limit: 60
      min_year: 2020

  - id: search_mesh
    action: search
    inputs: [expand]
    params:
      strategy: mesh
      sources: pubmed,europe_pmc
      limit: 60
      min_year: 2020

  - id: merged
    action: merge
    inputs: [search_original, search_mesh]
    params:
      method: rrf

  - id: enriched
    action: metrics
    inputs: [merged]

  - id: filtered
    action: filter
    inputs: [enriched]
    params:
      min_year: 2021
      has_abstract: true

output:
  format: markdown
  limit: 30
  ranking: quality
```

### Step fields to remember

| Field | Required? | Meaning |
| ---- | ------ | ---- |
| `id` | Recommended | It will be auto-fixed if missing, but you should name it yourself |
| `action` | Required | Only a fixed action set is currently accepted |
| `params` | Depends on action | Each action expects different parameters |
| `inputs` | Depends on action | Can only reference steps defined earlier |
| `on_error` | Optional | `skip` or `abort`, default is `skip` |

### Actions currently available

| Action | Common params | Meaning |
| ------ | ----------- | ---- |
| `search` | `query`, `sources`, `limit`, `min_year`, `max_year` | General literature search |
| `pico` | `P`, `I`, `C`, `O` | Build PICO elements and a combined query |
| `expand` | `topic` | Perform semantic expansion and MeSH strategy generation |
| `details` | `pmids` | Fetch detailed article metadata |
| `related` | `pmid`, `limit` | Find related articles |
| `citing` | `pmid`, `limit` | Find citing articles |
| `references` | `pmid`, `limit` | Find references |
| `metrics` | none | Add iCite metrics |
| `merge` | `method=union / intersection / rrf` | Merge multiple result streams |
| `filter` | `min_year`, `max_year`, `article_types`, `min_citations`, `has_abstract` | Post-processing filters with diagnostics |

### Shared globals and variables

Use `globals` for step parameter defaults and `variables` for `${name}` placeholders. Step-level params override globals.

```yaml
name: reusable_remi_pipeline
globals:
  sources: pubmed,europe_pmc
  limit: ${per_step_limit}
  min_year: ${start_year}
variables:
  topic: remimazolam ICU sedation
  per_step_limit: 50
  start_year: 2020
steps:
  - id: search_topic
    action: search
    params:
      query: ${topic}
  - id: filtered
    action: filter
    inputs: [search_topic]
    params:
      article_types: [RCT, systematic review]
      has_abstract: true
output:
  limit: 20
  ranking: quality
```

`article_types` accepts canonical values such as `randomized-controlled-trial` and common aliases such as `RCT`, `randomized controlled trial`, `systematic review`, and `meta analysis`. Unknown article type requests fail closed with a warning instead of silently disabling the filter. The filter report shows before/after counts, exclusion reasons, mappings, and examples of excluded articles.

### How `search` consumes upstream outputs

`search` does not always need its own `query`. It can derive the query from an upstream step:

- When upstream is `pico`, you can use `element: P|I|C|O`
- When upstream is `pico`, you can also use `use_combined: precision|recall`
- When upstream is `expand`, you can use `strategy: mesh` or another strategy name

### Dry-run and partial execution

Use `dry_run=True` before long pipelines or while editing variables:

```python
unified_search(query="", pipeline="<yaml>", dry_run=True)
```

Use `stop_at` to inspect an intermediate result set:

```python
unified_search(query="", pipeline="<yaml>", stop_at="merged")
```

`stop_at` is inclusive: the named step runs, downstream steps are skipped. This is useful when you want to inspect a PICO merge before adding filters or metrics.

### Full DAG example

For a longer multi-step example, see:

- `data/pipeline_examples/ai_in_anesthesiology.yaml`

## `manage_pipeline` usage

`manage_pipeline` is the recommended facade today. Legacy tools still exist, but new tutorials should prefer the facade.

### `action="list"`

```python
manage_pipeline()
manage_pipeline(action="list")
manage_pipeline(action="list", tag="sedation")
manage_pipeline(action="list", scope="workspace")
```

### `action="save"`

```python
manage_pipeline(
    action="save",
    name="weekly_remimazolam",
    config="""
template: comprehensive
template_params:
  query: remimazolam ICU sedation
  sources: pubmed,openalex,europe_pmc
  limit: 30
""",
    tags="sedation,icu",
    description="Weekly remimazolam surveillance",
    scope="workspace",
)
```

`config` must parse to a YAML/JSON mapping, not a list or scalar. If a client has trouble quoting multi-line YAML through `manage_pipeline(action="save")`, call `save_pipeline(name=..., config=...)` with the same YAML string; both tools use the same validator.

`scope` behavior:

- `workspace`: saved under `.pubmed-search/pipelines/` inside the project
- `global`: saved under the user data directory `~/.pubmed-search-mcp/pipelines/`
- `auto`: save to workspace when available, otherwise global

### `action="load"`

```python
manage_pipeline(action="load", source="weekly_remimazolam")
manage_pipeline(action="load", source="saved:weekly_remimazolam")
manage_pipeline(action="load", source="file:data/pipeline_examples/pico_remimazolam_vs_propofol.yaml")
```

`load_pipeline` and `manage_pipeline(load)` currently support:

- saved names
- `saved:<name>`
- `file:path/to/pipeline.yaml`

Direct URL loading is not currently part of the supported contract.

### `action="delete"`

```python
manage_pipeline(action="delete", name="weekly_remimazolam")
```

### `action="history"`

```python
manage_pipeline(action="history", name="weekly_remimazolam", limit=10)
```

### `action="schedule"`

```python
manage_pipeline(
    action="schedule",
    name="weekly_remimazolam",
    cron="0 9 * * 1",
    diff_mode=True,
    notify=True,
)
```

### Legacy tool mapping

| Facade | Legacy tool |
| ------ | ------ |
| `manage_pipeline(action="save", ...)` | `save_pipeline(...)` |
| `manage_pipeline(action="list", ...)` | `list_pipelines(...)` |
| `manage_pipeline(action="load", ...)` | `load_pipeline(...)` |
| `manage_pipeline(action="delete", ...)` | `delete_pipeline(...)` |
| `manage_pipeline(action="history", ...)` | `get_pipeline_history(...)` |
| `manage_pipeline(action="schedule", ...)` | `schedule_pipeline(...)` |

## Schedule and History

### Recommended flow

1. Save the pipeline first
2. Use `unified_search(query="", pipeline="saved:<name>")` for manual execution
3. Use `schedule_pipeline(...)` or `manage_pipeline(action="schedule", ...)` for recurring runs
4. Use `get_pipeline_history(name="...")` or facade `history` to inspect run history

### Scheduling

```python
schedule_pipeline(name="weekly_remimazolam", cron="0 9 * * 1")
schedule_pipeline(name="monthly_crispr_review", cron="0 8 1 * *")
schedule_pipeline(name="watch_icu_sedation", cron="0 */6 * * *")
```

Cron format is the standard 5-field form:

```text
minute hour day month weekday
```

To remove a schedule:

```python
schedule_pipeline(name="weekly_remimazolam", cron="")
```

### History

```python
get_pipeline_history(name="weekly_remimazolam", limit=5)
manage_pipeline(action="history", name="weekly_remimazolam", limit=5)
```

History shows:

- execution time
- total article count
- how many articles were added compared with the previous run
- how many were removed
- success or failure status

### Current limitations

- There is no standalone `list_schedules()` MCP tool yet
- If you want stable history and diffs, prefer saved pipelines over one-off inline pipelines

## Common errors and auto-fix behavior

Auto-fix currently happens mainly during schema parsing and semantic validation. In practice, the system first repairs data shape and then repairs meaning when possible.

### Cases that are auto-fixed

| Problem | Input | Auto-fixed result |
| ---- | ---- | -------- |
| action alias | `find` | `search` |
| action typo | `searc` | `search` |
| template alias | `clinical` | `pico` |
| template typo | `comprehensiv` | `comprehensive` |
| single-string inputs | `inputs: s1` | `inputs: [s1]` |
| non-dict params | `params: "oops"` | `params: {}` |
| missing step id | `id: ""` | auto-filled as `step_1` and similar |
| duplicate step id | `search`, `search` | second one becomes `search_2` |
| reference to missing step | `inputs: [missing]` | that reference is removed |
| reference to future step | `inputs: [later_step]` | that reference is removed |
| invalid `on_error` | `retry` | `skip` |
| invalid output format | `xml` | `markdown` |
| mistyped output ranking | `impac` | `impact` |
| invalid output limit | `0` or negative | `20` |

`output.format: json` is valid and is no longer auto-fixed to Markdown.

### Cases that are not auto-fixed and will fail

| Problem | Why it fails |
| ---- | ---- |
| template name is completely unrecognizable | no alias or fuzzy match applies |
| action name is completely unrecognizable | no alias or fuzzy match applies |
| template is missing required parameters | for example, `pico` without `P` or `I` |
| there are no `steps` and no `template` | nothing executable remains |
| more than 20 steps | exceeds the system limit |

### One intentionally broken example

```yaml
template: clinical
template_params:
  P: ICU patients
  I: remimazolam
output:
  format: xml
  limit: 0
  ranking: impac
```

The system currently auto-fixes it to the equivalent of:

```yaml
template: pico
template_params:
  P: ICU patients
  I: remimazolam
output:
  format: markdown
  limit: 20
  ranking: impact
```

### Practical recommendations

1. If you want auto-fix, history, and scheduling, save first and run second.
2. Use inline template pipelines only for small parameter sets. For review and versioning, save YAML files.
3. Start custom DAGs from the smallest runnable graph, then add `merge`, `metrics`, and `filter` incrementally.
4. Use `scope="workspace"` when the pipeline should be shared within a team or repo.
5. Use `scope="global"` when you only want your own reusable search habits across projects.
6. Keep Zotero Keeper integration outside PubMed MCP core. PubMed MCP should produce RIS/CSL/JSON/wiki notes; Zotero Keeper or another external client should handle Zotero import, duplicate policy, and library-specific behavior.
