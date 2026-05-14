---
name: pubmed-pico-search
description: "Agent-guided PICO clinical question search using parse_pico handoff and unified_search. Triggers: PICO, 臨床問題, A比B好嗎, treatment comparison, clinical question, 療效比較"
---

# PICO Clinical Question Search

Use this workflow for clinical comparison questions. The MCP server does not
semantically parse natural-language clinical questions. The agent extracts
P/I/C/O, submits the structured handoff through `parse_pico`, and then executes
the returned `template: pico` pipeline or an expanded Boolean query.

## PICO Elements

| Element | Meaning | Example |
| --- | --- | --- |
| `P` | Population / patient group | ICU patients requiring sedation |
| `I` | Intervention / exposure / index test | remimazolam |
| `C` | Comparator, optional | propofol |
| `O` | Outcome, recommended | delirium, hypotension, sedation efficacy |

## Workflow

```text
Agent extracts P/I/C/O
-> parse_pico(description, p, i, c, o)
-> optional generate_search_queries for P/I/C/O expansion
-> unified_search(query=original_question, pipeline=parse_pico.pipeline)
```

## Step 1: Agent Extracts PICO

Do the semantic work in the agent. Do not ask the MCP server to infer P/I/C/O
from free text. If P or I is unclear, ask the user before searching. Do not
invent missing clinical details.

## Step 2: Validate The Handoff

```python
pico = parse_pico(
    description="Is remimazolam better than propofol for ICU sedation?",
    p="ICU patients requiring sedation",
    i="remimazolam",
    c="propofol",
    o="delirium, hypotension, sedation efficacy",
    question_type="therapy",
    sources="pubmed,europe_pmc",
    limit=50,
)
```

Expected useful fields:

- `validation`: whether required P/I fields are present
- `pico`: human-readable P/I/C/O
- `query_elements`: search fragments that the backend will use
- `pipeline`: ready-to-run `template: pico` YAML
- `next_tool_call`: suggested `unified_search` call

When only `description` is provided, `parse_pico` returns a schema and asks the
agent to call it again with structured elements.

## Step 3: Optional MeSH / Synonym Expansion

Use this when the topic needs controlled vocabulary or systematic-review style
coverage.

```python
generate_search_queries(topic="ICU patients")
generate_search_queries(topic="remimazolam")
generate_search_queries(topic="propofol")
generate_search_queries(topic="delirium")
```

If you build high-quality fragments, pass them back as:

```python
parse_pico(
    description="Is remimazolam better than propofol for ICU sedation?",
    p="ICU patients requiring sedation",
    p_query='("Intensive Care Units"[MeSH] OR ICU[tiab])',
    i="remimazolam",
    i_query="(remimazolam[tiab] OR CNS7056[tiab])",
    c="propofol",
    c_query='("Propofol"[MeSH] OR propofol[tiab])',
    o="delirium",
    o_query='("Delirium"[MeSH] OR delirium[tiab])',
)
```

## Step 4: Execute Search

```python
unified_search(
    query="Is remimazolam better than propofol for ICU sedation?",
    pipeline=pico["pipeline"],
    ranking="quality",
)
```

The backend PICO pipeline searches O-aware precision and recall variants,
deduplicates results, merges ranked lists, and enriches the final set.

## Missing Fields

- Missing `C`: allowed. Do not invent a comparator.
- Missing `O`: allowed but discouraged. Ask the user when the outcome is central.
- Missing `P` or `I`: ask the user before running a structured PICO search.

## Recommended Reporting

Always show the final P/I/C/O table, the query or pipeline profile used, and the
main limits such as sources, years, species, and clinical query filter.
