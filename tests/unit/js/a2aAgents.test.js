/**
 * Unit tests for a2aAgents.js module
 * Tests: viewA2AAgent, editA2AAgent, toggleA2AAuthFields, testA2AAgent,
 *        handleA2ATestSubmit, handleA2ATestClose, cleanupA2ATestModal
 */

import { describe, test, expect, vi, afterEach } from "vitest";

vi.mock("../../../mcpgateway/admin_ui/modals", () => ({
  closeModal: vi.fn(),
  openModal: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
  validateInputName: vi.fn((s) => ({ valid: true, value: s })),
  validateUrl: vi.fn((s) => ({ valid: true, value: s })),
}));
vi.mock("../../../mcpgateway/admin_ui/tokens", () => ({
  getAuthToken: vi.fn(() => Promise.resolve("test-jwt-token")),
}));
vi.mock("../../../mcpgateway/admin_ui/utils", () => ({
  decodeHtml: vi.fn((s) => s || ""),
  fetchWithTimeout: vi.fn(),
  handleFetchError: vi.fn((e) => e.message),
  isInactiveChecked: vi.fn(() => false),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  safeSetValue: vi.fn((id, val) => {
    const el = document.getElementById(id);
    if (el) el.value = val;
  }),
  showErrorMessage: vi.fn(),
}));

import {
  viewA2AAgent,
  editA2AAgent,
  toggleA2AAuthFields,
  testA2AAgent,
  handleA2ATestSubmit,
  handleA2ATestClose,
  cleanupA2ATestModal,
} from "../../../mcpgateway/admin_ui/a2aAgents.js";
import { fetchWithTimeout } from "../../../mcpgateway/admin_ui/utils";
import { openModal, closeModal } from "../../../mcpgateway/admin_ui/modals";

afterEach(() => {
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// viewA2AAgent
// ---------------------------------------------------------------------------
describe("viewA2AAgent", () => {
  test("fetches and displays agent details", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = `
      <div id="agent-details"></div>
      <div id="agent-modal" class="hidden"></div>
    `;

    const agent = {
      name: "Test Agent",
      slug: "test-agent",
      endpointUrl: "http://localhost:9000",
      agentType: "A2A",
      protocolVersion: "1.0",
      description: "A test agent",
      visibility: "public",
      enabled: true,
      reachable: true,
      tags: ["tag1"],
      capabilities: {},
      config: {},
    };

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(agent),
    });

    await viewA2AAgent("agent-123");

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("/admin/a2a/agent-123")
    );
    expect(openModal).toHaveBeenCalledWith("agent-modal");
    expect(document.getElementById("agent-details").children.length).toBeGreaterThan(0);
  });

  test("shows error on fetch failure", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = '<div id="agent-details"></div>';

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
    });

    const { showErrorMessage } = await import("../../../mcpgateway/admin_ui/utils");
    await viewA2AAgent("bad-id");

    expect(showErrorMessage).toHaveBeenCalled();
  });

  test("handles agent with no tags", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = `
      <div id="agent-details"></div>
      <div id="agent-modal" class="hidden"></div>
    `;

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "No Tags Agent",
          slug: "no-tags",
          endpointUrl: "http://localhost",
          agentType: "A2A",
          protocolVersion: "1.0",
          enabled: false,
          reachable: false,
          tags: [],
          capabilities: {},
          config: {},
        }),
    });

    await viewA2AAgent("agent-no-tags");
    expect(document.getElementById("agent-details").textContent).toContain("No tags");
  });

  test("handles inactive agent status", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = `
      <div id="agent-details"></div>
      <div id="agent-modal" class="hidden"></div>
    `;

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "Inactive Agent",
          slug: "inactive",
          endpointUrl: "http://localhost",
          agentType: "A2A",
          protocolVersion: "1.0",
          enabled: false,
          reachable: false,
          tags: [],
          capabilities: {},
          config: {},
        }),
    });

    await viewA2AAgent("agent-inactive");
    expect(document.getElementById("agent-details").textContent).toContain("Inactive");
  });
});

