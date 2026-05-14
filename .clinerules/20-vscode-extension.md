---
paths:
  - "vscode-extension/**"
---

# VS Code Extension Rules

## Commands (run in `vscode-extension/`)
- `npm run lint`
- `npm run test:unit`
- `npm run test:ci`

## Behaviors To Preserve
- Never override VS Code default **Save As** for `.dfm` files.
- Treat overwriting a source DOCX as a data-loss risk: prompt when mtime changed.
- Parse MCP responses defensively: Markdown, fenced JSON, alias keys, and bilingual labels are all expected.
- Prefer persistence and stale-session cleanup over brittle in-memory-only state.

## Implementation Style
- Prefer clear control flow and defensive parsing over clever regex.
- Keep prompts explicit when an action is irreversible.
