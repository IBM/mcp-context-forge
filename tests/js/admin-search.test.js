/**
 * Unit tests for unified admin search (panel search + global search).
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

    test("clears search input and triggers server-side reload for panel entities", () => {
        // clearSearch clears the search input and triggers loadSearchablePanel
        // to fetch filtered results from the server (fixes #3128)
        const searchInput = doc.createElement("input");
        searchInput.id = "tools-search-input";
        searchInput.value = "test query";
        doc.body.appendChild(searchInput);

        const tagInput = doc.createElement("input");
        tagInput.id = "tools-tag-filter";
        tagInput.value = "tag1";
        doc.body.appendChild(tagInput);

        f()("tools");

        // Verify inputs are cleared
        expect(searchInput.value).toBe("");
        expect(tagInput.value).toBe("");
        // Note: loadSearchablePanel is called but we don't test HTMX behavior here
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

describe("team member modal split search regressions", () => {
    function userItemHtml(
        email,
        { checked = false, role = "member", autoCheck = false } = {},
    ) {
        const autoCheckAttr = autoCheck ? ' data-auto-check="true"' : "";
        const checkedAttr = checked ? " checked" : "";
        return `
            <div class="user-item" data-user-email="${email}">
                <input type="checkbox" name="associatedUsers" value="${email}"${autoCheckAttr}${checkedAttr} />
                <select class="role-select" name="role_${encodeURIComponent(email)}">
                    <option value="member"${role === "member" ? " selected" : ""}>Member</option>
                    <option value="owner"${role === "owner" ? " selected" : ""}>Owner</option>
                </select>
            </div>
        `;
    }

    test("serverSideNonMemberSearch enforces 2-char minimum without fetch", async () => {
        const teamId = "team-short-search";
        const container = doc.createElement("div");
        container.id = `team-non-members-container-${teamId}`;
        doc.body.appendChild(container);

        const originalFetchWithAuth = win.fetchWithAuth;
        win.fetchWithAuth = vi.fn();

        await win.serverSideNonMemberSearch(teamId, "a");

        expect(win.fetchWithAuth).not.toHaveBeenCalled();
        expect(container.textContent.toLowerCase()).toContain(
            "at least 2 characters",
        );
        win.fetchWithAuth = originalFetchWithAuth;
    });

    test("serverSideNonMemberSearch preserves selected users across different search results", async () => {
        const teamId = "team-nonmember-cache";
        const container = doc.createElement("div");
        container.id = `team-non-members-container-${teamId}`;
        container.innerHTML = userItemHtml("alice@example.com", {
            checked: true,
            role: "owner",
        });
        doc.body.appendChild(container);

        const originalFetchWithAuth = win.fetchWithAuth;
        win.fetchWithAuth = vi.fn().mockResolvedValue({
            ok: true,
            text: async () =>
                userItemHtml("bob@example.com", {
                    checked: false,
                    role: "member",
                }),
        });

        await win.serverSideNonMemberSearch(teamId, "bo");

        expect(win.fetchWithAuth).toHaveBeenCalledTimes(1);
        expect(
            Array.from(
                container.querySelectorAll('input[name="associatedUsers"]'),
            ).some(
                (input) => input.value === "alice@example.com" && input.checked,
            ),
        ).toBe(true);
        const aliceRoleInput = Array.from(
            container.querySelectorAll('input[type="hidden"]'),
        ).find((input) => input.name === "role_alice%40example.com");
        expect(aliceRoleInput).toBeDefined();
        expect(aliceRoleInput.value).toBe("owner");
        win.fetchWithAuth = originalFetchWithAuth;
    });

    test("serverSideMemberSearch restores member checkbox/role overrides after rerender", async () => {
        const teamId = "team-member-overrides";
        const container = doc.createElement("div");
        container.id = `team-members-container-${teamId}`;
        container.dataset.perPage = "50";
        container.innerHTML = userItemHtml("member@example.com", {
            checked: true,
            role: "member",
            autoCheck: true,
        });
        doc.body.appendChild(container);

        const existingCheckbox = container.querySelector(
            'input[name="associatedUsers"]',
        );
        const existingRoleSelect = container.querySelector(".role-select");
        existingCheckbox.checked = false;
        existingRoleSelect.value = "owner";

        const originalFetchWithAuth = win.fetchWithAuth;
        win.fetchWithAuth = vi.fn().mockResolvedValue({
            ok: true,
            text: async () =>
                userItemHtml("member@example.com", {
                    checked: true,
                    role: "member",
                    autoCheck: true,
                }),
        });

        await win.serverSideMemberSearch(teamId, "mem");

        const rerenderedCheckbox = container.querySelector(
            'input[name="associatedUsers"]',
        );
        const rerenderedRoleSelect = container.querySelector(".role-select");
        expect(rerenderedCheckbox.checked).toBe(false);
        expect(rerenderedRoleSelect.value).toBe("owner");
        win.fetchWithAuth = originalFetchWithAuth;
    });
});
