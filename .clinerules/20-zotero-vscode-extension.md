---
paths:
  - "vscode-extension/**"
---

# Zotero VS Code Extension Rules

## Commands

Run from `vscode-extension/`:

- `npm run sync-assets`
- `npm run compile`
- `npm test`
- `npm run package`

## Behaviors To Preserve

- Activation should register both Zotero Keeper and PubMed Search MCP servers when enabled.
- Embedded Python setup should be self-contained and should refresh packages when the pinned package source changes.
- PubMed Search installs must use the fixed GitHub archive commit from `src/pubmedSearchPackage.ts`.
- Official assistant assets must install into the workspace without overwriting custom user instructions.
- VSIX packaging must include `resources/repo-assets/**`, including nested `.github`, `.claude`, `.cline`, and `.clinerules` directories.

## Implementation Style

- Keep install paths cross-platform: use `path.join`, not string-concatenated separators.
- Treat package install state as part of versioning; update tests when changing package pins.
- Preserve user custom files unless the extension can recognize them as managed assets.
- Keep command titles accurate when behavior expands beyond Copilot-only assets.
