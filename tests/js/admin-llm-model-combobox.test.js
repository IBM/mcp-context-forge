/**
 * Unit tests for the LLM model-id combobox (PR #3806).
 *
 * Covers:
 *   - llmModelComboboxOpen: renders models and shows dropdown
 *   - llmModelComboboxClose: hides dropdown, null-safe, ARIA expanded
 *   - llmModelComboboxFilter: type-ahead filtering
 *   - llmModelComboboxSelect: sets input value and closes dropdown
 *   - llmModelComboboxKeydown: ArrowDown/ArrowUp/Enter/Escape keyboard nav
 *   - _renderLLMModelDropdown: DOM rendering, empty-state, XSS safety, ARIA roles
 *   - DOMContentLoaded delegation: mousedown preventDefault, click-to-select
 *   - fetchModelsForModelModal: populates combobox, stale-response guard
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
 * Returns the DOM elements for further assertions.
 */
async function populateModelsViaFetch(models) {
    const dom = setupFullModalDOM();
    win.ROOT_PATH = "";
    win.getAuthToken = async () => "fake-token";
    win.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, models }),
    });
    await win.fetchModelsForModelModal();
    return dom;
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

    test("sets role=option on each model <li>", () => {
        const { ul } = setupComboboxDOM();
        win._renderLLMModelDropdown([{ id: "m1" }, { id: "m2" }]);
        ul.querySelectorAll("li[data-model-id]").forEach((li) => {
            expect(li.getAttribute("role")).toBe("option");
        });
    });

    test("escapes HTML-significant characters in model IDs (XSS safety)", () => {
        const { ul } = setupComboboxDOM();
        const malicious = "<img onerror=alert(1) src=x>";
        win._renderLLMModelDropdown([{ id: malicious }]);
        expect(ul.children[0].textContent).toBe(malicious);
        expect(ul.querySelector("img")).toBeNull();
    });

    test("is a no-op when the dropdown element does not exist", () => {
        expect(() => win._renderLLMModelDropdown([{ id: "x" }])).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// llmModelComboboxOpen
// ---------------------------------------------------------------------------

describe("llmModelComboboxOpen", () => {
    test("does not open dropdown before any fetch has occurred", () => {
        const { ul } = setupComboboxDOM();
        win.llmModelComboboxOpen();
        expect(ul.classList.contains("hidden")).toBe(true);
    });

    test("opens dropdown after models have been fetched", async () => {
        await populateModelsViaFetch([{ id: "a" }, { id: "b" }]);
        const ul = doc.getElementById("llm-model-dropdown");
        ul.classList.add("hidden");
        win.llmModelComboboxOpen();
        expect(ul.classList.contains("hidden")).toBe(false);
        expect(ul.querySelectorAll("li[data-model-id]").length).toBe(2);
    });

    test("sets aria-expanded=true on the input", async () => {
        await populateModelsViaFetch([{ id: "m1" }]);
        const input = doc.getElementById("llm-model-model-id");
        win.llmModelComboboxOpen();
        expect(input.getAttribute("aria-expanded")).toBe("true");
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

    test("sets aria-expanded=false on the input", () => {
        const { input } = setupComboboxDOM();
        input.setAttribute("aria-expanded", "true");
        win.llmModelComboboxClose();
        expect(input.getAttribute("aria-expanded")).toBe("false");
    });

    test("is a no-op when the dropdown element does not exist", () => {
        expect(() => win.llmModelComboboxClose()).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// llmModelComboboxFilter
// ---------------------------------------------------------------------------

describe("llmModelComboboxFilter", () => {
    test("does not open dropdown before any fetch has occurred", () => {
        // Reset _llmModelsFetched via onModelProviderChange with empty provider
        const dom = setupFullModalDOM();
        dom.provider.value = "";
        win.onModelProviderChange();
        win.llmModelComboboxFilter("gpt");
        expect(dom.ul.classList.contains("hidden")).toBe(true);
    });

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
// llmModelComboboxKeydown — keyboard navigation
// ---------------------------------------------------------------------------

describe("llmModelComboboxKeydown", () => {
    async function setupKeyboardTest() {
        const dom = await populateModelsViaFetch([
            { id: "alpha" },
            { id: "bravo" },
            { id: "charlie" },
        ]);
        win.llmModelComboboxOpen();
        return dom;
    }

    function fireKey(key) {
        const event = doc.createEvent("Event");
        event.initEvent("keydown", true, true);
        event.key = key;
        event.preventDefault = vi.fn();
        event.stopPropagation = vi.fn();
        win.llmModelComboboxKeydown(event);
        return event;
    }

    test("ArrowDown moves highlight to the first item", async () => {
        await setupKeyboardTest();
        fireKey("ArrowDown");
        const ul = doc.getElementById("llm-model-dropdown");
        const active = ul.querySelector("#llm-model-active-option");
        expect(active).not.toBeNull();
        expect(active.dataset.modelId).toBe("alpha");
    });

    test("ArrowDown then ArrowDown moves to second item", async () => {
        await setupKeyboardTest();
        fireKey("ArrowDown");
        fireKey("ArrowDown");
        const ul = doc.getElementById("llm-model-dropdown");
        const active = ul.querySelector("#llm-model-active-option");
        expect(active.dataset.modelId).toBe("bravo");
    });

    test("ArrowDown clamps at the last item", async () => {
        await setupKeyboardTest();
        fireKey("ArrowDown");
        fireKey("ArrowDown");
        fireKey("ArrowDown");
        fireKey("ArrowDown"); // beyond last
        const ul = doc.getElementById("llm-model-dropdown");
        const active = ul.querySelector("#llm-model-active-option");
        expect(active.dataset.modelId).toBe("charlie");
    });

    test("ArrowUp moves highlight upward", async () => {
        await setupKeyboardTest();
        fireKey("ArrowDown");
        fireKey("ArrowDown");
        fireKey("ArrowUp");
        const ul = doc.getElementById("llm-model-dropdown");
        const active = ul.querySelector("#llm-model-active-option");
        expect(active.dataset.modelId).toBe("alpha");
    });

    test("ArrowUp clamps at the first item", async () => {
        await setupKeyboardTest();
        fireKey("ArrowDown");
        fireKey("ArrowUp");
        fireKey("ArrowUp"); // beyond first
        const ul = doc.getElementById("llm-model-dropdown");
        const active = ul.querySelector("#llm-model-active-option");
        expect(active.dataset.modelId).toBe("alpha");
    });

    test("Enter selects the highlighted item", async () => {
        const { input } = await setupKeyboardTest();
        fireKey("ArrowDown");
        fireKey("ArrowDown");
        const event = fireKey("Enter");
        expect(input.value).toBe("bravo");
        expect(event.preventDefault).toHaveBeenCalled();
    });

    test("Enter does nothing with no highlight", async () => {
        const { input } = await setupKeyboardTest();
        input.value = "";
        fireKey("Enter"); // no ArrowDown first
        expect(input.value).toBe("");
    });

    test("Escape closes the dropdown and stops propagation", async () => {
        await setupKeyboardTest();
        const ul = doc.getElementById("llm-model-dropdown");
        expect(ul.classList.contains("hidden")).toBe(false);
        const event = fireKey("Escape");
        expect(ul.classList.contains("hidden")).toBe(true);
        expect(event.stopPropagation).toHaveBeenCalled();
    });

    test("sets aria-activedescendant on highlight", async () => {
        await setupKeyboardTest();
        const input = doc.getElementById("llm-model-model-id");
        fireKey("ArrowDown");
        expect(input.getAttribute("aria-activedescendant")).toBe(
            "llm-model-active-option",
        );
    });

    test("clears aria-activedescendant on close", async () => {
        await setupKeyboardTest();
        const input = doc.getElementById("llm-model-model-id");
        fireKey("ArrowDown");
        win.llmModelComboboxClose();
        expect(input.hasAttribute("aria-activedescendant")).toBe(false);
    });

    test("is a no-op when dropdown is hidden", () => {
        setupComboboxDOM();
        // dropdown starts hidden — should not throw
        expect(() => fireKey("ArrowDown")).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// fetchModelsForModelModal — combobox integration
// ---------------------------------------------------------------------------

describe("fetchModelsForModelModal", () => {
    test("populates dropdown with models from API response", async () => {
        await populateModelsViaFetch([
            { id: "gpt-4o" },
            { id: "claude-3-opus" },
        ]);
        const ul = doc.getElementById("llm-model-dropdown");
        expect(ul.querySelectorAll("li[data-model-id]").length).toBe(2);
    });

    test("clears models on empty API response", async () => {
        await populateModelsViaFetch([{ id: "m1" }]);
        win.fetch = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({ success: true, models: [] }),
        });
        await win.fetchModelsForModelModal();
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

    test("discards response if provider changed during fetch", async () => {
        const { provider } = await populateModelsViaFetch([{ id: "old" }]);
        // Set up a fetch that resolves, but we change the provider before it does
        let resolveResponse;
        win.fetch = vi.fn().mockReturnValue(
            new win.Promise((resolve) => {
                resolveResponse = resolve;
            }),
        );
        const fetchPromise = win.fetchModelsForModelModal();
        // Simulate user switching provider while fetch is in-flight
        const opt2 = doc.createElement("option");
        opt2.value = "prov-2";
        provider.appendChild(opt2);
        provider.value = "prov-2";
        // Now resolve the original prov-1 response
        resolveResponse({
            ok: true,
            json: async () => ({
                success: true,
                models: [{ id: "stale-model" }],
            }),
        });
        await fetchPromise;
        // The stale response should be discarded; old models should remain
        win.llmModelComboboxOpen();
        const ul = doc.getElementById("llm-model-dropdown");
        const items = ul.querySelectorAll("li[data-model-id]");
        // Should still show "old" from the first fetch, not "stale-model"
        expect(items.length).toBe(1);
        expect(items[0].dataset.modelId).toBe("old");
    });

    test("discards earlier response when same provider is fetched twice", async () => {
        await populateModelsViaFetch([{ id: "initial" }]);
        // Set up two pending fetches to the same provider
        const resolvers = [];
        win.fetch = vi.fn().mockImplementation(
            () =>
                new win.Promise((r) => {
                    resolvers.push(r);
                }),
        );
        // Fire first request (e.g., auto-fetch on provider change)
        const fetch1 = win.fetchModelsForModelModal();
        // Yield so the first fetch() call registers before we start the second
        await new Promise((resolve) => setTimeout(resolve, 0));
        // Fire second request (e.g., user clicks refresh) before first resolves
        const fetch2 = win.fetchModelsForModelModal();
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(resolvers.length).toBe(2);
        // Resolve the SECOND (newer) request first
        resolvers[1]({
            ok: true,
            json: async () => ({
                success: true,
                models: [{ id: "newer" }],
            }),
        });
        await fetch2;
        // Now resolve the FIRST (older, stale) request
        resolvers[0]({
            ok: true,
            json: async () => ({
                success: true,
                models: [{ id: "older-stale" }],
            }),
        });
        await fetch1;
        // Only the newer response should be applied
        win.llmModelComboboxOpen();
        const ul = doc.getElementById("llm-model-dropdown");
        const items = ul.querySelectorAll("li[data-model-id]");
        expect(items.length).toBe(1);
        expect(items[0].dataset.modelId).toBe("newer");
    });
});

// ---------------------------------------------------------------------------
// DOMContentLoaded delegation
// ---------------------------------------------------------------------------

describe("DOMContentLoaded dropdown delegation", () => {
    test("mousedown on dropdown prevents default (keeps focus on input)", () => {
        const { ul } = setupComboboxDOM();

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

        const domReady = doc.createEvent("Event");
        domReady.initEvent("DOMContentLoaded", true, true);
        doc.dispatchEvent(domReady);

        const li = ul.querySelector("li[data-model-id]");
        const click = doc.createEvent("MouseEvent");
        click.initEvent("click", true, true);
        li.dispatchEvent(click);

        expect(input.value).toBe("test-model");
        expect(ul.classList.contains("hidden")).toBe(true);
    });
});
