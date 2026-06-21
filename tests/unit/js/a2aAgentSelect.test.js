/**
 * Unit tests for the T21B-introduced surface area:
 * - initA2aAgentSelect helper in a2aAgents.js (server-form A2A multi-select wiring)
 * - Card-URL display + Copy button rendered by viewA2AAgent in a2aAgents.js
 *
 * Mirrors the test conventions established in a2aAgents.test.js and
 * formSubmitHandlers.test.js (Vitest + jsdom, mocked utils + modals + servers).
 */

import { describe, test, expect, vi, afterEach } from "vitest";

import {
  initA2aAgentSelect,
  viewA2AAgent,
} from "../../../mcpgateway/admin_ui/a2aAgents.js";
import { fetchWithTimeout } from "../../../mcpgateway/admin_ui/utils";

vi.mock("../../../mcpgateway/admin_ui/modals", () => ({
  closeModal: vi.fn(),
  openModal: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
  validateInputName: vi.fn((s) => ({ valid: true, value: s })),
  validateUrl: vi.fn((s) => ({ valid: true, value: s })),
}));
vi.mock("../../../mcpgateway/admin_ui/auth.js", () => ({
  getAuthHeaders: vi.fn(() => Promise.resolve({})),
  loadAuthHeaders: vi.fn(),
}));
vi.mock("../../../mcpgateway/admin_ui/teams.js", () => ({
  applyVisibilityRestrictions: vi.fn(),
  isTeamScopedView: vi.fn(() => false),
}));
vi.mock("../../../mcpgateway/admin_ui/servers.js", () => {
  const stores = new Map();
  return {
    getEditSelections: vi.fn((key) => {
      if (!stores.has(key)) {
        stores.set(key, new Set());
      }
      return stores.get(key);
    }),
    __resetStores: () => stores.clear(),
  };
});
vi.mock("../../../mcpgateway/admin_ui/utils", () => ({
  decodeHtml: vi.fn((s) => s || ""),
  fetchWithTimeout: vi.fn(),
  getCookie: vi.fn(() => ""),
  handleFetchError: vi.fn((e) => e.message),
  isInactiveChecked: vi.fn(() => false),
  makeCopyIdButton: vi.fn((value) => {
    const btn = document.createElement("button");
    btn.dataset.copyValue = value;
    btn.className = "mock-copy-btn";
    return btn;
  }),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
  safeSetValue: vi.fn((id, val) => {
    const el = document.getElementById(id);
    if (el) {
      el.value = val;
    }
  }),
  showErrorMessage: vi.fn(),
}));

afterEach(async () => {
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
  delete window.A2A_PUBLIC_BASE_URL;
  const serversMod = await import("../../../mcpgateway/admin_ui/servers.js");
  if (typeof serversMod.__resetStores === "function") {
    serversMod.__resetStores();
  }
  vi.clearAllMocks();
});

function buildA2aContainer({ containerId, agents }) {
  const container = document.createElement("div");
  container.id = containerId;
  agents.forEach(({ id, name, checked = false }) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = "associatedA2aAgents";
    input.value = id;
    input.dataset.agentName = name;
    if (checked) {
      input.checked = true;
    }
    label.appendChild(input);
    const span = document.createElement("span");
    span.textContent = name;
    label.appendChild(span);
    container.appendChild(label);
  });
  document.body.appendChild(container);
  return container;
}

function buildAdjacentElements({ pillsId, warnId, selectBtnId, clearBtnId }) {
  const pills = document.createElement("div");
  pills.id = pillsId;
  document.body.appendChild(pills);

  const warn = document.createElement("div");
  warn.id = warnId;
  document.body.appendChild(warn);

  if (selectBtnId) {
    const selectBtn = document.createElement("button");
    selectBtn.id = selectBtnId;
    document.body.appendChild(selectBtn);
  }
  if (clearBtnId) {
    const clearBtn = document.createElement("button");
    clearBtn.id = clearBtnId;
    document.body.appendChild(clearBtn);
  }
}

