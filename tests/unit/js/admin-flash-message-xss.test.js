/**
 * Regression tests for the admin dashboard flash-message banner.
 *
 * The `?error=` / `?message=` query parameters are attacker-controlled (a
 * crafted link). This test slices the shipped flash IIFE out of `admin.html`
 * and runs it in JSDOM. The banner shows only text mapped from a fixed code
 * allowlist, so a link can neither inject markup nor choose the wording.
 */

import { describe, expect, test } from "vitest";
import fs from "fs";
import path from "path";
import { JSDOM } from "jsdom";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const adminHtml = fs.readFileSync(path.resolve(__dirname, "../../../mcpgateway/templates/admin.html"), "utf8");
const adminPy = fs.readFileSync(path.resolve(__dirname, "../../../mcpgateway/admin.py"), "utf8");

const start = adminHtml.indexOf("// Display flash messages from URL parameters");
const end = adminHtml.indexOf("})();", start);
if (start === -1 || end === -1) {
  throw new Error("Could not locate the flash-message IIFE in admin.html — update the extraction anchors.");
}
const flashSource = adminHtml.slice(start, end + "})();".length);

const GENERIC_ERROR = "❌ Something went wrong. Please try again.";
const MXSS_PAYLOAD = '<form><math><mtext></form><mglyph><style></math><img src=/np.png onerror="window.__xss=1">';

function renderWith(query) {
  const dom = new JSDOM(`<!DOCTYPE html><html><body><div id="global-notification" style="display: none;"></div></body></html>`, {
    url: `http://localhost/admin?${query}#tools`,
    runScripts: "outside-only",
  });
  const win = dom.window;
  win.eval(flashSource);
  return win;
}

function banner(win) {
  return win.document.getElementById("global-notification");
}

describe("admin.html flash message — code allowlist", () => {
  test("a known error code renders its mapped text", () => {
    const win = renderWith("error=permission_denied");

    expect(banner(win).querySelector("span").textContent).toBe("❌ You do not have permission to perform this action.");
    expect(banner(win).style.display).toBe("block");
  });

  test.each([MXSS_PAYLOAD, "Your session expired, call +1 555 0100", "toString", "__proto__", "constructor"])(
    "an unknown error value renders the generic message: %s",
    (value) => {
      const win = renderWith(`error=${encodeURIComponent(value)}`);

      expect(banner(win).querySelector("span").textContent).toBe(GENERIC_ERROR);
      expect(banner(win).querySelector("img, math, form")).toBeNull();
      expect(win.__xss).toBeUndefined();
    }
  );

  test("a known info code renders its mapped text", () => {
    const win = renderWith("message=gateway_delete_pending");

    expect(banner(win).querySelector("span").textContent).toBe("✅ Gateway deletion accepted and pending cleanup.");
  });

  test.each([`message=${encodeURIComponent(MXSS_PAYLOAD)}`, "message=toString", `success=${encodeURIComponent(MXSS_PAYLOAD)}`, "error=", "message=", "tab=tools"])(
    "no banner for unknown info codes, the removed success parameter, empty values, or no parameters: %s",
    (query) => {
      const win = renderWith(query);

      expect(banner(win).style.display).toBe("none");
      expect(banner(win).childNodes.length).toBe(0);
    }
  );

  test("removes the flash parameters from the URL and keeps the rest", () => {
    const win = renderWith("error=delete_failed&success=stale&team_id=t1");

    expect(win.location.search).toBe("?team_id=t1");
    expect(win.location.hash).toBe("#tools");
  });
});

describe("admin.html flash message — dismissal and focus", () => {
  test("the banner stays until the dismiss button is used", () => {
    const win = renderWith("error=delete_failed");
    const closeBtn = banner(win).querySelector("button");

    expect(closeBtn.getAttribute("aria-label")).toBe("Dismiss notification");
    expect(closeBtn.type).toBe("button");

    closeBtn.click();
    expect(banner(win).style.display).toBe("none");
    expect(banner(win).childNodes.length).toBe(0);
  });

  test("an error moves focus to the dismiss button", () => {
    const win = renderWith("error=delete_failed");

    expect(win.document.activeElement).toBe(banner(win).querySelector("button"));
  });

  test("an info message leaves focus alone", () => {
    const win = renderWith("message=gateway_delete_pending");

    expect(win.document.activeElement).toBe(win.document.body);
  });
});

describe("admin.py flash codes stay in sync with admin.html", () => {
  const emitted = new Set(
    [...adminPy.matchAll(/\b(?:error_code|accepted_message|error)\s*=\s*"([a-z_]+)"/g)].map((match) => match[1])
  );
  const allowlist = flashSource.match(/const (?:ERROR|INFO)_MESSAGES = \{[\s\S]*?\};/g).join("\n");

  test("admin.py emits codes", () => {
    expect(emitted.size).toBeGreaterThan(5);
  });

  test.each([...emitted])("code %s has a message in admin.html", (code) => {
    expect(allowlist).toMatch(new RegExp(`\\b${code}:`));
  });
});
