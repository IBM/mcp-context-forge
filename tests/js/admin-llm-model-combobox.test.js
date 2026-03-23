/**
 * Unit tests for the LLM model-id combobox (PR #3806).
 *
 * Covers:
 *   - llmModelComboboxOpen: renders models and shows dropdown
 *   - llmModelComboboxClose: hides dropdown, null-safe
 *   - llmModelComboboxFilter: type-ahead filtering
 *   - llmModelComboboxSelect: sets input value and closes dropdown
 *   - _renderLLMModelDropdown: DOM rendering, empty-state, XSS safety
 *   - DOMContentLoaded delegation: mousedown preventDefault, click-to-select
 *   - fetchModelsForModelModal: populates combobox from API response
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
            window.getPaginationParams = function () {
                return { page: 1, perPage: 10, includeInactive: null };
            };
            window.buildTableUrl = function (_tableName, baseUrl) {
                return baseUrl;
            };
            window.safeReplaceState = function () {};
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

/** Create the minimal DOM elements the combobox functions expect. */
function setupComboboxDOM() {
    const input = doc.createElement("input");
    input.id = "llm-model-model-id";
    input.type = "text";
    doc.body.appendChild(input);

    const ul = doc.createElement("ul");
    ul.id = "llm-model-dropdown";
    ul.classList.add("hidden");
    doc.body.appendChild(ul);

    return { input, ul };
}

/** Create the full modal DOM needed by fetchModelsForModelModal. */
function setupFullModalDOM() {
    const { input, ul } = setupComboboxDOM();

    const provider = doc.createElement("select");
    provider.id = "llm-model-provider";
    const opt = doc.createElement("option");
    opt.value = "prov-1";
    opt.textContent = "Test Provider";
    provider.appendChild(opt);
    provider.value = "prov-1";
    doc.body.appendChild(provider);

    const status = doc.createElement("p");
    status.id = "llm-model-fetch-status";
    status.classList.add("hidden");
    doc.body.appendChild(status);

    return { input, ul, provider, status };
}

/**
 * Populate the closure-scoped _llmAllModels via fetchModelsForModelModal.
 * Returns the models that were loaded.
 */
async function populateModelsViaFetch(models) {
    setupFullModalDOM();
    win.ROOT_PATH = "";
    win.getAuthToken = async () => "fake-token";
    win.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, models }),
    });
    await win.fetchModelsForModelModal();
    return models;
}

// ---------------------------------------------------------------------------
// _renderLLMModelDropdown
// ---------------------------------------------------------------------------

