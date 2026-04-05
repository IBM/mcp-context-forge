/**
 * Unit tests for the observability partial's __obsExecAndStrip helper
 * and the Alpine.mutateDom + initTree injection pattern.
 *
 * The function under test is defined inline in
 * mcpgateway/templates/observability_partial.html. We replicate its
 * logic here (same regex, same createElement approach) so we can
 * validate correctness in jsdom without loading the full template.
 *
 * NOTE: Because the helper lives in an inline template <script>, it
 * cannot be imported as a module. If the template implementation
 * changes, this replica must be updated to match.
 *
 * Covers PR #3967 — fix Alpine.js MutationObserver race condition.
 */

import { describe, test, expect, vi, beforeEach } from "vitest";
import { JSDOM } from "jsdom";

/**
 * Replica of window.__obsExecAndStrip from observability_partial.html.
 * Keep in sync with the template implementation.
 */
function defineObsExecAndStrip(window) {
  window.__obsExecAndStrip = function (html) {
    var scriptRe = new RegExp(
      "<" + 'script\\b([^>]*)>([\\s\\S]*?)</' + "script>",
      "gi",
    );
    var m;
    while ((m = scriptRe.exec(html)) !== null) {
      var attrs = m[1];
      var code = m[2].trim();
      if (/(?:^|\s)src\s*=/i.test(attrs)) {
        console.warn(
          "[obs] external <script src> not supported in dynamic partials, skipped",
        );
        continue;
      }
      if (code) {
        try {
          var s = window.document.createElement("script");
          s.text = code;
          window.document.head.appendChild(s);
          s.remove();
        } catch (e) {
          console.error("[obs] script exec error:", e);
        }
      }
    }
    return html.replace(
      new RegExp("<" + 'script\\b[^>]*>[\\s\\S]*?</' + "script>", "gi"),
      "",
    );
  };
}

let dom;
let win;
let doc;

beforeEach(() => {
  dom = new JSDOM("<!DOCTYPE html><html><head></head><body></body></html>", {
    url: "http://localhost",
    runScripts: "dangerously",
  });
  win = dom.window;
  doc = win.document;
  defineObsExecAndStrip(win);
});

