const DOC_PAGES = [
  {
    slug: "overview",
    group: "overview",
    lang: "en",
    audience: "start",
    title: "Overview",
    blurb: "Quick install, MCP SDK v2 runtime choice, supported clients, and the complete product map.",
    keywords: "MCP 2.0 MCP SDK v2 local stdio loopback service 45 tools broker security",
    file: "site-content/overview.md",
  },
  {
    slug: "overview-zh",
    group: "overview",
    lang: "zh",
    audience: "start",
    title: "總覽",
    blurb: "快速安裝、MCP SDK v2 runtime 選擇、支援 client 與完整產品地圖。",
    keywords: "MCP 2.0 MCP SDK v2 本機 stdio loopback 多人 service 45 工具 broker 安全",
    file: "site-content/overview-zh.md",
  },
  {
    slug: "user-guide",
    group: "user-guide",
    lang: "en",
    audience: "user",
    title: "User Guide",
    blurb: "Practical multi-source search, broker, full-text, evidence, export, note, and pipeline workflows.",
    keywords: "unified_search broker source errors rate limits artifacts local service filesystem",
    file: "site-content/user-guide.md",
  },
  {
    slug: "user-guide-zh",
    group: "user-guide",
    lang: "zh",
    audience: "user",
    title: "使用者指南",
    blurb: "多來源搜尋、broker、全文、證據、匯出、筆記與 pipeline 實務。",
    keywords: "unified_search broker source errors rate limits artifact 本機 service filesystem",
    file: "site-content/user-guide-zh.md",
  },
  {
    slug: "advanced-workflows",
    group: "advanced-workflows",
    lang: "en",
    audience: "user",
    title: "Advanced Research Workflows",
    blurb:
      "Research chronicle/lineage tree, Open-i image search, uploaded-image handoff, and persistent query memory.",
    keywords:
      "build_research_chronicle read_research_chronicle context_graph search_biomedical_images Open-i analyze_figure_for_search uploaded image persistent query memory read_session artifact",
    file: "site-content/advanced-workflows.md",
  },
  {
    slug: "advanced-workflows-zh",
    group: "advanced-workflows",
    lang: "zh",
    audience: "user",
    title: "進階研究工作流",
    blurb: "研究脈絡時間軸、Open-i 圖片搜尋、上傳圖片 handoff、持久化 query memory。",
    keywords:
      "研究編年史 研究脈絡 build_research_chronicle read_research_chronicle context_graph Open-i 圖片搜尋 search_biomedical_images 上傳圖片 analyze_figure_for_search 持久化 query memory read_session artifact",
    file: "site-content/advanced-workflows-zh.md",
  },
  {
    slug: "research-chronicle-rebuild-spec",
    group: "research-chronicle-rebuild-spec",
    lang: "all",
    audience: "developer",
    title: "Research Chronicle Rebuild Spec",
    titleByLang: { zh: "Research Chronicle 重建規格" },
    blurb:
      "Implemented contract for the persistent Research Chronicle, horizontal chronological branch map, evidence graph, artifacts, and migration mapping.",
    blurbByLang: {
      zh: "Persistent Research Chronicle、橫向時序分岔圖、evidence graph、artifact 與 migration mapping 的實作契約。",
    },
    keywords:
      "research chronicle timeline lineage tree context graph preview citation graph artifact read_session rebuild spec",
    file: "site-content/research-chronicle-rebuild-spec.md",
  },
  {
    slug: "tools-usage-guide",
    group: "tools-usage-guide",
    lang: "en",
    audience: "user",
    title: "Tools Usage Guide",
    blurb: "Capability-first routing guide for the primary MCP tool surface.",
    file: "site-content/tools-usage-guide.md",
  },
  {
    slug: "tools-usage-guide-zh",
    group: "tools-usage-guide",
    lang: "zh",
    audience: "user",
    title: "工具使用指南",
    blurb: "Primary MCP tool surface 的能力導向路由指南。",
    file: "site-content/tools-usage-guide-zh.md",
  },
  {
    slug: "pipeline-tutorial",
    group: "pipeline-tutorial",
    lang: "en",
    audience: "user",
    title: "Pipeline Tutorial",
    blurb: "Inline templates, saved plans, custom DAGs, history, and scheduling.",
    file: "site-content/pipeline-tutorial.md",
  },
  {
    slug: "pipeline-tutorial-zh",
    group: "pipeline-tutorial",
    lang: "zh",
    audience: "user",
    title: "Pipeline 教學",
    blurb: "Template、saved plan、custom DAG、history 與 schedule 的完整教學。",
    file: "site-content/pipeline-tutorial-zh.md",
  },
  {
    slug: "developer-guide",
    group: "developer-guide",
    lang: "en",
    audience: "developer",
    title: "Developer Guide",
    blurb: "DDD boundaries, tool registration, docs generation, validation, and release hygiene.",
    file: "site-content/developer-guide.md",
  },
  {
    slug: "developer-guide-zh",
    group: "developer-guide",
    lang: "zh",
    audience: "developer",
    title: "開發者指南",
    blurb: "DDD 邊界、tool 註冊、文件生成、驗證與 release hygiene。",
    file: "site-content/developer-guide-zh.md",
  },
  {
    slug: "python-sdk-http-cli-design",
    group: "python-sdk-http-cli-design",
    lang: "all",
    audience: "developer",
    title: "Python SDK And HTTP CLI Design",
    titleByLang: { zh: "Python SDK 與 HTTP CLI 設計" },
    blurb: "Separated contracts for MCP tools, Python package callers, and remote HTTP deployments.",
    blurbByLang: { zh: "MCP tools、Python package callers 與遠端 HTTP deployments 的分離合約。" },
    file: "site-content/python-sdk-http-cli-design.md",
  },
  {
    slug: "architecture",
    group: "architecture",
    lang: "all",
    audience: "developer",
    title: "Architecture",
    titleByLang: { zh: "架構" },
    blurb: "MCP SDK v2 request model, DDD layers, broker orchestration, tenant state, and runtime surfaces.",
    blurbByLang: { zh: "MCP SDK v2 request model、DDD 分層、broker orchestration、tenant state 與 runtime surfaces。" },
    keywords: "MCP 2.0 SDK v2 no initialize no session id DDD broker tenant concurrency",
    file: "site-content/architecture.md",
  },
  {
    slug: "quick-reference",
    group: "quick-reference",
    lang: "all",
    audience: "developer",
    title: "Quick Reference",
    titleByLang: { zh: "快速索引" },
    blurb: "Fast lookup for all 45 MCP tools across 16 registry categories.",
    blurbByLang: { zh: "45 個 MCP tools 與 16 個 registry categories 的快速查找。" },
    keywords: "45 tools 16 categories tool index parameters",
    file: "site-content/quick-reference.md",
  },
  {
    slug: "source-contracts",
    group: "source-contracts",
    lang: "all",
    audience: "developer",
    title: "Source Contracts",
    titleByLang: { zh: "資料來源契約" },
    blurb: "Multi-source broker stages, source selection, shared rate budgets, rights, and provenance.",
    blurbByLang: { zh: "多來源 broker 階段、source selection、共用 rate budget、rights 與 provenance。" },
    keywords: "broker PubMed Europe PMC OpenAlex Semantic Scholar CORE arXiv medRxiv bioRxiv retry backoff dedup",
    file: "site-content/source-contracts.md",
  },
  {
    slug: "semantic-scholar-api",
    group: "semantic-scholar-api",
    lang: "all",
    audience: "reference",
    title: "Semantic Scholar Data Plane",
    titleByLang: { zh: "Semantic Scholar 資料平面" },
    blurb: "Live relevance/bulk search, batch enrichment, and dataset metadata for operator workflows; partition download and local indexing are not implemented.",
    blurbByLang: { zh: "Live relevance/bulk、batch enrichment、dataset manifest/diff、權利與有界 ingestion。" },
    keywords: "Semantic Scholar S2 systematic bulk compiler batch dataset release manifest diff source metadata rate limit",
    file: "site-content/semantic-scholar-api.md",
  },
  {
    slug: "openalex-api",
    group: "openalex-api",
    lang: "all",
    audience: "reference",
    title: "OpenAlex Search And Data Plane",
    titleByLang: { zh: "OpenAlex 搜尋與資料平面" },
    blurb: "Capability-aware keyword/semantic search, cursor budgets, credits, and provenance; the operator snapshot path is declared but no local index is implemented.",
    blurbByLang: { zh: "Capability-aware keyword/semantic、cursor budget、credits 與 provenance；operator snapshot 路徑已有說明，但尚未實作 local index。" },
    keywords: "OpenAlex native semantic systematic cursor select credits cost rate limit snapshot sync provenance source metadata",
    file: "site-content/openalex-api.md",
  },
  {
    slug: "clinicalkey-ai",
    group: "clinicalkey-ai",
    lang: "all",
    audience: "reference",
    title: "ClinicalKey AI Boundary",
    titleByLang: { zh: "ClinicalKey AI 邊界" },
    blurb: "Default-off licensed evidence adapter, OAuth, zero-persistence governance, and excluded clinical workflows.",
    blurbByLang: { zh: "預設關閉的 licensed evidence adapter、OAuth、零持久化治理與排除的臨床流程。" },
    keywords: "ClinicalKey AI Elsevier OAuth licensed evidence zero persistence PHI data governance",
    file: "site-content/clinicalkey-ai.md",
  },
  {
    slug: "biomcp-analysis",
    group: "biomcp-analysis",
    lang: "all",
    audience: "developer",
    title: "BioMCP Architecture Analysis",
    titleByLang: { zh: "BioMCP 架構分析" },
    blurb: "Current BioMCP architecture, source/entity grammar, transferable patterns, and explicit non-goals for this repo.",
    blurbByLang: { zh: "BioMCP 現況、source/entity grammar、可移植模式與本 repo 明確不採用項目。" },
    keywords: "BioMCP Rust single grammar counts-first progressive disclosure pivots local study next commands",
    file: "site-content/biomcp-analysis.md",
  },
  {
    slug: "troubleshooting",
    group: "troubleshooting",
    lang: "all",
    audience: "reference",
    title: "Integrations & Operations",
    titleByLang: { zh: "整合與維運" },
    blurb: "MCP SDK v2, client setup, broker configuration, environment reference, verification, and recovery.",
    blurbByLang: { zh: "MCP SDK v2、client 設定、broker 組態、環境變數、驗證與故障排除。" },
    keywords: "MCP 2.0 operations clients environment browser broker health ready troubleshooting security",
    file: "site-content/troubleshooting.md",
  },
  {
    slug: "deployment",
    group: "deployment",
    lang: "all",
    audience: "reference",
    title: "Deployment",
    titleByLang: { zh: "部署" },
    blurb: "Separate local and authenticated multi-user contracts, security, probes, storage, and scaling limits.",
    blurbByLang: { zh: "分開本機與認證多人合約，含安全、probe、storage 與 scaling 邊界。" },
    keywords: "local stdio loopback multi-user service bearer auth tenant Host Origin scheduler replica backup",
    file: "site-content/deployment.md",
  },
];

