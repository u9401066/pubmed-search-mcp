<!-- Generated from docs/reports/mesh-preflight-2017/README.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# Does a MeSH preview improve a search decision?

On November 20, 2026, one Codex agent changed two of four PubMed searches after seeing a bounded comparison. Across the three interpretable pairs, both strategies recovered the same 20 of 34 known included reports. The reviewed searches presented 54 more candidate records in total. One review exposed a MeSH interpretation warning in both arms.

## Results

Both arms used PubMed relevance order and a maximum of 500 records per review. Each cell shows original → reviewed. “Included” counts positive content-level PMIDs in the frozen CLEF judgments. A study can have multiple reports.

| Review | Blinded decision | Included | Recovered at 500 | Candidates at 500 | All matches | ESearch attempts |
| --- | --- | ---: | --- | --- | --- | --- |
| CD007431 · lumbar radiculopathy | Keep both blocks | 15 | 4 → 4 | 500 → 500 | 1,590 → 1,590 | 1 → 4 |
| CD008081 · diabetic macular edema | Omit edema, keep diabetes and OCT | 10 | 7 → 7 | 500 → 500 | 1,457 → 2,688 | 1 → 4 |
| CD008760 · esophageal varices | Omit liver disease, keep capsule and varices | 9 | 9 → 9 | 72 → 126 | 72 → 126 | 1 → 4 |
| CD008782 · amyloid and dementia | Keep both after partial preview | 34 | Incomplete | Incomplete | Both carry a warning | 1 → 4 |

In the edema review, 170 records entered the first 500 and displaced 170 others. None of the gained or displaced records was a known included report. In the varices review, all nine known reports were already present before the extra 54 records entered. Across complete pairs the queues grew from 1,072 to 1,126. A reader continuing an already screened original queue would encounter 224 newly surfaced records across those three reviews. No human screening time was measured. Extra screens per additional included report is undefined because the gain was zero.

ESearch received four requests in the original arm and 16 in the reviewed arm across all four reviews. The additional twelve requests produced the three observations per topic. The exact JSON object shown to the agent occupied 593 UTF-8 bytes and 182 tokens under `o200k_base` (js-tiktoken 1.0.21). Individual summary values occupied 46, 47, 43 and 30 tokens before adding review IDs and the enclosing object. Host instructions, reasoning, tool wrappers and total billed usage were outside this measurement.

## Freeze and masking

The [protocol](reports/mesh-preflight-2017/protocol.json) selected the first four testing review IDs in lexical order. The baseline was the agent's first strategy given the review title. Each strategy combined a fixed concept and date range with two required MeSH/text blocks. Both arms had a four-request ceiling. The reviewed arm could keep the query or omit one block. It could see the production comparison summary, with no references supplied as seeds. The [frozen source file](https://github.com/CLEF-TAR/tar/blob/dbc13d02bb3e2f8ebc90e62ff47f5eb591e5ca20/2017-TAR/testing/qrels/qrel_content_test.txt) uses content-level inclusion as described by [Kanoulas, Li, Azzopardi and Spijker (2017)](https://strathprints.strath.ac.uk/62724/).

The qrels were downloaded to an ignored evaluation directory. Only their SHA-256 and topic titles were inspected before the [baseline commit](https://github.com/u9401066/pubmed-search-mcp/commit/0861f50). An exclusive stage receipt prevents a second live run in the same directory. All four choices and reasons were [committed before either arm retrieved a ranked page](https://github.com/u9401066/pubmed-search-mcp/commit/b056ef4). The agent and evaluator shared a workstation. Masking relied on withholding labels from the agent's inputs and locking decisions in Git. A future independent replication can hand only the title, clauses, decision instruction and visible summary to a separate reader.

The evaluation applies a common publication-date ceiling of 2016-12-31 to a contemporary PubMed index. The reviews' individual search dates, historical rankings, original published search strategies and any eligible records outside the public judgments are outside this comparison. Three completed pairs from diagnostic reviews do not establish performance on intervention reviews or meta-analysis generally. The pilot measures the marginal effect of preview on these four starting queries.

## What changed in v0.10.0

PubMed flagged `"Mild Cognitive Impairment"[mh]` in the fourth case. Its text-word alternatives still returned records. The frozen procedure marked the pair incomplete because the server's interpretation carried a warning. The original agent saw only which measurements were incomplete. After scoring, the plugin was changed to surface up to two short, distinct provider warning excerpts in the compact response. Their effect on decisions requires fresh topics.

The systematic-search skill now ships an [offline review table](https://github.com/u9401066/pubmed-search-mcp/blob/master/.claude/skills/pubmed-systematic-search/scripts/render_comparison.py). Export a production comparison's `plan.json` and sibling `drop-*.json` files from its session artifact. From the skill directory run `python scripts/render_comparison.py path/to/plan.json --choice keep --reason "Record the clinical reason here"`. It prints the selected query, sample PMIDs and the status of each difference without contacting PubMed.

## Reproduce

From the repository root, download the exact public qrels bytes using the URL in the protocol. Score the shipped [receipts and rankings](reports/mesh-preflight-2017/run) without contacting PubMed. Compare against the [recorded score](reports/mesh-preflight-2017/score.json).

```sh
curl -fL https://raw.githubusercontent.com/CLEF-TAR/tar/dbc13d02bb3e2f8ebc90e62ff47f5eb591e5ca20/2017-TAR/testing/qrels/qrel_content_test.txt -o qrels.txt
uv run --frozen python scripts/evaluate_mesh_preflight.py score --run docs/reports/mesh-preflight-2017/run --qrels qrels.txt
uv run --frozen python scripts/evaluate_mesh_preflight.py show --run docs/reports/mesh-preflight-2017/run
```

For a new live run, set `NCBI_EMAIL` to the operator's contact. Start with an unused run directory. Give the decision maker only the frozen clauses, title and compact preview printed to standard output. Write a choices JSON mapping each review ID to a `choice` (`keep` or an omitted block ID) and a nonempty `reason`. For a new blinded comparison use unseen reviews and freeze their own protocol with `--protocol` on each command. The published case decisions are now public.

```sh
uv run --frozen python scripts/evaluate_mesh_preflight.py freeze --run build/mesh-repeat --qrels qrels.txt
uv run --frozen python scripts/evaluate_mesh_preflight.py preview --run build/mesh-repeat
uv run --frozen python scripts/evaluate_mesh_preflight.py lock --run build/mesh-repeat --choices choices.json
uv run --frozen python scripts/evaluate_mesh_preflight.py retrieve --run build/mesh-repeat
uv run --frozen python scripts/evaluate_mesh_preflight.py score --run build/mesh-repeat --qrels qrels.txt
```

Each receipt binds its predecessor by hashing sorted, compact UTF-8 JSON. Interrupted live stages stay in the attempt directory. Record a fresh attempt in a new directory if the provider must be queried again. Exact historical results replay from the saved rankings. A new live request can observe changes to indexing or relevance order. [NCBI ESearch documentation](https://www.ncbi.nlm.nih.gov/books/NBK25499/)
