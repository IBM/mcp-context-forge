/**
 * Unit tests for formSubmitHandlers.js module
 * Tests: handleGatewayFormSubmit, handleResourceFormSubmit, handlePromptFormSubmit,
 *        handleEditPromptFormSubmit, handleServerFormSubmit, handleA2AFormSubmit,
 *        handleToolFormSubmit, handleEditToolFormSubmit, handleEditGatewayFormSubmit,
 *        handleEditA2AAgentFormSubmit, handleEditServerFormSubmit, handleEditResFormSubmit
 */

import { describe, test, expect, vi, afterEach, beforeEach } from "vitest";

import {
  handleGatewayFormSubmit,
  handleResourceFormSubmit,
  handlePromptFormSubmit,
  handleEditPromptFormSubmit,
  handleServerFormSubmit,
  handleA2AFormSubmit,
  handleToolFormSubmit,
  handleEditToolFormSubmit,
  handleEditGatewayFormSubmit,
  handleEditA2AAgentFormSubmit,
  handleEditServerFormSubmit,
  handleEditResFormSubmit,
} from "../../../mcpgateway/admin_ui/formSubmitHandlers.js";
import { showErrorMessage } from "../../../mcpgateway/admin_ui/utils";
import { safeParseJsonResponse } from "../../../mcpgateway/admin_ui/security";

vi.mock("../../../mcpgateway/admin_ui/constants", () => ({
  HEADER_NAME_REGEX: /^[A-Za-z0-9-]+$/,
}));
vi.mock("../../../mcpgateway/admin_ui/formFieldHandlers", () => ({
  generateSchema: vi.fn(() => '{"type":"object"}'),
}));
vi.mock("../../../mcpgateway/admin_ui/security", () => ({
  safeParseJsonResponse: vi.fn(async (response, msg) => {
    if (!response.ok) return null;
    return response.json();
  }),
  validateInputName: vi.fn((s) => {
    if (!s || s.trim() === "") return { valid: false, error: "Name is required" };
    return { valid: true, value: s.trim() };
  }),
  validateJson: vi.fn(() => ({ valid: true })),
  validateUrl: vi.fn((s) => {
    if (!s || !s.startsWith("http")) return { valid: false, error: "Invalid URL" };
    return { valid: true, value: s.trim() };
  }),
}));
vi.mock("../../../mcpgateway/admin_ui/utils", () => ({
  isInactiveChecked: vi.fn(() => false),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  showErrorMessage: vi.fn(),
}));

beforeEach(() => {
  window.ROOT_PATH = "";
  Object.defineProperty(window, "location", {
    value: {
      href: "http://localhost/admin",
      search: "",
      pathname: "/admin",
    },
    writable: true,
    configurable: true,
  });
});

afterEach(() => {
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
  vi.clearAllMocks();
});

function createFormEvent(formHtml) {
  document.body.innerHTML = formHtml;
  const form = document.querySelector("form");
  return {
    preventDefault: vi.fn(),
    target: form,
  };
}