// Complete 45 Tools Rich Database for Interactive Tool Explorer
const MCP_TOOLS_DATA = [
  {
    name: "unified_search",
    cat: "search",
    catName: { zh: "核心搜尋", en: "Search" },
    icon: "🔍",
    summary: {
      zh: "單一入口跨 6 大學術來源（PubMed、Europe PMC、OpenAlex、Semantic Scholar、CrossRef、CORE）綜合檢索，支援 ICD 自動轉換、預印本搜尋與輕量脈絡圖。",
      en: "Single gateway across 6 academic sources with automatic ICD translation, preprints, and context graph preview.",
    },
    example: 'unified_search(query="remimazolam ICU sedation", limit=10)',
    docLink: "user-guide",
  },
  {
    name: "parse_pico",
    cat: "query",
    catName: { zh: "查詢智能", en: "Query Intel" },
    icon: "🧠",
    summary: {
      zh: "驗證與解析 PICO（Population, Intervention, Comparator, Outcome）結構化臨床問題，產出可執行的搜尋 pipeline。",
      en: "Validate agent-provided PICO elements and structure them into runnable search pipelines.",
    },
    example: 'parse_pico(description="sedation in ICU", p="ICU patients", i="remimazolam", c="propofol", o="delirium")',
    docLink: "tools-usage-guide",
  },
  {
    name: "generate_search_queries",
    cat: "query",
    catName: { zh: "查詢智能", en: "Query Intel" },
    icon: "🧠",
    summary: {
      zh: "收集主題搜尋材料，利用 NCBI ESpell 拼字檢查與 MeSH 標準化詞庫擴展同義詞，供精確布林查詢決策。",
      en: "Gather search intelligence with MeSH expansion, spell-checking, and synonym suggestions for Boolean logic.",
    },
    example: 'generate_search_queries(topic="remimazolam sedation", strategy="comprehensive")',
    docLink: "tools-usage-guide",
  },
  {
    name: "analyze_search_query",
    cat: "query",
    catName: { zh: "查詢智能", en: "Query Intel" },
    icon: "🧠",
    summary: {
      zh: "在執行檢索前預先分析 PubMed 對布林查詢字串的實際解析與翻譯邏輯。",
      en: "Analyze how PubMed actually interprets and translates a Boolean query string before execution.",
    },
    example: 'analyze_search_query(query=\'"Remimazolam"[MeSH] AND "Sedation"[MeSH]\')',
    docLink: "tools-usage-guide",
  },
  {
    name: "fetch_article_details",
    cat: "discovery",
    catName: { zh: "文章探索", en: "Discovery" },
    icon: "📑",
    summary: {
      zh: "依 PMID 批次取得 PubMed 文章完整中繼資料（標題、摘要、作者、期刊、MeSH 標籤、DOI 等）。",
      en: "Batch fetch detailed metadata for one or more PubMed articles by PMID.",
    },
    example: 'fetch_article_details(pmids="32417976,34999964")',
    docLink: "tools-usage-guide",
  },
  {
    name: "find_related_articles",
    cat: "discovery",
    catName: { zh: "文章探索", en: "Discovery" },
    icon: "📑",
    summary: {
      zh: "利用 PubMed 相似度演算法尋找與指定論文相關的研究文獻。",
      en: "Find related articles using PubMed similarity algorithms.",
    },
    example: 'find_related_articles(pmid="32417976", limit=10)',
    docLink: "tools-usage-guide",
  },
  {
    name: "find_citing_articles",
    cat: "discovery",
    catName: { zh: "文章探索", en: "Discovery" },
    icon: "📑",
    summary: {
      zh: "向前追蹤引用此論文的後續研究文獻（Forward citation search）。",
      en: "Forward citation search: find articles that cited a given PubMed article.",
    },
    example: 'find_citing_articles(pmid="32417976", limit=10)',
    docLink: "tools-usage-guide",
  },
  {
    name: "get_article_references",
    cat: "discovery",
    catName: { zh: "文章探索", en: "Discovery" },
    icon: "📑",
    summary: {
      zh: "向後取得此論文的參考文獻清單（Backward citation search），挖掘基礎地基研究。",
      en: "Backward citation search: retrieve papers cited in this article's bibliography.",
    },
    example: 'get_article_references(pmid="32417976", limit=20)',
    docLink: "tools-usage-guide",
  },
  {
    name: "get_citation_metrics",
    cat: "discovery",
    catName: { zh: "文章探索", en: "Discovery" },
    icon: "📑",
    summary: {
      zh: "從 NIH iCite 取得論文客觀引用影響力指標（如 RCR 相對引用比率、NIH 百分位數、每年引用增速）。",
      en: "Retrieve citation metrics from NIH iCite (RCR, NIH percentile, citation count).",
    },
    example: 'get_citation_metrics(pmids="32417976,34999964", sort_by="rcr")',
    docLink: "tools-usage-guide",
  },
  {
    name: "verify_reference_list",
    cat: "discovery",
    catName: { zh: "引用驗證", en: "Reference Check" },
    icon: "🔬",
    summary: {
      zh: "比對純文字參考文獻清單與 PubMed 實證資料庫，驗證真實性、標題匹配度與識別碼。",
      en: "Verify plain-text reference list against PubMed evidence for title match and identifiers.",
    },
    example: 'verify_reference_list(references="Doi M, et al. BJA 2020...")',
    docLink: "tools-usage-guide",
  },
  {
    name: "get_fulltext",
    cat: "fulltext",
    catName: { zh: "全文工具", en: "Full Text" },
    icon: "📄",
    summary: {
      zh: "多來源全文擷取與結構化解析（Europe PMC XML、Unpaywall OA、機構 EZproxy/Direct、CORE、PDF 直連）。",
      en: "Enhanced multi-source fulltext retrieval with section parsing and PDF fallback.",
    },
    example: 'get_fulltext(pmid="32417976", sections="introduction,results")',
    docLink: "user-guide",
  },
  {
    name: "get_text_mined_terms",
    cat: "fulltext",
    catName: { zh: "全文工具", en: "Full Text" },
    icon: "📄",
    summary: {
      zh: "從 Europe PMC 取得文章全文的生物醫學文本挖掘標註（基因、疾病、化合物、生物體等實體）。",
      en: "Extract text-mined biomedical entities (genes, diseases, chemicals, organisms) from Europe PMC.",
    },
    example: 'get_text_mined_terms(pmid="32417976", semantic_type="CHEMICAL")',
    docLink: "user-guide",
  },
  {
    name: "get_article_figures",
    cat: "figure",
    catName: { zh: "圖表擷取", en: "Figures" },
    icon: "🖼️",
    summary: {
      zh: "從 PMC Open Access 文章抽取結構化圖表清單、標題說明（Caption）、高解析度圖片 URL 與 PDF 連結。",
      en: "Extract structured figure metadata, captions, image URLs, and PDF links from PMC Open Access articles.",
    },
    example: 'get_article_figures(pmcid="PMC11728358")',
    docLink: "user-guide",
  },
  {
    name: "search_gene",
    cat: "ncbi",
    catName: { zh: "NCBI 延伸", en: "NCBI Data" },
    icon: "🧬",
    summary: {
      zh: "搜尋 NCBI Gene 資料庫，取得基因符號、全名、物種與 Gene ID。",
      en: "Search NCBI Gene database for gene symbol, name, organism, and Gene ID.",
    },
    example: 'search_gene(query="BRCA1", organism="human")',
    docLink: "tools-usage-guide",
  },
  {
    name: "get_gene_details",
    cat: "ncbi",
    catName: { zh: "NCBI 延伸", en: "NCBI Data" },
    icon: "🧬",
    summary: {
      zh: "依 NCBI Gene ID 取得基因染色體位置、摘要說明與別名資訊。",
      en: "Get detailed gene chromosomal location, summary, and aliases by NCBI Gene ID.",
    },
    example: 'get_gene_details(gene_id="672")',
    docLink: "tools-usage-guide",
  },
  {
    name: "get_gene_literature",
    cat: "ncbi",
    catName: { zh: "NCBI 延伸", en: "NCBI Data" },
    icon: "🧬",
    summary: {
      zh: "取得與指定基因連結的 PubMed 研究論文清單。",
      en: "Get PubMed literature linked to an NCBI Gene ID.",
    },
    example: 'get_gene_literature(gene_id="672", limit=20)',
    docLink: "tools-usage-guide",
  },
  {
    name: "search_compound",
    cat: "ncbi",
    catName: { zh: "NCBI 延伸", en: "NCBI Data" },
    icon: "🧬",
    summary: {
      zh: "搜尋 PubChem 化合物與藥物資料庫，取得 PubChem CID、化學式與同義詞。",
      en: "Search PubChem for chemical compounds to obtain PubChem CID and formula.",
    },
    example: 'search_compound(query="remimazolam")',
    docLink: "tools-usage-guide",
  },
  {
    name: "get_compound_details",
    cat: "ncbi",
    catName: { zh: "NCBI 延伸", en: "NCBI Data" },
    icon: "🧬",
    summary: {
      zh: "依 PubChem CID 取得化合物分子結構、SMILES、IUPAC 名稱與性質。",
      en: "Get compound structure, SMILES, IUPAC name, and properties by PubChem CID.",
    },
    example: 'get_compound_details(cid="4943")',
    docLink: "tools-usage-guide",
  },
  {
    name: "get_compound_literature",
    cat: "ncbi",
    catName: { zh: "NCBI 延伸", en: "NCBI Data" },
    icon: "🧬",
    summary: {
      zh: "取得與指定 PubChem 化合物/藥物連結的 PubMed 研究論文清單。",
      en: "Get PubMed research articles linked to a PubChem CID.",
    },
    example: 'get_compound_literature(cid="4943", limit=20)',
    docLink: "tools-usage-guide",
  },
  {
    name: "search_clinvar",
    cat: "ncbi",
    catName: { zh: "NCBI 延伸", en: "NCBI Data" },
    icon: "🧬",
    summary: {
      zh: "搜尋 NCBI ClinVar 資料庫，取得基因變異之臨床致病性意義與分類。",
      en: "Search NCBI ClinVar for clinical significance and pathogenicity of genetic variants.",
    },
    example: 'search_clinvar(query="BRCA1", limit=10)',
    docLink: "tools-usage-guide",
  },
  {
    name: "build_citation_tree",
    cat: "citation",
    catName: { zh: "引用網絡", en: "Citations" },
    icon: "🌳",
    summary: {
      zh: "從單篇種子論文出發，建構前向引用與後向參考之雙向引用拓撲網絡圖（支援 Mermaid、Cytoscape、G6 等）。",
      en: "Build forward and backward citation network topology diagrams from a seed article.",
    },
    example: 'build_citation_tree(pmid="32417976", depth=2, output_format="mermaid")',
    docLink: "tools-usage-guide",
  },
  {
    name: "prepare_export",
    cat: "export",
    catName: { zh: "匯出工具", en: "Export" },
    icon: "📤",
    summary: {
      zh: "將搜尋結果匯出為各大文獻管理軟體格式（Official: RIS, MEDLINE, CSL JSON；Local: BibTeX, CSV, JSON）。",
      en: "Export citations into reference manager formats (RIS, BibTeX, MEDLINE, CSL JSON, CSV).",
    },
    example: 'prepare_export(pmids="last", format="ris")',
    docLink: "user-guide",
  },
  {
    name: "save_literature_notes",
    cat: "export",
    catName: { zh: "匯出工具", en: "Export" },
    icon: "📤",
    summary: {
      zh: "將搜尋論文保存為本機 Wiki / Foam 筆記（支援 frontmatter、雙向穩定 wikilinks 與 references.csl.json）。",
      en: "Save literature as local Wiki / Foam / Markdown notes with stable wikilinks and CSL JSON.",
    },
    example: 'save_literature_notes(pmids="last", note_format="wiki")',
    docLink: "user-guide",
  },
  {
    name: "read_session",
    cat: "session",
    catName: { zh: "Session 管理", en: "Session" },
    icon: "💾",
    summary: {
      zh: "統一門面讀取 Session 暫存、搜尋歷史、Search Runs、重放參數（Replay）及持久化 Artifact。",
      en: "Unified facade to inspect session cache, search history, search runs, replay args, and artifacts.",
    },
    example: 'read_session(action="artifact", artifact_id="...")',
    docLink: "user-guide",
  },
  {
    name: "get_session_pmids",
    cat: "session",
    catName: { zh: "Session 管理", en: "Session" },
    icon: "💾",
    summary: {
      zh: "取得 Session 暫存之最近一次（或指定歷史次數）搜尋的 PMID 列表。",
      en: "Get list of PMIDs cached from recent searches in current session.",
    },
    example: "get_session_pmids()",
    docLink: "user-guide",
  },
  {
    name: "get_cached_article",
    cat: "session",
    catName: { zh: "Session 管理", en: "Session" },
    icon: "💾",
    summary: {
      zh: "從 Session 快取快速讀取文章詳情，不消耗外部 API 額度與時間。",
      en: "Read cached article details from session without consuming NCBI API quota.",
    },
    example: 'get_cached_article(pmid="32417976")',
    docLink: "user-guide",
  },
  {
    name: "get_session_summary",
    cat: "session",
    catName: { zh: "Session 管理", en: "Session" },
    icon: "💾",
    summary: {
      zh: "取得目前 Session 快取狀態、搜尋次數與可用資料概覽。",
      en: "Get summary of current session cache status and search history.",
    },
    example: "get_session_summary(include_history=True)",
    docLink: "user-guide",
  },
  {
    name: "get_session_log",
    cat: "session",
    catName: { zh: "Session 管理", en: "Session" },
    icon: "💾",
    summary: {
      zh: "檢視當前 Session 的活動日誌與事件軌跡。",
      en: "Inspect session activity log and event history.",
    },
    example: "get_session_log(event_limit=50)",
    docLink: "user-guide",
  },
  {
    name: "configure_institutional_access",
    cat: "institutional",
    catName: { zh: "機構訂閱", en: "Institutional" },
    icon: "🏥",
    summary: {
      zh: "設定機構 OpenURL Link Resolver（支援台大、成大、清大、陽明交大、哈佛、牛津等預設值或自訂 URL）。",
      en: "Configure library OpenURL Link Resolver presets (NTU, Harvard, Oxford, etc.) or custom URL.",
    },
    example: 'configure_institutional_access(preset="ntu")',
    docLink: "user-guide",
  },
  {
    name: "get_institutional_link",
    cat: "institutional",
    catName: { zh: "機構訂閱", en: "Institutional" },
    icon: "🏥",
    summary: {
      zh: "為指定論文生成透過機構圖書館訂閱存取全文的 OpenURL 專屬連結。",
      en: "Generate institutional access OpenURL link for paywalled article full text.",
    },
    example: 'get_institutional_link(pmid="32417976")',
    docLink: "user-guide",
  },
  {
    name: "list_resolver_presets",
    cat: "institutional",
    catName: { zh: "機構訂閱", en: "Institutional" },
    icon: "🏥",
    summary: {
      zh: "列出所有內建支援的大學與機構 Link Resolver 預設範本清單。",
      en: "List all supported university and library Link Resolver presets.",
    },
    example: "list_resolver_presets()",
    docLink: "user-guide",
  },
  {
    name: "test_institutional_access",
    cat: "institutional",
    catName: { zh: "機構訂閱", en: "Institutional" },
    icon: "🏥",
    summary: {
      zh: "測試已設定的機構 Link Resolver 端點連線與回應狀態。",
      en: "Test connectivity and response of configured institutional link resolver.",
    },
    example: "test_institutional_access()",
    docLink: "user-guide",
  },
  {
    name: "diagnose_institutional_access",
    cat: "institutional",
    catName: { zh: "機構訂閱", en: "Institutional" },
    icon: "🏥",
    summary: {
      zh: "三階段診斷機構全文取用路徑（Direct DOI, EZproxy cookie, OpenURL handoff）。",
      en: "Diagnose full-text access across direct DOI, EZproxy, and OpenURL paths.",
    },
    example: 'diagnose_institutional_access(doi="10.1097/...")',
    docLink: "user-guide",
  },
  {
    name: "analyze_figure_for_search",
    cat: "vision",
    catName: { zh: "視覺搜索", en: "Vision" },
    icon: "👁️",
    summary: {
      zh: "接收上傳圖片或圖片 URL，交由 Agent Vision 能力判讀並自動抽取英文生醫關鍵詞執行文獻檢索。",
      en: "Analyze figure/image via Agent vision and extract English biomedical terms for literature search.",
    },
    example: 'analyze_figure_for_search(url="https://.../figure.png", search_type="medical")',
    docLink: "advanced-workflows",
  },
  {
    name: "convert_icd_mesh",
    cat: "icd",
    catName: { zh: "ICD 轉換", en: "ICD-MeSH" },
    icon: "🔄",
    summary: {
      zh: "ICD-9 / ICD-10 診斷代碼與 MeSH 標準醫學詞彙雙向對照轉換。",
      en: "Bidirectional conversion between ICD-9/ICD-10 codes and MeSH terms.",
    },
    example: 'convert_icd_mesh(code="E11")',
    docLink: "user-guide",
  },
  {
    name: "build_research_chronicle",
    cat: "chronicle",
    catName: { zh: "研究編年史", en: "Chronicle" },
    icon: "🕰️",
    summary: {
      zh: "建構持久化、版本化、有證據支撐的研究演化編年史與 X-Y 軸脈絡圖（支援以 topic、PMID 或 chronicle_id 延續）。",
      en: "Build persisted, versioned Research Chronicle with chronological spine and thematic lineage branches.",
    },
    example: 'build_research_chronicle(topic="remimazolam intraoperative", output="mermaid")',
    docLink: "advanced-workflows",
  },
  {
    name: "read_research_chronicle",
    cat: "chronicle",
    catName: { zh: "研究編年史", en: "Chronicle" },
    icon: "🕰️",
    summary: {
      zh: "讀取已保存之編年史快照（支援 load, list, diff 版本比對, milestones 里程碑分析, compare 主題比較, narrate 敘事）。",
      en: "Read stored chronicles: load, list, diff revisions, milestones analysis, multi-topic compare, narrate.",
    },
    example: 'read_research_chronicle(action="diff", chronicle_id="...", from_revision=1)',
    docLink: "advanced-workflows",
  },
  {
    name: "search_biomedical_images",
    cat: "vision",
    catName: { zh: "圖片搜尋", en: "Image Search" },
    icon: "🖼️",
    summary: {
      zh: "在 Open-i 與 Europe PMC 跨庫搜尋生醫圖片（X 光、CT、MRI、顯微鏡切片、臨床照片、圖表）。",
      en: "Search biomedical images across Open-i and Europe PMC (X-ray, CT, MRI, histology, clinical photos).",
    },
    example: 'search_biomedical_images(query="pneumonia chest X-ray", image_type="x")',
    docLink: "advanced-workflows",
  },
  {
    name: "manage_pipeline",
    cat: "pipeline",
    catName: { zh: "Pipeline 管理", en: "Pipeline" },
    icon: "🔁",
    summary: {
      zh: "Pipeline 的統一管理門面，負責搜尋工作流之 save, list, load, delete, history, schedule 操作。",
      en: "Unified facade for pipeline management: save, list, load, delete, history, schedule.",
    },
    example: 'manage_pipeline(action="list")',
    docLink: "pipeline-tutorial",
  },
  {
    name: "save_pipeline",
    cat: "pipeline",
    catName: { zh: "Pipeline 管理", en: "Pipeline" },
    icon: "🔁",
    summary: {
      zh: "將搜尋工作流配置保存為命名 Pipeline 供後續重複執行（支援 YAML/JSON 與結構驗證）。",
      en: "Save structured search pipeline for later reuse with validation.",
    },
    example: 'save_pipeline(name="daily_sedation", pipeline=...)',
    docLink: "pipeline-tutorial",
  },
  {
    name: "list_pipelines",
    cat: "pipeline",
    catName: { zh: "Pipeline 管理", en: "Pipeline" },
    icon: "🔁",
    summary: {
      zh: "列出所有已保存的 Pipeline 配置清單（可依標籤或範圍篩選）。",
      en: "List all saved search pipeline configurations.",
    },
    example: "list_pipelines()",
    docLink: "pipeline-tutorial",
  },
  {
    name: "load_pipeline",
    cat: "pipeline",
    catName: { zh: "Pipeline 管理", en: "Pipeline" },
    icon: "🔁",
    summary: {
      zh: "載入指定名稱的已保存 Pipeline 設定以供審閱或執行。",
      en: "Load saved pipeline configuration by name.",
    },
    example: 'load_pipeline(name="daily_sedation")',
    docLink: "pipeline-tutorial",
  },
  {
    name: "delete_pipeline",
    cat: "pipeline",
    catName: { zh: "Pipeline 管理", en: "Pipeline" },
    icon: "🔁",
    summary: {
      zh: "刪除指定已保存 Pipeline 及其關聯的執行紀錄。",
      en: "Delete a saved pipeline configuration and its execution history.",
    },
    example: 'delete_pipeline(name="daily_sedation")',
    docLink: "pipeline-tutorial",
  },
  {
    name: "get_pipeline_history",
    cat: "pipeline",
    catName: { zh: "Pipeline 管理", en: "Pipeline" },
    icon: "🔁",
    summary: {
      zh: "檢視 Pipeline 過往執行歷史、結果數量與新舊文章差異分析。",
      en: "Get execution history and result diff analysis for a pipeline.",
    },
    example: 'get_pipeline_history(name="daily_sedation")',
    docLink: "pipeline-tutorial",
  },
  {
    name: "schedule_pipeline",
    cat: "pipeline",
    catName: { zh: "Pipeline 管理", en: "Pipeline" },
    icon: "🔁",
    summary: {
      zh: "為已保存的 Pipeline 設定 Cron 排程進行定期背景搜尋。",
      en: "Schedule saved pipeline for periodic execution via cron.",
    },
    example: 'schedule_pipeline(name="daily_sedation", cron="0 8 * * 1")',
    docLink: "pipeline-tutorial",
  },
];

