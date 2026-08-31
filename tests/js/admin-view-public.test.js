/**
 * Tests for the toggleViewPublic function and View Public checkbox behaviour.
 *
 * Functions are imported directly from their source modules.
 * Only tokens.js is mocked (to prevent real fetch calls); all other modules
 * are imported as-is.
 *
 * Covers:
 *  - Checking the box keeps team_id and adds include_public=true to selector hx-get URLs
 *  - Unchecking removes include_public and keeps team_id
 *  - Round-trip: check → uncheck → check
 *  - team_id is not duplicated when unchecking with it already present
 *  - HTMX process + trigger are called per container per toggle
 *  - Multiple containers updated in a single call
 *  - Early-return guards (missing checkbox, missing teamId, missing container)
 */

import { describe, test, expect, beforeEach, vi } from "vitest";

import { toggleViewPublic } from "../../mcpgateway/admin_ui/filters.js";
import { initGatewaySelect } from "../../mcpgateway/admin_ui/gateways.js";

// Mock tokens.js to prevent real fetch calls.
vi.mock("../../mcpgateway/admin_ui/tokens.js", () => ({
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

beforeEach(() => {
  document.body.innerHTML = "";
  window.htmx = { process: vi.fn(), trigger: vi.fn(), ajax: vi.fn() };
  window.ROOT_PATH = "";
  window.USER_TEAMS_DATA = [];
  // Clean URL so getCurrentTeamId() returns null by default
  window.history.replaceState({}, "", "/");
  vi.clearAllMocks();
  // Restore htmx spies after clearAllMocks
  window.htmx = { process: vi.fn(), trigger: vi.fn(), ajax: vi.fn() };
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeCheckbox(id) {
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.id = id;
  document.body.appendChild(cb);
  return cb;
}

function makeHtmxContainer(id, url) {
  const div = document.createElement("div");
  div.id = id;
  div.setAttribute("hx-get", url);
  document.body.appendChild(div);
  return div;
}

// ---------------------------------------------------------------------------
// URL mutation
// ---------------------------------------------------------------------------

describe("toggleViewPublic — URL mutation", () => {
  test("checking the box keeps team_id and adds include_public=true", () => {
    makeCheckbox("add-server-view-public");
    const container = makeHtmxContainer(
      "associatedTools",
      "/admin/tools/partial?page=1&render=selector&team_id=team-abc",
    );

    toggleViewPublic(
      "add-server-view-public",
      ["associatedTools"],
      "team-abc",
    );

    const cb = document.getElementById("add-server-view-public");
    cb.checked = true;
    cb.dispatchEvent(new Event("change"));

    const url = container.getAttribute("hx-get");
    expect(url).toContain("team_id=team-abc");
    expect(url).toContain("include_public=true");
  });

  test("unchecking the box removes include_public and keeps team_id", () => {
    makeCheckbox("add-server-view-public");
    const container = makeHtmxContainer(
      "associatedTools",
      "/admin/tools/partial?page=1&render=selector&team_id=team-abc&include_public=true",
    );

    toggleViewPublic(
      "add-server-view-public",
      ["associatedTools"],
      "team-abc",
    );

    const cb = document.getElementById("add-server-view-public");
    cb.checked = false;
    cb.dispatchEvent(new Event("change"));

    const url = container.getAttribute("hx-get");
    expect(url).toContain("team_id=team-abc");
    expect(url).not.toContain("include_public");
  });

  test("round-trip check → uncheck → check keeps team_id throughout and toggles include_public", () => {
    makeCheckbox("add-server-view-public");
    const container = makeHtmxContainer(
      "associatedTools",
      "/admin/tools/partial?page=1&render=selector&team_id=team-abc",
    );

    toggleViewPublic(
      "add-server-view-public",
      ["associatedTools"],
      "team-abc",
    );

    const cb = document.getElementById("add-server-view-public");

    cb.checked = true;
    cb.dispatchEvent(new Event("change"));

    cb.checked = false;
    cb.dispatchEvent(new Event("change"));

    cb.checked = true;
    cb.dispatchEvent(new Event("change"));

    const url = container.getAttribute("hx-get");
    expect(url).toContain("team_id=team-abc");
    expect(url).toContain("include_public=true");
  });

  test("unchecking does not add team_id a second time when it is already present", () => {
    makeCheckbox("add-server-view-public");
    const container = makeHtmxContainer(
      "associatedTools",
      "/admin/tools/partial?page=1&render=selector&team_id=team-abc",
    );

    toggleViewPublic(
      "add-server-view-public",
      ["associatedTools"],
      "team-abc",
    );

    const cb = document.getElementById("add-server-view-public");
    cb.checked = false;
    cb.dispatchEvent(new Event("change"));

    const url = container.getAttribute("hx-get");
    expect((url.match(/team_id=/g) || []).length).toBe(1);
  });

  test("team_id value is URI-encoded in the appended param", () => {
    makeCheckbox("add-server-view-public");
    const container = makeHtmxContainer(
      "associatedTools",
      "/admin/tools/partial?page=1&render=selector",
    );

    toggleViewPublic(
      "add-server-view-public",
      ["associatedTools"],
      "team with spaces",
    );

    const cb = document.getElementById("add-server-view-public");
    cb.checked = false;
    cb.dispatchEvent(new Event("change"));

    expect(container.getAttribute("hx-get")).toContain(
      "team_id=team%20with%20spaces",
    );
  });

  test("checking adds include_public even when team_id was not initially in URL", () => {
    makeCheckbox("add-server-view-public");
    const container = makeHtmxContainer(
      "associatedTools",
      "/admin/tools/partial?page=1&render=selector",
    );

    win.toggleViewPublic(
      "add-server-view-public",
      ["associatedTools"],
      "team-abc",
    );

    const cb = doc.getElementById("add-server-view-public");
    cb.checked = true;
    cb.dispatchEvent(new win.Event("change"));

    const url = container.getAttribute("hx-get");
    expect(url).toContain("team_id=team-abc");
    expect(url).toContain("include_public=true");
  });

  test("include_public is not duplicated on repeated checks", () => {
    makeCheckbox("add-server-view-public");
    const container = makeHtmxContainer(
      "associatedTools",
      "/admin/tools/partial?page=1&render=selector&team_id=team-abc",
    );

    win.toggleViewPublic(
      "add-server-view-public",
      ["associatedTools"],
      "team-abc",
    );

    const cb = doc.getElementById("add-server-view-public");
    cb.checked = true;
    cb.dispatchEvent(new win.Event("change"));
    cb.checked = true;
    cb.dispatchEvent(new win.Event("change"));

    const url = container.getAttribute("hx-get");
    expect((url.match(/include_public=/g) || []).length).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// HTMX side-effects
// ---------------------------------------------------------------------------

describe("toggleViewPublic — HTMX side-effects", () => {
  test("htmx.process and htmx.trigger are called once per toggle", () => {
    makeCheckbox("add-server-view-public");
    makeHtmxContainer(
      "associatedTools",
      "/admin/tools/partial?page=1&render=selector&team_id=team-abc",
    );

    toggleViewPublic(
      "add-server-view-public",
      ["associatedTools"],
      "team-abc",
    );

    const cb = document.getElementById("add-server-view-public");
    cb.checked = true;
    cb.dispatchEvent(new Event("change"));

    expect(window.htmx.process).toHaveBeenCalledTimes(1);
    expect(window.htmx.trigger).toHaveBeenCalledTimes(1);
  });

  test("htmx.trigger is called with the container element and 'load'", () => {
    makeCheckbox("add-server-view-public");
    const container = makeHtmxContainer(
      "associatedTools",
      "/admin/tools/partial?page=1&render=selector&team_id=team-abc",
    );

    toggleViewPublic(
      "add-server-view-public",
      ["associatedTools"],
      "team-abc",
    );

    const cb = document.getElementById("add-server-view-public");
    cb.checked = true;
    cb.dispatchEvent(new Event("change"));

    expect(window.htmx.trigger).toHaveBeenCalledWith(container, "load");
  });

  test("htmx is called once per container when multiple containers are passed", () => {
    makeCheckbox("add-server-view-public");
    ["associatedTools", "associatedResources", "associatedPrompts"].forEach(
      (id) =>
        makeHtmxContainer(
          id,
          `/admin/${id}/partial?render=selector&team_id=team-abc`,
        ),
    );

    toggleViewPublic(
      "add-server-view-public",
      ["associatedTools", "associatedResources", "associatedPrompts"],
      "team-abc",
    );

    const cb = document.getElementById("add-server-view-public");
    cb.checked = true;
    cb.dispatchEvent(new Event("change"));

    expect(window.htmx.process).toHaveBeenCalledTimes(3);
    expect(window.htmx.trigger).toHaveBeenCalledTimes(3);
  });

  test("all containers have include_public=true added when checking with multiple containers", () => {
    makeCheckbox("add-server-view-public");
    const containers = [
      "associatedTools",
      "associatedResources",
      "associatedPrompts",
    ].map((id) =>
      makeHtmxContainer(
        id,
        `/admin/${id}/partial?render=selector&team_id=team-abc`,
      ),
    );

    toggleViewPublic(
      "add-server-view-public",
      ["associatedTools", "associatedResources", "associatedPrompts"],
      "team-abc",
    );

    const cb = document.getElementById("add-server-view-public");
    cb.checked = true;
    cb.dispatchEvent(new Event("change"));

    containers.forEach((c) => {
      const url = c.getAttribute("hx-get");
      expect(url).toContain("team_id=team-abc");
      expect(url).toContain("include_public=true");
    });
  });
});

// ---------------------------------------------------------------------------
// Guard / early-return behaviour
// ---------------------------------------------------------------------------

describe("toggleViewPublic — early-return guards", () => {
  test("does not throw when the checkbox does not exist in the DOM", () => {
    expect(() => {
      toggleViewPublic(
        "nonexistent-checkbox",
        ["associatedTools"],
        "team-abc",
      );
    }).not.toThrow();
  });

  test("does not throw when teamId is an empty string", () => {
    makeCheckbox("add-server-view-public");
    expect(() => {
      toggleViewPublic(
        "add-server-view-public",
        ["associatedTools"],
        "",
      );
    }).not.toThrow();
  });

  test("skips containers that are not in the DOM, processes those that are", () => {
    makeCheckbox("add-server-view-public");
    const present = makeHtmxContainer(
      "associatedTools",
      "/admin/tools/partial?render=selector&team_id=team-abc",
    );
    // "associatedMissing" does not exist in the DOM

    toggleViewPublic(
      "add-server-view-public",
      ["associatedTools", "associatedMissing"],
      "team-abc",
    );

    const cb = document.getElementById("add-server-view-public");
    cb.checked = true;
    cb.dispatchEvent(new Event("change"));

    // Present container updated, no error for missing one
    const url = present.getAttribute("hx-get");
    expect(url).toContain("team_id=team-abc");
    expect(url).toContain("include_public=true");
    expect(win.htmx.process).toHaveBeenCalledTimes(1);
  });

  test("skips a container that has no hx-get attribute", () => {
    makeCheckbox("add-server-view-public");
    const noAttr = document.createElement("div");
    noAttr.id = "associatedTools";
    document.body.appendChild(noAttr); // no hx-get set

    toggleViewPublic(
      "add-server-view-public",
      ["associatedTools"],
      "team-abc",
    );

    const cb = document.getElementById("add-server-view-public");
    cb.checked = true;
    cb.dispatchEvent(new Event("change"));

    expect(window.htmx.process).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// toggleViewPublic — gateway_id preservation
// ---------------------------------------------------------------------------

describe("toggleViewPublic — gateway_id preservation", () => {
  test("preserves team_id and adds include_public when toggling (no active gateway selection)", () => {
    makeCheckbox("add-server-view-public");
    const container = makeHtmxContainer(
      "associatedTools",
      "/admin/tools/partial?page=1&render=selector&gateway_id=gw-1&team_id=team-abc",
    );

    // No associatedGateways container in DOM → getSelectedGatewayIds() returns []

    toggleViewPublic(
      "add-server-view-public",
      ["associatedTools"],
      "team-abc",
    );

    const cb = document.getElementById("add-server-view-public");
    cb.checked = true;
    cb.dispatchEvent(new Event("change"));

    const url = container.getAttribute("hx-get");
    // team_id preserved, include_public added, gateway_id stripped (no active selection)
    expect(url).toContain("team_id=team-abc");
    expect(url).toContain("include_public=true");
    expect(url).not.toContain("gateway_id");
  });

  test("injects current gateway selection into hx-get on toggle", () => {
    makeCheckbox("add-server-view-public");
    const container = makeHtmxContainer(
      "associatedTools",
      "/admin/tools/partial?page=1&render=selector&team_id=team-abc",
    );

    // Simulate selected gateways via DOM checkboxes in associatedGateways container
    const gwContainer = document.createElement("div");
    gwContainer.id = "associatedGateways";
    document.body.appendChild(gwContainer);
    ["gw-1", "gw-2"].forEach((id) => {
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = id;
      cb.checked = true;
      gwContainer.appendChild(cb);
    });

    toggleViewPublic(
      "add-server-view-public",
      ["associatedTools"],
      "team-abc",
    );

    const cb = document.getElementById("add-server-view-public");
    cb.checked = true;
    cb.dispatchEvent(new Event("change"));

    const url = container.getAttribute("hx-get");
    expect(url).toContain("team_id=team-abc");
    expect(url).toContain("include_public=true");
    expect(url).toContain("gateway_id=gw-1%2Cgw-2");
  });

  test("round-trip preserves gateway_id when unchecking", () => {
    makeCheckbox("add-server-view-public");
    const container = makeHtmxContainer(
      "associatedTools",
      "/admin/tools/partial?page=1&render=selector&team_id=team-abc",
    );

    // Simulate one selected gateway
    const gwContainer = document.createElement("div");
    gwContainer.id = "associatedGateways";
    document.body.appendChild(gwContainer);
    const gw1 = document.createElement("input");
    gw1.type = "checkbox";
    gw1.value = "gw-1";
    gw1.checked = true;
    gwContainer.appendChild(gw1);

    toggleViewPublic(
      "add-server-view-public",
      ["associatedTools"],
      "team-abc",
    );

    const cb = document.getElementById("add-server-view-public");

    // check
    cb.checked = true;
    cb.dispatchEvent(new Event("change"));

    // uncheck
    cb.checked = false;
    cb.dispatchEvent(new Event("change"));

    const url = container.getAttribute("hx-get");
    expect(url).toContain("team_id=team-abc");
    expect(url).toContain("gateway_id=gw-1");
    expect(url).not.toContain("include_public");
  });
});

// ---------------------------------------------------------------------------
// initGatewaySelect — edit-modal Select All reads correct View Public checkbox
// ---------------------------------------------------------------------------

describe("initGatewaySelect — edit-modal Select All checkbox lookup", () => {
  function makeGatewayEditDom() {
    const container = document.createElement("div");
    container.id = "associatedEditGateways";
    document.body.appendChild(container);

    const pills = document.createElement("div");
    pills.id = "selectedEditGatewayPills";
    document.body.appendChild(pills);

    const warn = document.createElement("div");
    warn.id = "selectedEditGatewayWarning";
    document.body.appendChild(warn);

    const selectBtn = document.createElement("button");
    selectBtn.id = "selectAllEditGatewayBtn";
    document.body.appendChild(selectBtn);

    const clearBtn = document.createElement("button");
    clearBtn.id = "clearAllEditGatewayBtn";
    document.body.appendChild(clearBtn);
  }

  test("edit-modal Select All includes team_id and include_public when edit View Public is checked", async () => {
    // Both checkboxes exist in DOM (as on a team-scoped page)
    const addCb = makeCheckbox("add-server-view-public");
    addCb.checked = false; // add-modal unchecked
    const editCb = makeCheckbox("edit-server-view-public");
    editCb.checked = true; // edit-modal checked

    makeGatewayEditDom();

    // Set team_id via URL so getCurrentTeamId() returns "team-abc"
    window.history.replaceState({}, "", "/?team_id=team-abc");
    window.ROOT_PATH = "";
    let fetchedUrl = null;
    window.fetch = vi.fn().mockImplementation((url) => {
      fetchedUrl = url;
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ gateway_ids: [] }),
      });
    });

    // Init with edit selectId
    initGatewaySelect(
      "associatedEditGateways",
      "selectedEditGatewayPills",
      "selectedEditGatewayWarning",
      12,
      "selectAllEditGatewayBtn",
      "clearAllEditGatewayBtn",
      "searchEditGateways",
    );

    // Click the replaced Select All button
    const btn = document.getElementById("selectAllEditGatewayBtn");
    btn.click();
    // Let the async handler run
    await new Promise((resolve) => setTimeout(resolve, 50));

    // Should contain team_id AND include_public because edit checkbox is checked
    expect(fetchedUrl).not.toBeNull();
    expect(fetchedUrl).toContain("team_id=team-abc");
    expect(fetchedUrl).toContain("include_public=true");
  });

  test("edit-modal Select All includes team_id without include_public when edit View Public is unchecked", async () => {
    const addCb = makeCheckbox("add-server-view-public");
    addCb.checked = true; // add-modal checked (should be ignored)
    const editCb = makeCheckbox("edit-server-view-public");
    editCb.checked = false; // edit-modal unchecked

    makeGatewayEditDom();

    // Set team_id via URL so getCurrentTeamId() returns "team-abc"
    window.history.replaceState({}, "", "/?team_id=team-abc");
    window.ROOT_PATH = "";
    let fetchedUrl = null;
    window.fetch = vi.fn().mockImplementation((url) => {
      fetchedUrl = url;
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ gateway_ids: [] }),
      });
    });

    initGatewaySelect(
      "associatedEditGateways",
      "selectedEditGatewayPills",
      "selectedEditGatewayWarning",
      12,
      "selectAllEditGatewayBtn",
      "clearAllEditGatewayBtn",
      "searchEditGateways",
    );

    const btn = document.getElementById("selectAllEditGatewayBtn");
    btn.click();
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(fetchedUrl).not.toBeNull();
    expect(fetchedUrl).toContain("team_id=team-abc");
    expect(fetchedUrl).not.toContain("include_public");
  });
});
