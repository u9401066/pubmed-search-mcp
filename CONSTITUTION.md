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
