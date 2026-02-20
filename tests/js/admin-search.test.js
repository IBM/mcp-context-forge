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

    test("calls legacy filter function to immediately clear rows for panel entities", () => {
        // clearSearch invokes the entity-specific filter as a fallback to keep
        // rows visible even when the HTMX reload is delayed or missed.
        const original = win.filterToolsTable;
        win.filterToolsTable = vi.fn();

        const searchInput = doc.createElement("input");
        searchInput.id = "tools-search-input";
        doc.body.appendChild(searchInput);

        const table = doc.createElement("div");
        table.id = "tools-table";
        doc.body.appendChild(table);

        f()("tools");

        expect(win.filterToolsTable).toHaveBeenCalledWith("");
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

    test("routes users results to users tab and invokes user modal loader", () => {
        const modal = doc.createElement("div");
        modal.id = "global-search-modal";
        doc.body.appendChild(modal);

        const originalShowUserEditModal = win.showUserEditModal;
        win.showUserEditModal = vi.fn();
        win.showTab = vi.fn();

        const btn = doc.createElement("button");
        btn.dataset.entity = "users";
        btn.dataset.id = "user@example.com";
        doc.body.appendChild(btn);

        vi.useFakeTimers();
        try {
            f()(btn);
            vi.runAllTimers();
        } finally {
            vi.useRealTimers();
        }

        expect(win.showTab).toHaveBeenCalledWith("users");
        expect(win.showUserEditModal).toHaveBeenCalledWith("user@example.com");
        expect(modal.classList.contains("hidden")).toBe(true);
        win.showUserEditModal = originalShowUserEditModal;
    });

    test("routes teams results to teams tab and invokes team modal loader", () => {
        const modal = doc.createElement("div");
        modal.id = "global-search-modal";
        doc.body.appendChild(modal);

        const originalShowTeamEditModal = win.showTeamEditModal;
        win.showTeamEditModal = vi.fn();
        win.showTab = vi.fn();

        const btn = doc.createElement("button");
        btn.dataset.entity = "teams";
        btn.dataset.id = "team-123";
        doc.body.appendChild(btn);

        vi.useFakeTimers();
        try {
            f()(btn);
            vi.runAllTimers();
        } finally {
            vi.useRealTimers();
        }

        expect(win.showTab).toHaveBeenCalledWith("teams");
        expect(win.showTeamEditModal).toHaveBeenCalledWith("team-123");
        expect(modal.classList.contains("hidden")).toBe(true);
        win.showTeamEditModal = originalShowTeamEditModal;
    });
});

describe("showUserEditModal", () => {
    test("loads user edit form content via authenticated fetch fallback", async () => {
        const modal = doc.createElement("div");
        modal.id = "user-edit-modal";
        modal.classList.add("hidden");
        modal.style.display = "none";
        doc.body.appendChild(modal);

        const content = doc.createElement("div");
        content.id = "user-edit-modal-content";
        modal.appendChild(content);

        const originalFetchWithAuth = win.fetchWithAuth;
        const originalHtmx = win.htmx;
        const originalRootPath = win.ROOT_PATH;
        win.ROOT_PATH = "";
        win.htmx = null;
        win.fetchWithAuth = vi.fn().mockResolvedValue({
            ok: true,
            status: 200,
            statusText: "OK",
            text: async () =>
                '<div id="loaded-user-form">Loaded user form</div>',
        });

        await win.showUserEditModal("user@example.com");

        expect(win.fetchWithAuth).toHaveBeenCalledWith(
            "/admin/users/user%40example.com/edit",
            { method: "GET" },
        );
        expect(content.innerHTML).toContain("loaded-user-form");
        expect(modal.classList.contains("hidden")).toBe(false);
        expect(modal.style.display).toBe("block");

        win.fetchWithAuth = originalFetchWithAuth;
        win.htmx = originalHtmx;
        win.ROOT_PATH = originalRootPath;
    });

    test("prefers HTMX loader when available", async () => {
        const modal = doc.createElement("div");
        modal.id = "user-edit-modal";
        modal.classList.add("hidden");
        doc.body.appendChild(modal);

        const content = doc.createElement("div");
        content.id = "user-edit-modal-content";
        modal.appendChild(content);

        const originalFetchWithAuth = win.fetchWithAuth;
        const originalHtmx = win.htmx;
        const originalRootPath = win.ROOT_PATH;
        win.ROOT_PATH = "";
        win.fetchWithAuth = vi.fn();
        win.htmx = {
            ajax: vi.fn().mockResolvedValue(undefined),
        };

        await win.showUserEditModal("user@example.com");

        expect(win.htmx.ajax).toHaveBeenCalledWith(
            "GET",
            "/admin/users/user%40example.com/edit",
            {
                target: "#user-edit-modal-content",
                swap: "innerHTML",
            },
        );
        expect(win.fetchWithAuth).not.toHaveBeenCalled();
        expect(modal.classList.contains("hidden")).toBe(false);

        win.fetchWithAuth = originalFetchWithAuth;
        win.htmx = originalHtmx;
        win.ROOT_PATH = originalRootPath;
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
