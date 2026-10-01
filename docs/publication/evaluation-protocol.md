# Proposed controlled evaluation

Status: design for a future run, **not preregistered and not fully executed**.
Existing pilot results are linked in the [evidence map](evidence.md). A previous
5,000-query setup is not permission to start a costly run; this revision performs
local preparation and verification only.

## Question and arms

What does the integration package add when the host can already use native search
and direct PubMed access?

| Arm | Capability | Comparison |
| --- | --- | --- |
| A — native | Same host/model, native search, direct PubMed search/read/reference primitives | Baseline capability |
| B — original package | A plus original MCP and its bundled instructions, pinned to an immutable pre-improvement revision | B − A: original package utility |
| C — current package | A plus current MCP and its matching instructions, pinned to an immutable revision | C − B: maintenance benefit; C − A: current package utility |

Match task text, model version, reasoning settings, host version, runtime and
credentials. Preserve native search in every arm. Pin original package B from a
known release or commit and record its exact environment; do not silently make B
use C's updated instructions. Add server-only versus server-plus-instructions
ablations if attribution to the server rather than the full package is required.

## Two separate tracks

1. **Fixed corpus, multi-turn retrieval.** Snapshot documents, identifiers,
   references, available passages and provider-shaped responses. Record licenses,
   snapshot date and hashes. Instrument all arms against the same snapshot.
   Freeze retrieval index and relevance judgments; the agent may not read qrels.
   Restrict outside retrieval equally. Replacing the native backend with a fixture
   is an adapted evaluation, not native web search performance.
2. **Budgeted live integration.** Keep real native search and provider access.
   Interleave arm order, record timestamps and provider states. Coverage and
   ranking drift are part of this deployment-level result. Report separately
   from the fixed-corpus estimate.

NFCorpus is useful for lexical retrieval, PaperSearchQA for search/QA, and
ScholarGym for query planning, invocation and relevance assessment. LitSearch
tests scientific retrieval outside this project's main biomedical domain.
Do not merge these different units into an unexplained “research score,” or call
an adapter's result an official leaderboard score.

## Endpoints and article-selection stage

Choose the primary endpoint and dataset split before the run. For ranked
retrieval, report nDCG@10 with the exact gain convention, judged recall@100, and
judgment coverage. For QA, report answer exact match and gold-source hit with
normalization rules. For systematic screening, specify a recall target and
work-saved measure appropriate to the review; top-10 precision is insufficient.

Then evaluate selection policies against the same candidate pool: source ranking,
relevance reranking, and a diversity/coverage policy. Fix candidates first so that
discovery and selection gains are separable. Report omitted relevant records,
redundancy and exclusions, not just a higher average score. Tune only on a
development partition; reserve the test split until choices are frozen.

For citation context, sample actual claim/passage pairs with article and section
identifiers. Independent reviewers label support, contradiction, insufficient
context, or inaccessible evidence; resolve disagreements and report agreement.
Abstract-only decisions remain distinct from full-text-supported decisions.
PMID/DOI matching or exporting a bibliography does not satisfy this endpoint.

## Comparable budgets and statistics

Count primitives below the MCP wrapper: searches, article reads, reference calls,
retries, cache hits, provider requests, documents and bytes returned. Record model
input/output tokens, wall time and timeouts. One bundled call is not equivalent
to one native call. Limit both total useful information and operational resources
with documented stopping rules; preserve failed attempts in denominators.

Use isolated sessions and equal cache warm/cold policy. Pair questions across
arms, randomize order and use prespecified repetitions for stochastic hosts.
Choose sample size from a pilot and a smallest worthwhile effect, not from the
number of affordable examples alone. Report paired differences, intervals,
regressions and missingness. Correct or disclose multiple exploratory comparisons.
Keep trajectories and resource accounting alongside scores, with credentials and
licensed text handled according to their storage constraints.

## Provider protection and execution stop conditions

Use offline fixtures for broad sweeps. Any live phase receives a separate total
request and cost budget, provider/account-specific admission, bounded concurrency,
retry caps and shared cooldown handling. Start conservatively; do not raise
concurrency to recover benchmark throughput during 429/503 responses. Stop or
pause on sustained throttling, exhausted quota, authentication failure, or provider
instructions. Multiple processes sharing credentials require aggregate controls;
per-process limits alone do not enforce an account-wide quota.

## Required run artifacts

- Exact source revisions, environments, model/host settings and dataset hashes.
- Arm instructions and tool schemas, including every adapter difference.
- Randomization seed, budget policy, stopping rules and preregistration status.
- Per-task trajectories, outcomes, failures, primitive/resource counts and
  paired analysis code.
- A signed-off interpretation that separates component, harness and live-provider
  effects and identifies all deviations from the plan.

The present manuscript reports existing measurements and this proposed design.
It does not fill unexecuted experimental cells with estimates.
