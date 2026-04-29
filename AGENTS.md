# PubMed Search MCP Agent Baseline

Shared workspace guidance for agent clients that can read `AGENTS.md`.
Use this file for cross-tool baseline rules. Keep agent-specific behavior in
tool-native locations such as `.github/copilot-instructions.md` or
`.clinerules/` so the same instruction is not duplicated in multiple places.

## Scope

- This repository is a Python MCP server for biomedical literature search.
- The architecture follows DDD boundaries: presentation -> application -> domain,
  with infrastructure isolated behind those layers.
- Search, timeline, pipeline, export, session, and reference verification are
  product capabilities. MCP tools should remain thin wrappers over those
  services.
- Local literature notes default to wiki-note semantics. Foam-compatible
  wikilinks, MedPaper-style layouts, CSL JSON, and user templates are export
  profiles under the application export layer, not presentation-only behavior.

## Cross-tool Rules

- Use `uv` for dependency management and `uv run` for Python commands in this repo.
- Fix root causes instead of layering ad-hoc patches.
- Preserve DDD separation. Do not move business logic into MCP tool files,
  hooks, or shell scripts.
- Keep changes minimal and local. Avoid unrelated refactors when solving a
  focused problem.
- Update relevant docs when behavior, tool surface, or setup instructions change.
- When MCP tools are added, removed, or renamed, keep registry, docs, and
  generated artifacts in sync.
- When note export behavior changes, keep skills, Copilot instructions, Cline
  rules, generated docs, and packaged references aligned.
- Prefer existing repo assets over creating parallel variants. If a shared rule
  belongs here, do not duplicate it in `.clinerules/` or Copilot-only files.

## Important Paths

- `.github/copilot-instructions.md`: GitHub Copilot-specific runtime guidance
- `.clinerules/`: Cline-specific rules and workflows
- `.vscode/mcp.json`: workspace MCP setup for VS Code / Copilot Chat
- `.claude/skills/pipeline-persistence/references/`: packaged tutorial copies
  for agent bundles and VSIX integrations that do not read `docs/site-content/`
- `scripts/setup-vscode-ai-harness.sh`: install recommended VS Code extensions
- `docs/INTEGRATIONS.md`: client configuration reference

## Verification Baseline

- Narrow changes: run the smallest relevant validation first.
- Repo-wide validation when integration surfaces change:
  - `uv run pytest -q`
  - `uv run mypy src/ tests/`
  - `uv run python scripts/check_async_tests.py`

## Shared Constraints

- Do not add duplicate rule sets across tools. Put shared baseline rules here.
- Put Cline-only workflow automation in `.clinerules/workflows/`.
- Put Copilot-only hooks/chatmode/instruction behavior under `.github/`.
- Keep workspace-level AI assets version-controlled so users get a usable setup
  immediately after clone or packaging.
