---
paths:
  - "pyproject.toml"
  - "src/pubmed_search/__init__.py"
  - "uv.lock"
  - "CHANGELOG.md"
  - "README.md"
  - "README.zh-TW.md"
  - ".github/workflows/**"
  - ".claude/skills/**"
  - ".cline/skills/**"
  - ".clinerules/**"
---

# PubMed Release Rules

## Version Sources

- `pyproject.toml`
- `src/pubmed_search/__init__.py`
- `uv.lock`
- `CHANGELOG.md`
- Release tags: `vX.Y.Z`

## Minimum Verification

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src/ tests/`
- `uv run pytest`
- `uv run python scripts/count_mcp_tools.py --update-docs`
- `python3 scripts/check_cline_skills.py`
- `git diff --check`

## Release Hygiene

- Keep tool docs and skill references synchronized.
- Check that package metadata can be installed without requiring git.
- Confirm any downstream Zotero Keeper extension pin points at a reachable GitHub archive commit.
- Call out submodule pointer changes in the parent `zotero-keeper` repository.