describe("initA2aAgentSelect", () => {
  test("returns early with console.warn when required elements are missing", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    initA2aAgentSelect(
      "missing-container",
      "missing-pills",
      "missing-warn"
    );

    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("A2A agent select elements not found")
    );
    warnSpy.mockRestore();
  });

  test("syncs initially-checked checkboxes into persistent selection store + renders pills", async () => {
    buildA2aContainer({
      containerId: "associatedA2aAgents",
      agents: [
        { id: "agent-1", name: "Echo Agent", checked: true },
        { id: "agent-2", name: "Math Agent", checked: false },
        { id: "agent-3", name: "Code Agent", checked: true },
      ],
    });
    buildAdjacentElements({
      pillsId: "selectedA2aAgentsPills",
      warnId: "selectedA2aAgentsWarning",
      selectBtnId: "selectAllA2aAgentsBtn",
      clearBtnId: "clearAllA2aAgentsBtn",
    });

    initA2aAgentSelect(
      "associatedA2aAgents",
      "selectedA2aAgentsPills",
      "selectedA2aAgentsWarning",
      6,
      "selectAllA2aAgentsBtn",
      "clearAllA2aAgentsBtn"
    );

    const { getEditSelections } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );
    const store = getEditSelections("associatedA2aAgents");
    expect(store.has("agent-1")).toBe(true);
    expect(store.has("agent-3")).toBe(true);
    expect(store.has("agent-2")).toBe(false);

    const pills = document.getElementById("selectedA2aAgentsPills");
    expect(pills.children.length).toBe(2);
    const pillTexts = Array.from(pills.children).map(
      (el) => el.textContent.trim()
    );
    expect(pillTexts).toContain("Echo Agent");
    expect(pillTexts).toContain("Code Agent");

    const selectBtn = document.getElementById("selectAllA2aAgentsBtn");
    expect(selectBtn.textContent).toBe("Select All (2)");
  });

  test("renders +N more summary pill when selection count exceeds maxPillsToShow", () => {
    buildA2aContainer({
      containerId: "associatedA2aAgents",
      agents: [
        { id: "a1", name: "Agent 1", checked: true },
        { id: "a2", name: "Agent 2", checked: true },
        { id: "a3", name: "Agent 3", checked: true },
        { id: "a4", name: "Agent 4", checked: true },
        { id: "a5", name: "Agent 5", checked: true },
      ],
    });
    buildAdjacentElements({
      pillsId: "selectedA2aAgentsPills",
      warnId: "selectedA2aAgentsWarning",
    });

    initA2aAgentSelect(
      "associatedA2aAgents",
      "selectedA2aAgentsPills",
      "selectedA2aAgentsWarning"
    );

    const pills = document.getElementById("selectedA2aAgentsPills");
    expect(pills.children.length).toBe(4);
    const lastPill = pills.children[pills.children.length - 1];
    expect(lastPill.textContent).toBe("+2 more");
  });

  test("sets warning text when count exceeds max", () => {
    buildA2aContainer({
      containerId: "associatedA2aAgents",
      agents: Array.from({ length: 8 }, (_, i) => ({
        id: `a${i}`,
        name: `Agent ${i}`,
        checked: true,
      })),
    });
    buildAdjacentElements({
      pillsId: "selectedA2aAgentsPills",
      warnId: "selectedA2aAgentsWarning",
    });

    initA2aAgentSelect(
      "associatedA2aAgents",
      "selectedA2aAgentsPills",
      "selectedA2aAgentsWarning",
      6
    );

    const warn = document.getElementById("selectedA2aAgentsWarning");
    expect(warn.textContent).toContain("Selected 8 A2A agents");
    expect(warn.textContent).toContain("more than 6");
  });

  test("Clear All button clears all checkboxes and persistent store", async () => {
    buildA2aContainer({
      containerId: "associatedA2aAgents",
      agents: [
        { id: "agent-1", name: "Agent One", checked: true },
        { id: "agent-2", name: "Agent Two", checked: true },
      ],
    });
    buildAdjacentElements({
      pillsId: "selectedA2aAgentsPills",
      warnId: "selectedA2aAgentsWarning",
      clearBtnId: "clearAllA2aAgentsBtn",
    });

    initA2aAgentSelect(
      "associatedA2aAgents",
      "selectedA2aAgentsPills",
      "selectedA2aAgentsWarning",
      6,
      null,
      "clearAllA2aAgentsBtn"
    );

    const { getEditSelections } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );
    let store = getEditSelections("associatedA2aAgents");
    expect(store.size).toBe(2);

    document.getElementById("clearAllA2aAgentsBtn").click();

    const container = document.getElementById("associatedA2aAgents");
    const checkboxes = container.querySelectorAll(
      'input[name="associatedA2aAgents"]'
    );
    checkboxes.forEach((cb) => expect(cb.checked).toBe(false));

    store = getEditSelections("associatedA2aAgents");
    expect(store.size).toBe(0);
  });

  test("Select All button checks all visible checkboxes and adds them to store", async () => {
    buildA2aContainer({
      containerId: "associatedA2aAgents",
      agents: [
        { id: "agent-1", name: "Agent One" },
        { id: "agent-2", name: "Agent Two" },
        { id: "agent-3", name: "Agent Three" },
      ],
    });
    buildAdjacentElements({
      pillsId: "selectedA2aAgentsPills",
      warnId: "selectedA2aAgentsWarning",
      selectBtnId: "selectAllA2aAgentsBtn",
    });

    initA2aAgentSelect(
      "associatedA2aAgents",
      "selectedA2aAgentsPills",
      "selectedA2aAgentsWarning",
      6,
      "selectAllA2aAgentsBtn"
    );

    document.getElementById("selectAllA2aAgentsBtn").click();

    const container = document.getElementById("associatedA2aAgents");
    const checkboxes = container.querySelectorAll(
      'input[name="associatedA2aAgents"]'
    );
    checkboxes.forEach((cb) => expect(cb.checked).toBe(true));

    const { getEditSelections } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );
    const store = getEditSelections("associatedA2aAgents");
    expect(store.size).toBe(3);
  });

  test("delegated change events on checkboxes re-sync the persistent store", async () => {
    buildA2aContainer({
      containerId: "associatedA2aAgents",
      agents: [{ id: "agent-1", name: "Agent One" }],
    });
    buildAdjacentElements({
      pillsId: "selectedA2aAgentsPills",
      warnId: "selectedA2aAgentsWarning",
    });

    initA2aAgentSelect(
      "associatedA2aAgents",
      "selectedA2aAgentsPills",
      "selectedA2aAgentsWarning"
    );

    const cb = document.querySelector(
      'input[name="associatedA2aAgents"][value="agent-1"]'
    );
    cb.checked = true;
    cb.dispatchEvent(new Event("change", { bubbles: true }));

    const { getEditSelections } = await import(
      "../../../mcpgateway/admin_ui/servers.js"
    );
    const store = getEditSelections("associatedA2aAgents");
    expect(store.has("agent-1")).toBe(true);
  });
});

