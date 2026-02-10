/**
 * Unit tests for admin.js functions that need simple DOM element setup.
 */

import { describe, test, expect, beforeAll, beforeEach, afterAll } from "vitest";
import { loadAdminJs, cleanupAdminJs } from "./helpers/admin-env.js";

let win;
let doc;

beforeAll(() => {
    win = loadAdminJs();
    doc = win.document;
});

afterAll(() => {
    cleanupAdminJs();
});

// Reset DOM body between tests
beforeEach(() => {
    doc.body.textContent = "";
});

// ---------------------------------------------------------------------------
// safeGetElement
// ---------------------------------------------------------------------------
describe("safeGetElement", () => {
    const f = () => win.safeGetElement;

    test("returns element when it exists", () => {
        const div = doc.createElement("div");
        div.id = "test-element";
        doc.body.appendChild(div);
        expect(f()("test-element")).toBe(div);
    });

    test("returns null when element does not exist", () => {
        expect(f()("nonexistent")).toBeNull();
    });

    test("returns null with suppressWarning", () => {
        expect(f()("nonexistent", true)).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// safeSetValue
// ---------------------------------------------------------------------------
describe("safeSetValue", () => {
    const f = () => win.safeSetValue;

    test("sets value on existing element", () => {
        const input = doc.createElement("input");
        input.id = "my-input";
        doc.body.appendChild(input);
        f()("my-input", "hello");
        expect(input.value).toBe("hello");
    });

    test("does nothing when element does not exist", () => {
        // Should not throw
        f()("nonexistent", "value");
    });
});

// ---------------------------------------------------------------------------
// safeSetInnerHTML
// ---------------------------------------------------------------------------
describe("safeSetInnerHTML", () => {
    const f = () => win.safeSetInnerHTML;

    test("sets content when trusted", () => {
        const div = doc.createElement("div");
        f()(div, "<b>bold</b>", true);
        // Verify the bold element was created
        expect(div.querySelector("b")).not.toBeNull();
        expect(div.querySelector("b").textContent).toBe("bold");
    });

    test("falls back to textContent when not trusted", () => {
        const div = doc.createElement("div");
        f()(div, "<b>test</b>", false);
        expect(div.textContent).toBe("<b>test</b>");
        expect(div.querySelector("b")).toBeNull();
    });

    test("defaults to untrusted (no isTrusted argument)", () => {
        const div = doc.createElement("div");
        f()(div, "<b>test</b>");
        expect(div.textContent).toBe("<b>test</b>");
    });
});

// ---------------------------------------------------------------------------
// isInactiveChecked
// ---------------------------------------------------------------------------
describe("isInactiveChecked", () => {
    const f = () => win.isInactiveChecked;

    test("returns true when checkbox is checked", () => {
        const cb = doc.createElement("input");
        cb.type = "checkbox";
        cb.id = "show-inactive-tools";
        cb.checked = true;
        doc.body.appendChild(cb);
        expect(f()("tools")).toBe(true);
    });

    test("returns false when checkbox is unchecked", () => {
        const cb = doc.createElement("input");
        cb.type = "checkbox";
        cb.id = "show-inactive-tools";
        cb.checked = false;
        doc.body.appendChild(cb);
        expect(f()("tools")).toBe(false);
    });

    test("returns false when checkbox does not exist", () => {
        expect(f()("nonexistent")).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// getDefaultTabName
// ---------------------------------------------------------------------------
describe("getDefaultTabName", () => {
    const f = () => win.getDefaultTabName;

    test('returns "overview" when overview-panel exists', () => {
        const div = doc.createElement("div");
        div.id = "overview-panel";
        doc.body.appendChild(div);
        expect(f()()).toBe("overview");
    });

    test('returns "gateways" when overview-panel does not exist', () => {
        expect(f()()).toBe("gateways");
    });
});

// ---------------------------------------------------------------------------
// getCookie
// ---------------------------------------------------------------------------
describe("getCookie", () => {
    const f = () => win.getCookie;

    test("returns cookie value when it exists", () => {
        doc.cookie = "test_cookie=abc123";
        expect(f()("test_cookie")).toBe("abc123");
    });

    test("returns empty string when cookie does not exist", () => {
        expect(f()("nonexistent_cookie_xyz")).toBe("");
    });

    test("handles multiple cookies", () => {
        doc.cookie = "first=one";
        doc.cookie = "second=two";
        expect(f()("second")).toBe("two");
    });
});

// ---------------------------------------------------------------------------
// escapeHtmlChat
// ---------------------------------------------------------------------------
describe("escapeHtmlChat", () => {
    const f = () => win.escapeHtmlChat;

    test("escapes HTML tags", () => {
        const result = f()("<b>bold</b>");
        expect(result).not.toContain("<b>");
        expect(result).toContain("&lt;b&gt;");
    });

    test("returns plain text unchanged", () => {
        expect(f()("hello world")).toBe("hello world");
    });

    test("escapes ampersands", () => {
        expect(f()("a & b")).toContain("&amp;");
    });
});

// ---------------------------------------------------------------------------
// getExportOptions
// ---------------------------------------------------------------------------
describe("getExportOptions", () => {
    const f = () => win.getExportOptions;

    test("returns checked types", () => {
        const tools = doc.createElement("input");
        tools.type = "checkbox";
        tools.id = "export-tools";
        tools.checked = true;
        doc.body.appendChild(tools);

        const gateways = doc.createElement("input");
        gateways.type = "checkbox";
        gateways.id = "export-gateways";
        gateways.checked = true;
        doc.body.appendChild(gateways);

        const result = f()();
        expect(result.types).toContain("tools");
        expect(result.types).toContain("gateways");
    });

    test("omits unchecked types", () => {
        const tools = doc.createElement("input");
        tools.type = "checkbox";
        tools.id = "export-tools";
        tools.checked = false;
        doc.body.appendChild(tools);

        const result = f()();
        expect(result.types).not.toContain("tools");
    });

    test("returns tags value", () => {
        const tags = doc.createElement("input");
        tags.id = "export-tags";
        tags.value = "prod,staging";
        doc.body.appendChild(tags);

        expect(f()().tags).toBe("prod,staging");
    });

    test("returns empty tags when no element", () => {
        expect(f()().tags).toBe("");
    });

    test("returns includeInactive from checkbox", () => {
        const cb = doc.createElement("input");
        cb.type = "checkbox";
        cb.id = "export-include-inactive";
        cb.checked = true;
        doc.body.appendChild(cb);

        expect(f()().includeInactive).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// getPasswordPolicy
// ---------------------------------------------------------------------------
describe("getPasswordPolicy", () => {
    const f = () => win.getPasswordPolicy;

    test("returns null when element does not exist", () => {
        expect(f()()).toBeNull();
    });

    test("parses policy from data attributes", () => {
        const el = doc.createElement("div");
        el.id = "edit-password-policy-data";
        el.dataset.minLength = "8";
        el.dataset.requireUppercase = "true";
        el.dataset.requireLowercase = "true";
        el.dataset.requireNumbers = "false";
        el.dataset.requireSpecial = "true";
        doc.body.appendChild(el);

        const policy = f()();
        expect(policy.minLength).toBe(8);
        expect(policy.requireUppercase).toBe(true);
        expect(policy.requireLowercase).toBe(true);
        expect(policy.requireNumbers).toBe(false);
        expect(policy.requireSpecial).toBe(true);
    });

    test("defaults minLength to 0 when not set", () => {
        const el = doc.createElement("div");
        el.id = "edit-password-policy-data";
        doc.body.appendChild(el);

        expect(f()().minLength).toBe(0);
    });
});

// ---------------------------------------------------------------------------
// collectUserSelections
// ---------------------------------------------------------------------------
describe("collectUserSelections", () => {
    const f = () => win.collectUserSelections;

    test("collects checked gateway checkboxes", () => {
        const cb = doc.createElement("input");
        cb.type = "checkbox";
        cb.className = "gateway-checkbox";
        cb.checked = true;
        cb.dataset.gateway = "gw-1";
        doc.body.appendChild(cb);

        const result = f()();
        expect(result.gateways).toEqual(["gw-1"]);
    });

    test("collects checked item checkboxes", () => {
        const cb = doc.createElement("input");
        cb.type = "checkbox";
        cb.className = "item-checkbox";
        cb.checked = true;
        cb.dataset.type = "tools";
        cb.dataset.id = "tool-1";
        doc.body.appendChild(cb);

        const result = f()();
        expect(result.tools).toEqual(["tool-1"]);
    });

    test("ignores unchecked checkboxes", () => {
        const cb = doc.createElement("input");
        cb.type = "checkbox";
        cb.className = "gateway-checkbox";
        cb.checked = false;
        cb.dataset.gateway = "gw-1";
        doc.body.appendChild(cb);

        const result = f()();
        expect(result.gateways).toBeUndefined();
    });

    test("returns empty object when nothing checked", () => {
        expect(f()()).toEqual({});
    });
});

// ---------------------------------------------------------------------------
// getTableNamesForTab
// ---------------------------------------------------------------------------
describe("getTableNamesForTab", () => {
    const f = () => win.getTableNamesForTab;

    test("extracts table names from pagination controls", () => {
        const panel = doc.createElement("div");
        panel.id = "tools-panel";
        const ctrl = doc.createElement("div");
        ctrl.id = "tools-pagination-controls";
        panel.appendChild(ctrl);
        doc.body.appendChild(panel);

        expect(f()("tools")).toEqual(["tools"]);
    });

    test("returns empty array when panel not found", () => {
        expect(f()("nonexistent")).toEqual([]);
    });

    test("extracts multiple table names", () => {
        const panel = doc.createElement("div");
        panel.id = "overview-panel";
        const c1 = doc.createElement("div");
        c1.id = "tools-pagination-controls";
        const c2 = doc.createElement("div");
        c2.id = "servers-pagination-controls";
        panel.appendChild(c1);
        panel.appendChild(c2);
        doc.body.appendChild(panel);

        const result = f()("overview");
        expect(result).toContain("tools");
        expect(result).toContain("servers");
    });
});

// ---------------------------------------------------------------------------
// getTeamsPerPage
// ---------------------------------------------------------------------------
describe("getTeamsPerPage", () => {
    const f = () => win.getTeamsPerPage;

    test("returns default (10) when no controls exist", () => {
        expect(f()()).toBe(10);
    });

    test("reads value from select element", () => {
        const container = doc.createElement("div");
        container.id = "teams-pagination-controls";
        const select = doc.createElement("select");
        const option = doc.createElement("option");
        option.value = "25";
        option.selected = true;
        select.appendChild(option);
        container.appendChild(select);
        doc.body.appendChild(container);

        expect(f()()).toBe(25);
    });
});

// ---------------------------------------------------------------------------
// buildLLMConfig
// ---------------------------------------------------------------------------
describe("buildLLMConfig", () => {
    const f = () => win.buildLLMConfig;

    test("returns config with model only", () => {
        const result = f()("gpt-4");
        expect(result).toEqual({ model: "gpt-4" });
    });

    test("includes temperature when element has value", () => {
        const el = doc.createElement("input");
        el.id = "llm-temperature";
        el.value = "0.7";
        doc.body.appendChild(el);

        const result = f()("gpt-4");
        expect(result.temperature).toBeCloseTo(0.7);
    });

    test("includes max_tokens when element has value", () => {
        const el = doc.createElement("input");
        el.id = "llm-max-tokens";
        el.value = "2048";
        doc.body.appendChild(el);

        const result = f()("gpt-4");
        expect(result.max_tokens).toBe(2048);
    });

    test("ignores empty temperature/max_tokens", () => {
        const temp = doc.createElement("input");
        temp.id = "llm-temperature";
        temp.value = "  ";
        doc.body.appendChild(temp);

        const result = f()("gpt-4");
        expect(result.temperature).toBeUndefined();
    });
});

// ---------------------------------------------------------------------------
// getCurrentTeamId / getCurrentTeamName
// ---------------------------------------------------------------------------
describe("getCurrentTeamId", () => {
    const f = () => win.getCurrentTeamId;

    test("returns null when no team selector or URL params", () => {
        expect(f()()).toBeNull();
    });
});

describe("getCurrentTeamName", () => {
    const f = () => win.getCurrentTeamName;

    test("returns null when no team selected", () => {
        expect(f()()).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// generateUserId
// ---------------------------------------------------------------------------
describe("generateUserId", () => {
    const f = () => win.generateUserId;

    test("returns authenticated user when available", () => {
        win.CURRENT_USER = "admin@test.com";
        const result = f()();
        expect(result).toBe("admin@test.com");
    });

    test("generates unique ID when no authenticated user", () => {
        win.CURRENT_USER = null;
        try { win.sessionStorage.removeItem("llm_chat_user_id"); } catch (e) { /* noop */ }
        const result = f()();
        expect(result).toMatch(/^user_\d+_[a-z0-9]+$/);
    });

    test("returns consistent ID from sessionStorage on subsequent calls", () => {
        win.CURRENT_USER = null;
        try { win.sessionStorage.removeItem("llm_chat_user_id"); } catch (e) { /* noop */ }
        const first = f()();
        const second = f()();
        expect(first).toBe(second);
    });
});

// ---------------------------------------------------------------------------
// getCatalogUrl
// ---------------------------------------------------------------------------
describe("getCatalogUrl", () => {
    const f = () => win.getCatalogUrl;

    test("builds catalog URL from server object", () => {
        const result = f()({ id: "srv-123" });
        expect(result).toContain("/servers/srv-123");
        expect(result).toMatch(/^https?:\/\//);
    });
});

// ---------------------------------------------------------------------------
// generateConfig
// ---------------------------------------------------------------------------
describe("generateConfig", () => {
    const f = () => win.generateConfig;

    test("generates stdio config", () => {
        const result = f()({ id: "s1", name: "My Server" }, "stdio");
        expect(result.mcpServers).toBeDefined();
        expect(
            result.mcpServers["mcpgateway-wrapper"].env.MCP_SERVER_URL,
        ).toContain("/servers/s1");
    });

    test("generates sse config", () => {
        const result = f()({ id: "s1", name: "My Server" }, "sse");
        expect(result.servers).toBeDefined();
        const key = Object.keys(result.servers)[0];
        expect(result.servers[key].type).toBe("sse");
        expect(result.servers[key].url).toContain("/servers/s1/sse");
    });

    test("generates http config", () => {
        const result = f()({ id: "s1", name: "My Server" }, "http");
        const key = Object.keys(result.servers)[0];
        expect(result.servers[key].type).toBe("streamable-http");
        expect(result.servers[key].url).toContain("/servers/s1/mcp");
    });

    test("cleans server name for config key", () => {
        const result = f()(
            { id: "s1", name: "My Special Server!" },
            "sse",
        );
        const key = Object.keys(result.servers)[0];
        expect(key).toBe("my-special-server");
    });

    test("throws for unknown config type", () => {
        expect(() => f()({ id: "s1", name: "x" }, "unknown")).toThrow(
            /Unknown config type/,
        );
    });
});

// ---------------------------------------------------------------------------
// createMemoizedInit
// ---------------------------------------------------------------------------
describe("createMemoizedInit", () => {
    const f = () => win.createMemoizedInit;

    test("calls init function on first invocation", () => {
        let called = 0;
        const memo = f()(() => { called++; }, 0, "Test");
        memo.init();
        expect(called).toBe(1);
    });

    test("does not call init function on second invocation", () => {
        let called = 0;
        const memo = f()(() => { called++; }, 0, "Test");
        memo.init();
        memo.init();
        expect(called).toBe(1);
    });

    test("calls init again after reset", () => {
        let called = 0;
        const memo = f()(() => { called++; }, 0, "Test");
        memo.init();
        memo.reset();
        memo.init();
        expect(called).toBe(2);
    });

    test("returns a thenable from init", () => {
        const memo = f()(() => "result", 0, "Test");
        const result = memo.init();
        expect(typeof result.then).toBe("function");
    });

    test("allows retry after error", async () => {
        let attempt = 0;
        const memo = f()(() => {
            attempt++;
            if (attempt === 1) throw new Error("fail");
            return "ok";
        }, 0, "Test");

        await expect(memo.init()).rejects.toThrow("fail");
        await expect(memo.init()).resolves.toBe("ok");
    });
});
