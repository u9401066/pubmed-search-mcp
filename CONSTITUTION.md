# 專案憲法 (Project Constitution)

本文件定義專案的最高原則，所有 Skills、Agents 和程式碼必須遵守。

---

## 第一章：架構原則

### 第 1 條：DDD 領域驅動設計
1. 專案採用 Domain-Driven Design 架構
2. 核心領域邏輯與基礎設施分離
3. 使用 Ubiquitous Language（統一語言）

### 第 2 條：DAL 資料存取層獨立
1. Data Access Layer 必須獨立於業務邏輯
2. Repository Pattern 為唯一資料存取方式
3. 禁止在 Domain Layer 直接操作資料庫

### 第 3 條：分層架構
```
├── Domain/          # 核心領域（純業務邏輯，無外部依賴）
├── Application/     # 應用層（用例、服務編排）
├── Infrastructure/  # 基礎設施（DAL、外部服務）
└── Presentation/    # 呈現層（API、UI）
```

---

## 第二章：Memory Bank 原則

### 第 4 條：操作綁定
1. 每次重要操作必須同步更新 Memory Bank
2. Memory Bank 是專案的「長期記憶」
3. 優先更新順序：progress > activeContext > decisionLog

> 💡 **名言：「想要寫文件的時候，就更新 Memory Bank 吧！」**
> 
> 不要另開文件寫筆記，直接寫進 Memory Bank，讓知識留在專案內。

### 第 5 條：更新時機
| 操作類型 | 必須更新 |
|----------|----------|
| 完成功能 | progress.md (Done) |
| 開始任務 | progress.md (Doing), activeContext.md |
| 重大決策 | decisionLog.md |
| 架構變更 | architect.md, systemPatterns.md |

---

## 第三章：文檔原則

### 第 6 條：文檔優先
1. 程式碼是文檔的「編譯產物」
2. 修改程式碼前先更新規格文檔
3. README 是專案的「門面」，必須保持最新

### 第 7 條：Changelog 規範
1. 遵循 Keep a Changelog 格式
2. 語義化版本號
3. 每次 commit 前檢查是否需要更新

---

## 第三點五章：開發哲學

### 第 7.1 條：測試即文檔
1. 測試程式碼是最好的使用範例
2. 零散測試也是測試，寫進 `tests/` 資料夾
3. 不要在 REPL 或 notebook 中測試後就丟棄

> 💡 **名言：「想要零散測試的時候，就寫測試檔案進 tests/ 資料夾吧！」**
>
> 今天的零散測試，就是明天的回歸測試。

### 第 7.1.1 條：檔案衛生原則 (File Hygiene)

1. **專案根目錄禁止放臨時檔案**：`.txt`、`.log`、`.tmp`、`.bak` 等臨時產出物不得出現在專案根目錄
2. **臨時腳本禁止放在 `scripts/`**：除非是長期使用的工具腳本，否則不得放入 `scripts/` 目錄
3. **測試結果一律用 stdout 檢視**：不要將 pytest 輸出導向檔案再讀取，直接用終端機看
4. **若真需要臨時檔案**：放在 `scripts/_tmp/`（已被 `.gitignore` 排除），且用完即刪
5. **AI Agent 產生的修復腳本**：執行後立即刪除，不得殘留

> 💡 **名言：「根目錄是專案的門面，不是垃圾桶」**
>
> 每個出現在根目錄的檔案都應該有存在的理由。若它不值得被 git track，它就不值得在那裡。

#### 允許存在於根目錄的檔案

- 設定檔：`pyproject.toml`, `Dockerfile`, `docker-compose*.yml`, `.gitignore`, `uv.lock`
- 文檔：`README.md`, `CHANGELOG.md`, `CONSTITUTION.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `CONTRIBUTING.md`, `DEPLOYMENT.md`, `LICENSE`
- 入口點：`run_copilot.py`, `run_server.py`, `start.sh`

#### 禁止存在於根目錄的檔案

- ❌ 任何 `*.txt` 臨時輸出（`test_results.txt`, `full_test_result.txt` 等）
- ❌ 任何 `*.log` 日誌檔（已被 `.gitignore` 排除）
- ❌ 任何 `fix_*.py`、`auto_*.py` 等一次性修復腳本

### 第 7.2 條：環境即程式碼
1. 虛擬環境配置必須可重現
2. 依賴必須明確版本鎖定
3. 環境設定納入版本控制

### 第 7.3 條：主動重構原則
1. **持續重構**：程式碼應隨時保持可重構狀態
2. **單一職責**：一個模組/類別/函數只做一件事
3. **適時拆分**：當檔案/函數過長時必須拆分
4. **架構守護**：重構時必須維持 DDD 分層架構

> 💡 **名言：「重構不是改天換地，而是持續的小步快跑」**
>
> 每次提交都應該比上次更乾淨。

### 第 7.4 條：避免 Hardcode 原則 (Agent vs MCP 職責)
1. **MCP 是工具提供者，Agent 是決策者**
2. **不要在 MCP 中 hardcode Agent 能做的事**：
   - ❌ 翻譯字典 (Agent 有 LLM 翻譯能力)
   - ❌ 模式選擇邏輯 (Agent 理解用戶意圖)
   - ❌ 複雜業務規則 (應由 Agent 判斷)
3. **MCP 應該做的事**：
   - ✅ API 呼叫與封裝
   - ✅ 錯誤偵測與警告
   - ✅ 資料格式轉換
   - ✅ 提供選項讓 Agent 決策
4. **錯誤處理應指導 Agent 下一步**，而非嘗試自動修復

> 💡 **名言：「MCP 偵測問題，Agent 解決問題」**
>
> 不要讓 MCP 越俎代庖，Agent 比我們更聰明。

**範例**：
```
❌ MCP 維護 60 條翻譯字典 → 覆蓋不全、更新困難
✅ MCP 偵測非英文 → 返回錯誤 + 指導 → Agent 自己翻譯
```

---

## 第四章：子法授權

### 第 8 條：子法層級
```
憲法 (CONSTITUTION.md)
  └── 子法 (.github/bylaws/*.md)
        └── 實施細則 (Skills 內的 rules/)
```

### 第 9 條：子法優先順序
1. 子法不得違反憲法
2. 衝突時以較高層級為準
3. 未規範事項由 Skills 自行決定

---

## 附則

### 第 10 條：修憲程序
1. 修改憲法須在 decisionLog.md 記錄原因
2. 重大修改須更新版本號
3. 本憲法版本：v1.0.0
