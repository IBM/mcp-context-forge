/**
 * Regression tests for the infinite /partial request loop triggered by
 * search input initialization (fixes search bar infinite loop).
 *
 * The bug: initializeSearchInputs() attached the `input` event listener
 * BEFORE setting `searchInput.value`, so restoring the search query from
 * the URL fired the listener, which queued a /partial reload, which after
 * swapping triggered re-initialization — an infinite loop.
 *
 * The fix: set .value BEFORE attaching the listener, and stop
 * re-initializing search inputs in htmx:afterSwap / htmx:afterSettle
 * handlers (search inputs live outside the swapped table content).
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
    // Provide a stub htmx so loadSearchablePanel doesn't throw
    win.htmx = { ajax: vi.fn() };
    win.ROOT_PATH = "";
    // Clean URL search params so a failed test doesn't contaminate the next one
    const clean = new URL(win.location.href);
    clean.search = "";
    win.history.replaceState({}, "", clean.toString());
});

// ---------------------------------------------------------------------------
// Helper: build the minimal DOM for a panel's search infrastructure
// ---------------------------------------------------------------------------
function setupPanelDOM(_entityType, { searchInputId, tagInputId, tableName }) {
    const searchInput = doc.createElement("input");
    searchInput.id = searchInputId;
    searchInput.type = "text";
    doc.body.appendChild(searchInput);

    const tagInput = doc.createElement("input");
    tagInput.id = tagInputId;
    tagInput.type = "text";
    doc.body.appendChild(tagInput);

    const table = doc.createElement("table");
    table.id = `${tableName}-table`;
    doc.body.appendChild(table);

    return { searchInput, tagInput, table };
}

// ---------------------------------------------------------------------------
// initializeSearchInputs: value set before listener attachment
// ---------------------------------------------------------------------------
describe("initializeSearchInputs does not trigger reload on init", () => {
    test("setting search value from URL state does not fire input listener", () => {
        // Simulate URL state with a search query for servers
        const url = new URL(win.location.href);
        url.searchParams.set("servers_q", "my-query");
        win.history.replaceState({}, "", url.toString());

        const { searchInput } = setupPanelDOM("catalog", {
            searchInputId: "servers-search-input",
            tagInputId: "servers-tag-filter",
            tableName: "servers",
        });

        // Spy on input events — the fix ensures none fire during init
        const inputSpy = vi.fn();
        // We add a capturing listener on the parent to catch any input event
        // that might bubble from the search input during initialization.
        searchInput.parentNode.addEventListener("input", inputSpy, true);

        // Reset htmx.ajax call count before init
        win.htmx.ajax.mockClear();

        // Trigger search initialization via the exposed test helper
        win.testSearchInit();

        // The value should be restored from URL state
        const updatedInput = doc.getElementById("servers-search-input");
        expect(updatedInput.value).toBe("my-query");

        // No input event should have been dispatched during initialization
        // (Before the fix, setting .value after attaching the listener would
        // fire an input event and queue a /partial reload)
        expect(inputSpy).not.toHaveBeenCalled();

        // Clean up URL state
        url.searchParams.delete("servers_q");
        win.history.replaceState({}, "", url.toString());
    });

    test("setting tag value from URL state does not fire input listener", () => {
        const url = new URL(win.location.href);
        url.searchParams.set("tools_tags", "prod,staging");
        win.history.replaceState({}, "", url.toString());

        const { tagInput } = setupPanelDOM("tools", {
            searchInputId: "tools-search-input",
            tagInputId: "tools-tag-filter",
            tableName: "tools",
        });

        const inputSpy = vi.fn();
        tagInput.parentNode.addEventListener("input", inputSpy, true);

        win.htmx.ajax.mockClear();
        win.testSearchInit();

        const updatedTag = doc.getElementById("tools-tag-filter");
        expect(updatedTag.value).toBe("prod,staging");
        expect(inputSpy).not.toHaveBeenCalled();

        url.searchParams.delete("tools_tags");
        win.history.replaceState({}, "", url.toString());
    });

    test("no htmx.ajax call is made during initialization", () => {
        const url = new URL(win.location.href);
        url.searchParams.set("servers_q", "test");
        win.history.replaceState({}, "", url.toString());

        setupPanelDOM("catalog", {
            searchInputId: "servers-search-input",
            tagInputId: "servers-tag-filter",
            tableName: "servers",
        });

        win.htmx.ajax.mockClear();

        vi.useFakeTimers();
        try {
            win.testSearchInit();
            // Flush any debounced timers that might have been queued
            vi.advanceTimersByTime(1000);
        } finally {
            vi.useRealTimers();
        }

        // Before the fix, initializeSearchInputs would set .value after
        // attaching the listener, which queued a loadSearchablePanel call
        expect(win.htmx.ajax).not.toHaveBeenCalled();

        url.searchParams.delete("servers_q");
        win.history.replaceState({}, "", url.toString());
    });
});

// ---------------------------------------------------------------------------
// Typing in search input after init DOES trigger a reload (positive test)
// ---------------------------------------------------------------------------
describe("search input triggers reload on user input after init", () => {
    test("typing in search input queues a debounced /partial reload", () => {
        setupPanelDOM("catalog", {
            searchInputId: "servers-search-input",
            tagInputId: "servers-tag-filter",
            tableName: "servers",
        });

        win.htmx.ajax.mockClear();

        vi.useFakeTimers();
        try {
            win.testSearchInit();

            // Simulate user typing — dispatching an input event
            const input = doc.getElementById("servers-search-input");
            input.value = "hello";
            input.dispatchEvent(new win.Event("input", { bubbles: true }));

            // Before the debounce fires, no request yet
            expect(win.htmx.ajax).not.toHaveBeenCalled();

            // After debounce delay (250ms), the /partial request fires
            vi.advanceTimersByTime(300);
            expect(win.htmx.ajax).toHaveBeenCalledTimes(1);

            const [method, url] = win.htmx.ajax.mock.calls[0];
            expect(method).toBe("GET");
            expect(url).toContain("/admin/servers/partial");
            expect(url).toContain("q=hello");
        } finally {
            vi.useRealTimers();
        }
    });
});

// ---------------------------------------------------------------------------
// htmx:afterSwap on a table target should NOT re-initialize search inputs
// ---------------------------------------------------------------------------
describe("htmx:afterSwap does not re-initialize search inputs", () => {
    test("swapping a table target does not trigger htmx.ajax via search reinit", () => {
        const url = new URL(win.location.href);
        url.searchParams.set("servers_q", "existing-query");
        win.history.replaceState({}, "", url.toString());

        setupPanelDOM("catalog", {
            searchInputId: "servers-search-input",
            tagInputId: "servers-tag-filter",
            tableName: "servers",
        });

        // Initialize search inputs first
        win.testSearchInit();
        win.htmx.ajax.mockClear();

        vi.useFakeTimers();
        try {
            // Simulate an HTMX afterSwap event on the table element
            const table = doc.getElementById("servers-table");
            const swapEvent = new win.Event("htmx:afterSwap", {
                bubbles: true,
            });
            // HTMX events carry detail on the event object
            Object.defineProperty(swapEvent, "detail", {
                value: { target: table },
            });
            doc.body.dispatchEvent(swapEvent);

            // Flush any timers from potential debounced re-initialization
            vi.advanceTimersByTime(1000);

            // No /partial request should be triggered by the swap handler
            // (Before the fix, afterSwap would reset + reinitialize, which
            // set .value and triggered input → queueSearchablePanelReload)
            expect(win.htmx.ajax).not.toHaveBeenCalled();
        } finally {
            vi.useRealTimers();
        }

        url.searchParams.delete("servers_q");
        win.history.replaceState({}, "", url.toString());
    });
});

// ---------------------------------------------------------------------------
// htmx:afterSettle on a table target should NOT re-initialize search inputs
// ---------------------------------------------------------------------------
describe("htmx:afterSettle does not re-initialize search inputs", () => {
    test("settling a table target does not trigger htmx.ajax via search reinit", () => {
        const url = new URL(win.location.href);
        url.searchParams.set("tools_q", "my-tool");
        win.history.replaceState({}, "", url.toString());

        setupPanelDOM("tools", {
            searchInputId: "tools-search-input",
            tagInputId: "tools-tag-filter",
            tableName: "tools",
        });

        win.testSearchInit();
        win.htmx.ajax.mockClear();

        vi.useFakeTimers();
        try {
            const table = doc.getElementById("tools-table");
            const settleEvent = new win.Event("htmx:afterSettle", {
                bubbles: true,
            });
            Object.defineProperty(settleEvent, "detail", {
                value: { target: table },
            });
            doc.dispatchEvent(settleEvent);

            vi.advanceTimersByTime(1000);

            expect(win.htmx.ajax).not.toHaveBeenCalled();
        } finally {
            vi.useRealTimers();
        }

        url.searchParams.delete("tools_q");
        win.history.replaceState({}, "", url.toString());
    });
});

// ---------------------------------------------------------------------------
// Search input value persists across table swaps (not re-cloned)
// ---------------------------------------------------------------------------
describe("search input persists across table swaps", () => {
    test("search input value and listener survive a table swap", () => {
        setupPanelDOM("catalog", {
            searchInputId: "servers-search-input",
            tagInputId: "servers-tag-filter",
            tableName: "servers",
        });

        win.testSearchInit();

        // Type a value into the search input
        const input = doc.getElementById("servers-search-input");
        input.value = "my-search";

        // Simulate a table swap (replace table content, not the search input)
        const table = doc.getElementById("servers-table");
        table.innerHTML = "<tr><td>New content</td></tr>";

        // Fire afterSwap
        const swapEvent = new win.Event("htmx:afterSwap", { bubbles: true });
        Object.defineProperty(swapEvent, "detail", {
            value: { target: table },
        });
        doc.body.dispatchEvent(swapEvent);

        // Search input should still have its value (it was NOT re-cloned)
        const inputAfterSwap = doc.getElementById("servers-search-input");
        expect(inputAfterSwap).not.toBeNull();
        expect(inputAfterSwap.value).toBe("my-search");
    });
});
