/**
 * Tests for tag extraction via data-tag attributes and tag filter URL persistence.
 *
 * Covers the data-tag based extraction introduced to replace fragile CSS-class
 * selectors, the catalog special-case path, and URL state sync in addTagToFilter.
 */

import {
    describe,
    test,
    expect,
    beforeAll,
    beforeEach,
    afterAll,
    afterEach,
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
    // Reset URL search params between tests
    win.history.replaceState(null, "", "http://localhost/");
});

// ---------------------------------------------------------------------------
// Helper: build a panel table with data-tag attributes
// ---------------------------------------------------------------------------
function buildPanelTable(entityType, headers, rows) {
    const panel = doc.createElement("div");
    panel.id = `${entityType}-panel`;

    const table = doc.createElement("table");
    const thead = doc.createElement("thead");
    const headerRow = doc.createElement("tr");
    headers.forEach((h) => {
        const th = doc.createElement("th");
        th.textContent = h;
        headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = doc.createElement("tbody");
    rows.forEach((cells) => {
        const tr = doc.createElement("tr");
        cells.forEach((cell) => {
            const td = doc.createElement("td");
            if (Array.isArray(cell)) {
                // Array of tags — render as span elements with data-tag
                cell.forEach((tag) => {
                    const span = doc.createElement("span");
                    span.setAttribute("data-tag", tag);
                    span.textContent = tag;
                    td.appendChild(span);
                });
            } else {
                td.textContent = cell;
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    panel.appendChild(table);
    doc.body.appendChild(panel);
    return panel;
}

// ---------------------------------------------------------------------------
// Helper: build servers-table-body with data-tag attributes (catalog path)
// ---------------------------------------------------------------------------
function buildServersTableBody(tags) {
    const table = doc.createElement("table");
    const tbody = doc.createElement("tbody");
    tbody.id = "servers-table-body";
    tags.forEach((tagList) => {
        const tr = doc.createElement("tr");
        const td = doc.createElement("td");
        tagList.forEach((tag) => {
            const span = doc.createElement("span");
            span.setAttribute("data-tag", tag);
            span.textContent = tag;
            td.appendChild(span);
        });
        tr.appendChild(td);
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    doc.body.appendChild(table);
    return tbody;
}

// ---------------------------------------------------------------------------
// extractAvailableTags — catalog special case
// ---------------------------------------------------------------------------
describe("extractAvailableTags — catalog (data-tag)", () => {
    const f = () => win.extractAvailableTags;

    test("extracts tags from #servers-table-body [data-tag]", () => {
        buildServersTableBody([["prod", "staging"], ["dev"]]);
        const result = f()("catalog");
        expect(result).toEqual(["dev", "prod", "staging"]);
    });

    test("returns sorted unique tags", () => {
        buildServersTableBody([
            ["z-tag", "a-tag"],
            ["a-tag", "m-tag"],
        ]);
        const result = f()("catalog");
        expect(result).toEqual(["a-tag", "m-tag", "z-tag"]);
    });

    test("returns empty array when no servers-table-body", () => {
        const result = f()("catalog");
        expect(result).toEqual([]);
    });

    test("skips empty data-tag attributes", () => {
        const tbody = buildServersTableBody([["valid"]]);
        const emptySpan = doc.createElement("span");
        emptySpan.setAttribute("data-tag", "");
        tbody.querySelector("td").appendChild(emptySpan);

        const result = f()("catalog");
        expect(result).toEqual(["valid"]);
    });

    test("skips whitespace-only data-tag", () => {
        const tbody = buildServersTableBody([["valid"]]);
        const wsSpan = doc.createElement("span");
        wsSpan.setAttribute("data-tag", "   ");
        tbody.querySelector("td").appendChild(wsSpan);

        const result = f()("catalog");
        expect(result).toEqual(["valid"]);
    });

    test("skips tags exceeding 50 characters", () => {
        const longTag = "a".repeat(51);
        buildServersTableBody([["ok", longTag]]);
        const result = f()("catalog");
        expect(result).toEqual(["ok"]);
    });

    test("accepts single-character tags", () => {
        buildServersTableBody([["x"]]);
        const result = f()("catalog");
        expect(result).toEqual(["x"]);
    });
});

// ---------------------------------------------------------------------------
// extractAvailableTags — generic entity path (data-tag in panel table)
// ---------------------------------------------------------------------------
describe("extractAvailableTags — generic entity (data-tag)", () => {
    const f = () => win.extractAvailableTags;

    test("extracts tags from panel table using data-tag attributes", () => {
        buildPanelTable(
            "tools",
            ["Name", "Tags", "Status"],
            [
                ["tool-a", ["prod", "staging"], "active"],
                ["tool-b", ["dev"], "active"],
            ],
        );
        const result = f()("tools");
        expect(result).toEqual(["dev", "prod", "staging"]);
    });

    test("returns empty array when no Tags header exists", () => {
        buildPanelTable(
            "tools",
            ["Name", "Description", "Status"],
            [["tool-a", "desc", "active"]],
        );
        const result = f()("tools");
        expect(result).toEqual([]);
    });

    test("returns empty array when panel does not exist", () => {
        const result = f()("nonexistent");
        expect(result).toEqual([]);
    });

    test("skips inactive rows", () => {
        const panel = buildPanelTable(
            "gateways",
            ["Name", "Tags"],
            [
                ["gw-a", ["prod"]],
                ["gw-b", ["staging"]],
            ],
        );
        // Mark second row as inactive
        const rows = panel.querySelectorAll("tbody tr");
        rows[1].classList.add("inactive-row");

        const result = f()("gateways");
        expect(result).toEqual(["prod"]);
    });

    test("handles rows with fewer cells than tagsColumnIndex", () => {
        buildPanelTable("resources", ["Name", "Tags"], [["only-one-cell"]]);
        // The row only has 1 cell but tags column is at index 1
        // This is handled by the tagsColumnIndex < cells.length check
        const result = f()("resources");
        expect(result).toEqual([]);
    });
});

// ---------------------------------------------------------------------------
// updateAvailableTags — renders tag buttons from extracted data
// ---------------------------------------------------------------------------
describe("updateAvailableTags", () => {
    const f = () => win.updateAvailableTags;

    test("populates container with tag buttons", () => {
        buildServersTableBody([["alpha", "beta"]]);

        const container = doc.createElement("div");
        container.id = "catalog-available-tags";
        doc.body.appendChild(container);

        f()("catalog");

        const buttons = container.querySelectorAll("button");
        expect(buttons).toHaveLength(2);
        expect(buttons[0].textContent).toBe("alpha");
        expect(buttons[1].textContent).toBe("beta");
    });

    test("shows 'No tags found' when no tags exist", () => {
        const container = doc.createElement("div");
        container.id = "catalog-available-tags";
        doc.body.appendChild(container);

        f()("catalog");

        expect(container.textContent).toContain("No tags found");
    });

    test("does nothing when container does not exist", () => {
        expect(() => f()("catalog")).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// addTagToFilter — URL state persistence
// ---------------------------------------------------------------------------
describe("addTagToFilter — URL state sync", () => {
    const f = () => win.addTagToFilter;

    test("updates URL with tag filter state for searchable panels", () => {
        // Intercept safeReplaceState to capture URL updates
        let capturedUrl = null;
        win.safeReplaceState = (_state, _title, url) => {
            capturedUrl = url;
        };

        // Use servers-tag-filter (resolved via PANEL_SEARCH_CONFIG for catalog)
        const tagInput = doc.createElement("input");
        tagInput.id = "servers-tag-filter";
        tagInput.value = "";
        doc.body.appendChild(tagInput);

        const searchInput = doc.createElement("input");
        searchInput.id = "servers-search-input";
        searchInput.value = "";
        doc.body.appendChild(searchInput);

        f()("catalog", "production");

        expect(capturedUrl).not.toBeNull();
        expect(capturedUrl).toContain("servers_tags=production");
    });

    test("preserves search query in URL when adding tag", () => {
        let capturedUrl = null;
        win.safeReplaceState = (_state, _title, url) => {
            capturedUrl = url;
        };

        const tagInput = doc.createElement("input");
        tagInput.id = "servers-tag-filter";
        tagInput.value = "";
        doc.body.appendChild(tagInput);

        const searchInput = doc.createElement("input");
        searchInput.id = "servers-search-input";
        searchInput.value = "my-search";
        doc.body.appendChild(searchInput);

        f()("catalog", "staging");

        expect(capturedUrl).not.toBeNull();
        expect(capturedUrl).toContain("servers_q=my-search");
        expect(capturedUrl).toContain("servers_tags=staging");
    });
});

// ---------------------------------------------------------------------------
// tableToEntityType mapping
// ---------------------------------------------------------------------------
describe("tableToEntityType mapping", () => {
    test("servers-table maps to catalog", () => {
        // Verify the htmx:afterSettle handler correctly resolves entity types
        // by dispatching a simulated htmx:afterSettle event.
        buildServersTableBody([["test-tag"]]);
        const container = doc.createElement("div");
        container.id = "catalog-available-tags";
        doc.body.appendChild(container);

        // Create a mock target element with the expected table ID
        const target = doc.createElement("div");
        target.id = "servers-table";
        doc.body.appendChild(target);

        // Dispatch htmx:afterSettle targeting the servers-table
        const event = new win.Event("htmx:afterSettle", { bubbles: true });
        Object.defineProperty(event, "detail", {
            value: { target: target },
        });
        doc.body.dispatchEvent(event);

        // The handler should have called updateAvailableTags("catalog")
        const buttons = container.querySelectorAll("button");
        expect(buttons.length).toBeGreaterThanOrEqual(1);
        expect(buttons[0].textContent).toBe("test-tag");
    });
});

// ---------------------------------------------------------------------------
// Helper: build a servers-table with real table content (no loading message)
// ---------------------------------------------------------------------------
function buildLoadedServersTable() {
    const wrapper = doc.createElement("div");
    wrapper.id = "servers-table";
    const table = doc.createElement("table");
    const tbody = doc.createElement("tbody");
    const tr = doc.createElement("tr");
    const td = doc.createElement("td");
    td.textContent = "Server A";
    tr.appendChild(td);
    tbody.appendChild(tr);
    table.appendChild(tbody);
    wrapper.appendChild(table);
    doc.body.appendChild(wrapper);
    return wrapper;
}

// ---------------------------------------------------------------------------
// showTab("catalog") — regression path: restore filters from URL
// ---------------------------------------------------------------------------
describe("showTab catalog — restore filters from URL on return", () => {
    const showTab = () => win.showTab;

    // showTab wraps content-loading logic in setTimeout; use fake timers
    // so vi.runAllTimers() flushes the callback synchronously.
    beforeEach(() => {
        vi.useFakeTimers();
    });
    afterEach(() => {
        vi.useRealTimers();
    });

    test("restores tag and search inputs from URL when table is already loaded", () => {
        // Seed URL with persisted filter state
        win.history.replaceState(
            {},
            "",
            "http://localhost/?servers_tags=prod&servers_q=my-search#catalog",
        );

        buildLoadedServersTable();

        // Create the renamed inputs (resolved via PANEL_SEARCH_CONFIG)
        const tagInput = doc.createElement("input");
        tagInput.id = "servers-tag-filter";
        tagInput.value = "";
        doc.body.appendChild(tagInput);

        const searchInput = doc.createElement("input");
        searchInput.id = "servers-search-input";
        searchInput.value = "";
        doc.body.appendChild(searchInput);

        // Panel must have "hidden" class so the idempotency guard
        // (classList.contains("hidden")) doesn't short-circuit showTab.
        const panel = doc.createElement("div");
        panel.id = "catalog-panel";
        panel.classList.add("tab-panel", "hidden");
        doc.body.appendChild(panel);

        showTab()("catalog");
        vi.runAllTimers();

        expect(tagInput.value).toBe("prod");
        expect(searchInput.value).toBe("my-search");
    });

    test("does not overwrite inputs when URL has no filter state", () => {
        win.history.replaceState({}, "", "http://localhost/#catalog");

        buildLoadedServersTable();

        const tagInput = doc.createElement("input");
        tagInput.id = "servers-tag-filter";
        tagInput.value = "existing";
        doc.body.appendChild(tagInput);

        const searchInput = doc.createElement("input");
        searchInput.id = "servers-search-input";
        searchInput.value = "existing-q";
        doc.body.appendChild(searchInput);

        const panel = doc.createElement("div");
        panel.id = "catalog-panel";
        panel.classList.add("tab-panel", "hidden");
        doc.body.appendChild(panel);

        showTab()("catalog");
        vi.runAllTimers();

        // Inputs should remain unchanged — no URL state to restore
        expect(tagInput.value).toBe("existing");
        expect(searchInput.value).toBe("existing-q");
    });
});

// ---------------------------------------------------------------------------
// filterEntitiesByTags — uses data-tag attributes
// ---------------------------------------------------------------------------
describe("filterEntitiesByTags — data-tag contract", () => {
    const f = () => win.filterEntitiesByTags;

    function buildTaggedPanel(entityType, rows) {
        const panel = doc.createElement("div");
        panel.id = `${entityType}-panel`;
        const table = doc.createElement("table");
        const tbody = doc.createElement("tbody");
        rows.forEach(({ text, tags }) => {
            const tr = doc.createElement("tr");
            const td1 = doc.createElement("td");
            td1.textContent = text;
            tr.appendChild(td1);
            const td2 = doc.createElement("td");
            tags.forEach((tag) => {
                const span = doc.createElement("span");
                span.setAttribute("data-tag", tag);
                span.textContent = tag;
                td2.appendChild(span);
            });
            tr.appendChild(td2);
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        panel.appendChild(table);
        doc.body.appendChild(panel);
        return tbody;
    }

    test("shows rows matching filter tag", () => {
        const tbody = buildTaggedPanel("tools", [
            { text: "Tool A", tags: ["production"] },
            { text: "Tool B", tags: ["staging"] },
        ]);
        f()("tools", "production");
        const rows = tbody.querySelectorAll("tr");
        expect(rows[0].style.display).toBe("");
        expect(rows[1].style.display).toBe("none");
    });

    test("hides all rows when no tags match", () => {
        const tbody = buildTaggedPanel("tools", [
            { text: "Tool A", tags: ["alpha"] },
            { text: "Tool B", tags: ["beta"] },
        ]);
        f()("tools", "nonexistent");
        const rows = tbody.querySelectorAll("tr");
        expect(rows[0].style.display).toBe("none");
        expect(rows[1].style.display).toBe("none");
    });

    test("empty filter shows all rows", () => {
        const tbody = buildTaggedPanel("tools", [
            { text: "Tool A", tags: ["production"] },
            { text: "Tool B", tags: ["staging"] },
        ]);
        f()("tools", "");
        const rows = tbody.querySelectorAll("tr");
        expect(rows[0].style.display).toBe("");
        expect(rows[1].style.display).toBe("");
    });

    test("partial tag match works (OR substring logic)", () => {
        const tbody = buildTaggedPanel("tools", [
            { text: "Tool A", tags: ["production-us"] },
            { text: "Tool B", tags: ["staging"] },
        ]);
        f()("tools", "production");
        const rows = tbody.querySelectorAll("tr");
        expect(rows[0].style.display).toBe("");
        expect(rows[1].style.display).toBe("none");
    });
});
