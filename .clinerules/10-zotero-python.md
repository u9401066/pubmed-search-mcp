---
paths:
  - "mcp-server/**/*.py"
  - "mcp-server/pyproject.toml"
  - "mcp-server/uv.lock"
  - "scripts/**/*.py"
---

# Zotero Python Rules

## Environment

- Use `uv` for Python package and command execution.
- Prefer `uv run ...` from `mcp-server/` so commands use the correct dependency set.
- Avoid ad-hoc global installs.

## Architecture Guardrails

- Keep `domain/` free of I/O and infrastructure imports.
- Put Zotero HTTP access in `infrastructure/zotero_client/`.
- Keep MCP tool registration and validation in `infrastructure/mcp/`.
- Keep PubMed-specific mapping isolated in `infrastructure/mappers/pubmed_mapper.py` and bridge tools.

## Validation Gates

- Lint: `cd mcp-server && uv run ruff check .`
- Types: `cd mcp-server && uv run mypy src --ignore-missing-imports`
- Tests: `cd mcp-server && uv run pytest`

## Behavioral Rules

- Preserve duplicate detection by DOI, PMID, title, and Zotero item identity.
- Keep collection writes explicit; do not silently import into arbitrary collections.
- Return structured MCP responses that agents can parse without scraping prose.
- Add focused tests for tool behavior changes, especially import, saved-search, and collection flows.