// ---------------------------------------------------------------------------
// handleGatewayFormSubmit
// ---------------------------------------------------------------------------
describe("handleGatewayFormSubmit", () => {
  test("validates name and URL before submission", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="" />
        <input name="url" value="http://example.com" />
        <input name="visibility" value="public" />
        <input name="auth_type" value="none" />
      </form>
      <div id="status-gateways"></div>
      <div id="add-gateway-loading" style="display:none"></div>
    `);

    await handleGatewayFormSubmit(event);

    expect(showErrorMessage).toHaveBeenCalledWith(expect.stringContaining("required"));
  });

  test("validates URL format", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="MyGateway" />
        <input name="url" value="not-a-url" />
        <input name="visibility" value="public" />
        <input name="auth_type" value="none" />
      </form>
      <div id="status-gateways"></div>
      <div id="add-gateway-loading" style="display:none"></div>
    `);

    await handleGatewayFormSubmit(event);

    expect(showErrorMessage).toHaveBeenCalledWith(expect.stringContaining("Invalid URL"));
  });

  test("submits valid form data and redirects", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="TestGateway" />
        <input name="url" value="http://localhost:8080" />
        <input name="visibility" value="public" />
        <input name="auth_type" value="none" />
      </form>
      <div id="status-gateways"></div>
      <div id="add-gateway-loading" style="display:none"></div>
    `);

    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true });
    safeParseJsonResponse.mockResolvedValue({ success: true });

    await handleGatewayFormSubmit(event);

    expect(globalThis.fetch).toHaveBeenCalled();
    expect(event.preventDefault).toHaveBeenCalled();
  });

  test("validates passthrough headers format", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="TestGateway" />
        <input name="url" value="http://localhost:8080" />
        <input name="visibility" value="public" />
        <input name="auth_type" value="none" />
        <input name="passthrough_headers" value="X-Custom, Invalid Header!" />
      </form>
      <div id="status-gateways"></div>
      <div id="add-gateway-loading" style="display:none"></div>
    `);

    await handleGatewayFormSubmit(event);

    expect(showErrorMessage).toHaveBeenCalledWith(
      expect.stringContaining("Invalid passthrough header")
    );
  });

  test("hides loading indicator on completion", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="Gateway" />
        <input name="url" value="http://example.com" />
        <input name="visibility" value="public" />
        <input name="auth_type" value="none" />
      </form>
      <div id="status-gateways"></div>
      <div id="add-gateway-loading" style="display:block"></div>
    `);

    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true });
    safeParseJsonResponse.mockResolvedValue({ success: true });

    await handleGatewayFormSubmit(event);

    expect(document.getElementById("add-gateway-loading").style.display).toBe("none");
  });
});

// ---------------------------------------------------------------------------
// handleResourceFormSubmit
// ---------------------------------------------------------------------------
describe("handleResourceFormSubmit", () => {
  test("validates name before submission", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="" />
        <input name="uri" value="resource://test" />
        <input name="visibility" value="public" />
      </form>
      <div id="status-resources"></div>
      <div id="add-resource-loading" style="display:none"></div>
    `);

    await handleResourceFormSubmit(event);

    expect(showErrorMessage).toHaveBeenCalled();
  });

  test("appends uri_template for templatized URIs", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="TestResource" />
        <input name="uri" value="resource://{id}/items" />
        <input name="visibility" value="public" />
      </form>
      <div id="status-resources"></div>
      <div id="add-resource-loading" style="display:none"></div>
    `);

    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true });
    safeParseJsonResponse.mockResolvedValue({ success: true });

    await handleResourceFormSubmit(event);

    expect(globalThis.fetch).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// handlePromptFormSubmit
// ---------------------------------------------------------------------------
describe("handlePromptFormSubmit", () => {
  test("validates prompt name", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="" />
        <input name="visibility" value="public" />
      </form>
      <div id="status-prompts"></div>
      <div id="add-prompts-loading" style="display:none"></div>
    `);

    await handlePromptFormSubmit(event);

    expect(showErrorMessage).toHaveBeenCalled();
  });

  test("submits valid prompt and redirects", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="TestPrompt" />
        <input name="visibility" value="public" />
      </form>
      <div id="status-prompts"></div>
      <div id="add-prompts-loading" style="display:none"></div>
    `);

    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true });
    safeParseJsonResponse.mockResolvedValue({ success: true });

    await handlePromptFormSubmit(event);

    expect(globalThis.fetch).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// handleEditPromptFormSubmit
// ---------------------------------------------------------------------------
describe("handleEditPromptFormSubmit", () => {
  test("validates prompt name on edit", async () => {
    const event = createFormEvent(`
      <form action="/admin/prompts/1/edit">
        <input name="name" value="" />
        <input name="visibility" value="public" />
      </form>
    `);

    await handleEditPromptFormSubmit(event);

    expect(showErrorMessage).toHaveBeenCalled();
  });

  test("saves CodeMirror editors when present", async () => {
    window.promptToolHeadersEditor = { save: vi.fn() };
    window.promptToolSchemaEditor = { save: vi.fn() };

    const event = createFormEvent(`
      <form action="/admin/prompts/1/edit">
        <input name="name" value="EditedPrompt" />
        <input name="visibility" value="public" />
      </form>
    `);

    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true });
    safeParseJsonResponse.mockResolvedValue({ success: true });

    await handleEditPromptFormSubmit(event);

    expect(window.promptToolHeadersEditor.save).toHaveBeenCalled();
    expect(window.promptToolSchemaEditor.save).toHaveBeenCalled();

    delete window.promptToolHeadersEditor;
    delete window.promptToolSchemaEditor;
  });
});

// ---------------------------------------------------------------------------
// handleServerFormSubmit
// ---------------------------------------------------------------------------
describe("handleServerFormSubmit", () => {
  test("validates server name", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="" />
        <input name="visibility" value="public" />
      </form>
      <div id="serverFormError"></div>
      <div id="add-server-loading" style="display:none"></div>
    `);

    await handleServerFormSubmit(event);

    expect(showErrorMessage).toHaveBeenCalled();
  });

  test("submits valid server form", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="TestServer" />
        <input name="visibility" value="public" />
      </form>
      <div id="serverFormError"></div>
      <div id="add-server-loading" style="display:none"></div>
    `);

    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true });
    safeParseJsonResponse.mockResolvedValue({ success: true });

    await handleServerFormSubmit(event);

    expect(globalThis.fetch).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// handleA2AFormSubmit
// ---------------------------------------------------------------------------
describe("handleA2AFormSubmit", () => {
  test("validates A2A agent name", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="" />
        <input name="visibility" value="public" />
        <input name="auth_type" value="none" />
      </form>
      <div id="a2aFormError"></div>
      <div id="add-a2a-loading" style="display:none"></div>
    `);

    await handleA2AFormSubmit(event);

    expect(showErrorMessage).toHaveBeenCalled();
  });

  test("submits valid A2A agent form", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="TestA2A" />
        <input name="visibility" value="public" />
        <input name="auth_type" value="none" />
        <input name="agentType" value="A2A" />
      </form>
      <div id="a2aFormError"></div>
      <div id="add-a2a-loading" style="display:none"></div>
    `);

    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true });
    safeParseJsonResponse.mockResolvedValue({ success: true });

    await handleA2AFormSubmit(event);

    expect(globalThis.fetch).toHaveBeenCalled();
  });

  test("validates passthrough headers for A2A", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="TestA2A" />
        <input name="visibility" value="public" />
        <input name="auth_type" value="none" />
        <input name="passthrough_headers" value="Valid-Header, Invalid Header!" />
      </form>
      <div id="a2aFormError"></div>
      <div id="add-a2a-loading" style="display:none"></div>
    `);

    await handleA2AFormSubmit(event);

    expect(showErrorMessage).toHaveBeenCalledWith(
      expect.stringContaining("Invalid passthrough header")
    );
  });
});

