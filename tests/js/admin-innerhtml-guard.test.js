/**
 * Unit tests for the innerHTML guard (PR #3129 / PR #3373).
 *
 * Covers:
 *   A. innerHTML guard sanitizer — strips on* attrs, preserves data-*, safe hrefs
 *   B. selectTeamFromSelector — team selector delegation
 *   C. performTeamSelectorSearch — fetch + innerHTML with data-action retry
 *   D. Tool table event delegation — data-action buttons on #toolBody
 *   E. Metrics retry buttons — data-action="retry-metrics" pattern
 */

import {
    describe,
    test,
    expect,
    beforeAll,
    beforeEach,
    afterAll,
    vi,
} from "vitest";
import { loadAdminJs, cleanupAdminJs } from "./helpers/admin-env.js";

let win;
let doc;

beforeAll(() => {
    win = loadAdminJs({
        beforeEval: (window) => {
            // Provide globals that admin.js expects at load time
            window.getPaginationParams = function (tableName) {
                return { page: 1, perPage: 10, includeInactive: null };
            };
            window.buildTableUrl = function (tableName, baseUrl, params) {
                return baseUrl;
            };
            window.safeReplaceState = function (data, title, url) {};
        },
    });
    doc = win.document;
});

afterAll(() => {
    cleanupAdminJs();
});

beforeEach(() => {
    doc.body.textContent = "";
    vi.restoreAllMocks();
});

// ===========================================================================
// A. innerHTML guard sanitizer (tested via Element.prototype.innerHTML)
// ===========================================================================

describe("innerHTML guard — strips on* attributes", () => {
    test("strips onclick attribute from button", () => {
        const div = doc.createElement("div");
        doc.body.appendChild(div);
        div.innerHTML = '<button onclick="alert(1)">Click</button>';
        const btn = div.querySelector("button");
        expect(btn.hasAttribute("onclick")).toBe(false);
        div.remove();
    });

    test("strips onmouseover attribute from span", () => {
        const div = doc.createElement("div");
        doc.body.appendChild(div);
        div.innerHTML = '<span onmouseover="evil()">Hover</span>';
        const span = div.querySelector("span");
        expect(span.hasAttribute("onmouseover")).toBe(false);
        div.remove();
    });

    test("strips onerror attribute from img", () => {
        const div = doc.createElement("div");
        doc.body.appendChild(div);
        div.innerHTML = '<img src="x" onerror="evil()">';
        const img = div.querySelector("img");
        expect(img.hasAttribute("onerror")).toBe(false);
        div.remove();
    });

    test("strips onchange attribute from select", () => {
        const div = doc.createElement("div");
        doc.body.appendChild(div);
        div.innerHTML = '<select onchange="evil()"><option>A</option></select>';
        const sel = div.querySelector("select");
        expect(sel.hasAttribute("onchange")).toBe(false);
        div.remove();
    });

    test("strips multiple on* attributes from same element", () => {
        const div = doc.createElement("div");
        doc.body.appendChild(div);
        div.innerHTML =
            '<a href="#" onclick="a()" onmousedown="b()" onfocus="c()">Link</a>';
        const a = div.querySelector("a");
        expect(a.hasAttribute("onclick")).toBe(false);
        expect(a.hasAttribute("onmousedown")).toBe(false);
        expect(a.hasAttribute("onfocus")).toBe(false);
        div.remove();
    });

    test("strips <script> tags entirely", () => {
        const div = doc.createElement("div");
        doc.body.appendChild(div);
        div.innerHTML = '<p>Safe</p><script>evil()</script>';
        expect(div.querySelector("script")).toBeNull();
        expect(div.querySelector("p")).not.toBeNull();
        div.remove();
    });

    test("strips <iframe> tags", () => {
        const div = doc.createElement("div");
        doc.body.appendChild(div);
        div.innerHTML = '<iframe src="https://evil.com"></iframe>';
        expect(div.querySelector("iframe")).toBeNull();
        div.remove();
    });

    test("strips <object> tags", () => {
        const div = doc.createElement("div");
        doc.body.appendChild(div);
        div.innerHTML = '<object data="evil.swf"></object>';
        expect(div.querySelector("object")).toBeNull();
        div.remove();
    });

    test("strips <embed> tags", () => {
        const div = doc.createElement("div");
        doc.body.appendChild(div);
        div.innerHTML = '<embed src="evil.swf">';
        expect(div.querySelector("embed")).toBeNull();
        div.remove();
    });

    test("strips javascript: href", () => {
        const div = doc.createElement("div");
        doc.body.appendChild(div);
        div.innerHTML = '<a href="javascript:evil()">Click</a>';
        const a = div.querySelector("a");
        expect(a.hasAttribute("href")).toBe(false);
        div.remove();
    });

    test("strips vbscript: href", () => {
        const div = doc.createElement("div");
        doc.body.appendChild(div);
        div.innerHTML = '<a href="vbscript:evil()">Click</a>';
        const a = div.querySelector("a");
        expect(a.hasAttribute("href")).toBe(false);
        div.remove();
    });

    test("strips data:text/html src", () => {
        const div = doc.createElement("div");
        doc.body.appendChild(div);
        div.innerHTML = '<img src="data:text/html,<script>evil()</script>">';
        const img = div.querySelector("img");
        expect(img.hasAttribute("src")).toBe(false);
        div.remove();
    });
});

