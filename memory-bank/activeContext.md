# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

<!-- 一句話描述正在做什麼 -->
- **工具註冊架構重構** - 集中式管理 + 自動化文檔同步

## 📝 進行中的變更

<!-- 具體的檔案和修改 -->
| 目錄/檔案 | 變更內容 |
|----------|----------|
| `mcp_server/tool_registry.py` | 新增 - 集中式工具註冊 + 驗證 |
| `mcp_server/instructions.py` | 新增 - AI Agent 使用說明 |
| `mcp_server/tools/icd.py` | 新增 - ICD 轉換工具（從 resources.py 遷移） |
| `mcp_server/TOOLS_INDEX.md` | 新增 - 完整工具索引 |
| `scripts/count_mcp_tools.py` | 新增 - 工具統計腳本 |
| `README.md`, `README.zh-TW.md` | 修改 - 工具數量 21 → 34 |

## ✅ 已解決問題

<!-- 根本原因和解決方案 -->
**工具數量不同步**：
- 問題：README 顯示 21 工具，實際有 34 個
- 解決：`count_mcp_tools.py --update-docs` 自動同步

**工具註冊分散**：
- 問題：工具註冊散落各處，難以追蹤
- 解決：`tool_registry.py` 集中管理 + `validate_tool_registry()` 驗證

**ICD 工具錯放**：
- 問題：ICD 資料和工具放在 resources.py（379 行）
- 解決：遷移到 `tools/icd.py` 獨立模組

## 💡 關鍵發現

<!-- 本次工作階段的重要發現 -->
- FastMCP 內部結構：`mcp._tool_manager._tools` 存放已註冊工具
- 工具描述從 `Tool.description` 屬性取得（docstring 第一行）
- `TOOL_CATEGORIES` 必須與實際註冊工具同步（驗證功能）
- 工具統計腳本應在每次 git commit 前執行

## 📁 新增資料來源

```text
整合資料庫（共 8 個）:
├── PubMed (36M+)              # 主要搜尋
├── Europe PMC (45M+)          # 全文存取
├── CORE (270M+)               # 開放取用
├── OpenAlex (250M+)           # 學術元資料
├── Semantic Scholar (215M+)   # AI 增強
├── CrossRef (150M+)           # DOI 元資料
├── Unpaywall                  # OA 連結查找
└── ClinicalTrials.gov         # 🆕 臨床試驗
```

## 🔜 下一步

<!-- 接下來要做什麼 -->
1. ⏳ PRISMA flow tracking (Phase 5.9)
2. ⏳ Evidence level classification (Oxford CEBM I-V)
3. ⏳ Token 效率優化 (Phase 5.8)

---
*Last updated: 2026-01-27 - 工具註冊架構重構完成*