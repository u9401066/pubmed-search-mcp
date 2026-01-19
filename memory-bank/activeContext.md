# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

<!-- 一句話描述正在做什麼 -->
- **ROADMAP 更新** - 加入 Agent 友善標準 + Token 效率優化 (Phase 5.8)

## 📝 進行中的變更

<!-- 具體的檔案和修改 -->
| 檔案 | 變更內容 |
|------|----------|
| `run_copilot.py` | 重構使用 `create_copilot_server()` 函數，支援 `--full-tools` 參數 |
| `src/pubmed_search/mcp/copilot_tools.py` | **新增** - 11 個 Copilot 相容工具，避免 `anyOf` 多類型 |
| `scripts/test-copilot-mcp.py` | 更新測試工具名稱為 `search_pubmed`, `get_article` |

## ✅ 已解決問題

<!-- 根本原因和解決方案 -->
**根本原因**：
Copilot Studio 不支援 JSON Schema 中的 `anyOf` 多類型定義
- 原本使用 `Union[int, str]`、`Union[bool, str]`、`Optional[str]`
- 這些在 JSON Schema 中變成 `anyOf: [{"type": "integer"}, {"type": "string"}]`
- Microsoft 文檔明確指出：「schema definition is truncated when type is an array」

**解決方案**：
- 建立 `copilot_tools.py` 模組，使用單一類型參數
- 11 個簡化工具：search_pubmed, get_article, find_related, find_citations 等
- 所有參數僅使用 `str`, `int`, `bool` 單一類型
- 內部用 `InputNormalizer` 處理類型轉換

## 💡 關鍵發現

<!-- 本次工作階段的重要發現 -->
- 原本 25/31 個工具有 `anyOf` 問題
- Copilot Studio Known Issues 清單：
  1. `exclusiveMinimum` 必須是 Boolean（不是 integer）
  2. 多類型陣列會導致 schema truncation
  3. Reference type ($ref) 不支援
  4. Enum type 被解釋為 string

## 📁 新增/修改檔案

```
run_copilot.py                           # 重構
src/pubmed_search/mcp/copilot_tools.py   # 新增 - 11 個 Copilot 相容工具
scripts/test-copilot-mcp.py              # 更新測試工具名稱
```

## 🔜 下一步

<!-- 接下來要做什麼 -->
1. ⏳ 實作 Token 效率優化 (Phase 5.8)
   - `output_format="compact"` 參數
   - `UnifiedArticle.to_compact_dict()` 方法
2. ⏳ 競品學習功能 (Phase 5.7)
   - Think/Plan Tool 概念
   - 統一查詢語法

## 🚀 使用方式

```bash
# 啟動 Copilot Studio 相容模式（預設 11 個工具）
python run_copilot.py --port 8765

# 啟動完整工具集（可能有問題）
python run_copilot.py --port 8765 --full-tools

# 測試
python scripts/test-copilot-mcp.py http://localhost:8765/mcp
```

---
*Last updated: 2026-01-20 - ROADMAP Agent Friendly + Token Efficiency*