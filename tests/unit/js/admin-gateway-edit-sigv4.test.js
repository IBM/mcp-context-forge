/**
 * Tests that the gateway edit form keeps a stored AWS SigV4 auth type.
 *
 * The edit form cannot edit SigV4 credentials. It shows a SigV4 option only for
 * SigV4 gateways, so Save does not post an empty auth type.
 */

import { describe, test, expect, beforeEach, afterEach, vi } from "vitest";

import { editGateway } from "../../../mcpgateway/admin_ui/gateways.js";

vi.mock("../../../mcpgateway/admin_ui/tokens.js", () => ({
  fetchWithAuth: vi.fn(),
  performTokenSearch: vi.fn(),
  getAuthToken: vi.fn(),
  getTeamNameById: vi.fn(),
  setupCreateTokenForm: vi.fn(),
  setupTokenListEventHandlers: vi.fn(),
  updateTeamScopingWarning: vi.fn(),
  loadTokensList: vi.fn(),
  debouncedServerSideTokenSearch: vi.fn(),
}));

function mountEditForm() {
  document.body.innerHTML = `
    <form id="edit-gateway-form">
      <select name="auth_type" id="auth-type-gw-edit">
        <option value="">None</option>
        <option value="basic">Basic</option>
        <option value="bearer">Bearer Token</option>
        <option value="authheaders">Custom Headers</option>
        <option value="oauth">OAuth 2.0</option>
        <option value="query_param">Query Parameter (INSECURE)</option>
        <option value="sigv4" hidden>AWS SigV4 (stored credentials kept)</option>
      </select>
    </form>`;
}

function stubGateway(gateway) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(gateway), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

beforeEach(() => {
  window.ROOT_PATH = "";
  vi.spyOn(console, "log").mockImplementation(() => {});
  vi.spyOn(console, "warn").mockImplementation(() => {});
  vi.spyOn(console, "error").mockImplementation(() => {});
  mountEditForm();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("editGateway - SigV4 auth type", () => {
  test("a SigV4 gateway loads with the SigV4 option shown and selected", async () => {
    stubGateway({ name: "aws", url: "https://example.com/mcp", authType: "sigv4" });

    await editGateway("gw-1");

    const select = document.getElementById("auth-type-gw-edit");
    expect(select.value).toBe("sigv4");
    expect(select.querySelector('option[value="sigv4"]').hidden).toBe(false);
  });

  test("a non-SigV4 gateway keeps the SigV4 option hidden", async () => {
    stubGateway({ name: "plain", url: "https://example.com/mcp", authType: "bearer" });

    await editGateway("gw-2");

    const select = document.getElementById("auth-type-gw-edit");
    expect(select.value).toBe("bearer");
    expect(select.querySelector('option[value="sigv4"]').hidden).toBe(true);
  });

  test("the SigV4 option is hidden again after editing a SigV4 gateway first", async () => {
    stubGateway({ name: "aws", url: "https://example.com/mcp", authType: "sigv4" });
    await editGateway("gw-1");

    stubGateway({ name: "plain", url: "https://example.com/mcp", authType: "" });
    await editGateway("gw-2");

    const select = document.getElementById("auth-type-gw-edit");
    expect(select.value).toBe("");
    expect(select.querySelector('option[value="sigv4"]').hidden).toBe(true);
  });
});