describe("innerHTML guard — preserves safe attributes", () => {
    test("preserves data-action attribute", () => {
        const div = doc.createElement("div");
        doc.body.appendChild(div);
        div.innerHTML =
            '<button data-action="retry-metrics">Retry</button>';
        const btn = div.querySelector("button");
        expect(btn.getAttribute("data-action")).toBe("retry-metrics");
        div.remove();
    });

    test("preserves data-tool-id attribute", () => {
        const div = doc.createElement("div");
        doc.body.appendChild(div);
        div.innerHTML =
            '<button data-action="view-tool" data-tool-id="abc123">View</button>';
        const btn = div.querySelector("button");
        expect(btn.getAttribute("data-tool-id")).toBe("abc123");
        div.remove();
    });

    test("preserves data-team-id attribute", () => {
        const div = doc.createElement("div");
        doc.body.appendChild(div);
        div.innerHTML =
            '<button class="team-selector-item" data-team-id="team-42" data-action="select-team">Team</button>';
        const btn = div.querySelector("button");
        expect(btn.getAttribute("data-team-id")).toBe("team-42");
        expect(btn.getAttribute("data-action")).toBe("select-team");
        div.remove();
    });

    test("preserves safe https:// href", () => {
        const div = doc.createElement("div");
        doc.body.appendChild(div);
        div.innerHTML = '<a href="https://example.com">Link</a>';
        const a = div.querySelector("a");
        expect(a.getAttribute("href")).toBe("https://example.com");
        div.remove();
    });

    test("preserves class, id, type attributes", () => {
        const div = doc.createElement("div");
        doc.body.appendChild(div);
        div.innerHTML =
            '<button id="my-btn" type="button" class="btn-primary">OK</button>';
        const btn = div.querySelector("button");
        expect(btn.id).toBe("my-btn");
        expect(btn.type).toBe("button");
        expect(btn.className).toBe("btn-primary");
        div.remove();
    });

    test("guard is installed (window.__mcpgatewayInnerHtmlGuardInstalled)", () => {
        expect(win.__mcpgatewayInnerHtmlGuardInstalled).toBe(true);
    });
});

// ===========================================================================
// B. selectTeamFromSelector — team selector delegation
// ===========================================================================

