# 專案翻新計畫與執行紀錄 — 2026-09-15

> 後續狀態：已依序完成[十階段核心審查](core_review_2026-09-15.md)，
> 涵蓋 `src/pubmed_search/` 的 2,901 個定義。以下保留本批次當時的數量、待辦與驗證紀錄，
> 不代表目前仍有核心項目待審；tests／scripts 的所有定義不在本次核心完成宣告內。

本輪已完成可驗證的第一批翻新：建立逐一定義清冊、修正重現的資料錯誤、
收斂全文取得流程，並執行本機效能與整合驗證。產品目標維持學術搜尋與證據整合。
**尚未完成全 repo 每個 class/function 的語意審查，也沒有新的公開檢索 benchmark 增益數字。**

基準為 Git HEAD `0a392851b8c404e4709f25a3ae5d2d77ceae66ed` 加上前一輪尚未提交的
[維護修正](maintenance_audit_2026-09-15.md)。本報告與修改均在工作樹，未發布新版。

## 計畫與完成條件

| 階段 | 執行結果 | 完成條件 |
| --- | --- | --- |
| 建立清冊 | 已完成 Python 定義列舉與雜湊；另列非 Python 範圍 | 不因隱藏路徑、巢狀函式或重複名稱漏算；解析失敗必須可見 |
| 修正實際故障 | 已修正快取、依賴注入、作者匯出與 DOI URL 錯誤 | 先重現失敗，再通過對應回歸案例 |
| 收斂重複責任 | 已合併全文 downloader 流程、artifact 共用資料及作者排序 | 維持 tool contract、policy、自訂設定與輸出格式 |
| 校正量測工具 | 已修正 CLI 根節點辨識、無效量測、空 benchmark 成功與快取假命中 | 七組實際量測完成；刻意製造 miss 會失敗 |
| 本機整合驗證 | 結果見下方驗證紀錄 | 完整 gate 與 smoke 均通過；不靠上傳後才找錯 |
| 全量語意審查 | **進行中，未完成** | 指定範圍所有定義有有效審查證據，無 pending、follow_up、stale 或 orphan |

## 到底有多少 class/function？

清冊從 `git ls-files --cached --others --exclude-standard -z` 取得檔案，
涵蓋已追蹤及未忽略的新檔案，包含隱藏目錄。以 AST 解析而不 import 專案程式。

| 範圍 | Python 檔案 | class | function 總數 | 其中 method | 其中巢狀 function | 其中 async |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `src/` | 222 | 456 | 2,432 | 1,336 | 171 | 474 |
| `tests/` | 208 | 837 | 4,845 | 3,629 | 284 | 2,965 |
| `scripts/` | 35 | 18 | 305 | 19 | 17 | 10 |
| 根目錄 | 3 | 0 | 6 | 0 | 0 | 1 |
| **總計** | **468** | **1,311** | **7,588** | **4,984** | **472** | **3,450** |

共有 **8,899 個 Python 定義**，解析失敗為 0。method、巢狀及 async 都是 function
總數的子集合，不能重複相加。每個 `def` 定義計一次，包含 property getter/setter
及巢狀 tool；不包含 lambda、動態產生的函式或 dataclass 自動產生的方法。
pytest 參數化案例數與 function 數量是不同指標。

另外列出 **24 個非 Python 程式檔**：2 個 JS、1 個 MJS、13 個 shell、8 個 PowerShell。
目前清冊沒有解析這些語言的函式，也不宣稱已完成它們的全量語意審查。
清冊副檔名範圍為 `.py/.pyi/.js/.mjs/.ts/.tsx/.sh/.ps1`；HTML/Markdown
內嵌程式與外部套件不在定義計數範圍內。

本輪[審查帳本](code_review_ledger.json)記錄 **38 個逐項判斷**：34 個 reviewed、
4 個 follow_up；另外 8,861 個定義仍為 pending。其中 `src/` 是 16 個 reviewed、
4 個 follow_up、2,868 個 pending。前一輪的測試／稽核結果沒有自動升級成逐一定義審查。

```bash
uv run python scripts/perf/symbol_inventory.py
uv run python scripts/perf/symbol_inventory.py --require-reviewed src/
```

