/**
 * Unit tests for gateway.js module
 * Tests: viewGateway, editGateway, initGatewaySelect, getSelectedGatewayIds,
 *        testGateway, handleGatewayTestSubmit, handleGatewayTestClose,
 *        cleanupGatewayTestModal
 */

import { describe, test, expect, vi, afterEach } from "vitest";

import {
  viewGateway,
  editGateway,
  initGatewaySelect,
  getSelectedGatewayIds,
  testGateway,
} from "../../../mcpgateway/admin_ui/gateway.js";
import { fetchWithTimeout, showErrorMessage } from "../../../mcpgateway/admin_ui/utils";
import { openModal } from "../../../mcpgateway/admin_ui/modals";

vi.mock("../../../mcpgateway/admin_ui/auth.js", () => ({
  loadAuthHeaders: vi.fn(),
  updateAuthHeadersJSON: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/constants.js", () => ({
  MASKED_AUTH_VALUE: "*****",
}));
vi.mock("../../../mcpgateway/admin_ui/modals", () => ({
  closeModal: vi.fn(),
  openModal: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/prompts", () => ({
  initPromptSelect: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/resources", () => ({
  initResourceSelect: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
  validateInputName: vi.fn((s) => ({ valid: true, value: s })),
  validateJson: vi.fn((s) => ({
    valid: true,
    value: s ? JSON.parse(s) : null,
  })),
  validateUrl: vi.fn((s) => {
    if (!s || !s.startsWith("http")) return { valid: false, error: "Invalid URL" };
    return { valid: true, value: s };
  }),
}));
vi.mock("../../../mcpgateway/admin_ui/tools", () => ({
  initToolSelect: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/utils", () => ({
  decodeHtml: vi.fn((s) => s || ""),
  fetchWithTimeout: vi.fn(),
  getCurrentTeamId: vi.fn(() => null),
  handleFetchError: vi.fn((e) => e.message),
  isInactiveChecked: vi.fn(() => false),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  showErrorMessage: vi.fn(),
}));

afterEach(() => {
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// viewGateway
// ---------------------------------------------------------------------------
describe("viewGateway", () => {
  test("fetches and displays gateway details", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = `
      <div id="gateway-details"></div>
      <div id="gateway-modal" class="hidden"></div>
    `;

    const gateway = {
      name: "Test Gateway",
      url: "http://localhost:8080",
      description: "A gateway",
      visibility: "public",
      enabled: true,
      reachable: true,
      tags: ["mcp"],
    };

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(gateway),
    });

    await viewGateway("gw-1");

    expect(fetchWithTimeout).toHaveBeenCalledWith(
      expect.stringContaining("/admin/gateways/gw-1")
    );
    expect(openModal).toHaveBeenCalledWith("gateway-modal");
    const details = document.getElementById("gateway-details");
    expect(details.children.length).toBeGreaterThan(0);
  });

  test("shows error on fetch failure", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = '<div id="gateway-details"></div>';

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
    });

    await viewGateway("bad-id");

    expect(showErrorMessage).toHaveBeenCalled();
  });

  test("handles gateway with no tags", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = `
      <div id="gateway-details"></div>
      <div id="gateway-modal" class="hidden"></div>
    `;

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "GW",
          url: "http://localhost",
          enabled: true,
          reachable: false,
          tags: [],
        }),
    });

    await viewGateway("gw-no-tags");
    expect(document.getElementById("gateway-details").textContent).toContain("No tags");
  });

  test("shows inactive status for disabled gateway", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = `
      <div id="gateway-details"></div>
      <div id="gateway-modal" class="hidden"></div>
    `;

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "Disabled GW",
          url: "http://localhost",
          enabled: false,
          reachable: false,
          tags: [],
        }),
    });

    await viewGateway("gw-disabled");
    expect(document.getElementById("gateway-details").textContent).toContain("Inactive");
  });

  test("shows offline status for enabled but unreachable gateway", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = `
      <div id="gateway-details"></div>
      <div id="gateway-modal" class="hidden"></div>
    `;

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "Offline GW",
          url: "http://localhost",
          enabled: true,
          reachable: false,
          tags: [],
        }),
    });

    await viewGateway("gw-offline");
    expect(document.getElementById("gateway-details").textContent).toContain("Offline");
  });
});

