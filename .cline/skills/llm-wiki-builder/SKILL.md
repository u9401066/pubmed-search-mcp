---
name: llm-wiki-builder
description: "Build or refresh Foam-compatible LLM wikis from Zotero, PubMed, documents, and local Markdown notes using a multi-tool workflow."
---

# LLM Wiki Builder

Use this skill when the user asks to create, refresh, repair, or extend a Foam
wiki or LLM-readable literature wiki.

## Read First

- `.clinerules/35-foam-llm-wiki.md`
- `.clinerules/workflows/llm-wiki-build.md`
- `.github/zotero-research-workflow.md` when Zotero or PubMed evidence is involved

## Multi-Tool Choreography

1. Inspect the filesystem for the wiki root, Foam markers, existing note style,
   and link conventions.
2. Use Zotero tools to inspect saved library items, collections, and duplicate
   state before importing or refetching.
3. Use PubMed Search MCP tools for discovery, article details, related/citing
   articles, references, exports, and full-text follow-up.
4. Use asset-aware or document tools when PDFs, DOCX, DFM, tables, figures, or
   span-level citations are part of the request.
5. Write or update Markdown notes with Foam-compatible wikilinks and preserved
   source identifiers.
6. Validate generated links and report unresolved wiki TODOs separately from
   completed notes.

## Output Contract

- Keep the note graph readable in Foam and useful for LLM retrieval.
- Preserve source provenance close to claims.
- Ask before bulk rewrites, destructive cleanup, or Zotero imports.
- Do not leave broken wikilinks hidden in generated files.
