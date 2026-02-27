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
let realInitToolSelect;

beforeAll(() => {
    win = loadAdminJs();
    doc = win.document;
    realInitToolSelect = win.initToolSelect;
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

        expect(win.getEditSelections("associatedTools").has("tool-1")).toBe(
            true,
        );
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

        expect(win.getEditSelections("associatedTools").has("tool-1")).toBe(
            false,
        );
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

        const promptCb = addCheckbox(doc.getElementById("associatedPrompts"), {
            name: "associatedPrompts",
            value: "prompt-1",
        });
        promptCb.checked = true;
        promptCb.dispatchEvent(new win.Event("change", { bubbles: true }));

        expect(win.getEditSelections("associatedResources").has("res-1")).toBe(
            true,
        );
        expect(win.getEditSelections("associatedPrompts").has("prompt-1")).toBe(
            true,
        );
        // Cross-container isolation
        expect(win.getEditSelections("associatedTools").has("res-1")).toBe(
            false,
        );
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
        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "text/html",
                body: newHtml,
            }),
        );

        await win.serverSideToolSearch("");

        const container = doc.getElementById("associatedTools");
        const checked = Array.from(
            container.querySelectorAll('input[name="associatedTools"]:checked'),
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
            container.querySelectorAll('input[name="associatedTools"]:checked'),
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
            container.querySelectorAll('input[name="associatedTools"]:checked'),
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
        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "text/html",
                body: newHtml,
            }),
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
        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "text/html",
                body: newHtml,
            }),
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
        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "text/html",
                body: newHtml,
            }),
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
        addCheckbox(toolsDiv, {
            name: "associatedTools",
            value: "t3",
            checked: true,
        });
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
        addCheckbox(toolsDiv, {
            name: "associatedTools",
            value: "t1",
            checked: true,
        });
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

// ---------------------------------------------------------------------------
// ensureEditStoreListeners
// ---------------------------------------------------------------------------
describe("ensureEditStoreListeners", () => {
    function setupEditContainers() {
        [
            "edit-server-tools",
            "edit-server-resources",
            "edit-server-prompts",
        ].forEach(makeContainer);
    }

    test("checking an edit-server-tools checkbox adds its value to the Map", () => {
        setupEditContainers();
        win.ensureEditStoreListeners();

        const cb = addCheckbox(doc.getElementById("edit-server-tools"), {
            name: "associatedTools",
            value: "tool-edit-1",
        });
        cb.checked = true;
        cb.dispatchEvent(new win.Event("change", { bubbles: true }));

        expect(
            win.getEditSelections("edit-server-tools").has("tool-edit-1"),
        ).toBe(true);
    });

    test("unchecking an edit-server-tools checkbox removes its value from the Map", () => {
        setupEditContainers();
        win.ensureEditStoreListeners();
        win.getEditSelections("edit-server-tools").add("tool-edit-1");

        const cb = addCheckbox(doc.getElementById("edit-server-tools"), {
            name: "associatedTools",
            value: "tool-edit-1",
            checked: false,
        });
        cb.dispatchEvent(new win.Event("change", { bubbles: true }));

        expect(
            win.getEditSelections("edit-server-tools").has("tool-edit-1"),
        ).toBe(false);
    });

    test("tracks edit-server resources and prompts independently", () => {
        setupEditContainers();
        win.ensureEditStoreListeners();

        const resCb = addCheckbox(doc.getElementById("edit-server-resources"), {
            name: "associatedResources",
            value: "res-e1",
        });
        resCb.checked = true;
        resCb.dispatchEvent(new win.Event("change", { bubbles: true }));

        const promptCb = addCheckbox(
            doc.getElementById("edit-server-prompts"),
            { name: "associatedPrompts", value: "prompt-e1" },
        );
        promptCb.checked = true;
        promptCb.dispatchEvent(new win.Event("change", { bubbles: true }));

        expect(
            win.getEditSelections("edit-server-resources").has("res-e1"),
        ).toBe(true);
        expect(
            win.getEditSelections("edit-server-prompts").has("prompt-e1"),
        ).toBe(true);
        // Cross-container isolation
        expect(win.getEditSelections("edit-server-tools").has("res-e1")).toBe(
            false,
        );
    });

    test("is idempotent — calling twice does not double-count", () => {
        setupEditContainers();
        win.ensureEditStoreListeners();
        win.ensureEditStoreListeners();

        const cb = addCheckbox(doc.getElementById("edit-server-tools"), {
            name: "associatedTools",
            value: "tool-x",
        });
        cb.checked = true;
        cb.dispatchEvent(new win.Event("change", { bubbles: true }));

        const sel = win.getEditSelections("edit-server-tools");
        expect(sel.has("tool-x")).toBe(true);
        expect(sel.size).toBe(1);
    });
});