第一個命令更新被 Git 忽略的 `scripts/_tmp/review/symbols.json`。
第二個是明確的完成斷言，**現在應該失敗**。檔案 SHA-256 改變會讓審查變成
`stale_review`；刪除或改名的定義留下 orphan，空範圍也不能成功。
一般 pre-push 只要求清冊可生成且沒有解析缺口，尚不要求全量審查完成。
帳本是有證據連結的自我審查紀錄，不是獨立 reviewer 的批准，也不自動證明相依模組正確。

## 實際修正

| 問題 | 修改 | 驗證方式 |
| --- | --- | --- |
| 快取寫入整數年份、空 DOI/摘要或結構化作者後，被自己的反序列化拒絕 | 在寫入端產生 canonical envelope，保留原始 `full_data` 與嚴格讀取驗證 | 記憶體／磁碟重新開啟 × 三種作者形態，6 個先失敗後成功案例 |
| 注入的空 `ArticleCache` 因 `__len__` 為 0，被 `or` 表達式換掉 | 改成明確的 `is not None` | 經 SessionManager 寫入，從原本共享 cache 確實讀得到 |
| RIS/BibTeX 遇到空白作者崩潰，單一作者字串被逐字拆開 | 正規化作者容器與空白，合併姓名排序 helper | 兩種格式 × 三種作者輸入，6 個先失敗後成功案例 |
| 畸形 DOI URL 的 IPv6／port 解析拋出未處理 ValueError | 轉成既有 IdentifierValidationError | 嚴格 parser 拒絕；`try_normalize_doi` 回傳 None，2 個先失敗後成功案例 |
| MCP 的 PDF fallback 重做 application service 已有的下載、來源狀態與清理流程 | 單一 `_collect_download` 處理 standard／extended，policy 可停用 fallback | 驗證只呼叫一次 downloader、來源狀態、browser-session 輸出、cleanup 失敗仍保留全文 |
| 結構化與 Markdown artifact 重複維護 provenance／summary／metadata | 共用同一批資料，再由格式分支決定 artifact 檔案 | 既有 artifact、全文、實際 MCP protocol 驗證 |
| import audit 把 HTTP CLI 誤列成只有測試引用 | 納入 `pyproject.toml` console/gui entrypoints | HTTP CLI 被辨識為 runtime root |
| 無效 timing、未知 target 或快取 miss 仍可能得到成功效能報告 | 拒絕無效樣本與未知 target；每次 cache timing 要求全部命中 | 錯誤輸入與故意 miss 回歸；實際執行七組量測 |

`get_fulltext` 的 AST 定義跨度由 **544 → 410 行**，Ruff C901 由 **47 → 29**。
這是單一函式的局部改善；合併後的 service 承擔必要分支，不宣稱全 repo 複雜度同步下降。
MCP 公開工具仍為 **41 個**。直接呼叫 FulltextService 的消費端也取得一致的最後 fallback；
自訂 policy 可省略 `pdf_retrieval_fallback` 以停用。沒有改寫使用者的 harness 安裝內容。

## 全 repo 掃描與下一批整理順序

import audit 涵蓋 222 個 source module：34 個 root/package、182 個 runtime referenced、
3 個僅被測試與腳本引用、1 個 scripts-only、2 個 tests-only。這是靜態入邊分類，
不等於完整動態可達性或刪除許可。

1. `session/manager.py`：`warm_article_cache` 與 `add_to_cache` 的流程相近，
   但事件名稱與存檔語意不同；先保護事件／重放契約，再抽出共用操作。
2. `unified_formatting.py`、`application/unified/execution.py` 與 `pipeline/executor.py`：
   依輸出、查詢執行與 persistence 責任拆分；避免只為減少函式行數增加轉呼叫層。
3. `FulltextService._resolve_identifiers` 有無效的重複條件；
   `_format_core_fulltext` 建立的 section 註記未進入回傳值。
   先確認 section 的 API 意圖，再以實際輸出契約修正。
