/**
 * Unit tests for unified admin search (panel search + global search).
 */

import { describe, test, expect, beforeAll, beforeEach, afterAll, vi } from "vitest";
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
});

// ---------------------------------------------------------------------------
// clearSearch (window-exposed)
// ---------------------------------------------------------------------------
describe("clearSearch", () => {
    const f = () => win.clearSearch;

    test("clears search and tag inputs for panel entity", () => {
        const searchInput = doc.createElement("input");
        searchInput.id = "tools-search-input";
        searchInput.value = "some query";
        doc.body.appendChild(searchInput);

        const tagInput = doc.createElement("input");
        tagInput.id = "tools-tag-filter";
        tagInput.value = "prod,staging";
        doc.body.appendChild(tagInput);

        const table = doc.createElement("div");
        table.id = "tools-table";
        doc.body.appendChild(table);

        f()("tools");

        expect(searchInput.value).toBe("");
        expect(tagInput.value).toBe("");
    });

    test("does not throw for unknown entity type", () => {
        expect(() => f()("nonexistent")).not.toThrow();
    });

    test("handles tokens entity (not in panel search config)", () => {
        const searchInput = doc.createElement("input");
        searchInput.id = "tokens-search-input";
        searchInput.value = "my-token";
        doc.body.appendChild(searchInput);

        win.performTokenSearch = vi.fn();

        f()("tokens");

        expect(searchInput.value).toBe("");
        expect(win.performTokenSearch).toHaveBeenCalledWith("");
    });

    test("does not call legacy filter functions for panel entities", () => {
        // Tools is in PANEL_SEARCH_CONFIG, so filterToolsTable should NOT be called
        const original = win.filterToolsTable;
        win.filterToolsTable = vi.fn();

        const searchInput = doc.createElement("input");
        searchInput.id = "tools-search-input";
        doc.body.appendChild(searchInput);

        const table = doc.createElement("div");
        table.id = "tools-table";
        doc.body.appendChild(table);

        f()("tools");

        expect(win.filterToolsTable).not.toHaveBeenCalled();
        win.filterToolsTable = original;
    });
});

// ---------------------------------------------------------------------------
// Global search modal (window-exposed functions)
// ---------------------------------------------------------------------------
describe("Global search modal", () => {
    function setupSearchModal() {
        const modal = doc.createElement("div");
        modal.id = "global-search-modal";
        modal.classList.add("hidden");
        modal.setAttribute("aria-hidden", "true");
        doc.body.appendChild(modal);

        const input = doc.createElement("input");
        input.id = "global-search-input";
        input.type = "text";
        modal.appendChild(input);

        const results = doc.createElement("div");
        results.id = "global-search-results";
        modal.appendChild(results);

        return { modal, input, results };
    }

    test("openGlobalSearchModal shows modal", () => {
        const { modal } = setupSearchModal();
        win.openGlobalSearchModal();
        expect(modal.classList.contains("hidden")).toBe(false);
        expect(modal.getAttribute("aria-hidden")).toBe("false");
    });

    test("closeGlobalSearchModal hides modal", () => {
        const { modal } = setupSearchModal();
        modal.classList.remove("hidden");
        win.closeGlobalSearchModal();
        expect(modal.classList.contains("hidden")).toBe(true);
        expect(modal.getAttribute("aria-hidden")).toBe("true");
    });

    test("openGlobalSearchModal is idempotent", () => {
        const { modal } = setupSearchModal();
        win.openGlobalSearchModal();
        win.openGlobalSearchModal();
        expect(modal.classList.contains("hidden")).toBe(false);
    });

    test("closeGlobalSearchModal is idempotent when already hidden", () => {
        const { modal } = setupSearchModal();
        win.closeGlobalSearchModal();
        expect(modal.classList.contains("hidden")).toBe(true);
    });

    test("openGlobalSearchModal renders placeholder in results container", () => {
        const { results } = setupSearchModal();
        win.openGlobalSearchModal();
        expect(results.textContent).toContain("Start typing to search");
    });

    test("does nothing when modal element is missing", () => {
        expect(() => win.openGlobalSearchModal()).not.toThrow();
        expect(() => win.closeGlobalSearchModal()).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// navigateToGlobalSearchResult (window-exposed)
// ---------------------------------------------------------------------------
describe("navigateToGlobalSearchResult", () => {
    const f = () => win.navigateToGlobalSearchResult;

    test("does nothing for null button", () => {
        expect(() => f()(null)).not.toThrow();
    });

    test("does nothing for button without entity data", () => {
        const btn = doc.createElement("button");
        expect(() => f()(btn)).not.toThrow();
    });

    test("closes modal when navigating to result", () => {
        const modal = doc.createElement("div");
        modal.id = "global-search-modal";
        doc.body.appendChild(modal);

        win.showTab = vi.fn();

        const btn = doc.createElement("button");
        btn.dataset.entity = "tools";
        btn.dataset.id = "tool-1";
        doc.body.appendChild(btn);

        f()(btn);

        expect(modal.classList.contains("hidden")).toBe(true);
        expect(win.showTab).toHaveBeenCalledWith("tools");
    });

    test("does nothing for unknown entity type", () => {
        const modal = doc.createElement("div");
        modal.id = "global-search-modal";
        doc.body.appendChild(modal);

        const btn = doc.createElement("button");
        btn.dataset.entity = "unknown_entity_xyzzy";
        btn.dataset.id = "123";
        doc.body.appendChild(btn);

        // Should close modal but not throw
        expect(() => f()(btn)).not.toThrow();
        expect(modal.classList.contains("hidden")).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// Filter functions (window-exposed)
// ---------------------------------------------------------------------------
describe("filterServerTable", () => {
    test("is exposed on window", () => {
        expect(typeof win.filterServerTable).toBe("function");
    });
});

describe("filterToolsTable", () => {
    test("is exposed on window", () => {
        expect(typeof win.filterToolsTable).toBe("function");
    });
});
