<!-- Generated from docs/REPOSITORY_RELIABILITY_AUDIT.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# Repository 改進與驗證紀錄

日期：2026-09-09。對照原版：`dbcf0c88c76e6fac30877ff16a9850232e89bd4e`。

## v0.7.2 發布整合

下方原始稽核是在同步遠端前，以舊工作區取得的歷史紀錄。準備發布時發現遠端已更新
至 v0.7.1，故修正已重新整合到 `7d8e5b6` 的嚴格合約：目前為 **41 個 MCP 工具**，
保留 typed search pages、server-scoped container、`source_unavailable` 狀態與
不合法 provider batch 的拒絕行為。沒有恢復舊工具別名或寬鬆參數。

現行回歸案例已適配這些合約。原始 22 案例／19 個失敗與原始 source/test fingerprints
仍保留在歷史 JSON；不能把它們當成對 v0.7.1 的直接比較。以下 4,240 個通過等數字
也是整合前的稽核結果。

本版整合後的本機發布驗證（Python 3.10）：

- 完整 `uv run pytest -q`：**4,562 通過、53 跳過**，101.73 秒。
  包含 41 個工具的 source stdio、Streamable HTTP 與 fresh-wheel MCP acceptance。
- Ruff lint／461 個檔案格式檢查、mypy **426 個檔案**、async、DDD、skill、
  Bandit 中高嚴重度、deptry 與 vulture 檢查通過。
- wheel 與 sdist 建置成功；README、網站與 Wiki 同步測試通過。
- Playwright 在桌面 1440×1000 與手機 390×844 驗證新增頁面、導覽篩選、
  全站搜尋、繁中切換與手機選單；沒有 console error 或手機橫向溢出。
- 53 個既有 skip 包含 36 個外部 API／運行中 server 條件、13 個 PowerShell
  環境條件與 4 個舊 API 測試；沒有為本次修正放寬測試。
  本機沒有 Docker，容器 smoke test 由既有 PR／release CI 執行。

## 原始稽核範圍

本輪針對搜尋、選文所依賴的文獻識別、引用驗證、全文存取、快取並行與評測可重現性
檢查並修正可重現的缺陷。既有 MCP、pipeline、session、export、source contract
由全庫測試覆蓋。這次原始稽核沒有新增 MCP 工具或變更公開參數，當時工作區為 45 個工具。

## 修正與影響

| 範圍 | 原本問題 | 修改後行為 |
| --- | --- | --- |
| 引用驗證 | DOI 相符可覆蓋書目衝突；期刊、年份等欄位加分也可能讓錯誤 DOI 的候選勝出 | DOI 解析只接受正規化後相同的 DOI。提供的欄位衝突或無法確認時保留 `partial_match`，不回報 `verified` |
| PMID 證據 | 取回傳清單第一筆，未核對 PMID | 核對 cache 與回傳紀錄的 PMID；不將其他文章掛到這筆引用 |
| 引用解析 | 單獨的 `PMID:` 被當成作者，DOI 內的年份被當成出版年 | 識別碼與書目分開解析，識別碼本身不產生作者、期刊或出版年 |
| 引用批次容錯 | 個別 PMID／ECitMatch 查詢拋例外時，中斷整份報告 | 保留成功列，失敗列提供重試說明；API 不可用不代表文獻不存在 |
| 跨來源去重 | DOI 前綴組合、PMID 空白、現代 PMC 網址的表示不同，造成 identity 與合併判定不一致 | 共用正規化邏輯；`DOI: https://doi.org/...`、PMC 網址與識別碼可正確對應 |
| 空識別碼 | `doi:` 被當成共同 DOI，合併無關文章；也會阻擋標題備援去重 | 忽略正規化後的空識別碼，避免錯誤合併並保留標題備援 |
| 快取並行 | 所有不同 key 共用一個鎖；跨 event loop 使用也可能失敗 | 相同正規化 key 在同一 loop 共用抓取鎖，不同 key 可並行；取消後可重試，閒置鎖不累積 |
| 全文容錯 | 延伸來源初始化或關閉失敗，會丟掉先前成功取得的全文 | 保留成功來源內容與來源標示，記錄延伸來源錯誤 |
| 章節篩選 | `results, ` 的空項目匹配所有章節；無標題也會誤中 | 忽略空項目，具名篩選只匹配有標題的章節 |

