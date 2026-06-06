<!-- Generated from docs/ADVANCED_RESEARCH_WORKFLOWS.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# Advanced Research Workflows

This page makes the newer research surfaces visible from the docs-site
navigation: research timeline/lineage tree, Open-i image search, uploaded-image
handoff, and persistent query memory.

## Quick Map

| Need | Start here | Continue with |
| --- | --- | --- |
| See how a topic evolved over time | `build_research_timeline` | `analyze_timeline_milestones`, `compare_timelines` |
| Find biomedical images from text | `search_biomedical_images` | `get_article_figures`, `unified_search` |
| Upload or pass an image and search by its meaning | `analyze_figure_for_search` | `search_biomedical_images`, `unified_search` |
| Re-open large search/fulltext outputs without rerunning | `read_session(action="artifact")` | `read_session(action="list_artifacts")` |

## Research Timeline / Lineage Tree

Use timeline tools when the user asks how a field changed, which papers look like
milestones, or how two research tracks compare.

```python
build_research_timeline(topic="remimazolam ICU sedation", output_format="tree", max_events=20)
build_research_timeline(pmids="12345678,23456789", topic="Selected studies", output_format="mermaid")
analyze_timeline_milestones(topic="CAR-T therapy")
compare_timelines(topics="remimazolam,propofol,dexmedetomidine")
```

`build_research_timeline` accepts either a topic or a known PMID set, including
explicit comma-separated PMIDs. It supports `text`, `tree`, `mermaid`,
`mindmap`, `json`, `json_tree`, `timeline_js`, and `d3` output formats. For a
lightweight preview inside a normal search response, use
`unified_search(options="context_graph")`; it is a preview from the current
PMID-backed ranked set, not a complete graph. The planned persistent/versioned
Research Chronicle is specified in
[Research Chronicle Rebuild Spec](#/research-chronicle-rebuild-spec).

## Open-i Biomedical Image Search

Use `search_biomedical_images` when the visual finding is already text and the
goal is image evidence from Open-i.

```python
search_biomedical_images("chest X-ray pneumonia", sources="openi", image_type="x", limit=10)
search_biomedical_images("histology liver fibrosis", sources="openi", image_type="mc", license_type="by")
```

Open-i expects English medical terminology. For non-English prompts, the agent
should first translate anatomy, finding, and modality into English, then call
`search_biomedical_images`. Open-i is strongest for radiology, microscopy,
clinical photos, and teaching images; for article-native figures, use
`get_article_figures` on PMC Open Access articles.

## Uploaded Image To Literature Search

`analyze_figure_for_search` is the handoff tool for images supplied by an MCP
client. It accepts an image URL or a base64/data-URI image and returns MCP
`ImageContent` plus instructions for the LLM agent.

```python
analyze_figure_for_search(image="data:image/png;base64,...", search_type="medical")
```

The server does not perform standalone visual diagnosis. The intended workflow
is:

1. The MCP client passes the uploaded image or image URL to `analyze_figure_for_search`.
2. The LLM agent uses its vision capability to describe the image and extract English biomedical search terms.
3. The agent immediately continues with `search_biomedical_images` for similar biomedical images or `unified_search` for related papers.

## Persistent Query Memory

When session persistence is configured, large `unified_search` and
`get_fulltext` outputs can be saved as artifacts. The immediate tool response can
stay compact while the reusable payload remains available for later reads.

```python
read_session(action="list_artifacts")
read_session(action="artifact", artifact_id="...")
read_session(action="artifact", artifact_uri="artifact://...")
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="audit.json")
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="results.json", offset=0, max_chars=200000)
```

Artifacts are query memory, not a second search. Reading them does not rerun
external source calls. Local filesystem paths are redacted by default because
remote clients cannot read the server host path. Set
`PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS=true` only for local MCP clients that really
need `local_path` and `manifest_path`.

For `unified_search`, artifact files are intentionally richer than the immediate
MCP response. Read `audit.json` first for completeness warnings, then
`query_strategy.json` for the executed source/query plan, then `results.json` or
`results.toon` for the full article list. This keeps response tokens small while
leaving enough evidence for repeated agent reads, sandboxed clients, and future
remote artifact backends.

## Verification Status

The current primary 46-tool MCP server exposes these tools directly:

- Timeline: `build_research_timeline`, `analyze_timeline_milestones`, `compare_timelines`
- Image search: `search_biomedical_images`
- Uploaded-image handoff: `analyze_figure_for_search`
- Query memory: `read_session(action="artifact")`

Coverage is guarded by docs alignment tests, tool registry tests, image-search
tests, vision-search tests, timeline tests, and session artifact tests.
