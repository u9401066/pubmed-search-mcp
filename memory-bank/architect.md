# System Architect

> 📌 此檔案記錄重大架構決策，架構變更時更新。

## 🌐 系統架構圖

```
┌────────────────────────────────────────────────────────────┐
│                 PubMed Search MCP Server                   │
├────────────────────────────────────────────────────────────┤
│  🎯 Presentation Layer (MCP Tools)                         │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  src/pubmed_search/mcp/                             │   │
│  │  ├── server.py          # MCP Server (SSE/STDIO)   │   │
│  │  └── tools/             # 15+ MCP Tools            │   │
│  │      ├── unified.py / discovery.py  # unified_search, article exploration  │   │
│  │      ├── strategy.py    # generate_search_queries  │   │
│  │      ├── pico.py        # parse_pico               │   │
│  │      ├── export.py      # prepare_export           │   │
│  │      └── citation_tree.py # Citation Tree          │   │
│  └─────────────────────────────────────────────────────┘   │
├────────────────────────────────────────────────────────────┤
│  ⚙️ Infrastructure Layer (API Clients)                     │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  src/pubmed_search/entrez/                          │   │
│  │  ├── search.py          # ESearch, EFetch          │   │
│  │  ├── citation.py        # ELink (citations)        │   │
│  │  ├── icite.py           # NIH iCite API            │   │
│  │  └── utils.py           # MeSH, ESpell             │   │
│  │                                                     │   │
│  │  src/pubmed_search/sources/                         │   │
│  │  ├── semantic_scholar.py                            │   │
│  │  └── openalex.py                                    │   │
│  └─────────────────────────────────────────────────────┘   │
├────────────────────────────────────────────────────────────┤
│  🌐 External APIs                                          │
│  ┌─────────┐ ┌──────────────┐ ┌─────────────┐            │
│  │  NCBI   │ │ Semantic     │ │  OpenAlex   │            │
│  │ Entrez  │ │ Scholar      │ │             │            │
│  └─────────┘ └──────────────┘ └─────────────┘            │
└────────────────────────────────────────────────────────────┘
```

## 🏛️ 架構決策紀錄

### ADR-001: MCP 作為主要介面

**日期**：2025-01

**背景**：需要讓 AI Agent 能使用 PubMed 搜尋功能

**決定**：採用 Model Context Protocol (MCP) 作為主要介面

**理由**：
- MCP 是 AI Agent 工具的標準協定
- 支援 Claude, GPT 等多種 LLM
- SSE/STDIO 雙模式支援本地與遠端

### ADR-002: Biopython Entrez 封裝

**日期**：2025-01

**背景**：需要穩定的 NCBI API 存取

**決定**：使用 Biopython 的 Entrez 模組作為基礎

**理由**：
- 成熟穩定的 NCBI API 客戶端
- 自動處理 rate limiting
- 內建 XML 解析

### ADR-003: 多來源整合策略

**日期**：2025-01 (v0.1.10+)

**背景**：PubMed 之外還有其他有價值的來源

**決定**：新增 Semantic Scholar 和 OpenAlex 作為補充來源

**理由**：
- Semantic Scholar 有更好的引用分析
- OpenAlex 是開放資料來源
- 保持 PubMed 為主要來源

## 📦 模組圖

```
src/pubmed_search/
├── mcp/                 # MCP Layer
│   ├── server.py
│   ├── session_tools.py
│   └── tools/          # 5 個工具模組
│
├── entrez/             # NCBI Entrez Layer
│   ├── search.py
│   ├── citation.py
│   ├── icite.py
│   └── utils.py
│
├── sources/            # Multi-Source Layer
│   ├── semantic_scholar.py
│   └── openalex.py
│
├── export/             # Export Layer
│   ├── formats.py
│   └── links.py
│
└── client/             # High-Level Client
    ├── client.py       # PubMedClient
    └── session.py      # SearchSession
```

---
*Last updated: 2025-01-XX*
