---
name: pubmed-search-mcp-harness
description: "Codex harness for PubMed Search MCP. Triggers: pubmed search, literature search, unified_search, pipeline, fulltext, release checklist, Codex."
---

# PubMed Search MCP: Codex Harness Skill

Use this skill when working with Codex on PubMed Search MCP research workflows,
pipeline state, fulltext access, exports, and release checks.

## What To Read First

- `AGENTS.md` for Codex workspace instructions.
- `.github/agents/research.agent.md` for research-agent behavior.
- `.github/hooks/` and `scripts/hooks/copilot/` for pipeline enforcement assets.
- `.claude/skills/pubmed-*` and `.claude/skills/pipeline-persistence` for user-facing workflows.
- `.clinerules/` for project/release rules that also apply to Codex.

## Canonical Commands

- Lint: `uv run ruff check .`
- Format check: `uv run ruff format --check .`
- Types: `uv run mypy src/ tests/`
- Tests: `uv run pytest`
- Tool docs sync: `uv run python scripts/count_mcp_tools.py --update-docs`
- Skill audit: `python scripts/check_cline_skills.py`

## Research Guardrails

- Prefer `unified_search` as the primary multi-source entrypoint.
- Preserve session/pipeline state instead of relying on agent memory.
- Respect NCBI email/API-key policy and institutional access configuration.
- Keep exported citations reproducible with PMIDs, DOI, source, date filters, and query strategy.
