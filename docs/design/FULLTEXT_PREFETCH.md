# Bounded background fulltext — assessment and implementation

Date: 2026-10-01. Status: implemented after v0.7.5; see the Unreleased changelog.

## Decision

Reuse structured XML for ordinary fulltext reads, and offer an explicit
`unified_search(..., fulltext="prefetch")` for users likely to read the highest
ranked articles. Default `fulltext="off"` adds no speculative requests. Keep the
41-tool surface: the subsequent `get_fulltext` both waits for shared work if
needed and applies the requested section/figure/output controls.

This improves readiness, not retrieval coverage. It does not eliminate the
agent's later read call or inject entire papers into a search response. An
extra read selects the desired evidence; it need not trigger another download.
There is no status-polling loop or promise that an agent automatically consumes
the background output.

## Alternatives and cost

| Approach | Benefit | Cost / limitation | Decision |
| --- | --- | --- | --- |
| Existing foreground-only retrieval | No speculative network traffic | Repeated XML reads download again; reading waits on I/O | Preserve as the default with shared XML caching |
| Fetch all fulltexts before returning search | Text available in one response | Blocks search, multiplies calls and response tokens; downloads many unread papers | Reject |
| Unconditional background PDF/source fan-out | Can hide some later waiting | Wasted bandwidth, parsing CPU and rate quota; possible login/browser activity | Reject |
| Opt-in top-three XML prefetch | Overlaps a small predictable fetch with article selection | Up to three speculative XML requests, including unread papers | Implement |
| Durable background job/task API | Resume jobs and inspect status independently | New persistence, permission and client task-capability contracts; polling can add agent calls | Defer until durable batch retrieval is requested |

With `m` newly downloaded candidates and `u` of those eventually read before expiry,
the successful no-retry case adds `m-u` XML calls compared with demand caching.
For one article with fetch time `F` and useful overlap `T`, later I/O waiting
falls from `F` to approximately `max(0, F-T)`. Serial queueing, provider limits,
failures, parsing and other required sources reduce that benefit. These are
cost relationships, not measured WAN or model performance.

