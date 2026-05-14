---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
  - "scripts/**/*.py"
  - "pyproject.toml"
  - "uv.lock"
---

# Python Rules (uv / ruff / mypy / pytest)

## Environment
- Use `uv` for running tools (avoid ad-hoc `pip` commands).
- Prefer `uv run ...` so checks execute in the right venv and dependency set.

## Architecture Guardrails
- Keep `src/domain` free of I/O, filesystem access, and infrastructure imports.
- Put orchestration/side-effects in `src/application` or `src/infrastructure`.

## Validation Gates
- Lint: `uv run ruff check .`
- Types: `uv run mypy src --ignore-missing-imports`
- Tests: `uv run pytest`

## Messy Document Inputs (DOCX/DFM)
- Assume hostile/converted inputs: mixed encodings, broken numbering, odd whitespace, nested lists/tables.
- Favor tolerant parsing with explicit fallbacks over strict assumptions.
- Add a regression test when touching DOCX parsing/rendering logic (start with `tests/test_dfm.py` and `tests/integration/test_docx_save_flow.py`).