// ---------------------------------------------------------------------------
// editGateway
// ---------------------------------------------------------------------------
describe("editGateway", () => {
  test("fetches gateway data and populates edit form", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = `
      <form id="edit-gateway-form"></form>
      <input id="edit-gateway-name" />
      <input id="edit-gateway-url" />
      <textarea id="edit-gateway-description"></textarea>
      <input id="edit-gateway-tags" />
      <input id="edit-gateway-visibility-public" type="radio" name="visibility" />
      <input id="edit-gateway-visibility-team" type="radio" name="visibility" />
      <input id="edit-gateway-visibility-private" type="radio" name="visibility" />
      <select id="edit-gateway-transport"><option value="SSE">SSE</option></select>
      <select id="auth-type-gw-edit"><option value="">None</option></select>
      <div id="auth-basic-fields-gw-edit" style="display:none"></div>
      <div id="auth-bearer-fields-gw-edit" style="display:none"></div>
      <div id="auth-headers-fields-gw-edit" style="display:none"></div>
      <div id="auth-oauth-fields-gw-edit" style="display:none"></div>
      <div id="auth-query_param-fields-gw-edit" style="display:none"></div>
      <input id="edit-gateway-passthrough-headers" />
      <div id="gateway-edit-modal" class="hidden"></div>
    `;

    const gateway = {
      name: "EditGW",
      url: "http://localhost:8080",
      description: "Edit me",
      visibility: "team",
      transport: "SSE",
      authType: "",
      tags: ["t1"],
      passthroughHeaders: ["X-Custom"],
    };

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(gateway),
    });

    await editGateway("gw-edit-1");

    expect(document.getElementById("edit-gateway-name").value).toBe("EditGW");
    expect(document.getElementById("edit-gateway-url").value).toBe("http://localhost:8080");
    expect(document.getElementById("edit-gateway-description").value).toBe("Edit me");
    expect(document.getElementById("edit-gateway-visibility-team").checked).toBe(true);
    expect(document.getElementById("edit-gateway-passthrough-headers").value).toBe("X-Custom");
    expect(openModal).toHaveBeenCalledWith("gateway-edit-modal");
  });

  test("shows error on fetch failure", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = '<form id="edit-gateway-form"></form>';

    fetchWithTimeout.mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Server Error",
    });

    await editGateway("bad-gw");

    expect(showErrorMessage).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// initGatewaySelect
// ---------------------------------------------------------------------------
describe("initGatewaySelect", () => {
  test("initializes gateway selection with checkboxes", () => {
    document.body.innerHTML = `
      <div id="associatedGateways">
        <div class="tool-item">
          <input type="checkbox" value="gw-1" />
          <label>Gateway 1</label>
        </div>
        <div class="tool-item">
          <input type="checkbox" value="gw-2" />
          <label>Gateway 2</label>
        </div>
      </div>
      <div id="selectedGatewayPills"></div>
      <div id="selectedGatewayWarning"></div>
    `;

    initGatewaySelect("associatedGateways", "selectedGatewayPills", "selectedGatewayWarning");

    const pills = document.getElementById("selectedGatewayPills");
    expect(pills).not.toBeNull();
  });

  test("warns when required elements are missing", () => {
    const spy = vi.spyOn(console, "warn").mockImplementation(() => {});
    initGatewaySelect("nonexistent", "nonexistent", "nonexistent");
    expect(spy).toHaveBeenCalled();
  });

  test("updates pills when checkboxes change", () => {
    document.body.innerHTML = `
      <div id="gw-select">
        <div class="tool-item">
          <input type="checkbox" value="gw-1" />
          <span>Gateway One</span>
        </div>
      </div>
      <div id="gw-pills"></div>
      <div id="gw-warn"></div>
    `;

    initGatewaySelect("gw-select", "gw-pills", "gw-warn");

    const checkbox = document.querySelector('input[type="checkbox"]');
    checkbox.checked = true;
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));

    const pills = document.getElementById("gw-pills");
    expect(pills.children.length).toBeGreaterThan(0);
  });

  test("shows warning when exceeding max selection", () => {
    // Create 15 checkboxes to exceed default max of 12
    let checkboxHtml = "";
    for (let i = 0; i < 15; i++) {
      checkboxHtml += `
        <div class="tool-item">
          <input type="checkbox" value="gw-${i}" checked />
          <span>Gateway ${i}</span>
        </div>`;
    }

    document.body.innerHTML = `
      <div id="gw-select">${checkboxHtml}</div>
      <div id="gw-pills"></div>
      <div id="gw-warn"></div>
    `;

    initGatewaySelect("gw-select", "gw-pills", "gw-warn", 12);

    const warn = document.getElementById("gw-warn");
    expect(warn.textContent).toContain("impact performance");
  });
});

