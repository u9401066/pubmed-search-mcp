---
paths:
  - ".github/zotero-research-workflow.md"
  - "mcp-server/src/zotero_mcp/infrastructure/mcp/pubmed_tools.py"
  - "mcp-server/src/zotero_mcp/infrastructure/mcp/unified_import_tools.py"
  - "mcp-server/tests/unit/mcp/test_pubmed_tools.py"
  - "mcp-server/tests/unit/mcp/test_unified_import_tools.py"
---

# Zotero Research Workflow Rules

## Import Invariants

- Ask for the target Zotero collection before importing search results.
- Check for existing articles before creating new Zotero items.
- Prefer the unified `import_articles` bridge for PubMed JSON, PMID lists, or RIS text.
- Keep RIS and PubMed JSON parsing tolerant, but report skipped records clearly.

## Search-To-Library Flow

Use this shape unless the user asks for a different workflow:

1. Search or retrieve PubMed results.
2. Summarize the candidate articles and ask whether to import.
3. List or confirm the Zotero collection.
4. Check duplicates.
5. Import only the confirmed set.
6. Report created, skipped, duplicate, and failed records.

## Evidence Hygiene

- Keep PMID, DOI, title, journal, year, and URL metadata when available.
- Avoid claiming full-text access unless a PubMed/Europe PMC/CORE/OpenURL tool actually returned it.
- Prefer Zotero item reads for articles already in the library instead of re-fetching details from PubMed.
