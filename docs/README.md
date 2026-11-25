# Documentation map / 文件分類

Start with current contracts and guides. Design proposals and dated reports
describe their own snapshots; they do not override the running tool registry.

| Category | Canonical entry | Ownership |
| --- | --- | --- |
| Install and operate | [README](../README.md), [integrations](guides/INTEGRATIONS.md), [deployment](../DEPLOYMENT.md) | User-facing setup |
| Search and workflows | [user guide](guides/USER_GUIDE.md), [tool usage](guides/TOOLS_USAGE_GUIDE.md), [pipelines](guides/PIPELINE_MODE_TUTORIAL.en.md) | Current behavior; guides also have zh-TW editions |
| Architecture and contracts | [architecture](../ARCHITECTURE.md), [search architecture](architecture/UNIFIED_SEARCH_ARCHITECTURE.md), [source contracts](architecture/SOURCE_CONTRACTS.md) | Implemented boundaries and provider protections |
| Development and checks | [contributing](../CONTRIBUTING.md), [developer guide](development/DEVELOPER_GUIDE.md), [testing policy](development/TESTING.md), [script map](../scripts/README.md) | Local validation and maintenance commands |
| Provider API contracts | [OpenAlex](providers/OPENALEX_API.md), [Semantic Scholar](providers/SEMANTIC_SCHOLAR_API.md), [ClinicalKey AI](providers/CLINICALKEY_AI_INTEGRATION.md), [images](providers/IMAGE_SEARCH_API.md) | Access modes, limits and response boundaries |
| Evaluation and evidence | [benchmarks](research/ACADEMIC_RETRIEVAL_BENCHMARKS.md), [historical-methods case study](reports/chronicle_historical_method_2026-11-20.md), [report index](reports/README.md) | Reproducible methods, dated measurements and review ledger |
| Software citation and paper | [publication workspace](publication/README.md) | One current manuscript; evidence, bibliography and arXiv preparation |
| Design context | [pipeline persistence](archive/design/PIPELINE_PERSISTENCE_DESIGN.md), [fulltext registry](design/FULLTEXT_REGISTRY_REFACTOR.md), [background fulltext assessment](design/FULLTEXT_PREFETCH.md), [Chronicle specification](design/RESEARCH_CHRONICLE_REFACTOR_SPEC.md), [agent input contract](design/AGENT_INPUT_CONTRACT.md) | Read each document's implementation status before treating proposals as behavior |
| External comparisons | [reference repositories](reference-repositories/README.md), [BioMCP analysis](research/BIOMCP_ARCHITECTURE_ANALYSIS.md) | Comparisons and research, not product guarantees |
| Historical phases | [archive](archive/README.md) | Superseded implementation plans; old URLs contain navigation stubs |

## Capability inventory

本表以 2026-11-25 的 v0.11.0 為準。從 MCP `tools/list` 取得的 43 個名稱與 16 類 registry 完全相符。v0.10.0 的 registry 有 42 項，新增 `research_workspace`，也在既有 `analyze_search_query` 上加入 PubMed 組合預查。v0.11.0 新增 `pipeline_screening`，並讓保存的 pipeline 支援完整取回、PRISMA-S 紀錄與概念區塊分析。逐一查名稱、參數與輸出請用[繁中逐工具稽核](research/TOOL_QUALITY_AUDIT.zh-TW.md)、[English tool contracts](research/TOOL_QUALITY_AUDIT.md)或[產生的完整索引](../src/pubmed_search/presentation/mcp_server/TOOLS_INDEX.md)。

[All-tools acceptance](../tests/test_all_tools_mcp_acceptance.py) exercises every tool over stdio and HTTP with controlled provider responses, including an installed wheel. The table identifies further evidence and what still depends on the research topic, access or operating environment.

