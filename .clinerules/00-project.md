# asset-aware-mcp: Project Rules

These rules are meant for Cline usage in this repository.

## Goals
- Build an MCP server and VS Code extension for **asset-aware, citation-ready** document workflows.
- Prefer correctness and reproducibility: deterministic outputs, clear error paths, and tests for regressions.

## Repo Layout (DDD-ish)
- `src/domain/`: pure domain models/value objects (avoid I/O and framework coupling)
- `src/application/`: services/use-cases (coordinate domain + infrastructure)
- `src/infrastructure/`: adapters (DOCX/PDF/Marker/LightRAG, file I/O)
- `src/presentation/`: MCP tool layer + server wiring
- `vscode-extension/`: client integration (TypeScript)

## Canonical Commands
- Python checks: `uv run ruff check .`, `uv run mypy src --ignore-missing-imports`, `uv run pytest`
- VS Code extension checks (run in `vscode-extension/`): `npm run test:ci`
- Docker smoke: `docker build -t asset-aware-mcp:smoke .` then `docker run --rm --entrypoint python asset-aware-mcp:smoke -c "import src.presentation.server"`

## Safety / Hygiene
- Avoid editing or committing generated/ignored outputs: `dist/`, `vscode-extension/out/`, `data/`, `.venv/`.
- Never print or commit secrets from `.env`, key files, or `secrets/`.
- Avoid destructive git operations (`reset --hard`, `clean -fdx`) unless explicitly asked.

## Prefer Existing Patterns
- Keep MCP tool outputs backward-compatible when possible (tolerate alias keys / bilingual labels when parsing).
- Add focused tests with fixes; keep changes minimal and scoped.
- If you need product/architecture context, start with `memory-bank/activeContext.md` and `ARCHITECTURE.md`.

## Repo Defaults
- Default branch: `master` (release workflows assume this unless the repo is reconfigured).
- Use `.clineignore` to keep Cline indexing fast; explicitly mention ignored fixtures when you need them.
