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
