#!/usr/bin/env node

/**
 * Parse and render every Mermaid diagram found in .mmd files and Markdown.
 *
 * Dependencies deliberately live outside this repository. Point
 * MERMAID_NODE_MODULES at a node_modules directory containing the pinned
 * mermaid and jsdom packages used by CI.
 */

import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

const SUPPORTED_EXTENSIONS = new Set([".md", ".mmd"]);
const MAX_MERMAID_CHARACTERS = 49_000;
const DIAGRAM_TIMEOUT_MS = 10_000;
const EXPECTED_MERMAID_VERSION = "11.16.1";
const EXPECTED_JSDOM_VERSION = "26.1.0";

function usage() {
  return [
    "Usage: MERMAID_NODE_MODULES=/path/to/node_modules node",
    "       scripts/check_mermaid_rendering.mjs <file-or-directory> [...]",
    "",
    "Markdown files are scanned for Mermaid fenced code blocks; .mmd files",
    "are treated as single diagrams. Directories are scanned recursively.",
  ].join("\n");
}

function dependencyEntry(moduleRoot, ...segments) {
  return pathToFileURL(path.join(moduleRoot, ...segments)).href;
}

async function loadRenderingDependencies() {
  const configuredRoot = process.env.MERMAID_NODE_MODULES;
  if (!configuredRoot) {
    throw new Error(
      "MERMAID_NODE_MODULES must point to a node_modules directory containing mermaid and jsdom.",
    );
  }

  const moduleRoot = path.resolve(configuredRoot);
  const mermaidPackage = JSON.parse(
    await fs.readFile(path.join(moduleRoot, "mermaid", "package.json"), "utf8"),
  );
  const jsdomPackage = JSON.parse(
    await fs.readFile(path.join(moduleRoot, "jsdom", "package.json"), "utf8"),
  );
  if (mermaidPackage.version !== EXPECTED_MERMAID_VERSION) {
    throw new Error(
      `Expected Mermaid ${EXPECTED_MERMAID_VERSION}, found ${mermaidPackage.version || "unknown"}.`,
    );
  }
  if (jsdomPackage.version !== EXPECTED_JSDOM_VERSION) {
    throw new Error(
      `Expected jsdom ${EXPECTED_JSDOM_VERSION}, found ${jsdomPackage.version || "unknown"}.`,
    );
  }
  const { JSDOM } = await import(dependencyEntry(moduleRoot, "jsdom", "lib", "api.js"));
  return { JSDOM, moduleRoot };
}

function installBrowserGlobals(JSDOM) {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    pretendToBeVisual: true,
  });
  const { window } = dom;

  globalThis.window = window;
  globalThis.document = window.document;
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: window.navigator,
  });
  globalThis.Element = window.Element;
  globalThis.HTMLElement = window.HTMLElement;
  globalThis.SVGElement = window.SVGElement;
  globalThis.CSSStyleSheet = window.CSSStyleSheet;
  globalThis.Node = window.Node;
  globalThis.getComputedStyle = window.getComputedStyle.bind(window);
  globalThis.requestAnimationFrame = window.requestAnimationFrame.bind(window);
  globalThis.cancelAnimationFrame = window.cancelAnimationFrame.bind(window);

  if (!window.matchMedia) {
    window.matchMedia = () => ({
      matches: false,
      media: "",
      onchange: null,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      dispatchEvent() {
        return false;
      },
    });
  }

  // jsdom intentionally omits layout. Mermaid only needs deterministic text
  // dimensions to calculate a valid SVG during this syntax/render smoke test.
  if (!window.SVGElement.prototype.getBBox) {
    window.SVGElement.prototype.getBBox = function getBBox() {
      const textLength = this.textContent?.length ?? 0;
      return { x: 0, y: 0, width: Math.max(1, textLength * 8), height: 16 };
    };
  }
  if (!window.SVGElement.prototype.getComputedTextLength) {
    window.SVGElement.prototype.getComputedTextLength = function getComputedTextLength() {
      return Math.max(1, (this.textContent?.length ?? 0) * 8);
    };
  }

  // Mermaid mindmaps use Cytoscape, whose renderer probes a 2D canvas even
  // though this smoke test only consumes the returned SVG. jsdom has no
  // canvas implementation, so provide deterministic layout-safe primitives.
  window.HTMLCanvasElement.prototype.getContext = function getContext() {
    const canvas = this;
    const gradient = { addColorStop() {} };
    const context = {
      canvas,
      createLinearGradient() {
        return gradient;
      },
      createPattern() {
        return null;
      },
      createRadialGradient() {
        return gradient;
      },
      getImageData() {
        return { data: new Uint8ClampedArray(4), height: 1, width: 1 };
      },
      measureText(text) {
        return { width: Math.max(1, String(text).length * 8) };
      },
    };
    return new Proxy(context, {
      get(target, property) {
        if (property in target) {
          return target[property];
        }
        return () => {};
      },
      set(target, property, value) {
        target[property] = value;
        return true;
      },
    });
  };

  return dom;
}

function isMermaidInfoString(infoString) {
  const normalized = infoString.trim().toLowerCase();
  return (
    /^mermaid(?:\s|$)/.test(normalized) ||
    /^\{\s*\.mermaid(?:\s|\}|$)/.test(normalized)
  );
}

