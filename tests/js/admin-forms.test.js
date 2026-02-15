/**
 * Unit tests for admin.js form generation and schema functions.
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
// generateSchema
// ---------------------------------------------------------------------------
describe("generateSchema", () => {
    const f = () => win.generateSchema;

    function setupParams(params) {
        // Mutate the existing AppState (const in closure scope, shared via window)
        win.AppState.parameterCount = params.length;

        params.forEach((p, i) => {
            const idx = i + 1;
            const nameInput = doc.createElement("input");
            nameInput.name = `param_name_${idx}`;
            nameInput.value = p.name;
            doc.body.appendChild(nameInput);

            const typeSelect = doc.createElement("select");
            typeSelect.name = `param_type_${idx}`;
            const opt = doc.createElement("option");
            opt.value = p.type || "string";
            opt.selected = true;
            typeSelect.appendChild(opt);
            doc.body.appendChild(typeSelect);

            const descInput = doc.createElement("input");
            descInput.name = `param_description_${idx}`;
            descInput.value = p.description || "";
            doc.body.appendChild(descInput);

            const reqCheckbox = doc.createElement("input");
            reqCheckbox.type = "checkbox";
            reqCheckbox.name = `param_required_${idx}`;
            reqCheckbox.checked = p.required || false;
            doc.body.appendChild(reqCheckbox);
        });
    }

    test("generates JSON schema from form parameters", () => {
        setupParams([
            { name: "query", type: "string", description: "Search query", required: true },
            { name: "limit", type: "integer", description: "Max results", required: false },
        ]);
        const result = JSON.parse(f()());
        expect(result.title).toBe("CustomInputSchema");
        expect(result.type).toBe("object");
        expect(result.properties.query).toEqual({ type: "string", description: "Search query" });
        expect(result.properties.limit).toEqual({ type: "integer", description: "Max results" });
        expect(result.required).toContain("query");
        expect(result.required).not.toContain("limit");
    });

    test("returns empty schema when no parameters", () => {
        setupParams([]);
        const result = JSON.parse(f()());
        expect(result.properties).toEqual({});
        expect(result.required).toEqual([]);
    });

    test("skips parameters with empty names", () => {
        setupParams([
            { name: "", type: "string", description: "empty name" },
            { name: "valid", type: "string", description: "valid param" },
        ]);
        const result = JSON.parse(f()());
        expect(result.properties.valid).toBeDefined();
        expect(Object.keys(result.properties)).toHaveLength(1);
    });

    test("returns valid JSON string", () => {
        setupParams([{ name: "test", type: "string" }]);
        const result = f()();
        expect(() => JSON.parse(result)).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// updateRequestTypeOptions
// ---------------------------------------------------------------------------
describe("updateRequestTypeOptions", () => {
    const f = () => win.updateRequestTypeOptions;

    function setupRequestTypeDOM(integrationType) {
        const requestTypeSelect = doc.createElement("select");
        requestTypeSelect.id = "requestType";
        doc.body.appendChild(requestTypeSelect);

        const integrationTypeSelect = doc.createElement("select");
        integrationTypeSelect.id = "integrationType";
        const opt = doc.createElement("option");
        opt.value = integrationType;
        opt.selected = true;
        integrationTypeSelect.appendChild(opt);
        doc.body.appendChild(integrationTypeSelect);

        return requestTypeSelect;
    }

    test("populates options for REST integration", () => {
        const select = setupRequestTypeDOM("REST");
        f()();
        const options = Array.from(select.options).map((o) => o.value);
        expect(options).toContain("GET");
        expect(options).toContain("POST");
        expect(options).toContain("PUT");
        expect(options).toContain("PATCH");
        expect(options).toContain("DELETE");
    });

    test("clears options for MCP integration", () => {
        const select = setupRequestTypeDOM("MCP");
        f()();
        expect(select.options.length).toBe(0);
    });

    test("sets preselected value", () => {
        const select = setupRequestTypeDOM("REST");
        f()("PUT");
        expect(select.value).toBe("PUT");
    });

    test("ignores invalid preselected value", () => {
        const select = setupRequestTypeDOM("REST");
        f()("INVALID");
        // Should still have options but value won't be INVALID
        expect(select.options.length).toBeGreaterThan(0);
    });

    test("does not throw when elements missing", () => {
        expect(() => f()()).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// updateEditToolRequestTypes
// ---------------------------------------------------------------------------
describe("updateEditToolRequestTypes", () => {
    const f = () => win.updateEditToolRequestTypes;

    function setupEditToolDOM(integrationType) {
        const typeSelect = doc.createElement("select");
        typeSelect.id = "edit-tool-type";
        const opt = doc.createElement("option");
        opt.value = integrationType;
        opt.selected = true;
        typeSelect.appendChild(opt);
        doc.body.appendChild(typeSelect);

        const requestTypeSelect = doc.createElement("select");
        requestTypeSelect.id = "edit-tool-request-type";
        doc.body.appendChild(requestTypeSelect);

        return { typeSelect, requestTypeSelect };
    }

    test("populates options for REST type", () => {
        const { requestTypeSelect } = setupEditToolDOM("REST");
        f()();
        const options = Array.from(requestTypeSelect.options).map((o) => o.value);
        expect(options).toContain("GET");
        expect(options).toContain("POST");
        expect(requestTypeSelect.disabled).toBe(false);
    });

    test("clears and disables for MCP type", () => {
        const { requestTypeSelect } = setupEditToolDOM("MCP");
        f()();
        expect(requestTypeSelect.options.length).toBe(0);
        expect(requestTypeSelect.disabled).toBe(true);
    });

    test("sets selected method when provided", () => {
        const { requestTypeSelect } = setupEditToolDOM("REST");
        f()("DELETE");
        expect(requestTypeSelect.value).toBe("DELETE");
    });

    test("does not set invalid method", () => {
        const { requestTypeSelect } = setupEditToolDOM("REST");
        f()("INVALID");
        // Value should be first option (GET) since INVALID is not in list
        expect(requestTypeSelect.value).toBe("GET");
    });

    test("does not throw when elements missing", () => {
        expect(() => f()()).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// cleanUpUrlParamsForTab
// ---------------------------------------------------------------------------
describe("cleanUpUrlParamsForTab", () => {
    const f = () => win.cleanUpUrlParamsForTab;

    test("preserves only params for the target tab's tables", () => {
        // Set up a panel with pagination controls
        const panel = doc.createElement("div");
        panel.id = "tools-panel";
        const ctrl = doc.createElement("div");
        ctrl.id = "tools-pagination-controls";
        panel.appendChild(ctrl);
        doc.body.appendChild(panel);

        // Mock safeReplaceState to capture the URL
        let capturedUrl = null;
        win.safeReplaceState = (state, title, url) => {
            capturedUrl = url;
        };

        // Set window.location to have mixed params
        // JSDOM location is http://localhost
        const url = new win.URL(win.location.href);
        url.searchParams.set("tools_page", "2");
        url.searchParams.set("servers_page", "3");
        url.searchParams.set("team_id", "team-123");
        win.history.replaceState({}, "", url.toString());

        f()("tools");

        expect(capturedUrl).toContain("tools_page=2");
        expect(capturedUrl).toContain("team_id=team-123");
        expect(capturedUrl).not.toContain("servers_page");
    });

    test("preserves team_id as global param", () => {
        const panel = doc.createElement("div");
        panel.id = "overview-panel";
        doc.body.appendChild(panel);

        let capturedUrl = null;
        win.safeReplaceState = (state, title, url) => {
            capturedUrl = url;
        };

        const url = new win.URL(win.location.href);
        url.searchParams.set("team_id", "my-team");
        win.history.replaceState({}, "", url.toString());

        f()("overview");

        expect(capturedUrl).toContain("team_id=my-team");
    });

    test("removes all non-matching params", () => {
        const panel = doc.createElement("div");
        panel.id = "gateways-panel";
        const ctrl = doc.createElement("div");
        ctrl.id = "gateways-pagination-controls";
        panel.appendChild(ctrl);
        doc.body.appendChild(panel);

        let capturedUrl = null;
        win.safeReplaceState = (state, title, url) => {
            capturedUrl = url;
        };

        const url = new win.URL(win.location.href);
        url.searchParams.set("tools_page", "1");
        url.searchParams.set("resources_page", "2");
        win.history.replaceState({}, "", url.toString());

        f()("gateways");

        expect(capturedUrl).not.toContain("tools_page");
        expect(capturedUrl).not.toContain("resources_page");
    });
});