// ---------------------------------------------------------------------------
// editA2AAgent
// ---------------------------------------------------------------------------
describe("editA2AAgent", () => {
  test("fetches agent data and populates edit form", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = `
      <form id="edit-a2a-agent-form"></form>
      <input id="a2a-agent-name-edit" />
      <input id="a2a-agent-endpoint-url-edit" />
      <textarea id="a2a-agent-description-edit"></textarea>
      <select id="a2a-agent-type-edit"><option value="A2A">A2A</option></select>
      <input id="a2a-agent-tags-edit" />
      <input id="a2a-agent-capabilities-edit" />
      <input id="a2a-agent-config-edit" />
      <input id="a2a-visibility-public-edit" type="radio" />
      <input id="a2a-visibility-team-edit" type="radio" />
      <input id="a2a-visibility-private-edit" type="radio" />
      <select id="auth-type-a2a-edit"><option value="">None</option></select>
      <div id="auth-basic-fields-a2a-edit" style="display:none"></div>
      <div id="auth-bearer-fields-a2a-edit" style="display:none"></div>
      <div id="auth-headers-fields-a2a-edit" style="display:none"></div>
      <div id="auth-oauth-fields-a2a-edit" style="display:none"></div>
      <div id="auth-query_param-fields-a2a-edit" style="display:none"></div>
      <div id="a2a-edit-modal" class="hidden"></div>
    `;

    const agent = {
      name: "Edit Agent",
      endpointUrl: "http://localhost:9000/a2a",
      description: "Editable agent",
      agentType: "A2A",
      visibility: "public",
      authType: "",
      tags: ["t1", "t2"],
      capabilities: { streaming: true },
      config: { timeout: 30 },
    };

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(agent),
    });

    await editA2AAgent("agent-edit-123");

    expect(document.getElementById("a2a-agent-name-edit").value).toBe("Edit Agent");
    expect(document.getElementById("a2a-agent-endpoint-url-edit").value).toBe(
      "http://localhost:9000/a2a"
    );
    expect(document.getElementById("a2a-agent-description-edit").value).toBe("Editable agent");
    expect(document.getElementById("a2a-agent-tags-edit").value).toBe("t1, t2");
    expect(document.getElementById("a2a-visibility-public-edit").checked).toBe(true);
    expect(openModal).toHaveBeenCalledWith("a2a-edit-modal");
  });

  test("shows error on fetch failure", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = '<form id="edit-a2a-agent-form"></form>';

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
    });

    const { showErrorMessage } = await import("../../../mcpgateway/admin_ui/utils");
    await editA2AAgent("bad-id");

    expect(showErrorMessage).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// toggleA2AAuthFields