// ---------------------------------------------------------------------------
// closeModal resets edit selections
// ---------------------------------------------------------------------------
describe("closeModal edit-server reset", () => {
    test("closing server-edit-modal calls resetEditSelections", () => {
        // Create the modal element
        const modal = doc.createElement("div");
        modal.id = "server-edit-modal";
        modal.classList.remove("hidden"); // modal is visible
        doc.body.appendChild(modal);

        // Seed the store
        win.getEditSelections("edit-server-tools").add("t1");
        win.getEditSelections("edit-server-resources").add("r1");
        win.getEditSelections("edit-server-prompts").add("p1");

        win.closeModal("server-edit-modal");

        expect(win.getEditSelections("edit-server-tools").size).toBe(0);
        expect(win.getEditSelections("edit-server-resources").size).toBe(0);
        expect(win.getEditSelections("edit-server-prompts").size).toBe(0);
    });

    test("closing server-edit-modal removes stale selectAll hidden inputs", () => {
        const modal = doc.createElement("div");
        modal.id = "server-edit-modal";
        doc.body.appendChild(modal);

        // Create edit containers with stale hidden inputs (simulates a previous Select All)
        [
            {
                id: "edit-server-tools",
                names: ["selectAllTools", "allToolIds"],
            },
            {
                id: "edit-server-resources",
                names: ["selectAllResources", "allResourceIds"],
            },
            {
                id: "edit-server-prompts",
                names: ["selectAllPrompts", "allPromptIds"],
            },
        ].forEach(({ id, names }) => {
            const container = makeContainer(id);
            names.forEach((n) => {
                const hidden = doc.createElement("input");
                hidden.type = "hidden";
                hidden.name = n;
                hidden.value = n.includes("All") ? "true" : '["id1","id2"]';
                container.appendChild(hidden);
            });
        });

        win.closeModal("server-edit-modal");

        // All hidden inputs must be removed
        expect(
            doc
                .getElementById("edit-server-tools")
                .querySelector('input[name="selectAllTools"]'),
        ).toBeNull();
        expect(
            doc
                .getElementById("edit-server-tools")
                .querySelector('input[name="allToolIds"]'),
        ).toBeNull();
        expect(
            doc
                .getElementById("edit-server-resources")
                .querySelector('input[name="selectAllResources"]'),
        ).toBeNull();
        expect(
            doc
                .getElementById("edit-server-resources")
                .querySelector('input[name="allResourceIds"]'),
        ).toBeNull();
        expect(
            doc
                .getElementById("edit-server-prompts")
                .querySelector('input[name="selectAllPrompts"]'),
        ).toBeNull();
        expect(
            doc
                .getElementById("edit-server-prompts")
                .querySelector('input[name="allPromptIds"]'),
        ).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// handleEditServerFormSubmit — store contents override FormData
// ---------------------------------------------------------------------------
describe("handleEditServerFormSubmit", () => {
    function setupEditForm() {
        const form = doc.createElement("form");
        form.id = "edit-server-form";
        form.action = "/admin/servers/1";

        const nameInput = doc.createElement("input");
        nameInput.type = "text";
        nameInput.name = "name";
        nameInput.value = "my-server";
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

    test("includes off-screen tool IDs from the edit store", async () => {
        // Pre-seed store (simulates tools on earlier pages)
        win.getEditSelections("edit-server-tools").add("t1");
        win.getEditSelections("edit-server-tools").add("t2");

        const form = setupEditForm();

        // Only t3 is visible and checked in the DOM
        const toolsDiv = makeContainer("edit-server-tools");
        addCheckbox(toolsDiv, {
            name: "associatedTools",
            value: "t3",
            checked: true,
        });
        makeContainer("edit-server-resources");
        makeContainer("edit-server-prompts");

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

        await win.handleEditServerFormSubmit(fakeSubmitEvent(form));

        const submitted = capturedBody.getAll("associatedTools");
        expect(submitted).toContain("t1");
        expect(submitted).toContain("t2");
        expect(submitted).toContain("t3");
    });

    test("unchecked visible items are removed from the store on submit", async () => {
        // t1 was in the store (selected on page 1), but user unchecked it on current page
        win.getEditSelections("edit-server-tools").add("t1");
        win.getEditSelections("edit-server-tools").add("t2");

        const form = setupEditForm();

        const toolsDiv = makeContainer("edit-server-tools");
        addCheckbox(toolsDiv, {
            name: "associatedTools",
            value: "t1",
            checked: false,
        }); // unchecked
        makeContainer("edit-server-resources");
        makeContainer("edit-server-prompts");

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

        await win.handleEditServerFormSubmit(fakeSubmitEvent(form));

        const submitted = capturedBody.getAll("associatedTools");
        expect(submitted).not.toContain("t1");
        expect(submitted).toContain("t2");
    });

    test("includes edit-server resources and prompts from the store", async () => {
        win.getEditSelections("edit-server-resources").add("r1");
        win.getEditSelections("edit-server-prompts").add("p1");

        const form = setupEditForm();
        makeContainer("edit-server-tools");
        makeContainer("edit-server-resources");
        makeContainer("edit-server-prompts");

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

        await win.handleEditServerFormSubmit(fakeSubmitEvent(form));

        expect(capturedBody.getAll("associatedResources")).toContain("r1");
        expect(capturedBody.getAll("associatedPrompts")).toContain("p1");
    });
});

// ---------------------------------------------------------------------------
// serverSideEditToolSearch — edit-mode search flush and restore
// ---------------------------------------------------------------------------
describe("serverSideEditToolSearch", () => {
    function setupEditToolsContainer(checkboxes = []) {
        const container = makeContainer("edit-server-tools");
        checkboxes.forEach((c) =>
            addCheckbox(container, { name: "associatedTools", ...c }),
        );
        return container;
    }

    beforeEach(() => {
        win.initToolSelect = vi.fn();
        win.updateToolMapping = vi.fn();
    });

    test("flushes checked edit-mode checkboxes into the Map before search", async () => {
        setupEditToolsContainer([
            { value: "t1", checked: true },
            { value: "t2", checked: false },
        ]);

        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "text/html",
                body: "",
            }),
        );

        await win.serverSideEditToolSearch("");

        const toolSel = win.getEditSelections("edit-server-tools");
        expect(toolSel.has("t1")).toBe(true);
        expect(toolSel.has("t2")).toBe(false);
    });

    test("restores selections from store after clear-search reload", async () => {
        const container = setupEditToolsContainer([
            { value: "t1", checked: true },
        ]);
        container.setAttribute(
            "data-server-tools",
            JSON.stringify(["OriginalToolName"]),
        );

        const newHtml = `
            <input type="checkbox" name="associatedTools" value="t1" data-tool-name="Tool One">
            <input type="checkbox" name="associatedTools" value="t2" data-tool-name="Tool Two">
        `;
        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "text/html",
                body: newHtml,
            }),
        );

        await win.serverSideEditToolSearch("");

        const checked = Array.from(
            doc
                .getElementById("edit-server-tools")
                .querySelectorAll('input[name="associatedTools"]:checked'),
        ).map((cb) => cb.value);

        expect(checked).toContain("t1");
        expect(checked).not.toContain("t2");
    });

    test("restores selections from store after keyword search", async () => {
        setupEditToolsContainer([{ value: "t1", checked: true }]);

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

        await win.serverSideEditToolSearch("tool");

        const checked = Array.from(
            doc
                .getElementById("edit-server-tools")
                .querySelectorAll('input[name="associatedTools"]:checked'),
        ).map((cb) => cb.value);

        expect(checked).toContain("t1");
        expect(checked).not.toContain("t3");
    });
});

