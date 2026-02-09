---
name: tool-sync
description: Auto-sync MCP tool documentation when tools are added, removed, or renamed. Triggers: TS, tool-sync, 工具同步, 同步工具, sync tools, new tool, 新增工具, 工具變更, update tools.
---

# MCP 工具文檔自動同步

## 描述
當 MCP 工具被新增、移除、重新命名時，自動同步所有相關文檔。
確保 instructions、skills、README 中的工具數量和列表永遠與程式碼一致。

## 觸發條件
以下情境**必須**觸發此 Skill：
1. 新增了 `register_*_tools()` 函數或 `@mcp.tool()` 裝飾器
2. 修改了 `tool_registry.py` 的 `TOOL_CATEGORIES`
3. 修改了 `tools/__init__.py` 的 `register_all_tools()`
4. 刪除或重新命名任何 MCP 工具
5. 用戶明確要求 "同步工具" / "tool sync"

## 自動同步的文件（共 6 個）

| # | 文件 | 更新內容 | 更新方式 |
|---|------|----------|----------|
| 1 | `presentation/mcp_server/tool_registry.py` | `TOOL_CATEGORIES` dict | 手動 — 新增/移除工具分類 |
| 2 | `presentation/mcp_server/tools/__init__.py` | `register_all_tools()` | 手動 — import + 呼叫 register 函數 |
| 3 | `presentation/mcp_server/instructions.py` | SERVER_INSTRUCTIONS 工具列表 | 🤖 `--update-docs` 自動 |
| 4 | `.github/copilot-instructions.md` | Tool Categories 表格 | 🤖 `--update-docs` 自動 |
| 5 | `.claude/skills/pubmed-mcp-tools-reference/SKILL.md` | 完整工具參考 | 🤖 `--update-docs` 自動 |
| 6 | `README.md` + `README.zh-TW.md` | 工具數量 badge | 🤖 `--update-docs` 自動 |

## 執行流程

### Step 1: 手動修改（AI Agent 負責）
確保以下兩個「源頭」檔案正確：

```python
# 1. tool_registry.py — 新增分類
TOOL_CATEGORIES = {
    ...
    "new_category": {
        "name": "新分類名稱",
        "description": "分類描述",
        "tools": ["tool_name_1", "tool_name_2"],
    },
}

# 2. tools/__init__.py — 註冊函數
from .new_module import register_new_tools

def register_all_tools(mcp, searcher):
    ...
    register_new_tools(mcp)  # 新增呼叫
```

### Step 2: 執行自動同步腳本
```bash
uv run python scripts/count_mcp_tools.py --update-docs
```

### Step 3: 驗證
```bash
# 檢查工具數量是否正確
uv run python scripts/count_mcp_tools.py

# 檢查驗證是否通過（TOOL_CATEGORIES 與 FastMCP runtime 同步）
uv run python scripts/count_mcp_tools.py --verbose
```

### Step 4: 回報結果
```
🔄 MCP 工具同步完成

📊 統計：
  - 工具總數: XX → YY (+N)
  - 分類數: XX → YY (+N)
  - 更新文件: N 個

📝 已更新：
  ✅ tool_registry.py - 新增 "image_search" 分類
  ✅ tools/__init__.py - 新增 register_image_search_tools
  ✅ instructions.py - 工具列表已同步
  ✅ copilot-instructions.md - Tool Categories 已同步
  ✅ SKILL.md (tools-reference) - 已重新生成
  ✅ README.md - 工具數量已更新
  ✅ README.zh-TW.md - 工具數量已更新
  
⚠️ 驗證: PASSED ✅
```

## 重要規則

### 🔴 必須遵守
1. **任何工具變更後都要執行** `count_mcp_tools.py --update-docs`
2. **先修改源頭**（tool_registry.py + tools/__init__.py），再執行腳本
3. **驗證必須通過** — `TOOL_CATEGORIES` 與 FastMCP runtime 必須同步

### ⚠️ 注意事項
- `count_mcp_tools.py` 會自動偵測 `TOOL_CATEGORIES` 中所有類別（動態取得，不再硬編碼）
- `instructions.py` 只更新工具列表區塊，搜尋策略等手寫內容不會被覆蓋
- `pubmed-mcp-tools-reference` SKILL 會完全重新生成
- CHANGELOG 更新由 `changelog-updater` skill 另行處理

## 與其他 Skill 的關係
- **git-precommit**: commit 前會呼叫本 Skill 的同步步驟
- **git-doc-updater**: 文檔更新時也會觸發工具同步檢查
- **ddd-architect**: 新增功能模組時會提醒執行工具同步
