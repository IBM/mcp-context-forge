/**
 * Unit tests for auth.js module
 * Tests: toggleInputMask, addAuthHeader, removeAuthHeader, updateAuthHeadersJSON,
 *        loadAuthHeaders, fetchToolsForGateway, handleAuthTypeSelection,
 *        handleAuthTypeChange, handleOAuthGrantTypeChange, handleEditOAuthGrantTypeChange
 */

import { describe, test, expect, vi, afterEach } from "vitest";

vi.mock("../../../mcpgateway/admin_ui/constants.js", () => ({
  MASKED_AUTH_VALUE: "*****",
}));
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  showSuccessMessage: vi.fn(),
  showErrorMessage: vi.fn(),
}));

import {
  toggleInputMask,
  addAuthHeader,
  removeAuthHeader,
  updateAuthHeadersJSON,
  loadAuthHeaders,
  fetchToolsForGateway,
  handleAuthTypeSelection,
  handleAuthTypeChange,
  handleOAuthGrantTypeChange,
  handleEditOAuthGrantTypeChange,
} from "../../../mcpgateway/admin_ui/auth.js";
import { showErrorMessage, showSuccessMessage } from "../../../mcpgateway/admin_ui/utils.js";

afterEach(() => {
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// toggleInputMask
// ---------------------------------------------------------------------------
describe("toggleInputMask", () => {
  test("reveals password field to text", () => {
    document.body.innerHTML = `
      <input id="test-input" type="password" value="secret" data-sensitive-label="token" />
    `;
    const input = document.getElementById("test-input");
    const button = document.createElement("button");
    button.textContent = "Show";

    toggleInputMask(input, button);

    expect(input.type).toBe("text");
    expect(button.textContent).toBe("Hide");
    expect(button.getAttribute("aria-pressed")).toBe("true");
  });

  test("hides text field back to password", () => {
    document.body.innerHTML = `
      <input id="test-input" type="text" value="secret" data-sensitive-label="token" />
    `;
    const input = document.getElementById("test-input");
    const button = document.createElement("button");
    button.textContent = "Hide";

    toggleInputMask(input, button);

    expect(input.type).toBe("password");
    expect(button.textContent).toBe("Show");
    expect(button.getAttribute("aria-pressed")).toBe("false");
  });

  test("prevents reveal of stored secrets without revealable value", () => {
    document.body.innerHTML = `
      <input id="test-input" type="password" value="*****" data-is-masked="true" />
    `;
    const input = document.getElementById("test-input");
    const button = document.createElement("button");
    button.textContent = "Show";

    toggleInputMask(input, button);

    expect(input.type).toBe("password"); // should remain password
    expect(button.classList.contains("cursor-not-allowed")).toBe(true);
  });

  test("reveals stored secret when realValue is available", () => {
    document.body.innerHTML = `
      <input id="test-input" type="password" value="*****"
             data-is-masked="true" data-real-value="my-secret-token"
             data-sensitive-label="api key" />
    `;
    const input = document.getElementById("test-input");
    const button = document.createElement("button");

    toggleInputMask(input, button);

    expect(input.type).toBe("text");
    expect(input.value).toBe("my-secret-token");
  });

  test("does nothing when input is null", () => {
    const button = document.createElement("button");
    expect(() => toggleInputMask(null, button)).not.toThrow();
  });

  test("does nothing when button is null", () => {
    document.body.innerHTML = '<input id="test-input" type="password" />';
    const input = document.getElementById("test-input");
    expect(() => toggleInputMask(input, null)).not.toThrow();
  });

  test("accepts string id for inputOrId", () => {
    document.body.innerHTML = `
      <input id="test-input" type="password" value="val" data-sensitive-label="key" />
    `;
    const button = document.createElement("button");

    toggleInputMask("test-input", button);

    expect(document.getElementById("test-input").type).toBe("text");
  });
});

// ---------------------------------------------------------------------------
// addAuthHeader
// ---------------------------------------------------------------------------
describe("addAuthHeader", () => {
  test("adds a header row to the container", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container"></div>
      <input id="auth-headers-json" />
    `;

    addAuthHeader("auth-headers-container", { key: "X-API-Key", value: "abc" });

    const container = document.getElementById("auth-headers-container");
    expect(container.children.length).toBe(1);
    const keyInput = container.querySelector(".auth-header-key");
    const valueInput = container.querySelector(".auth-header-value");
    expect(keyInput.value).toBe("X-API-Key");
    expect(valueInput.value).toBe("abc");
  });

  test("handles masked values", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container"></div>
      <input id="auth-headers-json" />
    `;

    addAuthHeader("auth-headers-container", {
      key: "Authorization",
      value: "real-token",
      isMasked: true,
    });

    const container = document.getElementById("auth-headers-container");
    const valueInput = container.querySelector(".auth-header-value");
    expect(valueInput.value).toBe("*****");
    expect(valueInput.dataset.isMasked).toBe("true");
    expect(valueInput.dataset.realValue).toBe("real-token");
  });

  test("does nothing when container not found", () => {
    expect(() => addAuthHeader("nonexistent")).not.toThrow();
  });

  test("marks existing headers with data attribute", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container"></div>
      <input id="auth-headers-json" />
    `;

    addAuthHeader("auth-headers-container", { key: "X-Key", value: "v", existing: true });

    const row = document.querySelector('[id^="auth-header-"]');
    expect(row.dataset.existing).toBe("true");
  });
});

// ---------------------------------------------------------------------------
// removeAuthHeader
// ---------------------------------------------------------------------------
describe("removeAuthHeader", () => {
  test("removes a header row and updates JSON", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container">
        <div id="auth-header-1" class="flex items-center space-x-2">
          <input class="auth-header-key" value="X-Key" />
          <input class="auth-header-value" value="val" />
        </div>
      </div>
      <input id="auth-headers-json" />
    `;

    removeAuthHeader("auth-header-1", "auth-headers-container");

    const container = document.getElementById("auth-headers-container");
    expect(container.children.length).toBe(0);
  });

  test("does nothing for nonexistent header", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container"></div>
      <input id="auth-headers-json" />
    `;

    expect(() => removeAuthHeader("nonexistent", "auth-headers-container")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// updateAuthHeadersJSON
// ---------------------------------------------------------------------------
describe("updateAuthHeadersJSON", () => {
  test("serializes header rows to JSON input", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container">
        <div id="auth-header-1">
          <input class="auth-header-key" value="X-API-Key" />
          <input class="auth-header-value" value="secret123" />
        </div>
      </div>
      <input id="auth-headers-json" />
    `;

    updateAuthHeadersJSON("auth-headers-container");

    const jsonInput = document.getElementById("auth-headers-json");
    const parsed = JSON.parse(jsonInput.value);
    expect(parsed).toEqual([{ key: "X-API-Key", value: "secret123" }]);
  });

  test("skips completely empty rows", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container">
        <div id="auth-header-1">
          <input class="auth-header-key" value="" />
          <input class="auth-header-value" value="" />
        </div>
      </div>
      <input id="auth-headers-json" />
    `;

    updateAuthHeadersJSON("auth-headers-container");

    const jsonInput = document.getElementById("auth-headers-json");
    expect(jsonInput.value).toBe("");
  });

  test("maps container IDs to correct JSON inputs", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container-gw">
        <div id="auth-header-1">
          <input class="auth-header-key" value="Key" />
          <input class="auth-header-value" value="Val" />
        </div>
      </div>
      <input id="auth-headers-json-gw" />
    `;

    updateAuthHeadersJSON("auth-headers-container-gw");

    const jsonInput = document.getElementById("auth-headers-json-gw");
    expect(JSON.parse(jsonInput.value)).toEqual([{ key: "Key", value: "Val" }]);
  });

  test("does nothing when container not found", () => {
    expect(() => updateAuthHeadersJSON("nonexistent")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// loadAuthHeaders
// ---------------------------------------------------------------------------
describe("loadAuthHeaders", () => {
  test("loads headers into container", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container"></div>
      <input id="auth-headers-json" />
    `;

    const headers = [
      { key: "X-API-Key", value: "abc" },
      { key: "Authorization", value: "Bearer token" },
    ];

    loadAuthHeaders("auth-headers-container", headers);

    const container = document.getElementById("auth-headers-container");
    // Each header row is a direct child div
    const keyInputs = container.querySelectorAll(".auth-header-key");
    expect(keyInputs.length).toBe(2);
  });

  test("clears container when headers is empty", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container"><div>old content</div></div>
      <input id="auth-headers-json" value="old" />
    `;

    loadAuthHeaders("auth-headers-container", []);

    const container = document.getElementById("auth-headers-container");
    expect(container.innerHTML).toBe("");
    expect(document.getElementById("auth-headers-json").value).toBe("");
  });

  test("clears container when headers is null", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container"><div>old content</div></div>
      <input id="auth-headers-json" value="old" />
    `;

    loadAuthHeaders("auth-headers-container", null);

    expect(document.getElementById("auth-headers-json").value).toBe("");
  });

  test("skips null headers without key", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container"></div>
      <input id="auth-headers-json" />
    `;

    loadAuthHeaders("auth-headers-container", [
      { key: "Valid", value: "val" },
      null,
      { value: "no-key" },
    ]);

    // Only the header with key="Valid" should be added; null and keyless are skipped
    const container = document.getElementById("auth-headers-container");
    const keyInputs = container.querySelectorAll(".auth-header-key");
    const validKeys = Array.from(keyInputs).filter((k) => k.value === "Valid");
    expect(validKeys.length).toBe(1);
  });

  test("masks values when option is set", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container"></div>
      <input id="auth-headers-json" />
    `;

    loadAuthHeaders(
      "auth-headers-container",
      [{ key: "Secret", value: "hidden" }],
      { maskValues: true }
    );

    const valueInput = document.querySelector(".auth-header-value");
    expect(valueInput.value).toBe("*****");
    expect(valueInput.dataset.isMasked).toBe("true");
  });

  test("does nothing when container not found", () => {
    expect(() => loadAuthHeaders("nonexistent", [{ key: "K", value: "V" }])).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// fetchToolsForGateway
// ---------------------------------------------------------------------------
describe("fetchToolsForGateway", () => {
  test("fetches tools and shows success message", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = '<button id="fetch-tools-gw1">Fetch Tools</button>';

    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true, message: "Fetched 5 tools" }),
    });

    // Prevent actual reload
    const reloadMock = vi.fn();
    Object.defineProperty(window, "location", {
      value: { ...window.location, reload: reloadMock },
      writable: true,
      configurable: true,
    });

    await fetchToolsForGateway("gw1", "Test Gateway");

    const button = document.getElementById("fetch-tools-gw1");
    expect(button.textContent).toContain("Tools Fetched");
    expect(showSuccessMessage).toHaveBeenCalled();
  });

  test("shows error on fetch failure", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = '<button id="fetch-tools-gw1">Fetch Tools</button>';

    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ detail: "Not found" }),
    });

    await fetchToolsForGateway("gw1", "Test Gateway");

    const button = document.getElementById("fetch-tools-gw1");
    expect(button.textContent).toContain("Retry");
    expect(showErrorMessage).toHaveBeenCalled();
  });

  test("does nothing when button not found", async () => {
    window.ROOT_PATH = "";
    await fetchToolsForGateway("nonexistent", "Test");
    expect(showErrorMessage).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// handleAuthTypeSelection
// ---------------------------------------------------------------------------
describe("handleAuthTypeSelection", () => {
  function createFields() {
    const basic = document.createElement("div");
    basic.id = "basic";
    const bearer = document.createElement("div");
    bearer.id = "bearer";
    const headers = document.createElement("div");
    headers.id = "headers";
    const oauth = document.createElement("div");
    oauth.id = "oauth";
    const queryParam = document.createElement("div");
    queryParam.id = "query";
    return { basic, bearer, headers, oauth, queryParam };
  }

  test("shows basic fields for 'basic' auth type", () => {
    const { basic, bearer, headers, oauth, queryParam } = createFields();
    handleAuthTypeSelection("basic", basic, bearer, headers, oauth, queryParam);
    expect(basic.style.display).toBe("block");
    expect(bearer.style.display).toBe("none");
    expect(headers.style.display).toBe("none");
  });

  test("shows bearer fields for 'bearer' auth type", () => {
    const { basic, bearer, headers, oauth, queryParam } = createFields();
    handleAuthTypeSelection("bearer", basic, bearer, headers, oauth, queryParam);
    expect(bearer.style.display).toBe("block");
    expect(basic.style.display).toBe("none");
  });

  test("shows oauth fields for 'oauth' auth type", () => {
    const { basic, bearer, headers, oauth, queryParam } = createFields();
    handleAuthTypeSelection("oauth", basic, bearer, headers, oauth, queryParam);
    expect(oauth.style.display).toBe("block");
    expect(basic.style.display).toBe("none");
  });

  test("shows query_param fields for 'query_param' auth type", () => {
    const { basic, bearer, headers, oauth, queryParam } = createFields();
    handleAuthTypeSelection("query_param", basic, bearer, headers, oauth, queryParam);
    expect(queryParam.style.display).toBe("block");
    expect(basic.style.display).toBe("none");
  });

  test("hides all fields for 'none'", () => {
    const { basic, bearer, headers, oauth, queryParam } = createFields();
    handleAuthTypeSelection("none", basic, bearer, headers, oauth, queryParam);
    expect(basic.style.display).toBe("none");
    expect(bearer.style.display).toBe("none");
    expect(headers.style.display).toBe("none");
  });

  test("warns when required field elements not found", () => {
    const spy = vi.spyOn(console, "warn").mockImplementation(() => {});
    handleAuthTypeSelection("basic", null, null, null);
    expect(spy).toHaveBeenCalledWith("Auth field elements not found");
  });
});

// ---------------------------------------------------------------------------
// handleAuthTypeChange
// ---------------------------------------------------------------------------
describe("handleAuthTypeChange", () => {
  test("shows correct fields for gateway auth type change", () => {
    document.body.innerHTML = `
      <div id="auth-basic-fields-gw" style="display:none"></div>
      <div id="auth-bearer-fields-gw" style="display:none"></div>
      <div id="auth-headers-fields-gw" style="display:none"></div>
      <div id="auth-oauth-fields-gw" style="display:none"></div>
      <div id="auth-query_param-fields-gw" style="display:none"></div>
    `;

    const context = { id: "auth-type-gw", value: "basic" };
    handleAuthTypeChange.call(context);

    expect(document.getElementById("auth-basic-fields-gw").style.display).toBe("block");
    expect(document.getElementById("auth-bearer-fields-gw").style.display).toBe("none");
  });

  test("shows correct fields for a2a auth type change", () => {
    document.body.innerHTML = `
      <div id="auth-basic-fields-a2a" style="display:none"></div>
      <div id="auth-bearer-fields-a2a" style="display:none"></div>
      <div id="auth-headers-fields-a2a" style="display:none"></div>
      <div id="auth-oauth-fields-a2a" style="display:none"></div>
      <div id="auth-query_param-fields-a2a" style="display:none"></div>
    `;

    const context = { id: "auth-type-a2a", value: "bearer" };
    handleAuthTypeChange.call(context);

    expect(document.getElementById("auth-bearer-fields-a2a").style.display).toBe("block");
    expect(document.getElementById("auth-basic-fields-a2a").style.display).toBe("none");
  });

  test("hides all fields for 'none'", () => {
    document.body.innerHTML = `
      <div id="auth-basic-fields-gw" style="display:block"></div>
      <div id="auth-bearer-fields-gw" style="display:block"></div>
      <div id="auth-headers-fields-gw" style="display:block"></div>
      <div id="auth-oauth-fields-gw" style="display:none"></div>
      <div id="auth-query_param-fields-gw" style="display:none"></div>
    `;

    const context = { id: "auth-type-gw", value: "none" };
    handleAuthTypeChange.call(context);

    expect(document.getElementById("auth-basic-fields-gw").style.display).toBe("none");
    expect(document.getElementById("auth-bearer-fields-gw").style.display).toBe("none");
    expect(document.getElementById("auth-headers-fields-gw").style.display).toBe("none");
  });
});

// ---------------------------------------------------------------------------
// handleOAuthGrantTypeChange
// ---------------------------------------------------------------------------
describe("handleOAuthGrantTypeChange", () => {
  test("shows auth code fields for authorization_code grant", () => {
    document.body.innerHTML = `
      <div id="oauth-auth-code-fields-gw" style="display:none">
        <input type="url" />
      </div>
      <div id="oauth-username-field-gw" style="display:none"></div>
      <div id="oauth-password-field-gw" style="display:none"></div>
    `;

    const context = { id: "oauth-grant-type-gw", value: "authorization_code" };
    handleOAuthGrantTypeChange.call(context);

    expect(document.getElementById("oauth-auth-code-fields-gw").style.display).toBe("block");
  });

  test("shows username/password fields for password grant", () => {
    document.body.innerHTML = `
      <div id="oauth-auth-code-fields-gw" style="display:none"></div>
      <div id="oauth-username-field-gw" style="display:none"></div>
      <div id="oauth-password-field-gw" style="display:none"></div>
      <input id="oauth-username-gw" />
      <input id="oauth-password-gw" />
    `;

    const context = { id: "oauth-grant-type-gw", value: "password" };
    handleOAuthGrantTypeChange.call(context);

    expect(document.getElementById("oauth-username-field-gw").style.display).toBe("block");
    expect(document.getElementById("oauth-password-field-gw").style.display).toBe("block");
  });

  test("hides password fields for client_credentials grant", () => {
    document.body.innerHTML = `
      <div id="oauth-auth-code-fields-gw" style="display:block"></div>
      <div id="oauth-username-field-gw" style="display:block"></div>
      <div id="oauth-password-field-gw" style="display:block"></div>
      <input id="oauth-username-gw" />
      <input id="oauth-password-gw" />
    `;

    const context = { id: "oauth-grant-type-gw", value: "client_credentials" };
    handleOAuthGrantTypeChange.call(context);

    expect(document.getElementById("oauth-auth-code-fields-gw").style.display).toBe("none");
    expect(document.getElementById("oauth-username-field-gw").style.display).toBe("none");
    expect(document.getElementById("oauth-password-field-gw").style.display).toBe("none");
  });
});

// ---------------------------------------------------------------------------
// handleEditOAuthGrantTypeChange
// ---------------------------------------------------------------------------
describe("handleEditOAuthGrantTypeChange", () => {
  test("shows auth code fields for gw-edit authorization_code grant", () => {
    document.body.innerHTML = `
      <div id="oauth-auth-code-fields-gw-edit" style="display:none">
        <input type="url" />
      </div>
      <div id="oauth-username-field-gw-edit" style="display:none"></div>
      <div id="oauth-password-field-gw-edit" style="display:none"></div>
    `;

    const context = { id: "oauth-grant-type-gw-edit", value: "authorization_code" };
    handleEditOAuthGrantTypeChange.call(context);

    expect(document.getElementById("oauth-auth-code-fields-gw-edit").style.display).toBe("block");
  });

  test("detects a2a-edit prefix from element ID", () => {
    document.body.innerHTML = `
      <div id="oauth-auth-code-fields-a2a-edit" style="display:none">
        <input type="url" />
      </div>
      <div id="oauth-username-field-a2a-edit" style="display:none"></div>
      <div id="oauth-password-field-a2a-edit" style="display:none"></div>
    `;

    const context = { id: "oauth-grant-type-a2a-edit", value: "authorization_code" };
    handleEditOAuthGrantTypeChange.call(context);

    expect(document.getElementById("oauth-auth-code-fields-a2a-edit").style.display).toBe("block");
  });

  test("shows password fields for password grant type in edit mode", () => {
    document.body.innerHTML = `
      <div id="oauth-auth-code-fields-gw-edit" style="display:block"></div>
      <div id="oauth-username-field-gw-edit" style="display:none"></div>
      <div id="oauth-password-field-gw-edit" style="display:none"></div>
      <input id="oauth-username-gw-edit" />
      <input id="oauth-password-gw-edit" />
    `;

    const context = { id: "oauth-grant-type-gw-edit", value: "password" };
    handleEditOAuthGrantTypeChange.call(context);

    expect(document.getElementById("oauth-username-field-gw-edit").style.display).toBe("block");
    expect(document.getElementById("oauth-password-field-gw-edit").style.display).toBe("block");
    expect(document.getElementById("oauth-username-gw-edit").required).toBe(true);
    expect(document.getElementById("oauth-password-gw-edit").required).toBe(true);
  });

  test("hides password fields for client_credentials grant type in edit mode", () => {
    document.body.innerHTML = `
      <div id="oauth-auth-code-fields-gw-edit" style="display:block">
        <input type="url" />
      </div>
      <div id="oauth-username-field-gw-edit" style="display:block"></div>
      <div id="oauth-password-field-gw-edit" style="display:block"></div>
      <input id="oauth-username-gw-edit" required />
      <input id="oauth-password-gw-edit" required />
    `;

    const context = { id: "oauth-grant-type-gw-edit", value: "client_credentials" };
    handleEditOAuthGrantTypeChange.call(context);

    expect(document.getElementById("oauth-auth-code-fields-gw-edit").style.display).toBe("none");
    expect(document.getElementById("oauth-username-field-gw-edit").style.display).toBe("none");
    expect(document.getElementById("oauth-password-field-gw-edit").style.display).toBe("none");
    expect(document.getElementById("oauth-username-gw-edit").required).toBe(false);
    expect(document.getElementById("oauth-password-gw-edit").required).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// updateAuthHeadersJSON - extended coverage
// ---------------------------------------------------------------------------
describe("updateAuthHeadersJSON - extended", () => {
  test("validates key is required when value is present", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container">
        <div id="auth-header-1">
          <input class="auth-header-key" value="" />
          <input class="auth-header-value" value="some-value" />
        </div>
      </div>
      <input id="auth-headers-json" />
    `;

    updateAuthHeadersJSON("auth-headers-container");

    const keyInput = document.querySelector(".auth-header-key");
    expect(keyInput.validationMessage).toBeTruthy();
  });

  test("validates key format rejects special characters", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container">
        <div id="auth-header-1">
          <input class="auth-header-key" value="Invalid Key!" />
          <input class="auth-header-value" value="val" />
        </div>
      </div>
      <input id="auth-headers-json" />
    `;

    updateAuthHeadersJSON("auth-headers-container");

    const jsonInput = document.getElementById("auth-headers-json");
    // Invalid key should not be included in output
    expect(jsonInput.value).toBe("");
  });

  test("warns about duplicate keys", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    document.body.innerHTML = `
      <div id="auth-headers-container">
        <div id="auth-header-1">
          <input class="auth-header-key" value="X-API-Key" />
          <input class="auth-header-value" value="val1" />
        </div>
        <div id="auth-header-2">
          <input class="auth-header-key" value="X-API-Key" />
          <input class="auth-header-value" value="val2" />
        </div>
      </div>
      <input id="auth-headers-json" />
    `;

    updateAuthHeadersJSON("auth-headers-container");

    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("Duplicate header keys"),
      expect.any(Array)
    );
  });

  test("rejects more than 100 headers", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    let html = '<div id="auth-headers-container">';
    for (let i = 0; i < 101; i++) {
      html += `<div id="auth-header-${i}">
        <input class="auth-header-key" value="Key-${i}" />
        <input class="auth-header-value" value="val" />
      </div>`;
    }
    html += '</div><input id="auth-headers-json" />';
    document.body.innerHTML = html;

    updateAuthHeadersJSON("auth-headers-container");

    expect(errorSpy).toHaveBeenCalledWith("Maximum of 100 headers allowed per gateway");
  });

  test("maps auth-headers-container-a2a to auth-headers-json-a2a", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container-a2a">
        <div id="auth-header-1">
          <input class="auth-header-key" value="X-Key" />
          <input class="auth-header-value" value="val" />
        </div>
      </div>
      <input id="auth-headers-json-a2a" />
    `;

    updateAuthHeadersJSON("auth-headers-container-a2a");

    expect(JSON.parse(document.getElementById("auth-headers-json-a2a").value)).toEqual([
      { key: "X-Key", value: "val" },
    ]);
  });

  test("maps edit-auth-headers-container to edit-auth-headers-json", () => {
    document.body.innerHTML = `
      <div id="edit-auth-headers-container">
        <div id="auth-header-1">
          <input class="auth-header-key" value="Key" />
          <input class="auth-header-value" value="Val" />
        </div>
      </div>
      <input id="edit-auth-headers-json" />
    `;

    updateAuthHeadersJSON("edit-auth-headers-container");

    expect(JSON.parse(document.getElementById("edit-auth-headers-json").value)).toEqual([
      { key: "Key", value: "Val" },
    ]);
  });

  test("maps auth-headers-container-gw-edit to auth-headers-json-gw-edit", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container-gw-edit">
        <div id="auth-header-1">
          <input class="auth-header-key" value="K" />
          <input class="auth-header-value" value="V" />
        </div>
      </div>
      <input id="auth-headers-json-gw-edit" />
    `;

    updateAuthHeadersJSON("auth-headers-container-gw-edit");

    expect(document.getElementById("auth-headers-json-gw-edit").value).toBeTruthy();
  });

  test("maps auth-headers-container-a2a-edit to auth-headers-json-a2a-edit", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container-a2a-edit">
        <div id="auth-header-1">
          <input class="auth-header-key" value="K" />
          <input class="auth-header-value" value="V" />
        </div>
      </div>
      <input id="auth-headers-json-a2a-edit" />
    `;

    updateAuthHeadersJSON("auth-headers-container-a2a-edit");

    expect(document.getElementById("auth-headers-json-a2a-edit").value).toBeTruthy();
  });

  test("handles masked value that was changed by user", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container">
        <div id="auth-header-1">
          <input class="auth-header-key" value="X-Secret" />
          <input class="auth-header-value" value="new-value"
                 data-is-masked="true" data-real-value="old-value" />
        </div>
      </div>
      <input id="auth-headers-json" />
    `;

    updateAuthHeadersJSON("auth-headers-container");

    const jsonInput = document.getElementById("auth-headers-json");
    const parsed = JSON.parse(jsonInput.value);
    // Since value is neither MASKED_AUTH_VALUE nor realValue, isMasked should be cleared
    expect(parsed[0].value).toBe("new-value");
  });

  test("preserves masked value when not changed", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container">
        <div id="auth-header-1">
          <input class="auth-header-key" value="X-Secret" />
          <input class="auth-header-value" value="*****"
                 data-is-masked="true" data-real-value="real-secret" />
        </div>
      </div>
      <input id="auth-headers-json" />
    `;

    updateAuthHeadersJSON("auth-headers-container");

    const jsonInput = document.getElementById("auth-headers-json");
    const parsed = JSON.parse(jsonInput.value);
    expect(parsed[0].value).toBe("*****");
  });
});

