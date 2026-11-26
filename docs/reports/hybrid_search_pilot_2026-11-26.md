# Hybrid search retrieval pilot — 2026-11-26

This pilot asked whether fusing PubMed with full-text and semantic channels
(`unified_search(options="hybrid")`) retrieves more of a review's studies than
PubMed Best Match or the default `unified_search`. It did not. The sample is
six topics, so only large, consistent differences are read as findings.

## Setup

- **Runner:** `scripts/benchmark_hybrid_search.py`, GitHub Actions `ubuntu-latest`, live NCBI, Europe PMC and OpenAlex, no API keys, no LLM calls.
- **Topics:** six systematic reviews in anaesthesia and critical care (`tests/fixtures/hybrid_benchmark/topics.json`).
- **Gold:** primary studies in each review's PubMed reference list (15–45 per topic). This is a proxy for included studies: reference lists also hold background citations, so absolute recall is low for every arm.
- **Queries:** one MeSH-style query and one plain-language question per topic, written from the review question before any gold record was seen.
- **Arms:** PubMed Best Match; default `unified_search`; hybrid; hybrid with the breadth quota. Depth 50, searches limited to the review's publication year, the review itself removed.

## Results (run 2, means over six topics)

| Query | Arm | recall@10 | recall@20 | recall@50 | nDCG@20 | sec |
|---|---|---|---|---|---|---|
| MeSH | PubMed Best Match | 0.065 | 0.107 | 0.195 | 0.167 | 1.0 |
| MeSH | default | 0.062 | 0.114 | 0.195 | 0.166 | 4.8 |
| MeSH | hybrid | 0.076 | 0.117 | 0.199 | 0.164 | 23.4 |
| MeSH | hybrid + quota | 0.065 | 0.110 | 0.143 | 0.152 | 16.1 |
| question | PubMed Best Match | 0.039 | 0.043 | 0.043 | 0.092 | 0.6 |
| question | default | 0.079 | 0.120 | 0.171 | 0.185 | 5.7 |
| question | hybrid | 0.050 | 0.089 | 0.128 | 0.132 | 18.2 |
| question | hybrid + quota | 0.050 | 0.078 | 0.107 | 0.125 | 27.1 |

Run 1 (before the fixes below) gave the same ordering: default 0.191 against
PubMed 0.043 recall@50 on questions, and all arms within 0.03 on MeSH queries.

## Findings

- **F1 — default query expansion is the measured strength.** On plain-language questions the default search found about four times as many gold records in the top 50 as PubMed Best Match, in both runs and in five of six topics. PubMed ANDs every word of a long question.
- **F2 — hybrid did not improve recall.** With a MeSH query the three arms without a quota are indistinguishable. With a question, hybrid stayed below the default.
- **F3 — the breadth quota lowered recall** in both runs (0.195 to 0.143–0.171 recall@50 on MeSH queries). It is now opt-in (`breadth_quota`).
- **F4 — OpenAlex semantic search never answered** without an API key (12 of 12 calls failed in run 1; 24 of 24 fell back to keyword search in run 2). The "semantic" channel in these numbers is keyword relevance.
- **F5 — hybrid is four to five times slower** than the default (18–27 s against 5 s).
- **F6 — run-to-run variation is visible** (default on questions: 0.191 then 0.171), mostly from Semantic Scholar and Europe PMC timeouts.

## Limitations

- The gold standard favours PubMed: the reviews were themselves built from PubMed-style database searches of trials. It cannot show the value of records outside PubMed, and it says nothing about exploratory or mechanistic questions.
- Six topics from one clinical area, one query of each style per topic, written by the tool's developer.
- No agent in the loop: an agent rewrites queries, which this pilot does not model.

## Decisions

- Hybrid stays opt-in and is labelled experimental in the tool description.
- The breadth quota is off by default.
- Next evidence must come from agent-level runs on exploratory questions, with a clinician comparing blinded answers.