const LANGUAGE_STORAGE_KEY = "pubmed-docs-language";
const SUPPORTED_LANGUAGES = ["en", "zh"];
const LANGUAGE_META = {
  en: { htmlLang: "en", label: "EN" },
  zh: { htmlLang: "zh-TW", label: "繁中" },
};
const NAV_GROUPS = ["start", "user", "developer", "reference"];
const UI_COPY = {
  en: {
    siteEyebrow: "Documentation Site",
    tagline: "The complete operating handbook for researchers, AI-client users, service operators, and maintainers.",
    filterLabel: "Filter pages",
    filterPlaceholder: "overview, guide, tutorial, deployment...",
    sidebarNote: "Use the language switch for translated pages. Reference pages without a separate translation stay visible in both modes.",
    heroKicker: "Current MCP SDK v2 handbook",
    heroCopy:
      "Start with a working local search, then move through all 45 tools, broker/source behavior, evidence workflows, authenticated service deployment, troubleshooting, architecture, testing, and release operations under the modern MCP 2.0 request model.",
    menu: "Menu",
    outlineTitle: "On This Page",
    noPages: "No pages match this filter.",
    unableTitle: "Unable to load page",
    regenerate: "Run",
    regenerateSuffix: "to regenerate site content.",
    mermaidErrorTitle: "Diagram unavailable",
    mermaidErrorBody: "This diagram could not be rendered. Its source is preserved below; other diagrams remain available.",
    diagramLabel: "diagram",
    markdownFallback: "The Markdown renderer or sanitizer did not load. Raw documentation is preserved below.",
    toolMetric: "MCP tools",
    routingMetric: "capability families",
    oaMetric: "runtime contracts",
    journeyLocalKicker: "Start in five minutes",
    journeyLocalTitle: "Run locally",
    journeyLocalCopy: "Install with uvx, connect an AI client, and make the first search.",
    journeyResearchKicker: "Research handbook",
    journeyResearchTitle: "Use the 45 tools",
    journeyResearchCopy: "Choose a capability, search multiple sources, read full text, and preserve evidence.",
    journeyServiceKicker: "Operator runbook",
    journeyServiceTitle: "Deploy safely",
    journeyServiceCopy: "Keep local and authenticated multi-user service contracts separate.",
    journeyLabel: "Documentation quick paths",
    globalSearchPlaceholder: "Search docs & 45 tools... (Ctrl+K)",
    topbarSearchLabel: "Search Docs & Tools",
    toolExplorerTitle: "🛠️ 45 MCP Tools Interactive Explorer",
    toolExplorerSubtitle: "Filter tools by capability, search keywords in English or Chinese, and copy execution examples with one click.",
    toolSearchPlaceholder: "Search tool name, keyword (e.g. pmid, fulltext, pico, figure, 基因, rct, export)...",
    allToolsCategory: "All (45)",
    copyToolCode: "Copy",
    copiedToolCode: "Copied!",
    hubAll: "All Sections",
    hubTools: "45 Tools Explorer",
    hubUser: "User Guides",
    hubChronicle: "Research Chronicle",
    hubPipeline: "Pipelines",
    hubDev: "Architecture & Ops",
    breadcrumbHome: "Home",
    groups: {
      start: "Start Here",
      user: "For Users",
      developer: "For Developers",
      reference: "Reference",
    },
  },
  zh: {
    siteEyebrow: "文件網站",
    tagline: "給研究者、AI client 使用者、服務維運者與維護者的完整操作手冊。",
    filterLabel: "篩選頁面",
    filterPlaceholder: "總覽、指南、教學、部署...",
    sidebarNote: "使用語言切換查看翻譯頁；沒有獨立翻譯的 reference 頁會在兩種語言模式都顯示。",
    heroKicker: "當前 MCP SDK v2 完整手冊",
    heroCopy:
      "從可立即使用的本機搜尋開始，再在現代 MCP 2.0 request model 下完整掌握 45 個工具、broker/source 行為、證據工作流、認證多人服務部署、疑難排解、架構、測試與發佈操作。",
    menu: "選單",
    outlineTitle: "本頁目錄",
    noPages: "沒有符合篩選條件的頁面。",
    unableTitle: "無法載入頁面",
    regenerate: "請執行",
    regenerateSuffix: "重新生成 site content。",
    mermaidErrorTitle: "圖表無法顯示",
    mermaidErrorBody: "這張圖無法完成渲染；下方保留原始碼，頁面中的其他圖仍可正常顯示。",
    diagramLabel: "圖表",
    markdownFallback: "Markdown 渲染器或 sanitizer 未載入；下方保留完整原始文件。",
    toolMetric: "MCP 工具",
    routingMetric: "能力家族",
    oaMetric: "執行合約",
    journeyLocalKicker: "五分鐘開始",
    journeyLocalTitle: "本機執行",
    journeyLocalCopy: "用 uvx 安裝、接上 AI client，並完成第一次搜尋。",
    journeyResearchKicker: "研究操作手冊",
    journeyResearchTitle: "使用 45 個工具",
    journeyResearchCopy: "依能力選工具、平行查多來源、取得全文並保存證據。",
    journeyServiceKicker: "維運手冊",
    journeyServiceTitle: "安全部署",
    journeyServiceCopy: "完整分開本機與認證多人 service 的信任合約。",
    journeyLabel: "文件快速路徑",
    globalSearchPlaceholder: "搜尋文檔與 45 個工具... (Ctrl+K)",
    topbarSearchLabel: "搜尋文檔與工具",
    toolExplorerTitle: "🛠️ 45 個 MCP 工具互動索引庫",
    toolExplorerSubtitle: "依能力分類篩選、支援中英文關鍵字即時搜尋，一鍵複製呼叫範例與工具名稱。",
    toolSearchPlaceholder: "搜尋工具名稱、關鍵字（如 pmid, 全文, pico, 圖表, 基因, rct, export）...",
    allToolsCategory: "全部 (45)",
    copyToolCode: "複製",
    copiedToolCode: "已複製！",
    hubAll: "全部章節",
    hubTools: "45 工具庫",
    hubUser: "使用手冊",
    hubChronicle: "研究編年史",
    hubPipeline: "Pipeline 流程",
    hubDev: "架構與維運",
    breadcrumbHome: "首頁",
    groups: {
      start: "開始",
      user: "使用者",
      developer: "開發者",
      reference: "參考",
    },
  },
};

