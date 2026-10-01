# Agent input contract — v0.7.5 patch

Status: all five phases completed and locally verified on 2026-10-01. This is the 0.7.5 patch;
the public tool names and existing successful response bodies stay compatible.

## Delivery phases and acceptance criteria

1. **Shared field contracts.** Reuse PMID, PMCID, DOI and NCBI identifier
   annotations across discovery, article sources, sessions, citations and
   institutional access. Validate complete batches before any provider or
   filesystem work. Preserve order; deduplicate only after every item validates.
2. **Schema and runtime agreement.** Derive accepted transport representations
   from the argument schema. Publish native containers and bounded JSON-encoded
   containers, and integer/string alternatives. Keep canonical bounds and
   semantic identifier formats visible. Verify accepted requests against the
   published JSON Schema, including all 41 tools over MCP.
3. **Repairable errors.** Return `isError` plus structured `invalid_input`
   details, JSON Pointer paths, safe expected constraints, and recovery guidance.
   Only argument-validation failures may claim `executed: false`. Never echo
   rejected values, arbitrary object keys, exception contexts or credentials.
4. **Explicit format expansion.** Accept decimal integer strings in integer
   fields, official PMID/PMCID/DOI URLs in the corresponding identifier fields,
   flat Markdown PMID lists, JSON code fences and inline identifier backticks.
   Automatically correct explicit true/false text, unique enum/discriminator
   case/whitespace variants, and finite decimal number strings. Preserve free
   text, opaque local IDs, filenames and timestamps. No guessed aliases, truncation,
   arbitrary-host fetching, Unicode digit conversion or partial batch execution.
5. **Verification and release alignment.** Exercise one corrected retry,
   no-execution-on-error, deep paths, concurrent request isolation, all-tool
   schema checks, real stdio/HTTP and installed-wheel acceptance. Regenerate
   tool/skill/site references and run the full repository gate.

## Accepted representations

| Field | Accepted | Rejected deliberately |
| --- | --- | --- |
| PMID | String digits, `PMID:`/`pubmed:` prefix, official PubMed article URL | JSON numbers, zero/leading zero, prose, tracking query/fragment, foreign host |
| PMCID | String digits or `PMC`/`PMCID:` prefix, official PMC article URL | Wrong identifier kind, query/fragment, credentials/port |
| DOI | Canonical DOI, `doi:` prefix, doi.org/dx.doi.org URL | Foreign host, credentials/port, query/fragment |
| PMID batch | Native string array, JSON array string, delimited text, one PMID per Markdown bullet/numbered line | Nested/mixed-type/empty arrays, mixed `last`, malformed items, partial success |
| Number | Finite decimal number or bounded decimal string | NaN/Infinity, exponent strings, boolean, out-of-range value |
| Integer | JSON integer or bounded ASCII decimal string with optional minus sign and ASCII outer whitespace | Boolean, float, exponent, plus sign, Unicode digits, out-of-range value |
| Object/array | Native JSON or one layer of JSON-encoded container at each declared container field, optionally fenced | Duplicate keys, NaN/Infinity, excessive size/depth, unknown fields |
| Boolean/enum | Native values, true/false text, unique ASCII case/whitespace match | yes/no, 1/0, guessed synonyms or ambiguous choices |
| Free text | Original string | No JSON decoding or generic cleanup |

Use native JSON whenever possible. JSON Schema describes transport shape;
`contentSchema` and named identifier formats describe semantic validation that
many generic JSON Schema clients do not enforce. The server remains authoritative.

## Architecture and compatibility

- Domain value objects own identifier meaning and official URL parsing.
- Shared presentation field annotations own Pydantic validation, representation
  parsing and published format descriptions. No application business logic is
  moved into wrappers.
- One server boundary compiles transport schemas and renders validation errors.
  Errors raised after execution starts retain the existing execution-error
  policy and never claim the operation was not executed.
- Optional response metadata records normalization paths/rules without input
  values. Existing Markdown/JSON/TOON response bodies are preserved.
- No new tools, retired aliases, silent extra-field removal, automatic retry,
  new provider, or publishing operation is part of this patch.

## References

- [MCP tools: input schemas and tool execution errors](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- [Pydantic validators and JSON Schema input types](https://docs.pydantic.dev/latest/concepts/validators/#json-schema-and-field-validators)

## Verification record

- Shared identifier annotations now cover discovery, citation trees, article
  sources, session article reads, institutional access, NCBI IDs and all five
  PMID batch tools. No public tool was added or removed (41 tools, 16 categories).
- All-tool acceptance validates every accepted input against its published
  Draft 2020-12 schema, performs 41 rejected calls and one repaired retry per
  tool, and verifies 60 successful semantic calls per transport run.
- Source stdio covers both native and automatically corrected representations;
  Streamable HTTP and a freshly installed wheel exercise the same tool surface.
  Provider fixtures prohibit unexpected external network access.
- Focused regressions cover the original nine-PMID payload, shared-field parity,
  mixed automatic corrections in one call, multiple errors in one response,
  nested/array paths, unknown-key/value redaction, no filesystem work on invalid
  input, explicit false on a write flag, bounded errors and concurrent isolation.
- Ruff, mypy and skill/document synchronization checks passed during implementation.
- Initial implementation gate: `uv run --frozen python scripts/check_repo.py full` — **passed**
  on 2026-10-01. Ruff, formatting, async-test checks, repository ownership,
  publication preflight, symbol inventory and mypy passed; pytest reported
  **4,876 passed, 23 skipped, 30 deselected** (121.72 seconds).
- Additional checks: tool registry/docs generation, website generation, Cline/
  Codex skill validation and `git diff --check` passed. Version metadata and
  changelog remain 0.7.5. This records local implementation and validation;
  initial validation preceded release authorization. The user authorized review,
  segmented commits, push and publication on 2026-10-01.



## Follow-up release review (2026-10-01)

- Retain `invalid_json`, `duplicate_key` and `input_too_large` when Pydantic wraps
  a PMID batch parser failure. Only the known static transport exception may
  supply its code/message; arbitrary third-party validation contexts stay private.
- Normalize decimal strings through integer/number unions consistently with the
  published alternatives. A free-text union branch prevents enum rewriting;
  bounded text unions do not advertise a spelling repair the runtime rejects.
- Add these regressions to ordinary CI smoke, not only the local full suite.
- Release status and artifact evidence are recorded in the dated release report
  and memory bank, without changing historical v0.7.4 review provenance.

Release-review full gate: **4,882 passed, 23 skipped, 30 deselected** (134.54 s);
all lint/type/layout/publication checks passed. Publication is pending remote CI.