// ---------------------------------------------------------------------------
describe("toggleA2AAuthFields", () => {
  test("shows only the matching auth section", () => {
    document.body.innerHTML = `
      <div id="auth-basic-fields-a2a-edit" style="display:none"></div>
      <div id="auth-bearer-fields-a2a-edit" style="display:none"></div>
      <div id="auth-headers-fields-a2a-edit" style="display:none"></div>
      <div id="auth-oauth-fields-a2a-edit" style="display:none"></div>
      <div id="auth-query_param-fields-a2a-edit" style="display:none"></div>
    `;

    toggleA2AAuthFields("basic");

    expect(document.getElementById("auth-basic-fields-a2a-edit").style.display).toBe("block");
    expect(document.getElementById("auth-bearer-fields-a2a-edit").style.display).toBe("none");
  });

  test("hides all sections when authType is empty", () => {
    document.body.innerHTML = `
      <div id="auth-basic-fields-a2a-edit" style="display:block"></div>
      <div id="auth-bearer-fields-a2a-edit" style="display:block"></div>
      <div id="auth-headers-fields-a2a-edit" style="display:block"></div>
      <div id="auth-oauth-fields-a2a-edit" style="display:block"></div>
      <div id="auth-query_param-fields-a2a-edit" style="display:block"></div>
    `;

    toggleA2AAuthFields("");

    expect(document.getElementById("auth-basic-fields-a2a-edit").style.display).toBe("none");
    expect(document.getElementById("auth-bearer-fields-a2a-edit").style.display).toBe("none");
  });

  test("handles missing DOM elements gracefully", () => {
    expect(() => toggleA2AAuthFields("basic")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// testA2AAgent
// ---------------------------------------------------------------------------
describe("testA2AAgent", () => {
  test("opens test modal and populates fields", async () => {
    document.body.innerHTML = `
      <div id="a2a-test-modal" class="hidden"></div>
      <div id="a2a-test-modal-title"></div>
      <div id="a2a-test-modal-description"></div>
      <input id="a2a-test-agent-id" />
      <input id="a2a-test-query" />
      <div id="a2a-test-result" class="hidden"></div>
      <form id="a2a-test-form"></form>
      <button id="a2a-test-close"></button>
    `;

    await testA2AAgent("agent-1", "Test Agent", "http://localhost:9000");

    expect(document.getElementById("a2a-test-modal-title").textContent).toContain("Test Agent");
    expect(document.getElementById("a2a-test-agent-id").value).toBe("agent-1");
    expect(openModal).toHaveBeenCalledWith("a2a-test-modal");
  });

  test("shows error when modal setup fails", async () => {
    // No DOM elements present
    const { showErrorMessage } = await import("../../../mcpgateway/admin_ui/utils");
    await testA2AAgent("agent-1", "Test Agent", "http://localhost");
    // should still try to open modal even with minimal DOM
    expect(openModal).toHaveBeenCalledWith("a2a-test-modal");
  });
});

// ---------------------------------------------------------------------------
// handleA2ATestSubmit
// ---------------------------------------------------------------------------
describe("handleA2ATestSubmit", () => {
  test("submits test and displays success result", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = `
      <div id="a2a-test-loading" class="hidden"></div>
      <div id="a2a-test-response-json"></div>
      <div id="a2a-test-result" class="hidden"></div>
      <button id="a2a-test-submit">Test Agent</button>
      <input id="a2a-test-agent-id" value="agent-1" />
      <input id="a2a-test-query" value="Hello" />
    `;

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          success: true,
          result: { response: "Hello back!" },
        }),
    });

    const event = { preventDefault: vi.fn() };
    await handleA2ATestSubmit(event);

    expect(event.preventDefault).toHaveBeenCalled();
    const responseDiv = document.getElementById("a2a-test-response-json");
    expect(responseDiv.innerHTML).toContain("Test Successful");
  });

  test("displays error when agent ID is missing", async () => {
    document.body.innerHTML = `
      <div id="a2a-test-loading"></div>
      <div id="a2a-test-response-json"></div>
      <div id="a2a-test-result" class="hidden"></div>
      <button id="a2a-test-submit">Test Agent</button>
    `;

    const event = { preventDefault: vi.fn() };
    await handleA2ATestSubmit(event);

    const responseDiv = document.getElementById("a2a-test-response-json");
    expect(responseDiv.innerHTML).toContain("Error");
  });

  test("handles HTTP error response", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = `
      <div id="a2a-test-loading" class="hidden"></div>
      <div id="a2a-test-response-json"></div>
      <div id="a2a-test-result" class="hidden"></div>
      <button id="a2a-test-submit">Test Agent</button>
      <input id="a2a-test-agent-id" value="agent-1" />
      <input id="a2a-test-query" value="Hello" />
    `;

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
    });

    const event = { preventDefault: vi.fn() };
    await handleA2ATestSubmit(event);

    const responseDiv = document.getElementById("a2a-test-response-json");
    expect(responseDiv.innerHTML).toContain("Error");
  });

  test("restores button state after test", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = `
      <div id="a2a-test-loading" class="hidden"></div>
      <div id="a2a-test-response-json"></div>
      <div id="a2a-test-result" class="hidden"></div>
      <button id="a2a-test-submit">Test Agent</button>
      <input id="a2a-test-agent-id" value="agent-1" />
      <input id="a2a-test-query" value="Hello" />
    `;

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true, result: {} }),
    });

    const event = { preventDefault: vi.fn() };
    await handleA2ATestSubmit(event);

    const button = document.getElementById("a2a-test-submit");
    expect(button.disabled).toBe(false);
    expect(button.textContent).toBe("Test Agent");
  });
});

