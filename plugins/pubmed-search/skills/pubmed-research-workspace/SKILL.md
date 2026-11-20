---
name: pubmed-research-workspace
description: Manage a literature investigation across sessions or hand it to another reader. Use when the user wants to track search decisions, follow up leads, distinguish abstracts from passages, or resume unfinished research.
---

# Research workspace

Use `research_workspace` to keep a question, the decisions taken on it, and outstanding work on the connected server. The host agent selects and calls the research tools. A single literature lookup can go straight to `unified_search`.

Check that the connected server advertises `research_workspace` before promising a durable handoff. When trying the feature branch, use the plugin built with `scripts/build_agent_plugin.py --dev-output` from that checkout. A host connected to an older server can still use its search tools and report the handoff in the conversation.

## Pick up the question

For a new investigation, choose a stable ID and call `research_workspace(request={"action":"create","workspace_id":"implant-history","question":"When did researchers compare the two device designs?"})`. To continue, use `action="read"` with the same ID on the same data store and tenant. Use `action="list"` when the ID is unknown. The read returns the latest records and outstanding `open_actions`. Start history at `after=0` and follow `next_after` for earlier context. Follow `next_open_offset` with `open_offset` to see more open actions.

## Choose the activity the question needs

| Activity | What to do and retain |
| --- | --- |
| Explore | Search with `unified_search`. Record the question, exact query or saved pipeline name, scope and filters, and stable IDs of promising results. Keep a provider failure distinct from an empty result. |
| Expand | Follow an explicit lead with a citation lookup, a query variant or a Chronicle revision. Link the parent record and record why the new result belongs. A newly recognized link between older papers keeps the papers' original dates. |
| Examine | Inspect what was retrieved. Use `metadata`, `abstract` or `fulltext` for the material actually read. Full text needs a retrievable source reference and a passage locator such as a section, page or table. Keep an inaccessible methods section as a next action. Where authorized and available, a host can search a local Zotero library, match by PMID or DOI and retain its item key alongside the public ID. |
| Explain | Connect the supported interpretation and competing readings to their records with `parent_ids`. Cite the original papers and their locators. Keep outstanding questions visible in the handoff. Exported notes and workspace records retain their unverified status. |

Return to any activity as the evidence changes. A missing comparator can lead from Examine back to Expand.

During Expand, use `analyze_search_query` with the fixed PubMed scope in `query` and adjustable concepts in `comparison.blocks` when the connected server offers this parameter. Read a reported difference's sample PMIDs from `drop-<block>.json` through `read_session`. Keep the returned artifact URI in `source_refs` alongside the selected pipeline and record why you kept or relaxed the condition.

## Save a recoverable decision

```json
{
  "request": {
    "action": "record",
    "workspace_id": "implant-history",
    "record_id": "device-comparison",
    "activity": "explore",
    "note": "The abstract describes a comparison of implant devices. The eligibility criteria still need checking.",
    "source_refs": ["pmid:3878092"],
    "evidence_scope": "abstract",
    "next_action": "Find where the methods describe how devices were selected.",
    "actor": "agent"
  }
}
```

Use a stable `record_id` for each decision. After an ambiguous write, retry the same ID and payload. An ID conflict calls for reading the prior record. Append a new ID to document a correction. Use `parent_ids` for earlier records that informed this one and `resolves` only for earlier next actions this decision actually completes. Record distinct evidence scopes separately. Use `actor="human"` for an explicitly attributed human contribution.

For handoff, give the workspace ID, question, relevant record IDs, source locators and first open action. A colleague on the same principal and store can resume with `read` even after the original chat ends. Where a host lacks Zotero or full-text access, that gap travels with the question.

When reopening a source, inspect the record's or open action's `source_handoffs`. An entry supplies `source_ref`, `tool` and `arguments` for an explicit next call. Follow a returned handoff only when that source is needed. Resolve library-specific references through the authorized host integration.

If the user requests a handoff to read outside the agent, save the JSON from `action="read"` to a UTF-8 file. From this skill directory run `python scripts/render_handoff.py workspace.json` (or pass JSON on stdin). The bundled [handoff renderer](scripts/render_handoff.py) writes plain text to stdout and identifies omitted pages. It works offline using the Python standard library. Where the host cannot execute local scripts, summarize the same read response and its page limits directly.
