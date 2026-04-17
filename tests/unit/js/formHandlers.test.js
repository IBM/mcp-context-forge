/**
 * Unit tests for formHandlers.js module
 * Tests: handleToggleSubmit, handleSubmitWithConfirmation, handleDeleteSubmit
 */

import { describe, test, expect, vi, afterEach } from "vitest";

import {
  handleToggleSubmit,
  handleSubmitWithConfirmation,
  handleDeleteSubmit,
} from "../../../mcpgateway/admin_ui/formHandlers.js";

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// handleToggleSubmit
// ---------------------------------------------------------------------------
describe("handleToggleSubmit", () => {
  test("prevents default and calls fetch with FormData", async () => {
    // Make isInactiveChecked("tools") return true via DOM
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.id = "show-inactive-tools";
    cb.checked = true;
    document.body.appendChild(cb);

    document.body.insertAdjacentHTML("beforeend", '<form id="test-form" action="/test"></form>');
    const form = document.getElementById("test-form");

    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    global.fetch = fetchMock;

    const event = { preventDefault: vi.fn(), target: form };

    await handleToggleSubmit(event, "tools");

    expect(event.preventDefault).toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/test"),
      expect.objectContaining({
        method: "POST",
        credentials: "include", // pragma: allowlist secret
        redirect: "manual",
      })
    );
  });

  test("includes is_inactive_checked in FormData", async () => {
    document.body.innerHTML = '<form id="test-form" action="/test"></form>';
    const form = document.getElementById("test-form");

    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    global.fetch = fetchMock;

    const event = { preventDefault: vi.fn(), target: form };

    await handleToggleSubmit(event, "gateways");

    expect(fetchMock).toHaveBeenCalled();
    const callArgs = fetchMock.mock.calls[0];
    const formData = callArgs[1].body;
    expect(formData.get("is_inactive_checked")).toBe("false");
  });
});