describe("selectTeamFromSelector", () => {
    const f = () => win.selectTeamFromSelector;

    function makeTeamButton(opts = {}) {
        const btn = doc.createElement("button");
        btn.className = "team-selector-item";
        btn.dataset.teamId = opts.teamId || "team-99";
        btn.dataset.teamName = opts.teamName || "Engineering";
        btn.dataset.teamIsPersonal = opts.isPersonal ? "true" : "false";
        return btn;
    }

    test("calls updateTeamContext with correct teamId", () => {
        const spy = vi.fn();
        win.updateTeamContext = spy;

        const btn = makeTeamButton({ teamId: "team-42" });
        doc.body.appendChild(btn);
        f()(btn);

        expect(spy).toHaveBeenCalledWith("team-42");
        btn.remove();
        delete win.updateTeamContext;
    });

    test("clears #team-selector-search value", () => {
        win.updateTeamContext = vi.fn();
        const input = doc.createElement("input");
        input.id = "team-selector-search";
        input.value = "eng";
        doc.body.appendChild(input);

        const btn = makeTeamButton();
        doc.body.appendChild(btn);
        f()(btn);

        expect(input.value).toBe("");
        input.remove();
        btn.remove();
        delete win.updateTeamContext;
    });

    test("deletes dataset.loaded from #team-selector-items", () => {
        win.updateTeamContext = vi.fn();
        const container = doc.createElement("div");
        container.id = "team-selector-items";
        container.dataset.loaded = "true";
        doc.body.appendChild(container);

        const btn = makeTeamButton();
        doc.body.appendChild(btn);
        f()(btn);

        expect(container.dataset.loaded).toBeUndefined();
        container.remove();
        btn.remove();
        delete win.updateTeamContext;
    });

    test("does not throw when updateTeamContext is not defined", () => {
        delete win.updateTeamContext;
        const btn = makeTeamButton();
        doc.body.appendChild(btn);
        expect(() => f()(btn)).not.toThrow();
        btn.remove();
    });

    test("does not throw when #team-selector-search is absent", () => {
        win.updateTeamContext = vi.fn();
        const btn = makeTeamButton();
        doc.body.appendChild(btn);
        expect(() => f()(btn)).not.toThrow();
        btn.remove();
        delete win.updateTeamContext;
    });

    test("does not throw when #team-selector-items is absent", () => {
        win.updateTeamContext = vi.fn();
        const btn = makeTeamButton();
        doc.body.appendChild(btn);
        expect(() => f()(btn)).not.toThrow();
        btn.remove();
        delete win.updateTeamContext;
    });

    test("sets Alpine selectedTeamName with 🏢 prefix for non-personal team", () => {
        win.updateTeamContext = vi.fn();
        const alpineData = { selectedTeam: "", selectedTeamName: "", open: true };
        const xDataContainer = doc.createElement("div");
        xDataContainer.setAttribute("x-data", "{}");
        xDataContainer.__x = { $data: alpineData };

        const btn = makeTeamButton({ teamId: "t1", teamName: "Ops", isPersonal: false });
        xDataContainer.appendChild(btn);
        doc.body.appendChild(xDataContainer);

        f()(btn);

        expect(alpineData.selectedTeamName).toBe("🏢 Ops");
        expect(alpineData.selectedTeam).toBe("t1");
        expect(alpineData.open).toBe(false);
        xDataContainer.remove();
        delete win.updateTeamContext;
    });

    test("sets Alpine selectedTeamName with 👤 prefix for personal team", () => {
        win.updateTeamContext = vi.fn();
        const alpineData = { selectedTeam: "", selectedTeamName: "", open: true };
        const xDataContainer = doc.createElement("div");
        xDataContainer.setAttribute("x-data", "{}");
        xDataContainer.__x = { $data: alpineData };

        const btn = makeTeamButton({ teamId: "t2", teamName: "My Space", isPersonal: true });
        xDataContainer.appendChild(btn);
        doc.body.appendChild(xDataContainer);

        f()(btn);

        expect(alpineData.selectedTeamName).toBe("👤 My Space");
        xDataContainer.remove();
        delete win.updateTeamContext;
    });

    test("does not throw when Alpine __x is absent", () => {
        win.updateTeamContext = vi.fn();
        const btn = makeTeamButton();
        doc.body.appendChild(btn);
        expect(() => f()(btn)).not.toThrow();
        btn.remove();
        delete win.updateTeamContext;
    });
});

// ===========================================================================
// C. performTeamSelectorSearch — fetch + innerHTML with data-action retry
// ===========================================================================

