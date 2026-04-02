/**
 * Unit tests for appState.js module
 * Tests: AppState, registerCleanupToolTestState
 */

import { describe, test, expect, vi, afterEach } from "vitest";

import {
  AppState,
  registerCleanupToolTestState,
} from "../../../mcpgateway/admin_ui/appState.js";

afterEach(() => {
  // Reset AppState to clean defaults after each test
  AppState.parameterCount = 0;
  AppState.currentTestTool = null;
  AppState.toolTestResultEditor = null;
  AppState.isInitialized = false;
  AppState.pendingRequests.clear();
  AppState.activeModals.clear();
  AppState.currentTeamRelationshipFilter = "all";
  AppState.restrictedContextLogged = false;
  Object.keys(AppState.editors.gateway).forEach((key) => {
    AppState.editors.gateway[key] = null;
  });
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Parameter count management
// ---------------------------------------------------------------------------
describe("parameter count management", () => {
  test("getParameterCount returns current count", () => {
    expect(AppState.getParameterCount()).toBe(0);
  });

  test("incrementParameterCount increments and returns new value", () => {
    expect(AppState.incrementParameterCount()).toBe(1);
    expect(AppState.incrementParameterCount()).toBe(2);
    expect(AppState.getParameterCount()).toBe(2);
  });

  test("decrementParameterCount decrements and returns new value", () => {
    AppState.parameterCount = 3;
    expect(AppState.decrementParameterCount()).toBe(2);
    expect(AppState.decrementParameterCount()).toBe(1);
  });

  test("decrementParameterCount does not go below 0", () => {
    AppState.parameterCount = 0;
    expect(AppState.decrementParameterCount()).toBe(0);
    expect(AppState.getParameterCount()).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Modal management
// ---------------------------------------------------------------------------
describe("modal management", () => {
  test("isModalActive returns false for inactive modals", () => {
    expect(AppState.isModalActive("test-modal")).toBe(false);
  });

  test("setModalActive marks modal as active", () => {
    AppState.setModalActive("test-modal");
    expect(AppState.isModalActive("test-modal")).toBe(true);
  });

  test("setModalInactive marks modal as inactive", () => {
    AppState.setModalActive("test-modal");
    AppState.setModalInactive("test-modal");
    expect(AppState.isModalActive("test-modal")).toBe(false);
  });

  test("manages multiple modals independently", () => {
    AppState.setModalActive("modal-a");
    AppState.setModalActive("modal-b");
    expect(AppState.isModalActive("modal-a")).toBe(true);
    expect(AppState.isModalActive("modal-b")).toBe(true);

    AppState.setModalInactive("modal-a");
    expect(AppState.isModalActive("modal-a")).toBe(false);
    expect(AppState.isModalActive("modal-b")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Pending requests
// ---------------------------------------------------------------------------
describe("pending requests", () => {
  test("addPendingRequest adds controller to set", () => {
    const controller = new AbortController();
    AppState.addPendingRequest(controller);
    expect(AppState.pendingRequests.has(controller)).toBe(true);
  });

  test("removePendingRequest removes controller from set", () => {
    const controller = new AbortController();
    AppState.addPendingRequest(controller);
    AppState.removePendingRequest(controller);
    expect(AppState.pendingRequests.has(controller)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Team relationship filter
// ---------------------------------------------------------------------------
describe("team relationship filter", () => {
  test("getCurrentTeamRelationshipFilter returns default", () => {
    expect(AppState.getCurrentTeamRelationshipFilter()).toBe("all");
  });

  test("setCurrentTeamRelationshipFilter updates filter", () => {
    AppState.setCurrentTeamRelationshipFilter("owned");
    expect(AppState.getCurrentTeamRelationshipFilter()).toBe("owned");
  });
});

// ---------------------------------------------------------------------------
// Restricted context tracking
// ---------------------------------------------------------------------------
describe("restricted context tracking", () => {
  test("isRestrictedContextLogged returns false by default", () => {
    expect(AppState.isRestrictedContextLogged()).toBe(false);
  });

  test("setRestrictedContextLogged updates value", () => {
    AppState.setRestrictedContextLogged(true);
    expect(AppState.isRestrictedContextLogged()).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// reset
// ---------------------------------------------------------------------------
describe("reset", () => {
  test("resets all state to defaults", () => {
    // Set up non-default state
    AppState.parameterCount = 5;
    AppState.currentTestTool = { id: "tool-1" };
    AppState.toolTestResultEditor = { setValue: vi.fn() };
    AppState.activeModals.add("modal-a");
    AppState.restrictedContextLogged = true;
    AppState.editors.gateway.headers = { destroy: vi.fn() };

    AppState.reset();

    expect(AppState.parameterCount).toBe(0);
    expect(AppState.currentTestTool).toBeNull();
    expect(AppState.toolTestResultEditor).toBeNull();
    expect(AppState.activeModals.size).toBe(0);
    expect(AppState.restrictedContextLogged).toBe(false);
    expect(AppState.editors.gateway.headers).toBeNull();
  });

  test("aborts pending requests during reset", () => {
    const controller1 = new AbortController();
    const controller2 = new AbortController();
    const abortSpy1 = vi.spyOn(controller1, "abort");
    const abortSpy2 = vi.spyOn(controller2, "abort");

    AppState.addPendingRequest(controller1);
    AppState.addPendingRequest(controller2);

    AppState.reset();

    expect(abortSpy1).toHaveBeenCalled();
    expect(abortSpy2).toHaveBeenCalled();
    expect(AppState.pendingRequests.size).toBe(0);
  });

  test("handles abort errors gracefully during reset", () => {
    const controller = {
      abort: () => {
        throw new Error("abort failed");
      },
    };
    AppState.pendingRequests.add(controller);

    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(() => AppState.reset()).not.toThrow();
    expect(warnSpy).toHaveBeenCalledWith(
      "Error aborting request:",
      expect.any(Error)
    );
  });

  test("calls registered cleanup callback", () => {
    const cleanupFn = vi.fn();
    registerCleanupToolTestState(cleanupFn);

    AppState.reset();

    expect(cleanupFn).toHaveBeenCalledOnce();

    // Reset the callback to avoid side effects
    registerCleanupToolTestState(null);
  });

  test("resets all gateway editor entries to null", () => {
    AppState.editors.gateway.headers = "editor1";
    AppState.editors.gateway.body = "editor2";
    AppState.editors.gateway.formHandler = "handler1";
    AppState.editors.gateway.closeHandler = "handler2";

    AppState.reset();

    expect(AppState.editors.gateway.headers).toBeNull();
    expect(AppState.editors.gateway.body).toBeNull();
    expect(AppState.editors.gateway.formHandler).toBeNull();
    expect(AppState.editors.gateway.closeHandler).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// registerCleanupToolTestState
// ---------------------------------------------------------------------------
describe("registerCleanupToolTestState", () => {
  test("does not throw when registering null", () => {
    expect(() => registerCleanupToolTestState(null)).not.toThrow();
  });

  test("registered callback is not called when not a function", () => {
    registerCleanupToolTestState("not a function");
    // reset should not throw even with invalid callback
    expect(() => AppState.reset()).not.toThrow();
    registerCleanupToolTestState(null);
  });
});