// ---------------------------------------------------------------------------
// toggleViewPublic — listener accumulation regression (#3278)
// ---------------------------------------------------------------------------
describe("toggleViewPublic — listener accumulation regression", () => {
    test("calling toggleViewPublic multiple times does not multiply HTMX calls per toggle", () => {
        const cb = doc.createElement("input");
        cb.type = "checkbox";
        cb.id = "edit-server-view-public";
        doc.body.appendChild(cb);

        const container = doc.createElement("div");
        container.id = "edit-server-tools";
        container.setAttribute(
            "hx-get",
            "/admin/tools/partial?page=1&render=selector&team_id=team-xyz",
        );
        doc.body.appendChild(container);

        const originalHtmx = win.htmx;
        win.htmx = { process: vi.fn(), trigger: vi.fn() };

        // Simulate opening the edit modal 3 times (each call previously added a listener)
        win.toggleViewPublic(
            "edit-server-view-public",
            ["edit-server-tools"],
            "team-xyz",
        );
        win.toggleViewPublic(
            "edit-server-view-public",
            ["edit-server-tools"],
            "team-xyz",
        );
        win.toggleViewPublic(
            "edit-server-view-public",
            ["edit-server-tools"],
            "team-xyz",
        );

        // Toggle the checkbox once — should trigger exactly one HTMX call, not three
        cb.checked = true;
        cb.dispatchEvent(new win.Event("change"));

        expect(win.htmx.process).toHaveBeenCalledTimes(1);
        expect(win.htmx.trigger).toHaveBeenCalledTimes(1);

        win.htmx = originalHtmx;
    });
});

// ---------------------------------------------------------------------------
// View Public checkbox — search function integration (#3278)
// ---------------------------------------------------------------------------
describe("View Public checkbox — search function integration", () => {
    function makeViewPublicCheckbox(id, checked = false) {
        const cb = doc.createElement("input");
        cb.type = "checkbox";
        cb.id = id;
        cb.checked = checked;
        doc.body.appendChild(cb);
        return cb;
    }

    // --- serverSideToolSearch (Add Server) ---

    describe("serverSideToolSearch respects View Public state", () => {
        beforeEach(() => {
            win.initToolSelect = vi.fn();
            win.updateToolMapping = vi.fn();
        });

        test("keyword search includes team_id when View Public is unchecked", async () => {
            makeContainer("associatedTools");
            win.getCurrentTeamId = () => "team-abc";

            win.fetch = vi.fn().mockResolvedValue(
                mockResponse({
                    ok: true,
                    contentType: "application/json",
                    body: { tools: [] },
                }),
            );

            // No checkbox in DOM — should include team_id (default)
            await win.serverSideToolSearch("myTool");

            const fetchUrl = win.fetch.mock.calls[0][0];
            expect(fetchUrl).toContain("team_id=team-abc");
        });

        test("keyword search omits team_id when View Public is checked", async () => {
            makeContainer("associatedTools");
            makeViewPublicCheckbox("add-server-view-public", true);
            win.getCurrentTeamId = () => "team-abc";

            win.fetch = vi.fn().mockResolvedValue(
                mockResponse({
                    ok: true,
                    contentType: "application/json",
                    body: { tools: [] },
                }),
            );

            await win.serverSideToolSearch("myTool");

            const fetchUrl = win.fetch.mock.calls[0][0];
            expect(fetchUrl).not.toContain("team_id");
        });
    });

    // --- serverSidePromptSearch (Add Server) ---

    describe("serverSidePromptSearch respects View Public state", () => {
        beforeEach(() => {
            win.initPromptSelect = vi.fn();
            win.updatePromptMapping = vi.fn();
        });

        test("keyword search includes team_id when View Public is unchecked", async () => {
            makeContainer("associatedPrompts");
            win.getCurrentTeamId = () => "team-abc";

            win.fetch = vi.fn().mockResolvedValue(
                mockResponse({
                    ok: true,
                    contentType: "application/json",
                    body: { prompts: [] },
                }),
            );

            await win.serverSidePromptSearch("myPrompt");

            const fetchUrl = win.fetch.mock.calls[0][0];
            expect(fetchUrl).toContain("team_id=team-abc");
        });

        test("keyword search omits team_id when View Public is checked", async () => {
            makeContainer("associatedPrompts");
            makeViewPublicCheckbox("add-server-view-public", true);
            win.getCurrentTeamId = () => "team-abc";

            win.fetch = vi.fn().mockResolvedValue(
                mockResponse({
                    ok: true,
                    contentType: "application/json",
                    body: { prompts: [] },
                }),
            );

            await win.serverSidePromptSearch("myPrompt");

            const fetchUrl = win.fetch.mock.calls[0][0];
            expect(fetchUrl).not.toContain("team_id");
        });
    });

    // --- serverSideResourceSearch (Add Server) ---

    describe("serverSideResourceSearch respects View Public state", () => {
        beforeEach(() => {
            win.initResourceSelect = vi.fn();
            win.updateResourceMapping = vi.fn();
        });

        test("keyword search includes team_id when View Public is unchecked", async () => {
            makeContainer("associatedResources");
            win.getCurrentTeamId = () => "team-abc";

            win.fetch = vi.fn().mockResolvedValue(
                mockResponse({
                    ok: true,
                    contentType: "application/json",
                    body: { resources: [] },
                }),
            );

            await win.serverSideResourceSearch("myRes");

            const fetchUrl = win.fetch.mock.calls[0][0];
            expect(fetchUrl).toContain("team_id=team-abc");
        });

        test("keyword search omits team_id when View Public is checked", async () => {
            makeContainer("associatedResources");
            makeViewPublicCheckbox("add-server-view-public", true);
            win.getCurrentTeamId = () => "team-abc";

            win.fetch = vi.fn().mockResolvedValue(
                mockResponse({
                    ok: true,
                    contentType: "application/json",
                    body: { resources: [] },
                }),
            );

            await win.serverSideResourceSearch("myRes");

            const fetchUrl = win.fetch.mock.calls[0][0];
            expect(fetchUrl).not.toContain("team_id");
        });
    });

    // --- serverSideEditToolSearch (Edit Server) ---

    describe("serverSideEditToolSearch respects View Public state", () => {
        beforeEach(() => {
            win.initToolSelect = vi.fn();
            win.updateToolMapping = vi.fn();
        });

        test("keyword search includes team_id when View Public is unchecked", async () => {
            makeContainer("edit-server-tools");
            win.getCurrentTeamId = () => "team-abc";

            win.fetch = vi.fn().mockResolvedValue(
                mockResponse({
                    ok: true,
                    contentType: "application/json",
                    body: { tools: [] },
                }),
            );

            await win.serverSideEditToolSearch("myTool");

            const fetchUrl = win.fetch.mock.calls[0][0];
            expect(fetchUrl).toContain("team_id=team-abc");
        });

        test("keyword search omits team_id when View Public is checked", async () => {
            makeContainer("edit-server-tools");
            makeViewPublicCheckbox("edit-server-view-public", true);
            win.getCurrentTeamId = () => "team-abc";

            win.fetch = vi.fn().mockResolvedValue(
                mockResponse({
                    ok: true,
                    contentType: "application/json",
                    body: { tools: [] },
                }),
            );

            await win.serverSideEditToolSearch("myTool");

            const fetchUrl = win.fetch.mock.calls[0][0];
            expect(fetchUrl).not.toContain("team_id");
        });
    });

    // --- serverSideEditPromptsSearch (Edit Server) ---

    describe("serverSideEditPromptsSearch respects View Public state", () => {
        beforeEach(() => {
            win.initPromptSelect = vi.fn();
            win.updatePromptMapping = vi.fn();
        });

        test("keyword search includes team_id when View Public is unchecked", async () => {
            makeContainer("edit-server-prompts");
            win.getCurrentTeamId = () => "team-abc";

            win.fetch = vi.fn().mockResolvedValue(
                mockResponse({
                    ok: true,
                    contentType: "application/json",
                    body: { prompts: [] },
                }),
            );

            await win.serverSideEditPromptsSearch("myPrompt");

            const fetchUrl = win.fetch.mock.calls[0][0];
            expect(fetchUrl).toContain("team_id=team-abc");
        });

        test("keyword search omits team_id when View Public is checked", async () => {
            makeContainer("edit-server-prompts");
            makeViewPublicCheckbox("edit-server-view-public", true);
            win.getCurrentTeamId = () => "team-abc";

            win.fetch = vi.fn().mockResolvedValue(
                mockResponse({
                    ok: true,
                    contentType: "application/json",
                    body: { prompts: [] },
                }),
            );

            await win.serverSideEditPromptsSearch("myPrompt");

            const fetchUrl = win.fetch.mock.calls[0][0];
            expect(fetchUrl).not.toContain("team_id");
        });
    });

    // --- serverSideEditResourcesSearch (Edit Server) ---

    describe("serverSideEditResourcesSearch respects View Public state", () => {
        beforeEach(() => {
            win.initResourceSelect = vi.fn();
            win.updateResourceMapping = vi.fn();
        });

        test("keyword search includes team_id when View Public is unchecked", async () => {
            makeContainer("edit-server-resources");
            win.getCurrentTeamId = () => "team-abc";

            win.fetch = vi.fn().mockResolvedValue(
                mockResponse({
                    ok: true,
                    contentType: "application/json",
                    body: { resources: [] },
                }),
            );

            await win.serverSideEditResourcesSearch("myRes");

            const fetchUrl = win.fetch.mock.calls[0][0];
            expect(fetchUrl).toContain("team_id=team-abc");
        });

        test("keyword search omits team_id when View Public is checked", async () => {
            makeContainer("edit-server-resources");
            makeViewPublicCheckbox("edit-server-view-public", true);
            win.getCurrentTeamId = () => "team-abc";

            win.fetch = vi.fn().mockResolvedValue(
                mockResponse({
                    ok: true,
                    contentType: "application/json",
                    body: { resources: [] },
                }),
            );

            await win.serverSideEditResourcesSearch("myRes");

            const fetchUrl = win.fetch.mock.calls[0][0];
            expect(fetchUrl).not.toContain("team_id");
        });
    });
});

