<!-- Generated from README.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# PubMed Search MCP

<!-- mcp-name: io.github.u9401066/pubmed-search-mcp -->

[繁體中文](#/overview-zh) · [Documentation site](https://u9401066.github.io/pubmed-search-mcp/) · [Release history](https://github.com/u9401066/pubmed-search-mcp/blob/master/CHANGELOG.md)

An agent plugin for biomedical literature research. The host agent chooses a search strategy, follows citations and records what it read. The MCP server queries providers and keeps identifiers, search runs and evidence artifacts. A colleague using the same research workspace can pick up the outstanding reading.

The PubMed search code can be traced to November 25, 2025 in `med-paper-assistant`. GitHub records December 2, 2025 as the creation date of this repository. The first PyPI distribution followed on December 8. [Project history and primary records](#/publication#project-history)

![How an agent explores, expands, examines and explains a literature question](images/research-workflow.svg)

## Quick install

| Choose a version | Start here |
| --- | --- |
| Published v0.11.0 | Configure the client's stdio command as `uvx`, with `pubmed-search-mcp@0.11.0` as its argument. Set `NCBI_EMAIL` to your research contact. The release exposes **43 MCP Tools**, including a persistent research workspace. |
| Development checkout | Build the plugin from this checkout with the command below to test local changes. |

```sh
uv run --frozen python scripts/build_agent_plugin.py --dev-output build/pubmed-research-plugin
```

Select the generated directory in your agent's plugin installer. Keep the checkout available. The generated launcher uses this source tree. The version-pinned launcher in `plugins/pubmed-search/` uses the published package. [Client configurations and plugin installation](#/troubleshooting)

Four blinded review cases tested whether MeSH previews improve search decisions. [Methods, screening costs and results](#/mesh-preflight)

## What's new in v0.11.0

- **Systematic reviews**: saved pipelines retrieve the complete PubMed set (up to 10,000 records), keep PRISMA-S run records, export RIS/CSV/CSL-JSON, analyse concept-block contributions and log screening decisions (`pipeline_screening`).
- **Precision-first search**: your query fills the requested limit first; automatic broadening only fills a shortfall and every broadened record is labelled.
- **MeSH you can trust**: confirmed mappings require an exact preferred or entry term; a heading PubMed cannot resolve is corrected automatically in `unified_search` (with evidence) and suggested, never applied, in saved pipelines.
- **Reference checks that correct citations**: mis-cited years and volumes are reported as field corrections instead of looking fabricated.
- **Evidence-grounded Chronicles and clearer fulltext status**: study-design labels from PubMed publication types, quoted conclusion sentences, NCBI PMC fallback and typed source errors.

Details: [CHANGELOG](https://github.com/u9401066/pubmed-search-mcp/blob/master/CHANGELOG.md).

## Start with a research question

For example, ask the agent to trace the early development of cochlear implants and leave the next paper to read for a colleague. Choose a workflow before memorizing 43 tool names.

| Research task | What the agent can do |
| --- | --- |
| Define the scope | Expand MeSH and synonyms, validate agent-supplied PICO, or compare which papers a Boolean condition excludes. [PubMed combination example](#/tools-usage-guide#compare-pubmed-concept-blocks) |
| Search and extend | Search several providers, inspect per-source failures, then follow related papers, references or citing articles. [User guide](#/user-guide) |
| Read and verify | Inspect an abstract, an available full-text passage, figures or bibliography matches. Use `diagnose_institutional_access` for a configured resolver. Record the source and what was actually read. [Tool guide](#/tools-usage-guide) |
| Reuse a review strategy | Save a PICO or citation-expansion pipeline, retrieve the complete PubMed set, export PRISMA-S records and RIS/CSV, analyse each concept block's contribution and log screening decisions for PRISMA 2020 counts. Eligibility judgements and statistical pooling remain researcher tasks. [Pipeline tutorial](#/pipeline-tutorial) |
| Explore research history | Review dated Chronicle branches, landmarks, earlier alternatives and revision differences. [Historical case and workspace handoff](#/advanced-workflows) |
| Share results | Export citations or notes, record source identifiers and leave an open action. The host can cross-check an authorized local Zotero library. [Capability inventory and evidence](#/documentation-map#capability-inventory) |

For each of the 16 registry categories, see the implementation evidence and remaining limits in the [inventory](#/documentation-map#capability-inventory). The [tool-by-tool audit](#/tool-quality-audit) and [generated index](#/quick-reference) give individual contracts.

## Search limits and recovery

Generic literature discovery uses exactly one MCP entry point, `unified_search`. Deep search is precision-first: your query gets each source's full result budget, and lower-precision strategies only fill missing slots, disclosed in `broadening`. Inspect `search_status` and the run artifact before interpreting a small or empty result. OA identifiers, authorized institutional access and local copies determine which full-text passages can be read.

The `search-run/v1` journal also covers inline, `saved:<name>`, or `dry_run=true` pipeline execution. Use `read_session(request={"action":"replay_search","run_id":"..."})` to recover the original credential-free arguments. There is no public cursor-resume parameter yet. Submitting the recovered request starts a new search. A reply with `search_run.status="history_unavailable"` has no guaranteed durable replay. [Recovery and artifact formats](#/tools-usage-guide)

## Configuration

| Runtime | State and access |
| --- | --- |
| stdio or loopback HTTP | Trusted single-user deployment with a durable `default` tenant. The HTTP entry point is `pubmed-search-mcp-http --mode local --host 127.0.0.1`. |
| Authenticated service | `--mode service` fails closed without a bearer principal. Authenticated callers cannot load `file:` pipelines or choose a server-host note path. The service Compose scheduler is disabled. [Deployment](#/deployment) |
| Copilot Studio | Set `PUBMED_AUTH_TOKENS` and an assigned `NGROK_DOMAIN` before using `scripts/start-copilot-studio.sh --with-ngrok`. The local smoke launcher exercises the same canonical 43-tool strict registry. [Copilot integration](https://github.com/u9401066/pubmed-search-mcp/blob/master/copilot-studio/README.md) |

Modern 2026-07-28 clients use MCP SDK v2 requests. Python applications can call `pubmed_search.api` directly. The optional `pubmed-browser-fetch-broker` runs on a machine with an authorized browser session. [Integration guide](#/troubleshooting) · [Python facade](#/python-sdk-http-cli-design)

## Skills and development

**Usage Skills (12)** are shipped with the release plugin. **Development Skills (15)** stay in the repository for contributors. [Plugin skills](https://github.com/u9401066/pubmed-search-mcp/tree/master/plugins/pubmed-search/skills) · [Architecture](#/architecture) · [Testing](#/testing) · [Contributing](https://github.com/u9401066/pubmed-search-mcp/blob/master/CONTRIBUTING.md)

## Citation and license

We welcome patches, reproducible search cases, historically sourced Chronicle corrections and documentation updates. Include the version or commit you used and the observation you want someone else to reproduce. [Contribution guide](https://github.com/u9401066/pubmed-search-mcp/blob/master/CONTRIBUTING.md) · [Issues](https://github.com/u9401066/pubmed-search-mcp/issues)

The software is distributed under Apache License 2.0. When redistributing it, include the license, retain applicable notices and mark files you change. Articles, figures and datasets retrieved through the tools remain subject to their source terms. [License text](https://github.com/u9401066/pubmed-search-mcp/blob/master/LICENSE)

Cite the software version used, and the commit for a branch experiment. Cite original papers for research claims. The manuscript is a working draft. [Software citation](https://github.com/u9401066/pubmed-search-mcp/blob/master/CITATION.cff) · [Manuscript and evaluation](#/publication) · [Apache License 2.0](https://github.com/u9401066/pubmed-search-mcp/blob/master/LICENSE)
