<!-- Synced from docs/PIPELINE_MODE_TUTORIAL.en.md by scripts/build_docs_site.py -->

# Pipeline Mode Tutorial

> Status: current API tutorial
> Last updated: 2026-08-09
> Language: **English** | [繁體中文](pipeline-tutorial.zh-TW.md)

This document only describes pipeline mode behavior that is currently implemented and supported. It does not repeat older RFC or design-draft material. The focus is what you can execute now, save now, schedule now, and inspect through history now.

## Pipeline Mode Quick Start

![Pipeline entry points and execution workflow](../../../../docs/images/pipeline-entrypoints-and-dag.svg)

Pipeline mode currently has 3 practical entry points:

1. Pass YAML or JSON directly into `unified_search(..., pipeline="...")`
2. Save the config with `save_pipeline`, then run it with `saved:<name>`
3. Save it first, then schedule recurring runs with `schedule_pipeline`

> **Choose the runtime first.** Trusted local stdio/loopback callers can use
> project workspace scope, `file:` sources, and the in-process scheduler.
> Authenticated service callers use only their principal-scoped saved-pipeline
> store: no process-wide workspace scope or `file:` reads. The service Compose
> profile disables the scheduler until an operator supplies a single external
> leader/lease.

### Smallest usable example: inline template

```python
unified_search(
    query="",
    pipeline="""
template: pico
template_params:
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
save_pipeline(
    name="icu_remi_vs_propofol",
    config="""
template: pico
template_params:
  P: ICU patients requiring mechanical ventilation
  I: remimazolam
  C: propofol
  O: delirium, sedation quality
output:
  limit: 25
  ranking: quality
""",
    tags=["icu", "sedation", "remimazolam"],
    description="ICU sedation comparison",
)

unified_search(query="", pipeline="saved:icu_remi_vs_propofol")
```

### Structured output and continuation tools

Pipeline reports now include filter diagnostics and next-step handoffs. At the bottom of a Markdown report, the recommended continuation tools are:

- `read_session(request={"action":"pmids"})` for the run PMID set
- `prepare_export(pmids="last", format="ris")` for Zotero/EndNote/Mendeley-style citation handoff
- `save_literature_notes(pmids="last", note_format="wiki")` for local wiki/Foam-compatible Markdown notes

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
| You want to reuse the same search strategy | `save_pipeline(...)` |
| You want history diffs or local scheduling | save first, then use `saved:<name>` or `schedule_pipeline` |
| A trusted local caller wants to load a YAML file | `load_pipeline(source="file:path/to/pipeline.yaml")` |
| An authenticated service caller wants reuse | save in the tenant store, then use `saved:<name>` |

## Template Pipeline Tutorial

Template pipelines cover roughly 80% of normal use cases. The YAML is not sent directly into the executor as-is. It is first expanded into a real step DAG.

### 4 templates currently available

| Template | Required parameters | Common optional parameters | Purpose |
| -------- | -------- | ------------ | ---- |
| `pico` | `P`, `I` | `C`, `O`, `sources`, `limit` | Clinical comparison question |
| `comprehensive` | `query` | `sources`, `limit`, `min_year`, `max_year` | Broad multi-source search |
| `exploration` | `pmid` | `limit` | Explore outward from one seed paper |
| `gene_drug` | `term` | `sources`, `limit`, `min_year`, `max_year` | Gene- or drug-focused search |

### Canonical `template_params`

Template pipelines accept exactly one parameter field: `template_params`.
The retired top-level `params` spelling is rejected instead of being rewritten.
Step-based DAGs continue to use `params` inside each individual step.

### `pico`

