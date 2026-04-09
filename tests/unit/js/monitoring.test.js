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

  test("handles gateway_activated event", () => {
    window.ROOT_PATH = "";
    window.Admin = {
      generateStatusBadgeHtml: vi.fn(() => "<span>Active</span>"),
    };

    document.body.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>Actions</th>
            <th>Name</th>
            <th>URL</th>
            <th>Tags</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          <tr id="gateway-row-gw-1">
            <td>Actions</td>
            <td>Gateway 1</td>
            <td>http://localhost:9000</td>
            <td>mcp</td>
            <td>Offline</td>
          </tr>
        </tbody>
      </table>
    `;

    let eventHandler;
    const MockEventSource = vi.fn(function () {
      this.addEventListener = vi.fn((type, handler) => {
        if (type === "gateway_activated") {
          eventHandler = handler;
        }
      });
      this.onopen = null;
      this.onerror = null;
      this.close = vi.fn();
    });
    window.EventSource = MockEventSource;

    initializeRealTimeMonitoring();

    // Simulate gateway_activated event
    const event = {
      type: "gateway_activated",
      data: JSON.stringify({ id: "gw-1", enabled: true, reachable: true }),
    };
    eventHandler(event);

    const statusCell = document.querySelector("#gateway-row-gw-1 td:nth-child(5)");
    expect(statusCell.innerHTML).toContain("Active");
  });

  test("handles tool_activated event", () => {
    window.ROOT_PATH = "";
    window.Admin = {
      generateStatusBadgeHtml: vi.fn(() => "<span>Active</span>"),
    };

    document.body.innerHTML = `
      <div id="tools-panel">
        <table>
          <thead>
            <tr>
              <th>Actions</th>
              <th>Name</th>
              <th>Description</th>
              <th>Tags</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr id="tool-row-tool-1">
              <td>Actions</td>
              <td>read_file</td>
              <td>Reads a file</td>
              <td>filesystem</td>
              <td>Offline</td>
            </tr>
          </tbody>
        </table>
      </div>
    `;

    let eventHandler;
    const MockEventSource = vi.fn(function () {
      this.addEventListener = vi.fn((type, handler) => {
        if (type === "tool_activated") {
          eventHandler = handler;
        }
      });
      this.onopen = null;
      this.onerror = null;
      this.close = vi.fn();
    });
    window.EventSource = MockEventSource;

    initializeRealTimeMonitoring();

    // Simulate tool_activated event
    const event = {
      type: "tool_activated",
      data: JSON.stringify({ id: "tool-1", isActive: true }),
    };
    eventHandler(event);

    const statusCell = document.querySelector("#tool-row-tool-1 td:nth-child(5)");
    expect(statusCell.innerHTML).toContain("Active");
  });

  test("handles gateway_offline event", () => {
    window.ROOT_PATH = "";
    window.Admin = {
      generateStatusBadgeHtml: vi.fn(() => "<span>Offline</span>"),
    };

    document.body.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>Actions</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          <tr id="gateway-row-gw-2">
            <td>Actions</td>
            <td>Active</td>
          </tr>
        </tbody>
      </table>
    `;

    let eventHandler;
    const MockEventSource = vi.fn(function () {
      this.addEventListener = vi.fn((type, handler) => {
        if (type === "gateway_offline") {
          eventHandler = handler;
        }
      });
      this.onopen = null;
      this.onerror = null;
      this.close = vi.fn();
    });
    window.EventSource = MockEventSource;

    initializeRealTimeMonitoring();

    const event = {
      type: "gateway_offline",
      data: JSON.stringify({ id: "gw-2", enabled: true, reachable: false }),
    };
    eventHandler(event);

    const statusCell = document.querySelector("#gateway-row-gw-2 td:nth-child(2)");
    expect(statusCell.innerHTML).toContain("Offline");
  });

  test("handles tool_offline event", () => {
    window.ROOT_PATH = "";
    window.Admin = {
      generateStatusBadgeHtml: vi.fn(() => "<span>Offline</span>"),
    };

    document.body.innerHTML = `
      <div id="tools-panel">
        <table>
          <thead>
            <tr>
              <th>Actions</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr id="tool-row-tool-2">
              <td>Actions</td>
              <td>Active</td>
            </tr>
          </tbody>
        </table>
      </div>
    `;

    let eventHandler;
    const MockEventSource = vi.fn(function () {
      this.addEventListener = vi.fn((type, handler) => {
        if (type === "tool_offline") {
          eventHandler = handler;
        }
      });
      this.onopen = null;
      this.onerror = null;
      this.close = vi.fn();
    });
    window.EventSource = MockEventSource;

    initializeRealTimeMonitoring();

    const event = {
      type: "tool_offline",
      data: JSON.stringify({ id: "tool-2", isActive: false }),
    };
    eventHandler(event);

    const statusCell = document.querySelector("#tool-row-tool-2 td:nth-child(2)");
    expect(statusCell.innerHTML).toContain("Offline");
  });

  test("finds tool row by data attribute", () => {
    window.ROOT_PATH = "";
    window.Admin = {
      generateStatusBadgeHtml: vi.fn(() => "<span>Active</span>"),
    };

    document.body.innerHTML = `
      <div id="tools-panel">
        <table>
          <thead>
            <tr>
              <th>Actions</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr data-tool-id="tool-3">
              <td>Actions</td>
              <td>Offline</td>
            </tr>
          </tbody>
        </table>
      </div>
    `;

    let eventHandler;
    const MockEventSource = vi.fn(function () {
      this.addEventListener = vi.fn((type, handler) => {
        if (type === "tool_activated") {
          eventHandler = handler;
        }
      });
      this.onopen = null;
      this.onerror = null;
      this.close = vi.fn();
    });
    window.EventSource = MockEventSource;

    initializeRealTimeMonitoring();

    const event = {
      type: "tool_activated",
      data: JSON.stringify({ id: "tool-3", isActive: true }),
    };
    eventHandler(event);

    const statusCell = document.querySelector('[data-tool-id="tool-3"] td:nth-child(2)');
    expect(statusCell.innerHTML).toContain("Active");
  });

  test("finds tool row by innerHTML search", () => {
    window.ROOT_PATH = "";
    window.Admin = {
      generateStatusBadgeHtml: vi.fn(() => "<span>Active</span>"),
    };

    document.body.innerHTML = `
      <div id="tools-panel">
        <table>
          <thead>
            <tr>
              <th>Actions</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><button onclick="activate('tool-4')">Activate</button></td>
              <td>Offline</td>
            </tr>
          </tbody>
        </table>
      </div>
    `;

    let eventHandler;
    const MockEventSource = vi.fn(function () {
      this.addEventListener = vi.fn((type, handler) => {
        if (type === "tool_activated") {
          eventHandler = handler;
        }
      });
      this.onopen = null;
      this.onerror = null;
      this.close = vi.fn();
    });
    window.EventSource = MockEventSource;

    initializeRealTimeMonitoring();

    const event = {
      type: "tool_activated",
      data: JSON.stringify({ id: "tool-4", isActive: true }),
    };
    eventHandler(event);

    const row = document.querySelector("#tools-panel tbody tr");
    expect(row.id).toBe("tool-row-tool-4"); // Should set ID for optimization
    const statusCell = row.querySelector("td:nth-child(2)");
    expect(statusCell.innerHTML).toContain("Active");
  });

  test("warns when row not found", () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    let eventHandler;
    const MockEventSource = vi.fn(function () {
      this.addEventListener = vi.fn((type, handler) => {
        if (type === "gateway_activated") {
          eventHandler = handler;
        }
      });
      this.onopen = null;
      this.onerror = null;
      this.close = vi.fn();
    });
    window.EventSource = MockEventSource;

    initializeRealTimeMonitoring();

    const event = {
      type: "gateway_activated",
      data: JSON.stringify({ id: "nonexistent", enabled: true }),
    };
    eventHandler(event);

    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("Could not find row")
    );
    consoleSpy.mockRestore();
  });

  test("handles invalid JSON in event data", () => {
    window.ROOT_PATH = "";
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    let eventHandler;
    const MockEventSource = vi.fn(function () {
      this.addEventListener = vi.fn((type, handler) => {
        if (type === "gateway_activated") {
          eventHandler = handler;
        }
      });
      this.onopen = null;
      this.onerror = null;
      this.close = vi.fn();
    });
    window.EventSource = MockEventSource;

    initializeRealTimeMonitoring();

    const event = {
      type: "gateway_activated",
      data: "invalid json",
    };
    eventHandler(event);

    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("Error processing"),
      expect.any(Error)
    );
    consoleSpy.mockRestore();
  });

  test("applies flash effect to status cell", () => {
    vi.useFakeTimers();
    window.ROOT_PATH = "";
    window.Admin = {
      generateStatusBadgeHtml: vi.fn(() => "<span>Active</span>"),
    };

    document.body.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>Actions</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          <tr id="gateway-row-gw-5">
            <td>Actions</td>
            <td>Offline</td>
          </tr>
        </tbody>
      </table>
    `;

    let eventHandler;
    const MockEventSource = vi.fn(function () {
      this.addEventListener = vi.fn((type, handler) => {
        if (type === "gateway_activated") {
          eventHandler = handler;
        }
      });
      this.onopen = null;
      this.onerror = null;
      this.close = vi.fn();
    });
    window.EventSource = MockEventSource;

    initializeRealTimeMonitoring();

    const event = {
      type: "gateway_activated",
      data: JSON.stringify({ id: "gw-5", enabled: true }),
    };
    eventHandler(event);

    const statusCell = document.querySelector("#gateway-row-gw-5 td:nth-child(2)");
    expect(statusCell.classList.contains("bg-blue-50")).toBe(true);

    vi.advanceTimersByTime(1000);
    expect(statusCell.classList.contains("bg-blue-50")).toBe(false);

    vi.useRealTimers();
  });

  test("updates action buttons via updateEntityActionButtons", async () => {
    window.ROOT_PATH = "";
    window.Admin = {
      generateStatusBadgeHtml: vi.fn(() => "<span>Active</span>"),
    };

    const { updateEntityActionButtons } = await import("../../../mcpgateway/admin_ui/logging.js");

    document.body.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>Actions</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          <tr id="gateway-row-gw-6">
            <td>Actions</td>
            <td>Offline</td>
          </tr>
        </tbody>
      </table>
    `;

    let eventHandler;
    const MockEventSource = vi.fn(function () {
      this.addEventListener = vi.fn((type, handler) => {
        if (type === "gateway_activated") {
          eventHandler = handler;
        }
      });
      this.onopen = null;
      this.onerror = null;
      this.close = vi.fn();
    });
    window.EventSource = MockEventSource;

    initializeRealTimeMonitoring();

    const event = {
      type: "gateway_activated",
      data: JSON.stringify({ id: "gw-6", enabled: true }),
    };
    eventHandler(event);

    expect(updateEntityActionButtons).toHaveBeenCalledWith(
      expect.any(HTMLElement),
      "gateway",
      "gw-6",
      true
    );
  });

  test("handles missing status cell gracefully", () => {
    window.ROOT_PATH = "";

    document.body.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr id="gateway-row-gw-7">
            <td>Actions</td>
          </tr>
        </tbody>
      </table>
    `;

    let eventHandler;
    const MockEventSource = vi.fn(function () {
      this.addEventListener = vi.fn((type, handler) => {
        if (type === "gateway_activated") {
          eventHandler = handler;
        }
      });
      this.onopen = null;
      this.onerror = null;
      this.close = vi.fn();
    });
    window.EventSource = MockEventSource;

    initializeRealTimeMonitoring();

    const event = {
      type: "gateway_activated",
      data: JSON.stringify({ id: "gw-7", enabled: true }),
    };

    expect(() => eventHandler(event)).not.toThrow();
  });

  test("uses fallback status index when headers not found", () => {
    window.ROOT_PATH = "";
    window.Admin = {
      generateStatusBadgeHtml: vi.fn(() => "<span>Active</span>"),
    };

    document.body.innerHTML = `
      <table>
        <tbody>
          <tr id="gateway-row-gw-8">
            <td>Actions</td>
            <td>Name</td>
            <td>URL</td>
            <td>Tags</td>
            <td>Offline</td>
          </tr>
        </tbody>
      </table>
    `;

    let eventHandler;
    const MockEventSource = vi.fn(function () {
      this.addEventListener = vi.fn((type, handler) => {
        if (type === "gateway_activated") {
          eventHandler = handler;
        }
      });
      this.onopen = null;
      this.onerror = null;
      this.close = vi.fn();
    });
    window.EventSource = MockEventSource;

    initializeRealTimeMonitoring();

    const event = {
      type: "gateway_activated",
      data: JSON.stringify({ id: "gw-8", enabled: true }),
    };
    eventHandler(event);

    const statusCell = document.querySelector("#gateway-row-gw-8 td:nth-child(5)");
    expect(statusCell.innerHTML).toContain("Active");
  });

  test("handles onerror callback", () => {
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
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    initializeRealTimeMonitoring();

    const error = new Error("Connection failed");
    createdInstance.onerror(error);

    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("SSE Connection issue"),
      error
    );
    consoleSpy.mockRestore();
  });

  test("handles tool with URL path in innerHTML", () => {
    window.ROOT_PATH = "";
    window.Admin = {
      generateStatusBadgeHtml: vi.fn(() => "<span>Active</span>"),
    };

    document.body.innerHTML = `
      <div id="tools-panel">
        <table>
          <thead>
            <tr>
              <th>Actions</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><a href="/tools/tool-9/edit">Edit</a></td>
              <td>Offline</td>
            </tr>
          </tbody>
        </table>
      </div>
    `;

    let eventHandler;
    const MockEventSource = vi.fn(function () {
      this.addEventListener = vi.fn((type, handler) => {
        if (type === "tool_activated") {
          eventHandler = handler;
        }
      });
      this.onopen = null;
      this.onerror = null;
      this.close = vi.fn();
    });
    window.EventSource = MockEventSource;

    initializeRealTimeMonitoring();

    const event = {
      type: "tool_activated",
      data: JSON.stringify({ id: "tool-9", isActive: true }),
    };
    eventHandler(event);

    const row = document.querySelector("#tools-panel tbody tr");
    expect(row.id).toBe("tool-row-tool-9");
  });

  test("handles tool with double-quoted ID in innerHTML", () => {
    window.ROOT_PATH = "";
    window.Admin = {
      generateStatusBadgeHtml: vi.fn(() => "<span>Active</span>"),
    };

    document.body.innerHTML = `
      <div id="tools-panel">
        <table>
          <thead>
            <tr>
              <th>Actions</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><button data-id="tool-10">Activate</button></td>
              <td>Offline</td>
            </tr>
          </tbody>
        </table>
      </div>
    `;

    let eventHandler;
    const MockEventSource = vi.fn(function () {
      this.addEventListener = vi.fn((type, handler) => {
        if (type === "tool_activated") {
          eventHandler = handler;
        }
      });
      this.onopen = null;
      this.onerror = null;
      this.close = vi.fn();
    });
    window.EventSource = MockEventSource;

    initializeRealTimeMonitoring();

    const event = {
      type: "tool_activated",
      data: JSON.stringify({ id: "tool-10", isActive: true }),
    };
    eventHandler(event);

    const row = document.querySelector("#tools-panel tbody tr");
    expect(row.id).toBe("tool-row-tool-10");
  });
});