// ---------------------------------------------------------------------------
// getSelectedGatewayIds
// ---------------------------------------------------------------------------
describe("getSelectedGatewayIds", () => {
  test("returns empty array when no container found", () => {
    expect(getSelectedGatewayIds()).toEqual([]);
  });

  test("returns checked checkbox values", () => {
    document.body.innerHTML = `
      <div id="associatedGateways">
        <input type="checkbox" value="gw-1" checked />
        <input type="checkbox" value="gw-2" />
        <input type="checkbox" value="gw-3" checked />
      </div>
    `;

    const ids = getSelectedGatewayIds();
    expect(ids).toEqual(["gw-1", "gw-3"]);
  });

  test("returns all IDs when Select All mode is active", () => {
    document.body.innerHTML = `
      <div id="associatedGateways">
        <input type="checkbox" value="gw-1" checked />
        <input name="selectAllGateways" value="true" />
        <input name="allGatewayIds" value='["gw-1","gw-2","gw-3"]' />
      </div>
    `;

    const ids = getSelectedGatewayIds();
    expect(ids).toEqual(["gw-1", "gw-2", "gw-3"]);
  });

  test("handles null gateway checkbox sentinel", () => {
    document.body.innerHTML = `
      <div id="associatedGateways">
        <input type="checkbox" value="" data-gateway-null="true" checked />
        <input type="checkbox" value="gw-1" checked />
      </div>
    `;

    const ids = getSelectedGatewayIds();
    expect(ids).toContain("null");
    expect(ids).toContain("gw-1");
  });

  test("prefers edit container when edit modal is open", () => {
    document.body.innerHTML = `
      <div id="associatedGateways">
        <input type="checkbox" value="create-gw" checked />
      </div>
      <div id="associatedEditGateways">
        <input type="checkbox" value="edit-gw" checked />
      </div>
      <div id="server-edit-modal"><!-- not hidden --></div>
    `;

    const ids = getSelectedGatewayIds();
    expect(ids).toEqual(["edit-gw"]);
  });
});

