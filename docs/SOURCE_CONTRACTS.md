# Source Contracts

Contract reference for every upstream corpus, resolver, and access layer used by PubMed Search MCP.

This document answers seven operational questions for each source:

1. What role does the source play in the product?
2. What repo-side rate policy do we enforce in code?
3. Which credential is required or optional?
4. Whether the source gives direct full text, figure access, or only metadata.
5. Whether licensing is uniform or article-level.
6. Whether provenance is direct or indirect.
7. What an agent should and should not promise to a user.

## Contract Semantics

![Source contracts and provenance map](images/source-contracts-provenance-map.svg)

| Term | Meaning in this repo |
| ---- | -------------------- |
| Direct provenance | The API is the primary host or canonical service for the returned object type. |
| Indirect provenance | The API is an aggregator, mirror, resolver, or metadata graph that points to upstream hosts. |
| Full text access | The source can return article body text or a direct OA/fulltext link, not just metadata. |
| Figure access | The source can return structured figure metadata or image URLs. |
| License posture | Whether the source exposes a stable license model or only passes through article-level licenses. |

## Unified Search Broker

`unified_search` is the broker boundary for literature discovery. The broker is
an in-process orchestration layer, not another upstream proxy: it validates one
request, selects registered adapters, executes independent providers in
parallel, and returns one provenance-preserving result envelope.

```mermaid
flowchart LR
    request["Normalize and validate request"] --> planner["Registry-backed source planner"]
    planner --> scheduler["Concurrent broker scheduler"]
    scheduler --> pubmed["PubMed"]
    scheduler --> epmc["Europe PMC"]
    scheduler --> graph["OpenAlex and Semantic Scholar"]
    scheduler --> oa["CORE and preprint servers"]
    scheduler --> licensed["Scopus and Web of Science<br/>explicit opt-in"]
    pubmed --> envelope["SourceAdapterResult envelopes"]
    epmc --> envelope
    graph --> envelope
    oa --> envelope
    licensed --> envelope
    envelope --> merge["Identifier-first deduplication and ranking"]
    merge --> response["Results, provenance, counts, and partial failures"]
```

The broker has six explicit stages:

1. **Normalize and validate.** Parse query options, year bounds, result limits,
   source expressions, and disabled-source policy before any network call.
2. **Plan.** Resolve `auto`, `all`, explicit lists, exclusions such as
   `auto,-semantic_scholar`, and the optional preprint expansion through the
   central source registry. Enrichment-only sources cannot satisfy a primary
   search by themselves.
3. **Schedule.** Fan out independent adapters concurrently while retaining a
   bounded per-source deadline. A slow or failed provider cannot discard good
   results returned by another provider.
4. **Protect providers.** Reuse a process-wide conservative rate budget per
   upstream service, then apply source-specific concurrency, retry/backoff,
   timeout, and circuit-breaker policy. Creating another client instance never
   creates another upstream quota.
5. **Normalize and merge.** Convert every adapter outcome into the same
   `ok` / `empty` / `partial` / `error` contract. Deduplicate by DOI, PMID,
   PMCID, OpenAlex, Semantic Scholar, CORE, or arXiv identifiers before using a
   normalized-title fallback.
6. **Report.** Return ranked articles together with queried/responded sources,
   per-source counts, retryable error metadata, provenance, reproducibility
   diagnostics, and durable artifact hints when the caller is allowed to write
   them.

### Source-selection invariants

- An explicit source selection is a contract. `sources="openalex"` never
  silently substitutes PubMed when OpenAlex returns zero records.
- Auto-relaxation may broaden a PubMed query only when PubMed was part of the
  plan. It reuses the successful relaxed response instead of issuing the same
  PubMed request twice.
- `PUBMED_SEARCH_DISABLED_SOURCES` is a kill switch for explicit, automatic,
  `all`, and `options="preprints"` selection paths.
- An empty successful response is reported as `empty`, not as an outage. A
  provider timeout, transport failure, exhausted 429 response, or invalid
  adapter result remains source-scoped so the overall response can be
  `partial`.
- Crossref and other enrichment adapters run only after primary discovery and
  cannot be selected as the sole search corpus.

### Adding another API