const nav = document.getElementById("page-nav");
const filterInput = document.getElementById("nav-filter");
const filterLabel = document.getElementById("filter-label");
const docContent = document.getElementById("doc-content");
const pageOutline = document.getElementById("page-outline");
const pageTitle = document.getElementById("page-title");
const pageKicker = document.getElementById("page-kicker");
const navToggle = document.getElementById("nav-toggle");
const sidebar = document.getElementById("sidebar");
const sidebarBackdrop = document.getElementById("sidebar-backdrop");
const siteEyebrow = document.getElementById("site-eyebrow");
const siteTagline = document.getElementById("site-tagline");
const sidebarNoteText = document.getElementById("sidebar-note-text");
const heroKicker = document.getElementById("hero-kicker");
const heroCopy = document.getElementById("hero-copy");
const toolMetricLabel = document.getElementById("tool-metric-label");
const routingMetricLabel = document.getElementById("routing-metric-label");
const oaMetricLabel = document.getElementById("oa-metric-label");
const journeyGrid = document.getElementById("journey-grid");
const journeyLinks = Array.from(document.querySelectorAll("[data-page-group]"));
const languageControls = Array.from(document.querySelectorAll("[data-lang]"));
const readingProgressBar = document.getElementById("reading-progress");
const backToTopBtn = document.getElementById("back-to-top");
const docBreadcrumb = document.getElementById("doc-breadcrumb");
const globalSearchBtn = document.getElementById("global-search-btn");
const topbarSearchBtn = document.getElementById("topbar-search-btn");
const searchModalBackdrop = document.getElementById("search-modal-backdrop");
const modalSearchInput = document.getElementById("modal-search-input");
const modalSearchClose = document.getElementById("modal-search-close");
const modalSearchResults = document.getElementById("modal-search-results");
const toolExplorerWidget = document.getElementById("tool-explorer-widget");
const toolSearchInput = document.getElementById("tool-search-input");
const toolCountBadge = document.getElementById("tool-count-badge");
const toolCategoryChips = document.getElementById("tool-category-chips");
const toolCardsGrid = document.getElementById("tool-cards-grid");
const topicHubNav = document.getElementById("topic-hub-nav");

