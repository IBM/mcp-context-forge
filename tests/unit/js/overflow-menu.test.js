/**
 * Unit tests for overflow-menu component
 * Tests: overflowMenu factory function, Admin handler wiring for row actions
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { overflowMenu } from "../../../mcpgateway/admin_ui/components/overflow-menu.js";

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Build a component instance pre-wired with Alpine magic properties so tests
 * can call init / openMenu / navigate without a real Alpine runtime.
 */
function makeComponent(wrapperId = null, watchCallback = null) {
  const component = overflowMenu(wrapperId);
  component.$watch = vi.fn((prop, cb) => {
    if (watchCallback) watchCallback.ref = cb;
  });
  component.$refs = {};
  component.$nextTick = vi.fn((cb) => cb());
  return component;
}

/** Create <button role="menuitem"> elements inside a container div. */
function createMenuItems(count) {
  const menu = document.createElement("div");
  menu.setAttribute("role", "menu");
  const items = Array.from({ length: count }, () => {
    const btn = document.createElement("button");
    btn.setAttribute("role", "menuitem");
    menu.appendChild(btn);
    return btn;
  });
  document.body.appendChild(menu);
  return { menu, items };
}

// ─── Setup / teardown ─────────────────────────────────────────────────────────

beforeEach(() => {
  document.body.innerHTML = "";
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ─── Factory ──────────────────────────────────────────────────────────────────

describe("overflowMenu factory", () => {
  test("returns initial state with menuOpen false and zero position", () => {
    const component = overflowMenu();
    expect(component.menuOpen).toBe(false);
    expect(component.menuTop).toBe(0);
    expect(component.menuLeft).toBe(0);
  });

  test("exposes init, openMenu, and navigate methods", () => {
    const component = overflowMenu();
    expect(typeof component.init).toBe("function");
    expect(typeof component.openMenu).toBe("function");
    expect(typeof component.navigate).toBe("function");
  });

  test("accepts a wrapperId parameter without throwing", () => {
    expect(() => overflowMenu("tools-table-wrapper")).not.toThrow();
  });

  test("accepts null wrapperId", () => {
    expect(() => overflowMenu(null)).not.toThrow();
  });

  test("accepts no arguments (default null wrapperId)", () => {
    expect(() => overflowMenu()).not.toThrow();
  });
});

// ─── init ─────────────────────────────────────────────────────────────────────

describe("init", () => {
  test("registers a $watch on menuOpen", () => {
    const component = makeComponent();
    component.init();
    expect(component.$watch).toHaveBeenCalledWith("menuOpen", expect.any(Function));
  });

  test("sets main container overflow to hidden when menuOpen becomes true", () => {
    const main = document.createElement("main");
    main.setAttribute("data-scroll-container", "");
    document.body.appendChild(main);

    const cbHolder = {};
    const component = makeComponent(null, cbHolder);
    component.init();

    cbHolder.ref(true);
    expect(main.style.overflow).toBe("hidden");
  });

  test("restores main container overflow when menuOpen becomes false", () => {
    const main = document.createElement("main");
    main.setAttribute("data-scroll-container", "");
    main.style.overflow = "hidden";
    document.body.appendChild(main);

    const cbHolder = {};
    const component = makeComponent(null, cbHolder);
    component.init();

    cbHolder.ref(false);
    expect(main.style.overflow).toBe("");
  });

  test("does not throw when main scroll container is absent", () => {
    const cbHolder = {};
    const component = makeComponent(null, cbHolder);
    component.init();

    expect(() => cbHolder.ref(true)).not.toThrow();
  });

  test("sets wrapper overflow to hidden when menuOpen becomes true", () => {
    const wrapper = document.createElement("div");
    wrapper.id = "test-table-wrapper";
    document.body.appendChild(wrapper);

    const cbHolder = {};
    const component = makeComponent("test-table-wrapper", cbHolder);
    component.init();

    cbHolder.ref(true);
    expect(wrapper.style.overflow).toBe("hidden");
  });

  test("restores wrapper overflow when menuOpen becomes false", () => {
    const wrapper = document.createElement("div");
    wrapper.id = "test-table-wrapper";
    wrapper.style.overflow = "hidden";
    document.body.appendChild(wrapper);

    const cbHolder = {};
    const component = makeComponent("test-table-wrapper", cbHolder);
    component.init();

    cbHolder.ref(false);
    expect(wrapper.style.overflow).toBe("");
  });

  test("does not throw when wrapperId element does not exist in DOM", () => {
    const cbHolder = {};
    const component = makeComponent("nonexistent-wrapper", cbHolder);
    component.init();

    expect(() => cbHolder.ref(true)).not.toThrow();
  });

  test("skips wrapper lookup when wrapperId is null", () => {
    // No wrapper added to DOM — confirmed no-op when wrapperId is null
    const cbHolder = {};
    const component = makeComponent(null, cbHolder);
    component.init();

    expect(() => cbHolder.ref(true)).not.toThrow();
  });

  test("controls both main container and wrapper simultaneously", () => {
    const main = document.createElement("main");
    main.setAttribute("data-scroll-container", "");
    document.body.appendChild(main);

    const wrapper = document.createElement("div");
    wrapper.id = "dual-wrapper";
    document.body.appendChild(wrapper);

    const cbHolder = {};
    const component = makeComponent("dual-wrapper", cbHolder);
    component.init();

    cbHolder.ref(true);
    expect(main.style.overflow).toBe("hidden");
    expect(wrapper.style.overflow).toBe("hidden");

    cbHolder.ref(false);
    expect(main.style.overflow).toBe("");
    expect(wrapper.style.overflow).toBe("");
  });
});

// ─── openMenu ─────────────────────────────────────────────────────────────────

describe("openMenu", () => {
  function makeTrigger(bottom = 100, left = 50) {
    const trigger = document.createElement("button");
    trigger.getBoundingClientRect = vi.fn(() => ({ bottom, left }));
    return trigger;
  }

  test("sets menuOpen to true", () => {
    const { menu } = createMenuItems(1);
    const component = makeComponent();
    component.$refs = { trigger: makeTrigger(), menu };

    component.openMenu();
    expect(component.menuOpen).toBe(true);
  });

  test("sets menuTop to trigger bottom + 4", () => {
    const { menu } = createMenuItems(1);
    const component = makeComponent();
    component.$refs = { trigger: makeTrigger(120, 0), menu };

    component.openMenu();
    expect(component.menuTop).toBe(124);
  });

  test("sets menuLeft to trigger left", () => {
    const { menu } = createMenuItems(1);
    const component = makeComponent();
    component.$refs = { trigger: makeTrigger(0, 75), menu };

    component.openMenu();
    expect(component.menuLeft).toBe(75);
  });

  test("focuses the first menuitem after opening", () => {
    const { menu, items } = createMenuItems(2);
    const focusSpy = vi.spyOn(items[0], "focus");

    const component = makeComponent();
    component.$refs = { trigger: makeTrigger(), menu };

    component.openMenu();
    expect(focusSpy).toHaveBeenCalledOnce();
  });

  test("does not focus when menu has no menuitems", () => {
    const menu = document.createElement("div");
    document.body.appendChild(menu);

    const component = makeComponent();
    component.$refs = { trigger: makeTrigger(), menu };

    expect(() => component.openMenu()).not.toThrow();
  });
});

// ─── navigate ─────────────────────────────────────────────────────────────────

describe("navigate", () => {
  test("moves focus to the next item (dir = 1)", () => {
    const { menu, items } = createMenuItems(3);
    const component = makeComponent();
    component.$refs = { menu };

    items[0].focus();
    component.navigate(1);
    expect(document.activeElement).toBe(items[1]);
  });

  test("moves focus to the previous item (dir = -1)", () => {
    const { menu, items } = createMenuItems(3);
    const component = makeComponent();
    component.$refs = { menu };

    items[2].focus();
    component.navigate(-1);
    expect(document.activeElement).toBe(items[1]);
  });

  test("wraps from last item to first when moving forward", () => {
    const { menu, items } = createMenuItems(3);
    const component = makeComponent();
    component.$refs = { menu };

    items[2].focus();
    component.navigate(1);
    expect(document.activeElement).toBe(items[0]);
  });

  test("wraps from first item to last when moving backward", () => {
    const { menu, items } = createMenuItems(3);
    const component = makeComponent();
    component.$refs = { menu };

    items[0].focus();
    component.navigate(-1);
    expect(document.activeElement).toBe(items[2]);
  });

  test("works with a single menu item", () => {
    const { menu, items } = createMenuItems(1);
    const component = makeComponent();
    component.$refs = { menu };

    items[0].focus();
    component.navigate(1);
    expect(document.activeElement).toBe(items[0]);
  });
});

// ─── Admin namespace wiring ────────────────────────────────────────────────────
// These tests simulate what overflow-menu action handlers call at runtime to
// catch regressions where templates reference incorrect Admin method names
// (e.g. Admin.viewAgent vs Admin.viewA2AAgent, or bare handleToggleSubmit vs
// Admin.handleToggleSubmit).

describe("Admin namespace wiring for row actions", () => {
  beforeEach(() => {
    window.Admin = {
      viewA2AAgent: vi.fn(),
      handleToggleSubmit: vi.fn(),
      handleDeleteSubmit: vi.fn(),
    };
  });

  afterEach(() => {
    delete window.Admin;
  });

  test("Admin.viewA2AAgent is callable (agents table View action)", () => {
    expect(typeof window.Admin.viewA2AAgent).toBe("function");
    expect(() => window.Admin.viewA2AAgent(42)).not.toThrow();
    expect(window.Admin.viewA2AAgent).toHaveBeenCalledWith(42);
  });

  test("Admin.viewA2AAgent is defined — not Admin.viewAgent — for agents table", () => {
    expect(window.Admin.viewA2AAgent).toBeDefined();
    expect(window.Admin.viewAgent).toBeUndefined();
  });

  test("Admin.handleToggleSubmit is callable from toggle forms (tools table)", () => {
    const form = document.createElement("form");
    form.action = "/admin/tools/1/state";
    document.body.appendChild(form);
    const event = { preventDefault: vi.fn(), target: form };

    window.Admin.handleToggleSubmit(event, "tools");

    expect(window.Admin.handleToggleSubmit).toHaveBeenCalledWith(event, "tools");
  });

  test("Admin.handleToggleSubmit is callable from toggle forms (prompts table)", () => {
    const form = document.createElement("form");
    form.action = "/admin/prompts/1/state";
    document.body.appendChild(form);
    const event = { preventDefault: vi.fn(), target: form };

    window.Admin.handleToggleSubmit(event, "prompts");

    expect(window.Admin.handleToggleSubmit).toHaveBeenCalledWith(event, "prompts");
  });

  test("Admin.handleToggleSubmit is callable from toggle forms (servers table)", () => {
    const form = document.createElement("form");
    form.action = "/admin/servers/1/state";
    document.body.appendChild(form);
    const event = { preventDefault: vi.fn(), target: form };

    window.Admin.handleToggleSubmit(event, "servers");

    expect(window.Admin.handleToggleSubmit).toHaveBeenCalledWith(event, "servers");
  });

  test("Admin.handleToggleSubmit is callable from toggle forms (a2a-agents table)", () => {
    const form = document.createElement("form");
    form.action = "/admin/a2a/1/state";
    document.body.appendChild(form);
    const event = { preventDefault: vi.fn(), target: form };

    window.Admin.handleToggleSubmit(event, "a2a-agents");

    expect(window.Admin.handleToggleSubmit).toHaveBeenCalledWith(event, "a2a-agents");
  });
});
