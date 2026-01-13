# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

<!-- 一句話描述正在做什麼 -->
- 完善 Microsoft Copilot Studio MCP 整合（Stateless 模式）

## 📝 進行中的變更

<!-- 具體的檔案和修改 -->
| 檔案 | 變更內容 |
|------|----------|
| `run_copilot.py` | 新增 `--stateless` 參數，預設為 True |
| `src/pubmed_search/mcp/server.py` | 新增 `stateless_http` 參數 |
| `scripts/test-copilot-mcp.py` | 新增 MCP 相容性測試腳本 |
| `copilot-studio/openapi-schema.yaml` | 更新 host 為 `kmuh-ai.ngrok.dev` |

## ⚠️ 待解決

<!-- 遇到的問題或阻礙 -->
- ✅ MCP 伺服器測試通過 (5/5 步驟成功)
- ⏳ Copilot Studio 實際連線測試中

## 💡 重要決定

<!-- 本次工作階段做的決定 -->
- **Stateless 模式**: 依據 Microsoft 官方範例，使用 `stateless_http=True`
- 使用 Streamable HTTP 取代 SSE (SSE 已 deprecated)
- 添加 `json_response=True` 支援 Copilot Studio 的 `Accept: application/json`
- 添加 CopilotStudioMiddleware 轉換 202→200 回應
- 使用 ngrok 固定網域 `kmuh-ai.ngrok.dev`
- Python 虛擬環境升級至 3.12 (使用 uv)

## 📁 相關檔案

<!-- 涉及的檔案路徑 -->
```
run_copilot.py
copilot-studio/README.md
copilot-studio/openapi-schema.yaml
scripts/test-copilot-mcp.py
src/pubmed_search/mcp/server.py
```

## 🔜 下一步

<!-- 接下來要做什麼 -->
1. ✅ MCP 相容性測試通過
2. ⏳ 在 Copilot Studio 實際測試連線
3. 如有問題，檢查 response size 或 timeout 限制

---
*Last updated: 2026-01-13*