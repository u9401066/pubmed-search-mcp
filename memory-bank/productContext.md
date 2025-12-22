# Product Context

> 📌 此檔案描述專案的技術架構和產品定位，專案初期建立後較少更新。

## 📋 專案概述

**專案名稱**：PubMed Search MCP Server

**一句話描述**：為 AI Agent 提供專業的 PubMed 文獻搜尋能力的 MCP 伺服器。

**目標用戶**：醫學研究人員、AI 開發者、需要文獻搜尋自動化的團隊

## 🏗️ 架構

```
pubmed-search-mcp/
├── src/pubmed_search/
│   ├── entrez/         # NCBI Entrez API 封裝 (Infrastructure)
│   ├── mcp/            # MCP 伺服器與工具 (Presentation)
│   │   └── tools/      # MCP Tools 定義
│   ├── sources/        # 多來源整合 (Semantic Scholar, OpenAlex)
│   ├── api/            # HTTP API (背景服務)
│   └── client/         # PubMedClient 高階介面
└── tests/              # 測試 (411 tests, 90% coverage)
```

### 分層架構 (DDD-like)

```
MCP Tools (Presentation) → Entrez/Sources (Infrastructure) → NCBI API (External)
```

## ✨ 核心功能

- 🔍 **search_literature**: 基本 PubMed 搜尋
- 🧬 **generate_search_queries**: MeSH 詞彙擴展搜尋策略
- 🏥 **parse_pico**: PICO 臨床問題解析
- 🔗 **find_related_articles / find_citing_articles**: 文獻探索
- 📤 **prepare_export**: 多格式匯出 (RIS, BibTeX, CSV, MEDLINE, JSON)
- 🌳 **Citation Tree**: 引用樹視覺化 (v0.1.10+)

## 🔧 技術棧

| 類別 | 技術 |
|------|------|
| 語言 | Python 3.11+ |
| 套件管理 | pip / uv |
| MCP 框架 | mcp >= 1.0.0 |
| API 客戶端 | Biopython (Entrez), requests |
| 測試 | pytest, pytest-asyncio, pytest-cov |
| CI/CD | GitHub Actions |
| 容器化 | Docker, docker-compose |

## 📦 依賴

### 核心依賴
- biopython >= 1.81 (NCBI Entrez)
- mcp >= 1.0.0 (MCP 協定)
- requests >= 2.28.0 (HTTP)
- pylatexenc >= 2.10 (BibTeX Unicode)

### 開發依賴
- pytest, pytest-asyncio, pytest-cov

## 🚀 部署方式

1. **PyPI 安裝**: `pip install pubmed-search-mcp`
2. **Docker**: `docker-compose up`
3. **SSE Server**: `python run_server.py` (port 8765)

---
*Last updated: 2025-01-XX*