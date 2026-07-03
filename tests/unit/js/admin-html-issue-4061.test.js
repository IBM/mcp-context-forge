/**
 * Unit tests for HTML structure changes in issue #4061.
 *
 * Tests verify that the edit tool form contains all required advanced
 * configuration fields with correct attributes and does NOT contain
 * the removed gateway_id field.
 */

import { describe, test, expect, beforeEach } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";
import { JSDOM } from "jsdom";

let adminHTML;
let dom;
let document;

beforeEach(() => {
  // Load the actual admin.html file
  const htmlPath = join(process.cwd(), "mcpgateway", "templates", "admin.html");
  adminHTML = readFileSync(htmlPath, "utf-8");
  dom = new JSDOM(adminHTML);
  document = dom.window.document;
});

// ---------------------------------------------------------------------------
// Issue #4061: Advanced Configuration Field Presence in HTML
// ---------------------------------------------------------------------------
describe("Issue #4061: Advanced Configuration Field Presence in HTML", () => {
  test("edit tool form contains title field with correct attributes", () => {
    const titleField = document.getElementById("edit-tool-title");

    expect(titleField).not.toBeNull();
    expect(titleField.tagName).toBe("INPUT");
    expect(titleField.getAttribute("name")).toBe("title");
    expect(titleField.getAttribute("type")).toBe("text");
    expect(titleField.getAttribute("maxlength")).toBe("255");
    expect(titleField.getAttribute("placeholder")).toContain("Human-readable title");
  });

  test("edit tool form contains timeout_ms field with correct attributes", () => {
    const timeoutField = document.getElementById("edit-tool-timeout-ms");

    expect(timeoutField).not.toBeNull();
    expect(timeoutField.tagName).toBe("INPUT");
    expect(timeoutField.getAttribute("name")).toBe("timeout_ms");
    expect(timeoutField.getAttribute("type")).toBe("number");
    expect(timeoutField.getAttribute("min")).toBe("1");
    expect(timeoutField.getAttribute("placeholder")).toContain("milliseconds");
  });

  test("edit tool form contains jsonpath_filter field with correct attributes", () => {
    const jsonpathField = document.getElementById("edit-tool-jsonpath-filter");

    expect(jsonpathField).not.toBeNull();
    expect(jsonpathField.tagName).toBe("INPUT");
    expect(jsonpathField.getAttribute("name")).toBe("jsonpath_filter");
    expect(jsonpathField.getAttribute("type")).toBe("text");
    expect(jsonpathField.getAttribute("placeholder")).toContain("$.data");
  });

  test("edit tool form contains team_id field with correct attributes", () => {
    const teamField = document.getElementById("edit-tool-team-id");

    expect(teamField).not.toBeNull();
    expect(teamField.tagName).toBe("SELECT");
    expect(teamField.getAttribute("name")).toBe("team_id");

    // Check for "No Team" option
    const noTeamOption = teamField.querySelector('option[value=""]');
    expect(noTeamOption).not.toBeNull();
    expect(noTeamOption.textContent).toContain("No Team");
  });

  test("edit tool form contains REST passthrough button", () => {
    const buttonWrapper = document.getElementById("edit-tool-rest-passthrough-button-wrapper");
    const button = document.getElementById("edit-tool-passthrough-btn");

    expect(buttonWrapper).not.toBeNull();
    expect(button).not.toBeNull();
    expect(button.textContent).toContain("Add Passthrough");

    // Button wrapper should be hidden by default
    expect(buttonWrapper.getAttribute("style")).toContain("display: none");
  });

  test("edit tool form contains REST passthrough container with all fields", () => {
    const container = document.getElementById("edit-tool-passthrough-container");

    expect(container).not.toBeNull();
    expect(container.tagName).toBe("FIELDSET");

    // Container should be hidden by default
    expect(container.getAttribute("style")).toContain("display: none");

    // Check for legend
    const legend = container.querySelector("legend");
    expect(legend).not.toBeNull();
    expect(legend.textContent).toContain("REST Passthrough Configuration");
  });

  test("REST passthrough container contains base_url field", () => {
    const baseUrlField = document.getElementById("edit-tool-base-url");

    expect(baseUrlField).not.toBeNull();
    expect(baseUrlField.tagName).toBe("INPUT");
    expect(baseUrlField.getAttribute("name")).toBe("base_url");
    expect(baseUrlField.getAttribute("type")).toBe("url");
    expect(baseUrlField.getAttribute("placeholder")).toContain("https://");
  });

  test("REST passthrough container contains path_template field", () => {
    const pathField = document.getElementById("edit-tool-path-template");

    expect(pathField).not.toBeNull();
    expect(pathField.tagName).toBe("INPUT");
    expect(pathField.getAttribute("name")).toBe("path_template");
    expect(pathField.getAttribute("type")).toBe("text");
    expect(pathField.getAttribute("placeholder")).toContain("/api");
  });

  test("REST passthrough container contains query_mapping textarea", () => {
    const queryField = document.getElementById("edit-tool-query-mapping");

    expect(queryField).not.toBeNull();
    expect(queryField.tagName).toBe("TEXTAREA");
    expect(queryField.getAttribute("name")).toBe("query_mapping");
    expect(queryField.getAttribute("rows")).toBe("3");
    expect(queryField.getAttribute("placeholder")).toContain('{"param"');
  });

  test("REST passthrough container contains header_mapping textarea", () => {
    const headerField = document.getElementById("edit-tool-header-mapping");

    expect(headerField).not.toBeNull();
    expect(headerField.tagName).toBe("TEXTAREA");
    expect(headerField.getAttribute("name")).toBe("header_mapping");
    expect(headerField.getAttribute("rows")).toBe("3");
  });

  test("REST passthrough container contains expose_passthrough checkbox", () => {
    const exposeField = document.getElementById("edit-tool-expose-passthrough");

    expect(exposeField).not.toBeNull();
    expect(exposeField.tagName).toBe("INPUT");
    expect(exposeField.getAttribute("name")).toBe("expose_passthrough");
    expect(exposeField.getAttribute("type")).toBe("checkbox");

    // Check for associated label
    const label = document.querySelector('label[for="edit-tool-expose-passthrough"]');
    expect(label).not.toBeNull();
    expect(label.textContent).toContain("Expose");
  });

  test("REST passthrough container contains allowlist text input", () => {
    const allowlistField = document.getElementById("edit-tool-allowlist");

    expect(allowlistField).not.toBeNull();
    expect(allowlistField.tagName).toBe("INPUT");
    expect(allowlistField.getAttribute("name")).toBe("allowlist");
    expect(allowlistField.getAttribute("type")).toBe("text");
    expect(allowlistField.getAttribute("placeholder")).toContain("api.example.com");
  });

  test("edit tool form contains plugin section with pre and post chain fields", () => {
    const pluginSection = document.getElementById("edit-tool-plugin-section");

    expect(pluginSection).not.toBeNull();

    // Plugin section should be hidden by default
    expect(pluginSection.getAttribute("style")).toContain("display: none");

    // Check plugin_chain_pre
    const preChainField = document.getElementById("edit-tool-plugin-chain-pre");
    expect(preChainField).not.toBeNull();
    expect(preChainField.tagName).toBe("INPUT");
    expect(preChainField.getAttribute("name")).toBe("plugin_chain_pre");
    expect(preChainField.getAttribute("type")).toBe("text");

    // Check plugin_chain_post
    const postChainField = document.getElementById("edit-tool-plugin-chain-post");
    expect(postChainField).not.toBeNull();
    expect(postChainField.tagName).toBe("INPUT");
    expect(postChainField.getAttribute("name")).toBe("plugin_chain_post");
    expect(postChainField.getAttribute("type")).toBe("text");
  });

  test("all advanced field IDs follow edit-tool-* naming convention", () => {
    const expectedIds = [
      "edit-tool-title",
      "edit-tool-timeout-ms",
      "edit-tool-jsonpath-filter",
      "edit-tool-team-id",
      "edit-tool-passthrough-btn",
      "edit-tool-base-url",
      "edit-tool-path-template",
      "edit-tool-query-mapping",
      "edit-tool-header-mapping",
      "edit-tool-expose-passthrough",
      "edit-tool-allowlist",
      "edit-tool-plugin-chain-pre",
      "edit-tool-plugin-chain-post",
    ];

    expectedIds.forEach(id => {
      const element = document.getElementById(id);
      expect(element).not.toBeNull();
      expect(id).toMatch(/^edit-tool-[a-z0-9-]+$/);
    });
  });

  test("all advanced field names use snake_case not camelCase", () => {
    const expectedNames = [
      "title",
      "timeout_ms",
      "jsonpath_filter",
      "team_id",
      "base_url",
      "path_template",
      "query_mapping",
      "header_mapping",
      "expose_passthrough",
      "allowlist",
      "plugin_chain_pre",
      "plugin_chain_post",
    ];

    expectedNames.forEach(name => {
      const element = document.querySelector(`[name="${name}"]`);
      expect(element).not.toBeNull();

      // Verify it's snake_case (no camelCase)
      expect(name).not.toMatch(/[A-Z]/);
      if (name.includes("_")) {
        expect(name).toMatch(/^[a-z0-9]+(_[a-z0-9]+)*$/);
      }
    });
  });
});

