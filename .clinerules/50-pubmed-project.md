# PubMed Search MCP Project Rules

These rules are meant for Cline usage in the PubMed Search MCP repository.

## Goals

- Provide a robust MCP server for biomedical literature search, analysis, full-text access, and citation export.
- Make `unified_search` the default entrypoint while preserving specialized tools for PICO, MeSH, full text, citations, and pipelines.
- Keep outputs useful for downstream agents and for Zotero Keeper imports.

## Repo Layout

- `src/pubmed_search/domain/`: domain entities and value objects.
- `src/pubmed_search/application/`: search, export, pipeline, and analysis use cases.
- `src/pubmed_search/infrastructure/`: external clients and source integrations.
- `src/pubmed_search/presentation/mcp_server/`: MCP server, tools, prompts, and resources.
- `tests/`: pytest suite.
- `.claude/skills/`: user-facing research skills.
- `.cline/skills/` and `.clinerules/`: Cline harness assets.

## Canonical Commands

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src/ tests/`
- `uv run pytest`
- `uv run python scripts/count_mcp_tools.py --update-docs`
- `python3 scripts/check_cline_skills.py`

## Safety / Hygiene

- Avoid editing generated outputs unless the generator was run intentionally.
- Never commit NCBI API keys, Semantic Scholar keys, CORE keys, OpenAlex keys, cookies, or institutional resolver secrets.
- Avoid destructive git operations unless explicitly requested.
- Keep network-dependent behavior mockable and rate-limit aware.

## Prefer Existing Patterns

- Reuse source adapters and registry abstractions instead of adding one-off HTTP calls.
- Keep MCP tools small and delegate behavior to application services.
- Keep backward-compatible aliases where agents already consume fields.
- Update tool docs and user-facing skills when tool contracts change.
