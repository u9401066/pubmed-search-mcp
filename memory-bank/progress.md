# Progress (Updated: 2026-01-21)

## Done

- ✅ 達成 90% 測試覆蓋率 (411 tests)
- ✅ v0.1.8 發布到 PyPI
- ✅ v0.1.10-v0.1.25 功能更新
- ✅ ROADMAP 更新：Agent 友善標準定義 + Token 效率優化 (Phase 5.8)
- ✅ 競品分析更新 (2025 Aug-Sep findings)
- ✅ Ruff lint 修復 (13 errors fixed)
  - Citation Tree 視覺化
  - 多來源整合 (Semantic Scholar, OpenAlex, CORE, Europe PMC)
  - HTTP API 背景服務
  - OpenURL 機構存取整合
  - Vision Search 圖片搜尋
  - Unified Search 統一搜尋介面
- ✅ Docker 部署支援 (含 HTTPS)
- ✅ SSE Server 遠端存取 (port 8765)
- ✅ 導入 Claude Skills 系統 (13+ skills)
- ✅ 導入憲法-子法架構
- ✅ 建立 Memory Bank 記憶系統
- ✅ 專案結構一致性檢查完成
- ✅ MCP SDK 升級至 1.25.0
- ✅ ToolUniverse PR #64 提交
- ✅ 新增 medical-calc-mcp PR 指南文件
- ✅ FastAPI 依賴更新 (>=0.128.0)
- ✅ **Phase 2.2 功能完成**
  - ICD 自動偵測整合至 unified_search (ICD-10/ICD-9 → MeSH 擴展)
  - Preprint 搜尋整合 (arXiv, medRxiv, bioRxiv)
  - Advanced Filters 修復 (Clinical Query 語法: Therapy/Broad[filter])
  - MCP Resources 模組 (filter docs, ICD↔MeSH 雙向轉換)

## Doing

- 🔄 Token 效率優化 (Phase 5.8)
  - ⏳ 設計 compact output format
  - ⏳ `to_compact_dict()` 方法
- 🔄 競品學習功能 (Phase 5.7)
  - ⏳ Think/Plan Tool 概念

## Next

- medical-calc-mcp ToolUniverse PR 提交
- Token 效率優化實作
- Phase 5.7 功能實作
- 文件網站建立
- 多語言 README 完善