// ---------------------------------------------------------------------------
// Issue #4061: Gateway Field Removal from HTML
// ---------------------------------------------------------------------------
describe("Issue #4061: Gateway Field Removal from HTML", () => {
  test("edit tool form does NOT contain gateway_id field by ID", () => {
    const gatewayField = document.getElementById("edit-tool-gateway-id");
    expect(gatewayField).toBeNull();
  });

  test("edit tool form does NOT contain gateway_id field by name", () => {
    const gatewayFields = document.querySelectorAll('[name="gateway_id"]');
    expect(gatewayFields.length).toBe(0);
  });

  test("edit tool form does NOT contain gateway field in modal", () => {
    // Check within edit-tool-modal if it exists
    const modal = document.getElementById("edit-tool-modal");

    if (modal) {
      const gatewayInModal = modal.querySelector('[name="gateway_id"]');
      expect(gatewayInModal).toBeNull();

      const gatewayByIdInModal = modal.querySelector('#edit-tool-gateway-id');
      expect(gatewayByIdInModal).toBeNull();
    }
  });

  test("HTML does not reference gateway reassignment in edit tool section", () => {
    // Find the edit tool form section
    const editForm = document.getElementById("edit-tool-form");

    if (editForm) {
      const formHTML = editForm.innerHTML.toLowerCase();

      // Should not contain references to gateway reassignment
      expect(formHTML).not.toContain("reassign to gateway");
      expect(formHTML).not.toContain("gateway reassignment");
      expect(formHTML).not.toContain("change gateway");
    }
  });

  test("edit tool modal contains advanced fields but NOT gateway_id", () => {
    const modal = document.getElementById("edit-tool-modal");

    if (modal) {
      // Should have advanced fields
      expect(modal.querySelector('#edit-tool-title')).not.toBeNull();
      expect(modal.querySelector('#edit-tool-timeout-ms')).not.toBeNull();
      expect(modal.querySelector('#edit-tool-jsonpath-filter')).not.toBeNull();
      expect(modal.querySelector('#edit-tool-team-id')).not.toBeNull();

      // Should NOT have gateway field
      expect(modal.querySelector('[name="gateway_id"]')).toBeNull();
      expect(modal.querySelector('#edit-tool-gateway-id')).toBeNull();
    }
  });
});

