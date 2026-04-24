---
paths:
  - "src/pubmed_search/presentation/mcp_server/**"
  - "scripts/count_mcp_tools.py"
  - "scripts/build_docs_site.py"
  - ".github/hooks/**"
---

# MCP surface and sync rules

- Tool registry, tool docs, hook policy, and generated docs must stay synchronized.
- If MCP tool names or categories change, update both runtime registration and sync artifacts in the same change.
- Validate the smallest affected sync tests before widening to full repo validation.