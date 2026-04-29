<!-- Generated from docs/TOOLS_USAGE_GUIDE.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# PubMed Search MCP Tools Usage Guide

Capability-first guide for using the 45-tool PubMed Search MCP surface without treating the tool list as a menu to memorize.

## Reading Order

1. Start with the capability family that matches the user intent.
2. Use session tools to reuse the latest result set instead of asking the model to remember PMIDs.
3. Export citations or notes only after the evidence set is clear.
4. Use the raw [tools index](#/quick-reference) only when you need exact tool names.

## The 8 Capability Families

| Capability | Primary Tools | Use When |
| --- | --- | --- |
| Search entry | `unified_search` | The user wants papers, articles, or a first pass over a topic. |
| Query intelligence | `analyze_search_query`, `parse_pico`, `generate_search_queries` | The query needs MeSH, PICO, synonym expansion, or strategy planning. |
| Discovery | `fetch_article_details`, `find_related_articles`, `find_citing_articles`, `get_article_references`, `build_citation_tree` | The user has seed PMIDs and wants context, related work, or citation lineage. |
| Full text and figures | `get_fulltext`, `get_text_mined_terms`, `get_article_figures` | The user needs article body text, evidence sections, entities, captions, or image URLs. |
| External biomedical data | `search_gene`, `get_gene_details`, `search_compound`, `get_compound_details`, `search_clinvar` | The research question moves from papers into NCBI gene, compound, or clinical variant data. |
| Evaluation and timeline | `get_citation_metrics`, `build_research_timeline`, `analyze_timeline_milestones`, `compare_timelines` | The user asks what matters, what changed over time, or how fields compare. |
| Persistence and sessions | `read_session`, `get_session_pmids`, `get_cached_article`, `get_session_summary`, pipeline tools | The user wants to resume, repeat, audit, schedule, or save a search workflow. |
| Export and local notes | `prepare_export`, `save_literature_notes` | The user wants Zotero/EndNote/BibTeX files or local Markdown/wiki notes. |

## Intent Routing

| User Intent | Recommended Flow |
| --- | --- |
| Quick literature search | `unified_search(query=..., limit=...)` |
| Clinical comparison | `parse_pico` -> `generate_search_queries` -> `unified_search` |
| Systematic review seed | `analyze_search_query` -> `generate_search_queries` -> `unified_search` -> `save_pipeline` |
| Important paper exploration | `fetch_article_details` -> `find_related_articles` / `find_citing_articles` / `get_article_references` |
| Full-text synthesis | `get_fulltext` -> `get_text_mined_terms` -> structured summary |
| Zotero handoff | `prepare_export(pmids="last", format="ris")` or Zotero Keeper import tools |
| Local knowledge-base notes | `save_literature_notes(pmids="last")` |
| Repeatable search workflow | `save_pipeline` -> `unified_search(pipeline="saved:<name>")` |

Zotero Keeper should remain an external integration boundary. PubMed Search MCP produces RIS/CSL/JSON exports and local wiki notes; Zotero Keeper or another client owns Zotero import, duplicate handling, and library-specific policies.

## Local Wiki Note Export

Use `save_literature_notes` when the user wants a guided, semi-structured file output after search. This is better than asking an agent to assemble a Markdown note with a generic write-file operation.

Default behavior:

```python
save_literature_notes(pmids="last")
```

The default `note_format` is `wiki`. It writes one `.md` file per article with:

- YAML frontmatter for title, PMID, DOI, PMCID, journal, year, citation key, aliases, and tags
- Foam-compatible wikilinks in the generated index note
- triage fields for status, relevance, and decision
- summary, key findings, methods/population, limitations, and follow-up question sections
- source links to PubMed, DOI, and PMC when available
- a CSL JSON sidecar for citation-manager handoff

Supported note formats:

| Format | Link Style | Layout | Best For |
| --- | --- | --- | --- |
| `wiki` | `[[note|title]]` | default guided literature note | Foam, Obsidian-style, and general wiki workflows |
| `foam` | `[[note|title]]` | same compatible profile as `wiki` | existing Foam-specific users |
| `markdown` | `[title](note.md)` | same guided sections | plain Markdown repositories |
| `medpaper` | `[[citation_key|title]]` | verified reference note plus `metadata.json` | MedPaper-style or Zotero Keeper-compatible reference libraries |

Directory resolution:

1. `output_dir`, if provided
2. `PUBMED_NOTES_DIR`
3. `PUBMED_WORKSPACE_DIR/references`
4. `PUBMED_DATA_DIR/references`
5. `~/.pubmed-search-mcp/references`

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
aliases: ["smith2024_12345678", "12345678", "Smith 2024"]
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

Use `template_file` when a user has a house style:

```python
save_literature_notes(
    pmids="last",
    output_dir="./references",
    template_file="./reference-template.md"
)
```

Available placeholders include `{title}`, `{pmid}`, `{doi}`, `{pmc_id}`, `{journal}`, `{year}`, `{authors}`, `{abstract}`, `{citation_key}`, `{reference_id}`, `{note_format}`, `{created}`, `{pubmed_url}`, `{doi_url}`, `{citation}`, `{keywords}`, `{mesh_terms}`, and `{csl_json}`.

## Pipeline And Packaged Agent References

Pipeline tutorials live canonically in:

- `docs/PIPELINE_MODE_TUTORIAL.en.md`
- `docs/PIPELINE_MODE_TUTORIAL.md`

`scripts/build_docs_site.py` also syncs those tutorials into `.claude/skills/pipeline-persistence/references/` so external agent bundles and VSIX packages that do not ship `docs/site-content/` can still read them.