| Registry family | Tools | Tested behavior | Completeness boundary |
| --- | ---: | --- | --- |
| Search | 1 | Multi-source retrieval, partial failures and durable run output. [Broker tests](../tests/test_unified_broker_correctness.py) | Provider limits and bounded retrieval can omit eligible papers. |
| Query intelligence | 3 | PICO handoff, MeSH suggestions and live-set comparisons. [Comparison tests](../tests/test_query_comparison.py) | One historical PubMed example has live counts. Topic-wide recall still needs independent eligible studies. |
| Discovery | 5 | Article details, related records, references, citing papers and citation metrics. [Article workflow](guides/TOOLS_USAGE_GUIDE.md) | Missing links and metrics depend on source indexing. |
| Reference verification | 1 | Candidate matches and mismatch evidence. [Verification tests](../tests/test_reference_verification.py) | Bibliographic identity alone cannot establish claim support. |
| Full text | 2 | Section reads, fallback and mined entities. [Full-text tests](../tests/test_fulltext_service.py) | An abstract or resolver URL establishes only that level of access. |
| Figures | 1 | Figure extraction from available structured articles. [Figure tests](../tests/test_figure_tools.py) | Images and captions depend on the available source format. |
| Extended NCBI | 7 | Gene, compound, linked articles and ClinVar lookups. [NCBI tool tests](../tests/test_ncbi_extended_tools.py) | Database coverage and upstream availability apply per request. |
| Citation network | 1 | Bounded citation-tree traversal from seed PMIDs. [Graph tests](../tests/test_citation_tree.py) | Depth and branch limits bound the observed graph. |
| Export | 2 | Bibliography formatting and local wiki-note export. [Export tests](../tests/test_export_tools.py) | Notes retain their verification status and abstract opt-out. |
| Session and workspace | 2 | Inspect and replay run arguments, store and resume decisions. [Workspace tests](../tests/test_research_workspace.py) | Resuming reading and rerunning a strategy are supported. Provider cursor continuation remains open. |
| Institutional access | 5 | Resolver configuration, links, access tests and diagnosis. [Institutional fetch tests](../tests/test_institutional_fetch.py) | Each institution needs its own credential and entitlement check. |
| Vision handoff | 1 | Prepare figure-search input for a host agent. [Vision tests](../tests/test_vision_search.py) | Image interpretation depends on the host's capabilities. |
| ICD | 1 | ICD-to-MeSH lookup, mapping provenance and unsupported inputs. [Mapping tests](../tests/test_icd_conversion.py) | Coverage is limited to the available mappings. |
| Chronicle | 2 | Build and compare revisions, inspect candidate branches, milestones and documents. [Revision tests](../tests/test_chronicle_revision_integrity.py) · [Historical case](reports/chronicle_historical_method_2026-11-20.md) | Importance and disputed forks need independent domain review. |
| Biomedical image search | 1 | Query NLM Open-i with English terms and normalize returned images and source coverage. [Source tests](../tests/test_image_search.py) | A result link establishes neither ongoing availability nor reuse rights. |
| Pipeline | 7 | Save, load, list, delete, inspect history, schedule and unschedule. [Saved reports](../tests/test_pipeline_report_save.py) · [Scheduler](../tests/test_pipeline_scheduler.py) | Useful for review searches. Screening, risk-of-bias assessment and statistical pooling need other workflows. |

### 這些證據能回答哪些研究問題？

| 使用場景 | 分支上已有的能力 | 還缺哪一份證據 |
| --- | --- | --- |
| 系統性回顧與 EBM | 可保存並重跑搜尋式，以 PICO 組織問題，從個別差集檢查放寬條件後找到的 PMID。 | 先凍結一組獨立認定的合格研究，再跨主題量漏檢率與多出的篩選量。出版類型標記不能代替偏差風險或 GRADE 評讀。[檢索評估基準](research/ACADEMIC_RETRIEVAL_BENCHMARKS.md) |
| Chronicle 歷史分歧 | 舊文可在新修訂中建立關聯，保留原年份與來源。人工耳蝸三篇案例中，程式交出三份可追查的文獻，自動語意分歧候選為零。 | 請領域讀者獨立標記轉折、支線與相反解釋，分開評估「新發表」和「新辨認」。[案例與原始史料](reports/chronicle_historical_method_2026-11-20.md) |
| 全文與本機館藏 | 可區分摘要、可讀段落與 resolver 線索。宿主可透過獲授權的 Zotero Keeper 交叉比對 PMID 或 DOI。 | 各機構能讀到的全文和館藏不同。應實測從付費文章一路追到已授權段落的成功率。[來源與存取檢討](reports/chronicle_evidence_review_2026-11-20.md) |
| 跨人交接與多人部署 | 工作區可以保存決策、證據定位與下一步，服務能依租戶隔離狀態。 | 以預期的 3–5 個部署、每處 100–300 名註冊使用者設計尖峰同時使用情境。量交接時間、API 限流、跨租戶隔離及備份還原。[部署指南](../DEPLOYMENT.md) |

