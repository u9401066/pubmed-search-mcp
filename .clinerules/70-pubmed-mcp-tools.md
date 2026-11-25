---
paths:
  - "src/pubmed_search/presentation/mcp_server/**"
  - "src/pubmed_search/application/**"
  - "src/pubmed_search/infrastructure/sources/**"
  - "scripts/count_mcp_tools.py"
  - ".claude/skills/pubmed-mcp-tools-reference/SKILL.md"
---

# PubMed MCP Tool Rules

## Tool Contract Rules

- Keep MCP `unified_search` as the primary agent search facade; Python callers should use `pubmed_search.api`.
- Preserve session-aware flows: cached articles, last PMIDs, search history, and pipeline state.
- Return source counts and warnings when a source fails or contributes zero results.
- Keep output formats stable for markdown, JSON, RIS, BibTeX, CSV, and MEDLINE.
- Treat public MCP inputs as strict contracts after the shared input normalization in `docs/guides/TOOLS_USAGE_GUIDE.md#input-formats-and-validation`. Breaking releases remove retired fields and aliases; update every live agent asset in the same change instead of preserving compatibility shims.

## Research Workflow Rules

- For a study that will span searches or agents, follow the [research workspace skill](../.claude/skills/pubmed-research-workspace/SKILL.md). Resume with `research_workspace(request={"action":"read","workspace_id":"..."})`. Record the evidence scope and outstanding question, then follow the relevant source handoff before drawing a conclusion.
- Use `generate_search_queries` and `analyze_search_query` before complex/systematic searches.
- For iterative normal searches, `options="exclude_seen"` filters earlier completed/partial session results by PMID/normalized DOI before `limit`; disclose counts or history warnings. It is rejected with `pipeline=`.
- For multi-seed exploration use pipeline template `snowball` (`query`, optional `seed_limit` 1–10/default 5, `limit` default 20): search → citing + references → union merge. Scheduled `diff_mode` reports bounded changes since the previous successful run; `notify` retains local run/count summaries, not external push delivery.
- Chronicle rebuilds add predecessor changes only to default summary output (up to five added titles). Inspect `branches.added_details[].evidence_observation` in a diff for the dates and IDs of existing and newly observed papers. An unreadable predecessor degrades to `Change summary unavailable`; corrupt latest revisions still fail loudly.
- For systematic reviews, save a PubMed search step with `retrieval: exhaustive` (no `limit`, `max_records` ≤ 10000) and run `unified_search(pipeline="saved:<name>")`; read the complete set via `get_pipeline_history(view="records"|"run"|"prisma_s")`, export it with `prepare_export(pipeline_run=...)`, screen and count PRISMA 2020 flow with `pipeline_screening`, and audit MeSH blocks with a `block_analysis` step.
- For clinical comparison questions, extract P/I/C/O in the agent, then use `validate_pico_plan` to validate the structured handoff and obtain a runnable PICO pipeline.
- `build_research_chronicle` is the single research-evolution entry point; the old timeline tools were folded into it. Inspect `output="chronicle_map"` for a candidate fork, earlier evidence of separate lines and contemporary comparative or consensus sources. Use `direct_activity` for counts within this revision and `output="mermaid"` for the diagram. Preserve warnings from `mermaid_validation.json` when a safe/minimal tier is used or visual items are omitted, and preserve audit warnings for research-stage fallback, capped/unknown source coverage, or at least 20% multi-signal branch overlap. In diffs, absence is `not_observed_in_revision`, never conclusive retirement. Read stored chronicles with `read_research_chronicle` (`load` / `list` / `diff` / `narrate` / `milestones` / `compare`) instead of rebuilding.
- When `unified_search` returns an `artifact_summary`, preserve the user-facing summary and use `read_session(request={"action":"artifact","locator":{"kind":"artifact_uri","value":"artifact://..."},"artifact_file":"audit.json"})` for deeper audit files.
- Use `get_fulltext`, `get_article_figures`, and institutional access tools only when full-text retrieval is requested.
- For planned close reading, `unified_search(fulltext="prefetch")` prepares bounded XML; use the returned PMCID with `get_fulltext` without polling. See `docs/guides/TOOLS_USAGE_GUIDE.md`; keep prefetch off for broad screening.
- Export to RIS for Zotero/EndNote and BibTeX for LaTeX workflows.

## Tenant Isolation Rules

The server can serve many agents at once, so session state must stay scoped:

- Resolve session state through `get_session_manager()`. Never capture a `SessionManager` in a closure at registration time; it would pin every caller to the startup tenant.
- `set_session_manager()` intentionally clears the per-tenant registry (single-caller mode). Anything that installs the registry must run *after* tool registration.
- `normalize_tenant_id()` must stay idempotent; the registry re-normalizes ids.
- Keep upstream per-API rate limits global (NCBI meters per API key). Per-caller fairness belongs to `PUBMED_TENANT_MAX_CONCURRENCY`.
- Any new store that writes under `data_dir` must route through the tenant's directory, not the shared root.

## Documentation Sync

When tools are added, removed, or renamed:

- Run `uv run python scripts/count_mcp_tools.py --update-docs`.
- Update relevant `.claude/skills/pubmed-*` skills.
- Update `.github/agents/research.agent.md` if the research flow changes.
- Add or update MCP protocol tests.