// ---------------------------------------------------------------------------
// handleA2ATestClose
// ---------------------------------------------------------------------------
describe("handleA2ATestClose", () => {
  test("resets form and closes modal", () => {
    document.body.innerHTML = `
      <form id="a2a-test-form">
        <input name="query" value="Hello" />
      </form>
      <div id="a2a-test-response-json">old content</div>
      <div id="a2a-test-result">visible</div>
    `;

    handleA2ATestClose();

    expect(document.getElementById("a2a-test-response-json").innerHTML).toBe("");
    expect(document.getElementById("a2a-test-result").classList.contains("hidden")).toBe(true);
    expect(closeModal).toHaveBeenCalledWith("a2a-test-modal");
  });

  test("does not throw when elements are missing", () => {
    expect(() => handleA2ATestClose()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// cleanupA2ATestModal
// ---------------------------------------------------------------------------
describe("cleanupA2ATestModal", () => {
  test("cleans up without errors when no handlers set", () => {
    document.body.innerHTML = `
      <form id="a2a-test-form"></form>
      <button id="a2a-test-close"></button>
    `;

    expect(() => cleanupA2ATestModal()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// viewA2AAgent - extended coverage (offline status, object tags)
// ---------------------------------------------------------------------------
describe("viewA2AAgent - extended", () => {
  test("shows offline status for enabled but unreachable agent", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = `
      <div id="agent-details"></div>
      <div id="agent-modal" class="hidden"></div>
    `;

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "Offline Agent",
          slug: "offline",
          endpointUrl: "http://localhost",
          agentType: "A2A",
          protocolVersion: "1.0",
          enabled: true,
          reachable: false,
          tags: [],
          capabilities: {},
          config: {},
        }),
    });

    await viewA2AAgent("agent-offline");
    expect(document.getElementById("agent-details").textContent).toContain("Offline");
  });

  test("handles object tags with label property", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = `
      <div id="agent-details"></div>
      <div id="agent-modal" class="hidden"></div>
    `;

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "Tags Agent",
          slug: "tags",
          endpointUrl: "http://localhost",
          agentType: "A2A",
          protocolVersion: "1.0",
          enabled: true,
          reachable: true,
          tags: [{ label: "Tag One" }, "plain-tag"],
          capabilities: {},
          config: {},
        }),
    });

    await viewA2AAgent("agent-tags");
    const details = document.getElementById("agent-details").textContent;
    expect(details).toContain("Tag One");
    expect(details).toContain("plain-tag");
  });
});