### Product surfaces beyond MCP tools

| Surface | Implemented and checked | Remaining dependency |
| --- | --- | --- |
| Agent plugin and skills | 12 shipped skills, a version-pinned release launcher and a checkout launcher. Only the checkout includes branch features. [Packaging and restart tests](../tests/test_agent_plugin_package.py) | Host installation UI and agent decisions vary. |
| Prompts and resources | Live discovery returned nine prompts and 14 resources covering sessions, filters, ICD mapping and tool reference. [Resources](../src/pubmed_search/presentation/mcp_server/resources.py) · [Prompts](../src/pubmed_search/presentation/mcp_server/prompts.py) | Hosts decide which resources and prompts to expose. |
| Python, CLI and transport | `pubmed_search.api`, stdio and HTTP launchers, optional authorized browser broker, companion HTTP reads and Copilot Studio setup. [Python tests](../tests/test_public_api_facade.py) · [Transport and installed-wheel smoke](../tests/test_release_transport_smoke.py) | An installed server passing smoke still needs local client or institution configuration. |
| Deployment and access | Local single-user mode, bearer-authenticated principals, tenant-scoped storage and budgets. [Isolation tests](../tests/test_multi_tenant_deployment.py) · [Deployment](../DEPLOYMENT.md) | Capacity at 100–300 registered users per site and backup restoration need representative measurements. |
| Local sources and research evaluation | A host with Zotero Keeper access can compare PMID/DOI and record the local item key. [Handoff tests](../tests/test_workspace_source_handoffs.py) · [Benchmark scope](research/ACADEMIC_RETRIEVAL_BENCHMARKS.md) | Zotero authorization and full-text holdings are external. Evidence for retrieval quality is specific to the benchmark and version. |

### Markdown and illustration records

Open the [per-file Markdown catalog](reports/markdown-catalog.csv) to find an edit source, generated copy, historical record or client-specific instruction. Refresh it after adding or moving tracked documents with `uv run python scripts/check_repository_layout.py --document-catalog docs/reports/markdown-catalog.csv`. The catalog records ownership and provenance. Historical measurements keep their original dates. Current guides supersede old instructions where paths overlap.

The catalog includes the 32 website pages generated from canonical documents, plus skill copies, historical plans, GitHub contribution templates and compatibility pointers.

The 23 canonical SVGs in [images](images/) include 22 diagrams and one favicon. The research overview, PubMed query comparison and Chronicle figures use the current branch workflow or a dated worked example. The export, institutional access, session and capability diagrams have corrected labels. The remaining specialist figures cover deployment, data sources, DAGs, retrieval and verification. [Workspace overview](images/research-workflow.svg) · [MeSH set differences](images/search-query-workflow.svg) · [Chronicle publication and recognition dates](images/research-chronicle-lineage-flow.svg)

Two pipeline illustrations are also bundled with the skill for offline reading. [Archive index](archive/README.md) · [Current evaluation questions](../ROADMAP.md)

## Generated files and local output

- Edit canonical Markdown, then run `uv run python scripts/build_docs_site.py`.
  `site-content/` and `site-content.js` are generated website payloads.
  The same builder updates packaged pipeline tutorials in this repository. Pages and Wiki use `documentation_source_ref` in `repository-layout.json` for source and test links. Set the ref to the publication branch when promoting a preview.
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
