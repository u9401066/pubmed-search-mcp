const DOC_PAGES = [
  {
    slug: "overview",
    group: "overview",
    lang: "en",
    audience: "start",
    title: "Overview",
    blurb: "Project positioning, quick install, supported clients, and core workflow framing.",
    file: "site-content/overview.md",
  },
  {
    slug: "overview-zh",
    group: "overview",
    lang: "zh",
    audience: "start",
    title: "總覽",
    blurb: "專案定位、快速安裝、支援 client 與核心工作流概覽。",
    file: "site-content/overview-zh.md",
  },
  {
    slug: "user-guide",
    group: "user-guide",
    lang: "en",
    audience: "user",
    title: "User Guide",
    blurb: "Practical workflows for searching, exploring, full text, exports, notes, and pipelines.",
    file: "site-content/user-guide.md",
  },
  {
    slug: "user-guide-zh",
    group: "user-guide",
    lang: "zh",
    audience: "user",
    title: "使用者指南",
    blurb: "搜尋、探索、全文、匯出、筆記與 pipeline 的實務工作流。",
    file: "site-content/user-guide-zh.md",
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
    slug: "architecture",
    group: "architecture",
    lang: "all",
    audience: "developer",
    title: "Architecture",
    titleByLang: { zh: "架構" },
    blurb: "DDD layers, orchestration flow, and runtime surfaces.",
    blurbByLang: { zh: "DDD 分層、orchestration flow 與 runtime surfaces。" },
    file: "site-content/architecture.md",
  },
  {
    slug: "quick-reference",
    group: "quick-reference",
    lang: "all",
    audience: "developer",
    title: "Quick Reference",
    titleByLang: { zh: "快速索引" },
    blurb: "Fast lookup for MCP tools and categories.",
    blurbByLang: { zh: "MCP tools 與 categories 的快速查找。" },
    file: "site-content/quick-reference.md",
  },
  {
    slug: "source-contracts",
    group: "source-contracts",
    lang: "all",
    audience: "developer",
    title: "Source Contracts",
    titleByLang: { zh: "資料來源契約" },
    blurb: "Rate limits, rights, optional keys, and provenance semantics.",
    blurbByLang: { zh: "Rate limits、rights、optional keys 與 provenance semantics。" },
    file: "site-content/source-contracts.md",
  },
  {
    slug: "troubleshooting",
    group: "troubleshooting",
    lang: "all",
    audience: "reference",
    title: "Troubleshooting",
    titleByLang: { zh: "疑難排解" },
    blurb: "Setup, verification, integration checks, and failure recovery.",
    blurbByLang: { zh: "設定、驗證、整合檢查與 failure recovery。" },
    file: "site-content/troubleshooting.md",
  },
  {
    slug: "deployment",
    group: "deployment",
    lang: "all",
    audience: "reference",
    title: "Deployment",
    titleByLang: { zh: "部署" },
    blurb: "HTTPS, Docker, Copilot Studio, and production deployment guidance.",
    blurbByLang: { zh: "HTTPS、Docker、Copilot Studio 與 production deployment 指南。" },
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
    tagline: "Role-aware documentation for researchers, AI-client users, and maintainers.",
    filterLabel: "Filter pages",
    filterPlaceholder: "overview, guide, tutorial, deployment...",
    sidebarNote: "Use the language switch for translated pages. Reference pages without a separate translation stay visible in both modes.",
    heroKicker: "Docs for users and developers",
    heroCopy:
      "This site turns the repository docs into a role-aware handbook: user workflows, developer architecture, generated tool references, pipeline tutorials, source contracts, troubleshooting, and deployment.",
    menu: "Menu",
    outlineTitle: "On This Page",
    noPages: "No pages match this filter.",
    unableTitle: "Unable to load page",
    regenerate: "Run",
    regenerateSuffix: "to regenerate site content.",
    toolMetric: "generated tool index",
    routingMetric: "agent routing support",
    oaMetric: "full text and figures",
    groups: {
      start: "Start Here",
      user: "For Users",
      developer: "For Developers",
      reference: "Reference",
    },
  },
  zh: {
    siteEyebrow: "文件網站",
    tagline: "給研究者、AI client 使用者與維護者的角色導向文件。",
    filterLabel: "篩選頁面",
    filterPlaceholder: "總覽、指南、教學、部署...",
    sidebarNote: "使用語言切換查看翻譯頁；沒有獨立翻譯的 reference 頁會在兩種語言模式都顯示。",
    heroKicker: "給使用者與開發者的文件",
    heroCopy:
      "這個網站把 repo 文件整理成角色導向手冊：使用者工作流、開發者架構、生成工具索引、pipeline 教學、source contracts、疑難排解與部署。",
    menu: "選單",
    outlineTitle: "本頁內容",
    noPages: "沒有符合篩選條件的頁面。",
    unableTitle: "無法載入頁面",
    regenerate: "請執行",
    regenerateSuffix: "重新生成 site content。",
    toolMetric: "生成工具索引",
    routingMetric: "agent 路由支援",
    oaMetric: "全文與圖表",
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
const siteEyebrow = document.getElementById("site-eyebrow");
const siteTagline = document.getElementById("site-tagline");
const sidebarNoteText = document.getElementById("sidebar-note-text");
const heroKicker = document.getElementById("hero-kicker");
const heroCopy = document.getElementById("hero-copy");
const toolMetricLabel = document.getElementById("tool-metric-label");
const routingMetricLabel = document.getElementById("routing-metric-label");
const oaMetricLabel = document.getElementById("oa-metric-label");
const languageControls = Array.from(document.querySelectorAll("[data-lang]"));
const embeddedContent = window.DOC_PAGE_CONTENT || {};
let mermaidInitialized = false;
let activeLang = preferredLanguage();

marked.setOptions({
  gfm: true,
  breaks: false,
});

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
  return window.location.hash.replace(/^#\/?/, "").trim();
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
      .replace(/\s+/g, "-")
      .replace(/-+/g, "-") || "section"
  );
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

function buildPageOutline() {
  const headings = Array.from(docContent.querySelectorAll("h2, h3"));
  if (!headings.length) {
    pageOutline.hidden = true;
    pageOutline.innerHTML = "";
    return;
  }

  const seen = new Map();
  const items = headings.map((heading) => {
    const baseId = slugifyHeading(heading.textContent || "section");
    const nextCount = (seen.get(baseId) || 0) + 1;
    seen.set(baseId, nextCount);

    const id = nextCount === 1 ? baseId : `${baseId}-${nextCount}`;
    heading.id = id;
    heading.tabIndex = -1;

    return {
      id,
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

async function renderMermaidBlocks() {
  const blocks = Array.from(docContent.querySelectorAll("pre > code.language-mermaid"));
  if (!blocks.length || !window.mermaid) {
    return;
  }

  if (!mermaidInitialized) {
    window.mermaid.initialize({
      startOnLoad: false,
      securityLevel: "loose",
      theme: "base",
      themeVariables: {
        fontFamily: '"Segoe UI Variable Text", "Segoe UI", sans-serif',
        primaryColor: "#eef5ef",
        primaryTextColor: "#1e2a2f",
        primaryBorderColor: "#0f6c5c",
        lineColor: "#355f56",
        secondaryColor: "#f6f0e4",
        tertiaryColor: "#ffffff",
      },
    });
    mermaidInitialized = true;
  }

  blocks.forEach((block) => {
    const shell = document.createElement("div");
    shell.className = "mermaid-shell";

    const diagram = document.createElement("div");
    diagram.className = "mermaid";
    diagram.textContent = block.textContent || "";

    shell.appendChild(diagram);
    block.parentElement.replaceWith(shell);
  });

  try {
    await window.mermaid.run({ nodes: Array.from(docContent.querySelectorAll(".mermaid")) });
  } catch (error) {
    console.error("Mermaid rendering failed", error);
  }
}

function wireDocAnchors() {
  pageOutline.querySelectorAll("[data-doc-anchor]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const targetId = link.getAttribute("data-doc-anchor");
      if (!targetId) {
        return;
      }

      const target = docContent.querySelector(`#${CSS.escape(targetId)}`);
      if (!target) {
        return;
      }

      target.scrollIntoView({ behavior: "smooth", block: "start" });
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
    docContent.innerHTML = marked.parse(markdown);
    wrapScrollableTables();
    buildPageOutline();
    wireDocAnchors();
    await renderMermaidBlocks();

    docContent.querySelectorAll("a[href^='http']").forEach((link) => {
      link.setAttribute("target", "_blank");
      link.setAttribute("rel", "noreferrer noopener");
    });

    window.scrollTo({ top: 0, behavior: "instant" });
  } catch (error) {
    docContent.innerHTML = `
      <h3>${uiText("unableTitle")}</h3>
      <p>${String(error)}</p>
      <p>${uiText("regenerate")} <code>uv run python scripts/build_docs_site.py</code> ${uiText("regenerateSuffix")}</p>
    `;
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
