/**
 * Tests for installInnerHtmlGuard: plain innerHTML writes that never call
 * sanitizeHtmlForInsertion() are still sanitized once the guard is installed.
 */

import { beforeAll, describe, expect, test } from "vitest";
import { installInnerHtmlGuard } from "../../../mcpgateway/admin_ui/security.js";

describe("installInnerHtmlGuard", () => {
  beforeAll(() => {
    installInnerHtmlGuard();
  });

  test("marks the guard as installed and is idempotent", () => {
    const setter = Object.getOwnPropertyDescriptor(Element.prototype, "innerHTML").set;
    installInnerHtmlGuard();
    expect(window.__mcpgatewayInnerHtmlGuardInstalled).toBe(true);
    expect(Object.getOwnPropertyDescriptor(Element.prototype, "innerHTML").set).toBe(setter);
  });

  test("sanitizes a direct innerHTML write", () => {
    const div = document.createElement("div");
    div.innerHTML = '<img src=x onerror="window.__guardSink=1"><b>ok</b>';
    expect(div.querySelector("img").hasAttribute("onerror")).toBe(false);
    expect(div.querySelector("b").textContent).toBe("ok");
  });

  test("sanitizes the mXSS payload written directly to innerHTML", () => {
    const div = document.createElement("div");
    div.innerHTML = '<math><mtext><table><mglyph><style><img src=x onerror="window.__guardSink=1">';
    const withHandler = Array.from(div.querySelectorAll("*")).filter((el) =>
      Array.from(el.attributes).some((attr) => attr.name.toLowerCase().startsWith("on"))
    );
    expect(withHandler).toEqual([]);
  });

  test("leaves the innerHTML getter unchanged", () => {
    const div = document.createElement("div");
    div.innerHTML = '<span data-action="go">x</span>';
    expect(div.innerHTML).toBe('<span data-action="go">x</span>');
  });
});
