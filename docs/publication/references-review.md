# Bibliography review

Reviewed September 21, 2026 against primary records. Keys match
[references.bib](references.bib); the build rejects undefined, duplicate or unused
keys. This mechanical check does not validate a reference's scientific support.

| Key | Primary record | Use in this manuscript |
| --- | --- | --- |
| `robertson2009bm25` | [Original author-hosted paper](https://www.ccs.neu.edu/home/vip/teach/IRcourse/IR_surveys/robertson_foundations.pdf), [DOI](https://doi.org/10.1561/1500000019) | Established probabilistic lexical ranking; journal article, 2009, 3(4):333–389 |
| `cormack2009rrf` | [Author-hosted SIGIR paper](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf), [DOI](https://doi.org/10.1145/1571941.1572114) | Rank fusion attribution; SIGIR 2009, 758–759 |
| `carbonell1998mmr` | [Author publications](https://www.cs.cmu.edu/~jgc/publications.html), [DOI](https://doi.org/10.1145/290941.291025) | Relevance/diversity tradeoff attribution; SIGIR 1998, 335–336 |
| `rethlefsen2021prismas` | [Publisher article](https://link.springer.com/article/10.1186/s13643-020-01542-z) | Search reporting context; Systematic Reviews 10:39; no claim of complete PRISMA-S compliance |
| `vandeschoot2021asreview` | [Publisher article](https://www.nature.com/articles/s42256-020-00287-7) | Screening versus discovery distinction; correct title and Nature Machine Intelligence 3:125–133 |
| `thakur2021beir` | [Official proceedings](https://datasets-benchmarks-proceedings.neurips.cc/paper/2021/hash/65b9eea6e1cc6bb9f0cd2a47751a186f-Abstract-round2.html), [dataset distribution](https://github.com/beir-cellar/beir) | Retrieval evaluation and distribution used by the historical experiment |
| `nfcorpus` | [Publisher chapter / DOI](https://doi.org/10.1007/978-3-319-30671-1_58), [dataset project](https://www.cl.uni-heidelberg.de/statnlpgroup/nfcorpus/) | Boteva, Gholipour, Sokolov and Riezler, 2016, 716–722; distinguish original dataset from BEIR distribution |
| `ajith2024litsearch` | [ACL Anthology](https://aclanthology.org/2024.emnlp-main.840/) | EMNLP 2024 scientific retrieval task, 597 queries; not a biomedical-only evaluation |
| `shen2026scholargym` | [arXiv v3](https://arxiv.org/abs/2601.21654v3) | Static information-gathering tasks; version and approximate corpus size stated, not a completed repo benchmark |
| `burgess2026papersearchqa` | [arXiv](https://arxiv.org/abs/2601.18207), [author project](https://jmhb0.github.io/PaperSearchQA/) | Search/QA task and pilot source; project reports EACL 2026, bibliography cites available preprint |
| `mcp2026` | [Protocol specification](https://modelcontextprotocol.io/specification/2026-07-28) | Communication protocol context, not a claim about retrieval quality |
| `openresearch2026` | [Official alphaXiv repository](https://github.com/alphaXiv/OpenResearch) | Research-workspace scope and inspectable artifacts; no comparative outcome claim |

Crossref DOI metadata was used to cross-check the algorithm, PRISMA-S, ASReview
and NFCorpus publication fields. One conflict remains explicitly documented:
the current Crossref response for the BM25 survey reports a different volume/page
range; the bibliography follows the original paper's printed 3(4):333–389 rather
than silently copying the conflicting API fields. The NFCorpus project host was
intermittently unreachable during review; author/title/pages were checked through
its DOI record and the actual experiment's distribution through BEIR.

The old ASReview entry had the wrong title/journal. Unused or insufficiently
verified entries, speculative competitor comparisons and novelty framing from
the [archived bibliography](../archive/publication/references.bib) are not carried
into the new manuscript. Bibliographic provenance is retained without pretending
all older references have been validated.

Reference validation here checks identity and whether a source is appropriate
for the limited claim made. It does not imply replication of external experiments,
endorsement by the cited authors, or review of every statement in those works.
