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
- Do not remove old fields without tolerating them for at least one release cycle.

## Research Workflow Rules

- Use `generate_search_queries` and `analyze_search_query` before complex/systematic searches.
- For clinical comparison questions, extract P/I/C/O in the agent, then use `parse_pico` to validate the structured handoff and obtain a runnable PICO pipeline.
- `build_research_chronicle` is the single research-evolution entry point; the old timeline tools were folded into it. Read stored chronicles with `read_research_chronicle` (`load` / `list` / `diff` / `narrate` / `milestones` / `compare`) instead of rebuilding.
- When `unified_search` returns an `artifact_summary`, preserve the user-facing summary and use `read_session(action="artifact", artifact_uri=...)` for deeper audit files.
- Use `get_fulltext`, `get_article_figures`, and institutional access tools only when full-text retrieval is requested.
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
