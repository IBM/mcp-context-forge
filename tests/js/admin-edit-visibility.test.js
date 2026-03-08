/**
 * Tests that all edit form submit handlers preserve the visibility field
 * in the submitted FormData without creating duplicate entries.
 *
 * Covers: handleEditToolFormSubmit, handleEditPromptFormSubmit,
 *         handleEditGatewayFormSubmit, handleEditServerFormSubmit,
 *         handleEditResFormSubmit, handleEditA2AAgentFormSubmit
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
    win.ROOT_PATH = "";
    win.getCurrentTeamId = () => null;
    win.getSelectedGatewayIds = () => [];
    // Reset shared selection state
    win.editServerSelections = {};
    win._editStoreListenersAttached = false;
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockResponse({
    ok = true,
    status = 200,
    body = "",
    contentType = "application/json",
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

function fakeSubmitEvent(form) {
    return { target: form, preventDefault: vi.fn() };
}

/**
 * Create a minimal form with a name input, url input and visibility radio
 * buttons. The radio matching `selectedVisibility` is checked.
 */
function buildForm({ id, action, selectedVisibility = "team", fields = {} }) {
    const form = doc.createElement("form");
    form.id = id;
    form.action = action;

    const nameInput = doc.createElement("input");
    nameInput.type = "text";
    nameInput.name = "name";
    nameInput.value = fields.name || "test-entity";
    form.appendChild(nameInput);

    if (fields.url !== undefined || !fields.skipUrl) {
        const urlInput = doc.createElement("input");
        urlInput.type = "text";
        urlInput.name = fields.urlFieldName || "url";
        urlInput.value = fields.url || "https://example.com";
        form.appendChild(urlInput);
    }

    // Add visibility radio buttons (mimics admin.html structure)
    for (const vis of ["public", "team", "private"]) {
        const radio = doc.createElement("input");
        radio.type = "radio";
        radio.name = "visibility";
        radio.value = vis;
        radio.id = `${id.replace("-form", "")}-visibility-${vis}`;
        radio.checked = vis === selectedVisibility;
        form.appendChild(radio);
    }

    doc.body.appendChild(form);
    return form;
}

function setupCommonStubs() {
    win.validateInputName = () => ({ valid: true });
    win.validateUrl = () => ({ valid: true });
    win.isInactiveChecked = () => false;
    win.safeParseJsonResponse = async () => ({ success: true });
    win.showSuccessMessage = vi.fn();
    win.showErrorMessage = vi.fn();
    win._navigateAdmin = vi.fn();
    win.reloadAllResourceSections = vi.fn();
    win.safeGetElement = (id) => doc.getElementById(id);
}

function mockFetchCapture() {
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
    return () => capturedBody;
}

/**
 * Assert that submitted FormData contains exactly one visibility entry
 * with the expected value — no duplicates.
 */
function expectSingleVisibility(formData, expected) {
    const all = formData.getAll("visibility");
    expect(all).toEqual([expected]);
}

// ---------------------------------------------------------------------------
// handleEditToolFormSubmit
// ---------------------------------------------------------------------------
describe("handleEditToolFormSubmit — visibility preservation", () => {
    beforeEach(setupCommonStubs);

    test("submits exactly one visibility entry with the selected value", async () => {
        const form = buildForm({
            id: "edit-tool-form",
            action: "/admin/tools/1",
            selectedVisibility: "team",
        });

        const getCaptured = mockFetchCapture();
        await win.handleEditToolFormSubmit(fakeSubmitEvent(form));

        expectSingleVisibility(getCaptured(), "team");
    });

    test("visibility=public is preserved when selected", async () => {
        const form = buildForm({
            id: "edit-tool-form",
            action: "/admin/tools/2",
            selectedVisibility: "public",
        });

        const getCaptured = mockFetchCapture();
        await win.handleEditToolFormSubmit(fakeSubmitEvent(form));

        expectSingleVisibility(getCaptured(), "public");
    });
});

