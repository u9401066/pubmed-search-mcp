<!-- Generated from docs/publication/README.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# Publication and citation workspace / 論文與引用

**Status: working manuscript, not submitted.** The manuscript describes the v0.7.4 software surface. It has no arXiv identifier, publication DOI, or acceptance. Cite the version used for a software result using [CITATION.cff](https://github.com/u9401066/pubmed-search-mcp/blob/master/CITATION.cff).
Author and affiliation, confirmed September 21, 2026: **Tz-Ping Gau,
Kaohsiung Medical University Hospital**.

The paper is **PubMed Search MCP: An Auditable Integration Layer for
Agent-Assisted Biomedical Literature Retrieval**. It describes an academic
search integration service whose host agent retains planning and scientific
interpretation. It does not claim to be an autonomous researcher, introduce
BM25/RRF/MMR, or demonstrate a general agent-quality improvement.

## Project history

The following dates distinguish work in the predecessor project, the creation of this GitHub repository and distribution of the software. All times are UTC.

| Date and time | What the record establishes | Primary record |
| --- | --- | --- |
| 2025-11-25 12:10:10 | The predecessor, `med-paper-assistant`, recorded its PubMed search implementation and MCP integration. | [Predecessor commit](https://github.com/u9401066/med-paper-assistant/commit/3caef4b10cfb9c27c705d9ac512854d4528bfd81) |
| 2025-12-02 13:44:15 | GitHub created the standalone repository (21:44:15 in Taiwan). | [GitHub repository metadata, field `created_at`](https://api.github.com/repos/u9401066/pubmed-search-mcp) |
| 2025-12-02 20:49:06 | The root Git commit records extraction of the library. At 21:14:56 the predecessor added this repository as a submodule. | [Root commit](https://github.com/u9401066/pubmed-search-mcp/commit/735113cc3d6c8fe08cbb8a821983fa2dbb87ff5e) · [Submodule change in the predecessor](https://github.com/u9401066/med-paper-assistant/commit/68701dfce294a7ee241ddc6924a7a382313b6140) |
| 2025-12-08 00:26:46 | PyPI records the upload of the 0.1.0 wheel, followed by the source archive two seconds later. | [PyPI 0.1.0 files](https://pypi.org/project/pubmed-search-mcp/0.1.0/#files) · [File timestamps](https://pypi.org/pypi/pubmed-search-mcp/0.1.0/json) |
| 2025-12-14 03:25:29 | The v0.1.13 commit declared a switch from MIT to Apache 2.0. Consult the license shipped with the version you use. Release v0.10.0 restores the standard Apache text, including section 8. | [Root MIT license](https://github.com/u9401066/pubmed-search-mcp/blob/735113cc3d6c8fe08cbb8a821983fa2dbb87ff5e/LICENSE) · [v0.1.13 change](https://github.com/u9401066/pubmed-search-mcp/commit/eda59af5c1ce9d227ebf402ba5fd47ac5934b283) · [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0) |

To reproduce the creation lookup, run `gh api repos/u9401066/pubmed-search-mcp --jq .created_at`. In a full Git clone, `git log --max-parents=0 --format="%H %cI %s" origin/master` shows the root commit. A registry upload independently dates a distributed artifact. For a historical claim about a particular feature, cite its implementing commit.

Four Entrez modules have identical Git blob IDs in the predecessor immediately before extraction and at the root of this repository. They are `base.py`, `batch.py`, `search.py` and `utils.py`. For example, `search.py` has blob ID `85979059d0d4a87ac0f70a20fcf7f81783998119` in both trees. The matching file contents corroborate the extraction recorded in the commits. [Predecessor tree](https://github.com/u9401066/med-paper-assistant/tree/3632a130734b42da20c1297b30ad807fc8e9542a/src/med_paper_assistant/infrastructure/external/entrez) · [Standalone tree](https://github.com/u9401066/pubmed-search-mcp/tree/735113cc3d6c8fe08cbb8a821983fa2dbb87ff5e/src/pubmed_search/entrez)

The earliest entry in the GitHub Releases list when checked on November 20, 2026 was v0.5.8, published May 11, 2026. The PyPI archive above documents the earlier distribution. GitHub recognizes the corrected preview license as `Apache-2.0`. [GitHub release v0.5.8](https://github.com/u9401066/pubmed-search-mcp/releases/tag/v0.5.8) · [License detection at the correction commit](https://api.github.com/repos/u9401066/pubmed-search-mcp/license?ref=bfb87346c968e6581eb62e75583d7bece183c111)

## One source for each responsibility

| Source | Purpose |
| --- | --- |
| [main.tex](publication/main.tex) | The only current manuscript; complete methods, results, limitations and proposed evaluation |
| [references.bib](publication/references.bib) | Reviewed scholarly bibliography |
| [Reference review](publication/references-review.md) | Primary-source checks, claim scope and corrected old citations |
| [Evidence map](publication/evidence.md), [hash manifest](publication/evidence.json) | What each existing measurement supports, and what it does not |
| [Evaluation protocol](publication/evaluation-protocol.md) | Proposed native / original package / current package comparison; not a completed experiment or preregistration |
| [CITATION.cff](https://github.com/u9401066/pubmed-search-mcp/blob/master/CITATION.cff) | Canonical **software** citation and release metadata |
| [Historical originals](archive/publication/README.md) | Superseded January draft, old TeX, bibliography and PDF; do not cite their claims as current results |

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

Use GitHub's **Cite this repository** or [CITATION.cff](https://github.com/u9401066/pubmed-search-mcp/blob/master/CITATION.cff), and
record the version or exact commit used by an experiment. The generated BibTeX
also includes the release version. Cite the software today; add a manuscript
citation only after an actual public manuscript identifier exists. An arXiv
placeholder or invented DOI must not become `preferred-citation`.

The author-approved name and institution replace the old username-only citation.
The existing software contact email is retained in CFF; no new corresponding
author address is invented for the manuscript.
