# PubMed Search MCP 開發者指南

這份指南給 maintainer 與 contributor。它說明 codebase 組織、行為應放在哪一層、文件如何生成，以及哪些驗證命令保護整合面。

請搭配 [架構文件](../ARCHITECTURE.md)、[AGENTS.md](../AGENTS.md) 與 [工具使用指南](TOOLS_USAGE_GUIDE.zh-TW.md) 閱讀。

## Repository 契約

PubMed Search MCP 是 Python MCP server，架構遵守 Domain-Driven Design 邊界：

![DDD 與 runtime 邊界](images/ddd-runtime-boundaries.svg)

```text
presentation -> application -> domain
                  application -> infrastructure
```

Presentation layer 負責 MCP tools、prompts、resources 與 HTTP compatibility behavior。這層應保持 thin wrapper。Workflow orchestration 放在 `src/pubmed_search/application/`。Domain concepts 放在 `src/pubmed_search/domain/`。外部 API、storage adapters、cache implementations 與 provider-specific clients 放在 `src/pubmed_search/infrastructure/`。

共享規則：

- 使用 `uv` 與 `uv run`
- 修 root cause，不疊臨時 wrapper patch
- MCP tool functions 只做 application services 的 adapter
- 行為改變時同步更新 docs、generated tool indexes 與 site payloads
- 不要在 `.github/`、`.clinerules/` 與 `AGENTS.md` 重複 agent 規則

## Runtime Surfaces

| Surface | Entry | 用途 |
| --- | --- | --- |
| Local MCP stdio | `uvx pubmed-search-mcp` 或 `uv run python -m pubmed_search.presentation.mcp_server` | 預設本機 client 模式 |
| Streamable HTTP | `uv run python run_server.py --transport streamable-http` | 遠端 MCP clients 與 service deployments |
| Full Copilot-compatible HTTP | `uv run python run_server.py --transport streamable-http --copilot-compatible` | 保留完整 primary MCP surface，並加上 Copilot-compatible HTTP semantics |
| Simplified Copilot Studio | `uv run python run_copilot.py` | Copilot Studio compatibility 優先的小型 schema |
| Browser fetch broker | `uv run pubmed-browser-fetch-broker --token ...` | 可選的本機 Playwright broker，用於 authenticated PDF download capture |
| Static docs site | `docs/index.html` 加 generated payload | GitHub Pages 文件網站 |

不要把這些當成彼此分裂的產品。除了 `run_copilot.py` 有意暴露 Copilot-specific simplified surface，其餘多數都是同一核心能力的不同 adapter。

## Code Map

```text
src/pubmed_search/
├── domain/          # entities, value objects, domain services
├── application/     # search, export, timeline, pipeline, session orchestration
├── infrastructure/  # NCBI, Europe PMC, CORE, OpenAlex, CrossRef, cache, HTTP, sources
├── presentation/    # MCP server, HTTP API, browser broker entry point
└── shared/          # settings, async helpers, errors, profiling
```

重要 presentation 檔案：

- `presentation/mcp_server/server.py`：server creation、DI container、stdio startup、background API
- `presentation/mcp_server/tool_registry.py`：primary tool registry 的權威來源
- `presentation/mcp_server/tools/*.py`：MCP adapters
- `presentation/mcp_server/copilot_tools.py`：Copilot Studio simplified surface
- `presentation/mcp_server/http_compat.py`：Copilot HTTP compatibility middleware
- `presentation/browser_fetch_broker.py`：local browser broker CLI

重要文件檔案：

- `scripts/count_mcp_tools.py`：從 registry 重新生成 tool index
- `scripts/build_docs_site.py`：生成 `docs/site-content/*.md` 與 `docs/site-content.js`
- `docs/site.js`：client-side docs router 與 language switch
- `tests/test_docs_site_sync.py`：確認 generated docs payloads 與 canonical Markdown 一致

## 新增或修改 MCP Tools

Primary MCP tools 建議流程：