// ---------------------------------------------------------------------------
// handleToolFormSubmit
// ---------------------------------------------------------------------------
describe("handleToolFormSubmit", () => {
  test("validates tool name and URL", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="" />
        <input name="url" value="http://example.com" />
        <input name="visibility" value="public" />
      </form>
    `);

    await handleToolFormSubmit(event);

    expect(showErrorMessage).toHaveBeenCalled();
  });

  test("submits valid tool form", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="TestTool" />
        <input name="url" value="http://example.com/api" />
        <input name="visibility" value="public" />
      </form>
    `);

    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true });
    safeParseJsonResponse.mockResolvedValue({ success: true });

    await handleToolFormSubmit(event);

    expect(globalThis.fetch).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// handleEditToolFormSubmit
// ---------------------------------------------------------------------------
describe("handleEditToolFormSubmit", () => {
  test("validates tool name on edit", async () => {
    const event = createFormEvent(`
      <form action="/admin/tools/1/edit">
        <input name="name" value="" />
        <input name="url" value="http://example.com" />
      </form>
    `);

    await handleEditToolFormSubmit(event);

    expect(showErrorMessage).toHaveBeenCalled();
  });

  test("saves CodeMirror editors when present", async () => {
    window.editToolHeadersEditor = { save: vi.fn() };
    window.editToolSchemaEditor = { save: vi.fn() };
    window.editToolOutputSchemaEditor = { save: vi.fn() };

    const event = createFormEvent(`
      <form action="/admin/tools/1/edit">
        <input name="name" value="EditedTool" />
        <input name="url" value="http://example.com/api" />
      </form>
    `);

    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true });
    safeParseJsonResponse.mockResolvedValue({ success: true });

    await handleEditToolFormSubmit(event);

    expect(window.editToolHeadersEditor.save).toHaveBeenCalled();
    expect(window.editToolSchemaEditor.save).toHaveBeenCalled();
    expect(window.editToolOutputSchemaEditor.save).toHaveBeenCalled();

    delete window.editToolHeadersEditor;
    delete window.editToolSchemaEditor;
    delete window.editToolOutputSchemaEditor;
  });
});