// ---------------------------------------------------------------------------
// editA2AAgent - extended coverage (auth types, visibility, passthrough)
// ---------------------------------------------------------------------------
describe("editA2AAgent - auth types", () => {
  function createEditFormHTML(authType) {
    return `
      <form id="edit-a2a-agent-form"></form>
      <input id="a2a-agent-name-edit" />
      <input id="a2a-agent-endpoint-url-edit" />
      <textarea id="a2a-agent-description-edit"></textarea>
      <select id="a2a-agent-type-edit"><option value="A2A">A2A</option></select>
      <input id="a2a-agent-tags-edit" />
      <input id="a2a-agent-capabilities-edit" />
      <input id="a2a-agent-config-edit" />
      <input id="a2a-visibility-public-edit" type="radio" />
      <input id="a2a-visibility-team-edit" type="radio" />
      <input id="a2a-visibility-private-edit" type="radio" />
      <select id="auth-type-a2a-edit"><option value="${authType}">${authType}</option></select>
      <div id="auth-basic-fields-a2a-edit" style="display:none">
        <input name="auth_username" />
        <input name="auth_password" />
      </div>
      <div id="auth-bearer-fields-a2a-edit" style="display:none">
        <input name="auth_token" />
      </div>
      <div id="auth-headers-fields-a2a-edit" style="display:none">
        <input name="auth_header_key" />
        <input name="auth_header_value" />
      </div>
      <div id="auth-oauth-fields-a2a-edit" style="display:none"></div>
      <select id="oauth-grant-type-a2a-edit"><option value="client_credentials">CC</option><option value="authorization_code">AC</option></select>
      <input id="oauth-client-id-a2a-edit" />
      <input id="oauth-client-secret-a2a-edit" />
      <input id="oauth-token-url-a2a-edit" />
      <input id="oauth-authorization-url-a2a-edit" />
      <input id="oauth-redirect-uri-a2a-edit" />
      <input id="oauth-scopes-a2a-edit" />
      <div id="oauth-auth-code-fields-a2a-edit" style="display:none"></div>
      <div id="auth-query_param-fields-a2a-edit" style="display:none"></div>
      <input id="auth-query-param-key-a2a-edit" />
      <input id="auth-query-param-value-a2a-edit" />
      <input id="edit-a2a-agent-passthrough-headers" />
      <div id="a2a-edit-modal" class="hidden"></div>
    `;
  }

  test("populates basic auth fields", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = createEditFormHTML("basic");

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "Basic Agent",
          endpointUrl: "http://localhost",
          agentType: "A2A",
          visibility: "team",
          authType: "basic",
          authUsername: "admin",
          tags: [],
          capabilities: {},
          config: {},
        }),
    });

    await editA2AAgent("agent-basic");

    const usernameField = document.querySelector(
      "#auth-basic-fields-a2a-edit input[name='auth_username']"
    );
    expect(usernameField.value).toBe("admin");
    expect(document.getElementById("auth-basic-fields-a2a-edit").style.display).toBe("block");
    expect(document.getElementById("a2a-visibility-team-edit").checked).toBe(true);
  });

  test("populates bearer auth fields", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = createEditFormHTML("bearer");

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "Bearer Agent",
          endpointUrl: "http://localhost",
          agentType: "A2A",
          visibility: "private",
          authType: "bearer",
          authValue: "my-token",
          tags: [],
          capabilities: {},
          config: {},
        }),
    });

    await editA2AAgent("agent-bearer");

    const tokenField = document.querySelector(
      "#auth-bearer-fields-a2a-edit input[name='auth_token']"
    );
    expect(tokenField.value).toBe("my-token");
    expect(document.getElementById("auth-bearer-fields-a2a-edit").style.display).toBe("block");
    expect(document.getElementById("a2a-visibility-private-edit").checked).toBe(true);
  });

  test("populates authheaders fields", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = createEditFormHTML("authheaders");

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "Headers Agent",
          endpointUrl: "http://localhost",
          agentType: "A2A",
          visibility: "public",
          authType: "authheaders",
          authHeaderKey: "X-Api-Key",
          tags: [],
          capabilities: {},
          config: {},
        }),
    });

    await editA2AAgent("agent-headers");

    expect(document.getElementById("auth-headers-fields-a2a-edit").style.display).toBe("block");
  });

  test("populates OAuth fields with oauthConfig", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = createEditFormHTML("oauth");

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "OAuth Agent",
          endpointUrl: "http://localhost",
          agentType: "A2A",
          visibility: "public",
          authType: "oauth",
          oauthConfig: {
            grant_type: "authorization_code",
            client_id: "my-client",
            token_url: "http://auth.example.com/token",
            authorization_url: "http://auth.example.com/authorize",
            redirect_uri: "http://localhost/callback",
            scopes: ["read", "write"],
          },
          tags: [],
          capabilities: {},
          config: {},
        }),
    });

    await editA2AAgent("agent-oauth");

    expect(document.getElementById("auth-oauth-fields-a2a-edit").style.display).toBe("block");
    expect(document.getElementById("oauth-grant-type-a2a-edit").value).toBe("authorization_code");
    expect(document.getElementById("oauth-client-id-a2a-edit").value).toBe("my-client");
    expect(document.getElementById("oauth-token-url-a2a-edit").value).toBe(
      "http://auth.example.com/token"
    );
    expect(document.getElementById("oauth-authorization-url-a2a-edit").value).toBe(
      "http://auth.example.com/authorize"
    );
    expect(document.getElementById("oauth-redirect-uri-a2a-edit").value).toBe(
      "http://localhost/callback"
    );
    expect(document.getElementById("oauth-scopes-a2a-edit").value).toBe("read write");
    expect(document.getElementById("oauth-auth-code-fields-a2a-edit").style.display).toBe("block");
  });

  test("populates query_param auth fields", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = createEditFormHTML("query_param");

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "QP Agent",
          endpointUrl: "http://localhost",
          agentType: "A2A",
          visibility: "public",
          authType: "query_param",
          authQueryParamKey: "api_key",
          tags: [],
          capabilities: {},
          config: {},
        }),
    });

    await editA2AAgent("agent-qp");

    expect(document.getElementById("auth-query_param-fields-a2a-edit").style.display).toBe(
      "block"
    );
    expect(document.getElementById("auth-query-param-key-a2a-edit").value).toBe("api_key");
  });

  test("populates passthrough headers", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = createEditFormHTML("");

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "PT Agent",
          endpointUrl: "http://localhost",
          agentType: "A2A",
          visibility: "public",
          authType: "",
          tags: [{ label: "obj-tag" }],
          capabilities: {},
          config: {},
          passthroughHeaders: ["X-Custom", "X-Another"],
        }),
    });

    await editA2AAgent("agent-pt");

    expect(document.getElementById("edit-a2a-agent-passthrough-headers").value).toBe(
      "X-Custom, X-Another"
    );
    expect(document.getElementById("a2a-agent-tags-edit").value).toBe("obj-tag");
  });
});