function markdownDiagrams(source, filePath) {
  const lines = source.split(/\r?\n/);
  const diagrams = [];

  for (let index = 0; index < lines.length; index += 1) {
    const opening = lines[index].match(/^ {0,3}(`{3,}|~{3,})[ \t]*(.*)$/);
    if (!opening || !isMermaidInfoString(opening[2])) {
      continue;
    }

    const fenceCharacter = opening[1][0];
    const minimumFenceLength = opening[1].length;
    const firstSourceLine = index + 2;
    const body = [];
    let closed = false;

    for (index += 1; index < lines.length; index += 1) {
      const closing = lines[index].match(/^ {0,3}(`+|~+)[ \t]*$/);
      if (
        closing &&
        closing[1][0] === fenceCharacter &&
        closing[1].length >= minimumFenceLength
      ) {
        closed = true;
        break;
      }
      body.push(lines[index]);
    }

    if (!closed) {
      throw new Error(`Unclosed Mermaid fence at ${filePath}:${firstSourceLine - 1}`);
    }

    diagrams.push({
      label: `${filePath}:${firstSourceLine}`,
      source: body.join("\n").trim(),
    });
  }

  return diagrams;
}

async function collectFiles(inputPath) {
  const stats = await fs.stat(inputPath);
  if (stats.isFile()) {
    const extension = path.extname(inputPath).toLowerCase();
    if (!SUPPORTED_EXTENSIONS.has(extension)) {
      throw new Error(`Unsupported input file: ${inputPath}`);
    }
    return [inputPath];
  }
  if (!stats.isDirectory()) {
    throw new Error(`Input is neither a file nor a directory: ${inputPath}`);
  }

  const files = [];
  const entries = await fs.readdir(inputPath, { withFileTypes: true });
  entries.sort((left, right) => left.name.localeCompare(right.name));
  for (const entry of entries) {
    const childPath = path.join(inputPath, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await collectFiles(childPath)));
    } else if (entry.isFile() && SUPPORTED_EXTENSIONS.has(path.extname(entry.name).toLowerCase())) {
      files.push(childPath);
    }
  }
  return files;
}

async function readDiagrams(filePath) {
  const source = await fs.readFile(filePath, "utf8");
  if (path.extname(filePath).toLowerCase() === ".mmd") {
    return [{ label: `${filePath}:1`, source: source.trim() }];
  }
  return markdownDiagrams(source, filePath);
}

function formatError(error) {
  if (error instanceof Error) {
    return String(error.stack || error.message).replaceAll("\n", "\n    ");
  }
  return String(error);
}

async function withTimeout(promise, label) {
  let timeoutId;
  const timeout = new Promise((_resolve, reject) => {
    timeoutId = setTimeout(
      () => reject(new Error(`${label} exceeded ${DIAGRAM_TIMEOUT_MS} ms.`)),
      DIAGRAM_TIMEOUT_MS,
    );
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    clearTimeout(timeoutId);
  }
}

async function main() {
  const inputs = process.argv.slice(2);
  if (inputs.length === 0 || inputs.includes("--help") || inputs.includes("-h")) {
    console.log(usage());
    process.exitCode = inputs.length === 0 ? 2 : 0;
    return;
  }

  const files = [
    ...new Set(
      (
        await Promise.all(inputs.map((inputPath) => collectFiles(path.resolve(inputPath))))
      ).flat(),
    ),
  ].sort();
  const diagrams = (
    await Promise.all(files.map((filePath) => readDiagrams(path.relative(process.cwd(), filePath))))
  ).flat();

  if (diagrams.length === 0) {
    console.log(`Mermaid rendering check: no diagrams found in ${files.length} file(s).`);
    return;
  }

  const { JSDOM, moduleRoot } = await loadRenderingDependencies();
  const dom = installBrowserGlobals(JSDOM);
  // Mermaid (and DOMPurify) must be imported after browser globals exist.
  const mermaidModule = await import(
    dependencyEntry(moduleRoot, "mermaid", "dist", "mermaid.esm.mjs")
  );
  const mermaid = mermaidModule.default;
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    deterministicIds: true,
    suppressErrorRendering: true,
    layout: "dagre",
    theme: "default",
  });

  const failures = [];
  for (const [index, diagram] of diagrams.entries()) {
    if (!diagram.source) {
      failures.push({ label: diagram.label, error: new Error("Mermaid diagram is empty.") });
      continue;
    }
    if (diagram.source.length > MAX_MERMAID_CHARACTERS) {
      failures.push({
        label: diagram.label,
        error: new Error(
          `Diagram has ${diagram.source.length} characters; limit is ${MAX_MERMAID_CHARACTERS}.`,
        ),
      });
      continue;
    }

    try {
      await withTimeout(
        mermaid.parse(diagram.source, { suppressErrors: false }),
        `Parse for ${diagram.label}`,
      );
      const container = document.createElement("div");
      document.body.appendChild(container);
      try {
        const result = await withTimeout(
          mermaid.render(`mermaid-smoke-${index + 1}`, diagram.source, container),
          `SVG render for ${diagram.label}`,
        );
        if (!result.svg?.includes("<svg")) {
          throw new Error("Mermaid render completed without returning SVG output.");
        }
        if (/maximum text size|syntax error in text/i.test(result.svg)) {
          throw new Error("Mermaid returned an error SVG instead of the requested diagram.");
        }
      } finally {
        container.remove();
      }
      console.log(`PASS ${diagram.label}`);
    } catch (error) {
      failures.push({ label: diagram.label, error });
      console.error(`FAIL ${diagram.label}\n    ${formatError(error)}`);
    } finally {
      document.body.replaceChildren();
    }
  }

  dom.window.close();
  if (failures.length > 0) {
    console.error(
      `Mermaid rendering check failed: ${failures.length}/${diagrams.length} diagram(s) did not render.`,
    );
    process.exitCode = 1;
    return;
  }

  console.log(`Mermaid rendering check passed: ${diagrams.length} diagram(s) rendered to SVG.`);
}

main().catch((error) => {
  console.error(`Mermaid rendering check could not run:\n    ${formatError(error)}`);
  process.exitCode = 1;
});
