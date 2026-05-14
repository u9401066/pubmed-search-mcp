---
paths:
  - ".clinerules/workflows/llm-wiki-build.md"
  - ".cline/skills/llm-wiki-builder/SKILL.md"
  - ".codex/skills/llm-wiki-builder/SKILL.md"
  - ".github/zotero-research-workflow.md"
---

# Foam LLM Wiki Rules

Use these rules when turning Zotero, PubMed, PDF/full-text, or project evidence
into a Foam-compatible Markdown wiki for LLM-assisted reading and synthesis.

## Asset Boundaries

- Treat Foam wiki files as user-authored knowledge assets, not generated trash.
- Detect the wiki root before writing. Prefer an existing Foam workspace layout
  such as `.foam/`, `.vscode/settings.json`, or an existing note graph.
- Ask before bulk rewrites, renames, deletions, or moving an existing wiki root.
- Keep raw exports, RIS, JSON, and tool responses out of final notes unless the
  user explicitly asks for an appendix.

## Foam Rendering Invariants

- Create ordinary Markdown files that render without custom HTML.
- Use one `# H1` title per note, matching the human-readable note title.
- Use stable lowercase kebab-case filenames for new generated notes.
- Put display titles and source identifiers in YAML frontmatter when useful.
- Use Foam wikilinks only for real note targets:
  - `[[note-slug]]` when the target note exists or is created in the same workflow.
  - `[[note-slug|Readable label]]` when the filename is less readable than the title.
- Use relative Markdown links for attachments, figures, PDFs, or exported files.
- Do not leave unresolved wikilinks unless they are intentionally marked as TODO.

## Evidence And Citation Hygiene

- Preserve PMID, DOI, PMCID, Zotero key, URL, title, journal, year, and access
  status whenever available.
- Distinguish imported Zotero items, candidate PubMed results, and preprints.
- Cite claims at paragraph or bullet level using compact source markers such as
  `PMID:12345678`, `DOI:...`, or `Zotero:ABC123`.
- Prefer exact text spans, section names, page numbers, or quote hashes when a
  full-text or asset-aware tool provides them.
- Do not claim that a note is citation-ready unless its source markers can be
  traced back to a concrete article, item, or document span.

## Workflow And Skill Split

- Rules define durable wiki constraints and rendering invariants.
- Workflows define the complete user-facing sequence for making or refreshing
  an LLM wiki.
- Skills orchestrate multiple tools: filesystem search, Zotero inspection,
  PubMed discovery, full-text/asset extraction when available, Markdown writes,
  and link validation.
