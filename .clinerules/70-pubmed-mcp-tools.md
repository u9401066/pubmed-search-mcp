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

- Keep `unified_search` as the primary search facade.
- Preserve session-aware flows: cached articles, last PMIDs, search history, and pipeline state.
- Return source counts and warnings when a source fails or contributes zero results.
- Keep output formats stable for markdown, JSON, RIS, BibTeX, CSV, and MEDLINE.
- Do not remove old fields without tolerating them for at least one release cycle.

## Research Workflow Rules

- Use `generate_search_queries` and `analyze_search_query` before complex/systematic searches.
- Use `parse_pico` for clinical comparison questions.
- Use `get_fulltext`, `get_article_figures`, and institutional access tools only when full-text retrieval is requested.
- Export to RIS for Zotero/EndNote and BibTeX for LaTeX workflows.

## Documentation Sync

When tools are added, removed, or renamed:

- Run `uv run python scripts/count_mcp_tools.py --update-docs`.
- Update relevant `.claude/skills/pubmed-*` skills.
- Update `.github/agents/research.agent.md` if the research flow changes.
- Add or update MCP protocol tests.
