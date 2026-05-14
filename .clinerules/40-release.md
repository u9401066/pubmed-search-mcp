---
paths:
  - "pyproject.toml"
  - "src/__init__.py"
  - "uv.lock"
  - "Dockerfile"
  - "vscode-extension/package.json"
  - "vscode-extension/package-lock.json"
  - "CHANGELOG.md"
  - ".github/workflows/release.yml"
---

# Release Rules

## Version Sources (must stay in sync)
- Python: `pyproject.toml`, `src/__init__.py`
- Docker label: `Dockerfile`
- VS Code extension: `vscode-extension/package.json` + `package-lock.json`
- Lockfile: `uv.lock` (regenerate with `uv lock` when needed)
- Changelog: `CHANGELOG.md` (add a dated section)

## Minimum Pre-Tag Verification
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src --ignore-missing-imports`
- `uv run pytest`
- `(cd vscode-extension && npm run test:ci)` (includes VSIX package-contents guard)
- VSIX install smoke test (recommended; required in CI): `npm run test:install-smoke` (Linux activation: `xvfb-run -a npm run test:install-smoke -- --require-activation`)
- Docker smoke import: `docker build ...` + `python -c "import src.presentation.server"`
- `uv build`
- `git diff --check`

## Tag Format
- Annotated tags: `vX.Y.Z`
- Push commit first, then push the tag.

Tip: use the workflow `/release-publish.md` in `.clinerules/workflows/` for a guided release.
