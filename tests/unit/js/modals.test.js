/**
 * Unit tests for modals.js module
 * Tests: registerModalCleanup, openModal, closeModal, resetModalState,
 *        showCopyableModal, showApiKeyModal, closeApiKeyModal, submitApiKeyForm,
 *        toggleGrpcTlsFields, viewGrpcMethods
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

import {
  registerModalCleanup,
  openModal,
  closeModal,
  resetModalState,
  showCopyableModal,
  showApiKeyModal,
  closeApiKeyModal,
  submitApiKeyForm,
  toggleGrpcTlsFields,
  viewGrpcMethods,
} from "../../../mcpgateway/admin_ui/modals.js";
import { AppState } from "../../../mcpgateway/admin_ui/appState.js";

vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
}));
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  getCookie: vi.fn(() => "test-jwt"),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
}));

beforeEach(() => {
  AppState.activeModals.clear();
});

afterEach(() => {
  document.body.innerHTML = "";
  AppState.activeModals.clear();
});

// ---------------------------------------------------------------------------
// registerModalCleanup
// ---------------------------------------------------------------------------
describe("registerModalCleanup", () => {
  test("registers a callback for a known modal type", () => {
    const cb = vi.fn();
    registerModalCleanup("gatewayTest", cb);
    // No direct assertion; we verify via closeModal triggering it
  });

  test("ignores unknown modal types", () => {
    expect(() => registerModalCleanup("unknownType", vi.fn())).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// openModal
// ---------------------------------------------------------------------------
describe("openModal", () => {
  test("removes hidden class and tracks modal as active", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const modal = document.createElement("div");
    modal.id = "test-modal";
    modal.classList.add("hidden");
    document.body.appendChild(modal);

    openModal("test-modal");
    expect(modal.classList.contains("hidden")).toBe(false);
    expect(AppState.isModalActive("test-modal")).toBe(true);
    consoleSpy.mockRestore();
  });

  test("warns if modal is already active", () => {
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const modal = document.createElement("div");
    modal.id = "test-modal";
    document.body.appendChild(modal);

    openModal("test-modal");
    openModal("test-modal");
    expect(consoleSpy).toHaveBeenCalledWith(expect.stringContaining("already active"));
    consoleSpy.mockRestore();
    logSpy.mockRestore();
  });

  test("logs error if modal element not found", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    openModal("nonexistent");
    expect(errorSpy).toHaveBeenCalledWith(expect.stringContaining("not found"));
    errorSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// closeModal
// ---------------------------------------------------------------------------
describe("closeModal", () => {
  test("adds hidden class and removes modal from active set", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const modal = document.createElement("div");
    modal.id = "test-modal";
    document.body.appendChild(modal);

    AppState.setModalActive("test-modal");
    closeModal("test-modal");
    expect(modal.classList.contains("hidden")).toBe(true);
    expect(AppState.isModalActive("test-modal")).toBe(false);
    consoleSpy.mockRestore();
  });

  test("clears content of specified clearId element", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const modal = document.createElement("div");
    modal.id = "test-modal";
    document.body.appendChild(modal);

    const result = document.createElement("div");
    result.id = "result-area";
    result.innerHTML = "<p>old content</p>";
    document.body.appendChild(result);

    closeModal("test-modal", "result-area");
    expect(result.innerHTML).toBe("");
    consoleSpy.mockRestore();
  });

  test("calls registered cleanup callback for gateway-test-modal", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const cleanup = vi.fn();
    registerModalCleanup("gatewayTest", cleanup);

    const modal = document.createElement("div");
    modal.id = "gateway-test-modal";
    document.body.appendChild(modal);

    closeModal("gateway-test-modal");
    expect(cleanup).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  test("logs error if modal element not found", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    closeModal("nonexistent");
    expect(errorSpy).toHaveBeenCalledWith(expect.stringContaining("not found"));
    errorSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// resetModalState
// ---------------------------------------------------------------------------
describe("resetModalState", () => {
  test("clears dynamic content and resets forms", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const modal = document.createElement("div");
    modal.id = "test-modal";

    const dynamic = document.createElement("div");
    dynamic.setAttribute("data-dynamic-content", "");
    dynamic.innerHTML = "<p>dynamic</p>";
    modal.appendChild(dynamic);

    const form = document.createElement("form");
    const input = document.createElement("input");
    input.value = "dirty";
    form.appendChild(input);
    modal.appendChild(form);

    document.body.appendChild(modal);

    resetModalState("test-modal");
    expect(dynamic.innerHTML).toBe("");
    consoleSpy.mockRestore();
  });

  test("removes error message elements from forms", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const modal = document.createElement("div");
    modal.id = "test-modal";

    const form = document.createElement("form");
    const err = document.createElement("span");
    err.className = "error-message";
    err.textContent = "Error";
    form.appendChild(err);
    modal.appendChild(form);
    document.body.appendChild(modal);

    resetModalState("test-modal");
    expect(form.querySelector(".error-message")).toBeNull();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// showCopyableModal
// ---------------------------------------------------------------------------
describe("showCopyableModal", () => {
  test("creates modal overlay with title and message", () => {
    showCopyableModal("Test Title", "Test message content", "info");
    const overlay = document.getElementById("copyable-modal-overlay");
    expect(overlay).not.toBeNull();
    expect(overlay.innerHTML).toContain("Test Title");
    expect(overlay.innerHTML).toContain("Test message content");
  });

  test("removes existing modal before creating new one", () => {
    showCopyableModal("First", "First msg");
    showCopyableModal("Second", "Second msg");
    const overlays = document.querySelectorAll("#copyable-modal-overlay");
    expect(overlays.length).toBe(1);
    expect(overlays[0].innerHTML).toContain("Second");
  });

  test("close button removes the overlay", () => {
    showCopyableModal("Title", "Msg");
    const closeBtn = document.getElementById("copyable-modal-close");
    closeBtn.click();
    expect(document.getElementById("copyable-modal-overlay")).toBeNull();
  });

  test("supports success type styling", () => {
    showCopyableModal("Done", "All good", "success");
    const overlay = document.getElementById("copyable-modal-overlay");
    expect(overlay.innerHTML).toContain("green");
  });

  test("supports error type styling", () => {
    showCopyableModal("Error", "Something broke", "error");
    const overlay = document.getElementById("copyable-modal-overlay");
    expect(overlay.innerHTML).toContain("red");
  });
});

// ---------------------------------------------------------------------------
// showApiKeyModal / closeApiKeyModal
// ---------------------------------------------------------------------------
describe("showApiKeyModal / closeApiKeyModal", () => {
  function setupApiKeyModal() {
    const modal = document.createElement("div");
    modal.id = "api-key-modal";
    modal.classList.add("hidden");
    document.body.appendChild(modal);

    const serverId = document.createElement("input");
    serverId.id = "modal-server-id";
    document.body.appendChild(serverId);

    const serverName = document.createElement("span");
    serverName.id = "modal-server-name";
    document.body.appendChild(serverName);

    const customName = document.createElement("input");
    customName.id = "modal-custom-name";
    document.body.appendChild(customName);

    const form = document.createElement("form");
    form.id = "api-key-form";
    document.body.appendChild(form);

    return modal;
  }

  test("opens modal and sets server details", () => {
    const modal = setupApiKeyModal();
    showApiKeyModal("srv-1", "My Server", "http://example.com");
    expect(modal.classList.contains("hidden")).toBe(false);
    expect(document.getElementById("modal-server-id").value).toBe("srv-1");
    expect(document.getElementById("modal-server-name").textContent).toBe("My Server");
  });

  test("closes modal and resets form", () => {
    const modal = setupApiKeyModal();
    showApiKeyModal("srv-1", "My Server", "http://example.com");
    closeApiKeyModal();
    expect(modal.classList.contains("hidden")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// submitApiKeyForm
// ---------------------------------------------------------------------------
describe("submitApiKeyForm", () => {
  test("sends registration request via fetch", async () => {
    window.ROOT_PATH = "";

    const serverId = document.createElement("input");
    serverId.id = "modal-server-id";
    serverId.value = "srv-1";
    document.body.appendChild(serverId);

    const customName = document.createElement("input");
    customName.id = "modal-custom-name";
    customName.value = "Custom";
    document.body.appendChild(customName);

    const apiKey = document.createElement("input");
    apiKey.id = "modal-api-key";
    apiKey.value = "secret-key";
    document.body.appendChild(apiKey);

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      json: () => Promise.resolve({ success: true }),
    });

    const event = { preventDefault: vi.fn() };
    submitApiKeyForm(event);

    expect(event.preventDefault).toHaveBeenCalled();
    expect(fetchSpy).toHaveBeenCalledWith(
      "/admin/mcp-registry/srv-1/register",
      expect.objectContaining({ method: "POST" })
    );

    fetchSpy.mockRestore();
    delete window.ROOT_PATH;
  });
});

// ---------------------------------------------------------------------------
// toggleGrpcTlsFields
// ---------------------------------------------------------------------------
describe("toggleGrpcTlsFields", () => {
  test("shows cert and key fields when TLS is enabled", () => {
    const checkbox = document.createElement("input");
    checkbox.id = "grpc-tls-enabled";
    checkbox.type = "checkbox";
    checkbox.checked = true;
    document.body.appendChild(checkbox);

    const cert = document.createElement("div");
    cert.id = "grpc-tls-cert-field";
    cert.classList.add("hidden");
    document.body.appendChild(cert);

    const key = document.createElement("div");
    key.id = "grpc-tls-key-field";
    key.classList.add("hidden");
    document.body.appendChild(key);

    toggleGrpcTlsFields();
    expect(cert.classList.contains("hidden")).toBe(false);
    expect(key.classList.contains("hidden")).toBe(false);
  });

  test("hides cert and key fields when TLS is disabled", () => {
    const checkbox = document.createElement("input");
    checkbox.id = "grpc-tls-enabled";
    checkbox.type = "checkbox";
    checkbox.checked = false;
    document.body.appendChild(checkbox);

    const cert = document.createElement("div");
    cert.id = "grpc-tls-cert-field";
    document.body.appendChild(cert);

    const key = document.createElement("div");
    key.id = "grpc-tls-key-field";
    document.body.appendChild(key);

    toggleGrpcTlsFields();
    expect(cert.classList.contains("hidden")).toBe(true);
    expect(key.classList.contains("hidden")).toBe(true);
  });

  test("does not throw when elements are missing", () => {
    expect(() => toggleGrpcTlsFields()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// viewGrpcMethods
// ---------------------------------------------------------------------------
describe("viewGrpcMethods", () => {
  test("fetches methods and alerts results", async () => {
    window.ROOT_PATH = "";
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      json: () =>
        Promise.resolve({
          methods: [
            { full_name: "pkg.Service/Method", input_type: "Req", output_type: "Res" },
          ],
        }),
    });
    const alertSpy = vi.spyOn(globalThis, "alert").mockImplementation(() => {});

    viewGrpcMethods("svc-1");

    // Wait for promise chain
    await new Promise((r) => setTimeout(r, 10));

    expect(fetchSpy).toHaveBeenCalledWith(
      "/admin/grpc/svc-1/methods",
      expect.objectContaining({ method: "GET" })
    );
    expect(alertSpy).toHaveBeenCalledWith(expect.stringContaining("pkg.Service/Method"));

    fetchSpy.mockRestore();
    alertSpy.mockRestore();
    delete window.ROOT_PATH;
  });

  test("shows message when no methods found", async () => {
    window.ROOT_PATH = "";
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      json: () => Promise.resolve({ methods: [] }),
    });
    const alertSpy = vi.spyOn(globalThis, "alert").mockImplementation(() => {});

    viewGrpcMethods("svc-2");
    await new Promise((r) => setTimeout(r, 10));

    expect(alertSpy).toHaveBeenCalledWith(expect.stringContaining("No methods"));

    fetchSpy.mockRestore();
    alertSpy.mockRestore();
    delete window.ROOT_PATH;
  });
});