// ---------------------------------------------------------------------------
// handleEditGatewayFormSubmit
// ---------------------------------------------------------------------------
describe("handleEditGatewayFormSubmit", () => {
  test("validates gateway name and URL on edit", async () => {
    const event = createFormEvent(`
      <form action="/admin/gateways/1/edit">
        <input name="name" value="" />
        <input name="url" value="http://example.com" />
        <input name="auth_type" value="none" />
      </form>
    `);

    await handleEditGatewayFormSubmit(event);

    expect(showErrorMessage).toHaveBeenCalled();
  });

  test("validates passthrough headers on gateway edit", async () => {
    const event = createFormEvent(`
      <form action="/admin/gateways/1/edit">
        <input name="name" value="GW" />
        <input name="url" value="http://example.com" />
        <input name="auth_type" value="none" />
        <input name="passthrough_headers" value="Bad Header!" />
      </form>
    `);

    await handleEditGatewayFormSubmit(event);

    expect(showErrorMessage).toHaveBeenCalledWith(
      expect.stringContaining("Invalid passthrough header")
    );
  });
});

// ---------------------------------------------------------------------------
// handleEditA2AAgentFormSubmit
// ---------------------------------------------------------------------------
describe("handleEditA2AAgentFormSubmit", () => {
  test("validates A2A agent name on edit", async () => {
    const event = createFormEvent(`
      <form action="/admin/a2a/1/edit">
        <input name="name" value="" />
        <input name="endpoint_url" value="http://example.com" />
        <input name="auth_type" value="none" />
      </form>
    `);

    await handleEditA2AAgentFormSubmit(event);

    expect(showErrorMessage).toHaveBeenCalled();
  });

  test("validates URL on edit", async () => {
    const event = createFormEvent(`
      <form action="/admin/a2a/1/edit">
        <input name="name" value="AgentName" />
        <input name="endpoint_url" value="not-a-url" />
        <input name="auth_type" value="none" />
      </form>
    `);

    await handleEditA2AAgentFormSubmit(event);

    expect(showErrorMessage).toHaveBeenCalledWith(expect.stringContaining("Invalid URL"));
  });
});

