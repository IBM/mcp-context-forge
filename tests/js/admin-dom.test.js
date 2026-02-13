/**
 * Unit tests for functions that need DOM element setup.
 * Uses minimal JSDOM environment for DOM manipulation tests.
 */

import {
  describe,
  test,
  expect,
  beforeAll,
  beforeEach,
  afterAll,
} from "vitest";
import { createDOMEnvironment } from "./helpers/dom-env.js";
import {
  safeGetElement,
  safeSetValue,
  isInactiveChecked,
  getCookie,
  getCurrentTeamId,
  getCurrentTeamName,
  createMemoizedInit,
} from "../../mcpgateway/admin_ui/utils.js";
import {
  safeSetInnerHTML,
  escapeHtmlChat,
} from "../../mcpgateway/admin_ui/security.js";
import {
  getDefaultTabName,
  getTableNamesForTab,
} from "../../mcpgateway/admin_ui/tabs.js";
import { getTeamsPerPage } from "../../mcpgateway/admin_ui/teams.js";
import {
  getCatalogUrl,
  generateConfig,
} from "../../mcpgateway/admin_ui/configExport.js";

let env;
let document;
let window;

beforeAll(() => {
  env = createDOMEnvironment();
  document = env.document;
  window = env.window;

  // Make document and window available globally for functions that expect them
  global.document = document;
  global.window = window;
});

afterAll(() => {
  env.cleanup();
  delete global.document;
  delete global.window;
});

// Reset DOM body between tests
beforeEach(() => {
  document.body.textContent = "";
  // Clear window properties
  delete window.CURRENT_USER;
  delete window.IS_ADMIN;
  delete window.ROOT_PATH;
  delete window.USERTEAMSDATA;
});

