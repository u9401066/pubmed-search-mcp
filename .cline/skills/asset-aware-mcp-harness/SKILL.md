---
name: asset-aware-mcp-harness
description: "Cline harness for this repo (rules + workflows + checks). Triggers: cline harness, full check, release checklist, workflow, 文檔工作流, DFM, citation-ready."
---

# asset-aware-mcp: Cline Harness Skill

Use this skill when working in this repo with Cline and you want a reliable, production-grade loop: change -> verify -> ship.

## What To Use First
- Rules: `.clinerules/` (always-on, with conditional scopes)
- Workflows: `.clinerules/workflows/`
  - Run `/full-check.md` for the full local gates
  - Run `/release-publish.md` for a guided tagged release
- VSIX assistant assets: `vscode-extension/resources/repo-assets/asset-aware/`
  - Keep them synchronized with `cd vscode-extension && npm run sync-assets:check`
- Skills: this repo already has multiple skills under `.claude/skills/` (Cline can load them too)
  - If any `.claude/skills` instruction conflicts with current repo behavior, treat `.clinerules/` as the source of truth.

## Canonical Commands
- Python: `uv run ruff check .`, `uv run mypy src --ignore-missing-imports`, `uv run pytest`
- Extension (in `vscode-extension/`): `npm run test:ci`
- Docker smoke: `docker build -t asset-aware-mcp:smoke .` then `docker run --rm --entrypoint python asset-aware-mcp:smoke -c "import src.presentation.server"`

## Citation-Ready Mindset
- Prefer stable, verifiable spans (line/char/byte offsets + hashes) over loose “source: page 3” citations.
- Treat CRAAP fields as a conservative scaffold: avoid claiming more confidence than you can actually verify.

## MCP Auto-Config Mindset
- VSIX install/update must keep Copilot `.vscode/mcp.json`, Cline `cline_mcp_settings.json`, and Codex `config.toml` idempotent.
- Preserve unrelated MCP servers and user-local Cline/Codex metadata.
- Do not create duplicate Asset-Aware server entries under alternative names.