// ---------------------------------------------------------------------------
// handleEditServerFormSubmit
// ---------------------------------------------------------------------------
describe("handleEditServerFormSubmit", () => {
  test("validates server name on edit", async () => {
    const event = createFormEvent(`
      <form action="/admin/servers/1/edit">
        <input name="name" value="" />
      </form>
    `);

    await handleEditServerFormSubmit(event);

    expect(showErrorMessage).toHaveBeenCalled();
  });

  test("submits valid server edit form", async () => {
    const event = createFormEvent(`
      <form action="/admin/servers/1/edit">
        <input name="name" value="EditedServer" />
      </form>
    `);

    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true });
    safeParseJsonResponse.mockResolvedValue({ success: true });

    await handleEditServerFormSubmit(event);

    expect(globalThis.fetch).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// handleEditResFormSubmit
// ---------------------------------------------------------------------------
describe("handleEditResFormSubmit", () => {
  test("validates resource name on edit", async () => {
    const event = createFormEvent(`
      <form action="/admin/resources/1/edit">
        <input name="name" value="" />
        <input name="uri" value="resource://test" />
      </form>
    `);

    await handleEditResFormSubmit(event);

    expect(showErrorMessage).toHaveBeenCalled();
  });

  test("appends uri_template for templatized URIs on edit", async () => {
    const event = createFormEvent(`
      <form action="/admin/resources/1/edit">
        <input name="name" value="EditRes" />
        <input name="uri" value="resource://{id}" />
      </form>
    `);

    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true });
    safeParseJsonResponse.mockResolvedValue({ success: true });

    await handleEditResFormSubmit(event);

    expect(globalThis.fetch).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// handleGatewayFormSubmit - extended (auth_headers, OAuth, team_id)
// ---------------------------------------------------------------------------
describe("handleGatewayFormSubmit - extended", () => {
  test("parses and re-appends auth_headers JSON", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="GW" />
        <input name="url" value="http://localhost:8080" />
        <input name="visibility" value="public" />
        <input name="auth_type" value="authheaders" />
        <input name="auth_headers" value='[{"key":"X-API-Key","value":"secret"}]' />
      </form>
      <div id="status-gateways"></div>
      <div id="add-gateway-loading" style="display:none"></div>
    `);

    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true });
    safeParseJsonResponse.mockResolvedValue({ success: true });

    await handleGatewayFormSubmit(event);

    expect(globalThis.fetch).toHaveBeenCalled();
    const fetchCall = globalThis.fetch.mock.calls[0];
    const formData = fetchCall[1].body;
    expect(formData.get("auth_headers")).toBeTruthy();
  });

  test("clears oauth_grant_type when auth_type is not oauth", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="GW" />
        <input name="url" value="http://localhost:8080" />
        <input name="visibility" value="public" />
        <input name="auth_type" value="bearer" />
        <input name="oauth_grant_type" value="client_credentials" />
      </form>
      <div id="status-gateways"></div>
      <div id="add-gateway-loading" style="display:none"></div>
    `);

    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true });
    safeParseJsonResponse.mockResolvedValue({ success: true });

    await handleGatewayFormSubmit(event);

    const fetchCall = globalThis.fetch.mock.calls[0];
    const formData = fetchCall[1].body;
    expect(formData.get("oauth_grant_type")).toBe("");
  });

  test("appends team_id from URL params when present", async () => {
    Object.defineProperty(window, "location", {
      value: {
        href: "http://localhost/admin?team_id=team-abc",
        search: "?team_id=team-abc",
        pathname: "/admin",
      },
      writable: true,
      configurable: true,
    });

    const event = createFormEvent(`
      <form>
        <input name="name" value="GW" />
        <input name="url" value="http://localhost:8080" />
        <input name="visibility" value="public" />
        <input name="auth_type" value="none" />
      </form>
      <div id="status-gateways"></div>
      <div id="add-gateway-loading" style="display:none"></div>
    `);

    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true });
    safeParseJsonResponse.mockResolvedValue({ success: true });

    await handleGatewayFormSubmit(event);

    const fetchCall = globalThis.fetch.mock.calls[0];
    const formData = fetchCall[1].body;
    expect(formData.get("team_id")).toBe("team-abc");
  });

  test("shows error when fetch returns failure result", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="GW" />
        <input name="url" value="http://localhost:8080" />
        <input name="visibility" value="public" />
        <input name="auth_type" value="none" />
      </form>
      <div id="status-gateways"></div>
      <div id="add-gateway-loading" style="display:none"></div>
    `);

    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true });
    safeParseJsonResponse.mockResolvedValue({ success: false, message: "Duplicate name" });

    await handleGatewayFormSubmit(event);

    expect(showErrorMessage).toHaveBeenCalledWith("Duplicate name");
  });
});

// ---------------------------------------------------------------------------
// handleA2AFormSubmit - extended (auth_headers, OAuth, team_id)
// ---------------------------------------------------------------------------
describe("handleA2AFormSubmit - extended", () => {
  test("parses auth_headers JSON for A2A agent", async () => {
    const event = createFormEvent(`
      <form>
        <input name="name" value="Agent" />
        <input name="visibility" value="public" />
        <input name="auth_type" value="authheaders" />
        <input name="auth_headers" value='[{"key":"X-Key","value":"val"}]' />
      </form>
      <div id="a2aFormError"></div>
      <div id="add-a2a-loading" style="display:none"></div>
    `);

    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true });
    safeParseJsonResponse.mockResolvedValue({ success: true });

    await handleA2AFormSubmit(event);

    expect(globalThis.fetch).toHaveBeenCalled();
  });

  test("appends team_id from URL for A2A agent", async () => {
    Object.defineProperty(window, "location", {
      value: {
        href: "http://localhost/admin?team_id=t1",
        search: "?team_id=t1",
        pathname: "/admin",
      },
      writable: true,
      configurable: true,
    });

    const event = createFormEvent(`
      <form>
        <input name="name" value="Agent" />
        <input name="visibility" value="public" />
        <input name="auth_type" value="none" />
      </form>
      <div id="a2aFormError"></div>
      <div id="add-a2a-loading" style="display:none"></div>
    `);

    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true });
    safeParseJsonResponse.mockResolvedValue({ success: true });

    await handleA2AFormSubmit(event);

    const fetchCall = globalThis.fetch.mock.calls[0];
    const formData = fetchCall[1].body;
    expect(formData.get("team_id")).toBe("t1");
  });
});

// ---------------------------------------------------------------------------
// handleEditGatewayFormSubmit - extended
// ---------------------------------------------------------------------------
describe("handleEditGatewayFormSubmit - extended", () => {
  test("submits valid gateway edit with auth_headers", async () => {
    const event = createFormEvent(`
      <form action="/admin/gateways/1/edit">
        <input name="name" value="GW Edit" />
        <input name="url" value="http://example.com" />
        <input name="auth_type" value="authheaders" />
        <input name="auth_headers" value='[{"key":"K","value":"V"}]' />
      </form>
    `);

    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true });
    safeParseJsonResponse.mockResolvedValue({ success: true });

    await handleEditGatewayFormSubmit(event);

    expect(globalThis.fetch).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// handleEditA2AAgentFormSubmit - extended
// ---------------------------------------------------------------------------
describe("handleEditA2AAgentFormSubmit - extended", () => {
  test("submits valid A2A agent edit", async () => {
    const event = createFormEvent(`
      <form action="/admin/a2a/1/edit">
        <input name="name" value="AgentEdit" />
        <input name="endpoint_url" value="http://localhost:9000" />
        <input name="auth_type" value="none" />
        <input name="visibility" value="public" />
      </form>
    `);

    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true });
    safeParseJsonResponse.mockResolvedValue({ success: true });

    await handleEditA2AAgentFormSubmit(event);

    expect(globalThis.fetch).toHaveBeenCalled();
  });

  test("validates passthrough headers on A2A edit", async () => {
    const event = createFormEvent(`
      <form action="/admin/a2a/1/edit">
        <input name="name" value="Agent" />
        <input name="endpoint_url" value="http://localhost:9000" />
        <input name="auth_type" value="none" />
        <input name="passthrough_headers" value="Bad Header!" />
      </form>
    `);

    await handleEditA2AAgentFormSubmit(event);

    expect(showErrorMessage).toHaveBeenCalledWith(
      expect.stringContaining("Invalid passthrough header")
    );
  });
});
