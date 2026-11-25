# Fulltext Registry Refactor Design

## Goal

Promote fulltext retrieval from an accumulated fallback chain into a metadata-driven service.

The immediate objective is not to add more sources. The objective is to make the existing fulltext path mature enough that new sources can be added without growing a second orchestration layer in the MCP tool.

## Current Status

The phase split was introduced on 2026-08-31. The 2026-09-15 audit found and
removed a remaining PDF fallback orchestrator in the MCP tool:

- `get_fulltext` keeps input normalization, progress/log bridging, and output formatting
- `application/fulltext/service.py` owns identifier-aware source orchestration
- `application/fulltext/registry.py` defines the policy/source metadata surface
- `fulltext_download.py` coordinates separate discovery, fetch, and extract phase objects
- historical infrastructure re-export modules and downloader pass-through methods are removed
- standard fallback and extended discovery now use the same application collector;
  one request does not run the downloader twice
- default policies include `pdf_retrieval_fallback`; custom policies can omit that
  source to disable it, including for direct application-service consumers
- acquired text survives downloader cleanup failures; download facts are formatted
  by the MCP layer, and shared artifact metadata serves both output branches

New behavior must be added through those authoritative application or phase modules; there is no parallel compatibility surface.

## Problem Statement

The remaining constraints and original design motivation are:

1. Application policy and infrastructure phases have explicit owners.
   - `application/fulltext/service.py` owns policy resolution and high-level orchestration.
   - `fulltext_discovery.py`, `fulltext_fetch.py`, and `fulltext_extract.py` own their respective phase behavior.

2. Structured fulltext is still over-coupled to Europe PMC.
   - Structured XML parsing is coordinated in the application service but still
     relies on the Europe PMC source; direct PMC structured retrieval remains a
     separate proposed enhancement.

3. `extended_sources` is a transport flag, not a retrieval policy.
   - The current boolean mixes user intent, discovery breadth, and fallback behavior into one switch.

4. `FulltextDownloader` composes discovery, fetch, and extract without duplicating their methods.

## Design Principles

1. Keep the public tool thin.
   - `get_fulltext` should only do input normalization, progress reporting, and output formatting.

2. Move orchestration into a service.
   - Source ordering, fallback rules, and identifier-aware policy selection belong in one fulltext service.

3. Make source metadata first-class.
   - Priority, capabilities, identifier requirements, and policy membership must live in a registry.

4. Separate retrieval phases.
   - Discovery: resolve candidate content locations.
   - Fetch: retrieve XML, PDF, or HTML payloads.
   - Extract: turn payloads into structured sections or plain text.

5. Keep one contract per capability.
   - Application contracts are imported from `application.fulltext`; phase behavior is called on its owning phase object. Removed historical paths are intentionally not aliased.

## Target Architecture

```text
get_fulltext MCP tool
  -> FulltextService
       -> FulltextRegistry
       -> Policy resolver
       -> Discovery layer
       -> Fetch layer
       -> Extract layer
```

### Tool Layer

`src/pubmed_search/presentation/mcp_server/tools/europe_pmc.py`

Responsibilities:

- normalize `identifier`, `pmid`, `pmcid`, `doi`
- emit progress updates
- format markdown / json / toon output
- attach figures and next-tool suggestions

Non-responsibilities:

- no direct three-source orchestration
- no policy resolution
- no source-specific fallback branching

### Service Layer

`src/pubmed_search/application/fulltext/service.py`

Responsibilities:

- resolve a retrieval policy from identifiers and requested discovery breadth
- execute structured-first or expanded discovery flows
- coordinate discovery, fetch, and extract phases
- return one normalized fulltext result object for the tool layer

### Registry Layer

`src/pubmed_search/application/fulltext/registry.py`

Responsibilities:

- define available fulltext sources and their metadata
- define retrieval policies
- filter sources by identifier availability and policy scope

### Downloader Layer

`src/pubmed_search/infrastructure/sources/fulltext_download.py`

Responsibilities:

- compose candidate discovery through `FulltextDiscoveryPhase`
- compose PDF / landing-page retrieval through `FulltextFetchPhase`
- compose PDF and structured text extraction through `FulltextExtractPhase`
- enforce end-to-end deadlines, candidate ordering, and client lifecycle

