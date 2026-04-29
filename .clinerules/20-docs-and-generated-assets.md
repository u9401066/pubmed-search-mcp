---
paths:
  - "README.md"
  - "README.zh-TW.md"
  - "docs/**"
  - ".vscode/**"
  - "copilot-studio/**"
  - ".github/**"
---

# Docs and generated asset rules

- Keep user-facing setup docs aligned with the real workspace assets and scripts.
- If README-driven docs site content changes, regenerate it with `uv run python scripts/build_docs_site.py`.
- Treat `docs/site-content/**` as generated website payload, not an external integration contract.
- If VSIX or agent bundles need a tutorial, sync it into a bundled asset such as `.claude/skills/**/references/`.
- Prefer one canonical setup document and link to it rather than copying the same setup text into multiple files.
- When describing Copilot vs Cline setup, separate shared baseline from client-specific overlay.