搜尋排序先前完成的 BM25、RRF 與 pipeline 查詢相關性修正，繼續保留並通過回歸測試。
其公開資料結果與完整 Agent 評測設計見 [benchmark 紀錄](#/academic-retrieval-benchmarks)。

`verified` 是書目一致性判定，尚未評估論文是否支持某個論述。引用語境、立場與
選文召回率仍需各自的公開標註及 Agent 實驗，不能從這些修正推算得分。

## 兩輪重現與修正

先寫入可失敗的測試，再修改 production code。第一輪 18 個案例中有 15 個失敗，
涵蓋引用、去重、快取與全文；第二輪補充識別碼解析、批次容錯與跨 event loop
使用。最後將同一份 22 個案例實際載入原版 source 再比較：

| 相同 regression suite | 原版 | 改版 |
| --- | ---: | ---: |
| 通過 | 3 | 22 |
| 失敗 | 19 | 0 |

這是針對已發現缺陷建立的開發回歸集合，**不是公開 benchmark，也不是研究品質
提高 19/22 的證據**。它能確認修正前後行為差異；快取測試確認獨立抓取能重疊執行，
沒有推論真實 PubMed API 的延遲改善比例。

整合後版本可重跑下列檢查，結果不應直接覆寫歷史 JSON：

```bash
uv run pytest -q tests/test_research_reliability.py
uv run pytest -q
uv run mypy src/ tests/
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check_async_tests.py
uv run python scripts/hooks/check_ddd_layers.py
uv run python scripts/check_cline_skills.py
uv run bandit -r src/ -c pyproject.toml -ll --quiet
uv run deptry src/
uv run vulture src/ scripts/ vulture_whitelist.py --min-confidence 80
```

原始 regression 對照曾使用先前評測保存的 source archive，並核對 import 位置。
重現該次數字時，必須同時使用歷史 JSON 中記錄的 source 與 test fingerprints；
目前 tests 已適配 v0.7.1 的 typed source 合約，不能直接套回舊版當成相同實驗。

## 完整驗證與限制

- 完整 `uv run pytest -q`：**4,240 通過、37 跳過、1 失敗**，205.84 秒。
- 唯一失敗：`test_fulltext_urls.py::TestURLFormats::test_europe_pmc_pdf_url`，
  外部 Europe PMC PDF 網址回傳 HTTP 520。該測試與原版 commit 逐位元相同；
  在原版環境重跑同樣失敗。沒有改斷言或增加 skip 來隱藏失敗。
- 全庫執行開始後另補跨 event loop 測試；最後的引用／可靠性／文件同步 focused
  suite **65 通過**，其中可靠性集合 **22 通過**。
- 型別檢查 **394 個檔案通過**；Ruff lint、429 個檔案格式檢查、async、DDD、
  skill、Bandit 中高嚴重度、既定 deptry 指令與 vulture 檢查通過。
- 中英文使用說明與 generated docs site 同步；既有 benchmark 與工作區修改保留。

機器可讀的 source／test fingerprints、逐案例原版與改版狀態及測試摘要，見
[audit JSON](reports/repository_reliability_audit_2026-09-09.json)。

## 完整 Agent 評測狀態

上述整合及版本更新會改變 lockfile／evaluator fingerprint，因此發布版已另建
prepare-only manifest 並通過續跑驗證，見
[v0.7.2 preflight](reports/papersearchqa_v072_preflight_2026-09-09.json)。
既有未開始的實驗目錄保持原樣，不以新版檔案覆寫舊協定。

原版 A/B 的 5,000 題 manifest 重新以 `--resume --prepare-only` 驗證成功。
仍為 **prepared、0 次執行**；沒有啟動模型長跑或消耗該長跑額度。
原版 B 的 source hash 與 manifest 均保持原樣，這輪產品修改沒有污染原版對照。

目前已能證明上述缺陷修復，尚不能宣稱「整套 MCP 比原生 Codex 提高多少」。
後續要量測原生 A、原版 B、改版 C 的產品效果，應固定 C 的 source／skills 快照，
使用相同資料與預算另建實驗，並按題目配對比較；不把 C 覆寫進既有 B 的 manifest。