const localizedJourneyElements = {
  journeyLocalKicker: document.getElementById("journey-local-kicker"),
  journeyLocalTitle: document.getElementById("journey-local-title"),
  journeyLocalCopy: document.getElementById("journey-local-copy"),
  journeyResearchKicker: document.getElementById("journey-research-kicker"),
  journeyResearchTitle: document.getElementById("journey-research-title"),
  journeyResearchCopy: document.getElementById("journey-research-copy"),
  journeyServiceKicker: document.getElementById("journey-service-kicker"),
  journeyServiceTitle: document.getElementById("journey-service-title"),
  journeyServiceCopy: document.getElementById("journey-service-copy"),
};

const embeddedContent = window.DOC_PAGE_CONTENT || {};
let mermaidInitialized = false;
let mermaidDiagramId = 0;
let pageRenderGeneration = 0;
let activeLang = preferredLanguage();
let selectedToolCategory = "all";
let activeModalResultIndex = 0;

if (window.marked) {
  window.marked.setOptions({
    gfm: true,
    breaks: false,
  });
}

function preferredLanguage() {
  try {
    const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    if (SUPPORTED_LANGUAGES.includes(stored)) {
      return stored;
    }
  } catch (_error) {
    // Ignore storage failures in strict browser contexts.
  }

  const browserLanguage = (window.navigator.language || "").toLowerCase();
  return browserLanguage.startsWith("zh") ? "zh" : "en";
}

function persistLanguage(lang) {
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
  } catch (_error) {
    // Language still works for the current session.
  }
}

function uiText(key) {
  return UI_COPY[activeLang]?.[key] || UI_COPY.en[key] || key;
}

function pageBySlug(slug) {
  return DOC_PAGES.find((page) => page.slug === slug);
}

function defaultSlugForLanguage(lang) {
  const translatedOverview = DOC_PAGES.find((page) => page.group === "overview" && page.lang === lang);
  return translatedOverview?.slug || "overview";
}

function rawSlugFromHash() {
  const hash = window.location.hash.trim();
  if (!hash.startsWith("#/")) {
    return "";
  }

  return hash.slice(2).split("#", 1)[0].trim();
}

function anchorFromHash() {
  const hash = window.location.hash.trim();
  if (hash.startsWith("#/")) {
    const anchor = hash.slice(2).split("#").slice(1).join("#");
    return anchor ? decodeURIComponent(anchor) : "";
  }

  if (hash.startsWith("#")) {
    return decodeURIComponent(hash.slice(1));
  }

  return "";
}

function currentSlug() {
  return rawSlugFromHash() || defaultSlugForLanguage(activeLang);
}

function pageText(page, key) {
  const localized = page[`${key}ByLang`];
  return localized?.[activeLang] || page[key];
}

function translatedSlugFor(page, lang) {
  if (!page) {
    return defaultSlugForLanguage(lang);
  }

  if (page.lang === "all" || page.lang === lang) {
    return page.slug;
  }

  const translated = DOC_PAGES.find((entry) => entry.group === page.group && entry.lang === lang);
  return translated?.slug || page.slug;
}

function pageMatchesLanguage(page) {
  return page.lang === "all" || page.lang === activeLang;
}

function closeSidebar() {
  sidebar.classList.remove("open");
  navToggle.setAttribute("aria-expanded", "false");
  if (sidebarBackdrop) {
    sidebarBackdrop.hidden = true;
  }
}

function renderLanguageControls() {
  languageControls.forEach((button) => {
    const isActive = button.dataset.lang === activeLang;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  });
}

function localizeStaticText() {
  document.documentElement.lang = LANGUAGE_META[activeLang].htmlLang;

  if (siteEyebrow) siteEyebrow.textContent = uiText("siteEyebrow");
  if (siteTagline) siteTagline.textContent = uiText("tagline");
  if (filterLabel) filterLabel.textContent = uiText("filterLabel");
  if (filterInput) filterInput.placeholder = uiText("filterPlaceholder");
  if (sidebarNoteText) sidebarNoteText.textContent = uiText("sidebarNote");
  if (heroKicker) heroKicker.textContent = uiText("heroKicker");
  if (heroCopy) heroCopy.textContent = uiText("heroCopy");
  if (navToggle) navToggle.textContent = uiText("menu");
  if (toolMetricLabel) toolMetricLabel.textContent = uiText("toolMetric");
  if (routingMetricLabel) routingMetricLabel.textContent = uiText("routingMetric");
  if (oaMetricLabel) oaMetricLabel.textContent = uiText("oaMetric");
  if (journeyGrid) journeyGrid.setAttribute("aria-label", uiText("journeyLabel"));

  const globalSearchText = document.getElementById("global-search-text");
  if (globalSearchText) globalSearchText.textContent = uiText("globalSearchPlaceholder");
  const topbarSearchLabel = document.getElementById("topbar-search-label");
  if (topbarSearchLabel) topbarSearchLabel.textContent = uiText("topbarSearchLabel");

  const toolExpTitle = document.getElementById("tool-explorer-title");
  if (toolExpTitle) toolExpTitle.textContent = uiText("toolExplorerTitle");
  const toolExpSubtitle = document.getElementById("tool-explorer-subtitle");
  if (toolExpSubtitle) toolExpSubtitle.textContent = uiText("toolExplorerSubtitle");
  if (toolSearchInput) toolSearchInput.placeholder = uiText("toolSearchPlaceholder");

  const hubAll = document.getElementById("hub-all-text");
  if (hubAll) hubAll.textContent = uiText("hubAll");
  const hubTools = document.getElementById("hub-tools-text");
  if (hubTools) hubTools.textContent = uiText("hubTools");
  const hubUser = document.getElementById("hub-user-text");
  if (hubUser) hubUser.textContent = uiText("hubUser");
  const hubChronicle = document.getElementById("hub-chronicle-text");
  if (hubChronicle) hubChronicle.textContent = uiText("hubChronicle");
  const hubPipeline = document.getElementById("hub-pipeline-text");
  if (hubPipeline) hubPipeline.textContent = uiText("hubPipeline");
  const hubDev = document.getElementById("hub-dev-text");
  if (hubDev) hubDev.textContent = uiText("hubDev");

  journeyLinks.forEach((link) => {
    const group = link.dataset.pageGroup;
    const target = DOC_PAGES.find((page) => page.group === group && page.lang === activeLang)
      || DOC_PAGES.find((page) => page.group === group && page.lang === "all");
    if (target) {
      link.setAttribute("href", `#/${target.slug}`);
    }
  });
  Object.entries(localizedJourneyElements).forEach(([key, element]) => {
    if (element) {
      element.textContent = uiText(key);
    }
  });
}

