/**
 * Unit tests for plugin filter delegation (issue #3271).
 *
 * Covers:
 *   A. initializePluginFunctions() sets up input/change listeners on #plugin-filters
 *   B. initializePluginFunctions() sets up click/keydown listeners on #plugins-panel
 *   C. Typing in search box calls filterPlugins and hides/shows cards
 *   D. Changing a dropdown calls filterPlugins
 *   E. Clicking a hook/tag/author badge calls filterByHook/Tag/Author
 *   F. Clicking "View Details" button calls showPluginDetails
 *   G. Enter/Space on a focused badge calls the filter (keyboard navigation)
 */

import { describe, test, expect, beforeAll, afterAll, vi } from "vitest";
import { loadAdminJs, cleanupAdminJs } from "./helpers/admin-env.js";

let win;
let doc;

beforeAll(() => {
    win = loadAdminJs({
        beforeEval: (window) => {
            window.getPaginationParams = () => ({
                page: 1,
                perPage: 10,
                includeInactive: null,
            });
            window.buildTableUrl = (tableName, baseUrl) => baseUrl;
            window.safeReplaceState = () => {};
            window.IS_ADMIN = true;
            // JSDOM does not implement scrollIntoView
            window.HTMLElement.prototype.scrollIntoView = () => {};
        },
    });
    doc = win.document;
});

afterAll(() => {
    cleanupAdminJs();
});