describe("viewA2AAgent card URL affordance (T21B-d)", () => {
  function defaultAgent() {
    return {
      id: "agent-uuid",
      name: "echo-agent",
      slug: "echo-agent",
      endpointUrl: "http://localhost:9000",
      agentType: "A2A",
      protocolVersion: "1.0",
      description: "Echo agent",
      visibility: "public",
      enabled: true,
      reachable: true,
      tags: [],
      capabilities: {},
      config: {},
    };
  }

  test("renders Card URL link using window.A2A_PUBLIC_BASE_URL when provided", async () => {
    window.ROOT_PATH = "";
    window.A2A_PUBLIC_BASE_URL = "https://gateway.example.com";
    document.body.innerHTML = `
      <div id="agent-details"></div>
      <div id="agent-modal" class="hidden"></div>
    `;

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(defaultAgent()),
    });

    await viewA2AAgent("agent-uuid");

    const link = document.querySelector(
      'a[href="https://gateway.example.com/a2a/echo-agent/.well-known/agent-card.json"]'
    );
    expect(link).toBeTruthy();
    expect(link.target).toBe("_blank");
    expect(link.rel).toBe("noopener noreferrer");
  });

  test("falls back to window.location.origin when A2A_PUBLIC_BASE_URL is not configured", async () => {
    window.ROOT_PATH = "";
    document.body.innerHTML = `
      <div id="agent-details"></div>
      <div id="agent-modal" class="hidden"></div>
    `;

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(defaultAgent()),
    });

    await viewA2AAgent("agent-uuid");

    const origin = window.location.origin;
    const link = document.querySelector(
      `a[href="${origin}/a2a/echo-agent/.well-known/agent-card.json"]`
    );
    expect(link).toBeTruthy();
  });

  test("does not render Card URL row when agent.name is missing", async () => {
    window.ROOT_PATH = "";
    window.A2A_PUBLIC_BASE_URL = "https://gateway.example.com";
    document.body.innerHTML = `
      <div id="agent-details"></div>
      <div id="agent-modal" class="hidden"></div>
    `;

    const agentWithoutName = { ...defaultAgent(), name: undefined };
    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(agentWithoutName),
    });

    await viewA2AAgent("agent-uuid");

    const link = document.querySelector(
      'a[href*="/.well-known/agent-card.json"]'
    );
    expect(link).toBeNull();
  });

  test("includes a Copy button alongside the Card URL link", async () => {
    window.ROOT_PATH = "";
    window.A2A_PUBLIC_BASE_URL = "https://gateway.example.com";
    document.body.innerHTML = `
      <div id="agent-details"></div>
      <div id="agent-modal" class="hidden"></div>
    `;

    fetchWithTimeout.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(defaultAgent()),
    });

    await viewA2AAgent("agent-uuid");

    const copyButtons = document.querySelectorAll("button.mock-copy-btn");
    const cardCopyBtn = Array.from(copyButtons).find(
      (b) =>
        b.dataset.copyValue ===
        "https://gateway.example.com/a2a/echo-agent/.well-known/agent-card.json"
    );
    expect(cardCopyBtn).toBeTruthy();
  });
});