// ---------------------------------------------------------------------------
// ALLOW_PUBLIC_VISIBILITY — edit modal legacy-public coercion
// ---------------------------------------------------------------------------
describe("editServer visibility coercion when ALLOW_PUBLIC_VISIBILITY is false", () => {
    let flagWin;
    let flagDoc;

    beforeAll(() => {
        flagWin = loadAdminJs({
            beforeEval: (w) => {
                w.ALLOW_PUBLIC_VISIBILITY = false;
            },
        });
        flagDoc = flagWin.document;
    });

    afterAll(() => {
        cleanupAdminJs();
    });

    beforeEach(() => {
        flagDoc.body.textContent = "";
        flagWin.ROOT_PATH = "";
    });

    function buildEditServerDOM(teamId = null) {
        const form = flagDoc.createElement("form");
        form.id = "edit-server-form";

        // Visibility radios — public is disabled as Jinja would render it
        ["public", "team", "private"].forEach((val) => {
            const input = flagDoc.createElement("input");
            input.type = "radio";
            input.name = "visibility";
            input.value = val;
            input.id = `edit-visibility-${val}`;
            if (val === "public") input.disabled = true;
            form.appendChild(input);
        });

        flagDoc.body.appendChild(form);

        // Server modal (openModal looks for this)
        const modal = flagDoc.createElement("div");
        modal.id = "server-modal";
        modal.className = "hidden";
        flagDoc.body.appendChild(modal);

        // Set team_id in URL if provided
        const url = new flagWin.URL(flagWin.location.href);
        if (teamId) {
            url.searchParams.set("team_id", teamId);
        } else {
            url.searchParams.delete("team_id");
        }
        flagWin.history.replaceState({}, "", url.toString());
    }

    function mockServerFetch(serverData) {
        // fetchWithTimeout wraps fetch and adds signal/headers, so mock must
        // accept extra options gracefully and return a proper Response-like.
        const makeResponse = () => ({
            ok: true,
            status: 200,
            headers: {
                get: () => "application/json",
            },
            json: () => Promise.resolve(serverData),
            text: () => Promise.resolve(JSON.stringify(serverData)),
            clone: makeResponse,
        });
        flagWin.fetch = vi
            .fn()
            .mockImplementation(() => Promise.resolve(makeResponse()));
    }

    test("legacy public server coerces to team when teamId is set", async () => {
        buildEditServerDOM("team-abc");
        flagWin.console.error = vi.fn();
        mockServerFetch({
            id: "srv-1",
            name: "OldPublicServer",
            visibility: "public",
            teamId: "team-abc",
            url: "http://example.com",
            associatedTools: [],
            associatedResources: [],
            associatedPrompts: [],
        });

        try {
            await flagWin.editServer("srv-1");
        } catch {
            // editServer may throw on missing DOM elements (modal etc.)
        }

        const teamRadio = flagDoc.getElementById("edit-visibility-team");
        const publicRadio = flagDoc.getElementById("edit-visibility-public");
        expect(teamRadio.checked).toBe(true);
        expect(publicRadio.checked).toBe(false);
    });

    test("public server stays public when no teamId in URL (global scope)", async () => {
        buildEditServerDOM(null);
        mockServerFetch({
            id: "srv-2",
            name: "OldPublicServer",
            visibility: "public",
            teamId: null,
            url: "http://example.com",
            associatedTools: [],
            associatedResources: [],
            associatedPrompts: [],
        });

        await flagWin.editServer("srv-2");

        // No team_id in URL → no coercion, public radio remains selected.
        const privateRadio = flagDoc.getElementById("edit-visibility-private");
        const publicRadio = flagDoc.getElementById("edit-visibility-public");
        expect(publicRadio.checked).toBe(true);
        expect(privateRadio.checked).toBe(false);
    });

    test("team visibility still selects team radio when flag is false", async () => {
        buildEditServerDOM("team-abc");
        mockServerFetch({
            id: "srv-3",
            name: "TeamServer",
            visibility: "team",
            teamId: "team-abc",
            url: "http://example.com",
            associatedTools: [],
            associatedResources: [],
            associatedPrompts: [],
        });

        await flagWin.editServer("srv-3");

        const teamRadio = flagDoc.getElementById("edit-visibility-team");
        expect(teamRadio.checked).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// closeModal — failure-tolerant cleanup (#3259)
// ---------------------------------------------------------------------------
describe("closeModal — cleanup failure does not prevent modal hiding (#3259)", () => {
    test("modal hides even when resetEditSelections throws", () => {
        const modal = doc.createElement("div");
        modal.id = "server-edit-modal";
        doc.body.appendChild(modal);

        // Sabotage resetEditSelections so it throws
        const originalReset = win.resetEditSelections;
        win.resetEditSelections = () => {
            throw new Error("intentional cleanup failure");
        };

        // Should not throw and should still hide the modal
        expect(() => win.closeModal("server-edit-modal")).not.toThrow();
        expect(modal.classList.contains("hidden")).toBe(true);

        win.resetEditSelections = originalReset;
    });

    test("AppState.setModalInactive is called even when cleanup throws", () => {
        const modal = doc.createElement("div");
        modal.id = "server-edit-modal";
        doc.body.appendChild(modal);
        win.AppState.setModalActive("server-edit-modal");

        const originalReset = win.resetEditSelections;
        win.resetEditSelections = () => {
            throw new Error("intentional cleanup failure");
        };

        win.closeModal("server-edit-modal");
        expect(win.AppState.isModalActive("server-edit-modal")).toBe(false);

        win.resetEditSelections = originalReset;
    });
});

// ---------------------------------------------------------------------------
// serverSideEditToolSearch — add-only flush preserves prior selections (#3260)
// ---------------------------------------------------------------------------
describe("serverSideEditToolSearch — add-only flush (#3260)", () => {
    beforeEach(() => {
        win.initToolSelect = vi.fn();
        win.updateToolMapping = vi.fn();
    });

    test("unchecked search-result checkboxes do NOT delete prior selections from store", async () => {
        const container = makeContainer("edit-server-tools");

        // Pre-populate the in-memory store with a selection the user made earlier
        win.getEditSelections("edit-server-tools").add(
            "tool-previously-selected",
        );

        // Container currently shows two checkboxes — one checked, one not
        addCheckbox(container, {
            name: "associatedTools",
            value: "tool-checked",
            checked: true,
        });
        addCheckbox(container, {
            name: "associatedTools",
            value: "tool-previously-selected",
            checked: false,
        });

        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "application/json",
                body: { tools: [{ id: "tool-checked", name: "Checked Tool" }] },
            }),
        );

        await win.serverSideEditToolSearch("checked");

        const toolSel = win.getEditSelections("edit-server-tools");
        // The previously-selected tool should still be in the store
        expect(toolSel.has("tool-previously-selected")).toBe(true);
        // The currently checked tool should also be in the store
        expect(toolSel.has("tool-checked")).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// serverSideEditPromptsSearch — add-only flush preserves prior selections (#3260)
// ---------------------------------------------------------------------------
describe("serverSideEditPromptsSearch — add-only flush (#3260)", () => {
    beforeEach(() => {
        win.initPromptSelect = vi.fn();
        win.updatePromptMapping = vi.fn();
    });

    test("unchecked search-result checkboxes do NOT delete prior prompt selections", async () => {
        const container = makeContainer("edit-server-prompts");

        win.getEditSelections("edit-server-prompts").add("prompt-prior");

        addCheckbox(container, {
            name: "associatedPrompts",
            value: "prompt-checked",
            checked: true,
        });
        addCheckbox(container, {
            name: "associatedPrompts",
            value: "prompt-prior",
            checked: false,
        });

        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "application/json",
                body: {
                    prompts: [{ id: "prompt-checked", name: "Checked Prompt" }],
                },
            }),
        );

        await win.serverSideEditPromptsSearch("checked");

        const promptSel = win.getEditSelections("edit-server-prompts");
        expect(promptSel.has("prompt-prior")).toBe(true);
        expect(promptSel.has("prompt-checked")).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// serverSideEditResourcesSearch — add-only flush preserves prior selections (#3260)
// ---------------------------------------------------------------------------
describe("serverSideEditResourcesSearch — add-only flush (#3260)", () => {
    beforeEach(() => {
        win.initResourceSelect = vi.fn();
        win.updateResourceMapping = vi.fn();
    });

    test("unchecked search-result checkboxes do NOT delete prior resource selections", async () => {
        const container = makeContainer("edit-server-resources");

        win.getEditSelections("edit-server-resources").add("res-prior");

        addCheckbox(container, {
            name: "associatedResources",
            value: "res-checked",
            checked: true,
        });
        addCheckbox(container, {
            name: "associatedResources",
            value: "res-prior",
            checked: false,
        });

        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "application/json",
                body: {
                    resources: [
                        { id: "res-checked", name: "Checked Resource" },
                    ],
                },
            }),
        );

        await win.serverSideEditResourcesSearch("checked");

        const resSel = win.getEditSelections("edit-server-resources");
        expect(resSel.has("res-prior")).toBe(true);
        expect(resSel.has("res-checked")).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// initToolSelect Select All — populates in-memory store (#3257)
// ---------------------------------------------------------------------------
describe("initToolSelect Select All populates in-memory store (#3257)", () => {
    beforeEach(() => {
        // Restore the real initToolSelect in case earlier tests replaced it
        win.initToolSelect = realInitToolSelect;
    });

    test("Select All populates getEditSelections store for the container", async () => {
        // Build a wrapper so that the button can be cloneNode+replaceChild'd
        const wrapper = doc.createElement("div");
        doc.body.appendChild(wrapper);

        const container = doc.createElement("div");
        container.id = "edit-server-tools";
        wrapper.appendChild(container);

        // Add checkboxes (JSDOM has no layout so offsetParent is null —
        // the handler will take the paginated/fetch path)
        addCheckbox(container, {
            name: "associatedTools",
            value: "tool-a",
            checked: false,
        });
        addCheckbox(container, {
            name: "associatedTools",
            value: "tool-b",
            checked: false,
        });

        // Pill + warning containers
        const pills = doc.createElement("div");
        pills.id = "selectedEditToolsPills";
        wrapper.appendChild(pills);

        const warn = doc.createElement("div");
        warn.id = "selectedEditToolsWarning";
        wrapper.appendChild(warn);

        // Select All button (must have a parentNode for replaceChild)
        const selectBtn = doc.createElement("button");
        selectBtn.id = "selectAllEditToolsBtn";
        wrapper.appendChild(selectBtn);

        // Clear button (must have a parentNode for replaceChild)
        const clearBtn = doc.createElement("button");
        clearBtn.id = "clearAllEditToolsBtn";
        wrapper.appendChild(clearBtn);

        // Mock fetch to return tool IDs (paginated path)
        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "application/json",
                body: { tool_ids: ["tool-a", "tool-b", "tool-c"] },
            }),
        );

        win.initToolSelect(
            "edit-server-tools",
            "selectedEditToolsPills",
            "selectedEditToolsWarning",
            6,
            "selectAllEditToolsBtn",
            "clearAllEditToolsBtn",
        );

        // After initToolSelect the button is cloned+replaced — get the new one
        const newSelectBtn = doc.getElementById("selectAllEditToolsBtn");
        newSelectBtn.click();

        // Wait for the async click handler (fetch + DOM update) to settle
        for (let i = 0; i < 20; i++) {
            await new Promise((resolve) => setTimeout(resolve, 50));
            if (win.getEditSelections("edit-server-tools").size >= 3) break;
        }

        const editSel = win.getEditSelections("edit-server-tools");
        expect(editSel.has("tool-a")).toBe(true);
        expect(editSel.has("tool-b")).toBe(true);
        expect(editSel.has("tool-c")).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// ensureNoResultsElement — dynamic "no results" message (#3314)
// ---------------------------------------------------------------------------
describe("ensureNoResultsElement", () => {
    test("returns existing element when already in the DOM", () => {
        const container = makeContainer("myContainer");
        const msg = doc.createElement("p");
        msg.id = "noMyMessage";
        const span = doc.createElement("span");
        span.id = "myQuerySpan";
        msg.appendChild(span);
        container.parentNode.insertBefore(msg, container.nextSibling);

        const result = win.ensureNoResultsElement(
            "myContainer",
            "noMyMessage",
            "myQuerySpan",
            "item",
        );

        expect(result.msg).toBe(msg);
        expect(result.span).toBe(span);
    });

    test("falls back to querySelector when span id is missing", () => {
        const container = makeContainer("ctr2");
        const msg = doc.createElement("p");
        msg.id = "noMsg2";
        const span = doc.createElement("span");
        // No id on span — ensureNoResultsElement should find it via querySelector
        msg.appendChild(span);
        container.parentNode.insertBefore(msg, container.nextSibling);

        const result = win.ensureNoResultsElement(
            "ctr2",
            "noMsg2",
            "spanId2",
            "widget",
        );

        expect(result.msg).toBe(msg);
        expect(result.span).toBe(span);
    });

    test("creates element dynamically when missing from DOM", () => {
        const container = makeContainer("dynContainer");

        const result = win.ensureNoResultsElement(
            "dynContainer",
            "noDynMessage",
            "dynQuerySpan",
            "tool",
        );

        expect(result.msg).not.toBeNull();
        expect(result.msg.id).toBe("noDynMessage");
        expect(result.msg.style.display).toBe("none");
        expect(result.msg.className).toBe(
            "text-gray-700 dark:text-gray-300 mt-2",
        );
        expect(result.span).not.toBeNull();
        expect(result.span.id).toBe("dynQuerySpan");
        expect(result.msg.textContent).toContain("No tool found containing");
        // Verify it's inserted after the container
        expect(container.nextSibling).toBe(result.msg);
    });

    test("returns nulls when container does not exist", () => {
        const result = win.ensureNoResultsElement(
            "nonexistentContainer",
            "noMsg",
            "spanId",
            "item",
        );

        expect(result.msg).toBeNull();
        expect(result.span).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// serverSideToolSearch — container visibility on zero results (#3314)
// ---------------------------------------------------------------------------
describe("serverSideToolSearch — container visibility (#3314)", () => {
    beforeEach(() => {
        win.initToolSelect = vi.fn();
        win.updateToolMapping = vi.fn();
    });

    test("hides container and shows message when search returns zero results", async () => {
        const container = makeContainer("associatedTools");

        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "application/json",
                body: { tools: [] },
            }),
        );

        await win.serverSideToolSearch("zzzzz");

        expect(container.style.display).toBe("none");
        const noMsg = doc.getElementById("noToolsMessage");
        expect(noMsg).not.toBeNull();
        expect(noMsg.style.display).toBe("block");
        const span = doc.getElementById("searchQueryTools");
        expect(span.textContent).toBe("zzzzz");
    });

    test("shows container and hides message when search returns results", async () => {
        const container = makeContainer("associatedTools");

        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "application/json",
                body: { tools: [{ id: "t1", name: "Tool One" }] },
            }),
        );

        await win.serverSideToolSearch("tool");

        expect(container.style.display).toBe("");
        const noMsg = doc.getElementById("noToolsMessage");
        if (noMsg) {
            expect(noMsg.style.display).toBe("none");
        }
    });

    test("resets container visibility at start of search after previous no-results", async () => {
        const container = makeContainer("associatedTools");
        container.style.display = "none"; // simulate previous no-results state

        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "text/html",
                body: '<input type="checkbox" name="associatedTools" value="t1">',
            }),
        );

        await win.serverSideToolSearch("");

        expect(container.style.display).toBe("");
    });
});

// ---------------------------------------------------------------------------
// serverSidePromptSearch — container visibility on zero results (#3314)
// ---------------------------------------------------------------------------
describe("serverSidePromptSearch — container visibility (#3314)", () => {
    beforeEach(() => {
        win.initPromptSelect = vi.fn();
        win.updatePromptMapping = vi.fn();
    });

    test("hides container and shows message when search returns zero results", async () => {
        const container = makeContainer("associatedPrompts");

        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "application/json",
                body: { prompts: [] },
            }),
        );

        await win.serverSidePromptSearch("zzzzz");

        expect(container.style.display).toBe("none");
        const noMsg = doc.getElementById("noPromptsMessage");
        expect(noMsg).not.toBeNull();
        expect(noMsg.style.display).toBe("block");
    });

    test("resets container visibility on empty-string search", async () => {
        const container = makeContainer("associatedPrompts");
        container.style.display = "none";

        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "text/html",
                body: "",
            }),
        );

        await win.serverSidePromptSearch("");

        expect(container.style.display).toBe("");
    });
});