// ---------------------------------------------------------------------------
// Issue #4061: Field Label and Help Text Validation
// ---------------------------------------------------------------------------
describe("Issue #4061: Field Label and Help Text Validation", () => {
  test("title field has appropriate label and help text", () => {
    const titleField = document.getElementById("edit-tool-title");
    const label = titleField.closest("div").querySelector("label");
    const helpText = titleField.closest("div").querySelector("p");

    expect(label).not.toBeNull();
    expect(label.textContent).toContain("Title");
    expect(helpText).not.toBeNull();
    expect(helpText.textContent).toContain("MCP BaseMetadata");
  });

  test("timeout_ms field has appropriate label and help text", () => {
    const timeoutField = document.getElementById("edit-tool-timeout-ms");
    const label = timeoutField.closest("div").querySelector("label");
    const helpText = timeoutField.closest("div").querySelector("p");

    expect(label).not.toBeNull();
    expect(label.textContent).toContain("Timeout");
    expect(helpText).not.toBeNull();
    expect(helpText.textContent).toContain("Leave empty to use global default");
  });

  test("jsonpath_filter field has appropriate label and help text", () => {
    const jsonpathField = document.getElementById("edit-tool-jsonpath-filter");
    const label = jsonpathField.closest("div").querySelector("label");
    const helpText = jsonpathField.closest("div").querySelector("p");

    expect(label).not.toBeNull();
    expect(label.textContent).toContain("JSONPath");
    expect(helpText).not.toBeNull();
    expect(helpText.textContent).toContain("JSONPath expression");
  });

  test("team_id field has appropriate label and help text", () => {
    const teamField = document.getElementById("edit-tool-team-id");
    const label = teamField.closest("div").querySelector("label");
    const helpText = teamField.closest("div").querySelector("p");

    expect(label).not.toBeNull();
    expect(label.textContent).toContain("Team");
    expect(helpText).not.toBeNull();
    expect(helpText.textContent).toContain("Reassign this tool");
  });

  test("REST passthrough fields have appropriate labels and help text", () => {
    // Base URL
    const baseUrlField = document.getElementById("edit-tool-base-url");
    const baseUrlLabel = baseUrlField.closest("div").querySelector("label");
    const baseUrlHelp = baseUrlField.closest("div").querySelector("p");

    expect(baseUrlLabel.textContent).toContain("Base URL");
    expect(baseUrlHelp.textContent).toContain("must include scheme and host");

    // Path Template
    const pathField = document.getElementById("edit-tool-path-template");
    const pathLabel = pathField.closest("div").querySelector("label");
    const pathHelp = pathField.closest("div").querySelector("p");

    expect(pathLabel.textContent).toContain("Path Template");
    expect(pathHelp.textContent).toContain("must start with '/'");

    // Query Mapping
    const queryField = document.getElementById("edit-tool-query-mapping");
    const queryLabel = queryField.closest("div").querySelector("label");
    const queryHelp = queryField.closest("div").querySelector("p");

    expect(queryLabel.textContent).toContain("Query Mapping");
    expect(queryHelp.textContent).toContain("JSON object");

    // Header Mapping
    const headerField = document.getElementById("edit-tool-header-mapping");
    const headerLabel = headerField.closest("div").querySelector("label");

    expect(headerLabel.textContent).toContain("Header Mapping");
  });

  test("plugin chain fields have appropriate labels", () => {
    const preChainField = document.getElementById("edit-tool-plugin-chain-pre");
    const preChainLabel = preChainField.closest("div").querySelector("label");

    expect(preChainLabel).not.toBeNull();
    expect(preChainLabel.textContent).toContain("Pre-processing Plugins");

    const postChainField = document.getElementById("edit-tool-plugin-chain-post");
    const postChainLabel = postChainField.closest("div").querySelector("label");

    expect(postChainLabel).not.toBeNull();
    expect(postChainLabel.textContent).toContain("Post-processing Plugins");
  });
});