```yaml
template: pico
template_params:
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
template_params:
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

![Custom pipeline DAG workflow](../../../../docs/images/custom-pipeline-dag.svg)

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
| `id` | Required | Exact unique step ID; it is never generated or repaired |
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
- When upstream is `pico`, you can also use `use_combined: precision|recall|intervention_outcome|comparison_outcome`
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

## Single-purpose pipeline tools

Pipeline management deliberately uses seven schema-exact tools. Each operation
exposes only its own valid arguments, so misspelled or irrelevant fields fail
closed under the v3 MCP contract.

### List

```python
list_pipelines()
list_pipelines(tag="sedation")
list_pipelines(scope="workspace")
```

### Save

```python
save_pipeline(
    name="weekly_remimazolam",
    config="""
template: comprehensive
template_params:
  query: remimazolam ICU sedation
  sources: pubmed,openalex,europe_pmc
  limit: 30
""",
    tags=["sedation", "icu"],
    description="Weekly remimazolam surveillance",
    scope="workspace",
)
```

`config` must parse to a YAML/JSON mapping, not a list or scalar. `tags` is a
JSON array of at most 20 strict strings; CSV text is rejected.

`scope` behavior:

- local `workspace`: saved under `.pubmed-search/pipelines/` inside the project
- local `global`: saved under the user data directory `~/.pubmed-search-mcp/pipelines/`
- local `auto`: save to workspace when available, otherwise global
- authenticated service: the tenant-derived store deliberately has no
  process-wide workspace root; `auto` resolves to that principal's isolated
  data root and `workspace` is unavailable

### Load

```python
load_pipeline(source="weekly_remimazolam")
load_pipeline(source="saved:weekly_remimazolam")
load_pipeline(source="file:data/pipeline_examples/pico_remimazolam_vs_propofol.yaml")
```

`load_pipeline` currently supports:

- saved names
- `saved:<name>`
- local-only `file:path/to/pipeline.yaml`

Authenticated service callers cannot read `file:` paths from the server host;
save the YAML by name first. Direct URL loading is not currently part of the
supported contract.

### Delete

```python
delete_pipeline(name="weekly_remimazolam")
```

### History

```python
get_pipeline_history(name="weekly_remimazolam", limit=10)
```

### Schedule

```python
schedule_pipeline(
    name="weekly_remimazolam",
    cron="0 9 * * 1",
    diff_mode=True,
    notify=True,
)
```

### Unschedule

```python
unschedule_pipeline(name="weekly_remimazolam")
```

## Schedule and History

### Recommended flow

1. Save the pipeline first
2. Use `unified_search(query="", pipeline="saved:<name>")` for manual execution
3. Use `schedule_pipeline(...)` for recurring runs
4. Use `get_pipeline_history(name="...")` to inspect run history

### Scheduling

The examples below require a trusted local process with the scheduler enabled.
`docker-compose.service.yml` disables the in-process scheduler. Storing schedule
metadata in a service does not make it execute; use manual runs or provide one
external leader/lease before enabling recurring execution.

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
unschedule_pipeline(name="weekly_remimazolam")
```

### History

```python
get_pipeline_history(name="weekly_remimazolam", limit=5)
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
- Service mode stays single-process/single-replica, and its Compose profile does
  not run scheduled pipelines

## Validation and exact bounds

Pipeline identifiers, types, and enum-like values are schema-exact. The
validator does not coerce scalar types, clip explicit values, or guess caller
intent from aliases, spelling similarity, or nearby step IDs. Published safety
bounds are validation constraints, not normalization rules.

`output.format: json` is a canonical valid format and remains unchanged.

### Cases that fail without repair

| Problem | Why it fails |
| ---- | ---- |
| retired template field `params` | use canonical `template_params` |
| unknown or misspelled template | only the four canonical template names are accepted |
| unknown or misspelled action | only the ten canonical action names are accepted |
| missing or duplicate step ID | step identity is never generated or rewritten |
| unknown or future dependency ID | dependency references are never guessed or removed |
| invalid `on_error`, output format, or ranking | enum-like values are never substituted |
| output/action/template limit below or above its published range | explicit limits are never defaulted or clipped |
| wrong types or explicit `null` | values are never coerced to strings, lists, mappings, or integers |
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

This config is rejected. Write the intended canonical values explicitly:

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

1. Validate with `dry_run=True` before saving or scheduling a long pipeline.
2. Use inline template pipelines only for small parameter sets. For review and versioning, save YAML files.
3. Start custom DAGs from the smallest runnable graph, then add `merge`, `metrics`, and `filter` incrementally.
4. In local mode, use `scope="workspace"` when the pipeline should be shared in a trusted repo.
5. In local mode, use `scope="global"` for your own reusable search habits across projects.
6. In authenticated service mode, omit workspace/file paths and reuse named pipelines from the current tenant store.
7. Keep Zotero Keeper integration outside PubMed MCP core. PubMed MCP should produce RIS/CSL/JSON/wiki notes; Zotero Keeper or another external client should handle Zotero import, duplicate policy, and library-specific behavior.