Use prefetch for targeted fulltext synthesis, evidence-section reading and
small follow-up investigations. Leave it off for broad screening, uncertain
queries, repeated exploratory searches, metered connections and abstract-only
work. A PMCID is an eligibility hint; it does not prove API access. Europe PMC
only serves its open-access subset through
[`fullTextXML`](https://europepmc.org/RestfulWebService).

## Implemented bounds and ownership

- Consider only the top three ranked results; skip missing/malformed PMCIDs,
  explicitly closed-access records and duplicate PMCIDs. Do not scan deeper,
  resolve extra IDs or change ranking to fill the quota.
- At most three background jobs per server, with one background XML operation
  at a time. A 15-second deadline includes queue time. The speculative client
  has a 10-second transport timeout, one attempt and a 2 MiB response cap.
- Share the ordinary Europe PMC rate, concurrency and Retry-After cooldown
  keys. Existing provider quotas are not raised. A running background operation
  cannot be preempted safely; some contention remains possible.
- Cache at most 32 XML entries and 16 MiB of UTF-8 content per server, with a
  2 MiB per-entry cap. Python object and parsing overhead are additional. XML
  success TTL is 15 minutes; absent/failed speculation suppresses new automatic
  work for 60 seconds. Explicit demand may retry failed speculation immediately
  through normal transport policy, which still observes provider cooldowns.
- Cache and in-flight keys include the stable tenant. Separate server instances
  do not share content. Anonymous/stateless and unverified transport identities
  do not own background work or cross-request XML caches.
- Foreground reads coalesce, preserve complete XML, and apply section filters
  independently. Cancelling one reader does not cancel another; abandoned
  demand work is cancelled. A demand XML operation has a 45-second deadline.
- The runtime bounds both orchestration and underlying I/O at 16 pending tasks.
  Cancellation-resistant I/O remains owned and retains its background slot;
  expired/late work cannot publish a cache entry. Shutdown cancels work before
  closing source clients and discards cached XML.
- `PUBMED_FULLTEXT_PREFETCH_LIMIT=0` disables speculation; values 1–3 lower the
  candidate window. A disabled Europe PMC source also prevents prefetch.
- Pipeline calls reject `fulltext="prefetch"` before pipeline execution. Search
  dry-run mode does not schedule speculation. Pipeline budgets are not bypassed
  by hidden fulltext work.

The implementation uses an application-owned `FulltextCache` with injected I/O,
a restricted infrastructure client and thin MCP composition. It does not depend
on clients implementing the evolving [MCP Tasks extension](https://tasks.extensions.modelcontextprotocol.io/specification/draft/tasks).
Background work is process-local and best-effort, not a durable job queue.

## Agent interaction

```python
unified_search(query="remimazolam ICU sedation", fulltext="prefetch", output_format="json")
# Continue selecting evidence. Do not poll the prefetch snapshot.
get_fulltext(source={"kind":"pmcid","value":"PMC7096777"},
             sections="methods,results", include_pdf_links=False)
```

Structured search responses and saved result artifacts include
`enrichment.fulltext_prefetch`; Markdown contains a short readiness note even
with query analysis hidden. Its rows are a scheduling snapshot, not a later
completion notification. Use the row's PMCID source to avoid another PMID
metadata-resolution call. Missing candidates retain normal on-demand behavior.
The search journal and strategy artifact preserve the selected prefetch mode.

Only selected `get_fulltext` reads use the existing artifact persistence path.
Speculation stores no paper files, performs no institution/browser access,
fetches no figures and does not extract PDFs. A successful XML read with
`include_pdf_links=False` also skips the otherwise unnecessary Unpaywall lookup;
if XML is unavailable, normal explicit retrieval fallbacks still apply.

## Validation and measurement

Behavioral regressions cover selection and admission bounds, non-blocking
scheduling, in-flight sharing, retries after failed speculation, negative and
positive TTLs, byte/LRU eviction, section isolation, anonymous/tenant/server
boundaries, provider switches, one-attempt 429/503 handling, body limits,
cancellation-resistant sources and shutdown. The existing all-tool acceptance
scenario now enables prefetch and fails if the later fulltext tool downloads
the same XML again, over source stdio, HTTP and a fresh wheel.

The [offline comparison](../reports/fulltext_prefetch_2026-10-01.json) uses the
real cache/scheduler with 80 ms artificial XML latency and 100 ms article
selection time, five repeats per scenario. It checks identical returned text
and counts unused requests. Reproduce with:

```bash
uv run python scripts/perf/fulltext_prefetch.py --output build/fulltext-prefetch.json
```

The fixture excludes real network, search, XML parsing, agent/model behavior,
tokens, provider availability and institutional content. It supports the
bounded-overlap decision; it is not an end-to-end performance claim.

Observed median foreground XML waiting, with upstream calls in parentheses:

| Scenario | Uncached demand | Demand cache | Top-three prefetch |
| --- | --- | --- | --- |
| Read one article twice | 160.409 ms (2) | 80.346 ms (1) | 0.023 ms (3; 2 unused) |
| Read all three articles | 240.563 ms (3) | 241.016 ms (3) | 140.637 ms (3; 0 unused) |

The cache is useful even without speculation. Prefetch saves time only when
selection/other work overlaps retrieval; it adds waste when prepared articles
are not read. Production uptake should be evaluated from actual read rates and
provider budgets before considering any default-on policy.

Final local gate on 2026-10-01: **4,900 passed, 23 skipped, 30 deselected**
(125.13 seconds). Ruff, formatting, async-test consistency, ownership,
publication preflight, inventory and mypy all passed. Generated docs/skills and
documentation links passed; 18 new focused tests cover the cache and transport.
