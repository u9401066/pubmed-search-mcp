# Publication and citation workspace / 論文與引用

**Status: working manuscript, not submitted.** The software is v0.7.4; the
manuscript does not yet have an arXiv identifier, publication DOI, or acceptance.
Author and affiliation, confirmed September 21, 2026: **Tz-Ping Gau,
Kaohsiung Medical University Hospital**.

The paper is **PubMed Search MCP: An Auditable Integration Layer for
Agent-Assisted Biomedical Literature Retrieval**. It describes an academic
search integration service whose host agent retains planning and scientific
interpretation. It does not claim to be an autonomous researcher, introduce
BM25/RRF/MMR, or demonstrate a general agent-quality improvement.

## One source for each responsibility

| Source | Purpose |
| --- | --- |
| [main.tex](main.tex) | The only current manuscript; complete methods, results, limitations and proposed evaluation |
| [references.bib](references.bib) | Reviewed scholarly bibliography |
| [Reference review](references-review.md) | Primary-source checks, claim scope and corrected old citations |
| [Evidence map](evidence.md), [hash manifest](evidence.json) | What each existing measurement supports, and what it does not |
| [Evaluation protocol](evaluation-protocol.md) | Proposed native / original package / current package comparison; not a completed experiment or preregistration |
| [CITATION.cff](../../CITATION.cff) | Canonical **software** citation and release metadata |
| [Historical originals](../archive/publication/README.md) | Superseded January draft, old TeX, bibliography and PDF; do not cite their claims as current results |

## Read the existing evidence correctly

- NFCorpus test nDCG@10: 0.293357 → 0.297831 in a historical lexical-scorer
  comparison. Recall@100's paired interval includes zero. This did not evaluate
  the complete agent package.
- Offline execution: staggered dependencies reduced median in-memory MCP time
  by 19.82%, with unchanged operation counts and output signatures. All five
  scenarios are reported, including a serial-case slowdown. These are simulated
  provider delays, not live API throughput measurements.
- Three-query native/package pilot: both answered 2/3 exactly and hit the gold
  source PMID in 1/3. It does not establish an overall package benefit.
- Release checks demonstrate software contracts. Passing test counts do not
  measure literature relevance or claim support.

## Build locally

From the repository root, validate evidence hashes and bibliography keys and
generate tables without TeX, provider requests, or agent calls:

```bash
uv run --frozen python scripts/build_publication.py --prepare-only
```

Install [Tectonic](https://tectonic-typesetting.github.io/) separately, then:

```bash
uv run --frozen python scripts/build_publication.py --tectonic /path/to/tectonic
```

The first Tectonic run may download its TeX support bundle. It does not call
PubMed or run a benchmark. Local outputs live in ignored `build/publication/`:

- `main.pdf`: compiled reading copy.
- `arxiv-source.zip`: allowlisted TeX sources, generated tables, bibliography
  source and resolved `main.bbl`; no PDF, logs or historical drafts.
- `manifest.json`: source, citation metadata, builder and evidence hashes.
- `software-citation.bib`: generated from `CITATION.cff`.

`--prepare-only` invalidates old compiled artifacts so a previous PDF cannot be
mistaken for the current validated build. Do not edit generated tables or copies
in `build/`. Update a measured result by adding a dated report, reviewing its
scope, then intentionally updating `evidence.json`; never rewrite old evidence
to obtain a desired paper result.

Local compilation is not an arXiv submission check. Before actual upload, review
the final text, authorship, manuscript license, declarations and contact details;
then follow [arXiv's TeX instructions](https://info.arxiv.org/help/submit_tex.html)
and inspect the PDF produced by arXiv. No submission is performed by the builder.

## Cite the released software

Use GitHub's **Cite this repository** or [CITATION.cff](../../CITATION.cff), and
record the version or exact commit used by an experiment. The generated BibTeX
also includes the release version. Cite the software today; add a manuscript
citation only after an actual public manuscript identifier exists. An arXiv
placeholder or invented DOI must not become `preferred-citation`.

The author-approved name and institution replace the old username-only citation.
The existing software contact email is retained in CFF; no new corresponding
author address is invented for the manuscript.
