# Research Artifact Envelope Design

## Goal

MCP tools should return a compact, useful response while persisting complete research artifacts that agents can read repeatedly through `read_session` without spending response tokens.

## Principles

- The MCP response is an index card: enough summary for an agent to answer immediately, plus artifact locators and retrieval hints.
- Artifact files are the durable data channel: full result sets, query strategy, audit checks, and human-readable responses live in files.
- Local file paths are optional debug metadata. Remote servers and sandboxed clients must be able to retrieve artifacts through `artifact_uri`, `artifact_file`, `offset`, and `max_chars`.
- Academic completeness is checked from available run evidence by default. Live re-query checks are a future opt-in mode, not the default.

## Artifact Envelope

Each research artifact uses schema version `research-artifact/v1` and includes:

- `results.<format>`: complete structured payload for the tool result.
- `query_strategy.json`: original query, normalized/executed query, filters, requested and dispatched sources, ranking, deep-search strategies, ICD expansion, and relaxation history.
- `audit.json`: local/source-count completeness checks with pass/warn/fail status and actionable findings.
- `response.md` when markdown was generated.
- `query.md` for a quick human-readable query note.

The manifest summary exposes only compact fields: query, returned count, source counts, audit status, warnings, available files, and recommended read order.

## Audit Scope

Default audit mode is `source-counts`:

- Verify result count equals the persisted article list length.
- Verify source returned counts and known totals are present when available.
- Flag source errors and zero-response sources.
- Check PMID list uniqueness and missing identifier/metadata rates.
- Check aggregation sanity such as unique count versus duplicate count.
- Compare deep-search strategy counts to executed strategy records.

The audit does not re-run upstream APIs by default, so it avoids quota cost and false alarms from changing databases.

## Retrieval Contract

Agents should use:

```text
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="audit.json")
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="results.json", offset=0, max_chars=200000)
```

`list_artifacts` returns a compact locator with files and read hints. `artifact` reads return pagination metadata and redact local paths unless explicitly allowed by settings.

## Response Contract

`unified_search` structured responses include:

- `statistics`, `source_counts`, and source warnings.
- `artifact` locator with file list, audit status, and read hints.
- `artifact_summary` explaining which file to read next.
- If response size is capped, the truncated response still preserves source counts, source warnings, and artifact retrieval metadata when space allows.

Markdown responses append a compact persistent artifact section with the same retrieval hints.
