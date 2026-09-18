<!-- Generated from docs/README.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# Documentation map / 文件分類

Start with current contracts and guides. Design proposals and dated reports
describe their own snapshots; they do not override the running tool registry.

| Category | Canonical entry | Ownership |
| --- | --- | --- |
| Install and operate | [README](#/overview), [integrations](#/troubleshooting), [deployment](#/deployment) | User-facing setup |
| Search and workflows | [user guide](#/user-guide), [tool usage](#/tools-usage-guide), [pipelines](#/pipeline-tutorial) | Current behavior; guides also have zh-TW editions |
| Architecture and contracts | [architecture](#/architecture), [search architecture](#/unified-search-architecture), [source contracts](#/source-contracts) | Implemented boundaries and provider protections |
| Development and checks | [contributing](https://github.com/u9401066/pubmed-search-mcp/blob/master/CONTRIBUTING.md), [developer guide](#/developer-guide), [script map](https://github.com/u9401066/pubmed-search-mcp/blob/master/scripts/README.md) | Local validation and maintenance commands |
| Evaluation and evidence | [benchmarks](#/academic-retrieval-benchmarks), [report index](reports/README.md) | Reproducible methods, dated measurements and review ledger |
| Design context | [pipeline persistence](PIPELINE_PERSISTENCE_DESIGN.md), [fulltext registry](FULLTEXT_REGISTRY_REFACTOR.md), [Chronicle specification](#/research-chronicle-rebuild-spec) | Read each document's implementation status before treating proposals as behavior |
| External comparisons | [reference repositories](reference-repositories/README.md), [BioMCP analysis](#/biomcp-analysis) | Comparisons and research, not product guarantees |
| Historical phases | [archive](archive/README.md) | Superseded implementation plans; old URLs contain navigation stubs |

## Generated files and local output

- Edit canonical Markdown, then run `uv run python scripts/build_docs_site.py`.
  `site-content/` and `site-content.js` are generated website payloads.
  The same builder updates packaged pipeline tutorials in this repository.
- `images/` holds documentation assets; use existing diagrams when possible.
- Keep measured evidence in `reports/`; keep disposable profiling output,
  inventories and downloads under the ignored `scripts/_tmp/` directory.
- `superpowers/` contains dated planning artifacts. `memory-bank/` at the repo
  root records current maintenance context, rather than another user guide.
- Root discovery files such as README, CONTRIBUTING, CHANGELOG and AGENTS remain
  at their established paths. Existing skill installations remain user-owned;
  document generation does not install or overwrite a user's customized harness.

Archive a superseded document with its relative links repaired and a short
old-path pointer. Preserve dated benchmark results and review-evidence paths.
Avoid creating a second copy of a current contract just to give it another name.