The downloader should become phase-oriented infrastructure, not the place where tool policy is decided.

## Fulltext Registry Model

Each source entry should be metadata-driven.

Suggested fields:

| Field | Purpose |
| --- | --- |
| `key` | Stable source identifier |
| `label` | User-facing source name |
| `priority` | Ordering within a policy |
| `identifier_support` | Which identifiers are sufficient: `pmcid`, `pmid`, `doi` |
| `capabilities` | Supported outputs: `structured`, `pdf`, `landing_page_resolution`, `fulltext_text` |
| `policy_groups` | Which policy scopes can use this source |
| `handler_key` | Which implementation handles the source |
| `enabled` | Optional future runtime gating |

Suggested initial source inventory:

| Key | Identifiers | Capabilities | Current implementation path |
| --- | --- | --- | --- |
| `registered_fulltext` | `pmid`, `pmcid`, `doi` | supplied text (not a provider) | tenant supplied-fulltext store |
| `europe_pmc` | `pmcid` | `structured`, `pdf` | direct Europe PMC client |
| `ncbi_pmc` | `pmcid` | `structured`, `official_host` | NCBI E-utilities `efetch db=pmc` |
| `pmc_html` | `pmcid` | `structured`, `official_host`, `single_article_only` | public PMC article page |
| `pmc` | `pmcid`, `pmid` | `pdf`, `landing_page_resolution` | downloader |
| `unpaywall` | `doi` | `pdf`, `landing_page_resolution` | direct or downloader |
| `core` | `doi` | `pdf`, `landing_page_resolution`, `fulltext_text` | direct or downloader |
| `pubmed_linkout` | `pmid` | `landing_page_resolution` | downloader |
| `openurl` | `pmid`, `doi` | `landing_page_resolution` | downloader |
| `doi_redirect` | `doi` | `landing_page_resolution` | downloader |
| `crossref` | `doi` | `landing_page_resolution` | downloader |
| `doaj` | `doi` | `pdf`, `landing_page_resolution` | downloader |
| `zenodo` | `doi` | `pdf`, `landing_page_resolution` | downloader |
| `semantic_scholar` | `doi` | `pdf`, `landing_page_resolution` | downloader |
| `openalex` | `doi` | `pdf`, `landing_page_resolution` | downloader |
| `arxiv` | `doi` | `pdf` | downloader |
| `biorxiv` | `doi` | `pdf` | downloader |
| `medrxiv` | `doi` | `pdf` | downloader |

Future high-value sources:

| Key | Why add it |
| --- | --- |
| `pmc_structured_direct` | direct PMC structured fallback, reducing Europe PMC coupling |
| `openaire` | high-value OA discovery source |
| `base` | broad institutional repository coverage |

## Policy Model

`extended_sources` should stop being the main control surface. The system should resolve a policy automatically.

Suggested policies:

### `structured_first`

Use when a PMCID is known.

Behavior:

- try structured fulltext first
- then standard discovery
- optionally upgrade discovery breadth when the request explicitly asks for it

### `standard_discovery`

Use for typical PMID-driven or mixed identifier flows.

Behavior:

- no structured-first branch unless PMCID becomes available
- use standard discovery sources only

### `expanded_discovery`

Use when DOI-only access is the primary path, or when the caller explicitly asks for broader fallback.

Behavior:

- widen discovery sources automatically
- still preserve source priority and extraction order

Suggested policy resolution rules:

1. If `pmcid` is present, use `structured_first`.
2. Else if only `doi` is present, use `expanded_discovery`.
3. Else use `standard_discovery`.
4. If `extended_sources=True` is requested, widen discovery scope explicitly.

## Phase Split

### 1. Discovery

Input:

- normalized identifiers
- resolved policy
- registry metadata

Output:

- ordered candidate sources
- normalized content links
- optional direct fulltext candidates

Examples:

- Europe PMC XML candidate
- Unpaywall OA locations
- CORE download URL
- OpenURL landing page

### 2. Fetch

Input:

- candidate sources from discovery

Output:

- raw XML, PDF bytes, HTML landing page content

Examples:

- fetch XML from Europe PMC
- fetch PDF from repository or publisher
- fetch HTML landing page and resolve a direct PDF