// ---------------------------------------------------------------------------
// serverSideResourceSearch — container visibility on zero results (#3314)
// ---------------------------------------------------------------------------
describe("serverSideResourceSearch — container visibility (#3314)", () => {
    beforeEach(() => {
        win.initResourceSelect = vi.fn();
        win.updateResourceMapping = vi.fn();
    });

    test("hides container and shows message when search returns zero results", async () => {
        const container = makeContainer("associatedResources");

        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "application/json",
                body: { resources: [] },
            }),
        );

        await win.serverSideResourceSearch("zzzzz");

        expect(container.style.display).toBe("none");
        const noMsg = doc.getElementById("noResourcesMessage");
        expect(noMsg).not.toBeNull();
        expect(noMsg.style.display).toBe("block");
    });

    test("resets container visibility on empty-string search", async () => {
        const container = makeContainer("associatedResources");
        container.style.display = "none";

        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "text/html",
                body: "",
            }),
        );

        await win.serverSideResourceSearch("");

        expect(container.style.display).toBe("");
    });
});

// ---------------------------------------------------------------------------
// serverSideEditToolSearch — container visibility on zero results (#3314)
// ---------------------------------------------------------------------------
describe("serverSideEditToolSearch — container visibility (#3314)", () => {
    beforeEach(() => {
        win.initToolSelect = vi.fn();
        win.updateToolMapping = vi.fn();
    });

    test("hides container and shows message when search returns zero results", async () => {
        const container = makeContainer("edit-server-tools");

        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "application/json",
                body: { tools: [] },
            }),
        );

        await win.serverSideEditToolSearch("zzzzz");

        expect(container.style.display).toBe("none");
        const noMsg = doc.getElementById("noEditToolsMessage");
        expect(noMsg).not.toBeNull();
        expect(noMsg.style.display).toBe("block");
    });

    test("resets container visibility on empty-string search", async () => {
        const container = makeContainer("edit-server-tools");
        container.style.display = "none";

        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "text/html",
                body: "",
            }),
        );

        await win.serverSideEditToolSearch("");

        expect(container.style.display).toBe("");
    });
});