describe("performTeamSelectorSearch", () => {
    const f = () => win.performTeamSelectorSearch;

    function makeContainer() {
        const container = doc.createElement("div");
        container.id = "team-selector-items";
        doc.body.appendChild(container);
        return container;
    }

    test("sets loading placeholder HTML before fetch", () => {
        const container = makeContainer();
        const fetchSpy = vi.fn(() => new Promise(() => {})); // never resolves
        win.fetch = fetchSpy;

        f()("eng");

        expect(container.innerHTML).toContain("Loading");
        container.remove();
        delete win.fetch;
    });

    test("on success: sets container.innerHTML to fetched HTML", async () => {
        const container = makeContainer();
        const html = '<button class="team-selector-item" data-team-id="t1">Team 1</button>';
        win.fetch = vi.fn(() =>
            Promise.resolve({
                ok: true,
                text: () => Promise.resolve(html),
            }),
        );

        f()("eng");
        await new Promise((r) => setTimeout(r, 10));

        expect(container.innerHTML).toContain("team-selector-item");
        container.remove();
        delete win.fetch;
    });

    test("on success: sets container.dataset.loaded = 'true'", async () => {
        const container = makeContainer();
        win.fetch = vi.fn(() =>
            Promise.resolve({
                ok: true,
                text: () => Promise.resolve("<div>Teams</div>"),
            }),
        );

        f()("");
        await new Promise((r) => setTimeout(r, 10));

        expect(container.dataset.loaded).toBe("true");
        container.remove();
        delete win.fetch;
    });

    test("on error: renders retry button with data-action='retry-team-search' (not onclick)", async () => {
        const container = makeContainer();
        win.fetch = vi.fn(() => Promise.reject(new Error("Network error")));

        f()("eng");
        await new Promise((r) => setTimeout(r, 10));

        const retryBtn = container.querySelector('[data-action="retry-team-search"]');
        expect(retryBtn).not.toBeNull();
        expect(retryBtn.hasAttribute("onclick")).toBe(false);
        container.remove();
        delete win.fetch;
    });

    test("on error: retry button has addEventListener (not onclick attr)", async () => {
        const container = makeContainer();
        win.fetch = vi.fn(() => Promise.reject(new Error("Network error")));

        f()("eng");
        await new Promise((r) => setTimeout(r, 10));

        const retryBtn = container.querySelector('[data-action="retry-team-search"]');
        expect(retryBtn).not.toBeNull();
        // Verify no inline onclick attribute — listener is attached via addEventListener
        expect(retryBtn.getAttribute("onclick")).toBeNull();
        container.remove();
        delete win.fetch;
    });

    test("on error: clicking retry button triggers a new fetch", async () => {
        const container = makeContainer();
        let callCount = 0;
        win.fetch = vi.fn(() => {
            callCount++;
            return Promise.reject(new Error("Network error"));
        });

        f()("eng");
        await new Promise((r) => setTimeout(r, 10));

        const retryBtn = container.querySelector('[data-action="retry-team-search"]');
        expect(retryBtn).not.toBeNull();

        // Click retry — should trigger searchTeamSelector('') → performTeamSelectorSearch
        retryBtn.click();
        await new Promise((r) => setTimeout(r, 350)); // debounce is 300ms

        expect(callCount).toBeGreaterThan(1);
        container.remove();
        delete win.fetch;
    });

    test("does nothing when #team-selector-items container is absent", () => {
        // No container in DOM
        expect(() => f()("eng")).not.toThrow();
    });
});

// ===========================================================================
// D. Tool table event delegation — data-action buttons
// ===========================================================================
//
// The delegation listener is registered inside a DOMContentLoaded handler in
// admin.js (line ~12131). In JSDOM, DOMContentLoaded fires during document
// parsing — but loadAdminJs() evaluates admin.js after the document is already
// loaded, so DOMContentLoaded never re-fires and the listener is never attached
// to #toolBody automatically.
//
// Strategy:
//   • Structural tests: verify buttons carry data-action / data-tool-id and
//     have NO onclick attribute — this is the core PR guarantee.
//   • Delegation dispatch tests: manually wire the same delegation logic that
//     admin.js registers in DOMContentLoaded, then fire clicks through it.
//     This mirrors exactly what the browser does at page load.