### 3. Extract

Input:

- raw XML, PDF, HTML-derived final resource

Output:

- section-filtered structured content
- extracted plain text
- provenance metadata

Examples:

- select `methods,results` from structured XML
- extract plain text from PDF
- mark extracted content as `derived` rather than `direct`

## Proposed Result Contract

The service should return one normalized result model with at least:

| Field | Purpose |
| --- | --- |
| `policy_key` | Which policy was used |
| `sources_tried` | Human-readable trace of the flow |
| `content` | Final rendered content |
| `content_sections` | Structured sections used to build the content |
| `pdf_links` | Deduplicated link inventory |
| `title` | Best available title |
| `fulltext_source` | Source that produced the final content |
| `canonical_host` | Canonical host for provenance |
| `provenance` | `direct`, `indirect`, `derived`, or `mixed` |

This lets the tool format once, regardless of how the content was found.

## File Plan

### Authoritative files

- `src/pubmed_search/application/fulltext/registry.py`
- `src/pubmed_search/application/fulltext/service.py`
- `src/pubmed_search/infrastructure/sources/fulltext_discovery.py`
- `src/pubmed_search/infrastructure/sources/fulltext_fetch.py`
- `src/pubmed_search/infrastructure/sources/fulltext_extract.py`

### Existing files to slim down

- `src/pubmed_search/presentation/mcp_server/tools/europe_pmc.py`
- `src/pubmed_search/infrastructure/sources/fulltext_download.py`

## Migration Plan

### Phase 1: Registry and policy

- add `FulltextRegistry`
- define source metadata and policy resolution
- keep current behavior unchanged where possible

### Phase 2: Service extraction

- move orchestration out of `get_fulltext`
- keep tool output formatting intact
- keep current public signature intact

### Phase 3: Downloader split (complete)

- call explicit discovery phase methods
- call explicit fetch phase methods
- call explicit extract phase methods
- stop letting the downloader decide policy
- remove duplicate downloader pass-through methods and historical re-export modules

### Phase 4: Direct PMC structured fallback (complete)

- source key `ncbi_pmc` (`infrastructure/sources/ncbi_pmc.py`): NCBI E-utilities
  `efetch db=pmc` with the configured `tool`/`email`/`api_key`, drawing from the
  same `ncbi-entrez` rate budget as Bio.Entrez; `esummary db=pubmed` resolves a
  PMID to PMCID/DOI when Europe PMC metadata fails (`ncbi_metadata`)
- Europe PMC and NCBI share one JATS parser (`infrastructure/sources/jats.py`);
  it extracts only the main `<article>` -- a nested `<sub-article>` or
  `<response>` (decision letter, author reply) never supplies body sections,
  figures or references
- `efetch` answering HTTP 200 without an article is a missing record only when
  the articleset carries NCBI's per-ID `<error>` statement; an `<ERROR>`
  envelope, an empty body or an empty articleset is `invalid_response`
- `structured_first` is `europe_pmc, ncbi_pmc, ...`; `application/fulltext/racing.py`
  starts NCBI when Europe PMC fails, has no body, or has not answered within the
  hedge delay (6 s), keeps the first usable body and cancels the other attempt
  (`source_notices: superseded`). Only a body ends the race; an attempt that
  ignores cancellation past the 1 s grace is held and reaped when it finishes
- NCBI's "publisher does not allow downloading of the full text in XML form"
  record is `front_matter_only`: no sections, a PMC landing-page link, and the
  ordinary PDF fallback still runs. The restriction applies to NCBI's XML copy
  only, so a Europe PMC attempt already running is not cancelled by it; it
  answers, fails or stops at the deadline (the XML cache bounds a foreground
  Europe PMC fetch at 45 s) and is reported accordingly. The restriction is
  detected in the main article's text and comments only
- one request deadline (`PUBMED_FULLTEXT_DEADLINE_SECONDS`, default 90 s) bounds
  every stage; a source cancelled by it is `deadline_exceeded`, a source never
  started is listed in `sources_skipped`. The PDF/extended downloader receives
  the remaining budget (minus at most 1 s) as its own end-to-end timeout, so it
  returns the links it already found instead of being cancelled with none