// ---------------------------------------------------------------------------
// Helper: build a minimal plugins panel + partial DOM
// ---------------------------------------------------------------------------
function buildPluginsDOM() {
    doc.body.innerHTML = "";

    // Outer panel (what admin.html provides)
    const panel = doc.createElement("div");
    panel.id = "plugins-panel";
    doc.body.appendChild(panel);

    // Modal (outside plugins_enabled block in the real template)
    const modal = doc.createElement("div");
    modal.id = "plugin-details-modal";
    modal.className = "hidden";
    const modalName = doc.createElement("div");
    modalName.id = "modal-plugin-name";
    const modalContent = doc.createElement("div");
    modalContent.id = "modal-plugin-content";
    const closeBtn = doc.createElement("button");
    closeBtn.dataset.closePluginModal = "";
    modal.append(modalName, modalContent, closeBtn);
    panel.appendChild(modal);

    // Inject partial content (what the fetch would return after sanitisation)
    const partial = doc.createElement("div");
    partial.className = "space-y-6";

    // --- Hook badges (stats section) ---
    const hookBadgeAll = doc.createElement("div");
    hookBadgeAll.dataset.filterHook = "";
    hookBadgeAll.setAttribute("role", "button");
    hookBadgeAll.setAttribute("tabindex", "0");
    hookBadgeAll.textContent = "All Hooks";

    const hookBadgeRequest = doc.createElement("div");
    hookBadgeRequest.dataset.filterHook = "request_hook";
    hookBadgeRequest.setAttribute("role", "button");
    hookBadgeRequest.setAttribute("tabindex", "0");
    const hookSpan = doc.createElement("span");
    hookSpan.textContent = "Request Hook";
    hookBadgeRequest.appendChild(hookSpan);

    // --- Tag badges ---
    const tagBadgeAll = doc.createElement("span");
    tagBadgeAll.dataset.filterTag = "";
    tagBadgeAll.setAttribute("role", "button");
    tagBadgeAll.setAttribute("tabindex", "0");
    tagBadgeAll.textContent = "All Tags";

    const tagBadgeSecurity = doc.createElement("span");
    tagBadgeSecurity.dataset.filterTag = "security";
    tagBadgeSecurity.setAttribute("role", "button");
    tagBadgeSecurity.setAttribute("tabindex", "0");
    tagBadgeSecurity.textContent = "security";

    // --- Author badges ---
    const authorBadgeAll = doc.createElement("span");
    authorBadgeAll.dataset.filterAuthor = "";
    authorBadgeAll.setAttribute("role", "button");
    authorBadgeAll.setAttribute("tabindex", "0");
    authorBadgeAll.textContent = "All Authors";

    const authorBadgeIbm = doc.createElement("span");
    authorBadgeIbm.dataset.filterAuthor = "ibm";
    authorBadgeIbm.setAttribute("role", "button");
    authorBadgeIbm.setAttribute("tabindex", "0");
    authorBadgeIbm.textContent = "ibm";

    // --- Search & filter controls (#plugin-filters) ---
    const filtersSection = doc.createElement("div");
    filtersSection.id = "plugin-filters";

    const searchInput = doc.createElement("input");
    searchInput.type = "text";
    searchInput.id = "plugin-search";
    filtersSection.appendChild(searchInput);

    const modeFilter = doc.createElement("select");
    modeFilter.id = "plugin-mode-filter";
    const modeOpt = doc.createElement("option");
    modeOpt.value = "";
    modeOpt.textContent = "All Modes";
    modeFilter.appendChild(modeOpt);
    filtersSection.appendChild(modeFilter);

    const statusFilter = doc.createElement("select");
    statusFilter.id = "plugin-status-filter";
    const statusOpt = doc.createElement("option");
    statusOpt.value = "";
    statusOpt.textContent = "All Status";
    statusFilter.appendChild(statusOpt);
    filtersSection.appendChild(statusFilter);

    const hookFilter = doc.createElement("select");
    hookFilter.id = "plugin-hook-filter";
    const hookOpt = doc.createElement("option");
    hookOpt.value = "";
    hookOpt.textContent = "All Hooks";
    hookFilter.appendChild(hookOpt);
    filtersSection.appendChild(hookFilter);

    const tagFilter = doc.createElement("select");
    tagFilter.id = "plugin-tag-filter";
    const tagOpt = doc.createElement("option");
    tagOpt.value = "";
    tagOpt.textContent = "All Tags";
    tagFilter.appendChild(tagOpt);
    filtersSection.appendChild(tagFilter);

    const authorFilter = doc.createElement("select");
    authorFilter.id = "plugin-author-filter";
    const authorOpt = doc.createElement("option");
    authorOpt.value = "";
    authorOpt.textContent = "All Authors";
    authorFilter.appendChild(authorOpt);
    filtersSection.appendChild(authorFilter);

    // --- Plugin grid with cards ---
    const grid = doc.createElement("div");
    grid.id = "plugin-grid";

    const card1 = doc.createElement("div");
    card1.className = "plugin-card";
    card1.dataset.name = "http-header-filter";
    card1.dataset.description = "filter sensitive http headers";
    card1.dataset.author = "ibm";
    card1.dataset.mode = "enforce";
    card1.dataset.status = "enabled";
    card1.dataset.hooks = "request_hook,response_hook";
    card1.dataset.tags = "security,headers";
    const viewBtn1 = doc.createElement("button");
    viewBtn1.dataset.showPlugin = "http-header-filter";
    viewBtn1.textContent = "View Details";
    card1.appendChild(viewBtn1);
    grid.appendChild(card1);

    const card2 = doc.createElement("div");
    card2.className = "plugin-card";
    card2.dataset.name = "rate-limiter";
    card2.dataset.description = "limits request rate";
    card2.dataset.author = "community";
    card2.dataset.mode = "permissive";
    card2.dataset.status = "enabled";
    card2.dataset.hooks = "request_hook";
    card2.dataset.tags = "rate-limiting";
    const viewBtn2 = doc.createElement("button");
    viewBtn2.dataset.showPlugin = "rate-limiter";
    viewBtn2.textContent = "View Details";
    card2.appendChild(viewBtn2);
    grid.appendChild(card2);

    const card3 = doc.createElement("div");
    card3.className = "plugin-card";
    card3.dataset.name = "http-header-filter";
    card3.dataset.description = "filter sensitive http headers";
    card3.dataset.author = "ibm";
    card3.dataset.mode = "enforce_ignore_error";
    card3.dataset.status = "enabled";
    card3.dataset.hooks = "request_hook,response_hook";
    card3.dataset.tags = "security,headers";
    const viewBtn3 = doc.createElement("button");
    viewBtn3.dataset.showPlugin = "http-header-filter";
    viewBtn3.textContent = "View Details";
    card3.appendChild(viewBtn3);
    grid.appendChild(card3);

    partial.append(
        hookBadgeAll,
        hookBadgeRequest,
        tagBadgeAll,
        tagBadgeSecurity,
        authorBadgeAll,
        authorBadgeIbm,
        filtersSection,
        grid,
    );
    panel.appendChild(partial);

    return {
        panel,
        filtersSection,
        searchInput,
        modeFilter,
        statusFilter,
        hookFilter,
        tagFilter,
        authorFilter,
        hookBadgeAll,
        hookBadgeRequest,
        tagBadgeAll,
        tagBadgeSecurity,
        authorBadgeAll,
        authorBadgeIbm,
        card1,
        card2,
        card3,
        viewBtn1,
        viewBtn2,
        modal,
        closeBtn,
    };
}