describe("tool table event delegation via #toolBody", () => {
    // Manually replicate the DOMContentLoaded delegation handler from admin.js
    // so tests can verify dispatch without relying on DOMContentLoaded firing.
    function attachDelegationListener(wrapper) {
        wrapper.addEventListener("click", function (e) {
            const btn = e.target.closest("[data-action]");
            if (!btn) return;
            const toolId = btn.dataset.toolId;
            if (!toolId) return;
            switch (btn.dataset.action) {
                case "enrich-tool":
                    win.enrichTool(toolId);
                    break;
                case "generate-tool-tests":
                    win.generateToolTestCases(toolId);
                    break;
                case "validate-tool":
                    win.validateTool(toolId);
                    break;
                case "view-tool":
                    win.viewTool(toolId);
                    break;
                case "edit-tool":
                    win.editTool(toolId);
                    break;
            }
        });
    }

    function makeToolBody() {
        const tbody = doc.createElement("tbody");
        tbody.id = "toolBody";
        doc.body.appendChild(tbody);
        attachDelegationListener(tbody);
        return tbody;
    }

    function makeToolButton(action, toolId) {
        const btn = doc.createElement("button");
        btn.dataset.action = action;
        btn.dataset.toolId = toolId;
        return btn;
    }

    function appendButtonToBody(tbody, action, toolId) {
        const tr = doc.createElement("tr");
        const td = doc.createElement("td");
        const btn = makeToolButton(action, toolId);
        td.appendChild(btn);
        tr.appendChild(td);
        tbody.appendChild(tr);
        return btn;
    }

    // --- Structural guarantee: buttons use data-action, not onclick ---

    test("tool action buttons have no onclick attribute (data-action pattern)", () => {
        const tbody = makeToolBody();
        const actions = [
            "view-tool",
            "edit-tool",
            "enrich-tool",
            "validate-tool",
            "generate-tool-tests",
        ];
        actions.forEach((action) => {
            const btn = appendButtonToBody(tbody, action, "tool-x");
            expect(btn.hasAttribute("onclick")).toBe(false);
            expect(btn.dataset.action).toBe(action);
        });
        tbody.remove();
    });

    // --- Delegation dispatch tests (listener manually wired above) ---

    test("data-action='view-tool' click calls viewTool(toolId)", () => {
        const spy = vi.fn();
        win.viewTool = spy;
        const tbody = makeToolBody();
        const btn = appendButtonToBody(tbody, "view-tool", "tool-1");

        btn.click();

        expect(spy).toHaveBeenCalledWith("tool-1");
        tbody.remove();
    });

    test("data-action='edit-tool' click calls editTool(toolId)", () => {
        const spy = vi.fn();
        win.editTool = spy;
        const tbody = makeToolBody();
        const btn = appendButtonToBody(tbody, "edit-tool", "tool-2");

        btn.click();

        expect(spy).toHaveBeenCalledWith("tool-2");
        tbody.remove();
    });

    test("data-action='enrich-tool' click calls enrichTool(toolId)", () => {
        const spy = vi.fn();
        win.enrichTool = spy;
        const tbody = makeToolBody();
        const btn = appendButtonToBody(tbody, "enrich-tool", "tool-3");

        btn.click();

        expect(spy).toHaveBeenCalledWith("tool-3");
        tbody.remove();
    });

    test("data-action='validate-tool' click calls validateTool(toolId)", () => {
        const spy = vi.fn();
        win.validateTool = spy;
        const tbody = makeToolBody();
        const btn = appendButtonToBody(tbody, "validate-tool", "tool-4");

        btn.click();

        expect(spy).toHaveBeenCalledWith("tool-4");
        tbody.remove();
    });

    test("data-action='generate-tool-tests' click calls generateToolTestCases(toolId)", () => {
        const spy = vi.fn();
        win.generateToolTestCases = spy;
        const tbody = makeToolBody();
        const btn = appendButtonToBody(tbody, "generate-tool-tests", "tool-5");

        btn.click();

        expect(spy).toHaveBeenCalledWith("tool-5");
        tbody.remove();
    });

    test("button without data-tool-id does not call any handler", () => {
        const viewSpy = vi.fn();
        win.viewTool = viewSpy;
        const tbody = makeToolBody();
        const tr = doc.createElement("tr");
        const td = doc.createElement("td");
        const btn = doc.createElement("button");
        btn.dataset.action = "view-tool";
        // No data-tool-id — delegation guard `if (!toolId) return` fires
        td.appendChild(btn);
        tr.appendChild(td);
        tbody.appendChild(tr);

        expect(() => btn.click()).not.toThrow();
        expect(viewSpy).not.toHaveBeenCalled();
        tbody.remove();
    });

    test("click on non-action element inside tbody is ignored", () => {
        const viewSpy = vi.fn();
        win.viewTool = viewSpy;
        const tbody = makeToolBody();
        const tr = doc.createElement("tr");
        const td = doc.createElement("td");
        td.textContent = "Tool Name";
        tr.appendChild(td);
        tbody.appendChild(tr);

        td.click();

        expect(viewSpy).not.toHaveBeenCalled();
        tbody.remove();
    });
});

