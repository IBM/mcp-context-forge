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

// ---------------------------------------------------------------------------
// toggleServerCodeExecutionSection
// ---------------------------------------------------------------------------
describe("toggleServerCodeExecutionSection", () => {
    const f = () => win.toggleServerCodeExecutionSection;

    test("shows create code execution section when server type is code_execution", () => {
        const select = doc.createElement("select");
        select.id = "server-type";
        select.name = "server_type";
        select.innerHTML = `
            <option value="standard">standard</option>
            <option value="code_execution">code_execution</option>
        `;
        select.value = "code_execution";
        doc.body.appendChild(select);

        const section = doc.createElement("div");
        section.id = "server-code-execution-section";
        section.className = "hidden";
        doc.body.appendChild(section);

        f()("create");

        expect(section.classList.contains("hidden")).toBe(false);
    });

    test("hides create code execution section when server type is standard", () => {
        const select = doc.createElement("select");
        select.id = "server-type";
        select.name = "server_type";
        select.innerHTML = `
            <option value="standard">standard</option>
            <option value="code_execution">code_execution</option>
        `;
        select.value = "standard";
        doc.body.appendChild(select);

        const section = doc.createElement("div");
        section.id = "server-code-execution-section";
        section.className = "hidden";
        doc.body.appendChild(section);

        f()("create");

        expect(section.classList.contains("hidden")).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// applyCodeExecutionFieldTemplate
// ---------------------------------------------------------------------------
describe("applyCodeExecutionFieldTemplate", () => {
    const f = () => win.applyCodeExecutionFieldTemplate;

    test("applies JSON template to a plain textarea", () => {
        const field = doc.createElement("textarea");
        field.id = "server-sandbox-policy";
        doc.body.appendChild(field);

        f()("server-sandbox-policy", "sandbox_policy");

        const parsed = JSON.parse(field.value);
        expect(parsed.runtime).toBe("deno");
        expect(parsed.max_execution_time_ms).toBe(30000);
        expect(parsed.allow_raw_http).toBe(false);
    });

    test("applies template to CodeMirror-backed textarea and keeps it focused", () => {
        const field = doc.createElement("textarea");
        field.id = "server-mount-rules";

        let value = "";
        let focused = false;
        let cursorSet = false;
        let refreshed = false;

        field.CodeMirror = {
            getValue: () => value,
            setValue: (nextValue) => {
                value = nextValue;
            },
            focus: () => {
                focused = true;
            },
            lineCount: () => 1,
            getLine: () => value,
            setCursor: () => {
                cursorSet = true;
            },
            refresh: () => {
                refreshed = true;
            },
        };

        doc.body.appendChild(field);
        f()("server-mount-rules", "mount_rules");

        const parsed = JSON.parse(value);
        expect(parsed.include_tags).toEqual(["prod"]);
        expect(focused).toBe(true);
        expect(cursorSet).toBe(true);
        expect(refreshed).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// previewCreateVirtualServer
// ---------------------------------------------------------------------------
describe("previewCreateVirtualServer", () => {
    const f = () => win.previewCreateVirtualServer;

    function setupPreviewDom() {
        const form = doc.createElement("form");
        form.id = "add-server-form";

        const name = doc.createElement("input");
        name.name = "name";
        name.value = "Code Exec Server";
        form.appendChild(name);

        const description = doc.createElement("textarea");
        description.name = "description";
        description.value = "preview description";
        form.appendChild(description);

        const icon = doc.createElement("input");
        icon.name = "icon";
        icon.value = "https://example.com/icon.png";
        form.appendChild(icon);

        const tags = doc.createElement("input");
        tags.name = "tags";
        tags.value = "prod, code-exec";
        form.appendChild(tags);

        const visibilityPublic = doc.createElement("input");
        visibilityPublic.type = "radio";
        visibilityPublic.name = "visibility";
        visibilityPublic.value = "public";
        visibilityPublic.checked = true;
        form.appendChild(visibilityPublic);

        const serverType = doc.createElement("select");
        serverType.id = "server-type";
        serverType.name = "server_type";
        serverType.innerHTML = `
            <option value="standard">standard</option>
            <option value="code_execution">code_execution</option>
        `;
        serverType.value = "code_execution";
        form.appendChild(serverType);

        const stubLanguage = doc.createElement("select");
        stubLanguage.name = "stub_language";
        stubLanguage.innerHTML = `
            <option value="">Auto</option>
            <option value="typescript">typescript</option>
        `;
        stubLanguage.value = "typescript";
        form.appendChild(stubLanguage);

        const skillsScope = doc.createElement("input");
        skillsScope.name = "skills_scope";
        skillsScope.value = "team:team-1";
        form.appendChild(skillsScope);

        const skillsRequireApproval = doc.createElement("input");
        skillsRequireApproval.type = "checkbox";
        skillsRequireApproval.name = "skills_require_approval";
        skillsRequireApproval.checked = true;
        form.appendChild(skillsRequireApproval);

        const mountRules = doc.createElement("textarea");
        mountRules.name = "mount_rules";
        mountRules.value = '{"include_tags":["prod"]}';
        form.appendChild(mountRules);

        const sandboxPolicy = doc.createElement("textarea");
        sandboxPolicy.name = "sandbox_policy";
        sandboxPolicy.value = '{"runtime":"deno"}';
        form.appendChild(sandboxPolicy);

        const tokenization = doc.createElement("textarea");
        tokenization.name = "tokenization";
        tokenization.value = '{"enabled":true}';
        form.appendChild(tokenization);

        const associatedTool = doc.createElement("input");
        associatedTool.type = "checkbox";
        associatedTool.name = "associatedTools";
        associatedTool.value = "tool-1";
        associatedTool.checked = true;
        form.appendChild(associatedTool);

        const associatedResource = doc.createElement("input");
        associatedResource.type = "checkbox";
        associatedResource.name = "associatedResources";
        associatedResource.value = "resource-1";
        associatedResource.checked = true;
        form.appendChild(associatedResource);

        const associatedPrompt = doc.createElement("input");
        associatedPrompt.type = "checkbox";
        associatedPrompt.name = "associatedPrompts";
        associatedPrompt.value = "prompt-1";
        associatedPrompt.checked = true;
        form.appendChild(associatedPrompt);

        doc.body.appendChild(form);

        const toolsContainer = doc.createElement("div");
        toolsContainer.id = "associatedTools";
        toolsContainer.setAttribute("data-selected-tools", '["tool-2"]');
        doc.body.appendChild(toolsContainer);

        const resourcesContainer = doc.createElement("div");
        resourcesContainer.id = "associatedResources";
        resourcesContainer.setAttribute(
            "data-selected-resources",
            '["resource-2"]',
        );
        doc.body.appendChild(resourcesContainer);

        const promptsContainer = doc.createElement("div");
        promptsContainer.id = "associatedPrompts";
        promptsContainer.setAttribute("data-selected-prompts", '["prompt-2"]');
        doc.body.appendChild(promptsContainer);

        const previewContainer = doc.createElement("div");
        previewContainer.id = "server-preview-container";
        previewContainer.className = "hidden";
        doc.body.appendChild(previewContainer);

        const previewError = doc.createElement("p");
        previewError.id = "server-preview-error";
        previewError.className = "hidden";
        previewContainer.appendChild(previewError);

        const previewJson = doc.createElement("pre");
        previewJson.id = "server-preview-json";
        previewContainer.appendChild(previewJson);

        return { mountRules, previewContainer, previewError, previewJson };
    }

    test("renders server payload preview from add server form", () => {
        const { previewContainer, previewJson } = setupPreviewDom();
        f()();

        expect(previewContainer.classList.contains("hidden")).toBe(false);
        const payload = JSON.parse(previewJson.textContent);
        expect(payload.name).toBe("Code Exec Server");
        expect(payload.server_type).toBe("code_execution");
        expect(payload.associated_tools).toEqual(
            expect.arrayContaining(["tool-1", "tool-2"]),
        );
        expect(payload.associated_resources).toEqual(
            expect.arrayContaining(["resource-1", "resource-2"]),
        );
        expect(payload.associated_prompts).toEqual(
            expect.arrayContaining(["prompt-1", "prompt-2"]),
        );
        expect(payload.stub_language).toBe("typescript");
        expect(payload.skills_scope).toBe("team:team-1");
        expect(payload.skills_require_approval).toBe(true);
        expect(payload.mount_rules).toEqual({ include_tags: ["prod"] });
        expect(payload.sandbox_policy).toEqual({ runtime: "deno" });
        expect(payload.tokenization).toEqual({ enabled: true });
    });

    test("shows preview validation error for invalid JSON policy fields", () => {
        const { mountRules, previewError } = setupPreviewDom();
        mountRules.value = "{";

        f()();

        expect(previewError.classList.contains("hidden")).toBe(false);
        expect(previewError.textContent).toContain("Mount Rules");
    });
});