// ---------------------------------------------------------------------------
// handleSubmitWithConfirmation
// ---------------------------------------------------------------------------
describe("handleSubmitWithConfirmation", () => {
  test("shows confirmation dialog and submits on confirm", async () => {
    document.body.innerHTML = '<form id="test-form" action="/test"></form>';
    const form = document.getElementById("test-form");

    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    global.fetch = fetchMock;

    const event = { preventDefault: vi.fn(), target: form };

    vi.spyOn(window, "confirm").mockReturnValue(true);

    await handleSubmitWithConfirmation(event, "tools");

    // Confirmation message should use singular display name "tool", not plural "tools"
    expect(window.confirm).toHaveBeenCalledWith(
      expect.stringContaining("permanently delete this tool")
    );
    expect(fetchMock).toHaveBeenCalled();
  });

  test("does not submit when user cancels confirmation", () => {
    document.body.innerHTML = '<form id="test-form" action="/test"></form>';
    const form = document.getElementById("test-form");

    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    global.fetch = fetchMock;

    const event = { preventDefault: vi.fn(), target: form };

    vi.spyOn(window, "confirm").mockReturnValue(false);

    const result = handleSubmitWithConfirmation(event, "tools");

    expect(result).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// handleDeleteSubmit
// ---------------------------------------------------------------------------
describe("handleDeleteSubmit", () => {
  test("shows two confirmation dialogs and appends purge field on confirm", async () => {
    document.body.innerHTML = '<form id="test-form" action="/test"></form>';
    const form = document.getElementById("test-form");

    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    global.fetch = fetchMock;

    const event = { preventDefault: vi.fn(), target: form };

    vi.spyOn(window, "confirm")
      .mockReturnValueOnce(true) // first confirm (delete)
      .mockReturnValueOnce(true); // second confirm (purge metrics)

    await handleDeleteSubmit(event, "gateways", "test-gw");

    expect(window.confirm).toHaveBeenCalledTimes(2);
    const purgeField = form.querySelector('input[name="purge_metrics"]');
    expect(purgeField).not.toBeNull();
    expect(purgeField.value).toBe("true");
    expect(fetchMock).toHaveBeenCalled();
  });

  test("uses name in confirmation message when provided", () => {
    document.body.innerHTML = '<form id="test-form"></form>';
    const form = document.getElementById("test-form");
    form.submit = vi.fn();

    const event = { preventDefault: vi.fn(), target: form };

    vi.spyOn(window, "confirm")
      .mockReturnValueOnce(true)
      .mockReturnValueOnce(false);

    handleDeleteSubmit(event, "tools", "my-tool");

    // Confirmation message should use singular display name "tool", not plural "tools"
    expect(window.confirm).toHaveBeenCalledWith(
      expect.stringContaining('tool "my-tool"')
    );
  });

  test("does not purge metrics when user declines second confirmation", async () => {
    document.body.innerHTML = '<form id="test-form" action="/test"></form>';
    const form = document.getElementById("test-form");

    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    global.fetch = fetchMock;

    const event = { preventDefault: vi.fn(), target: form };

    vi.spyOn(window, "confirm")
      .mockReturnValueOnce(true)
      .mockReturnValueOnce(false);

    await handleDeleteSubmit(event, "catalog");

    const purgeField = form.querySelector('input[name="purge_metrics"]');
    expect(purgeField).toBeNull();
    expect(fetchMock).toHaveBeenCalled();
  });

  test("returns false when user cancels first confirmation", () => {
    document.body.innerHTML = '<form id="test-form"></form>';
    const form = document.getElementById("test-form");
    form.submit = vi.fn();

    const event = { preventDefault: vi.fn(), target: form };

    vi.spyOn(window, "confirm").mockReturnValue(false);

    const result = handleDeleteSubmit(event, "resources");

    expect(result).toBe(false);
    expect(form.submit).not.toHaveBeenCalled();
  });

  test("appends team_id from URL when present", async () => {
    const url = new URL(window.location.href);
    url.searchParams.set("team_id", "team-42");
    window.history.replaceState({}, "", url.toString());

    document.body.innerHTML = '<form id="test-form" action="/test"></form>';
    const form = document.getElementById("test-form");

    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    global.fetch = fetchMock;

    const event = { preventDefault: vi.fn(), target: form };

    vi.spyOn(window, "confirm")
      .mockReturnValueOnce(true)
      .mockReturnValueOnce(false);

    await handleDeleteSubmit(event, "tools", "t1");

    expect(fetchMock).toHaveBeenCalled();
    const callArgs = fetchMock.mock.calls[0];
    const formData = callArgs[1].body;
    expect(formData.get("team_id")).toBe("team-42");

    window.history.replaceState({}, "", window.location.pathname);
  });

  test("passes inactiveType to isInactiveChecked via hidden field value", async () => {
    // Add checked checkbox for "prompts" so isInactiveChecked("prompts") returns true
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.id = "show-inactive-prompts";
    cb.checked = true;
    document.body.appendChild(cb);

    document.body.insertAdjacentHTML("beforeend", '<form id="test-form"></form>');
    const form = document.getElementById("test-form");

    const event = { preventDefault: vi.fn(), target: form };

    vi.spyOn(window, "confirm")
      .mockReturnValueOnce(true)
      .mockReturnValueOnce(false);

    let capturedFormData;
    vi.spyOn(global, "fetch").mockImplementation((_url, options) => {
      capturedFormData = options.body;
      return Promise.resolve({ ok: true });
    });

    await handleDeleteSubmit(event, "tools", "t1", "prompts");

    expect(capturedFormData.get("is_inactive_checked")).toBe("true");
  });

  test("uses PANEL_SEARCH_CONFIG for A2A agents refresh (partialPath and targetSelector)", async () => {
    const form = document.createElement("form");
    form.id = "test-form";
    form.action = "/test";
    document.body.appendChild(form);

    const tableDiv = document.createElement("div");
    tableDiv.id = "agents-table";  // Correct ID per PANEL_SEARCH_CONFIG
    document.body.appendChild(tableDiv);

    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    global.fetch = fetchMock;

    // Mock HTMX
    const htmxAjaxMock = vi.fn();
    global.window.htmx = { ajax: htmxAjaxMock };
    global.window.ROOT_PATH = "";

    const event = { preventDefault: vi.fn(), target: form };

    vi.spyOn(window, "confirm")
      .mockReturnValueOnce(true)
      .mockReturnValueOnce(false);

    // type="agent" for the confirmation message, but inactiveType="a2a-agents" is used
    // for refresh lookup in PANEL_SEARCH_CONFIG (handleDeleteSubmit uses inactiveType || type)
    await handleDeleteSubmit(event, "agent", "test-agent", "a2a-agents");

    // Verify HTMX was called with correct partial path (a2a/partial) and target selector (#agents-table)
    expect(htmxAjaxMock).toHaveBeenCalledWith(
      'GET',
      expect.stringContaining('/admin/a2a/partial'),
      expect.objectContaining({
        target: '#agents-table',  // targetSelector from PANEL_SEARCH_CONFIG, not #a2a-agents-table
        swap: 'outerHTML'
      })
    );
  });

  test("uses PANEL_SEARCH_CONFIG for catalog/servers refresh", async () => {
    const form = document.createElement("form");
    form.id = "test-form";
    form.action = "/test";
    document.body.appendChild(form);

    const tableDiv = document.createElement("div");
    tableDiv.id = "servers-table";  // Correct ID per PANEL_SEARCH_CONFIG for catalog
    document.body.appendChild(tableDiv);

    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    global.fetch = fetchMock;

    // Mock HTMX
    const htmxAjaxMock = vi.fn();
    global.window.htmx = { ajax: htmxAjaxMock };
    global.window.ROOT_PATH = "";

    const event = { preventDefault: vi.fn(), target: form };

    vi.spyOn(window, "confirm")
      .mockReturnValueOnce(true)
      .mockReturnValueOnce(false);

    await handleDeleteSubmit(event, "catalog", "test-server", "catalog");

    // Verify HTMX was called with correct partial path (servers/partial) and target selector (#servers-table)
    expect(htmxAjaxMock).toHaveBeenCalledWith(
      'GET',
      expect.stringContaining('/admin/servers/partial'),
      expect.objectContaining({
        target: '#servers-table',  // targetSelector from PANEL_SEARCH_CONFIG for catalog
        swap: 'outerHTML'
      })
    );
  });

  test("throws error when PANEL_SEARCH_CONFIG is missing for a type", async () => {
    const form = document.createElement("form");
    form.id = "test-form";
    form.action = "/test";
    document.body.appendChild(form);

    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    global.fetch = fetchMock;

    // Mock HTMX
    const htmxAjaxMock = vi.fn();
    global.window.htmx = { ajax: htmxAjaxMock };
    global.window.ROOT_PATH = "";

    const event = { preventDefault: vi.fn(), target: form };

    vi.spyOn(window, "confirm")
      .mockReturnValueOnce(true)
      .mockReturnValueOnce(false);

    // Should throw error for unregistered entity type
    await expect(async () => {
      await handleDeleteSubmit(event, "unknown", "test-unknown", "unknown-type");
    }).rejects.toThrow('No PANEL_SEARCH_CONFIG found for type: unknown-type');

    // HTMX should NOT be called since error is thrown before refresh
    expect(htmxAjaxMock).not.toHaveBeenCalled();
  });
});