1. 把 business logic 放在 domain/application/infrastructure，不放在 tool wrapper。
2. 在 `src/pubmed_search/presentation/mcp_server/tools/` 新增或更新 MCP adapter。
3. 在 `tool_registry.py` 登錄 tool，選對 category 與 description。
4. 增加或更新 service behavior 與 presentation adapter 的 tests。
5. 重新生成 tool index：

   ```bash
   uv run python scripts/count_mcp_tools.py --update-docs
   ```

6. 如果 user-facing behavior 改變，同步更新 capability docs。
7. 重建 docs site：

   ```bash
   uv run python scripts/build_docs_site.py
   ```

8. 先跑最小相關測試；如果 registry、docs、transport 或 generated artifacts 改變，再跑更廣的驗證。

`TOOLS_INDEX.md` 是 registry 的生成結果，不應手動維護。

目前 tool count 與 category count 的 source of truth 是 `uv run python scripts/count_mcp_tools.py --json`。不要在 docs 或 comments 手數工具。

## 新增 Source Connector

Source connector 必須待在 infrastructure boundary 後面。Provider-specific concerns 不應流進 MCP tool files。

建議流程：

1. 在 `infrastructure/sources/` 或對應 infrastructure package 加 provider client 或 adapter。
2. 任何穩定的跨來源概念，先在 domain/application 建模，再進 presentation。
3. Commercial 或 credentialed connectors 要用 explicit settings gate。
4. 依賴 licensed access 的 connector 預設保持 default-off。
5. CI 使用 mocked tests；live integration tests 保持 opt-in。
6. 更新 source contracts 與 user docs，說明 rate limits、rights expectations、optional keys 與 provenance behavior。

如果某 provider 沒 credential 會失敗或有授權限制，不要默默加進 `source="all"`。

## Search 與 Session 行為

`unified_search` 是公開文字文獻搜尋入口。`parse_pico`、`generate_search_queries` 與 `analyze_search_query` 等 query intelligence tools 協助 agent 在執行搜尋前規劃。

Session tools 的存在，是讓 follow-up actions 重用最新 result set。User docs 應鼓勵使用 `pmids="last"` 與 session reads，而不是讓模型靠對話記憶 PMID。任何影響 session IDs、cached article shape 或 follow-up semantics 的變更，都應包含多步驟 workflow tests。

## Export 與本機 Notes

Export layer 屬於 `application/export/`。Presentation tools 不應手動組 RIS、BibTeX、CSL JSON 或 Markdown note layouts。

邊界規則：

- `prepare_export` 負責 citation 與 dataset exports。
- `save_literature_notes` 負責 local note workflows。
- Local note defaults 使用 wiki-note semantics。
- Foam-compatible wikilinks、MedPaper-style layouts、CSL JSON 與 user templates 是 export profiles，不是 presentation-only behavior。
- 輸出目錄解析順序必須保持文件化：`output_dir`、`PUBMED_NOTES_DIR`、`PUBMED_WORKSPACE_DIR/references`、`PUBMED_DATA_DIR/references`、`~/.pubmed-search-mcp/references`。

Note export 行為改變時，要同步更新 user docs、generated docs、描述同一行為的 skills 或 packaged references，以及 tests。

## Pipeline Workflows

Pipeline behavior 是 application capability，不是 shell script feature。Canonical tutorials 位於：

- `docs/PIPELINE_MODE_TUTORIAL.en.md`
- `docs/PIPELINE_MODE_TUTORIAL.md`

`scripts/build_docs_site.py` 會另外同步到 `.claude/skills/pipeline-persistence/references/`，讓不讀 `docs/site-content/` 的 agent bundles 與 VSIX integrations 仍能取得教學。

Pipeline 變更需要同時考慮：

- schema compatibility
- validation errors
- execution history
- scheduling behavior
- docs site routing
- packaged tutorial copies

## Documentation System

![文件發布流程](images/docs-publishing-flow.svg)

Canonical Markdown sources 仍在 repo 裡。Static site 會 embed generated copies，讓 GitHub Pages 不需要 backend 也能服務文件。

生成流程：

```bash
uv run python scripts/count_mcp_tools.py --update-docs
uv run python scripts/build_docs_site.py
uv run python scripts/build_github_wiki.py --output build/github-wiki
```

