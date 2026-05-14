---
name: asset-aware-mcp-harness
description: "Codex harness for Asset-Aware MCP. Triggers: asset-aware, MCP, PDF, DOCX, DFM, citation-ready, CRAAP, release checklist, VSIX."
---

# Asset-Aware MCP: Codex Harness Skill

Use this skill when working with Codex on this repository, the VS Code
extension, MCP configuration, citation-ready document pipelines, or release
verification.

## What To Read First

- `AGENTS.md` for Codex workspace instructions.
- `.github/copilot-instructions.md` for cross-agent project guardrails.
- `.clinerules/` for implementation and release rules that also apply here.
- `memory-bank/activeContext.md` for the current working focus.

## Canonical Commands

- Python checks: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src --ignore-missing-imports`, `uv run pytest`
- Extension checks: `cd vscode-extension && npm run test:ci`
- Assistant asset sync: `cd vscode-extension && npm run sync-assets:check`
- VSIX smoke: `cd vscode-extension && npm run test:install-smoke`
- Docker smoke: `docker build -t asset-aware-mcp:smoke .` then `docker run --rm --entrypoint python asset-aware-mcp:smoke -c "import src.presentation.server"`

## Citation-Ready Rules

- Prefer verifiable spans: source revision, span IDs, byte/char/line offsets,
  context text, and hashes.
- Keep CRAAP values conservative unless the implementation can justify them.
- Preserve aliases/backward compatibility when evolving MCP tool payloads.

## Release Rules

- Treat VSIX install/update as a first-class release path.
- Confirm Copilot, Cline, and Codex MCP config merge behavior remains
  idempotent and non-destructive.
- Do not tag until sync-assets, unit tests, package contents, install smoke,
  artifact audit, Docker smoke, and git diff hygiene are clean.