function switchLanguage(nextLang) {
  if (!SUPPORTED_LANGUAGES.includes(nextLang) || nextLang === activeLang) {
    return;
  }

  const previousPage = pageBySlug(rawSlugFromHash()) || pageBySlug(defaultSlugForLanguage(activeLang));
  activeLang = nextLang;
  persistLanguage(activeLang);
  const nextSlug = translatedSlugFor(previousPage, activeLang);

  if (rawSlugFromHash() === nextSlug) {
    renderPage();
    return;
  }

  window.location.hash = `#/${nextSlug}`;
}

function slugifyHeading(text) {
  return (
    (text || "section")
      .trim()
      .toLowerCase()
      .replace(/[^\p{L}\p{N}\s-]/gu, "")
      .replace(/\s/g, "-")
      .replace(/^-+/g, "") || "section"
  );
}

function ensureHeadingIds() {
  const seen = new Map();
  docContent.querySelectorAll("h1, h2, h3, h4").forEach((heading) => {
    const baseId = slugifyHeading(heading.textContent || "section");
    const nextCount = (seen.get(baseId) || 0) + 1;
    seen.set(baseId, nextCount);

    heading.id = nextCount === 1 ? baseId : `${baseId}-${nextCount}`;
    heading.tabIndex = -1;
  });
}

function wrapScrollableTables() {
  docContent.querySelectorAll("table").forEach((table) => {
    if (table.parentElement?.classList.contains("table-scroll")) {
      return;
    }

    const wrapper = document.createElement("div");
    wrapper.className = "table-scroll";
    table.replaceWith(wrapper);
    wrapper.appendChild(table);
  });
}

function wrapLocalImages() {
  docContent.querySelectorAll("img").forEach((image) => {
    const source = image.getAttribute("src") || "";
    if (!source.startsWith("images/") || image.closest(".figure-scroll")) {
      return;
    }

    const parent = image.parentElement;
    if (!parent) {
      return;
    }

    const wrapper = document.createElement("figure");
    wrapper.className = "figure-scroll";

    if (parent.tagName.toLowerCase() === "p" && parent.children.length === 1) {
      parent.replaceWith(wrapper);
      wrapper.appendChild(image);
      return;
    }

    image.replaceWith(wrapper);
    wrapper.appendChild(image);
  });
}

function injectCodeCopyButtons() {
  docContent.querySelectorAll("pre").forEach((pre) => {
    if (pre.querySelector(".code-copy-btn") || pre.closest(".mermaid-shell")) {
      return;
    }
    const button = document.createElement("button");
    button.className = "code-copy-btn";
    button.type = "button";
    button.textContent = uiText("copyToolCode");
    button.setAttribute("aria-label", "Copy code");

    button.addEventListener("click", async () => {
      const code = pre.querySelector("code")?.textContent || pre.textContent || "";
      try {
        await navigator.clipboard.writeText(code);
        button.textContent = uiText("copiedToolCode");
        button.classList.add("copied");
        setTimeout(() => {
          button.textContent = uiText("copyToolCode");
          button.classList.remove("copied");
        }, 1500);
      } catch (_e) {
        button.textContent = "Error";
      }
    });

    pre.appendChild(button);
  });
}

function updateBreadcrumbs(page) {
  if (!docBreadcrumb) return;
  const groupLabel = UI_COPY[activeLang].groups[page.audience] || page.audience;
  docBreadcrumb.innerHTML = `
    <a href="#/${defaultSlugForLanguage(activeLang)}">${uiText("breadcrumbHome")}</a>
    <span class="bc-sep">/</span>
    <span class="bc-group">${groupLabel}</span>
    <span class="bc-sep">/</span>
    <span class="bc-current">${pageText(page, "title")}</span>
  `;
}

function buildPageOutline() {
  const headings = Array.from(docContent.querySelectorAll("h2, h3"));
  if (!headings.length) {
    pageOutline.hidden = true;
    pageOutline.innerHTML = "";
    return;
  }

  const items = headings.map((heading) => {
    return {
      id: heading.id,
      level: heading.tagName.toLowerCase(),
      text: heading.textContent?.trim() || "Section",
    };
  });

  pageOutline.hidden = false;
  pageOutline.innerHTML = `
    <div class="outline-card">
      <p class="outline-title">${uiText("outlineTitle")}</p>
      <nav class="outline-nav" aria-label="${uiText("outlineTitle")}">
        ${items
          .map(
            (item) => `
              <a class="outline-link ${item.level}" href="#" data-doc-anchor="${item.id}">
                ${item.text}
              </a>
            `,
          )
          .join("")}
      </nav>
    </div>
  `;
}

function setupScrollSpy() {
  const headings = Array.from(docContent.querySelectorAll("h2, h3"));
  if (!headings.length) return;

  const links = Array.from(pageOutline.querySelectorAll(".outline-link"));
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const id = entry.target.id;
          links.forEach((link) => {
            link.classList.toggle("active", link.getAttribute("data-doc-anchor") === id);
          });
        }
      });
    },
    { rootMargin: "-80px 0px -70% 0px", threshold: 0 }
  );

  headings.forEach((h) => observer.observe(h));
}

function replaceMermaidBlock(block, index) {
  const source = block.textContent || "";
  const sourceContainer = block.parentElement;
  if (!sourceContainer) {
    return null;
  }

  const shell = document.createElement("div");
  shell.className = "mermaid-shell";
  shell.dataset.mermaidIndex = String(index);

  const diagram = document.createElement("div");
  diagram.className = "mermaid";
  diagram.id = `mermaid-diagram-${++mermaidDiagramId}`;
  diagram.textContent = source;

  shell.appendChild(diagram);
  sourceContainer.replaceWith(shell);
  return { diagram, shell, source };
}

function showMermaidFailure(renderTarget, error) {
  if (!renderTarget || !renderTarget.shell.isConnected) {
    return;
  }

  const { shell, source } = renderTarget;
  const notice = document.createElement("div");
  notice.className = "mermaid-error";
  notice.setAttribute("role", "status");

  const title = document.createElement("strong");
  title.textContent = uiText("mermaidErrorTitle");

  const message = document.createElement("p");
  message.textContent = uiText("mermaidErrorBody");

  const detail = document.createElement("p");
  detail.className = "mermaid-error-detail";
  detail.textContent = mermaidErrorMessage(error);

  const sourceContainer = document.createElement("pre");
  const sourceCode = document.createElement("code");
  sourceCode.className = "mermaid-source";
  sourceCode.textContent = source;
  sourceContainer.appendChild(sourceCode);

  notice.append(title, message, detail);
  shell.replaceChildren(notice, sourceContainer);
  shell.dataset.mermaidStatus = "error";
}

function mermaidErrorMessage(error) {
  if (error instanceof Error) {
    return error.message;
  }
  if (error && typeof error === "object") {
    const knownMessage = error.message || error.str || error.error?.message;
    if (knownMessage) {
      return String(knownMessage);
    }
    try {
      return JSON.stringify(error);
    } catch (_serializationError) {
      return String(error);
    }
  }
  return String(error || "Unknown Mermaid error");
}

function nameRenderedDiagram(renderTarget, index) {
  const svg = renderTarget.shell.querySelector("svg");
  if (!svg) {
    return;
  }
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${pageTitle.textContent || "Documentation"} — ${uiText("diagramLabel")} ${index + 1}`);
}

async function renderMermaidBlock(block, index, generation) {
  if (generation !== pageRenderGeneration || !block.isConnected) {
    return;
  }
  const renderTarget = replaceMermaidBlock(block, index);
  if (!renderTarget) {
    return;
  }

  try {
    await window.mermaid.parse(renderTarget.source);
    if (generation !== pageRenderGeneration || !renderTarget.shell.isConnected) {
      return;
    }
    await window.mermaid.run({ nodes: [renderTarget.diagram], suppressErrors: false });
    if (generation !== pageRenderGeneration || !renderTarget.shell.isConnected) {
      return;
    }
    nameRenderedDiagram(renderTarget, index);
    renderTarget.shell.dataset.mermaidStatus = "rendered";
  } catch (error) {
    console.error(`Mermaid diagram ${index + 1} failed`, error);
    if (generation === pageRenderGeneration) {
      showMermaidFailure(renderTarget, error);
    }
  }
}

async function renderMermaidBlocks(generation) {
  const blocks = Array.from(docContent.querySelectorAll("pre > code.language-mermaid"));
  if (!blocks.length) {
    return;
  }

  if (!window.mermaid) {
    blocks.forEach((block, index) => {
      const renderTarget = replaceMermaidBlock(block, index);
      showMermaidFailure(renderTarget, new Error("Mermaid library did not load."));
    });
    return;
  }

  if (!mermaidInitialized) {
    try {
      window.mermaid.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        suppressErrorRendering: true,
        theme: "base",
        themeVariables: {
          fontFamily: '"Segoe UI Variable Text", "Segoe UI", sans-serif',
          primaryColor: "#eef5ef",
          primaryTextColor: "#1e2a2f",
          primaryBorderColor: "#0f6c5c",
          lineColor: "#355f56",
          secondaryColor: "#eef2ff",
          tertiaryColor: "#ffffff",
        },
      });
      mermaidInitialized = true;
    } catch (error) {
      console.error("Mermaid initialization failed", error);
      blocks.forEach((block, index) => {
        const renderTarget = replaceMermaidBlock(block, index);
        showMermaidFailure(renderTarget, error);
      });
      return;
    }
  }

  for (const [index, block] of blocks.entries()) {
    if (generation !== pageRenderGeneration) {
      break;
    }
    await renderMermaidBlock(block, index, generation);
  }
}

function renderMarkdown(markdown) {
  if (window.marked && window.DOMPurify) {
    const rendered = window.marked.parse(markdown);
    docContent.innerHTML = window.DOMPurify.sanitize(rendered, {
      USE_PROFILES: { html: true },
      FORBID_TAGS: ["style"],
    });
    return true;
  }

  const notice = document.createElement("p");
  notice.className = "dependency-warning";
  notice.setAttribute("role", "status");
  notice.textContent = uiText("markdownFallback");
  const sourceContainer = document.createElement("pre");
  const sourceCode = document.createElement("code");
  sourceCode.textContent = markdown;
  sourceContainer.appendChild(sourceCode);
  docContent.replaceChildren(notice, sourceContainer);
  return false;
}

function scrollToDocAnchor(targetId, behavior = "smooth") {
  if (!targetId) {
    return false;
  }

  const target = docContent.querySelector(`#${CSS.escape(targetId)}`);
  if (!target) {
    return false;
  }

  target.scrollIntoView({ behavior, block: "start" });
  return true;
}