// ---------------------------------------------------------------------------
// A. Listener setup
// ---------------------------------------------------------------------------

describe("A. initializePluginFunctions() sets up listeners", () => {
    test("input event on search box triggers filterPlugins", () => {
        const { searchInput } = buildPluginsDOM();
        win.initializePluginFunctions();

        // Spy AFTER init; arrow-function wrapper in listener looks up win.filterPlugins
        // at event time so the spy is picked up correctly
        const spy = vi.spyOn(win, "filterPlugins");

        searchInput.value = "header";
        searchInput.dispatchEvent(new win.Event("input", { bubbles: true }));

        expect(spy).toHaveBeenCalled();
    });

    test("change event on dropdown triggers filterPlugins", () => {
        const { modeFilter } = buildPluginsDOM();
        win.initializePluginFunctions();

        const spy = vi.spyOn(win, "filterPlugins");

        const enforceOpt = doc.createElement("option");
        enforceOpt.value = "enforce";
        modeFilter.appendChild(enforceOpt);

        modeFilter.value = "enforce";
        modeFilter.dispatchEvent(new win.Event("change", { bubbles: true }));

        expect(spy).toHaveBeenCalled();
    });
});

// ---------------------------------------------------------------------------
// B. filterPlugins — search filtering
// ---------------------------------------------------------------------------

describe("B. filterPlugins search filtering", () => {
    test("searching for 'header' hides card that does not match", () => {
        const { searchInput, card1, card2, card3 } = buildPluginsDOM();
        win.initializePluginFunctions();

        searchInput.value = "header";
        searchInput.dispatchEvent(new win.Event("input", { bubbles: true }));

        // card1 and card3 name/desc contain "header", card2 does not
        expect(card1.style.display).not.toBe("none");
        expect(card2.style.display).toBe("none");
        expect(card3.style.display).not.toBe("none");
    });

    test("clearing search shows all cards", () => {
        const { searchInput, card1, card2, card3 } = buildPluginsDOM();
        win.initializePluginFunctions();

        // First filter
        searchInput.value = "header";
        searchInput.dispatchEvent(new win.Event("input", { bubbles: true }));
        expect(card2.style.display).toBe("none");

        // Then clear
        searchInput.value = "";
        searchInput.dispatchEvent(new win.Event("input", { bubbles: true }));
        expect(card1.style.display).toBe("block");
        expect(card2.style.display).toBe("block");
        expect(card3.style.display).toBe("block");
    });

    test("mode filter hides cards with different mode", () => {
        const { modeFilter, card1, card2, card3 } = buildPluginsDOM();
        win.initializePluginFunctions();

        // Add the option so the select value can actually be set
        const enforceOpt = doc.createElement("option");
        enforceOpt.value = "enforce";
        modeFilter.appendChild(enforceOpt);

        modeFilter.value = "enforce";
        modeFilter.dispatchEvent(new win.Event("change", { bubbles: true }));

        // card1 mode=enforce, card2 mode=permissive
        expect(card1.style.display).toBe("block");
        expect(card2.style.display).toBe("none");
        expect(card3.style.display).toBe("none");
    });
    test("mode filter select enforce_ignore_error card", () => {
        const { modeFilter, card1, card2, card3 } = buildPluginsDOM();
        win.initializePluginFunctions();

        // Add the option so the select value can actually be set
        const enforceOpt = doc.createElement("option");
        enforceOpt.value = "enforce_ignore_error";
        modeFilter.appendChild(enforceOpt);

        modeFilter.value = "enforce_ignore_error";
        modeFilter.dispatchEvent(new win.Event("change", { bubbles: true }));

        // card1 mode=enforce, card2 mode=permissive. card3 mode=enforce_ignore_error
        expect(card1.style.display).toBe("none");
        expect(card2.style.display).toBe("none");
        expect(card3.style.display).toBe("block");
    });

});