A new adapter should be admitted only when it adds a distinct corpus,
identifier authority, or legal-access path. It must register aliases and
capabilities, declare credentials and a conservative upstream policy, emit the
shared result/error envelope, preserve canonical identifiers and licenses, and
ship contract, timeout, 429, empty-result, deduplication, and partial-failure
tests. This prevents a larger source list from merely multiplying duplicate
records and rate-limit failures.

## Search And Discovery Sources

| Source | Product role | Repo-side rate policy | Credentials | Full text / figures | License posture | Indirect provenance |
| ------ | ------------ | --------------------- | ----------- | ------------------- | --------------- | ------------------- |
| PubMed / NCBI Entrez | Primary biomedical search, identifiers, abstracts, citation links | 0.34 s between requests without key, 0.1 s with key in Entrez base client | `NCBI_EMAIL` required by policy, `NCBI_API_KEY` optional | Metadata and abstracts direct; full text is indirect via PMC, DOI, LinkOut, or downstream resolvers | No single article-content license; metadata and abstract visibility follow NCBI plus publisher rights | Low for PubMed records themselves; higher once you pivot to PMC/LinkOut for content |
| Europe PMC | Search, OA/fulltext discovery, fullTextXML, text-mined terms | 0.1 s minimum interval | No API key; email is used for polite identification | Direct OA fullTextXML for supported records; can surface PMC-backed figures/full text | Article-level OA licenses vary by record | Yes. Europe PMC aggregates PubMed plus partner sources and mirrors OA content |
| OpenAlex | Broad discovery, OA indicators, institution/concept graph, journal context | 0.1 s minimum interval | No API key; polite-pool email is passed through existing email config | No hosted full text; only OA location hints and metadata | Metadata/open-data friendly, but article full-text license is inherited from linked OA location | Yes. OpenAlex is a metadata graph and OA-location aggregator |
| Semantic Scholar | Cross-domain discovery, citation graph, OA PDF hints | 1.0 s minimum interval with or without a key, plus cooldown after exhausted 429 retries | `S2_API_KEY` or `SEMANTIC_SCHOLAR_API_KEY` optional | No hosted full text; may expose `openAccessPdf` hints | Article-level license comes from linked host, not from Semantic Scholar itself | Yes. Metadata and OA hints are aggregated from upstream scholarly sources |
| CORE | Large OA aggregator for repositories and full-text-enabled outputs | 6.0 s without key, 2.5 s with key | `CORE_API_KEY` optional but strongly recommended | Can return OA records and full-text-backed outputs when repositories expose them | Repository-specific; no single global content license | Yes. CORE aggregates thousands of repositories and providers |
| Crossref | DOI registry, title lookup, funder metadata, references, enrichment | 0.05 s minimum interval | `CROSSREF_EMAIL` optional but recommended for polite pool | No direct full text; metadata and DOI resolution only | Metadata only; full-text rights remain with publisher or OA host | Yes. Crossref points to publisher and registry records rather than hosting article content |
| arXiv | Preprint discovery across quantitative biology, statistics, computing, and adjacent fields | 3.0 s minimum interval and one in-flight request | No API key | Abstract metadata plus direct arXiv PDF links | Record-level arXiv license; do not infer peer review or downstream reuse rights | Low for arXiv records; published-version matching is an indirect DOI/title link |
| medRxiv / bioRxiv | Medical and biological preprint discovery with local filtering of date-based API results | Shared provider budget and a 20 s broker-side source deadline; no fixed repo interval | No API key | Abstract metadata and preprint URLs/PDF links where supplied | Article-level preprint license; not evidence of peer review | Low for native preprint records; published-version matching is indirect |
| Scopus | Licensed bibliographic and citation discovery; default off and never silently added to `auto` | 0.2 s minimum interval; maximum 25 records per adapter request | `SCOPUS_ENABLED=true` plus `SCOPUS_API_KEY`; optional institutional token | Metadata, identifiers, citation fields, and links; no repository-hosted article body | Elsevier API/subscription terms and the caller's institutional entitlements | Low for the Scopus index record; linked publisher content remains indirect |
| Web of Science | Licensed bibliographic and citation discovery; default off and never silently added to `auto` | 0.2 s minimum interval; maximum 25 records per adapter request | `WEB_OF_SCIENCE_ENABLED=true` plus `WEB_OF_SCIENCE_API_KEY` | Metadata, identifiers, citation fields, and links; no repository-hosted article body | Clarivate API/subscription terms and the caller's institutional entitlements | Low for the Web of Science record; linked publisher content remains indirect |
| NCBI Extended (Gene, PubChem, ClinVar) | Structured gene, compound, and variant data outside PubMed | 0.34 s without key, 0.1 s with key | `NCBI_EMAIL` required by policy, `NCBI_API_KEY` optional | No article full text; structured database records only | Database-record specific; not a literature full-text source | Low. These are canonical NCBI databases, but not direct article-body providers |