describe("_renderLLMModelDropdown", () => {
    test("renders empty-state message when models list is empty", () => {
        const { ul } = setupComboboxDOM();
        win._renderLLMModelDropdown([]);
        expect(ul.children.length).toBe(1);
        expect(ul.children[0].textContent).toContain("No models found");
    });

    test("renders one <li> per model with correct data-model-id", () => {
        const { ul } = setupComboboxDOM();
        const models = [{ id: "gpt-4o" }, { id: "claude-3" }];
        win._renderLLMModelDropdown(models);
        expect(ul.children.length).toBe(2);
        expect(ul.children[0].dataset.modelId).toBe("gpt-4o");
        expect(ul.children[0].textContent).toBe("gpt-4o");
        expect(ul.children[1].dataset.modelId).toBe("claude-3");
    });

    test("escapes HTML-significant characters in model IDs (XSS safety)", () => {
        const { ul } = setupComboboxDOM();
        const malicious = "<img onerror=alert(1) src=x>";
        win._renderLLMModelDropdown([{ id: malicious }]);
        // textContent is used, so the string should appear literally, not as HTML
        expect(ul.children[0].textContent).toBe(malicious);
        // No <img> element should exist
        expect(ul.querySelector("img")).toBeNull();
    });

    test("is a no-op when the dropdown element does not exist", () => {
        // No DOM setup — should not throw
        expect(() => win._renderLLMModelDropdown([{ id: "x" }])).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// llmModelComboboxOpen
// ---------------------------------------------------------------------------

describe("llmModelComboboxOpen", () => {
    test("removes 'hidden' class from dropdown", () => {
        setupComboboxDOM();
        // Even with empty models, open should show the dropdown
        win.llmModelComboboxOpen();
        const ul = doc.getElementById("llm-model-dropdown");
        expect(ul.classList.contains("hidden")).toBe(false);
    });

    test("renders fetched models into dropdown on open", async () => {
        await populateModelsViaFetch([{ id: "a" }, { id: "b" }]);
        const ul = doc.getElementById("llm-model-dropdown");
        // fetchModelsForModelModal already renders, but open should re-render
        win.llmModelComboboxOpen();
        expect(ul.querySelectorAll("li[data-model-id]").length).toBe(2);
    });
});

// ---------------------------------------------------------------------------
// llmModelComboboxClose
// ---------------------------------------------------------------------------

describe("llmModelComboboxClose", () => {
    test("adds 'hidden' class to dropdown", () => {
        const { ul } = setupComboboxDOM();
        ul.classList.remove("hidden");
        win.llmModelComboboxClose();
        expect(ul.classList.contains("hidden")).toBe(true);
    });

    test("is a no-op when the dropdown element does not exist", () => {
        // No DOM setup — should not throw
        expect(() => win.llmModelComboboxClose()).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// llmModelComboboxFilter
// ---------------------------------------------------------------------------

describe("llmModelComboboxFilter", () => {
    test("filters models by case-insensitive substring match", async () => {
        await populateModelsViaFetch([
            { id: "gpt-4o" },
            { id: "gpt-3.5-turbo" },
            { id: "claude-3-opus" },
        ]);
        const ul = doc.getElementById("llm-model-dropdown");
        win.llmModelComboboxFilter("gpt");
        const items = ul.querySelectorAll("li[data-model-id]");
        expect(items.length).toBe(2);
        expect(items[0].dataset.modelId).toBe("gpt-4o");
        expect(items[1].dataset.modelId).toBe("gpt-3.5-turbo");
    });

    test("shows all models when filter text is empty", async () => {
        await populateModelsViaFetch([{ id: "a" }, { id: "b" }]);
        const ul = doc.getElementById("llm-model-dropdown");
        win.llmModelComboboxFilter("");
        expect(ul.querySelectorAll("li[data-model-id]").length).toBe(2);
    });

    test("shows empty-state when no models match", async () => {
        await populateModelsViaFetch([{ id: "gpt-4o" }]);
        const ul = doc.getElementById("llm-model-dropdown");
        win.llmModelComboboxFilter("zzz-no-match");
        expect(ul.querySelectorAll("li[data-model-id]").length).toBe(0);
        expect(ul.textContent).toContain("No models found");
    });

    test("ensures dropdown is visible after filtering", async () => {
        await populateModelsViaFetch([{ id: "m1" }]);
        const ul = doc.getElementById("llm-model-dropdown");
        ul.classList.add("hidden");
        win.llmModelComboboxFilter("m1");
        expect(ul.classList.contains("hidden")).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// llmModelComboboxSelect
// ---------------------------------------------------------------------------

describe("llmModelComboboxSelect", () => {
    test("sets input value and closes dropdown", () => {
        const { input, ul } = setupComboboxDOM();
        ul.classList.remove("hidden");
        win.llmModelComboboxSelect("gpt-4o-mini");
        expect(input.value).toBe("gpt-4o-mini");
        expect(ul.classList.contains("hidden")).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// fetchModelsForModelModal — combobox integration
// ---------------------------------------------------------------------------

describe("fetchModelsForModelModal", () => {
    test("populates dropdown with models from API response", async () => {
        const models = [{ id: "gpt-4o" }, { id: "claude-3-opus" }];
        await populateModelsViaFetch(models);
        const ul = doc.getElementById("llm-model-dropdown");
        expect(ul.querySelectorAll("li[data-model-id]").length).toBe(2);
    });

    test("clears models on empty API response", async () => {
        // First populate
        await populateModelsViaFetch([{ id: "m1" }]);
        // Then fetch returns empty
        win.fetch = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({ success: true, models: [] }),
        });
        await win.fetchModelsForModelModal();
        // open should show empty state
        win.llmModelComboboxOpen();
        const ul = doc.getElementById("llm-model-dropdown");
        expect(ul.querySelectorAll("li[data-model-id]").length).toBe(0);
    });

    test("clears models on fetch error", async () => {
        await populateModelsViaFetch([{ id: "m1" }]);
        win.fetch = vi.fn().mockRejectedValue(new win.Error("network error"));
        await win.fetchModelsForModelModal();
        win.llmModelComboboxOpen();
        const ul = doc.getElementById("llm-model-dropdown");
        expect(ul.querySelectorAll("li[data-model-id]").length).toBe(0);
    });
});

// ---------------------------------------------------------------------------
// DOMContentLoaded delegation
// ---------------------------------------------------------------------------

describe("DOMContentLoaded dropdown delegation", () => {
    test("mousedown on dropdown prevents default (keeps focus on input)", () => {
        const { ul } = setupComboboxDOM();

        // Fire the DOMContentLoaded handler so delegation is wired
        const event = doc.createEvent("Event");
        event.initEvent("DOMContentLoaded", true, true);
        doc.dispatchEvent(event);

        const mousedown = doc.createEvent("MouseEvent");
        mousedown.initEvent("mousedown", true, true);
        const spy = vi.spyOn(mousedown, "preventDefault");
        ul.dispatchEvent(mousedown);
        expect(spy).toHaveBeenCalled();
    });

    test("click on <li> with data-model-id selects the model", () => {
        const { input, ul } = setupComboboxDOM();
        win._renderLLMModelDropdown([{ id: "test-model" }]);

        // Fire DOMContentLoaded to wire delegation
        const domReady = doc.createEvent("Event");
        domReady.initEvent("DOMContentLoaded", true, true);
        doc.dispatchEvent(domReady);

        // Click the first <li>
        const li = ul.querySelector("li[data-model-id]");
        const click = doc.createEvent("MouseEvent");
        click.initEvent("click", true, true);
        li.dispatchEvent(click);

        expect(input.value).toBe("test-model");
        expect(ul.classList.contains("hidden")).toBe(true);
    });
});