// ---------------------------------------------------------------------------
// C. Badge click delegation
// ---------------------------------------------------------------------------

describe("C. badge click sets hook filter and calls filterPlugins", () => {
    test("clicking a specific hook badge filters by that hook", () => {
        const { hookBadgeRequest, hookFilter, card1, card2 } =
            buildPluginsDOM();
        win.initializePluginFunctions();

        // Add option for request_hook to the filter dropdown
        const opt = doc.createElement("option");
        opt.value = "request_hook";
        hookFilter.appendChild(opt);

        hookBadgeRequest.dispatchEvent(
            new win.MouseEvent("click", { bubbles: true }),
        );

        // Both cards have request_hook so both should be visible
        expect(hookFilter.value).toBe("request_hook");
        expect(card1.style.display).not.toBe("none");
        expect(card2.style.display).not.toBe("none");
    });

    test("clicking a span inside a hook badge is handled via closest()", () => {
        const { hookBadgeRequest, hookFilter } = buildPluginsDOM();
        win.initializePluginFunctions();

        const opt = doc.createElement("option");
        opt.value = "request_hook";
        hookFilter.appendChild(opt);

        // Click the inner span, not the badge div directly
        const innerSpan = hookBadgeRequest.querySelector("span");
        innerSpan.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));

        expect(hookFilter.value).toBe("request_hook");
    });

    test("clicking the All Hooks badge resets the hook filter", () => {
        const { hookBadgeAll, hookBadgeRequest, hookFilter } =
            buildPluginsDOM();
        win.initializePluginFunctions();

        const opt = doc.createElement("option");
        opt.value = "request_hook";
        hookFilter.appendChild(opt);

        // First select a specific hook
        hookBadgeRequest.dispatchEvent(
            new win.MouseEvent("click", { bubbles: true }),
        );
        expect(hookFilter.value).toBe("request_hook");

        // Then click All Hooks
        hookBadgeAll.dispatchEvent(
            new win.MouseEvent("click", { bubbles: true }),
        );
        expect(hookFilter.value).toBe("");
    });

    test("clicking a tag badge sets the tag filter", () => {
        const { tagBadgeSecurity, tagFilter, card1, card2 } = buildPluginsDOM();
        win.initializePluginFunctions();

        const opt = doc.createElement("option");
        opt.value = "security";
        tagFilter.appendChild(opt);

        tagBadgeSecurity.dispatchEvent(
            new win.MouseEvent("click", { bubbles: true }),
        );

        expect(tagFilter.value).toBe("security");
        // card1 has security tag, card2 does not
        expect(card1.style.display).not.toBe("none");
        expect(card2.style.display).toBe("none");
    });

    test("clicking an author badge sets the author filter", () => {
        const { authorBadgeIbm, authorFilter, card1, card2 } =
            buildPluginsDOM();
        win.initializePluginFunctions();

        const opt = doc.createElement("option");
        opt.value = "ibm";
        authorFilter.appendChild(opt);

        authorBadgeIbm.dispatchEvent(
            new win.MouseEvent("click", { bubbles: true }),
        );

        expect(authorFilter.value).toBe("ibm");
        // card1 author=ibm, card2 author=community
        expect(card1.style.display).not.toBe("none");
        expect(card2.style.display).toBe("none");
    });
});

