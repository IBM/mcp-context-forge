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

    await handleSubmitWithConfirmation(event, "tool");

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

    const result = handleSubmitWithConfirmation(event, "tool");

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

    await handleDeleteSubmit(event, "gateway", "test-gw");

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

    handleDeleteSubmit(event, "tool", "my-tool");

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

    await handleDeleteSubmit(event, "server");

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

    const result = handleDeleteSubmit(event, "resource");

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

    await handleDeleteSubmit(event, "tool", "t1");

    expect(fetchMock).toHaveBeenCalled();
    const callArgs = fetchMock.mock.calls[0];
    const formData = callArgs[1].body;
    expect(formData.get("team_id")).toBe("team-42");

    window.history.replaceState({}, "", window.location.pathname);
  });

  test("passes inactiveType to isInactiveChecked via hidden field value", async () => {
    // Add checked checkbox for "custom-type" so isInactiveChecked("custom-type") returns true
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.id = "show-inactive-custom-type";
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

    await handleDeleteSubmit(event, "tool", "t1", "custom-type");

    expect(capturedFormData.get("is_inactive_checked")).toBe("true");
  });
});