Generated outputs：

- `src/pubmed_search/presentation/mcp_server/TOOLS_INDEX.md`
- `docs/site-content/*.md`
- `docs/site-content.js`
- 選定的 `.claude/skills/.../references/*.md` pipeline tutorial copies
- `build/github-wiki/*.md`，供 GitHub Wiki sync workflow 使用

新增 docs page 時：

1. 新增 canonical Markdown file。
2. 加到 `scripts/build_docs_site.py` 的 `PAGES`。
3. 在 `docs/site.js` 加對應 metadata。
4. 重建 site payload。
5. 執行 `uv run pytest tests/test_docs_site_sync.py -q`。

Docs site 的 language switch 是 client-side state。英文與繁中頁應在 `docs/site.js` 共用同一個 `group`，這樣切換語言時才能映射到對應翻譯。

GitHub Wiki 也由同一批 canonical docs 生成：`scripts/build_github_wiki.py` 會輸出 wiki-friendly Markdown，`.github/workflows/wiki.yml` 再推到獨立的 wiki repository。若新頁面也要出現在 Wiki，除了 docs site 的 `PAGES` 與 `docs/site.js` metadata，需要同步加入 wiki builder 的 `PAGES`。

## Validation

窄變更先跑最小有效檢查。整合面變更使用 repo baseline：

```bash
uv run pytest -q
uv run mypy src/ tests/
uv run python scripts/check_async_tests.py
```

常見 focused checks：

```bash
uv run python scripts/count_mcp_tools.py --json
uv run ruff check src/ tests/ scripts/ run_server.py run_copilot.py
uv run pytest tests/test_docs_site_sync.py -q
uv run python scripts/count_mcp_tools.py --update-docs
uv run python scripts/build_docs_site.py
uv run pubmed-search-mcp --help
uv run pubmed-browser-fetch-broker --help
```

當你改到 registry behavior、generated docs、public tool schemas、transport behavior、export behavior、session shape 或 shared infrastructure，就要跑完整 baseline。

`tests/test_docs_site_sync.py` 只能證明 generated site payloads 和 canonical Markdown sources 一致；它不證明 Markdown 裡的事實和 runtime behavior 一致。因此 registry 與 tool-surface 變更仍要跑 count script 與 focused behavior tests。

## GitHub Pages 部署

`Deploy Docs Site` workflow 會在 `main` 或 `master` 上，針對 docs、scripts、README、deployment docs、architecture docs 或 MCP server presentation files 變更時，重建 tool index 與 docs payload。

Live site 由 GitHub Pages 發布 `docs/` artifact。如果 deployed site 看起來過期：

1. 確認本機 generation 是乾淨的。
2. 確認變更的 source path 有包含在 `.github/workflows/pages.yml`。
3. 檢查最新 Pages workflow run。
4. 確認 `docs/site-content.js` 包含預期 slug。

## 常見錯誤

| 錯誤 | 更好的做法 |
| --- | --- |
| 把 workflow logic 寫進 MCP tool function | 新增 application service，讓 tool 保持 thin |
| 手動改 `TOOLS_INDEX.md` | 改 `tool_registry.py` 後重新生成 |
| 新增 docs source 但忘了 `PAGES` 或 `docs/site.js` | 同步加入兩個 metadata 位置，並跑 docs sync tests |
| 把 source 描述成永遠可用 | 說明 keys、rate limits、rights 與 default-off behavior |
| 加 browser fallback 但沒限制 host | 要求 token 與 `allowed_hosts` |
| 改 note output shape 卻不改 docs | 更新 user docs、generated docs、templates 與 tests |
| 把 Copilot simplified tools 當 primary surface | Primary behavior 應對齊 primary tool registry |

## Release Hygiene

發佈或推送 integration-heavy changes 前：

1. 重新生成 tool 與 docs payloads。
2. 執行 focused tests 與 repo validation baseline。
3. 檢查 `git status --short`，只 stage intentional files。
4. 確認需要 generation 的 source changes 有對應 generated files。
5. Push 後檢查 GitHub Actions，docs changed 時尤其要看 Pages workflow。
