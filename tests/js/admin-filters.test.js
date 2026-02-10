/**
 * Unit tests for admin.js table filtering functions.
 */

import { describe, test, expect, beforeAll, beforeEach, afterAll } from "vitest";
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
// Helper: build a simple table with tbody
// ---------------------------------------------------------------------------
function buildTable(tbodyId, rows, { testIdAttr, startCol = 0 } = {}) {
    const table = doc.createElement("table");
    const tbody = doc.createElement("tbody");
    tbody.id = tbodyId;
    rows.forEach((cells) => {
        const tr = doc.createElement("tr");
        if (testIdAttr) tr.setAttribute("data-testid", testIdAttr);
        cells.forEach((text) => {
            const td = doc.createElement("td");
            td.textContent = text;
            tr.appendChild(td);
        });
        table.appendChild(tbody);
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return table;
}

// ---------------------------------------------------------------------------
// filterServerTable
// ---------------------------------------------------------------------------
describe("filterServerTable", () => {
    const f = () => win.filterServerTable;

    function buildServerTable(rows) {
        const table = doc.createElement("table");
        const tbody = doc.createElement("tbody");
        tbody.id = "servers-table-body";
        rows.forEach((cells) => {
            const tr = doc.createElement("tr");
            tr.setAttribute("data-testid", "server-item");
            cells.forEach((text) => {
                const td = doc.createElement("td");
                td.textContent = text;
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        doc.body.appendChild(table);
        return tbody;
    }

    test("shows matching rows and hides non-matching", () => {
        // Columns: Actions(0), Icon(1), S.No.(2), UUID(3), Name(4), ...
        const tbody = buildServerTable([
            ["act", "ico", "1", "uuid-1", "Alpha Server", "desc alpha"],
            ["act", "ico", "2", "uuid-2", "Beta Server", "desc beta"],
        ]);
        f()("alpha");
        const rows = tbody.querySelectorAll("tr");
        expect(rows[0].style.display).toBe("");
        expect(rows[1].style.display).toBe("none");
    });

    test("empty search shows all rows", () => {
        const tbody = buildServerTable([
            ["act", "ico", "1", "uuid-1", "Alpha", "desc"],
            ["act", "ico", "2", "uuid-2", "Beta", "desc"],
        ]);
        f()("");
        const rows = tbody.querySelectorAll("tr");
        expect(rows[0].style.display).toBe("");
        expect(rows[1].style.display).toBe("");
    });

    test("case-insensitive search", () => {
        const tbody = buildServerTable([
            ["act", "ico", "1", "uuid-1", "MyServer", "test"],
        ]);
        f()("MYSERVER");
        expect(tbody.querySelector("tr").style.display).toBe("");
    });

    test("no table does not throw", () => {
        expect(() => f()("anything")).not.toThrow();
    });

    test("falls back to data-testid selector", () => {
        // Build without #servers-table-body id
        const table = doc.createElement("table");
        const tbody = doc.createElement("tbody");
        tbody.setAttribute("data-testid", "server-list");
        const tr = doc.createElement("tr");
        tr.setAttribute("data-testid", "server-item");
        ["act", "ico", "1", "uuid", "Fallback Server", "desc"].forEach((t) => {
            const td = doc.createElement("td");
            td.textContent = t;
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
        table.appendChild(tbody);
        doc.body.appendChild(table);

        f()("fallback");
        expect(tr.style.display).toBe("");
    });
});

// ---------------------------------------------------------------------------
// filterToolsTable
// ---------------------------------------------------------------------------
describe("filterToolsTable", () => {
    const f = () => win.filterToolsTable;

    function buildToolsTable(rows) {
        const table = doc.createElement("table");
        const tbody = doc.createElement("tbody");
        tbody.id = "tools-table-body";
        rows.forEach((cells) => {
            const tr = doc.createElement("tr");
            cells.forEach((text) => {
                const td = doc.createElement("td");
                td.textContent = text;
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        doc.body.appendChild(table);
        return tbody;
    }

    test("shows matching rows and hides non-matching", () => {
        // Columns: Actions(0), S.No.(1), Source(2), Name(3), ...
        const tbody = buildToolsTable([
            ["act", "1", "REST", "get-users", "GET", "Gets users", "", "", "", "", "Active"],
            ["act", "2", "MCP", "list-files", "POST", "Lists files", "", "", "", "", "Active"],
        ]);
        f()("get-users");
        const rows = tbody.querySelectorAll("tr");
        expect(rows[0].style.display).toBe("");
        expect(rows[1].style.display).toBe("none");
    });

    test("empty search shows all rows", () => {
        const tbody = buildToolsTable([
            ["act", "1", "REST", "tool-a", "GET", "desc", "", "", "", "", "Active"],
            ["act", "2", "MCP", "tool-b", "POST", "desc", "", "", "", "", "Active"],
        ]);
        f()("");
        const rows = tbody.querySelectorAll("tr");
        expect(rows[0].style.display).toBe("");
        expect(rows[1].style.display).toBe("");
    });

    test("no table does not throw", () => {
        expect(() => f()("anything")).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// filterResourcesTable
// ---------------------------------------------------------------------------
describe("filterResourcesTable", () => {
    const f = () => win.filterResourcesTable;

    function buildResourcesTable(rows) {
        const table = doc.createElement("table");
        const tbody = doc.createElement("tbody");
        tbody.id = "resources-table-body";
        rows.forEach((cells) => {
            const tr = doc.createElement("tr");
            cells.forEach((text) => {
                const td = doc.createElement("td");
                td.textContent = text;
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        doc.body.appendChild(table);
        return tbody;
    }

    test("shows matching rows and hides non-matching", () => {
        // Columns: Actions(0), Source(1), Name(2), ...
        const tbody = buildResourcesTable([
            ["act", "gateway-1", "config-file", "Configuration file", "prod", "admin", "team-a", "Active"],
            ["act", "gateway-2", "log-file", "Log file", "staging", "dev", "team-b", "Active"],
        ]);
        f()("config");
        const rows = tbody.querySelectorAll("tr");
        expect(rows[0].style.display).toBe("");
        expect(rows[1].style.display).toBe("none");
    });

    test("empty search shows all rows", () => {
        const tbody = buildResourcesTable([
            ["act", "gw", "res-a", "desc", "", "", "", ""],
            ["act", "gw", "res-b", "desc", "", "", "", ""],
        ]);
        f()("");
        const rows = tbody.querySelectorAll("tr");
        expect(rows[0].style.display).toBe("");
        expect(rows[1].style.display).toBe("");
    });

    test("no table does not throw", () => {
        expect(() => f()("anything")).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// filterPromptsTable
// ---------------------------------------------------------------------------
describe("filterPromptsTable", () => {
    const f = () => win.filterPromptsTable;

    function buildPromptsTable(rows) {
        const table = doc.createElement("table");
        const tbody = doc.createElement("tbody");
        tbody.id = "prompts-table-body";
        rows.forEach((cells) => {
            const tr = doc.createElement("tr");
            cells.forEach((text) => {
                const td = doc.createElement("td");
                td.textContent = text;
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        doc.body.appendChild(table);
        return tbody;
    }

    test("shows matching rows and hides non-matching", () => {
        // Columns: Actions(0), S.No.(1), GatewayName(2), Name(3), ...
        const tbody = buildPromptsTable([
            ["act", "1", "gw-1", "greeting-prompt", "A greeting", "tag-a", "owner", "team", "Active"],
            ["act", "2", "gw-2", "farewell-prompt", "A farewell", "tag-b", "owner", "team", "Active"],
        ]);
        f()("greeting");
        const rows = tbody.querySelectorAll("tr");
        expect(rows[0].style.display).toBe("");
        expect(rows[1].style.display).toBe("none");
    });

    test("empty search shows all rows", () => {
        const tbody = buildPromptsTable([
            ["act", "1", "gw", "p-a", "desc", "", "", "", ""],
            ["act", "2", "gw", "p-b", "desc", "", "", "", ""],
        ]);
        f()("");
        const rows = tbody.querySelectorAll("tr");
        expect(rows[0].style.display).toBe("");
        expect(rows[1].style.display).toBe("");
    });

    test("no table does not throw", () => {
        expect(() => f()("anything")).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// filterA2AAgentsTable
// ---------------------------------------------------------------------------
describe("filterA2AAgentsTable", () => {
    const f = () => win.filterA2AAgentsTable;

    function buildAgentsTable(rows, { usePanel = false } = {}) {
        const wrapper = doc.createElement("div");
        wrapper.id = usePanel ? "a2a-agents-panel" : "agents-table";
        const table = doc.createElement("table");
        const tbody = doc.createElement("tbody");
        rows.forEach((cells) => {
            const tr = doc.createElement("tr");
            cells.forEach((text) => {
                const td = doc.createElement("td");
                td.textContent = text;
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        wrapper.appendChild(table);
        doc.body.appendChild(wrapper);
        return tbody;
    }

    test("shows matching rows via #agents-table", () => {
        // Columns: Actions(0), ID(1), Name(2), ...
        const tbody = buildAgentsTable([
            ["act", "id-1", "Weather Agent", "Gets weather", "http://a", "tag", "type", "Active", "OK", "owner", "team", "public"],
            ["act", "id-2", "Search Agent", "Does search", "http://b", "tag", "type", "Active", "OK", "owner", "team", "public"],
        ]);
        f()("weather");
        const rows = tbody.querySelectorAll("tr");
        expect(rows[0].style.display).toBe("");
        expect(rows[1].style.display).toBe("none");
    });

    test("falls back to #a2a-agents-panel", () => {
        const tbody = buildAgentsTable(
            [["act", "id-1", "Fallback Agent", "desc", "http://c", "", "", "", "", "", "", ""]],
            { usePanel: true },
        );
        f()("fallback");
        expect(tbody.querySelector("tr").style.display).toBe("");
    });

    test("empty search shows all rows", () => {
        const tbody = buildAgentsTable([
            ["act", "id-1", "Agent A", "desc", "", "", "", "", "", "", "", ""],
            ["act", "id-2", "Agent B", "desc", "", "", "", "", "", "", "", ""],
        ]);
        f()("");
        const rows = tbody.querySelectorAll("tr");
        expect(rows[0].style.display).toBe("");
        expect(rows[1].style.display).toBe("");
    });

    test("no table does not throw", () => {
        expect(() => f()("anything")).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// filterGatewaysTable
// ---------------------------------------------------------------------------
describe("filterGatewaysTable", () => {
    const f = () => win.filterGatewaysTable;

    function buildGatewaysTable(rows, { enabledValues = [] } = {}) {
        const panel = doc.createElement("div");
        panel.id = "gateways-panel";
        const table = doc.createElement("table");
        const thead = doc.createElement("thead");
        const headerRow = doc.createElement("tr");
        ["actions", "s.no.", "name", "url", "tags", "status", "lastseen", "owner", "team", "visibility"].forEach((h) => {
            const th = doc.createElement("th");
            th.textContent = h;
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);
        const tbody = doc.createElement("tbody");
        rows.forEach((cells, i) => {
            const tr = doc.createElement("tr");
            if (enabledValues[i] !== undefined) {
                tr.setAttribute("data-enabled", enabledValues[i]);
            }
            cells.forEach((text) => {
                const td = doc.createElement("td");
                td.textContent = text;
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        panel.appendChild(table);
        doc.body.appendChild(panel);
        return tbody;
    }

    test("shows matching rows and hides non-matching (strategy 1: gateways-panel)", () => {
        const tbody = buildGatewaysTable([
            ["act", "1", "Server Alpha", "http://alpha.com", "prod", "Active", "now", "admin", "team-a", "public"],
            ["act", "2", "Server Beta", "http://beta.com", "staging", "Active", "now", "admin", "team-b", "public"],
        ]);
        f()("alpha");
        const rows = tbody.querySelectorAll("tr");
        expect(rows[0].style.display).not.toBe("none");
        expect(rows[1].style.display).toBe("none");
    });

    test("empty search shows all rows", () => {
        const tbody = buildGatewaysTable([
            ["act", "1", "Server A", "http://a.com", "", "Active", "", "", "", ""],
            ["act", "2", "Server B", "http://b.com", "", "Active", "", "", "", ""],
        ]);
        f()("");
        const rows = tbody.querySelectorAll("tr");
        expect(rows[0].style.display).not.toBe("none");
        expect(rows[1].style.display).not.toBe("none");
    });

    test("integrates inactive filter — hides disabled rows when checkbox unchecked", () => {
        // Create the inactive checkbox
        const cb = doc.createElement("input");
        cb.type = "checkbox";
        cb.id = "show-inactive-gateways";
        cb.checked = false;
        doc.body.appendChild(cb);

        const tbody = buildGatewaysTable(
            [
                ["act", "1", "Enabled GW", "http://a.com", "", "Active", "", "", "", ""],
                ["act", "2", "Disabled GW", "http://b.com", "", "Inactive", "", "", "", ""],
            ],
            { enabledValues: ["true", "false"] },
        );
        f()("");
        const rows = tbody.querySelectorAll("tr");
        expect(rows[0].style.display).not.toBe("none");
        expect(rows[1].style.display).toBe("none");
    });

    test("no table does not throw", () => {
        expect(() => f()("anything")).not.toThrow();
    });

    test("strategy 3: finds table by header matching", () => {
        // Build a table without gateways-panel, with matching headers
        const table = doc.createElement("table");
        const thead = doc.createElement("thead");
        const headerRow = doc.createElement("tr");
        ["actions", "s.no.", "name", "url", "tags", "status", "lastseen", "owner", "team", "visibility"].forEach((h) => {
            const th = doc.createElement("th");
            th.textContent = h;
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);

        const tbody = doc.createElement("tbody");
        const tr = doc.createElement("tr");
        tr.setAttribute("data-enabled", "true");
        ["act", "1", "Found Server", "http://found.com", "", "Active", "", "", "", ""].forEach((text) => {
            const td = doc.createElement("td");
            td.textContent = text;
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
        table.appendChild(tbody);
        doc.body.appendChild(table);

        f()("found");
        expect(tr.style.display).not.toBe("none");
    });
});

// ---------------------------------------------------------------------------
// addTagToFilter
// ---------------------------------------------------------------------------
describe("addTagToFilter", () => {
    const f = () => win.addTagToFilter;

    test("adds tag to empty filter input", () => {
        const input = doc.createElement("input");
        input.id = "tools-tag-filter";
        input.value = "";
        doc.body.appendChild(input);

        // Need the panel with tbody for filterEntitiesByTags to work
        const panel = doc.createElement("div");
        panel.id = "tools-panel";
        const table = doc.createElement("table");
        const tbody = doc.createElement("tbody");
        table.appendChild(tbody);
        panel.appendChild(table);
        doc.body.appendChild(panel);

        f()("tools", "production");
        expect(input.value).toBe("production");
    });

    test("appends tag to existing tags", () => {
        const input = doc.createElement("input");
        input.id = "tools-tag-filter";
        input.value = "staging";
        doc.body.appendChild(input);

        const panel = doc.createElement("div");
        panel.id = "tools-panel";
        const table = doc.createElement("table");
        table.appendChild(doc.createElement("tbody"));
        panel.appendChild(table);
        doc.body.appendChild(panel);

        f()("tools", "production");
        expect(input.value).toContain("staging");
        expect(input.value).toContain("production");
    });

    test("does not add duplicate tag", () => {
        const input = doc.createElement("input");
        input.id = "tools-tag-filter";
        input.value = "production";
        doc.body.appendChild(input);

        const panel = doc.createElement("div");
        panel.id = "tools-panel";
        const table = doc.createElement("table");
        table.appendChild(doc.createElement("tbody"));
        panel.appendChild(table);
        doc.body.appendChild(panel);

        f()("tools", "production");
        // Should still just be "production" (not duplicated)
        const tags = input.value.split(",").map((t) => t.trim()).filter((t) => t);
        expect(tags.filter((t) => t === "production")).toHaveLength(1);
    });

    test("no filter input does not throw", () => {
        expect(() => f()("nonexistent", "tag")).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// filterEntitiesByTags
// ---------------------------------------------------------------------------
describe("filterEntitiesByTags", () => {
    const f = () => win.filterEntitiesByTags;

    function buildTaggedTable(entityType, rows) {
        const panel = doc.createElement("div");
        panel.id = `${entityType}-panel`;
        const table = doc.createElement("table");
        const tbody = doc.createElement("tbody");
        rows.forEach(({ text, tags }) => {
            const tr = doc.createElement("tr");
            const td = doc.createElement("td");
            td.textContent = text;
            tr.appendChild(td);
            // Add tag spans
            const tagTd = doc.createElement("td");
            tags.forEach((tag) => {
                const span = doc.createElement("span");
                span.className = "inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full";
                span.textContent = tag;
                tagTd.appendChild(span);
            });
            tr.appendChild(tagTd);
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        panel.appendChild(table);
        doc.body.appendChild(panel);
        return tbody;
    }

    // NOTE: Tests with non-empty filter tags are skipped because
    // filterEntitiesByTags uses CSS comments (/* ... */) in its
    // querySelectorAll selector, which JSDOM's nwsapi cannot parse.

    test("empty filter shows all rows", () => {
        const tbody = buildTaggedTable("tools", [
            { text: "Tool A", tags: ["production"] },
            { text: "Tool B", tags: ["staging"] },
        ]);
        f()("tools", "");
        const rows = tbody.querySelectorAll("tr");
        expect(rows[0].style.display).toBe("");
        expect(rows[1].style.display).toBe("");
    });

    test("whitespace-only filter shows all rows", () => {
        const tbody = buildTaggedTable("tools", [
            { text: "Tool A", tags: ["production"] },
        ]);
        f()("tools", "  ,  , ");
        const rows = tbody.querySelectorAll("tr");
        expect(rows[0].style.display).toBe("");
    });

    test("no matching panel does not throw", () => {
        expect(() => f()("nonexistent", "tag")).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// clearTagFilter
// ---------------------------------------------------------------------------
describe("clearTagFilter", () => {
    const f = () => win.clearTagFilter;

    test("clears filter input and shows all rows", () => {
        const input = doc.createElement("input");
        input.id = "tools-tag-filter";
        input.value = "production";
        doc.body.appendChild(input);

        // Build a panel with rows to verify they become visible
        const panel = doc.createElement("div");
        panel.id = "tools-panel";
        const table = doc.createElement("table");
        const tbody = doc.createElement("tbody");
        const tr = doc.createElement("tr");
        tr.style.display = "none";
        const td = doc.createElement("td");
        td.textContent = "Tool";
        tr.appendChild(td);
        tbody.appendChild(tr);
        table.appendChild(tbody);
        panel.appendChild(table);
        doc.body.appendChild(panel);

        f()("tools");
        expect(input.value).toBe("");
        expect(tr.style.display).toBe("");
    });

    test("no filter input does not throw", () => {
        expect(() => f()("nonexistent")).not.toThrow();
    });
});
