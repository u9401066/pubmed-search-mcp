---
paths:
  - "mcp-server/pyproject.toml"
  - "mcp-server/src/zotero_mcp/__init__.py"
  - "mcp-server/uv.lock"
  - "vscode-extension/package.json"
  - "vscode-extension/package-lock.json"
  - "vscode-extension/src/pubmedSearchPackage.ts"
  - "vscode-extension/.vscodeignore"
  - "CHANGELOG.md"
  - "vscode-extension/CHANGELOG.md"
  - ".github/workflows/**"
---

# Zotero Release Rules

## Version Sources

- Python package metadata: `mcp-server/pyproject.toml`
- Python runtime fallback: `mcp-server/src/zotero_mcp/__init__.py`
- VS Code extension: `vscode-extension/package.json` and `vscode-extension/package-lock.json`
- PubMed Search install pin: `vscode-extension/src/pubmedSearchPackage.ts`
- Changelogs: `CHANGELOG.md` and `vscode-extension/CHANGELOG.md`

## Minimum Verification

- `cd mcp-server && uv run ruff check .`
- `cd mcp-server && uv run mypy src --ignore-missing-imports`
- `cd mcp-server && uv run pytest`
- `cd vscode-extension && npm run sync-assets && npm run compile && npm test`
- `cd vscode-extension && npm run package`
- `git diff --check`

## VSIX Packaging Requirements

- Run `npm run sync-assets` before `vsce package`.
- Confirm the VSIX includes nested assistant assets under `resources/repo-assets/`.
- If `.vscodeignore` changes, check package contents before publishing.
- Keep generated `resources/repo-assets/` changes together with source assistant assets.

## Tag Format

- Extension release tags use `vX.Y.Z-ext`.
- Push the release commit before pushing the tag.