- `PUBMED_FULLTEXT_NCBI_PMC_FALLBACK=false` disables the NCBI route

### Source status contract

`application/fulltext/coverage.py` classifies already-sanitized failures without
importing infrastructure:

| `source_errors[].code` | Meaning |
| --- | --- |
| `upstream_retries_exhausted` | retryable HTTP status (5xx/408) still failing after transport retries |
| `rate_limited` | HTTP 429 or open circuit; `retry_after_seconds` carries the applied cooldown when known |
| `upstream_http_error` | non-retryable HTTP status (`status_code`) |
| `upstream_connection_error` | connection reset, hang-up or DNS failure |
| `timeout` | the source's own timeout or the XML cache fetch deadline |
| `deadline_exceeded` | cancelled at the overall `get_fulltext` deadline |
| `invalid_response` | unparseable or oversized payload |
| `cache_error` | local fulltext cache closed or at capacity; upstream status unknown |
| `source_unavailable` | anything else |

`FulltextCache` re-raises the adapter's own sanitized exception; it never
rewrites an upstream failure as a cache error. `source_notices` holds
`no_body`, `front_matter_only`, `superseded` and `supplied_not_verified`; none
of the first three is fulltext, and the last marks text registered by the host
agent or user.

### Phase 6: Single-article PMC page, acquisition plan and supplied text (v0.12.0)

Motivation: in an agent benchmark the host agent read the ENGAGES trial
(PMID 30721296, PMC6439616) from its public PMC page while the server returned
only links: Europe PMC timed out and NCBI `efetch` was `front_matter_only`
because the publisher forbids XML reuse.

- **`pmc_html` source** (`infrastructure/sources/pmc_html.py`): reads
  `https://pmc.ncbi.nlm.nih.gov/articles/PMCxxxxxxx/` through the fail-closed
  outbound layer (`fetch_public_url`) with the configured NCBI identity, a
  dedicated process-wide budget (`ncbi-pmc-article-page`, 1 request/s) and a
  4 MiB cap; parses the page into the shared section model (title + subtitle,
  "Abstract" block, nested body sections, figure captions, references with
  PMID/DOI, the displayed copyright/license text, courtesy note); drops site
  chrome, author pop-ups, table wraps, supplementary boxes and the side panel.
  A page that declares another canonical PMCID, an error page or a redirect off
  NCBI is `invalid_response`; 404/410 is an absence; 429 or a CAPTCHA
  interstitial is `rate_limited` with a shared cooldown, and later reads fail
  fast during the cooldown instead of waiting inside the request deadline.
- **Explicit single-article only.** `FulltextRequest.explicit_article_read`
  defaults to `False`; only the `get_fulltext` tool sets it. The page joins the
  structured race as a `HedgedAttempt(start_on_hedge=False)`: it starts only
  after an XML attempt failed, had no body or was `front_matter_only`, never
  merely because XML is slow. Another XML attempt may still be running then
  (for example a slow Europe PMC after NCBI answered front matter only); the
  first usable body wins and the slower attempt is reported as `superseded`. Search
  prefetch uses its own XML-only fetcher and can never reach the page
  (`tests/test_fulltext_pmc_html.py` proves both). Parsed pages are cached per
  tenant (16 entries, 1 h) in `ToolSessionRuntime.article_page_cache`;
  `PUBMED_FULLTEXT_PMC_HTML=false` removes the source. The body is reported as
  `fulltext_provenance: direct` with `fulltext_retrieval` (`source: pmc_html`,
  URL, `retrieved_at`, displayed license text, courtesy note,
  `usage: individual_reading`).
- **`fulltext_plan`** (`application/fulltext/plan.py`): when no usable body is
  obtained (or only unstructured PDF text), an ordered list of applicable steps
  for the host agent: `retry_later`, `host_fetch`, `download_oa_pdf`,
  `expand_discovery`, `institutional`, `zotero_attachment`, `ask_user_for_pdf`.
  Each carries `why`, `legal`, optional `url`/`via`/`tool_hint`/`then` and a
  pre-filled `register_with` skeleton. Steps are emitted only when they apply
  (PMCID, located OA links, configured OpenURL/EZproxy/broker, a DOI or PMID).