// ---------------------------------------------------------------------------
// serverSideEditPromptsSearch — container visibility on zero results (#3314)
// ---------------------------------------------------------------------------
describe("serverSideEditPromptsSearch — container visibility (#3314)", () => {
    beforeEach(() => {
        win.initPromptSelect = vi.fn();
        win.updatePromptMapping = vi.fn();
    });

    test("hides container and shows message when search returns zero results", async () => {
        const container = makeContainer("edit-server-prompts");

        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "application/json",
                body: { prompts: [] },
            }),
        );

        await win.serverSideEditPromptsSearch("zzzzz");

        expect(container.style.display).toBe("none");
        const noMsg = doc.getElementById("noEditPromptsMessage");
        expect(noMsg).not.toBeNull();
        expect(noMsg.style.display).toBe("block");
    });

    test("resets container visibility on empty-string search", async () => {
        const container = makeContainer("edit-server-prompts");
        container.style.display = "none";

        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "text/html",
                body: "",
            }),
        );

        await win.serverSideEditPromptsSearch("");

        expect(container.style.display).toBe("");
    });
});

// ---------------------------------------------------------------------------
// serverSideEditResourcesSearch — container visibility on zero results (#3314)
// ---------------------------------------------------------------------------
describe("serverSideEditResourcesSearch — container visibility (#3314)", () => {
    beforeEach(() => {
        win.initResourceSelect = vi.fn();
        win.updateResourceMapping = vi.fn();
    });

    test("hides container and shows message when search returns zero results", async () => {
        const container = makeContainer("edit-server-resources");

        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "application/json",
                body: { resources: [] },
            }),
        );

        await win.serverSideEditResourcesSearch("zzzzz");

        expect(container.style.display).toBe("none");
        const noMsg = doc.getElementById("noEditResourcesMessage");
        expect(noMsg).not.toBeNull();
        expect(noMsg.style.display).toBe("block");
    });

    test("resets container visibility on empty-string search", async () => {
        const container = makeContainer("edit-server-resources");
        container.style.display = "none";

        win.fetch = vi.fn().mockResolvedValue(
            mockResponse({
                ok: true,
                contentType: "text/html",
                body: "",
            }),
        );

        await win.serverSideEditResourcesSearch("");

        expect(container.style.display).toBe("");
    });
});