4. `clinicalkey_ai.py`、`semantic_scholar_datasets.py` 目前僅有測試的靜態引用；
   先確認文件／外部 import／預定整合用途，才決定接線、隔離或移除。
   評測模組由 scripts 使用是合理用途，不能因沒有 product 入邊而刪掉。
5. HTTP reader、provider DOI helper 與 lazy package export 有相似程式碼，
   但解碼、安全、接受字元及套件邊界不同；不能把 AST 相同當成語意相同。
6. 24 個非 Python 程式檔需要另外的函式清冊與審查證據，才可宣稱全語言完成。

現有 Ruff C901／分支／statement／return 掃描有 261 條診斷，是候選清單，不是 bug 數；
同一函式可能有多條診斷，registrar 的巢狀定義也會影響數字。
`scripts/_tmp/review/ruff_complexity.json` 與 `imports.json` 保存本次本機掃描。

## 本機量測與驗證

七組固定合成輸入量測已執行；以下是本機最大 N 的單次報告中位耗時，
用於尋找異常，不作跨機器、產品檢索品質或嚴格 Big-O 的證明。

| 目標 | 最大 N | 耗時 |
| --- | ---: | ---: |
| aggregate_deduplicate | 800 | 2.060 ms |
| rank_articles | 800 | 29.901 ms |
| format_unified_results | 400 | 31.129 ms |
| pipeline_filter | 8,000 | 2.191 ms |
| article_to_dict | 800 | 1.616 ms |
| export_ris | 800 | 3.610 ms |
| session_cache_lookup | 800 | 10.856 ms |

量測資料位於 `scripts/_tmp/review/complexity_timings.json`，可重新執行：

```bash
uv run python scripts/perf/complexity_scan.py --json-output scripts/_tmp/review/complexity_timings.json --markdown-output scripts/_tmp/review/complexity_timings.md
uv run --frozen python scripts/check_repo.py full
uv run --frozen python scripts/check_repo.py smoke
```

- **Full gate：4,576 passed、23 skipped、30 deselected，pytest 104.16 秒。**
  Ruff、467 檔格式檢查、async audit、468 檔 Python AST 清冊、430 檔 mypy 全部通過。
  另外對三個 perf 稽核腳本執行 mypy 也通過。
- **Smoke：165 passed，13.09 秒。** 使用與一般雲端 CI 相同的命令。
  完整與 smoke 都包含 41 工具的實際 stdio／Streamable HTTP／fresh-wheel acceptance。
- DDD、Bandit、deptry、vulture、instruction/skill/hook consistency 與 diff whitespace 檢查通過。
  已有的 hook 版本提示及 suppression 提示不等於掃描失敗。
- `--require-reviewed src/` 實際回傳 exit 1，符合仍有待審定義的狀態；
  清冊回歸另驗證檔案變動使審查失效、刪除定義留下 orphan、空範圍不能成功。
- 七組效能量測成功完成，修正後紀錄沒有 `Discarded invalid article-cache entry`。
  故意讓 cache lookup 回傳 misses 的案例確認量測會拒絕產出假成功。
- README、翻新紀錄、全文架構文件、CONTRIBUTING、CHANGELOG 與 MEM 已更新，
  網站內容已重新生成。MCP registry／工具文件同步確認 41 工具、16 類別，無數量漂移。
- 本輪沒有 Docker／Windows／macOS／live provider 實測，也沒有重做前一輪的
  121 個 SVG render；圖形產生程式未在本輪修改。不能以本機 Python 成功代替這些檢查。

驗證時的程式清冊 snapshot SHA-256：
`e738455d8447d913430f7ba8034fc2ade00e14df1b5bb918125f783bb7ec07b6`。
之後的程式修改需重新驗證，不能沿用這份成功紀錄。

沿用前一輪本機優先策略：完整測試在 pre-push 執行，一般雲端只跑獨立 smoke，
跨平台／container／Mermaid 完整 CI 採 opt-in；發布 gate 保留獨立驗證。
本輪不啟動 5,000 題模型長跑、不呼叫付費模型或 live 文獻 provider。
新的修正可證明已重現故障的改善，尚不能換算為 MCP 相對原生搜尋的 recall/nDCG 增益。
