---
paths:
  - "src/domain/citation.py"
  - "src/domain/value_objects.py"
  - "src/presentation/tools/document_tools.py"
  - "src/presentation/tools/table_tools.py"
  - "tests/unit/test_citation_index.py"
---

# Citation-Ready Design Rules (CRAAP Scaffold)

This repo aims for **citation-ready assets** where a reference can be traced back to a precise span (line/sentence/block) and re-verified after edits.

## Evidence Span Invariants
- Prefer stable identifiers and locators: `doc_id`, `span_id`, `source_revision_id`, `locator_version`.
- When possible, include multiple locators (line/char/byte offsets) plus `text_sha256` and short surrounding context.
- Avoid false precision: keep CRAAP scores empty unless a real scoring method exists; default to conservative `unassessed`/`needs_review`.

## Backward-Compatible Tool Outputs
- When changing structured tool payloads, keep alias keys accepted (don’t break old clients).
- If removing fields, provide a migration path or tolerate legacy inputs for a full release cycle.
