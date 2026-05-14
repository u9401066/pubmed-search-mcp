# Zotero Keeper Project Rules

These rules are meant for Cline usage in the Zotero Keeper repository.

## Goals

- Build a local MCP toolkit that combines Zotero reference management with PubMed literature search.
- Keep the user path simple: VS Code extension setup should install Python, packages, MCP definitions, and assistant assets without manual glue.
- Preserve research safety: ask before importing into Zotero collections, avoid duplicates, and keep source metadata traceable.

## Repo Layout

- `mcp-server/src/zotero_mcp/`: Zotero Keeper Python MCP server.
- `mcp-server/tests/`: unit and integration tests for the Zotero server.
- `external/pubmed-search-mcp/`: PubMed Search MCP submodule used by the extension.
- `vscode-extension/`: VS Code extension that registers both MCP servers and installs assistant assets.
- `.github/`: Copilot instructions, agents, bylaws, and CI/release workflows.
- `.claude/skills/` and `.cline/skills/`: assistant-facing operational skills.

## Canonical Commands

- Zotero server checks: `cd mcp-server && uv run pytest`
- Zotero lint/type checks: `cd mcp-server && uv run ruff check . && uv run mypy src --ignore-missing-imports`
- Extension checks: `cd vscode-extension && npm run sync-assets && npm run compile && npm test`
- VSIX package smoke: `cd vscode-extension && npm run package`
- Diff hygiene: `git diff --check`

## Safety / Hygiene

- Avoid editing generated outputs: `vscode-extension/out/`, `dist/`, `.venv/`, `.pytest_cache/`, `__pycache__/`.
- Never print or commit secrets from `.env`, NCBI API keys, Zotero credentials, or key files.
- Do not use destructive git commands unless the user explicitly asks.
- Submodule changes under `external/pubmed-search-mcp/` must be intentional and called out in status.

## Prefer Existing Patterns

- Keep MCP tool outputs backward-compatible when possible.
- Use `import_articles` for PubMed-to-Zotero import flows unless a legacy path is explicitly requested.
- Keep extension bundled asset sources and `vscode-extension/resources/repo-assets/` in sync via `npm run sync-assets`.
- Start context reads with `memory-bank/activeContext.md`, `ARCHITECTURE.md`, and `docs/COLLABORATION_WORKFLOW.md` when the task is architectural.