- **Supplied text** (`application/fulltext/intake.py`, `supplied.py`;
  `register_fulltext` tool): mandatory provenance, bounded inline content,
  allow-listed local files (workspace, notes, tenant data,
  `PUBMED_FULLTEXT_INTAKE_ROOTS`; no `..`, symlinks resolved before the root
  check, none for remote authenticated callers), JATS/HTML/PDF parsed with the
  provider adapters, stored per tenant beside the session artifacts as
  `agent_supplied` / `user_supplied`. `get_fulltext` serves it first as
  `registered_fulltext` with `supplied_not_verified` (opt out with
  `use_registered_fulltext=false`); note export records `fulltext_state`.

NCBI permits reading individual PMC articles but prohibits systematic or bulk
downloading from the PMC website. Nothing in this phase loops over search
results; bulk reuse belongs to the PMC Open Access subset services.

Pre-release review hardening (same release):

- Parsing is linear and bounded: Markdown headings use a linear pattern and
  lines over 300 characters are never headings; the HTML tree builder counts
  open elements per tag so stray end tags cost O(1), and caps elements
  (100,000), depth (128), sections (5,000) and size (8 M characters). A
  breach is `invalid_input` for intake and `invalid_response` for the page.
  Intake parsing, file reads and store writes run in worker threads.
- `pmc_html` needs an operator contact (`NCBI_EMAIL`; skipped as
  `not_configured` otherwise), has hourly budgets per process and per tenant,
  keeps redirects on NCBI hosts (checked before any status handling), backs
  off on 403, requires the page to declare its PMCID (canonical, citation URL
  meta or final URL) and its `citation_pmid` to match a known PMID, reports a
  page without the body container as layout drift, and marks PDF-only pages.
- The plan uses open-access wording only for verified OA links
  (`download_oa_pdf`); free-to-read PDFs (and a licensed PDF the server
  already extracted unstructured text from) are `download_pdf`,
  unknown-access PDFs are `check_access`, and other licensed copies go
  through `institutional`. Registration skeletons follow what
  the caller may use (content instead of files for remote callers; none
  without durable storage).
- Supplied text: a body-less registration never shadows providers
  (`supplied_no_body`); the newest registration wins per article across all
  known identifiers; documents declaring another article are refused;
  provenance is `supplied` and the supplier's license stays in
  `fulltext_retrieval`; network/device paths are refused before any OS call
  and files are read once with an identity check; the store retries Windows
  sharing violations, rolls back a failed save, drops dangling pointers and
  has a byte quota; source URLs are redacted. Withdrawing a registration is
  proposed as a separate decision (re-registering corrects it meanwhile).

### Phase 5: New high-value sources

- add `OpenAIRE`
- add `BASE`
- only after the service and registry are stable

## Acceptance Criteria

The refactor is successful when all of the following are true:

1. `get_fulltext` no longer owns source orchestration.
2. Policy resolution is identifier-driven, not boolean-driven.
3. Source capabilities are defined in one registry.
4. Discovery, fetch, and extract are explicit phases in code.
5. Adding a new fulltext source requires registry registration plus one handler, not MCP tool surgery.

## Testing Plan

### New tests

- `tests/test_fulltext_registry.py`
  - source filtering by identifier availability
  - policy resolution from PMCID / PMID / DOI

- `tests/test_fulltext_service.py`
  - structured-first path
  - DOI-only expanded discovery path
  - direct content vs extracted content provenance
  - link deduplication across discovery phases

### Existing tests to simplify

- `tests/test_europe_pmc_tools.py`
- `tests/test_europe_pmc_tools_extended.py`

These tool tests should focus on:

- input normalization
- progress reporting
- output formatting
- service integration seams

The service layer should own the orchestration assertions.

## Non-Goals For The First Pass

1. Do not add five more sources before the registry exists.
2. Do not change the public `get_fulltext` signature yet.
3. Do not fully redesign figure extraction in the same change.
4. Do not merge fulltext and text-mining into one mega-service.

## Recommendation

The best implementation order is:

1. FulltextRegistry and policy layer
2. Thin `get_fulltext` refactor onto a service
3. Direct PMC structured fallback

That sequence reduces duplication first, then reduces Europe PMC coupling, then makes new source additions cheap.