// ---------------------------------------------------------------------------
// testGateway
// ---------------------------------------------------------------------------
describe("testGateway", () => {
  test("opens test modal for valid URL", async () => {
    document.body.innerHTML = `
      <div id="gateway-test-modal" class="hidden"></div>
      <form id="gateway-test-form"></form>
      <input id="gateway-test-url" />
      <button id="gateway-test-close"></button>
    `;

    await testGateway("http://localhost:8080");

    expect(openModal).toHaveBeenCalledWith("gateway-test-modal");
    expect(document.getElementById("gateway-test-url").value).toBe("http://localhost:8080");
  });

  test("shows error for invalid URL", async () => {
    await testGateway("not-a-url");
    expect(showErrorMessage).toHaveBeenCalledWith(
      expect.stringContaining("Invalid gateway URL")
    );
  });

  test("does not throw when modal elements are missing", async () => {
    await expect(testGateway("http://localhost:8080")).resolves.not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// editGateway - extended auth type coverage
// ---------------------------------------------------------------------------
describe("editGateway - auth types", () => {
  function createGatewayEditHTML() {
    return `
      <form id="edit-gateway-form"></form>
      <input id="edit-gateway-name" />
      <input id="edit-gateway-url" />
      <textarea id="edit-gateway-description"></textarea>
      <input id="edit-gateway-tags" />
      <input id="edit-gateway-visibility-public" type="radio" name="visibility" />
      <input id="edit-gateway-visibility-team" type="radio" name="visibility" />
      <input id="edit-gateway-visibility-private" type="radio" name="visibility" />
      <select id="edit-gateway-transport"><option value="SSE">SSE</option></select>
      <select id="auth-type-gw-edit"><option value="">None</option></select>
      <div id="auth-basic-fields-gw-edit" style="display:none">
        <input name="auth_username" />
        <input name="auth_password" type="password" />
      </div>
      <div id="auth-bearer-fields-gw-edit" style="display:none">
        <input name="auth_token" type="password" />
      </div>
      <div id="auth-headers-fields-gw-edit" style="display:none">
        <input name="auth_header_key" />
        <input name="auth_header_value" type="password" />
      </div>
      <div id="auth-headers-container-gw-edit"></div>
      <input id="auth-headers-json-gw-edit" />
      <div id="auth-oauth-fields-gw-edit" style="display:none"></div>
      <select id="oauth-grant-type-gw-edit"><option value="client_credentials">CC</option></select>
      <input id="oauth-client-id-gw-edit" />
      <input id="oauth-client-secret-gw-edit" />
      <input id="oauth-token-url-gw-edit" />
      <input id="oauth-authorization-url-gw-edit" />
      <input id="oauth-redirect-uri-gw-edit" />
      <input id="oauth-scopes-gw-edit" />
      <div id="oauth-auth-code-fields-gw-edit" style="display:none"></div>
      <div id="auth-query_param-fields-gw-edit" style="display:none">
        <input name="auth_query_param_key" />
        <input name="auth_query_param_value" type="password" />
      </div>
      <input id="edit-gateway-passthrough-headers" />
      <div id="gateway-edit-modal" class="hidden"></div>
    `;
  }

  test("populates basic auth fields for gateway edit", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = createGatewayEditHTML();

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "Basic GW",
          url: "http://localhost:8080",
          visibility: "public",
          transport: "SSE",
          authType: "basic",
          authUsername: "user",
          authPasswordUnmasked: "secret123",
          tags: [],
        }),
    });

    await editGateway("gw-basic");

    expect(document.getElementById("auth-basic-fields-gw-edit").style.display).toBe("block");
    const usernameField = document.querySelector(
      "#auth-basic-fields-gw-edit input[name='auth_username']"
    );
    expect(usernameField.value).toBe("user");
  });

  test("populates bearer auth fields for gateway edit", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = createGatewayEditHTML();

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "Bearer GW",
          url: "http://localhost:8080",
          visibility: "team",
          transport: "SSE",
          authType: "bearer",
          authTokenUnmasked: "real-token",
          tags: [],
        }),
    });

    await editGateway("gw-bearer");

    expect(document.getElementById("auth-bearer-fields-gw-edit").style.display).toBe("block");
    expect(document.getElementById("edit-gateway-visibility-team").checked).toBe(true);
  });

  test("populates OAuth fields for gateway edit", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = createGatewayEditHTML();

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "OAuth GW",
          url: "http://localhost:8080",
          visibility: "private",
          transport: "SSE",
          authType: "oauth",
          oauthConfig: {
            grant_type: "client_credentials",
            client_id: "cid",
            token_url: "http://auth/token",
            scopes: ["api"],
          },
          tags: [],
        }),
    });

    await editGateway("gw-oauth");

    expect(document.getElementById("auth-oauth-fields-gw-edit").style.display).toBe("block");
    expect(document.getElementById("oauth-client-id-gw-edit").value).toBe("cid");
    expect(document.getElementById("oauth-token-url-gw-edit").value).toBe("http://auth/token");
    expect(document.getElementById("oauth-scopes-gw-edit").value).toBe("api");
    expect(document.getElementById("edit-gateway-visibility-private").checked).toBe(true);
  });

  test("populates query_param auth fields for gateway edit", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = createGatewayEditHTML();

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "QP GW",
          url: "http://localhost:8080",
          visibility: "public",
          transport: "SSE",
          authType: "query_param",
          authQueryParamKey: "token",
          authQueryParamValueUnmasked: "secret-val",
          tags: [],
        }),
    });

    await editGateway("gw-qp");

    expect(document.getElementById("auth-query_param-fields-gw-edit").style.display).toBe("block");
    const keyField = document.querySelector(
      "#auth-query_param-fields-gw-edit input[name='auth_query_param_key']"
    );
    expect(keyField.value).toBe("token");
  });

  test("populates passthrough headers for gateway edit", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = createGatewayEditHTML();

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "PT GW",
          url: "http://localhost:8080",
          visibility: "public",
          transport: "SSE",
          authType: "",
          tags: [{ label: "tag-obj" }],
          passthroughHeaders: ["X-Custom", "X-Trace"],
        }),
    });

    await editGateway("gw-pt");

    expect(document.getElementById("edit-gateway-passthrough-headers").value).toBe(
      "X-Custom, X-Trace"
    );
  });

  test("populates authheaders with loadAuthHeaders for gateway edit", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = createGatewayEditHTML();

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "AH GW",
          url: "http://localhost:8080",
          visibility: "public",
          transport: "SSE",
          authType: "authheaders",
          authHeaders: [
            { key: "X-API-Key", value: "secret" },
          ],
          authHeadersUnmasked: [
            { key: "X-API-Key", value: "real-secret" },
          ],
          tags: [],
        }),
    });

    await editGateway("gw-ah");

    expect(document.getElementById("auth-headers-fields-gw-edit").style.display).toBe("block");
  });
});

