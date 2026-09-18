# Documentation map / 文件分類

Start with current contracts and guides. Design proposals and dated reports
describe their own snapshots; they do not override the running tool registry.

| Category | Canonical entry | Ownership |
| --- | --- | --- |
| Install and operate | [README](../README.md), [integrations](INTEGRATIONS.md), [deployment](../DEPLOYMENT.md) | User-facing setup |
| Search and workflows | [user guide](USER_GUIDE.md), [tool usage](TOOLS_USAGE_GUIDE.md), [pipelines](PIPELINE_MODE_TUTORIAL.en.md) | Current behavior; guides also have zh-TW editions |
| Architecture and contracts | [architecture](../ARCHITECTURE.md), [search architecture](UNIFIED_SEARCH_ARCHITECTURE.md), [source contracts](SOURCE_CONTRACTS.md) | Implemented boundaries and provider protections |
| Development and checks | [contributing](../CONTRIBUTING.md), [developer guide](DEVELOPER_GUIDE.md), [script map](../scripts/README.md) | Local validation and maintenance commands |
| Evaluation and evidence | [benchmarks](ACADEMIC_RETRIEVAL_BENCHMARKS.md), [report index](reports/README.md) | Reproducible methods, dated measurements and review ledger |
| Design context | [pipeline persistence](PIPELINE_PERSISTENCE_DESIGN.md), [fulltext registry](FULLTEXT_REGISTRY_REFACTOR.md), [Chronicle specification](RESEARCH_CHRONICLE_REFACTOR_SPEC.md) | Read each document's implementation status before treating proposals as behavior |
| External comparisons | [reference repositories](reference-repositories/README.md), [BioMCP analysis](BIOMCP_ARCHITECTURE_ANALYSIS.md) | Comparisons and research, not product guarantees |
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