// ---------------------------------------------------------------------------
// handleEditPromptFormSubmit
// ---------------------------------------------------------------------------
describe("handleEditPromptFormSubmit — visibility preservation", () => {
    beforeEach(setupCommonStubs);

    test("submits exactly one visibility entry with the selected value", async () => {
        const form = buildForm({
            id: "edit-prompt-form",
            action: "/admin/prompts/1",
            selectedVisibility: "private",
        });

        const getCaptured = mockFetchCapture();
        await win.handleEditPromptFormSubmit(fakeSubmitEvent(form));

        expectSingleVisibility(getCaptured(), "private");
    });
});

// ---------------------------------------------------------------------------
// handleEditGatewayFormSubmit
// ---------------------------------------------------------------------------
describe("handleEditGatewayFormSubmit — visibility preservation", () => {
    beforeEach(setupCommonStubs);

    test("submits exactly one visibility entry with the selected value", async () => {
        const form = buildForm({
            id: "edit-gateway-form",
            action: "/admin/gateways/1",
            selectedVisibility: "team",
        });

        // Gateway handler reads passthrough_headers
        const phInput = doc.createElement("input");
        phInput.type = "hidden";
        phInput.name = "passthrough_headers";
        phInput.value = "";
        form.appendChild(phInput);

        const getCaptured = mockFetchCapture();
        await win.handleEditGatewayFormSubmit(fakeSubmitEvent(form));

        expectSingleVisibility(getCaptured(), "team");
    });
});

// ---------------------------------------------------------------------------
// handleEditServerFormSubmit
// ---------------------------------------------------------------------------
describe("handleEditServerFormSubmit — visibility preservation", () => {
    beforeEach(() => {
        setupCommonStubs();
        win.editServerSelections = {};
        win._editStoreListenersAttached = false;
    });

    function makeContainer(id) {
        const div = doc.createElement("div");
        div.id = id;
        doc.body.appendChild(div);
        return div;
    }

    test("submits exactly one visibility entry with the selected value", async () => {
        const form = buildForm({
            id: "edit-server-form",
            action: "/admin/servers/1",
            selectedVisibility: "public",
        });

        // Server handler needs association containers
        makeContainer("edit-server-tools");
        makeContainer("edit-server-resources");
        makeContainer("edit-server-prompts");

        const getCaptured = mockFetchCapture();
        await win.handleEditServerFormSubmit(fakeSubmitEvent(form));

        expectSingleVisibility(getCaptured(), "public");
    });
});

// ---------------------------------------------------------------------------
// handleEditResFormSubmit
// ---------------------------------------------------------------------------
describe("handleEditResFormSubmit — visibility preservation", () => {
    beforeEach(setupCommonStubs);

    test("submits exactly one visibility entry with the selected value", async () => {
        const form = buildForm({
            id: "edit-resource-form",
            action: "/admin/resources/1",
            selectedVisibility: "team",
            fields: { urlFieldName: "uri", url: "https://example.com/res" },
        });

        const getCaptured = mockFetchCapture();
        await win.handleEditResFormSubmit(fakeSubmitEvent(form));

        expectSingleVisibility(getCaptured(), "team");
    });
});

// ---------------------------------------------------------------------------
// handleEditA2AAgentFormSubmit
// ---------------------------------------------------------------------------
describe("handleEditA2AAgentFormSubmit — visibility preservation", () => {
    beforeEach(setupCommonStubs);

    test("submits exactly one visibility entry with the selected value", async () => {
        const form = buildForm({
            id: "edit-a2a-form",
            action: "/admin/a2a-agents/1",
            selectedVisibility: "team",
            fields: {
                urlFieldName: "endpoint_url",
                url: "https://example.com/a2a",
            },
        });

        // A2A handler reads passthrough_headers and auth_type
        const phInput = doc.createElement("input");
        phInput.type = "hidden";
        phInput.name = "passthrough_headers";
        phInput.value = "";
        form.appendChild(phInput);

        const authInput = doc.createElement("input");
        authInput.type = "hidden";
        authInput.name = "auth_type";
        authInput.value = "none";
        form.appendChild(authInput);

        const getCaptured = mockFetchCapture();
        await win.handleEditA2AAgentFormSubmit(fakeSubmitEvent(form));

        expectSingleVisibility(getCaptured(), "team");
    });
});