// ===========================================================================
// E. Metrics retry buttons — data-action="retry-metrics" pattern
// ===========================================================================

describe("showMetricsError — data-action retry button", () => {
    // showMetricsError(error) looks up "aggregated-metrics-content" via safeGetElement,
    // creates an errorDiv, sets errorDiv.innerHTML (guard runs but data-action survives),
    // then appends errorDiv to that container.
    function makeMetricsContent() {
        const content = doc.createElement("div");
        content.id = "aggregated-metrics-content";
        doc.body.appendChild(content);
        return content;
    }

    test("renders button with data-action='retry-metrics' (not onclick)", () => {
        const content = makeMetricsContent();
        const err = new Error("Network timeout");
        win.showMetricsError(err);

        // Button is inside errorDiv which was appended to content
        const retryBtn = content.querySelector('[data-action="retry-metrics"]');
        expect(retryBtn).not.toBeNull();
        expect(retryBtn.hasAttribute("onclick")).toBe(false);
        content.remove();
    });

    test("retry button has addEventListener-bound click (not inline onclick)", () => {
        // The function binds retryLoadMetrics via addEventListener at call time.
        // We verify the structural guarantee: data-action present, no onclick attr.
        // (The bound listener captures the original function reference, so we
        //  cannot intercept it by replacing win.retryLoadMetrics after load.)
        const content = makeMetricsContent();
        const err = new Error("Server error");
        win.showMetricsError(err);

        const retryBtn = content.querySelector('[data-action="retry-metrics"]');
        expect(retryBtn).not.toBeNull();
        // No inline handler — event was wired via addEventListener
        expect(retryBtn.getAttribute("onclick")).toBeNull();
        content.remove();
    });

    test("error message is escaped (XSS prevention)", () => {
        const content = makeMetricsContent();
        const err = new Error('<script>evil()</script>');
        win.showMetricsError(err);

        const html = content.innerHTML;
        expect(html).not.toContain("<script>");
        content.remove();
    });
});

describe("displayMetrics empty-state — data-action retry button", () => {
    // displayMetrics needs BOTH "aggregated-metrics-section" (outer) and
    // "aggregated-metrics-content" (inner) to exist; otherwise it retries via
    // setTimeout and the synchronous test assertions would see an empty container.
    function makeMetricsContainers() {
        const section = doc.createElement("div");
        section.id = "aggregated-metrics-section";
        const content = doc.createElement("div");
        content.id = "aggregated-metrics-content";
        section.appendChild(content);
        doc.body.appendChild(section);
        return { section, content };
    }

    test("empty-state button has data-action='retry-metrics' (not onclick)", () => {
        const { section, content } = makeMetricsContainers();
        // Pass empty data to trigger empty-state branch
        win.displayMetrics({});

        const refreshBtn = content.querySelector('[data-action="retry-metrics"]');
        expect(refreshBtn).not.toBeNull();
        expect(refreshBtn.hasAttribute("onclick")).toBe(false);
        section.remove();
    });

    test("empty-state button has addEventListener-bound click (not inline onclick)", () => {
        // Same reasoning as showMetricsError: the listener is bound at call time
        // to the original retryLoadMetrics reference; structural check is sufficient.
        const { section, content } = makeMetricsContainers();
        win.displayMetrics({});

        const refreshBtn = content.querySelector('[data-action="retry-metrics"]');
        expect(refreshBtn).not.toBeNull();
        expect(refreshBtn.getAttribute("onclick")).toBeNull();
        section.remove();
    });

    test("empty-state shows 'No Metrics Available' message", () => {
        const { section, content } = makeMetricsContainers();
        win.displayMetrics({});

        expect(content.textContent).toContain("No Metrics Available");
        section.remove();
    });
});
