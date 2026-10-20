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

  test("keeps <tr>/<td> rows written to a tbody and still strips handlers", () => {
    const tbody = document.createElement("tbody");
    tbody.innerHTML =
      '<tr data-action="show-log"><td>a</td><td><button onclick="window.__guardSink=1" data-action="x">b</button></td></tr>';
    const row = tbody.querySelector('tr[data-action="show-log"]');
    expect(row).not.toBeNull();
    expect(tbody.querySelectorAll("td")).toHaveLength(2);
    expect(tbody.querySelector("button").hasAttribute("onclick")).toBe(false);
    expect(tbody.querySelector("button").getAttribute("data-action")).toBe("x");
  });

  test("keeps <td> cells written to a tr and <th> cells written to a thead row", () => {
    const tr = document.createElement("tr");
    tr.innerHTML = "<td>1</td><td>2</td>";
    expect(tr.querySelectorAll("td")).toHaveLength(2);

    const thead = document.createElement("thead");
    thead.innerHTML = "<tr><th>h</th></tr>";
    expect(thead.querySelector("th").textContent).toBe("h");
  });

  test("clears a tbody when assigned an empty string", () => {
    const tbody = document.createElement("tbody");
    tbody.innerHTML = "<tr><td>x</td></tr>";
    tbody.innerHTML = "";
    expect(tbody.childElementCount).toBe(0);
  });
});
