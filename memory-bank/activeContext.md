# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

<!-- 一句話描述正在做什麼 -->
- 整合 Microsoft Copilot Studio MCP 支援

## 📝 進行中的變更

<!-- 具體的檔案和修改 -->
| 檔案 | 變更內容 |
|------|----------|
| `run_copilot.py` | 新增 Copilot Studio 專用啟動器 |
| `copilot-studio/` | 新增 Copilot Studio 整合文檔 |
| `scripts/start-copilot-ngrok.sh` | ngrok tunnel 腳本 |
| `src/pubmed_search/mcp/server.py` | 新增 `json_response` 參數支援 |

## ⚠️ 待解決

<!-- 遇到的問題或阻礙 -->
- Copilot Studio 連線測試中，出現 SystemError
- 需要確認 202→200 middleware 是否解決問題

## 💡 重要決定

<!-- 本次工作階段做的決定 -->
- 使用 Streamable HTTP 取代 SSE (SSE 已 deprecated)
- 添加 `json_response=True` 支援 Copilot Studio 的 `Accept: application/json`
- 添加 CopilotStudioMiddleware 轉換 202→200 回應
- 使用 ngrok 固定網域 `kmuh-ai.ngrok.dev`

## 📁 相關檔案

<!-- 涉及的檔案路徑 -->
```
run_copilot.py
copilot-studio/README.md
scripts/start-copilot-ngrok.sh
src/pubmed_search/mcp/server.py
```

## 🔜 下一步

<!-- 接下來要做什麼 -->
1. 確認 Copilot Studio 連線成功
2. 測試工具呼叫功能
3. 文檔完善

---
*Last updated: 2026-01-13*