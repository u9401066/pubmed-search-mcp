---
name: llm-wiki-builder
description: "Codex workflow skill for building Foam-compatible LLM wikis from Zotero, PubMed, documents, and local Markdown notes."
---

# LLM Wiki Builder

Use this skill when working on Foam, LLM wiki, literature wiki, citation-ready
notes, or Markdown knowledge graph tasks in this repository or an installed
workspace.

## Read First

- `.clinerules/35-foam-llm-wiki.md`
- `.clinerules/workflows/llm-wiki-build.md`
- `.github/zotero-research-workflow.md` when Zotero or PubMed evidence is involved

## Workflow

1. Find the wiki root and existing Foam conventions.
2. Build a note map before editing files.
3. Gather evidence through the appropriate MCP tools:
   - Zotero Keeper for saved library state and imports.
   - PubMed Search MCP for search, details, related/citing/reference traversal,
     export, timeline, and full-text follow-up.
   - Asset-aware/document tools for PDFs, DOCX, DFM, tables, figures, and
     span-level evidence when available.
4. Write Markdown notes with stable filenames, one H1, clean sections, and
   Foam-compatible wikilinks.
5. Validate links, attachments, and source markers before reporting completion.

## Guardrails

- Ask before bulk rewrites, destructive cleanup, or Zotero imports.
- Keep source identifiers near claims.
- Do not leave unresolved wikilinks unless they are marked as intentional TODOs.
- Keep generated notes human-readable and chunkable for LLM retrieval.