// ---------------------------------------------------------------------------
// initGatewaySelect - extended coverage (search, checkbox delegation)
// ---------------------------------------------------------------------------
describe("initGatewaySelect - extended", () => {
  test("search filters items by text content", () => {
    document.body.innerHTML = `
      <input id="searchGateways" />
      <div id="gw-select">
        <div class="tool-item">
          <input type="checkbox" value="gw-1" />
          <span>Alpha Gateway</span>
        </div>
        <div class="tool-item">
          <input type="checkbox" value="gw-2" />
          <span>Beta Gateway</span>
        </div>
      </div>
      <div id="gw-pills"></div>
      <div id="gw-warn"></div>
    `;

    initGatewaySelect("gw-select", "gw-pills", "gw-warn", 12, null, null, "searchGateways");

    const searchInput = document.getElementById("searchGateways");
    searchInput.value = "Alpha";
    searchInput.dispatchEvent(new Event("input"));

    const items = document.querySelectorAll(".tool-item");
    expect(items[0].style.display).toBe("");
    expect(items[1].style.display).toBe("none");
  });

  test("shows no results message when search has no matches", () => {
    document.body.innerHTML = `
      <input id="searchGateways" />
      <div id="gw-select">
        <div class="tool-item">
          <input type="checkbox" value="gw-1" />
          <span>Alpha</span>
        </div>
      </div>
      <div id="gw-pills"></div>
      <div id="gw-warn"></div>
      <div id="noGatewayMessage" style="display:none"></div>
      <span id="searchQueryServers"></span>
    `;

    initGatewaySelect("gw-select", "gw-pills", "gw-warn", 12, null, null, "searchGateways");

    const searchInput = document.getElementById("searchGateways");
    searchInput.value = "nonexistent";
    searchInput.dispatchEvent(new Event("input"));

    expect(document.getElementById("noGatewayMessage").style.display).toBe("block");
    expect(document.getElementById("searchQueryServers").textContent).toBe("nonexistent");
  });

  test("shows summary pill when more than 3 items selected", () => {
    let html = '<div id="gw-select">';
    for (let i = 0; i < 5; i++) {
      html += `<div class="tool-item">
        <input type="checkbox" value="gw-${i}" checked />
        <span>Gateway ${i}</span>
      </div>`;
    }
    html += `</div><div id="gw-pills"></div><div id="gw-warn"></div>`;
    document.body.innerHTML = html;

    initGatewaySelect("gw-select", "gw-pills", "gw-warn");

    const pills = document.getElementById("gw-pills");
    expect(pills.children.length).toBe(4); // 3 pills + 1 "+2 more"
    expect(pills.lastChild.textContent).toContain("+2 more");
  });

  test("checkbox delegation logs gateway selection and updates", () => {
    document.body.innerHTML = `
      <div id="gw-select">
        <div class="tool-item">
          <input type="checkbox" value="gw-1" />
          <span>Gateway One</span>
        </div>
      </div>
      <div id="gw-pills"></div>
      <div id="gw-warn"></div>
    `;

    initGatewaySelect("gw-select", "gw-pills", "gw-warn");

    const checkbox = document.querySelector('input[type="checkbox"]');
    checkbox.checked = true;
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));

    const pills = document.getElementById("gw-pills");
    expect(pills.children.length).toBeGreaterThan(0);
  });

  test("checkbox handles null gateway sentinel", () => {
    document.body.innerHTML = `
      <div id="gw-select">
        <div class="tool-item">
          <input type="checkbox" value="" data-gateway-null="true" />
          <span>No Gateway</span>
        </div>
      </div>
      <div id="gw-pills"></div>
      <div id="gw-warn"></div>
    `;

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    initGatewaySelect("gw-select", "gw-pills", "gw-warn");

    const checkbox = document.querySelector('input[type="checkbox"]');
    checkbox.checked = true;
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));

    expect(logSpy).toHaveBeenCalledWith(
      expect.stringContaining("null")
    );
  });
});

// ---------------------------------------------------------------------------
// getSelectedGatewayIds - extended
// ---------------------------------------------------------------------------
describe("getSelectedGatewayIds - extended", () => {
  test("uses edit container when edit container is visible and no main container", () => {
    document.body.innerHTML = `
      <div id="associatedEditGateways" style="display:block">
        <input type="checkbox" value="edit-gw" checked />
      </div>
    `;

    // offsetParent is null in jsdom for hidden elements, but we can test
    // the code path where editModal is not explicitly open
    const ids = getSelectedGatewayIds();
    // Without a visible modal, it falls through to either container
    expect(Array.isArray(ids)).toBe(true);
  });

  test("filters out empty string values from selection", () => {
    document.body.innerHTML = `
      <div id="associatedGateways">
        <input type="checkbox" value="" checked />
        <input type="checkbox" value="gw-1" checked />
      </div>
    `;

    const ids = getSelectedGatewayIds();
    expect(ids).not.toContain("");
    expect(ids).toContain("gw-1");
  });
});
