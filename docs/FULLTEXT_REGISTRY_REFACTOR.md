# Fulltext Registry Refactor Design

## Goal

Promote fulltext retrieval from an accumulated fallback chain into a metadata-driven service.

The immediate objective is not to add more sources. The objective is to make the existing fulltext path mature enough that new sources can be added without growing a second orchestration layer in the MCP tool.

## Current Status

As of 2026-04-06, the first orchestration extraction has landed:

- `get_fulltext` keeps input normalization, progress/log bridging, and output formatting
- `fulltext_service.py` owns identifier-aware source orchestration
- `fulltext_registry.py` defines the initial policy/source metadata surface

The next refactor target is now narrower: make `fulltext_download.py` more explicitly phase-oriented internally so discovery, fetch, and extract are cleanly separated below the service layer.

## Problem Statement

The current fulltext path already has meaningful source coverage, but the architecture is still uneven:

1. Discovery and extraction responsibilities are still uneven below the service layer.
   - `fulltext_service.py` now owns policy resolution and high-level orchestration.
   - `fulltext_download.py` still mixes broad link discovery, fetch logic, and PDF text extraction in one infrastructure module.

2. Structured fulltext is still over-coupled to Europe PMC.
   - Structured XML is treated as a special-case branch in the tool instead of a pluggable structured source policy.

3. `extended_sources` is a transport flag, not a retrieval policy.
   - The current boolean mixes user intent, discovery breadth, and fallback behavior into one switch.

4. Discovery, fetch, and extract are present but not explicit.
   - The downloader already does all three, but they are not separated as replaceable strategies.

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

5. Preserve backward compatibility.
   - The public `get_fulltext(..., extended_sources=...)` signature can remain for compatibility, but the boolean should become a legacy hint that upgrades policy selection rather than owning orchestration.

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

`src/pubmed_search/infrastructure/sources/fulltext_service.py`

Responsibilities:

- resolve a retrieval policy from identifiers and compatibility hints
- execute structured-first or expanded discovery flows
- coordinate discovery, fetch, and extract phases
- return one normalized fulltext result object for the tool layer

### Registry Layer

`src/pubmed_search/infrastructure/sources/fulltext_registry.py`

Responsibilities:

- define available fulltext sources and their metadata
- define retrieval policies
- filter sources by identifier availability and policy scope

### Downloader Layer

`src/pubmed_search/infrastructure/sources/fulltext_download.py`

Responsibilities after refactor:

- discovery helpers for link candidates
- fetch helpers for XML / PDF / landing pages
- extract helpers for PDF text or structured content post-processing

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
| `europe_pmc` | `pmcid` | `structured`, `pdf` | direct Europe PMC client |
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
- optionally upgrade discovery breadth if compatibility hint requests it

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
4. If legacy `extended_sources=True` is provided, widen discovery scope without changing the public tool contract.

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

### New files

- `src/pubmed_search/infrastructure/sources/fulltext_registry.py`
- `src/pubmed_search/infrastructure/sources/fulltext_service.py`

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

### Phase 3: Downloader split

- expose explicit discovery helpers
- expose explicit fetch helpers
- expose explicit extract helpers
- stop letting the downloader decide policy

### Phase 4: Direct PMC structured fallback

- add `pmc_structured_direct`
- place it behind the same structured capability contract as Europe PMC
- allow `structured_first` to try more than one structured source

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