// ---------------------------------------------------------------------------
// loadAuthHeaders - extended coverage
// ---------------------------------------------------------------------------
describe("loadAuthHeaders - extended", () => {
  test("maps auth-headers-container-gw to auth-headers-json-gw", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container-gw"></div>
      <input id="auth-headers-json-gw" value="old" />
    `;

    loadAuthHeaders("auth-headers-container-gw", []);

    expect(document.getElementById("auth-headers-json-gw").value).toBe("");
  });

  test("maps auth-headers-container-a2a to auth-headers-json-a2a", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container-a2a"></div>
      <input id="auth-headers-json-a2a" value="old" />
    `;

    loadAuthHeaders("auth-headers-container-a2a", []);

    expect(document.getElementById("auth-headers-json-a2a").value).toBe("");
  });

  test("maps edit-auth-headers-container to edit-auth-headers-json", () => {
    document.body.innerHTML = `
      <div id="edit-auth-headers-container"></div>
      <input id="edit-auth-headers-json" value="old" />
    `;

    loadAuthHeaders("edit-auth-headers-container", []);

    expect(document.getElementById("edit-auth-headers-json").value).toBe("");
  });

  test("maps auth-headers-container-gw-edit to auth-headers-json-gw-edit", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container-gw-edit"></div>
      <input id="auth-headers-json-gw-edit" value="old" />
    `;

    loadAuthHeaders("auth-headers-container-gw-edit", []);

    expect(document.getElementById("auth-headers-json-gw-edit").value).toBe("");
  });

  test("maps auth-headers-container-a2a-edit to auth-headers-json-a2a-edit", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container-a2a-edit"></div>
      <input id="auth-headers-json-a2a-edit" value="old" />
    `;

    loadAuthHeaders("auth-headers-container-a2a-edit", []);

    expect(document.getElementById("auth-headers-json-a2a-edit").value).toBe("");
  });

  test("handles header with non-string value", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container"></div>
      <input id="auth-headers-json" />
    `;

    loadAuthHeaders("auth-headers-container", [
      { key: "X-Key", value: 12345 },
    ]);

    const container = document.getElementById("auth-headers-container");
    const valueInput = container.querySelector(".auth-header-value");
    expect(valueInput.value).toBe("");
  });
});

// ---------------------------------------------------------------------------
// toggleInputMask - extended coverage
// ---------------------------------------------------------------------------
describe("toggleInputMask - extended", () => {
  test("re-masks stored secret when hiding", () => {
    document.body.innerHTML = `
      <input id="test-input" type="text" value="revealed-secret"
             data-is-masked="true" data-real-value="revealed-secret"
             data-sensitive-label="key" />
    `;
    const input = document.getElementById("test-input");
    const button = document.createElement("button");
    button.textContent = "Hide";

    toggleInputMask(input, button);

    expect(input.type).toBe("password");
    expect(input.value).toBe("*****");
    expect(button.textContent).toBe("Show");
  });

  test("updates aria-label with default label when data-sensitive-label is missing", () => {
    document.body.innerHTML = `
      <input id="test-input" type="password" value="secret" />
    `;
    const input = document.getElementById("test-input");
    const button = document.createElement("button");

    toggleInputMask(input, button);

    expect(button.getAttribute("aria-label")).toContain("Hide");
  });

  test("calls updateAuthHeadersJSON when inside auth-headers-container", () => {
    document.body.innerHTML = `
      <div id="auth-headers-container-gw">
        <div id="auth-header-1">
          <input id="test-input" type="password" value="secret"
                 class="auth-header-value" data-sensitive-label="header" />
          <input class="auth-header-key" value="X-Key" />
        </div>
      </div>
      <input id="auth-headers-json-gw" />
    `;
    const input = document.getElementById("test-input");
    const button = document.createElement("button");

    toggleInputMask(input, button);

    // After toggle, updateAuthHeadersJSON should have been called
    // The JSON input should have been updated
    expect(input.type).toBe("text");
  });
});

// ---------------------------------------------------------------------------
// handleAuthTypeSelection - extended coverage for authheaders
// ---------------------------------------------------------------------------
describe("handleAuthTypeSelection - authheaders with container", () => {
  test("shows authheaders fields and adds header row when container is empty", () => {
    document.body.innerHTML = `
      <div id="headers-section">
        <div id="test-container"></div>
      </div>
    `;
    const basic = document.createElement("div");
    const bearer = document.createElement("div");
    const headersFields = document.getElementById("headers-section");
    const oauth = document.createElement("div");
    const queryParam = document.createElement("div");

    handleAuthTypeSelection("authheaders", basic, bearer, headersFields, oauth, queryParam);

    expect(headersFields.style.display).toBe("block");
  });
});

// ---------------------------------------------------------------------------
// handleAuthTypeChange - extended coverage
// ---------------------------------------------------------------------------
describe("handleAuthTypeChange - extended", () => {
  test("shows authheaders fields", () => {
    document.body.innerHTML = `
      <div id="auth-basic-fields-gw" style="display:none"></div>
      <div id="auth-bearer-fields-gw" style="display:none"></div>
      <div id="auth-headers-fields-gw" style="display:none"></div>
      <div id="auth-oauth-fields-gw" style="display:none"></div>
      <div id="auth-query_param-fields-gw" style="display:none"></div>
    `;

    const context = { id: "auth-type-gw", value: "authheaders" };
    handleAuthTypeChange.call(context);

    expect(document.getElementById("auth-headers-fields-gw").style.display).toBe("block");
  });

  test("shows oauth fields", () => {
    document.body.innerHTML = `
      <div id="auth-basic-fields-gw" style="display:none"></div>
      <div id="auth-bearer-fields-gw" style="display:none"></div>
      <div id="auth-headers-fields-gw" style="display:none"></div>
      <div id="auth-oauth-fields-gw" style="display:none"></div>
      <div id="auth-query_param-fields-gw" style="display:none"></div>
    `;

    const context = { id: "auth-type-gw", value: "oauth" };
    handleAuthTypeChange.call(context);

    expect(document.getElementById("auth-oauth-fields-gw").style.display).toBe("block");
  });

  test("shows query_param fields", () => {
    document.body.innerHTML = `
      <div id="auth-basic-fields-gw" style="display:none"></div>
      <div id="auth-bearer-fields-gw" style="display:none"></div>
      <div id="auth-headers-fields-gw" style="display:none"></div>
      <div id="auth-oauth-fields-gw" style="display:none"></div>
      <div id="auth-query_param-fields-gw" style="display:none"></div>
    `;

    const context = { id: "auth-type-gw", value: "query_param" };
    handleAuthTypeChange.call(context);

    expect(document.getElementById("auth-query_param-fields-gw").style.display).toBe("block");
  });
});

// ---------------------------------------------------------------------------
// handleOAuthGrantTypeChange - extended (a2a prefix)
// ---------------------------------------------------------------------------
describe("handleOAuthGrantTypeChange - a2a prefix", () => {
  test("shows auth code fields for a2a authorization_code grant", () => {
    document.body.innerHTML = `
      <div id="oauth-auth-code-fields-a2a" style="display:none">
        <input type="url" />
      </div>
      <div id="oauth-username-field-a2a" style="display:none"></div>
      <div id="oauth-password-field-a2a" style="display:none"></div>
    `;

    const context = { id: "oauth-grant-type-a2a", value: "authorization_code" };
    handleOAuthGrantTypeChange.call(context);

    expect(document.getElementById("oauth-auth-code-fields-a2a").style.display).toBe("block");
  });

  test("shows password fields for a2a password grant", () => {
    document.body.innerHTML = `
      <div id="oauth-auth-code-fields-a2a" style="display:none"></div>
      <div id="oauth-username-field-a2a" style="display:none"></div>
      <div id="oauth-password-field-a2a" style="display:none"></div>
      <input id="oauth-username-a2a" />
      <input id="oauth-password-a2a" />
    `;

    const context = { id: "oauth-grant-type-a2a", value: "password" };
    handleOAuthGrantTypeChange.call(context);

    expect(document.getElementById("oauth-username-field-a2a").style.display).toBe("block");
    expect(document.getElementById("oauth-password-field-a2a").style.display).toBe("block");
  });
});
