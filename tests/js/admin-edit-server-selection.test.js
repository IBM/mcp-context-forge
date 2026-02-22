/**
 * Tests for the unified Map-based selection store used by both the add-server
 * and edit-server association pickers.
 *
 * Covers:
 *  - getEditSelections / resetEditSelections primitives
 *  - ensureAddStoreListeners: checkbox tracking and form reset
 *  - serverSideToolSearch: flush-before-search, restore-after-load
 *  - serverSidePromptSearch: flush-before-search, restore-after-load,
 *      and the bug fix (restores associatedPrompts, not associatedTools)
 *  - serverSideResourceSearch: flush-before-search, restore-after-load
 *  - handleServerFormSubmit: Map contents land in FormData across pagination
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
    win = loadAdminJs();
    doc = win.document;
});

afterAll(() => {
    cleanupAdminJs();
});

beforeEach(() => {
    doc.body.textContent = "";

    // Reset shared Map and listener flags between tests
    win.editServerSelections = {};
    win._addStoreListenersAttached = false;
    win._editStoreListenersAttached = false;

    // Default stubs for fetch-dependent functions
    win.ROOT_PATH = "";
    win.getSelectedGatewayIds = () => [];
    win.getCurrentTeamId = () => null;
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockResponse({
    ok = true,
    status = 200,
    body = "",
    contentType = "text/plain",
} = {}) {
    const textValue = typeof body === "string" ? body : JSON.stringify(body);
    const jsonValue =
        typeof body === "object" && body !== null
            ? body
            : (() => {
                  try {
                      return JSON.parse(body || "{}");
                  } catch {
                      return {};
                  }
              })();
    return {
        ok,
        status,
        headers: {
            get: (n) =>
                n.toLowerCase() === "content-type" ? contentType : null,
        },
        json: vi.fn().mockResolvedValue(jsonValue),
        text: vi.fn().mockResolvedValue(textValue),
        clone() {
            return mockResponse({ ok, status, body, contentType });
        },
    };
}

function addCheckbox(container, { name, value, checked = false } = {}) {
    const cb = doc.createElement("input");
    cb.type = "checkbox";
    cb.name = name;
    cb.value = value;
    cb.checked = checked;
    container.appendChild(cb);
    return cb;
}

function makeContainer(id) {
    const div = doc.createElement("div");
    div.id = id;
    doc.body.appendChild(div);
    return div;
}

// ---------------------------------------------------------------------------
// getEditSelections
// ---------------------------------------------------------------------------
describe("getEditSelections", () => {
    test("returns an empty Set for an unknown container ID", () => {
        const sel = win.getEditSelections("brand-new-container");
        expect(sel.size).toBe(0);
        expect(typeof sel.has).toBe("function");
        expect(typeof sel.add).toBe("function");
    });

    test("returns the same Set on repeated calls for the same container", () => {
        const s1 = win.getEditSelections("my-container");
        s1.add("id-x");
        const s2 = win.getEditSelections("my-container");
        expect(s2.has("id-x")).toBe(true);
    });

    test("different containers hold independent Sets", () => {
        win.getEditSelections("container-a").add("shared-id");
        expect(win.getEditSelections("container-b").has("shared-id")).toBe(
            false,
        );
    });
});

// ---------------------------------------------------------------------------
// resetEditSelections
// ---------------------------------------------------------------------------
describe("resetEditSelections", () => {
    test("clears edit-server-tools, edit-server-resources, and edit-server-prompts", () => {
        win.getEditSelections("edit-server-tools").add("t1");
        win.getEditSelections("edit-server-resources").add("r1");
        win.getEditSelections("edit-server-prompts").add("p1");

        win.resetEditSelections();

        expect(win.getEditSelections("edit-server-tools").size).toBe(0);
        expect(win.getEditSelections("edit-server-resources").size).toBe(0);
        expect(win.getEditSelections("edit-server-prompts").size).toBe(0);
    });

    test("does NOT clear add-server container keys", () => {
        win.getEditSelections("associatedTools").add("t1");
        win.getEditSelections("associatedResources").add("r1");
        win.getEditSelections("associatedPrompts").add("p1");

        win.resetEditSelections();

        expect(win.getEditSelections("associatedTools").has("t1")).toBe(true);
        expect(win.getEditSelections("associatedResources").has("r1")).toBe(
            true,
        );
        expect(win.getEditSelections("associatedPrompts").has("p1")).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// ensureAddStoreListeners
// ---------------------------------------------------------------------------
describe("ensureAddStoreListeners", () => {
    function setupContainers() {
        ["associatedTools", "associatedResources", "associatedPrompts"].forEach(
            makeContainer,
        );
    }

    test("checking a tool checkbox adds its value to the Map", () => {
        setupContainers();
        win.ensureAddStoreListeners();

        const cb = addCheckbox(doc.getElementById("associatedTools"), {
            name: "associatedTools",
            value: "tool-1",
        });
        cb.checked = true;
        cb.dispatchEvent(new win.Event("change", { bubbles: true }));

        expect(
            win.getEditSelections("associatedTools").has("tool-1"),
        ).toBe(true);
    });

    test("unchecking a tool checkbox removes its value from the Map", () => {
        setupContainers();
        win.ensureAddStoreListeners();
        win.getEditSelections("associatedTools").add("tool-1");

        const cb = addCheckbox(doc.getElementById("associatedTools"), {
            name: "associatedTools",
            value: "tool-1",
            checked: false,
        });
        cb.dispatchEvent(new win.Event("change", { bubbles: true }));

        expect(
            win.getEditSelections("associatedTools").has("tool-1"),
        ).toBe(false);
    });

    test("tracks resources and prompts checkboxes independently", () => {
        setupContainers();
        win.ensureAddStoreListeners();

        const resCb = addCheckbox(doc.getElementById("associatedResources"), {
            name: "associatedResources",
            value: "res-1",
        });
        resCb.checked = true;
        resCb.dispatchEvent(new win.Event("change", { bubbles: true }));

        const promptCb = addCheckbox(
            doc.getElementById("associatedPrompts"),
            { name: "associatedPrompts", value: "prompt-1" },
        );
        promptCb.checked = true;
        promptCb.dispatchEvent(new win.Event("change", { bubbles: true }));

        expect(
            win.getEditSelections("associatedResources").has("res-1"),
        ).toBe(true);
        expect(
            win.getEditSelections("associatedPrompts").has("prompt-1"),
        ).toBe(true);
        // Cross-container isolation
        expect(
            win.getEditSelections("associatedTools").has("res-1"),
        ).toBe(false);
    });

    test("is idempotent — calling twice does not double-count", () => {
        setupContainers();
        win.ensureAddStoreListeners();
        win.ensureAddStoreListeners();

        const cb = addCheckbox(doc.getElementById("associatedTools"), {
            name: "associatedTools",
            value: "tool-x",
        });
        cb.checked = true;
        cb.dispatchEvent(new win.Event("change", { bubbles: true }));

        // Set deduplicates, so the value is present exactly once regardless
        const sel = win.getEditSelections("associatedTools");
        expect(sel.has("tool-x")).toBe(true);
        expect(sel.size).toBe(1);
    });

    test("form reset clears all add-server selections from the Map", () => {
        setupContainers();
        const form = doc.createElement("form");
        form.id = "add-server-form";
        doc.body.appendChild(form);

        win.ensureAddStoreListeners();
        win.getEditSelections("associatedTools").add("t1");
        win.getEditSelections("associatedResources").add("r1");
        win.getEditSelections("associatedPrompts").add("p1");

        form.dispatchEvent(new win.Event("reset"));

        expect(win.getEditSelections("associatedTools").size).toBe(0);
        expect(win.getEditSelections("associatedResources").size).toBe(0);
        expect(win.getEditSelections("associatedPrompts").size).toBe(0);
    });

    test("form reset does not clear edit-server selections", () => {
        setupContainers();
        const form = doc.createElement("form");
        form.id = "add-server-form";
        doc.body.appendChild(form);

        win.ensureAddStoreListeners();
        win.getEditSelections("edit-server-tools").add("t1");

        form.dispatchEvent(new win.Event("reset"));

        expect(win.getEditSelections("edit-server-tools").has("t1")).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// serverSideToolSearch
// ---------------------------------------------------------------------------
describe("serverSideToolSearch", () => {
    function setupToolsContainer(checkboxes = []) {
        const container = makeContainer("associatedTools");
        checkboxes.forEach((c) =>
            addCheckbox(container, { name: "associatedTools", ...c }),
        );
        return container;
    }

    beforeEach(() => {
        win.initToolSelect = vi.fn();
        win.updateToolMapping = vi.fn();
    });

    test("flushes checked checkboxes into the Map before clearing the container", async () => {
        setupToolsContainer([
            { value: "t1", checked: true },
            { value: "t2", checked: false },
        ]);

        win.fetch = vi
            .fn()
            .mockResolvedValue(
                mockResponse({ ok: true, contentType: "text/html", body: "" }),
            );

        await win.serverSideToolSearch("");

        const toolSel = win.getEditSelections("associatedTools");
        expect(toolSel.has("t1")).toBe(true);
        expect(toolSel.has("t2")).toBe(false);
    });

    test("restores previously selected checkboxes after empty-string search reloads", async () => {
        setupToolsContainer([{ value: "t1", checked: true }]);

        const newHtml = `
            <input type="checkbox" name="associatedTools" value="t1">
            <input type="checkbox" name="associatedTools" value="t2">
        `;
        win.fetch = vi
            .fn()
            .mockResolvedValue(
                mockResponse({ ok: true, contentType: "text/html", body: newHtml }),
            );

        await win.serverSideToolSearch("");

        const container = doc.getElementById("associatedTools");
        const checked = Array.from(
            container.querySelectorAll(
                'input[name="associatedTools"]:checked',
            ),
        ).map((cb) => cb.value);

        expect(checked).toContain("t1");
        expect(checked).not.toContain("t2");
    });

    test("restores selections after keyword search results are rendered", async () => {
        setupToolsContainer([{ value: "t1", checked: true }]);

        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "application/json",
                body: {
                    tools: [
                        { id: "t1", name: "Tool One" },
                        { id: "t3", name: "Tool Three" },
                    ],
                },
            }),
        );

        await win.serverSideToolSearch("tool");

        const container = doc.getElementById("associatedTools");
        const checked = Array.from(
            container.querySelectorAll(
                'input[name="associatedTools"]:checked',
            ),
        ).map((cb) => cb.value);

        expect(checked).toContain("t1");
        expect(checked).not.toContain("t3");
    });

    test("accumulates selections across two successive searches", async () => {
        setupToolsContainer([{ value: "t1", checked: true }]);

        // First search returns t1
        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "application/json",
                body: { tools: [{ id: "t1", name: "Tool One" }] },
            }),
        );
        await win.serverSideToolSearch("one");

        // Simulate user checking t2 in search results
        const container = doc.getElementById("associatedTools");
        addCheckbox(container, {
            name: "associatedTools",
            value: "t2",
            checked: true,
        });

        // Second search returns both t1 and t2
        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "application/json",
                body: {
                    tools: [
                        { id: "t1", name: "Tool One" },
                        { id: "t2", name: "Tool Two" },
                    ],
                },
            }),
        );
        await win.serverSideToolSearch("tool");

        const checked = Array.from(
            container.querySelectorAll(
                'input[name="associatedTools"]:checked',
            ),
        ).map((cb) => cb.value);

        expect(checked).toContain("t1");
        expect(checked).toContain("t2");
    });
});

// ---------------------------------------------------------------------------
// serverSidePromptSearch
// ---------------------------------------------------------------------------
describe("serverSidePromptSearch", () => {
    function setupPromptsContainer(checkboxes = []) {
        const container = makeContainer("associatedPrompts");
        checkboxes.forEach((c) =>
            addCheckbox(container, { name: "associatedPrompts", ...c }),
        );
        return container;
    }

    beforeEach(() => {
        win.initPromptSelect = vi.fn();
        win.updatePromptMapping = vi.fn();
    });

    test("flushes checked prompt checkboxes into the Map before search", async () => {
        setupPromptsContainer([
            { value: "p1", checked: true },
            { value: "p2", checked: false },
        ]);

        win.fetch = vi
            .fn()
            .mockResolvedValue(
                mockResponse({ ok: true, contentType: "text/html", body: "" }),
            );

        await win.serverSidePromptSearch("");

        const promptSel = win.getEditSelections("associatedPrompts");
        expect(promptSel.has("p1")).toBe(true);
        expect(promptSel.has("p2")).toBe(false);
    });

    test("restores previously selected prompts after empty-string search reloads", async () => {
        setupPromptsContainer([{ value: "p1", checked: true }]);

        const newHtml = `
            <input type="checkbox" name="associatedPrompts" value="p1">
            <input type="checkbox" name="associatedPrompts" value="p2">
        `;
        win.fetch = vi
            .fn()
            .mockResolvedValue(
                mockResponse({ ok: true, contentType: "text/html", body: newHtml }),
            );

        await win.serverSidePromptSearch("");

        const container = doc.getElementById("associatedPrompts");
        const checked = Array.from(
            container.querySelectorAll(
                'input[name="associatedPrompts"]:checked',
            ),
        ).map((cb) => cb.value);

        expect(checked).toContain("p1");
        expect(checked).not.toContain("p2");
    });

    // -----------------------------------------------------------------------
    // Bug fix: after empty-string search, the restore code must query
    // 'input[name="associatedPrompts"]' — NOT 'input[name="associatedTools"]'.
    // -----------------------------------------------------------------------
    test("bug fix: only restores associatedPrompts checkboxes, not associatedTools", async () => {
        setupPromptsContainer([{ value: "p1", checked: true }]);

        // New content contains both prompt AND tool checkboxes
        const newHtml = `
            <input type="checkbox" name="associatedPrompts" value="p1">
            <input type="checkbox" name="associatedPrompts" value="p2">
            <input type="checkbox" name="associatedTools"   value="t1">
        `;
        win.fetch = vi
            .fn()
            .mockResolvedValue(
                mockResponse({ ok: true, contentType: "text/html", body: newHtml }),
            );

        await win.serverSidePromptSearch("");

        const container = doc.getElementById("associatedPrompts");

        const checkedPrompts = Array.from(
            container.querySelectorAll(
                'input[name="associatedPrompts"]:checked',
            ),
        ).map((cb) => cb.value);
        expect(checkedPrompts).toContain("p1");
        expect(checkedPrompts).not.toContain("p2");

        // The tool checkbox must NOT have been checked by the prompt restore
        const checkedTools = Array.from(
            container.querySelectorAll('input[name="associatedTools"]:checked'),
        ).map((cb) => cb.value);
        expect(checkedTools).toHaveLength(0);
    });
});

// ---------------------------------------------------------------------------
// serverSideResourceSearch
// ---------------------------------------------------------------------------
describe("serverSideResourceSearch", () => {
    function setupResourcesContainer(checkboxes = []) {
        const container = makeContainer("associatedResources");
        checkboxes.forEach((c) =>
            addCheckbox(container, { name: "associatedResources", ...c }),
        );
        return container;
    }

    beforeEach(() => {
        win.initResourceSelect = vi.fn();
        win.updateResourceMapping = vi.fn();
    });

    test("flushes checked resource checkboxes into the Map before search", async () => {
        setupResourcesContainer([
            { value: "r1", checked: true },
            { value: "r2", checked: false },
        ]);

        win.fetch = vi
            .fn()
            .mockResolvedValue(
                mockResponse({ ok: true, contentType: "text/html", body: "" }),
            );

        await win.serverSideResourceSearch("");

        const resSel = win.getEditSelections("associatedResources");
        expect(resSel.has("r1")).toBe(true);
        expect(resSel.has("r2")).toBe(false);
    });

    test("restores previously selected resources after empty-string search reloads", async () => {
        setupResourcesContainer([{ value: "r1", checked: true }]);

        const newHtml = `
            <input type="checkbox" name="associatedResources" value="r1">
            <input type="checkbox" name="associatedResources" value="r2">
        `;
        win.fetch = vi
            .fn()
            .mockResolvedValue(
                mockResponse({ ok: true, contentType: "text/html", body: newHtml }),
            );

        await win.serverSideResourceSearch("");

        const container = doc.getElementById("associatedResources");
        const checked = Array.from(
            container.querySelectorAll(
                'input[name="associatedResources"]:checked',
            ),
        ).map((cb) => cb.value);

        expect(checked).toContain("r1");
        expect(checked).not.toContain("r2");
    });

    test("restores selections after keyword search results are rendered", async () => {
        setupResourcesContainer([{ value: "r1", checked: true }]);

        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "application/json",
                body: {
                    resources: [
                        { id: "r1", name: "Resource One" },
                        { id: "r3", name: "Resource Three" },
                    ],
                },
            }),
        );

        await win.serverSideResourceSearch("res");

        const container = doc.getElementById("associatedResources");
        const checked = Array.from(
            container.querySelectorAll(
                'input[name="associatedResources"]:checked',
            ),
        ).map((cb) => cb.value);

        expect(checked).toContain("r1");
        expect(checked).not.toContain("r3");
    });
});

// ---------------------------------------------------------------------------
// handleServerFormSubmit — Map contents must reach the POST FormData
// ---------------------------------------------------------------------------
describe("handleServerFormSubmit", () => {
    function setupForm(name = "test-server") {
        const form = doc.createElement("form");
        form.id = "add-server-form";
        form.action = "/admin/servers";

        const nameInput = doc.createElement("input");
        nameInput.type = "text";
        nameInput.name = "name";
        nameInput.value = name;
        form.appendChild(nameInput);

        const vis = doc.createElement("input");
        vis.name = "visibility";
        vis.value = "public";
        form.appendChild(vis);

        doc.body.appendChild(form);
        return form;
    }

    function fakeSubmitEvent(form) {
        return { target: form, preventDefault: vi.fn() };
    }

    beforeEach(() => {
        win.validateInputName = () => ({ valid: true });
        win.isInactiveChecked = () => false;
        win.safeParseJsonResponse = async () => ({ success: true });
        win.showSuccessMessage = vi.fn();
        win.showErrorMessage = vi.fn();
        win.reloadAllResourceSections = vi.fn();
        win.safeGetElement = (id) => doc.getElementById(id);
    });

    test("includes all tool IDs from the Map — including those from previous pages", async () => {
        // Pre-seed Map (simulates tools selected on earlier scroll pages)
        win.getEditSelections("associatedTools").add("t1");
        win.getEditSelections("associatedTools").add("t2");

        const form = setupForm();

        // Only t3 is currently visible and checked
        const toolsDiv = makeContainer("associatedTools");
        addCheckbox(toolsDiv, { name: "associatedTools", value: "t3", checked: true });
        makeContainer("associatedResources");
        makeContainer("associatedPrompts");

        let capturedBody = null;
        win.fetch = vi.fn().mockImplementation((_url, opts) => {
            capturedBody = opts.body;
            return Promise.resolve(
                mockResponse({
                    ok: true,
                    contentType: "application/json",
                    body: { success: true },
                }),
            );
        });

        await win.handleServerFormSubmit(fakeSubmitEvent(form));

        const submitted = capturedBody.getAll("associatedTools");
        expect(submitted).toContain("t1");
        expect(submitted).toContain("t2");
        expect(submitted).toContain("t3");
    });

    test("deduplicates a tool ID that is both in the Map and currently checked", async () => {
        win.getEditSelections("associatedTools").add("t1");

        const form = setupForm();
        const toolsDiv = makeContainer("associatedTools");
        addCheckbox(toolsDiv, { name: "associatedTools", value: "t1", checked: true });
        makeContainer("associatedResources");
        makeContainer("associatedPrompts");

        let capturedBody = null;
        win.fetch = vi.fn().mockImplementation((_url, opts) => {
            capturedBody = opts.body;
            return Promise.resolve(
                mockResponse({
                    ok: true,
                    contentType: "application/json",
                    body: { success: true },
                }),
            );
        });

        await win.handleServerFormSubmit(fakeSubmitEvent(form));

        const submitted = capturedBody.getAll("associatedTools");
        expect(submitted.filter((id) => id === "t1")).toHaveLength(1);
    });

    test("includes resources and prompts from the Map", async () => {
        win.getEditSelections("associatedResources").add("r1");
        win.getEditSelections("associatedPrompts").add("p1");

        const form = setupForm();
        makeContainer("associatedTools");
        makeContainer("associatedResources");
        makeContainer("associatedPrompts");

        let capturedBody = null;
        win.fetch = vi.fn().mockImplementation((_url, opts) => {
            capturedBody = opts.body;
            return Promise.resolve(
                mockResponse({
                    ok: true,
                    contentType: "application/json",
                    body: { success: true },
                }),
            );
        });

        await win.handleServerFormSubmit(fakeSubmitEvent(form));

        expect(capturedBody.getAll("associatedResources")).toContain("r1");
        expect(capturedBody.getAll("associatedPrompts")).toContain("p1");
    });
});