function wireDocAnchors() {
  pageOutline.querySelectorAll("[data-doc-anchor]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const targetId = link.getAttribute("data-doc-anchor");
      scrollToDocAnchor(targetId);
    });
  });
}

function wireMarkdownAnchors(page) {
  docContent.querySelectorAll("a[href^='#']").forEach((link) => {
    link.addEventListener("click", (event) => {
      const href = link.getAttribute("href") || "";
      if (!href || href === "#") {
        return;
      }

      if (href.startsWith("#/")) {
        const [targetSlug, targetAnchor = ""] = href.slice(2).split("#");
        if (targetSlug !== page.slug || !targetAnchor) {
          return;
        }

        event.preventDefault();
        const decodedAnchor = decodeURIComponent(targetAnchor);
        if (scrollToDocAnchor(decodedAnchor)) {
          window.history.replaceState(null, "", `#/${page.slug}#${encodeURIComponent(decodedAnchor)}`);
        }
        return;
      }

      event.preventDefault();
      const decodedAnchor = decodeURIComponent(href.slice(1));
      if (scrollToDocAnchor(decodedAnchor)) {
        window.history.replaceState(null, "", `#/${page.slug}#${encodeURIComponent(decodedAnchor)}`);
      }
    });
  });
}

function searchHaystack(page) {
  return [
    page.title,
    page.blurb,
    page.titleByLang?.en,
    page.titleByLang?.zh,
    page.blurbByLang?.en,
    page.blurbByLang?.zh,
    page.keywords,
    embeddedContent[page.slug],
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function renderNav(filter = "") {
  const normalized = filter.trim().toLowerCase();
  const active = currentSlug();
  const pages = DOC_PAGES.filter(pageMatchesLanguage).filter((page) => {
    if (!normalized) {
      return true;
    }

    return searchHaystack(page).includes(normalized);
  });

  const sections = NAV_GROUPS.map((group) => {
    const groupedPages = pages.filter((page) => page.audience === group);
    if (!groupedPages.length) {
      return "";
    }

    return `
      <section class="nav-section" aria-label="${UI_COPY[activeLang].groups[group]}">
        <p class="nav-section-title">${UI_COPY[activeLang].groups[group]}</p>
        ${groupedPages
          .map(
            (page) => `
              <a class="page-link ${page.slug === active ? "active" : ""}" href="#/${page.slug}">
                <strong>${pageText(page, "title")}</strong>
                <span>${pageText(page, "blurb")}</span>
              </a>
            `,
          )
          .join("")}
      </section>
    `;
  }).join("");

  nav.innerHTML = sections || `<p class="nav-empty">${uiText("noPages")}</p>`;
}

// ──────────────────────────────────────────────────────────────────────────
// Interactive 45-Tool Explorer
// ──────────────────────────────────────────────────────────────────────────

const TOOL_CATEGORIES_LIST = [
  { key: "all", labelZh: "全部 (45)", labelEn: "All (45)" },
  { key: "search", labelZh: "🔍 核心搜尋 (1)", labelEn: "🔍 Search (1)" },
  { key: "query", labelZh: "🧠 查詢智能 (3)", labelEn: "🧠 Query Intel (3)" },
  { key: "discovery", labelZh: "📑 文章探索 (5)", labelEn: "📑 Discovery (5)" },
  { key: "fulltext", labelZh: "📄 全文工具 (2)", labelEn: "📄 Full Text (2)" },
  { key: "figure", labelZh: "🖼️ 圖表擷取 (1)", labelEn: "🖼️ Figures (1)" },
  { key: "ncbi", labelZh: "🧬 基因與化合物 (7)", labelEn: "🧬 Genes & Drugs (7)" },
  { key: "citation", labelZh: "🌳 引用網絡 (1)", labelEn: "🌳 Citations (1)" },
  { key: "export", labelZh: "📤 匯出與筆記 (2)", labelEn: "📤 Export (2)" },
  { key: "session", labelZh: "💾 Session 管理 (5)", labelEn: "💾 Session (5)" },
  { key: "institutional", labelZh: "🏥 機構訂閱 (5)", labelEn: "🏥 Library OpenURL (5)" },
  { key: "vision", labelZh: "👁️ 視覺搜尋 (2)", labelEn: "👁️ Vision (2)" },
  { key: "chronicle", labelZh: "🕰️ 研究編年史 (2)", labelEn: "🕰️ Chronicle (2)" },
  { key: "pipeline", labelZh: "🔁 Pipeline 工作流 (7)", labelEn: "🔁 Pipelines (7)" },
];

function renderToolCategoryChips() {
  if (!toolCategoryChips) return;
  toolCategoryChips.innerHTML = TOOL_CATEGORIES_LIST.map((cat) => {
    const label = activeLang === "zh" ? cat.labelZh : cat.labelEn;
    const isActive = cat.key === selectedToolCategory;
    return `
      <button class="tool-cat-chip ${isActive ? "active" : ""}" data-cat="${cat.key}" type="button">
        ${label}
      </button>
    `;
  }).join("");

  toolCategoryChips.querySelectorAll(".tool-cat-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectedToolCategory = btn.dataset.cat;
      renderToolCategoryChips();
      renderToolCards();
    });
  });
}

function renderToolCards() {
  if (!toolCardsGrid) return;
  const keyword = (toolSearchInput?.value || "").trim().toLowerCase();

  const filtered = MCP_TOOLS_DATA.filter((tool) => {
    const matchCat = selectedToolCategory === "all" || tool.cat === selectedToolCategory;
    if (!matchCat) return false;
    if (!keyword) return true;

    const summaryText = (tool.summary.zh + " " + tool.summary.en).toLowerCase();
    const catNameText = (tool.catName.zh + " " + tool.catName.en).toLowerCase();
    return (
      tool.name.toLowerCase().includes(keyword) ||
      summaryText.includes(keyword) ||
      catNameText.includes(keyword) ||
      tool.example.toLowerCase().includes(keyword)
    );
  });

  if (toolCountBadge) {
    toolCountBadge.textContent = `${filtered.length} / ${MCP_TOOLS_DATA.length}`;
  }

  if (!filtered.length) {
    toolCardsGrid.innerHTML = `
      <div class="tool-empty-card">
        <p>🔍 ${activeLang === "zh" ? "查無符合的 MCP 工具，請嘗試其他關鍵字（如 pmid, fulltext, figure, 基因, rct）" : "No matching MCP tools found. Try keywords like pmid, fulltext, figure, rct, export."}</p>
      </div>
    `;
    return;
  }

  toolCardsGrid.innerHTML = filtered.map((tool) => {
    const catLabel = activeLang === "zh" ? tool.catName.zh : tool.catName.en;
    const summary = activeLang === "zh" ? tool.summary.zh : tool.summary.en;
    const translatedDocSlug = activeLang === "zh" ? `${tool.docLink}-zh` : tool.docLink;

    return `
      <div class="tool-card" data-tool="${tool.name}">
        <div class="tool-card-header">
          <div class="tool-name-wrap">
            <span class="tool-icon">${tool.icon}</span>
            <strong class="tool-name">${tool.name}</strong>
          </div>
          <span class="tool-cat-badge cat-${tool.cat}">${catLabel}</span>
        </div>
        <p class="tool-summary">${summary}</p>
        <div class="tool-example-wrap">
          <code class="tool-example">${tool.example}</code>
          <button class="tool-copy-btn" data-copy="${tool.name}" title="Copy tool call" type="button">📋 ${uiText("copyToolCode")}</button>
        </div>
        <div class="tool-card-footer">
          <a class="tool-doc-link" href="#/${translatedDocSlug}">📖 ${activeLang === "zh" ? "查看使用指南 →" : "View Handbook →"}</a>
        </div>
      </div>
    `;
  }).join("");

  toolCardsGrid.querySelectorAll(".tool-copy-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const code = btn.previousElementSibling?.textContent || btn.dataset.copy;
      try {
        await navigator.clipboard.writeText(code);
        btn.textContent = `✅ ${uiText("copiedToolCode")}`;
        setTimeout(() => {
          btn.textContent = `📋 ${uiText("copyToolCode")}`;
        }, 1500);
      } catch (_e) {
        btn.textContent = "Error";
      }
    });
  });
}

// ──────────────────────────────────────────────────────────────────────────
// Universal Global Search Modal (Ctrl+K)
// ──────────────────────────────────────────────────────────────────────────

function openSearchModal() {
  if (!searchModalBackdrop) return;
  searchModalBackdrop.hidden = false;
  modalSearchInput.value = "";
  modalSearchInput.focus();
  renderSearchResults("");
}

function closeSearchModal() {
  if (!searchModalBackdrop) return;
  searchModalBackdrop.hidden = true;
}