// ---------------------------------------------------------------------------
// A. __obsExecAndStrip — script extraction and execution
// ---------------------------------------------------------------------------
describe("__obsExecAndStrip", () => {
  test("executes inline script and returns HTML without script tags", () => {
    const html =
      '<script>window.__testVal = 42;</script><div class="content">Hello</div>';
    const clean = win.__obsExecAndStrip(html);

    expect(clean).toBe('<div class="content">Hello</div>');
    expect(win.__testVal).toBe(42);
  });

  test("handles multiple script blocks in order", () => {
    const html = [
      "<script>window.__order = [];</script>",
      "<div>between</div>",
      "<script>window.__order.push('second');</script>",
      "<script>window.__order.push('third');</script>",
    ].join("");

    const clean = win.__obsExecAndStrip(html);

    expect(clean).toBe("<div>between</div>");
    expect(win.__order).toEqual(["second", "third"]);
  });

  test("handles script tags with attributes (e.g. defer)", () => {
    const html =
      '<script defer>window.__deferred = true;</script><p>Content</p>';
    const clean = win.__obsExecAndStrip(html);

    expect(clean).toBe("<p>Content</p>");
    expect(win.__deferred).toBe(true);
  });

  test("skips empty script blocks", () => {
    const html = "<script>   </script><script></script><div>ok</div>";
    const clean = win.__obsExecAndStrip(html);

    expect(clean).toBe("<div>ok</div>");
  });

  test("returns original HTML when no scripts are present", () => {
    const html = "<div>No scripts here</div><p>Just content</p>";
    const clean = win.__obsExecAndStrip(html);

    expect(clean).toBe(html);
  });

  test("handles case-insensitive script tags", () => {
    const html = '<SCRIPT>window.__upperCase = true;</SCRIPT><div>ok</div>';
    const clean = win.__obsExecAndStrip(html);

    expect(clean).toBe("<div>ok</div>");
    expect(win.__upperCase).toBe(true);
  });

  test("scripts execute in global scope (window)", () => {
    const html =
      "<script>window.createTestController = function() { return { init: true }; };</script><div></div>";
    const clean = win.__obsExecAndStrip(html);

    expect(clean).toBe("<div></div>");
    expect(typeof win.createTestController).toBe("function");
    expect(win.createTestController()).toEqual({ init: true });
  });

  test("catches and logs script execution errors", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    // Syntax errors in jsdom won't throw from s.text assignment,
    // but runtime errors in evaluated code do throw from appendChild.
    // We test that the function doesn't throw and continues processing.
    const html =
      "<script>window.__before = 1;</script>" +
      "<script>throw new Error('deliberate');</script>" +
      "<script>window.__after = 2;</script>" +
      "<div>ok</div>";

    const clean = win.__obsExecAndStrip(html);

    expect(clean).toBe("<div>ok</div>");
    expect(win.__before).toBe(1);
    // After the error, subsequent scripts should still execute
    expect(win.__after).toBe(2);
    consoleSpy.mockRestore();
  });

  test("cleans up script elements from document.head", () => {
    const headScriptsBefore = doc.head.querySelectorAll("script").length;
    win.__obsExecAndStrip(
      "<script>window.__cleanup = 1;</script><div></div>",
    );
    const headScriptsAfter = doc.head.querySelectorAll("script").length;

    // Script should be appended and immediately removed
    expect(headScriptsAfter).toBe(headScriptsBefore);
  });

  test("warns and skips external script src tags", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const html =
      '<script src="https://cdn.example.com/lib.js"></script>' +
      "<script>window.__inlineRan = true;</script>" +
      "<div>content</div>";

    const clean = win.__obsExecAndStrip(html);

    expect(warnSpy).toHaveBeenCalledWith(
      "[obs] external <script src> not supported in dynamic partials, skipped",
    );
    // External script stripped from HTML, inline script still executed
    expect(win.__inlineRan).toBe(true);
    expect(clean).toBe("<div>content</div>");
    warnSpy.mockRestore();
  });

  test("warns on script src with extra attributes", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const html =
      '<script defer src="lib.js"></script><div>ok</div>';

    const clean = win.__obsExecAndStrip(html);

    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(clean).toBe("<div>ok</div>");
    warnSpy.mockRestore();
  });

  test("does not false-positive on data-src attribute", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const html =
      '<script data-src="config">window.__dataSrcRan = true;</script><div>ok</div>';

    const clean = win.__obsExecAndStrip(html);

    // data-src is NOT an external script — it should execute normally
    expect(warnSpy).not.toHaveBeenCalled();
    expect(win.__dataSrcRan).toBe(true);
    expect(clean).toBe("<div>ok</div>");
    warnSpy.mockRestore();
  });

  test("simulates real observability controller pattern", () => {
    // This mirrors what observability_tools.html actually produces
    const html = [
      "<script defer>",
      "window.createToolsController = function() {",
      "  return {",
      "    timeRange: 24,",
      "    loading: false,",
      "    async init() { this.loading = true; }",
      "  };",
      "};",
      "</script>",
      '<div class="tools-dashboard" x-data="createToolsController()" x-init="init()">',
      "  <h2>Tools Dashboard</h2>",
      "</div>",
    ].join("\n");

    const clean = win.__obsExecAndStrip(html);

    // Controller should be defined
    expect(typeof win.createToolsController).toBe("function");
    const controller = win.createToolsController();
    expect(controller.timeRange).toBe(24);
    expect(controller.loading).toBe(false);

    // HTML should not contain script tags
    expect(clean).not.toContain("<script");
    expect(clean).toContain("tools-dashboard");
    expect(clean).toContain('x-data="createToolsController()"');
  });
});

