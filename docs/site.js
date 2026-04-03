const DOC_PAGES = [
  {
    slug: "overview",
    title: "Overview",
    blurb: "README, quickstart, counts-first search, and core workflow framing.",
    file: "site-content/overview.md",
  },
  {
    slug: "overview-zh",
    title: "Overview (zh-TW)",
    blurb: "Traditional Chinese overview for the main README surface.",
    file: "site-content/overview-zh.md",
  },
  {
    slug: "architecture",
    title: "Architecture",
    blurb: "DDD layers, orchestration flow, and runtime surfaces.",
    file: "site-content/architecture.md",
  },
  {
    slug: "quick-reference",
    title: "Quick Reference",
    blurb: "Fast lookup for MCP tools and categories.",
    file: "site-content/quick-reference.md",
  },
  {
    slug: "source-contracts",
    title: "Source Contracts",
    blurb: "Rate limits, rights, optional keys, and provenance semantics.",
    file: "site-content/source-contracts.md",
  },
  {
    slug: "troubleshooting",
    title: "Troubleshooting",
    blurb: "Setup, verification, integration checks, and failure recovery.",
    file: "site-content/troubleshooting.md",
  },
  {
    slug: "deployment",
    title: "Deployment",
    blurb: "HTTPS, Docker, and production deployment guidance.",
    file: "site-content/deployment.md",
  },
];

const nav = document.getElementById("page-nav");
const filterInput = document.getElementById("nav-filter");
const docContent = document.getElementById("doc-content");
const pageOutline = document.getElementById("page-outline");
const pageTitle = document.getElementById("page-title");
const pageKicker = document.getElementById("page-kicker");
const navToggle = document.getElementById("nav-toggle");
const sidebar = document.getElementById("sidebar");
const embeddedContent = window.DOC_PAGE_CONTENT || {};
let mermaidInitialized = false;

marked.setOptions({
  gfm: true,
  breaks: false,
});

function currentSlug() {
  const hash = window.location.hash.replace(/^#\/?/, "").trim();
  return hash || "overview";
}

function slugifyHeading(text) {
  return (text || "section")
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-") || "section";
}

function closeSidebar() {
  sidebar.classList.remove("open");
  navToggle.setAttribute("aria-expanded", "false");
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
      <p class="outline-title">On This Page</p>
      <nav class="outline-nav" aria-label="Section navigation">
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

function renderNav(filter = "") {
  const normalized = filter.trim().toLowerCase();
  const active = currentSlug();
  const pages = DOC_PAGES.filter((page) => {
    if (!normalized) {
      return true;
    }

    return `${page.title} ${page.blurb}`.toLowerCase().includes(normalized);
  });

  nav.innerHTML = pages
    .map(
      (page) => `
        <a class="page-link ${page.slug === active ? "active" : ""}" href="#/${page.slug}">
          <strong>${page.title}</strong>
          <span>${page.blurb}</span>
        </a>
      `,
    )
    .join("");
}

async function renderPage() {
  const slug = currentSlug();
  const page = DOC_PAGES.find((entry) => entry.slug === slug) || DOC_PAGES[0];

  if (page.slug !== slug) {
    window.location.hash = `#/${page.slug}`;
    return;
  }

  pageTitle.textContent = page.title;
  pageKicker.textContent = page.blurb;
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
      <h3>Unable to load page</h3>
      <p>${String(error)}</p>
      <p>Run <code>uv run python scripts/build_docs_site.py</code> to regenerate site content.</p>
    `;
  }
}

filterInput.addEventListener("input", (event) => {
  renderNav(event.target.value);
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
  renderNav();
  renderPage();
});