function renderSearchResults(query) {
  if (!modalSearchResults) return;
  const q = query.trim().toLowerCase();
  if (!q) {
    modalSearchResults.innerHTML = `
      <p class="modal-search-hint">
        💡 ${activeLang === "zh" ? "輸入關鍵字搜尋文檔章節、概念或 45 個 MCP 工具..." : "Type a keyword to search across documents, headings, and all 45 tools..."}
      </p>
    `;
    return;
  }

  const results = [];

  // Search in tools
  MCP_TOOLS_DATA.forEach((tool) => {
    const summary = activeLang === "zh" ? tool.summary.zh : tool.summary.en;
    const catName = activeLang === "zh" ? tool.catName.zh : tool.catName.en;
    if (
      tool.name.toLowerCase().includes(q) ||
      summary.toLowerCase().includes(q) ||
      catName.toLowerCase().includes(q)
    ) {
      results.push({
        type: "tool",
        icon: "🛠️",
        title: tool.name,
        badge: catName,
        detail: summary,
        url: `#/${activeLang === "zh" ? `${tool.docLink}-zh` : tool.docLink}`,
      });
    }
  });

  // Search in pages
  DOC_PAGES.filter(pageMatchesLanguage).forEach((page) => {
    const title = pageText(page, "title");
    const blurb = pageText(page, "blurb");
    const haystack = searchHaystack(page);
    if (haystack.includes(q)) {
      results.push({
        type: "page",
        icon: "📄",
        title: title,
        badge: UI_COPY[activeLang].groups[page.audience] || page.audience,
        detail: blurb,
        url: `#/${page.slug}`,
      });
    }
  });

  if (!results.length) {
    modalSearchResults.innerHTML = `
      <p class="modal-search-empty">
        ${activeLang === "zh" ? `找不到與「<strong>${query}</strong>」相關的結果` : `No results found for "<strong>${query}</strong>"`}
      </p>
    `;
    return;
  }

  activeModalResultIndex = 0;
  modalSearchResults.innerHTML = results.slice(0, 15).map((r, i) => `
    <a class="modal-search-item ${i === 0 ? "selected" : ""}" href="${r.url}" data-index="${i}">
      <span class="ms-icon">${r.icon}</span>
      <div class="ms-body">
        <div class="ms-header">
          <strong>${r.title}</strong>
          <span class="ms-badge">${r.badge}</span>
        </div>
        <p class="ms-detail">${r.detail}</p>
      </div>
    </a>
  `).join("");

  modalSearchResults.querySelectorAll(".modal-search-item").forEach((item) => {
    item.addEventListener("click", () => {
      closeSearchModal();
    });
  });
}

// ──────────────────────────────────────────────────────────────────────────
// Reading Progress & Back to Top
// ──────────────────────────────────────────────────────────────────────────

function handleScroll() {
  const scrollY = window.scrollY || document.documentElement.scrollTop;
  const height = document.documentElement.scrollHeight - document.documentElement.clientHeight;
  const progress = height > 0 ? (scrollY / height) * 100 : 0;

  if (readingProgressBar) {
    readingProgressBar.style.width = `${progress}%`;
  }

  if (backToTopBtn) {
    backToTopBtn.classList.toggle("visible", scrollY > 300);
  }
}

// ──────────────────────────────────────────────────────────────────────────
// Main Page Rendering
// ──────────────────────────────────────────────────────────────────────────

async function renderPage() {
  const generation = ++pageRenderGeneration;
  const requestedSlug = currentSlug();
  let page = pageBySlug(requestedSlug);

  if (!page) {
    page = pageBySlug(defaultSlugForLanguage(activeLang)) || DOC_PAGES[0];
    window.location.hash = `#/${page.slug}`;
    return;
  }

  if (page.lang !== "all" && page.lang !== activeLang) {
    activeLang = page.lang;
    persistLanguage(activeLang);
  }

  localizeStaticText();
  renderLanguageControls();
  pageTitle.textContent = pageText(page, "title");
  pageKicker.textContent = pageText(page, "blurb");
  renderNav(filterInput.value);
  updateBreadcrumbs(page);

  // Show Tool Explorer widget prominently on overview & user guide pages
  if (toolExplorerWidget) {
    const isOverview = page.group === "overview" || page.group === "tools-usage-guide" || page.group === "quick-reference";
    toolExplorerWidget.classList.toggle("pinned-open", isOverview);
    renderToolCategoryChips();
    renderToolCards();
  }

  try {
    const markdown = embeddedContent[page.slug];
    if (!markdown) {
      throw new Error(`Missing embedded content for ${page.slug}. Run uv run python scripts/build_docs_site.py.`);
    }
    if (!renderMarkdown(markdown)) {
      return;
    }
    ensureHeadingIds();
    wrapScrollableTables();
    wrapLocalImages();
    injectCodeCopyButtons();
    buildPageOutline();
    setupScrollSpy();
    wireDocAnchors();
    wireMarkdownAnchors(page);
    await renderMermaidBlocks(generation);
    if (generation !== pageRenderGeneration) {
      return;
    }

    docContent.querySelectorAll("a[href^='http']").forEach((link) => {
      link.setAttribute("target", "_blank");
      link.setAttribute("rel", "noreferrer noopener");
    });

    const targetAnchor = anchorFromHash();
    if (targetAnchor) {
      requestAnimationFrame(() => {
        if (!scrollToDocAnchor(targetAnchor, "instant")) {
          window.scrollTo({ top: 0, behavior: "instant" });
        }
      });
    } else {
      window.scrollTo({ top: 0, behavior: "instant" });
    }
  } catch (error) {
    const title = document.createElement("h3");
    title.textContent = uiText("unableTitle");
    const detail = document.createElement("p");
    detail.textContent = String(error);
    const recovery = document.createElement("p");
    recovery.append(`${uiText("regenerate")} `);
    const command = document.createElement("code");
    command.textContent = "uv run python scripts/build_docs_site.py";
    recovery.append(command, ` ${uiText("regenerateSuffix")}`);
    docContent.replaceChildren(title, detail, recovery);
  }
}

// ──────────────────────────────────────────────────────────────────────────
// Event Listeners & Hub Navigation
// ──────────────────────────────────────────────────────────────────────────

filterInput.addEventListener("input", (event) => {
  renderNav(event.target.value);
});

if (toolSearchInput) {
  toolSearchInput.addEventListener("input", () => {
    renderToolCards();
  });
}

languageControls.forEach((button) => {
  button.addEventListener("click", () => {
    switchLanguage(button.dataset.lang);
  });
});

navToggle.addEventListener("click", () => {
  const isOpen = sidebar.classList.toggle("open");
  navToggle.setAttribute("aria-expanded", String(isOpen));
  if (sidebarBackdrop) {
    sidebarBackdrop.hidden = !isOpen;
  }
});

if (sidebarBackdrop) {
  sidebarBackdrop.addEventListener("click", closeSidebar);
}

if (globalSearchBtn) {
  globalSearchBtn.addEventListener("click", openSearchModal);
}
if (topbarSearchBtn) {
  topbarSearchBtn.addEventListener("click", openSearchModal);
}
if (modalSearchClose) {
  modalSearchClose.addEventListener("click", closeSearchModal);
}
if (searchModalBackdrop) {
  searchModalBackdrop.addEventListener("click", (e) => {
    if (e.target === searchModalBackdrop) closeSearchModal();
  });
}

if (modalSearchInput) {
  modalSearchInput.addEventListener("input", (e) => {
    renderSearchResults(e.target.value);
  });
  modalSearchInput.addEventListener("keydown", (e) => {
    const items = modalSearchResults.querySelectorAll(".modal-search-item");
    if (!items.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeModalResultIndex = (activeModalResultIndex + 1) % items.length;
      items.forEach((item, i) => item.classList.toggle("selected", i === activeModalResultIndex));
      items[activeModalResultIndex].scrollIntoView({ block: "nearest" });
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeModalResultIndex = (activeModalResultIndex - 1 + items.length) % items.length;
      items.forEach((item, i) => item.classList.toggle("selected", i === activeModalResultIndex));
      items[activeModalResultIndex].scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") {
      e.preventDefault();
      const selected = items[activeModalResultIndex];
      if (selected) {
        selected.click();
      }
    }
  });
}

if (topicHubNav) {
  topicHubNav.querySelectorAll(".topic-hub-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      topicHubNav.querySelectorAll(".topic-hub-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const hub = btn.dataset.hub;
      if (hub === "tools") {
        if (toolExplorerWidget) {
          toolExplorerWidget.scrollIntoView({ behavior: "smooth" });
          toolSearchInput?.focus();
        }
      } else if (hub === "user") {
        window.location.hash = `#/${activeLang === "zh" ? "user-guide-zh" : "user-guide"}`;
      } else if (hub === "chronicle") {
        window.location.hash = `#/${activeLang === "zh" ? "advanced-workflows-zh" : "advanced-workflows"}`;
      } else if (hub === "pipeline") {
        window.location.hash = `#/${activeLang === "zh" ? "pipeline-tutorial-zh" : "pipeline-tutorial"}`;
      } else if (hub === "dev") {
        window.location.hash = `#/architecture`;
      } else {
        window.location.hash = `#/${defaultSlugForLanguage(activeLang)}`;
      }
    });
  });
}

if (backToTopBtn) {
  backToTopBtn.addEventListener("click", () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

window.addEventListener("scroll", handleScroll, { passive: true });

window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeSidebar();
    closeSearchModal();
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    openSearchModal();
  }
  if (event.key === "/" && document.activeElement && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") {
    event.preventDefault();
    openSearchModal();
  }
});

window.addEventListener("hashchange", () => {
  closeSidebar();
  closeSearchModal();
  renderPage();
});

window.addEventListener("DOMContentLoaded", () => {
  localizeStaticText();
  renderLanguageControls();
  renderNav();
  renderPage();
});
