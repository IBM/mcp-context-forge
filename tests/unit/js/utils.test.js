/**
 * Unit tests for utils.js module
 * Tests: createMemoizedInit, safeGetElement, safeSetValue, isInactiveChecked,
 *        fetchWithTimeout, handleFetchError, showErrorMessage, showSuccessMessage,
 *        parseUriTemplate, isAdminUser, copyToClipboard, copyJsonToClipboard,
 *        getCookie, getCurrentTeamId, getCurrentTeamName, updateEditToolUrl,
 *        formatTimestamp, handleKeydown, getRootPath, showToast, showNotification,
 *        isValidBase64, refreshLogs, truncateText, decodeHtml
 */

import { describe, test, expect, vi, afterEach, beforeEach } from "vitest";

import {
  createMemoizedInit,
  safeGetElement,
  safeSetValue,
  isInactiveChecked,
  fetchWithTimeout,
  handleFetchError,
  showErrorMessage,
  showSuccessMessage,
  parseUriTemplate,
  isAdminUser,
  copyToClipboard,
  copyJsonToClipboard,
  getCookie,
  getCurrentTeamId,
  getCurrentTeamName,
  updateEditToolUrl,
  formatTimestamp,
  handleKeydown,
  getRootPath,
  showToast,
  showNotification,
  isValidBase64,
  refreshLogs,
  truncateText,
  decodeHtml,
  getPaginationParams,
  buildTableUrl,
  makeCopyIdButton,
  handleDeleteUserError,
} from "../../../mcpgateway/admin_ui/utils.js";