// ---------------------------------------------------------------------------
// safeGetElement
// ---------------------------------------------------------------------------
describe("safeGetElement", () => {
  test("returns element when it exists", () => {
    const div = document.createElement("div");
    div.id = "test-element";
    document.body.appendChild(div);
    expect(safeGetElement("test-element")).toBe(div);
  });

  test("returns null when element does not exist", () => {
    expect(safeGetElement("nonexistent")).toBeNull();
  });

  test("returns null with suppressWarning", () => {
    expect(safeGetElement("nonexistent", true)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// safeSetValue
// ---------------------------------------------------------------------------
describe("safeSetValue", () => {
  test("sets value on existing element", () => {
    const input = document.createElement("input");
    input.id = "my-input";
    document.body.appendChild(input);
    safeSetValue("my-input", "hello");
    expect(input.value).toBe("hello");
  });

  test("does nothing when element does not exist", () => {
    // Should not throw
    safeSetValue("nonexistent", "value");
  });
});

// ---------------------------------------------------------------------------
// safeSetInnerHTML
// ---------------------------------------------------------------------------
describe("safeSetInnerHTML", () => {
  test("sets content when trusted", () => {
    const div = document.createElement("div");
    safeSetInnerHTML(div, "<b>bold</b>", true);
    // Verify the bold element was created
    expect(div.querySelector("b")).not.toBeNull();
    expect(div.querySelector("b").textContent).toBe("bold");
  });

  test("falls back to textContent when not trusted", () => {
    const div = document.createElement("div");
    safeSetInnerHTML(div, "<b>test</b>", false);
    expect(div.textContent).toBe("<b>test</b>");
    expect(div.querySelector("b")).toBeNull();
  });

  test("defaults to untrusted (no isTrusted argument)", () => {
    const div = document.createElement("div");
    safeSetInnerHTML(div, "<b>test</b>");
    expect(div.textContent).toBe("<b>test</b>");
  });
});

// ---------------------------------------------------------------------------
// isInactiveChecked
// ---------------------------------------------------------------------------
describe("isInactiveChecked", () => {
  test("returns true when checkbox is checked", () => {
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.id = "show-inactive-tools";
    cb.checked = true;
    document.body.appendChild(cb);
    expect(isInactiveChecked("tools")).toBe(true);
  });

  test("returns false when checkbox is unchecked", () => {
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.id = "show-inactive-tools";
    cb.checked = false;
    document.body.appendChild(cb);
    expect(isInactiveChecked("tools")).toBe(false);
  });

  test("returns false when checkbox does not exist", () => {
    expect(isInactiveChecked("nonexistent")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// getDefaultTabName
// ---------------------------------------------------------------------------
describe("getDefaultTabName", () => {
  test('returns "overview" when overview-panel exists', () => {
    const div = document.createElement("div");
    div.id = "overview-panel";
    document.body.appendChild(div);
    expect(getDefaultTabName()).toBe("overview");
  });

  test('returns "gateways" when overview-panel does not exist', () => {
    expect(getDefaultTabName()).toBe("gateways");
  });
});

// ---------------------------------------------------------------------------
// getCookie
// ---------------------------------------------------------------------------
describe("getCookie", () => {
  test("returns cookie value when it exists", () => {
    document.cookie = "test_cookie=abc123";
    expect(getCookie("test_cookie")).toBe("abc123");
  });

  test("returns empty string when cookie does not exist", () => {
    expect(getCookie("nonexistent_cookie_xyz")).toBe("");
  });

  test("handles multiple cookies", () => {
    document.cookie = "first=one";
    document.cookie = "second=two";
    expect(getCookie("second")).toBe("two");
  });
});

// ---------------------------------------------------------------------------
// escapeHtmlChat
// ---------------------------------------------------------------------------
describe("escapeHtmlChat", () => {
  test("escapes HTML tags", () => {
    const result = escapeHtmlChat("<b>bold</b>");
    expect(result).not.toContain("<b>");
    expect(result).toContain("&lt;b&gt;");
  });

  test("returns plain text unchanged", () => {
    expect(escapeHtmlChat("hello world")).toBe("hello world");
  });

  test("escapes ampersands", () => {
    expect(escapeHtmlChat("a & b")).toContain("&amp;");
  });
});

// Note: getExportOptions, getPasswordPolicy, collectUserSelections are internal functions
// not exported from their modules, so they are not tested here.

// ---------------------------------------------------------------------------
// getTableNamesForTab
// ---------------------------------------------------------------------------
describe("getTableNamesForTab", () => {
  test("extracts table names from pagination controls", () => {
    const panel = document.createElement("div");
    panel.id = "tools-panel";
    const ctrl = document.createElement("div");
    ctrl.id = "tools-pagination-controls";
    panel.appendChild(ctrl);
    document.body.appendChild(panel);

    expect(getTableNamesForTab("tools")).toEqual(["tools"]);
  });

  test("returns empty array when panel not found", () => {
    expect(getTableNamesForTab("nonexistent")).toEqual([]);
  });

  test("extracts multiple table names", () => {
    const panel = document.createElement("div");
    panel.id = "overview-panel";
    const c1 = document.createElement("div");
    c1.id = "tools-pagination-controls";
    const c2 = document.createElement("div");
    c2.id = "servers-pagination-controls";
    panel.appendChild(c1);
    panel.appendChild(c2);
    document.body.appendChild(panel);

    const result = getTableNamesForTab("overview");
    expect(result).toContain("tools");
    expect(result).toContain("servers");
  });
});

// ---------------------------------------------------------------------------
// getTeamsPerPage
// ---------------------------------------------------------------------------
describe("getTeamsPerPage", () => {
  test("returns default (10) when no controls exist", () => {
    expect(getTeamsPerPage()).toBe(10);
  });

  test("reads value from select element", () => {
    const container = document.createElement("div");
    container.id = "teams-pagination-controls";
    const select = document.createElement("select");
    const option = document.createElement("option");
    option.value = "25";
    option.selected = true;
    select.appendChild(option);
    container.appendChild(select);
    document.body.appendChild(container);

    expect(getTeamsPerPage()).toBe(25);
  });
});

// Note: buildLLMConfig is an internal function not exported from llmChat.js

// ---------------------------------------------------------------------------
// getCurrentTeamId / getCurrentTeamName
// ---------------------------------------------------------------------------
describe("getCurrentTeamId", () => {
  test("returns null when no team selector or URL params", () => {
    expect(getCurrentTeamId()).toBeNull();
  });
});

describe("getCurrentTeamName", () => {
  test("returns null when no team selected", () => {
    expect(getCurrentTeamName()).toBeNull();
  });
});

// Note: generateUserId is an internal function not exported from llmChat.js

// ---------------------------------------------------------------------------
// getCatalogUrl
// ---------------------------------------------------------------------------
describe("getCatalogUrl", () => {
  test("builds catalog URL from server object", () => {
    const result = getCatalogUrl({ id: "srv-123" });
    expect(result).toContain("/servers/srv-123");
    expect(result).toMatch(/^https?:\/\//);
  });
});

// ---------------------------------------------------------------------------
// generateConfig
// ---------------------------------------------------------------------------
describe("generateConfig", () => {
  test("generates stdio config", () => {
    const result = generateConfig({ id: "s1", name: "My Server" }, "stdio");
    expect(result.mcpServers).toBeDefined();
    expect(
      result.mcpServers["mcpgateway-wrapper"].env.MCP_SERVER_URL
    ).toContain("/servers/s1");
  });

  test("generates sse config", () => {
    const result = generateConfig({ id: "s1", name: "My Server" }, "sse");
    expect(result.servers).toBeDefined();
    const key = Object.keys(result.servers)[0];
    expect(result.servers[key].type).toBe("sse");
    expect(result.servers[key].url).toContain("/servers/s1/sse");
  });

  test("generates http config", () => {
    const result = generateConfig({ id: "s1", name: "My Server" }, "http");
    const key = Object.keys(result.servers)[0];
    expect(result.servers[key].type).toBe("streamable-http");
    expect(result.servers[key].url).toContain("/servers/s1/mcp");
  });

  test("cleans server name for config key", () => {
    const result = generateConfig(
      { id: "s1", name: "My Special Server!" },
      "sse"
    );
    const key = Object.keys(result.servers)[0];
    expect(key).toBe("my-special-server");
  });

  test("throws for unknown config type", () => {
    expect(() => generateConfig({ id: "s1", name: "x" }, "unknown")).toThrow(
      /Unknown config type/
    );
  });
});

// ---------------------------------------------------------------------------
// createMemoizedInit
// ---------------------------------------------------------------------------
describe("createMemoizedInit", () => {
  test("calls init function on first invocation", () => {
    let called = 0;
    const memo = createMemoizedInit(
      () => {
        called++;
      },
      0,
      "Test"
    );
    memo.init();
    expect(called).toBe(1);
  });

  test("does not call init function on second invocation", () => {
    let called = 0;
    const memo = createMemoizedInit(
      () => {
        called++;
      },
      0,
      "Test"
    );
    memo.init();
    memo.init();
    expect(called).toBe(1);
  });

  test("calls init again after reset", () => {
    let called = 0;
    const memo = createMemoizedInit(
      () => {
        called++;
      },
      0,
      "Test"
    );
    memo.init();
    memo.reset();
    memo.init();
    expect(called).toBe(2);
  });

  test("returns a thenable from init", () => {
    const memo = createMemoizedInit(() => "result", 0, "Test");
    const result = memo.init();
    expect(typeof result.then).toBe("function");
  });

  test("allows retry after error", async () => {
    let attempt = 0;
    const memo = createMemoizedInit(
      () => {
        attempt++;
        if (attempt === 1) throw new Error("fail");
        return "ok";
      },
      0,
      "Test"
    );

    await expect(memo.init()).rejects.toThrow("fail");
    await expect(memo.init()).resolves.toBe("ok");
  });
});
