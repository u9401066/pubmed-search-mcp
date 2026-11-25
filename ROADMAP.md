# Research roadmap / 研究路線

## Available in v0.11.0

Saved pipelines now serve systematic reviews end to end on the PubMed side: complete retrieval of the result set, PRISMA-S run records with the executed query and translation, RIS/CSV/CSL-JSON export, concept-block contribution analysis and a screening log with PRISMA 2020 counts. `unified_search` is precision-first and corrects MeSH headings PubMed cannot resolve, with disclosure. Next: an "other methods" PRISMA branch, grouping reports into studies, and AND-preserving broadening for expert queries.

## Available in v0.10.0

The plugin can compare bounded PubMed concept combinations and open the evidence behind a difference. A tenant-owned research workspace links decisions, evidence and outstanding reading across sessions. The four-review MeSH pilot and its frozen decisions accompany v0.10.0. [Capability inventory](docs/README.md#capability-inventory) · [Release history](CHANGELOG.md)

## Agent plugin delivery plan

2026-11-20 五輪研究目標。第一組宿主選定 **VS Code Copilot 與 Codex**。前一位研究者為什麼選這條檢索式？下一位打開全新對話，多久能找到還沒讀完的那篇原文？

### 分支上已能重用的東西

| 入口 | 目前可驗證的行為 | 下一步從哪裡接 |
| --- | --- | --- |
| Plugin 打包 | 產生器選入 12 個研究技能與 MCP 啟動設定。發行設定啟動 v0.11.0，開發設定啟動 checkout。 | 先讀已連線 server 的工具與輸入 schema，分清正式版與分支能力。[產生器](scripts/build_agent_plugin.py) · [重啟與安裝測試](tests/test_agent_plugin_package.py) |
| 可執行的技能腳本 | 隨包的 `render_handoff.py` 可在離線環境把一頁 workspace JSON 轉成人可讀的交接，包含頁面缺口。 | 同一份受租戶保護的資料可供 agent、命令列與閱覽頁使用。[腳本正本](.claude/skills/pubmed-research-workspace/scripts/render_handoff.py) · [交接測試](tests/test_workspace_handoff_export.py) |
| Copilot 工作區 hooks | 此 repo 的 Bash／PowerShell wrapper 已處理 session 開始、提問、工具前後及 session 結束。部分路徑相對於 checkout，目前這些 hook 隨工作區載入。 | 先選一個事件移植到安裝包，測安裝目錄、一般專案工作目錄與兩套 hook 同時存在時的行為。[現有 hook 合約](docs/development/COPILOT_HOOKS_PIPELINE_ENFORCEMENT.md) |
| 研究服務 | MeSH 差集、workspace 分頁、未完成行動、Chronicle 修訂與來源定位都有既有入口。 | 排序、預算、授權、資料寫入與重試語意繼續由 application service 負責。宿主轉接程式只轉換事件和呈現回覆。[組合預查](src/pubmed_search/application/search/query_comparison.py) · [Workspace](src/pubmed_search/application/research_workspace.py) · [來源接手](src/pubmed_search/application/workspace_handoff.py) |

### 官方規格和實作案例帶來的設計決定

| 讀過的規格或案例 | 本專案採用的做法 |
| --- | --- |
| Agent Plugins 1.0 定義根目錄 manifest、skills、MCP 設定與客戶端擴充命名空間。技能可攜帶腳本，執行取決於宿主環境。[規格與套件結構](https://agent-plugins.org/) · [客戶端擴充](https://agent-plugins.org/plugin-authors/client-extensions) | 保留一份可攜核心。沒有執行本機腳本能力的客戶端，仍能以 MCP 讀同一頁交接資料。 |
| VS Code 將 plugin hooks 放在 `com.github.copilot/`，提供 plugin 相對路徑與可由使用者啟用的 automation template。工作區 hook 和 plugin hook 可能同時觸發。[VS Code 作者指南](https://code.visualstudio.com/docs/agents/reference/agent-plugin-reference) | Copilot 選為第一個封裝 hook 的宿主。測試同一事件重送與重複載入，並確認使用者安裝目錄可包含空白。 |
| Codex 可用根 manifest 的 `extensions.com.openai` 宣告 hooks；桌面本機腳本須存在於執行環境，且 hook 定義需受信任。[OpenAI 打包說明](https://developers.openai.com/plugins/build/plugins) | Codex 的第一條接手路徑由使用者明確啟動技能。同一案例再測手動安裝且已信任的桌面 hook，記錄兩種模式各省下的步驟。 |
| Anthropic 的 Explanatory Output Style 在 `SessionStart` 呼叫隨包腳本，將少量上下文交還宿主。[Hook manifest](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/explanatory-output-style/hooks/hooks.json) · [腳本](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/explanatory-output-style/hooks-handlers/session-start.sh) | 借用「事件 → 短提示」的結構。有綁定的研究才提示一個可接續動作，全文與歷次查詢留給點讀。Claude Code 原生轉接器排在首輪試用後。 |
| Anthropic 的 Bio Research 依「文獻檢索」與「期刊存取」等工作分配 connector；Data Analyst 同時提供連線資料源與讀取使用者匯出檔的操作方式。[Bio Research connector 對照](https://github.com/anthropics/knowledge-work-plugins/blob/main/bio-research/CONNECTORS.md) · [Data Analyst 使用案例](https://github.com/anthropics/knowledge-work-plugins/blob/main/data/README.md) | Zotero Keeper 是可選的館藏查詢端。按實際權限列可用來源；缺少連線時可讀獲授權的匯出清單，保留待查的 PMID／DOI 和證據層級。 |

### 分輪交付與驗收

以下是擬議增量與試驗目標。第一輪使用分支 launcher；受控測試與人工操作的宿主驗收分開記錄。第 1 輪確立來源與交接格式後，檢索預查和館藏比對可各自試驗。週報的自動投遞另依賴第 5 輪的執行與重試紀錄。

| 輪次 | 交付 | 可決定是否進入下一階段的驗收 |
| --- | --- | --- |
| 1．雙宿主接手 | 兩端明確選取同一 workspace。Copilot 將讀過的 PMID、證據層級及未完成行動存入服務。先走顯式技能，再加一個 Copilot 啟動提示。Codex 用同一服務身分在新對話讀回。 | 在兩個實際宿主互換角色。分別測啟用／停用 hook、未綁定 workspace、不同租戶、v0.9.0。相同身分取回同一 record ID；只讀摘要的紀錄在兩端仍是摘要。恢復交接本身對文獻供應端發出 0 個請求。 |
| 2．檢索策略審閱 | 將既有 MeSH 比較、選定策略與決策理由連起來。提供隨包的離線報表腳本，從匯出的 `plan.json` 與所選差集產生可引用的比較表；保留原式、時間及供應端警告。 | 人工耳蝸固定樣本應重現 12／+10／+190，重排區塊不改結果。超時顯示未知。另以至少三個回顧主題盲留合格 PMID，比較有無預查的找回率、每多找回一篇所需篩選量、API 呼叫及 agent 輸入量。已揭露給 agent 的種子另計。[既有範例](docs/guides/TOOLS_USAGE_GUIDE.zh-TW.md#比較-pubmed-概念組合) |
| 3．Chronicle 審閱與週報 | 將相鄰修訂投影成可離線閱讀的時間表。每一筆保留原文年份、首次觀察修訂、候選分歧理由、相反解讀及待查原文。可選週報從同一份修訂差異挑最多三筆。 | 兩篇舊文因補標首次相連，完整年表保留兩篇與新關係，週報可列為「新辨認的關聯」。相同修訂重跑不重送。領域讀者分別評估辨認歷史分歧與辨認新進展的結果。[歷史案例](docs/reports/chronicle_historical_method_2026-11-20.md) |
| 4．全文與 EBM 證據表 | 為已選篇目產生待查清單。宿主可使用已授權的 Zotero Keeper，以 PMID／DOI 比對館藏並帶回本地定位；離線審閱表可輸出 CSV，記錄實際讀到的摘要、段落、頁碼或表格。 | 用只有摘要、有合法本地全文、相同標題不同 DOI、館藏未連線四種案例驗收。只有實際讀到的段落可登記全文級證據；從表格能回到原始紀錄。偏差風險、GRADE 與適格性由評讀者填寫。 |
| 5．多人服務與排程 | 以服務端已保存的 pipeline 與 scheduler 為基礎；桌面 automation 供人選取追蹤主題。一次排程交由一個執行者，服務端保留工作狀態與可恢復的結果。 | 用 3–5 處部署、每處 100–300 名註冊者作規劃基準，先量實際尖峰併發。測兩個桌面同時要求同一工作、斷線、429、跨租戶與備份還原，報告重複執行、尾端延遲、供應端花費及還原時間。[服務合約](DEPLOYMENT.md) |

第 2 至 4 輪也適合提供一個可選的「第二位評讀者」角色。由宿主提供受限的讀取工具，先只交給它凍結的檢索計畫、年代與來源定位，請它獨立記下可能漏檢的對象或另一種歷史解讀，再與第一位的筆記對照。比較兩份判讀時保留歧見與原文定位。沒有自訂 agent 功能的客戶端可用同一份評讀說明開新對話。能否提升判讀品質須以盲評案例驗證。[VS Code 自訂 agent 與 plugin 結構](https://code.visualstudio.com/docs/agents/reference/agent-plugin-reference)

Chronicle 也可以讓研究者直接對著史料修訂判讀。先從同一份 revision 匯出可搜尋的靜態 HTML，比對兩篇原文年份、段落與不同解讀；之後可在支援的 VS Code Copilot session 試用互動式 Canvas。研究者選取某一筆並提交註解時，透過既有 workspace 服務附上 record ID、來源與人工署名。驗收看另一端的 Codex 能否讀回同一則註解，以及離線閱覽頁是否清楚標示快照版本。[VS Code plugin 視覺介面與限制](https://code.visualstudio.com/docs/agent-customization/agent-plugins)

### 第一個可合併的切片

1. **打包與綁定。** 在既有產生器明列 Copilot 擴充檔，先打進 development plugin。從安裝包外的空目錄啟動。操作者選定服務連線與 workspace ID 後，宿主只保存該連線的選擇；共用研究紀錄保存在已驗證租戶的服務。另保留清除選擇的操作。[打包與安裝位置](scripts/build_agent_plugin.py)
2. **事件與回覆。** 第一個事件只處理 session 開始。已選案時提示 agent 用既有的 `research_workspace(request={"action":"read","workspace_id":"implant-history","limit":1})` 檢查選定工作區（此處以人工耳蝸案例為例）；未選案時安靜返回。資料頁以一筆未完成行動、來源 ID、證據層級及分頁指標供點讀。研究者或 agent 明確選擇才執行預查、開啟來源或寫入決策。
3. **兩端實測。** Copilot 留下 PMID 3878092 的摘要紀錄及「查原文裝置選擇條件」。關閉對話，在 Codex 以相同服務身分接手，再交換兩端重測。比較手動貼交接、顯式技能、顯式技能加 hook 三種條件；記錄宿主版本、模式、首個正確下一步所需時間、工具呼叫、重複提示與輸入量。
4. **採用門檻。** 提議先測五組配對交接。五組均須還原正確紀錄、保留原證據層級且無跨租戶資料。每次開案最多一則提示，提示以 1 KiB UTF-8 為試驗上限，另記宿主可提供的實際 token 數。若加 hook 對接手時間沒有可觀察的改善，先交付顯式技能與腳本，留下實測數據再決定是否預設提示。

### 五輪交付追蹤

本次正式版優先交付第 2 輪。手動與技能交接仍需在兩個真實宿主計時。第 3 與第 4 輪共用研究工作區的證據定位，第 5 輪另驗證多租戶負載。每輪保留宿主版本、輸入、決策紀錄和失敗案例，供團隊決定是否採用。

| 輪次 | 驗收狀態與下一份證據 |
| --- | --- |
| 1．Copilot ↔ Codex | 待真機雙向交接。比較手動、skill、skill 加啟動 hook 三組的時間、提示大小及恢復時的供應端請求數。 |
| 2．MeSH | [四題盲測與離線審閱表](docs/reports/mesh-preflight-2017/README.md) 已交付。下一次用新回顧獨立驗證詞彙修正提示。 |
| 3．Chronicle | 待領域讀者從完整年表與三則週報追查同一組分歧、原始年份、後補關聯及相反解讀。 |
| 4．全文與 EBM | 待驗證只有摘要、本地全文、同名異 DOI 與館藏離線時，兩個宿主都能辨識證據層級及缺件。 |
| 5．多人服務 | 待量測 3–5 處部署、每處 100–300 位註冊者下的實際尖峰併發、工作去重、限流與還原。 |

## Questions for the next evaluation

| Question | Evidence needed |
| --- | --- |
| Do search previews recover eligible studies at an acceptable screening cost? | Freeze eligible reference studies before tuning terms. Compare recovered studies, screening burden and provider calls on multiple review topics. |
| Can Chronicle identify an important historical fork? | Have independent readers mark forks, earlier alternatives and milestones. Evaluate recovered historical links separately from newly published studies. |
| Can another agent resume a review? | Measure time to recover the chosen search, excluded alternatives, source access and next unfinished reading across two plugin hosts. |
| Can one organizational deployment serve its intended users? | Exercise concurrent tenants, provider outages, restart and backup restoration under a measured workload. Record latency and isolation failures. |

These are evaluation questions. The [methods protocol](docs/publication/evaluation-protocol.md) and [renovation review](docs/reports/renovation_review_2026-11-20.md) record the starting evidence. Earlier phases, proposed extensions, candidate retirements and tool names are preserved in the [roadmap through v0.9.0](docs/archive/research/roadmap-through-v090.md).