afterEach(() => {
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
  delete window.IS_ADMIN;
  delete window.USERTEAMSDATA;
  delete window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT;
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// createMemoizedInit
// ---------------------------------------------------------------------------
describe("createMemoizedInit", () => {
  test("runs the init function on first call", async () => {
    const fn = vi.fn(() => "result");
    const { init } = createMemoizedInit(fn, 300, "Test");
    const result = await init();
    expect(fn).toHaveBeenCalledOnce();
    expect(result).toBe("result");
  });

  test("skips subsequent calls after initialization", async () => {
    const fn = vi.fn();
    const { init } = createMemoizedInit(fn, 300, "Test");
    await init();
    await init();
    expect(fn).toHaveBeenCalledOnce();
  });

  test("reset allows re-initialization", async () => {
    const fn = vi.fn();
    const { init, reset } = createMemoizedInit(fn, 300, "Test");
    await init();
    reset();
    await init();
    expect(fn).toHaveBeenCalledTimes(2);
  });

  test("handles errors and allows retry", async () => {
    let callCount = 0;
    const fn = vi.fn(() => {
      callCount++;
      if (callCount === 1) throw new Error("fail");
      return "ok";
    });
    const { init } = createMemoizedInit(fn, 300, "Test");
    await expect(init()).rejects.toThrow("fail");
    const result = await init();
    expect(result).toBe("ok");
  });

  test("debouncedInit delays execution", async () => {
    vi.useFakeTimers();
    const fn = vi.fn();
    const { debouncedInit } = createMemoizedInit(fn, 100, "Test");
    debouncedInit();
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(100);
    expect(fn).toHaveBeenCalledOnce();
    vi.useRealTimers();
  });

  test("debouncedInit cancels previous pending call", async () => {
    vi.useFakeTimers();
    const fn = vi.fn();
    const { debouncedInit } = createMemoizedInit(fn, 100, "Test");
    debouncedInit();
    debouncedInit();
    vi.advanceTimersByTime(100);
    expect(fn).toHaveBeenCalledOnce();
    vi.useRealTimers();
  });

  test("reset clears pending debounced calls", () => {
    vi.useFakeTimers();
    const fn = vi.fn();
    const { debouncedInit, reset } = createMemoizedInit(fn, 100, "Test");
    debouncedInit();
    reset();
    vi.advanceTimersByTime(200);
    expect(fn).not.toHaveBeenCalled();
    vi.useRealTimers();
  });
});

// ---------------------------------------------------------------------------
// safeGetElement
// ---------------------------------------------------------------------------
describe("safeGetElement", () => {
  test("returns element when it exists", () => {
    document.body.innerHTML = '<div id="test-el"></div>';
    const el = safeGetElement("test-el");
    expect(el).not.toBeNull();
    expect(el.id).toBe("test-el");
  });

  test("returns null for missing element", () => {
    const el = safeGetElement("nonexistent");
    expect(el).toBeNull();
  });

  test("logs warning for missing element by default", () => {
    const spy = vi.spyOn(console, "warn").mockImplementation(() => {});
    safeGetElement("nonexistent");
    expect(spy).toHaveBeenCalledWith(
      expect.stringContaining("nonexistent")
    );
  });

  test("suppresses warning when suppressWarning is true", () => {
    const spy = vi.spyOn(console, "warn").mockImplementation(() => {});
    safeGetElement("nonexistent", true);
    expect(spy).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// safeSetValue
// ---------------------------------------------------------------------------
describe("safeSetValue", () => {
  test("sets value on existing element", () => {
    document.body.innerHTML = '<input id="test-input" />';
    safeSetValue("test-input", "hello");
    expect(document.getElementById("test-input").value).toBe("hello");
  });

  test("does nothing when element not found", () => {
    expect(() => safeSetValue("nonexistent", "val")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// isInactiveChecked
// ---------------------------------------------------------------------------
describe("isInactiveChecked", () => {
  test("returns true when checkbox is checked", () => {
    document.body.innerHTML = '<input type="checkbox" id="show-inactive-tools" checked />';
    expect(isInactiveChecked("tools")).toBe(true);
  });

  test("returns false when checkbox is unchecked", () => {
    document.body.innerHTML = '<input type="checkbox" id="show-inactive-tools" />';
    expect(isInactiveChecked("tools")).toBe(false);
  });

  test("returns false when checkbox element does not exist", () => {
    expect(isInactiveChecked("tools")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// fetchWithTimeout
// ---------------------------------------------------------------------------
describe("fetchWithTimeout", () => {
  test("returns response on success", async () => {
    const mockResponse = {
      ok: true,
      status: 200,
      headers: { get: () => "5" },
      clone: () => ({ text: () => Promise.resolve("body") }),
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(mockResponse);
    const result = await fetchWithTimeout("/api/test");
    expect(result).toBe(mockResponse);
  });

  test("throws on network error", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(
      new Error("Failed to fetch")
    );
    await expect(fetchWithTimeout("/api/test")).rejects.toThrow(
      "Unable to connect to server"
    );
  });

  test("throws on abort/timeout", async () => {
    const abortError = new Error("aborted");
    abortError.name = "AbortError";
    vi.spyOn(globalThis, "fetch").mockRejectedValue(abortError);
    await expect(fetchWithTimeout("/api/test")).rejects.toThrow(
      "Request timed out"
    );
  });

  test("throws on status 0 (network/CORS)", async () => {
    const mockResponse = {
      ok: false,
      status: 0,
      headers: { get: () => null },
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(mockResponse);
    await expect(fetchWithTimeout("/api/test")).rejects.toThrow(
      "Network error or server is not responding"
    );
  });

  test("returns non-200 responses as-is", async () => {
    const mockResponse = {
      ok: false,
      status: 404,
      headers: { get: () => null },
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(mockResponse);
    const result = await fetchWithTimeout("/api/test");
    expect(result.status).toBe(404);
  });

  test("handles empty response body gracefully", async () => {
    const mockResponse = {
      ok: true,
      status: 200,
      headers: { get: () => null },
      clone: () => ({ text: () => Promise.resolve("") }),
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(mockResponse);
    const result = await fetchWithTimeout("/api/test");
    expect(result).toBe(mockResponse);
  });

  test("handles content-length 0 response", async () => {
    const mockResponse = {
      ok: true,
      status: 200,
      headers: { get: (h) => (h === "content-length" ? "0" : null) },
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(mockResponse);
    const result = await fetchWithTimeout("/api/test");
    expect(result).toBe(mockResponse);
  });

  test("improves empty response error messages", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(
      new Error("ERR_EMPTY_RESPONSE")
    );
    await expect(fetchWithTimeout("/api/test")).rejects.toThrow(
      "Server returned an empty response"
    );
  });
});

// ---------------------------------------------------------------------------
// handleFetchError
// ---------------------------------------------------------------------------
describe("handleFetchError", () => {
  test("returns abort message", () => {
    const error = new Error("aborted");
    error.name = "AbortError";
    expect(handleFetchError(error, "fetch data")).toContain("timed out");
  });

  test("returns HTTP error message", () => {
    const error = new Error("HTTP 500");
    expect(handleFetchError(error, "fetch data")).toContain("Server error");
  });

  test("returns network error message", () => {
    const error = new Error("NetworkError");
    expect(handleFetchError(error, "fetch data")).toContain("Network error");
  });

  test("returns generic error message", () => {
    const error = new Error("Something broke");
    expect(handleFetchError(error, "fetch data")).toContain("Something broke");
  });
});

// ---------------------------------------------------------------------------
// showErrorMessage
// ---------------------------------------------------------------------------
describe("showErrorMessage", () => {
  test("displays error in specific element", () => {
    document.body.innerHTML = '<div id="err"></div>';
    showErrorMessage("Bad request", "err");
    const el = document.getElementById("err");
    expect(el.textContent).toBe("Bad request");
    expect(el.classList.contains("text-red-600")).toBe(true);
  });

  test("creates global error notification when no elementId", () => {
    showErrorMessage("Global error");
    const divs = document.querySelectorAll(".bg-red-600");
    expect(divs.length).toBe(1);
    expect(divs[0].textContent).toBe("Global error");
  });

  test("auto-removes global notification after timeout", () => {
    vi.useFakeTimers();
    showErrorMessage("Temp error");
    expect(document.querySelectorAll(".bg-red-600").length).toBe(1);
    vi.advanceTimersByTime(5000);
    expect(document.querySelectorAll(".bg-red-600").length).toBe(0);
    vi.useRealTimers();
  });
});

// ---------------------------------------------------------------------------
// showSuccessMessage
// ---------------------------------------------------------------------------
describe("showSuccessMessage", () => {
  test("creates success notification", () => {
    showSuccessMessage("Done!");
    const divs = document.querySelectorAll(".bg-green-600");
    expect(divs.length).toBe(1);
    expect(divs[0].textContent).toBe("Done!");
  });

  test("auto-removes success notification after timeout", () => {
    vi.useFakeTimers();
    showSuccessMessage("Saved!");
    expect(document.querySelectorAll(".bg-green-600").length).toBe(1);
    vi.advanceTimersByTime(3000);
    expect(document.querySelectorAll(".bg-green-600").length).toBe(0);
    vi.useRealTimers();
  });
});

// ---------------------------------------------------------------------------
// parseUriTemplate
// ---------------------------------------------------------------------------
describe("parseUriTemplate", () => {
  test("extracts fields from URI template", () => {
    expect(parseUriTemplate("/api/{name}/items/{id}")).toEqual([
      "name",
      "id",
    ]);
  });

  test("returns empty array for no placeholders", () => {
    expect(parseUriTemplate("/api/items")).toEqual([]);
  });

  test("handles single placeholder", () => {
    expect(parseUriTemplate("/api/{id}")).toEqual(["id"]);
  });

  test("handles empty string", () => {
    expect(parseUriTemplate("")).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// isAdminUser
// ---------------------------------------------------------------------------
describe("isAdminUser", () => {
  test("returns true when IS_ADMIN is truthy", () => {
    window.IS_ADMIN = true;
    expect(isAdminUser()).toBe(true);
  });

  test("returns false when IS_ADMIN is falsy", () => {
    window.IS_ADMIN = false;
    expect(isAdminUser()).toBe(false);
  });

  test("returns false when IS_ADMIN is undefined", () => {
    delete window.IS_ADMIN;
    expect(isAdminUser()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// copyToClipboard
// ---------------------------------------------------------------------------
describe("copyToClipboard", () => {
  test("selects and copies element content", () => {
    document.body.innerHTML = '<input id="token-field" value="abc123" />';
    document.execCommand = vi.fn();
    copyToClipboard("token-field");
    expect(document.execCommand).toHaveBeenCalledWith("copy");
  });

  test("does nothing when element is not found", () => {
    document.execCommand = vi.fn();
    copyToClipboard("nonexistent");
    expect(document.execCommand).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// copyJsonToClipboard
// ---------------------------------------------------------------------------
describe("copyJsonToClipboard", () => {
  test("copies input value to clipboard", async () => {
    document.body.innerHTML = '<input id="json-input" value=\'{"key":"val"}\' />';
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText: writeTextMock } });
    copyJsonToClipboard("json-input");
    expect(writeTextMock).toHaveBeenCalledWith('{"key":"val"}');
  });

  test("copies textContent when element has no value", async () => {
    document.body.innerHTML = '<div id="json-div">{"a":1}</div>';
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText: writeTextMock } });
    copyJsonToClipboard("json-div");
    expect(writeTextMock).toHaveBeenCalledWith('{"a":1}');
  });

  test("does nothing when element not found", () => {
    const spy = vi.spyOn(console, "warn").mockImplementation(() => {});
    copyJsonToClipboard("nonexistent");
    expect(spy).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// getCookie
// ---------------------------------------------------------------------------
describe("getCookie", () => {
  test("retrieves cookie value", () => {
    Object.defineProperty(document, "cookie", {
      value: "session=abc123; theme=dark",
      configurable: true,
      writable: true,
    });
    expect(getCookie("session")).toBe("abc123");
    expect(getCookie("theme")).toBe("dark");
  });

  test("returns empty string for missing cookie", () => {
    Object.defineProperty(document, "cookie", {
      value: "session=abc123",
      configurable: true,
      writable: true,
    });
    expect(getCookie("nonexistent")).toBe("");
  });
});

// ---------------------------------------------------------------------------
// getCurrentTeamId
// ---------------------------------------------------------------------------
describe("getCurrentTeamId", () => {
  test("returns null when no team selector and no URL param", () => {
    expect(getCurrentTeamId()).toBeNull();
  });

  test("returns team_id from URL params as fallback", () => {
    const url = new URL(window.location.href);
    url.searchParams.set("team_id", "team-123");
    window.history.replaceState({}, "", url.toString());
    expect(getCurrentTeamId()).toBe("team-123");
    // cleanup
    window.history.replaceState({}, "", window.location.pathname);
  });

  test("returns null when team_id URL param is 'all'", () => {
    const url = new URL(window.location.href);
    url.searchParams.set("team_id", "all");
    window.history.replaceState({}, "", url.toString());
    expect(getCurrentTeamId()).toBeNull();
    window.history.replaceState({}, "", window.location.pathname);
  });

  test("returns null when team_id URL param is empty", () => {
    const url = new URL(window.location.href);
    url.searchParams.set("team_id", "");
    window.history.replaceState({}, "", url.toString());
    expect(getCurrentTeamId()).toBeNull();
    window.history.replaceState({}, "", window.location.pathname);
  });
});

// ---------------------------------------------------------------------------
// getCurrentTeamName
// ---------------------------------------------------------------------------
describe("getCurrentTeamName", () => {
  test("returns null when no team is selected", () => {
    expect(getCurrentTeamName()).toBeNull();
  });

  test("returns team name from USERTEAMSDATA", () => {
    const url = new URL(window.location.href);
    url.searchParams.set("team_id", "team-1");
    window.history.replaceState({}, "", url.toString());
    window.USERTEAMSDATA = [
      { id: "team-1", name: "Alpha Team", ispersonal: false },
    ];
    expect(getCurrentTeamName()).toBe("Alpha Team");
    window.history.replaceState({}, "", window.location.pathname);
  });

  test("returns team id as fallback when name not found", () => {
    const url = new URL(window.location.href);
    url.searchParams.set("team_id", "team-999");
    window.history.replaceState({}, "", url.toString());
    window.USERTEAMSDATA = [];
    expect(getCurrentTeamName()).toBe("team-999");
    window.history.replaceState({}, "", window.location.pathname);
  });
});

// ---------------------------------------------------------------------------
// updateEditToolUrl
// ---------------------------------------------------------------------------
describe("updateEditToolUrl", () => {
  test("makes URL field readonly when type is MCP", () => {
    document.body.innerHTML = `
      <select id="edit-tool-type"><option value="MCP" selected>MCP</option></select>
      <input id="edit-tool-url" />
    `;
    updateEditToolUrl();
    expect(document.getElementById("edit-tool-url").readOnly).toBe(true);
  });

  test("makes URL field editable when type is not MCP", () => {
    document.body.innerHTML = `
      <select id="edit-tool-type"><option value="REST" selected>REST</option></select>
      <input id="edit-tool-url" />
    `;
    updateEditToolUrl();
    expect(document.getElementById("edit-tool-url").readOnly).toBe(false);
  });

  test("does nothing when elements are missing", () => {
    expect(() => updateEditToolUrl()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// formatTimestamp
// ---------------------------------------------------------------------------
describe("formatTimestamp", () => {
  test("formats a timestamp string", () => {
    const result = formatTimestamp("2024-01-15T10:30:00Z");
    expect(typeof result).toBe("string");
    expect(result.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// handleKeydown
// ---------------------------------------------------------------------------
describe("handleKeydown", () => {
  test("calls callback on Enter key", () => {
    const callback = vi.fn();
    const event = new KeyboardEvent("keydown", { key: "Enter" });
    Object.defineProperty(event, "preventDefault", { value: vi.fn() });
    handleKeydown(event, callback);
    expect(callback).toHaveBeenCalledOnce();
    expect(event.preventDefault).toHaveBeenCalled();
  });

  test("calls callback on Space key", () => {
    const callback = vi.fn();
    const event = new KeyboardEvent("keydown", { key: " " });
    Object.defineProperty(event, "preventDefault", { value: vi.fn() });
    handleKeydown(event, callback);
    expect(callback).toHaveBeenCalledOnce();
  });

  test("does not call callback on other keys", () => {
    const callback = vi.fn();
    const event = new KeyboardEvent("keydown", { key: "Escape" });
    handleKeydown(event, callback);
    expect(callback).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// getRootPath
// ---------------------------------------------------------------------------
describe("getRootPath", () => {
  test("returns ROOT_PATH when set", () => {
    window.ROOT_PATH = "/gateway";
    expect(getRootPath()).toBe("/gateway");
  });

  test("returns empty string when ROOT_PATH not set", () => {
    delete window.ROOT_PATH;
    expect(getRootPath()).toBe("");
  });
});

// ---------------------------------------------------------------------------
// showNotification
// ---------------------------------------------------------------------------
describe("showNotification", () => {
  test("creates notification element in DOM", () => {
    showNotification("Test message", "success");
    const toasts = document.querySelectorAll(".bg-green-100");
    expect(toasts.length).toBe(1);
    expect(toasts[0].textContent).toBe("Test message");
  });

  test("creates error notification with red styling", () => {
    showNotification("Error!", "error");
    const toasts = document.querySelectorAll(".bg-red-100");
    expect(toasts.length).toBe(1);
  });

  test("creates info notification with blue styling", () => {
    showNotification("Info message", "info");
    const toasts = document.querySelectorAll(".bg-blue-100");
    expect(toasts.length).toBe(1);
  });

  test("auto-removes notification after 5 seconds", () => {
    vi.useFakeTimers();
    showNotification("Temp", "info");
    expect(document.querySelectorAll(".bg-blue-100").length).toBe(1);
    vi.advanceTimersByTime(5000);
    expect(document.querySelectorAll(".bg-blue-100").length).toBe(0);
    vi.useRealTimers();
  });
});

// ---------------------------------------------------------------------------
// isValidBase64
// ---------------------------------------------------------------------------
describe("isValidBase64", () => {
  test("returns true for valid base64", () => {
    expect(isValidBase64("SGVsbG8=")).toBe(true);
    expect(isValidBase64("YWJj")).toBe(true);
    expect(isValidBase64("YQ==")).toBe(true);
  });

  test("returns false for empty string", () => {
    expect(isValidBase64("")).toBe(false);
  });

  test("returns false for invalid base64", () => {
    expect(isValidBase64("not valid!")).toBe(false);
    expect(isValidBase64("abc$def")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// refreshLogs
// ---------------------------------------------------------------------------
describe("refreshLogs", () => {
  test("triggers htmx refresh when logs section exists", () => {
    document.body.innerHTML = '<div id="logs"></div>';
    window.htmx = { trigger: vi.fn() };
    refreshLogs();
    expect(window.htmx.trigger).toHaveBeenCalled();
    delete window.htmx;
  });

  test("does nothing when logs section missing", () => {
    expect(() => refreshLogs()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// truncateText
// ---------------------------------------------------------------------------
describe("truncateText", () => {
  test("truncates text longer than maxLength", () => {
    expect(truncateText("Hello World", 5)).toBe("Hello...");
  });

  test("returns text as-is when shorter than maxLength", () => {
    expect(truncateText("Hi", 10)).toBe("Hi");
  });

  test("returns empty string for null/undefined", () => {
    expect(truncateText(null, 10)).toBe("");
    expect(truncateText(undefined, 10)).toBe("");
  });
});

// ---------------------------------------------------------------------------
// decodeHtml
// ---------------------------------------------------------------------------
describe("decodeHtml", () => {
  test("decodes HTML entities", () => {
    expect(decodeHtml("&amp;")).toBe("&");
    expect(decodeHtml("&lt;script&gt;")).toBe("<script>");
  });

  test("returns empty string for null/undefined", () => {
    expect(decodeHtml(null)).toBe("");
    expect(decodeHtml(undefined)).toBe("");
  });

  test("returns plain text unchanged", () => {
    expect(decodeHtml("hello world")).toBe("hello world");
  });
});

// ---------------------------------------------------------------------------
// showToast
// ---------------------------------------------------------------------------
describe("showToast", () => {
  test("logs message when showNotification is not a global function", () => {
    const spy = vi.spyOn(console, "log").mockImplementation(() => {});
    showToast("toast message", "info");
    expect(spy).toHaveBeenCalledWith(expect.stringContaining("toast message"));
  });

  test("maps error type to danger for showNotification", () => {
    // showToast calls showNotification which creates a DOM element
    showToast("error toast", "error");
    // showToast maps "error" → "danger", which hits the default case in showNotification (blue)
    const toasts = document.querySelectorAll(".bg-blue-100");
    expect(toasts.length).toBe(1);
  });

  test("passes through non-error types directly", () => {
    showToast("success toast", "success");
    const toasts = document.querySelectorAll(".bg-green-100");
    expect(toasts.length).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// createMemoizedInit - extended (concurrent init guard)
// ---------------------------------------------------------------------------
describe("createMemoizedInit - extended", () => {
  test("blocks concurrent initialization", async () => {
    let resolveFn;
    const fn = vi.fn(
      () => new Promise((resolve) => { resolveFn = resolve; })
    );
    const { init } = createMemoizedInit(fn, 300, "ConcurrentTest");

    // Start first init (it blocks because the promise hasn't resolved)
    const firstCall = init();

    // Second call while first is still "initializing"
    // Since the sync init marks initializing=true and doesn't await,
    // the second call should skip
    const secondCall = init();
    await secondCall;

    // fn should only have been called once
    expect(fn).toHaveBeenCalledOnce();
  });

  test("init clears pending debounce timeout", async () => {
    vi.useFakeTimers();
    const fn = vi.fn();
    const { init, debouncedInit } = createMemoizedInit(fn, 200, "ClearDebounce");

    // Start a debounced call
    debouncedInit();

    // Call init directly (should clear the debounce)
    await init();

    // Advance timers past debounce delay
    vi.advanceTimersByTime(300);

    // fn should only have been called once (by init, not debounce)
    expect(fn).toHaveBeenCalledOnce();
    vi.useRealTimers();
  });
});

// ---------------------------------------------------------------------------
// getCurrentTeamId - extended (Alpine.js data stack)
// ---------------------------------------------------------------------------
describe("getCurrentTeamId - Alpine.js", () => {
  test("returns team from Alpine.js component", () => {
    document.body.innerHTML = '<div id="team-sel"></div>';
    const el = document.getElementById("team-sel");
    el.setAttribute("x-data", '{"selectedTeam":"team-abc"}');
    // Set up _x_dataStack to simulate Alpine.js
    el._x_dataStack = [{ selectedTeam: "team-abc" }];

    // querySelector with attribute selector should find it
    expect(getCurrentTeamId()).toBe("team-abc");
  });

  test("returns null when Alpine selectedTeam is empty", () => {
    document.body.innerHTML = '<div id="team-sel"></div>';
    const el = document.getElementById("team-sel");
    el.setAttribute("x-data", '{"selectedTeam":""}');
    el._x_dataStack = [{ selectedTeam: "" }];

    expect(getCurrentTeamId()).toBeNull();
  });

  test("returns null when Alpine selectedTeam is 'all'", () => {
    document.body.innerHTML = '<div id="team-sel"></div>';
    const el = document.getElementById("team-sel");
    el.setAttribute("x-data", '{"selectedTeam":"all"}');
    el._x_dataStack = [{ selectedTeam: "all" }];

    expect(getCurrentTeamId()).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// getCurrentTeamName - extended (Alpine.js paths)
// ---------------------------------------------------------------------------
describe("getCurrentTeamName - extended", () => {
  test("returns personal team name from USERTEAMSDATA", () => {
    const url = new URL(window.location.href);
    url.searchParams.set("team_id", "team-p");
    window.history.replaceState({}, "", url.toString());
    window.USERTEAMSDATA = [
      { id: "team-p", name: "Personal Team", ispersonal: true },
    ];
    expect(getCurrentTeamName()).toBe("Personal Team");
    window.history.replaceState({}, "", window.location.pathname);
  });

  test("returns team name from Alpine.js selectedTeamName", () => {
    document.body.innerHTML = '<div id="team-sel"></div>';
    const el = document.getElementById("team-sel");
    el.setAttribute("x-data", '{"selectedTeam":"team-1"}');
    el._x_dataStack = [{ selectedTeam: "team-1", selectedTeamName: "Alpha Squad" }];

    expect(getCurrentTeamName()).toBe("Alpha Squad");
  });

  test("returns team name from Alpine.js teams array", () => {
    document.body.innerHTML = '<div id="team-sel"></div>';
    const el = document.getElementById("team-sel");
    el.setAttribute("x-data", '{"selectedTeam":"team-2"}');
    el._x_dataStack = [{
      selectedTeam: "team-2",
      selectedTeamName: "All Teams",
      teams: [
        { id: "team-2", name: "Beta Team", ispersonal: false },
      ],
    }];

    expect(getCurrentTeamName()).toBe("Beta Team");
  });

  test("returns personal team name from Alpine teams array", () => {
    document.body.innerHTML = '<div id="team-sel"></div>';
    const el = document.getElementById("team-sel");
    el.setAttribute("x-data", '{"selectedTeam":"team-3"}');
    el._x_dataStack = [{
      selectedTeam: "team-3",
      selectedTeamName: "All Teams",
      teams: [
        { id: "team-3", name: "My Team", ispersonal: true },
      ],
    }];

    expect(getCurrentTeamName()).toBe("My Team");
  });
});

// ---------------------------------------------------------------------------
// fetchWithTimeout - extended
// ---------------------------------------------------------------------------
describe("fetchWithTimeout - extended", () => {
  test("uses custom timeout from window config", async () => {
    window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT = 5000;
    const mockResponse = {
      ok: true,
      status: 200,
      headers: { get: () => "5" },
      clone: () => ({ text: () => Promise.resolve("body") }),
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(mockResponse);
    const result = await fetchWithTimeout("/api/test");
    expect(result).toBe(mockResponse);
  });

  test("handles NetworkError message variant", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(
      new Error("NetworkError when attempting to fetch")
    );
    await expect(fetchWithTimeout("/api/test")).rejects.toThrow(
      "Unable to connect to server"
    );
  });
});

// ---------------------------------------------------------------------------
// copyJsonToClipboard - clipboard failure
// ---------------------------------------------------------------------------
describe("copyJsonToClipboard - extended", () => {
  test("shows error when clipboard write fails", async () => {
    document.body.innerHTML = '<input id="json-input" value="data" />';
    const writeTextMock = vi.fn().mockRejectedValue(new Error("denied"));
    Object.assign(navigator, { clipboard: { writeText: writeTextMock } });

    copyJsonToClipboard("json-input");

    // Wait for the promise to settle
    await vi.waitFor(() => {
      const errorDivs = document.querySelectorAll(".bg-red-600");
      expect(errorDivs.length).toBe(1);
    });
  });
});

// ---------------------------------------------------------------------------
// safeGetElement - error catch block
// ---------------------------------------------------------------------------
describe("safeGetElement - error handling", () => {
  test("returns null and logs error when getElementById throws", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(document, "getElementById").mockImplementation(() => {
      throw new Error("DOM error");
    });
    const el = safeGetElement("any-id");
    expect(el).toBeNull();
    expect(spy).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// fetchWithTimeout - actual abort via timeout callback
// ---------------------------------------------------------------------------
describe("fetchWithTimeout - actual abort callback", () => {
  test("fires timeout callback and aborts the request", async () => {
    vi.useFakeTimers();
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockImplementation((_url, options) => {
      return new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => {
          const err = new Error("aborted");
          err.name = "AbortError";
          reject(err);
        });
      });
    });
    const promise = fetchWithTimeout("/api/test", {}, 1000);
    vi.advanceTimersByTime(1000);
    await expect(promise).rejects.toThrow("Request timed out");
    vi.useRealTimers();
  });
});

// ---------------------------------------------------------------------------
// createMemoizedInit - re-entrant guard (lines 36-37)
// ---------------------------------------------------------------------------
describe("createMemoizedInit - re-entrant guard", () => {
  test("skips re-entrant init calls made during initialization", async () => {
    let callCount = 0;
    let outerInit;
    const { init } = createMemoizedInit(function () {
      callCount++;
      // Call init again while initializing=true — should be skipped
      outerInit();
    }, 300, "Reentry");
    outerInit = init;
    await init();
    expect(callCount).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// copyToClipboard - extended coverage for uncovered branches
// ---------------------------------------------------------------------------
describe("copyToClipboard - extended", () => {
  afterEach(() => {
    Object.assign(navigator, { clipboard: null });
    if (typeof document.execCommand !== "undefined") {
      delete document.execCommand;
    }
  });

  test("shows error notification when textToCopy is empty", async () => {
    document.body.innerHTML = '<input id="empty-field" value="" />';
    Object.assign(navigator, { clipboard: null });
    await copyToClipboard("empty-field");
    const errorToasts = document.querySelectorAll(".bg-red-100");
    expect(errorToasts.length).toBe(1);
  });

  test("uses clipboard API when available and shows success notification", async () => {
    document.body.innerHTML = '<input id="token-field" value="mytoken" />';
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText: writeTextMock } });
    await copyToClipboard("token-field");
    expect(writeTextMock).toHaveBeenCalledWith("mytoken");
    const successToasts = document.querySelectorAll(".bg-green-100");
    expect(successToasts.length).toBeGreaterThanOrEqual(1);
  });

  test("uses textContent when element has no string value", async () => {
    document.body.innerHTML = '<div id="text-div">mytoken</div>';
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText: writeTextMock } });
    await copyToClipboard("text-div");
    expect(writeTextMock).toHaveBeenCalledWith("mytoken");
  });

  test("falls back to execCommand when clipboard API rejects", async () => {
    document.body.innerHTML = '<input id="token-field" value="mytoken" />';
    const writeTextMock = vi.fn().mockRejectedValue(new Error("denied"));
    Object.assign(navigator, { clipboard: { writeText: writeTextMock } });
    document.execCommand = vi.fn().mockReturnValue(true);
    vi.spyOn(console, "warn").mockImplementation(() => {});
    await copyToClipboard("token-field");
    expect(document.execCommand).toHaveBeenCalledWith("copy");
    const successToasts = document.querySelectorAll(".bg-green-100");
    expect(successToasts.length).toBeGreaterThanOrEqual(1);
  });

  test("returns false in fallback when execCommand is not a function", async () => {
    document.body.innerHTML = '<input id="token-field" value="mytoken" />';
    Object.assign(navigator, { clipboard: null });
    document.execCommand = "not-a-function";
    await copyToClipboard("token-field");
    const errorToasts = document.querySelectorAll(".bg-red-100");
    expect(errorToasts.length).toBeGreaterThanOrEqual(1);
  });

  test("catches execCommand error in fallback and shows failure notification", async () => {
    document.body.innerHTML = '<input id="token-field" value="mytoken" />';
    Object.assign(navigator, { clipboard: null });
    document.execCommand = vi.fn().mockImplementation(() => {
      throw new Error("execCommand failed");
    });
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    await copyToClipboard("token-field");
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("Fallback copy failed"),
      expect.any(Error)
    );
    const errorToasts = document.querySelectorAll(".bg-red-100");
    expect(errorToasts.length).toBeGreaterThanOrEqual(1);
  });
});

// ---------------------------------------------------------------------------
// getCurrentTeamId - with USER_TEAMS_DATA (covers isKnownTeamId .some path)
// ---------------------------------------------------------------------------
describe("getCurrentTeamId - with team data", () => {
  afterEach(() => {
    delete window.USER_TEAMS_DATA;
    delete window.USER_TEAMS;
    window.history.replaceState({}, "", window.location.pathname);
  });

  test("returns team id when found in USER_TEAMS_DATA", () => {
    window.USER_TEAMS_DATA = [{ id: "team-xyz", name: "My Team" }];
    const url = new URL(window.location.href);
    url.searchParams.set("team_id", "team-xyz");
    window.history.replaceState({}, "", url.toString());
    expect(getCurrentTeamId()).toBe("team-xyz");
  });

  test("returns null when team id not found in USER_TEAMS_DATA", () => {
    window.USER_TEAMS_DATA = [{ id: "team-other", name: "Other Team" }];
    const url = new URL(window.location.href);
    url.searchParams.set("team_id", "team-unknown");
    window.history.replaceState({}, "", url.toString());
    expect(getCurrentTeamId()).toBeNull();
  });

  test("uses USER_TEAMS when USER_TEAMS_DATA is not set", () => {
    window.USER_TEAMS = [{ id: "team-abc", name: "ABC Team" }];
    const url = new URL(window.location.href);
    url.searchParams.set("team_id", "team-abc");
    window.history.replaceState({}, "", url.toString());
    expect(getCurrentTeamId()).toBe("team-abc");
  });

  test("returns null when team id not found via Alpine.js and USER_TEAMS_DATA set", () => {
    document.body.innerHTML = '<div id="team-sel"></div>';
    const el = document.getElementById("team-sel");
    el.setAttribute("x-data", '{"selectedTeam":"team-nope"}');
    el._x_dataStack = [{ selectedTeam: "team-nope" }];
    window.USER_TEAMS_DATA = [{ id: "team-real", name: "Real Team" }];
    expect(getCurrentTeamId()).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// getPaginationParams
// ---------------------------------------------------------------------------
describe("getPaginationParams", () => {
  afterEach(() => {
    window.history.replaceState({}, "", window.location.pathname);
  });

  test("returns defaults when no URL params", () => {
    const params = getPaginationParams("tools");
    expect(params.page).toBe(1);
    expect(params.perPage).toBe(10);
    expect(params.includeInactive).toBeNull();
  });

  test("reads page and size from namespaced URL params", () => {
    const url = new URL(window.location.href);
    url.searchParams.set("tools_page", "3");
    url.searchParams.set("tools_size", "25");
    url.searchParams.set("tools_inactive", "true");
    window.history.replaceState({}, "", url.toString());
    const params = getPaginationParams("tools");
    expect(params.page).toBe(3);
    expect(params.perPage).toBe(25);
    expect(params.includeInactive).toBe("true");
  });

  test("ensures page is at least 1 when param is 0", () => {
    const url = new URL(window.location.href);
    url.searchParams.set("tools_page", "0");
    window.history.replaceState({}, "", url.toString());
    expect(getPaginationParams("tools").page).toBe(1);
  });

  test("uses default perPage of 10 when size param is 0 (falsy parseInt)", () => {
    // parseInt("0") = 0, falsy, so fallback to || 10 default
    const url = new URL(window.location.href);
    url.searchParams.set("tools_size", "0");
    window.history.replaceState({}, "", url.toString());
    expect(getPaginationParams("tools").perPage).toBe(10);
  });

  test("uses tableName prefix for namespacing", () => {
    const url = new URL(window.location.href);
    url.searchParams.set("servers_page", "5");
    url.searchParams.set("tools_page", "2");
    window.history.replaceState({}, "", url.toString());
    expect(getPaginationParams("servers").page).toBe(5);
    expect(getPaginationParams("tools").page).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// buildTableUrl
// ---------------------------------------------------------------------------
describe("buildTableUrl", () => {
  afterEach(() => {
    window.history.replaceState({}, "", window.location.pathname);
  });

  test("builds basic URL with page and per_page", () => {
    const url = buildTableUrl("tools", "/api/tools");
    expect(url).toContain("page=1");
    expect(url).toContain("per_page=10");
    expect(url).toMatch(/^\/api\/tools\?/);
  });

  test("includes non-empty additional params", () => {
    const url = buildTableUrl("tools", "/api/tools", { status: "active" });
    expect(url).toContain("status=active");
  });

  test("skips null, undefined, and empty string additional params", () => {
    const url = buildTableUrl("tools", "/api/tools", {
      a: null,
      b: undefined,
      c: "",
    });
    expect(url).not.toContain("a=");
    expect(url).not.toContain("b=");
    expect(url).not.toContain("c=");
  });

  test("URL include_inactive takes precedence over additionalParams value", () => {
    const u = new URL(window.location.href);
    u.searchParams.set("tools_inactive", "true");
    window.history.replaceState({}, "", u.toString());
    const url = buildTableUrl("tools", "/api/tools", { include_inactive: "false" });
    expect(url).toContain("include_inactive=true");
  });

  test("uses additionalParams include_inactive when URL param absent", () => {
    const url = buildTableUrl("tools", "/api/tools", { include_inactive: "false" });
    expect(url).toContain("include_inactive=false");
  });

  test("adds include_inactive from URL even when not in additionalParams", () => {
    const u = new URL(window.location.href);
    u.searchParams.set("tools_inactive", "1");
    window.history.replaceState({}, "", u.toString());
    const url = buildTableUrl("tools", "/api/tools", {});
    expect(url).toContain("include_inactive=1");
  });

  test("preserves namespaced query from URL", () => {
    const u = new URL(window.location.href);
    u.searchParams.set("tools_q", "myquery");
    window.history.replaceState({}, "", u.toString());
    const url = buildTableUrl("tools", "/api/tools");
    expect(url).toContain("q=myquery");
  });

  test("preserves namespaced tags from URL", () => {
    const u = new URL(window.location.href);
    u.searchParams.set("tools_tags", "tag1");
    window.history.replaceState({}, "", u.toString());
    const url = buildTableUrl("tools", "/api/tools");
    expect(url).toContain("tags=tag1");
  });

  test("uses page from URL when set", () => {
    const u = new URL(window.location.href);
    u.searchParams.set("tools_page", "4");
    u.searchParams.set("tools_size", "20");
    window.history.replaceState({}, "", u.toString());
    const url = buildTableUrl("tools", "/api/tools");
    expect(url).toContain("page=4");
    expect(url).toContain("per_page=20");
  });
});

// ---------------------------------------------------------------------------
// createMemoizedInit - default args
// ---------------------------------------------------------------------------
describe("createMemoizedInit - default args", () => {
  test("works with only the fn argument (uses defaults for debounceMs and name)", async () => {
    const fn = vi.fn();
    const { init } = createMemoizedInit(fn);
    await init();
    expect(fn).toHaveBeenCalledOnce();
  });
});

// ---------------------------------------------------------------------------
// handleFetchError - default operation arg
// ---------------------------------------------------------------------------
describe("handleFetchError - default arg", () => {
  test("uses default operation name when not provided", () => {
    const error = new Error("something");
    const msg = handleFetchError(error);
    expect(msg).toContain("operation");
  });
});

// ---------------------------------------------------------------------------
// showErrorMessage - element not found when elementId provided
// ---------------------------------------------------------------------------
describe("showErrorMessage - missing element", () => {
  test("does not throw when elementId given but element not found", () => {
    expect(() => showErrorMessage("Err", "nonexistent-element")).not.toThrow();
  });

  test("global notification removed before timeout does not throw", () => {
    vi.useFakeTimers();
    showErrorMessage("Temp error");
    const div = document.querySelector(".bg-red-600");
    div.parentNode.removeChild(div); // remove before timeout
    expect(() => vi.advanceTimersByTime(5000)).not.toThrow();
    vi.useRealTimers();
  });
});

// ---------------------------------------------------------------------------
// showSuccessMessage - removal before timeout
// ---------------------------------------------------------------------------
describe("showSuccessMessage - removal before timeout", () => {
  test("does not throw when toast removed before timeout fires", () => {
    vi.useFakeTimers();
    showSuccessMessage("Done");
    const div = document.querySelector(".bg-green-600");
    div.parentNode.removeChild(div);
    expect(() => vi.advanceTimersByTime(3000)).not.toThrow();
    vi.useRealTimers();
  });
});

// ---------------------------------------------------------------------------
// showNotification - default arg and removal before timeout
// ---------------------------------------------------------------------------
describe("showNotification - extra branches", () => {
  test("uses default type 'info' when no type provided", () => {
    showNotification("default type");
    const toasts = document.querySelectorAll(".bg-blue-100");
    expect(toasts.length).toBe(1);
  });

  test("does not throw when toast removed before auto-remove fires", () => {
    vi.useFakeTimers();
    showNotification("Temp", "info");
    const toast = document.querySelector(".bg-blue-100");
    toast.parentNode.removeChild(toast);
    expect(() => vi.advanceTimersByTime(5000)).not.toThrow();
    vi.useRealTimers();
  });
});

// ---------------------------------------------------------------------------
// showToast - default type arg
// ---------------------------------------------------------------------------
describe("showToast - default type", () => {
  test("uses default type 'info' when no type provided", () => {
    showToast("default toast");
    const toasts = document.querySelectorAll(".bg-blue-100");
    expect(toasts.length).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// copyToClipboard - div element (no select/setSelectionRange) + empty textContent
// ---------------------------------------------------------------------------
describe("copyToClipboard - div element branches", () => {
  afterEach(() => {
    Object.assign(navigator, { clipboard: null });
    if (typeof document.execCommand !== "undefined") {
      delete document.execCommand;
    }
  });

  test("fallback works with element that has no select or setSelectionRange", async () => {
    // A div does not have .select() or .setSelectionRange() - covers false branches
    document.body.innerHTML = '<div id="text-div">mytoken</div>';
    Object.assign(navigator, { clipboard: null });
    document.execCommand = vi.fn().mockReturnValue(true);
    await copyToClipboard("text-div");
    expect(document.execCommand).toHaveBeenCalledWith("copy");
  });

  test("shows error when textContent is empty string (covers binary-expr false arm)", async () => {
    // Empty div: typeof element.value !== "string", element.textContent = "" (falsy)
    document.body.innerHTML = '<div id="empty-div"></div>';
    Object.assign(navigator, { clipboard: null });
    await copyToClipboard("empty-div");
    const errorToasts = document.querySelectorAll(".bg-red-100");
    expect(errorToasts.length).toBeGreaterThanOrEqual(1);
  });
});

// ---------------------------------------------------------------------------
// copyJsonToClipboard - data-toast="off" suppresses success toast
// ---------------------------------------------------------------------------
describe("copyJsonToClipboard - data-toast off", () => {
  test("does not show success toast when data-toast is 'off'", async () => {
    document.body.innerHTML = '<input id="json-in" value="data" data-toast="off" />';
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText: writeTextMock } });
    copyJsonToClipboard("json-in");
    await vi.waitFor(() => expect(writeTextMock).toHaveBeenCalled());
    // No success message shown
    expect(document.querySelectorAll(".bg-green-600").length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// getCurrentTeamName - Alpine.js paths with missing teams
// ---------------------------------------------------------------------------
describe("getCurrentTeamName - additional Alpine.js branches", () => {
  afterEach(() => {
    window.history.replaceState({}, "", window.location.pathname);
    delete window.USER_TEAMS_DATA;
    delete window.USER_TEAMS;
    delete window.USERTEAMSDATA;
  });

  test("falls back to team id when Alpine has no teams array", () => {
    // Setup: selectedTeamName is "All Teams" and no teams array
    document.body.innerHTML = '<div id="team-sel"></div>';
    const el = document.getElementById("team-sel");
    el.setAttribute("x-data", '{"selectedTeam":"team-x"}');
    el._x_dataStack = [{ selectedTeam: "team-x", selectedTeamName: "All Teams" }];
    expect(getCurrentTeamName()).toBe("team-x");
  });

  test("falls back to team id when team not found in Alpine teams array", () => {
    document.body.innerHTML = '<div id="team-sel"></div>';
    const el = document.getElementById("team-sel");
    el.setAttribute("x-data", '{"selectedTeam":"team-y"}');
    el._x_dataStack = [{
      selectedTeam: "team-y",
      selectedTeamName: "All Teams",
      teams: [{ id: "team-other", name: "Other Team", ispersonal: false }],
    }];
    expect(getCurrentTeamName()).toBe("team-y");
  });
});

// ---------------------------------------------------------------------------
// handleDeleteUserError
// ---------------------------------------------------------------------------
describe("handleDeleteUserError", () => {
  test("does nothing when event.detail.successful is true", () => {
    const event = { detail: { successful: true, xhr: { responseText: "<p>Error</p>" } } };
    handleDeleteUserError(event);
    expect(document.querySelectorAll(".bg-red-600").length).toBe(0);
  });

  test("shows error message from response text when unsuccessful", () => {
    const event = { detail: { successful: false, xhr: { responseText: "<p>User not found</p>" } } };
    handleDeleteUserError(event);
    const errors = document.querySelectorAll(".bg-red-600");
    expect(errors.length).toBe(1);
    expect(errors[0].textContent).toBe("User not found");
  });

  test("falls back to 'Error deleting user' when responseText is empty", () => {
    const event = { detail: { successful: false, xhr: { responseText: "" } } };
    handleDeleteUserError(event);
    const errors = document.querySelectorAll(".bg-red-600");
    expect(errors.length).toBe(1);
    expect(errors[0].textContent).toBe("Error deleting user");
  });

  test("falls back to 'Error deleting user' when responseText is whitespace only", () => {
    const event = { detail: { successful: false, xhr: { responseText: "   " } } };
    handleDeleteUserError(event);
    const errors = document.querySelectorAll(".bg-red-600");
    expect(errors.length).toBe(1);
    expect(errors[0].textContent).toBe("Error deleting user");
  });

  test("strips HTML tags and shows only text content", () => {
    const event = {
      detail: {
        successful: false,
        xhr: { responseText: "<html><body><h1>403</h1><p>Forbidden: cannot delete admin</p></body></html>" },
      },
    };
    handleDeleteUserError(event);
    const errors = document.querySelectorAll(".bg-red-600");
    expect(errors.length).toBe(1);
    expect(errors[0].textContent).toContain("Forbidden: cannot delete admin");
    expect(errors[0].textContent).not.toContain("<");
  });
});

// ---------------------------------------------------------------------------
// makeCopyIdButton
// ---------------------------------------------------------------------------
describe("makeCopyIdButton", () => {
  afterEach(() => {
    Object.assign(navigator, { clipboard: null });
    if (typeof document.execCommand !== "undefined") {
      delete document.execCommand;
    }
  });

  test("creates a button element with correct attributes", () => {
    const btn = makeCopyIdButton("test-id");
    expect(btn.tagName).toBe("BUTTON");
    expect(btn.type).toBe("button");
    expect(btn.title).toBe("Copy ID to clipboard");
    expect(btn.textContent).toBe("📋 Copy");
  });

  test("copies id string using clipboard API on click", async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText: writeTextMock } });
    const btn = makeCopyIdButton("abc-123");
    document.body.appendChild(btn);
    btn.click();
    await vi.waitFor(() => {
      expect(writeTextMock).toHaveBeenCalledWith("abc-123");
    });
  });

  test("converts numeric id to string when copying", async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText: writeTextMock } });
    const btn = makeCopyIdButton(42);
    document.body.appendChild(btn);
    btn.click();
    await vi.waitFor(() => {
      expect(writeTextMock).toHaveBeenCalledWith("42");
    });
  });

  test("changes text to Copied on success and reverts after 2s", async () => {
    vi.useFakeTimers();
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText: writeTextMock } });
    const btn = makeCopyIdButton("my-id");
    document.body.appendChild(btn);
    btn.click();
    // Let the clipboard promise resolve (microtasks)
    await Promise.resolve();
    await Promise.resolve();
    expect(btn.textContent).toBe("✅ Copied!");
    vi.advanceTimersByTime(2000);
    expect(btn.textContent).toBe("📋 Copy");
    vi.useRealTimers();
  });

  test("changes text to Failed on clipboard error and reverts after 2s", async () => {
    vi.useFakeTimers();
    const writeTextMock = vi.fn().mockRejectedValue(new Error("denied"));
    Object.assign(navigator, { clipboard: { writeText: writeTextMock } });
    const btn = makeCopyIdButton("my-id");
    document.body.appendChild(btn);
    btn.click();
    await Promise.resolve();
    await Promise.resolve();
    expect(btn.textContent).toBe("❌ Failed");
    vi.advanceTimersByTime(2000);
    expect(btn.textContent).toBe("📋 Copy");
    vi.useRealTimers();
  });

  test("uses textarea fallback when clipboard API unavailable", async () => {
    Object.assign(navigator, { clipboard: null });
    document.execCommand = vi.fn().mockReturnValue(true);
    const btn = makeCopyIdButton("fallback-id");
    document.body.appendChild(btn);
    btn.click();
    await vi.waitFor(() => {
      expect(document.execCommand).toHaveBeenCalledWith("copy");
    });
  });

  test("shows failure text when fallback execCommand throws", async () => {
    vi.useFakeTimers();
    Object.assign(navigator, { clipboard: null });
    document.execCommand = vi.fn().mockImplementation(() => {
      throw new Error("execCommand failed");
    });
    const btn = makeCopyIdButton("fail-id");
    document.body.appendChild(btn);
    btn.click();
    await Promise.resolve();
    expect(btn.textContent).toBe("❌ Failed");
    vi.useRealTimers();
  });
});
