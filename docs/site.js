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
    outlineTitle: "本頁內容",
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

  if (siteEyebrow) {
    siteEyebrow.textContent = uiText("siteEyebrow");
  }
  if (siteTagline) {
    siteTagline.textContent = uiText("tagline");
  }
  if (filterLabel) {
    filterLabel.textContent = uiText("filterLabel");
  }
  if (filterInput) {
    filterInput.placeholder = uiText("filterPlaceholder");
  }
  if (sidebarNoteText) {
    sidebarNoteText.textContent = uiText("sidebarNote");
  }
  if (heroKicker) {
    heroKicker.textContent = uiText("heroKicker");
  }
  if (heroCopy) {
    heroCopy.textContent = uiText("heroCopy");
  }
  if (navToggle) {
    navToggle.textContent = uiText("menu");
  }
  if (toolMetricLabel) {
    toolMetricLabel.textContent = uiText("toolMetric");
  }
  if (routingMetricLabel) {
    routingMetricLabel.textContent = uiText("routingMetric");
  }
  if (oaMetricLabel) {
    oaMetricLabel.textContent = uiText("oaMetric");
  }
  if (journeyGrid) {
    journeyGrid.setAttribute("aria-label", uiText("journeyLabel"));
  }
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
    buildPageOutline();
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

filterInput.addEventListener("input", (event) => {
  renderNav(event.target.value);
});

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

window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeSidebar();
  }
});

window.addEventListener("hashchange", () => {
  closeSidebar();
  renderPage();
});
window.addEventListener("DOMContentLoaded", () => {
  localizeStaticText();
  renderLanguageControls();
  renderNav();
  renderPage();
});