// ---------------------------------------------------------------------------
// D. "View Details" button
// ---------------------------------------------------------------------------

describe("D. View Details button opens modal", () => {
    test("clicking View Details calls showPluginDetails", () => {
        const { viewBtn1 } = buildPluginsDOM();
        win.initializePluginFunctions();

        // Replace showPluginDetails to avoid actual fetch
        const spy = vi.fn();
        win.showPluginDetails = spy;

        viewBtn1.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));

        expect(spy).toHaveBeenCalledWith("http-header-filter");
    });
});

// ---------------------------------------------------------------------------
// E. Modal close button
// ---------------------------------------------------------------------------

describe("E. Modal close button calls closePluginDetails", () => {
    test("clicking close button hides the modal", () => {
        const { modal, closeBtn } = buildPluginsDOM();
        win.initializePluginFunctions();

        modal.classList.remove("hidden");

        closeBtn.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));

        expect(modal.classList.contains("hidden")).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// F. Keyboard navigation (Enter/Space on badges)
// ---------------------------------------------------------------------------

describe("F. Keyboard navigation — Enter/Space on badges", () => {
    test("pressing Enter on a hook badge triggers the filter", () => {
        const { hookBadgeRequest, hookFilter } = buildPluginsDOM();
        win.initializePluginFunctions();

        const opt = doc.createElement("option");
        opt.value = "request_hook";
        hookFilter.appendChild(opt);

        hookBadgeRequest.dispatchEvent(
            new win.KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
        );

        expect(hookFilter.value).toBe("request_hook");
    });

    test("pressing Space on a hook badge triggers the filter", () => {
        const { hookBadgeRequest, hookFilter } = buildPluginsDOM();
        win.initializePluginFunctions();

        const opt = doc.createElement("option");
        opt.value = "request_hook";
        hookFilter.appendChild(opt);

        hookBadgeRequest.dispatchEvent(
            new win.KeyboardEvent("keydown", { key: " ", bubbles: true }),
        );

        expect(hookFilter.value).toBe("request_hook");
    });

    test("pressing other keys on a badge does not trigger the filter", () => {
        const { hookBadgeRequest } = buildPluginsDOM();
        win.initializePluginFunctions();

        const spy = vi.spyOn(win, "filterByHook");

        hookBadgeRequest.dispatchEvent(
            new win.KeyboardEvent("keydown", { key: "Tab", bubbles: true }),
        );

        expect(spy).not.toHaveBeenCalled();
    });

    test("pressing Enter on View Details button opens modal", () => {
        const { viewBtn1 } = buildPluginsDOM();
        win.initializePluginFunctions();

        const spy = vi.fn();
        win.showPluginDetails = spy;

        viewBtn1.dispatchEvent(
            new win.KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
        );

        expect(spy).toHaveBeenCalledWith("http-header-filter");
    });

    test("Space in search box is not swallowed by delegated handler", () => {
        const { searchInput } = buildPluginsDOM();
        win.initializePluginFunctions();

        const evt = new win.KeyboardEvent("keydown", {
            key: " ",
            bubbles: true,
            cancelable: true,
        });
        searchInput.dispatchEvent(evt);

        expect(evt.defaultPrevented).toBe(false);
    });

    test("Enter on select dropdown is not swallowed by delegated handler", () => {
        const { modeFilter } = buildPluginsDOM();
        win.initializePluginFunctions();

        const evt = new win.KeyboardEvent("keydown", {
            key: "Enter",
            bubbles: true,
            cancelable: true,
        });
        modeFilter.dispatchEvent(evt);

        expect(evt.defaultPrevented).toBe(false);
    });
});
