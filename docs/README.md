# Documentation map / 文件分類

Start with current contracts and guides. Design proposals and dated reports
describe their own snapshots; they do not override the running tool registry.

| Category | Canonical entry | Ownership |
| --- | --- | --- |
| Install and operate | [README](../README.md), [integrations](guides/INTEGRATIONS.md), [deployment](../DEPLOYMENT.md) | User-facing setup |
| Search and workflows | [user guide](guides/USER_GUIDE.md), [tool usage](guides/TOOLS_USAGE_GUIDE.md), [pipelines](guides/PIPELINE_MODE_TUTORIAL.en.md) | Current behavior; guides also have zh-TW editions |
| Architecture and contracts | [architecture](../ARCHITECTURE.md), [search architecture](architecture/UNIFIED_SEARCH_ARCHITECTURE.md), [source contracts](architecture/SOURCE_CONTRACTS.md) | Implemented boundaries and provider protections |
| Development and checks | [contributing](../CONTRIBUTING.md), [developer guide](development/DEVELOPER_GUIDE.md), [script map](../scripts/README.md) | Local validation and maintenance commands |
| Provider API contracts | [OpenAlex](providers/OPENALEX_API.md), [Semantic Scholar](providers/SEMANTIC_SCHOLAR_API.md), [ClinicalKey AI](providers/CLINICALKEY_AI_INTEGRATION.md), [images](providers/IMAGE_SEARCH_API.md) | Access modes, limits and response boundaries |
| Evaluation and evidence | [benchmarks](research/ACADEMIC_RETRIEVAL_BENCHMARKS.md), [report index](reports/README.md) | Reproducible methods, dated measurements and review ledger |
| Software citation and paper | [publication workspace](publication/README.md) | One current manuscript; evidence, bibliography and arXiv preparation |
| Design context | [pipeline persistence](archive/design/PIPELINE_PERSISTENCE_DESIGN.md), [fulltext registry](design/FULLTEXT_REGISTRY_REFACTOR.md), [Chronicle specification](design/RESEARCH_CHRONICLE_REFACTOR_SPEC.md) | Read each document's implementation status before treating proposals as behavior |
| External comparisons | [reference repositories](reference-repositories/README.md), [BioMCP analysis](research/BIOMCP_ARCHITECTURE_ANALYSIS.md) | Comparisons and research, not product guarantees |
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

## Whole-repository ownership

[repository-layout.json](repository-layout.json) classifies every tracked or new
non-ignored file, including source, tests, client assets, deployment files, reports
and generated pages. This is a placement inventory, separate from semantic code
review. Run `uv run python scripts/check_repository_layout.py --output build/repository-layout.json`;
unclassified or ambiguously owned files fail the local full gate.

The 27 root discovery/configuration/launcher files retain their established paths.
`src/`, `tests/`, `data/`, `scripts/`, `nginx/` and `copilot-studio/` already have
runtime consumers; their structure remains explicit in the ownership map.
Client-specific directories retain their installed ownership manifests and
customizations. Scripts keep stable command paths and use [one script map](../scripts/README.md).

The [move map](document-migrations.json) records the September 2026 relocation.
Website hash routes and Wiki page names remain stable; raw repository Markdown
paths listed in that map have changed. Update external source-file links using
the map. Only the existing Phase pointers, paper entry and embedded image-API
reference retain old-path stubs; directories contain the canonical full documents.
Keep dated JSON results and release receipts at their existing paths. Preserve
historical publication originals byte-for-byte, with their status documented.
