---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
  - "scripts/**/*.py"
  - "pyproject.toml"
  - "uv.lock"
---

# PubMed Python Rules

## Environment

- Use `uv` for all Python commands.
- Prefer `uv run ...` so checks execute in the right environment.
- Do not introduce raw package-manager calls in docs, CI, or code paths.

## Architecture Guardrails

- Keep `domain/` free of I/O, environment reads, and framework imports.
- Keep external API calls in `infrastructure/`.
- Put orchestration in `application/`.
- Keep MCP presentation code as thin wrappers around services.
- Read configuration through shared settings, not scattered `os.environ` reads.

## Validation Gates

- Lint: `uv run ruff check .`
- Format: `uv run ruff format --check .`
- Types: `uv run mypy src/ tests/`
- Tests: `uv run pytest`

## Test Rules

- Use async tests and `AsyncMock` for async methods.
- Preserve xdist-friendly tests; avoid singleton state leaks.
- Mock external APIs unless a test is explicitly marked integration.
- Add regression tests for parsing, query expansion, ranking, source counts, and MCP tool contracts.
