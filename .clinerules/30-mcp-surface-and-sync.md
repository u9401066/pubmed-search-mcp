---
paths:
  - "AGENTS.md"
  - "src/pubmed_search/application/export/**"
  - "src/pubmed_search/presentation/mcp_server/**"
  - "scripts/count_mcp_tools.py"
  - "scripts/build_docs_site.py"
  - ".claude/skills/**"
  - ".github/agents/**"
  - ".github/hooks/**"
---

# MCP surface and sync rules

- Tool registry, tool docs, hook policy, and generated docs must stay synchronized.
- If MCP tool names or categories change, update both runtime registration and sync artifacts in the same change.
- If search/export behavior changes, align AGENTS.md, relevant skills, Copilot agent instructions, Cline rules, and generated docs in the same change.
- Keep wiki-note export defaults, Foam-compatible aliases, MedPaper-style output, CSL JSON, and user-template docs described consistently.
- Validate the smallest affected sync tests before widening to full repo validation.