// ---------------------------------------------------------------------------
// initGatewaySelect — applySearch container visibility (#3314)
// ---------------------------------------------------------------------------
describe("initGatewaySelect — applySearch visibility (#3314)", () => {
    function setupGatewaySelect(items = [], selectId = "associatedGateways") {
        const container = doc.createElement("div");
        container.id = selectId;
        doc.body.appendChild(container);

        items.forEach((text) => {
            const item = doc.createElement("div");
            item.className = "tool-item";
            item.textContent = text;
            const cb = doc.createElement("input");
            cb.type = "checkbox";
            cb.name = selectId;
            cb.value = text;
            item.appendChild(cb);
            container.appendChild(item);
        });

        const pills = doc.createElement("div");
        pills.id =
            selectId === "associatedEditGateways"
                ? "selectedEditGatewayPills"
                : "selectedGatewayPills";
        doc.body.appendChild(pills);

        const warn = doc.createElement("div");
        warn.id =
            selectId === "associatedEditGateways"
                ? "selectedEditGatewayWarning"
                : "selectedGatewayWarning";
        doc.body.appendChild(warn);

        const searchInput = doc.createElement("input");
        searchInput.id =
            selectId === "associatedEditGateways"
                ? "searchEditGateways"
                : "searchGateways";
        doc.body.appendChild(searchInput);

        return { container, searchInput };
    }

    test("hides container and shows message when search matches nothing", () => {
        const { container, searchInput } = setupGatewaySelect([
            "fast_time",
            "rest_a2a",
        ]);

        win.initGatewaySelect(
            "associatedGateways",
            "selectedGatewayPills",
            "selectedGatewayWarning",
            12,
            null,
            null,
            "searchGateways",
        );

        searchInput.value = "zzzzz";
        searchInput.dispatchEvent(new win.Event("input"));

        expect(container.style.display).toBe("none");
        const noMsg = doc.getElementById("noGatewayMessage");
        expect(noMsg).not.toBeNull();
        expect(noMsg.style.display).toBe("block");
    });

    test("shows container and hides message when search matches items", () => {
        const { container, searchInput } = setupGatewaySelect([
            "fast_time",
            "rest_a2a",
        ]);

        win.initGatewaySelect(
            "associatedGateways",
            "selectedGatewayPills",
            "selectedGatewayWarning",
            12,
            null,
            null,
            "searchGateways",
        );

        // First trigger no-results to create the message element
        searchInput.value = "zzzzz";
        searchInput.dispatchEvent(new win.Event("input"));
        expect(container.style.display).toBe("none");

        // Now search for something that matches
        searchInput.value = "fast";
        searchInput.dispatchEvent(new win.Event("input"));

        expect(container.style.display).toBe("");
        const noMsg = doc.getElementById("noGatewayMessage");
        if (noMsg) {
            expect(noMsg.style.display).toBe("none");
        }
    });

    test("uses Edit message IDs for edit container", () => {
        const { searchInput } = setupGatewaySelect(
            ["fast_time"],
            "associatedEditGateways",
        );

        win.initGatewaySelect(
            "associatedEditGateways",
            "selectedEditGatewayPills",
            "selectedEditGatewayWarning",
            12,
            null,
            null,
            "searchEditGateways",
        );

        searchInput.value = "zzzzz";
        searchInput.dispatchEvent(new win.Event("input"));

        const noMsg = doc.getElementById("noEditGatewayMessage");
        expect(noMsg).not.toBeNull();
        expect(noMsg.style.display).toBe("block");
        // Add-modal message should NOT be created
        expect(doc.getElementById("noGatewayMessage")).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// serverSideToolSearch — error catch keeps container visible (#3314)
// ---------------------------------------------------------------------------
describe("serverSideToolSearch — error catch visibility (#3314)", () => {
    beforeEach(() => {
        win.initToolSelect = vi.fn();
        win.updateToolMapping = vi.fn();
    });

    test("container stays visible and message hidden on fetch error", async () => {
        const container = makeContainer("associatedTools");
        container.style.display = "none"; // simulate previous no-results state

        win.fetch = vi.fn().mockRejectedValue(new Error("Network failure"));

        await win.serverSideToolSearch("test");

        // Container should be visible (reset at top of function)
        expect(container.style.display).toBe("");
        // Message should be hidden in catch block
        const noMsg = doc.getElementById("noToolsMessage");
        if (noMsg) {
            expect(noMsg.style.display).toBe("none");
        }
    });
});

// ---------------------------------------------------------------------------
// serverSideEditToolSearch — error catch keeps container visible (#3314)
// ---------------------------------------------------------------------------
describe("serverSideEditToolSearch — error catch visibility (#3314)", () => {
    beforeEach(() => {
        win.initToolSelect = vi.fn();
        win.updateToolMapping = vi.fn();
    });

    test("container stays visible and message hidden on fetch error", async () => {
        const container = makeContainer("edit-server-tools");
        container.style.display = "none";

        win.fetch = vi.fn().mockRejectedValue(new Error("Network failure"));

        await win.serverSideEditToolSearch("test");

        expect(container.style.display).toBe("");
        const noMsg = doc.getElementById("noEditToolsMessage");
        if (noMsg) {
            expect(noMsg.style.display).toBe("none");
        }
    });
});
