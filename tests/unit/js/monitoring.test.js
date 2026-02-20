/**
 * Unit tests for monitoring.js module
 * Tests: initializeRealTimeMonitoring
 */

import { describe, test, expect, vi, afterEach } from "vitest";

import { initializeRealTimeMonitoring } from "../../../mcpgateway/admin_ui/monitoring.js";

vi.mock("../../../mcpgateway/admin_ui/logging.js", () => ({
  updateEntityActionButtons: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  safeGetElement: vi.fn((id) => document.getElementById(id)),
}));

afterEach(() => {
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
  delete window.EventSource;
});

// ---------------------------------------------------------------------------
// initializeRealTimeMonitoring
// ---------------------------------------------------------------------------
describe("initializeRealTimeMonitoring", () => {
  test("does nothing when EventSource is not available", () => {
    delete window.EventSource;
    expect(() => initializeRealTimeMonitoring()).not.toThrow();
  });

  test("creates EventSource when available", () => {
    window.ROOT_PATH = "";
    const instance = {
      addEventListener: vi.fn(),
      onopen: null,
      onerror: null,
      close: vi.fn(),
    };

    const MockEventSource = vi.fn(function () {
      Object.assign(this, instance);
    });
    window.EventSource = MockEventSource;

    initializeRealTimeMonitoring();

    expect(MockEventSource).toHaveBeenCalledWith(
      expect.stringContaining("/admin/events")
    );
    expect(instance.addEventListener).toHaveBeenCalled();
  });

  test("registers event listeners for gateway and tool events", () => {
    window.ROOT_PATH = "";
    const addListenerMock = vi.fn();
    const MockEventSource = vi.fn(function () {
      this.addEventListener = addListenerMock;
      this.onopen = null;
      this.onerror = null;
      this.close = vi.fn();
    });
    window.EventSource = MockEventSource;

    initializeRealTimeMonitoring();

    const eventTypes = addListenerMock.mock.calls.map((call) => call[0]);
    expect(eventTypes).toContain("gateway_activated");
    expect(eventTypes).toContain("gateway_offline");
    expect(eventTypes).toContain("tool_activated");
    expect(eventTypes).toContain("tool_offline");
  });

  test("sets onopen and onerror handlers", () => {
    window.ROOT_PATH = "";
    let createdInstance;
    const MockEventSource = vi.fn(function () {
      this.addEventListener = vi.fn();
      this.onopen = null;
      this.onerror = null;
      this.close = vi.fn();
      createdInstance = this;
    });
    window.EventSource = MockEventSource;
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    initializeRealTimeMonitoring();

    expect(createdInstance.onopen).toBeTypeOf("function");
    expect(createdInstance.onerror).toBeTypeOf("function");

    // Test onopen handler
    createdInstance.onopen();
    expect(consoleSpy).toHaveBeenCalled();

    consoleSpy.mockRestore();
  });
});