// ---------------------------------------------------------------------------
// B. Alpine.mutateDom + initTree injection pattern
// ---------------------------------------------------------------------------
describe("Alpine.mutateDom + initTree injection pattern", () => {
  /**
   * Helper that replicates the hardened Alpine guard from
   * observability_partial.html (matches initialization.js pattern).
   */
  function injectWithAlpineGuard(alpine, container, cleanHtml) {
    if (
      alpine &&
      typeof alpine.mutateDom === "function" &&
      typeof alpine.initTree === "function"
    ) {
      alpine.mutateDom(() => {
        container.innerHTML = cleanHtml;
      });
      alpine.initTree(container);
    } else {
      container.innerHTML = cleanHtml;
    }
  }

  test("mutateDom suppresses observer during innerHTML assignment", () => {
    const container = doc.createElement("div");
    doc.body.appendChild(container);

    const mutateDomCalls = [];
    const initTreeCalls = [];
    win.Alpine = {
      mutateDom: (fn) => {
        mutateDomCalls.push(fn);
        fn();
      },
      initTree: (el) => initTreeCalls.push(el),
    };

    const cleanHtml = '<div x-data="test()">content</div>';
    injectWithAlpineGuard(win.Alpine, container, cleanHtml);

    expect(mutateDomCalls).toHaveLength(1);
    expect(initTreeCalls).toHaveLength(1);
    expect(initTreeCalls[0]).toBe(container);
    expect(container.innerHTML).toBe(cleanHtml);
  });

  test("falls back to direct innerHTML when Alpine is not available", () => {
    const container = doc.createElement("div");
    doc.body.appendChild(container);

    delete win.Alpine;

    const cleanHtml = "<div>fallback content</div>";
    injectWithAlpineGuard(win.Alpine, container, cleanHtml);

    expect(container.innerHTML).toBe(cleanHtml);
  });

  test("falls back when Alpine exists but mutateDom is missing", () => {
    const container = doc.createElement("div");
    doc.body.appendChild(container);

    win.Alpine = { initTree: () => {} };

    const cleanHtml = "<div>partial Alpine</div>";
    injectWithAlpineGuard(win.Alpine, container, cleanHtml);

    expect(container.innerHTML).toBe(cleanHtml);
  });

  test("falls back when Alpine exists but initTree is missing", () => {
    const container = doc.createElement("div");
    doc.body.appendChild(container);

    win.Alpine = { mutateDom: (fn) => fn() };

    const cleanHtml = "<div>partial Alpine</div>";
    injectWithAlpineGuard(win.Alpine, container, cleanHtml);

    expect(container.innerHTML).toBe(cleanHtml);
  });

  test("falls back when Alpine has non-function mutateDom/initTree", () => {
    const container = doc.createElement("div");
    doc.body.appendChild(container);

    win.Alpine = { version: "3.x", mutateDom: "not-a-fn", initTree: 42 };

    const cleanHtml = "<div>wrong types</div>";
    injectWithAlpineGuard(win.Alpine, container, cleanHtml);

    expect(container.innerHTML).toBe(cleanHtml);
  });

  test("full pipeline: extract scripts, suppress observer, init tree", () => {
    const container = doc.createElement("div");
    container.id = "tools-container";
    doc.body.appendChild(container);

    const initTreeCalls = [];
    win.Alpine = {
      mutateDom: (fn) => fn(),
      initTree: (el) => initTreeCalls.push(el),
    };

    // Simulate the full flow from observability_partial.html
    const html = [
      "<script>window.createToolsController = function() { return { ok: true }; };</script>",
      '<div class="tools-dashboard" x-data="createToolsController()">Dashboard</div>',
    ].join("");

    const cleanHtml = win.__obsExecAndStrip(html);

    // Controller should be defined BEFORE DOM insertion
    expect(typeof win.createToolsController).toBe("function");

    injectWithAlpineGuard(win.Alpine, container, cleanHtml);

    expect(initTreeCalls).toHaveLength(1);
    expect(container.querySelector(".tools-dashboard")).not.toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });
});
