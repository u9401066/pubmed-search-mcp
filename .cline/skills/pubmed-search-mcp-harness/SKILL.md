---
name: pubmed-search-mcp-harness
description: "Cline harness for PubMed Search MCP. Triggers: pubmed search, literature search, unified_search, pipeline, fulltext, release checklist, Cline."
---

# PubMed Search MCP: Cline Harness Skill

Use this skill when working in the PubMed Search MCP repository with Cline and you need
a dependable loop for literature-search tools, pipeline behavior, and release checks.

## What To Use First

- Rules: `.clinerules/`
- Workflows: `.clinerules/workflows/`
  - Run `/pubmed-full-check.md` for local gates.
  - Run `/pubmed-skills-audit.md` after changing skills or rules.
  - Run `/pubmed-release-publish.md` for release prep.
- User-facing research skills: `.claude/skills/pubmed-*` and `.claude/skills/pipeline-persistence`.
  - If a `.claude/skills` instruction conflicts with current implementation, prefer `.clinerules/`.

## Canonical Commands

- Lint: `uv run ruff check .`
- Format check: `uv run ruff format --check .`
- Types: `uv run mypy src/ tests/`
- Tests: `uv run pytest`
- Tool docs sync: `uv run python scripts/count_mcp_tools.py --update-docs`
- Skill audit: `python3 scripts/check_cline_skills.py`

## Research Guardrails

- Prefer `unified_search` as the primary multi-source entrypoint.
- Preserve session/pipeline state instead of relying on agent memory.
- Respect NCBI email/API-key policy and institutional access configuration.
- Keep exported citations reproducible: PMIDs, DOI, source, date filters, and query strategy matter.