## OA Resolution, Full Text, And Visual Sources

| Source | Product role | Repo-side rate policy | Credentials | Full text / figures | License posture | Indirect provenance |
| ------ | ------------ | --------------------- | ----------- | ------------------- | --------------- | ------------------- |
| Unpaywall | Legal OA resolver used for enrichment and download fallback | 0.1 s minimum interval | `UNPAYWALL_EMAIL` expected | No hosted full text; returns legal OA locations and license hints | License comes from the chosen OA location | Yes. Unpaywall is a resolver over repositories and publisher OA endpoints |
| PMC Open Access / FigureClient | Structured figure extraction and PMC-backed visual retrieval | 0.2 s minimum interval in figure client | No dedicated key | Direct figure metadata and image URLs only for PMC Open Access-compatible articles | Article-level OA license; figure reuse depends on the article's license | Mixed. FigureClient uses Europe PMC XML, PMC efetch XML, and PMC BioC fallback |
| FulltextDownloader chain | PDF/fulltext link collection and fallback routing | Concurrency-limited downloader with per-source fallbacks; no single shared interval | No single key; downstream keys come from CORE, Unpaywall, and source-specific services | Can return direct PDF links, text, or structured sections depending on the source | License varies by the final OA host | Yes. This layer is intentionally indirect and should cite the final host it selected |
| Open-i | Biomedical image discovery across image-bearing biomedical articles | 1.0 s minimum interval | No API key | Image metadata and URLs; not general article full text | Supports license filtering by CC-style Open-i license codes | Yes. Open-i is an image-focused aggregator rather than the canonical publisher host |
| ClinicalTrials.gov | Trial registry enrichment alongside literature results | No explicit repo-side throttle declared in current client | No key | Structured registry records only; no article full text | Registry data, not article-license content | Low. Canonical trial registry, but not a paper/full-text source |
| OpenURL resolver | Institutional subscription handoff | No outbound fetch in resolver builder itself | `OPENURL_RESOLVER` or preset config | Subscription access handoff only; not a content corpus | Governed by your institution's subscription agreements | Yes. This is a redirect/access layer, not a source of record |

## Contract Rules For Agents

1. Treat PubMed, Europe PMC, and NCBI Extended as canonical for their native record types, but do not imply full text unless the workflow pivots into PMC, OA links, or an institutional resolver.
2. Treat OpenAlex, Semantic Scholar, CORE, Crossref, and Unpaywall as discovery, enrichment, or access-routing layers. When they surface a link, preserve the upstream host in the final answer.
3. Treat figure extraction as PMC Open Access scoped. If a PMID has no resolvable PMCID, do not promise figure extraction.
4. Treat license fields as article-level unless a source has an explicit platform-level rule. OA status does not automatically mean reusable figures.
5. Treat `optional key` as throughput control, not an authorization promise. A key may improve rate limits without changing rights.
6. When a source is indirect, include both the surfacing source and the canonical host when presenting evidence trails or download links.

## Practical Examples

| Need | Prefer | Why |
| ---- | ------ | --- |
| Highest-trust biomedical identifiers | PubMed / NCBI Entrez | Canonical PMID-first workflow |
| Structured OA XML | Europe PMC | Direct fullTextXML support |
| OA figure extraction | PMC Open Access via FigureClient | Direct figure metadata and image URLs |
| Broad OA corpus expansion | CORE or OpenAlex | Aggregated discovery beyond PubMed |
| Legal OA link resolution | Unpaywall | Best OA location plus license hints |
| DOI metadata and references | Crossref | Canonical DOI registry enrichment |
| Institutional subscription handoff | OpenURL | Access layer, not corpus |
