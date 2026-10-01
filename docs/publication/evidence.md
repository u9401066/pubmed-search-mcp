# Claim-to-evidence map

Reviewed September 21, 2026. This map separates measured observations from
implementation descriptions and proposed work. The [machine manifest](evidence.json)
pins the existing JSON records; the [builder](../../scripts/build_publication.py)
verifies those bytes before generating the manuscript tables.

| Manuscript claim | Evidence and scope | Limits |
| --- | --- | --- |
| Historical lexical ranking changed on NFCorpus | [JSON](../reports/academic_retrieval_benchmark_2026-09-09.json); 3,633 documents, dev 324 / test 323 queries; per-query paired comparisons and 10,000 bootstrap resamples | A lexical component, no LLM or full MCP; linear-gain nDCG and available qrels; test recall interval crosses zero |
| Dependency-ready execution reduced avoidable waiting in the staggered fixture | [Execution report](../reports/search_execution_2026-09-18.md), [before](../reports/search_execution_2026-09-18_before.json), [after](../reports/search_execution_2026-09-18_after.json); five scenarios, 20 repetitions, identical work signatures | Fixed-delay providers; no WAN, LLM, real cooldown or process startup; serial MCP case regressed; session growth prevents treating the timing gap as pure protocol cost |
| A paired agent runner can execute native/package conditions | [JSON](../reports/native_codex_product_benchmark_2026-09-09.json); three pairs, one repetition; native web search in both | No frozen corpus or enforced token/backend budgets; 2/3 answer EM and 1/3 source hit in both; no inferential precision from a three-pair zero difference |
| v0.7.4 passed documented release checks | [Release receipt](../reports/release_v074_2026-09-18.md), [JSON](../reports/release_v074_2026-09-18.json); local Python 3.10/3.13, actual stdio/HTTP/wheel tool checks | Test counts concern software contracts, not relevance; local/cloud skip counts differ because environment capabilities differ |
| 41 tools / 16 registry categories; host/service separation | [Registry](../../src/pubmed_search/presentation/mcp_server/tool_registry.py), [architecture](../../ARCHITECTURE.md), [tool guide](../guides/TOOLS_USAGE_GUIDE.md) | An implemented interface, not evidence that more tools improve research |
| Provider protection and ownership boundaries | [Source contracts](../architecture/SOURCE_CONTRACTS.md), [pipeline budgets](../../src/pubmed_search/application/pipeline/budgets.py), [installation contract](../../AGENTS.md) | Documented process/event-loop scope; no distributed quota guarantee; user-owned installed harness assets remain preserved |
| Full native/original/current package comparison | [Proposed protocol](evaluation-protocol.md) | Not executed or preregistered; the 5,000-query benchmark is not reported as complete |

## Revision identity

The lexical report's baseline commit starts `dbcf0c8`; its `production_files`
contains before/after hashes. The execution reports contain `executor_sha256`
and `script_sha256`, and the after-record pins the before-record. Their Git label
alone does not identify the measured uncommitted change. The pilot names its
historical package revision, source fingerprint, runner, model and CLI version.
These different histories must remain visible; none is silently renamed
“the v0.7.4 full-product benchmark.”

## Claims removed from the old draft

- “Novel” BM25+/RRF/MMR algorithms: replaced with attribution to original work.
- An established research-maturity score, clinical evidence grade or scientific
  disruption detector: not supported by the available validation.
- A causal end-to-end MCP gain: not established by the small pilot.
- Live API throughput or a guarantee against throttling: not tested by synthetic
  timing fixtures; aggregate deployment load still matters.
- Bibliography verification as proof of claim support: these are separate tasks.

The old sources are retained [as historical originals](../archive/publication/README.md).
Hash checking establishes input identity, not correctness of an experimental
design. Human scientific review remains necessary before submission.
