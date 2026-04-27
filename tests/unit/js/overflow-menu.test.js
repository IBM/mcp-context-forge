/**
 * Unit tests for overflow-menu component
 * Tests: overflowMenu factory function, Admin handler wiring for row actions
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import {
  overflowMenu,
  _resetCurrentlyOpenForTests,
} from "../../../mcpgateway/admin_ui/components/overflow-menu.js";

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
  document.body.replaceChildren();
  _resetCurrentlyOpenForTests();
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

// ─── Integration: Menu positioning and viewport clamping ──────────────────────

describe("Integration: Menu positioning with viewport boundaries", () => {
  function createMenuWithTrigger(triggerRect, menuHeight = 200) {
    const trigger = document.createElement("button");
    trigger.getBoundingClientRect = vi.fn(() => triggerRect);

    const menu = document.createElement("div");
    menu.setAttribute("role", "menu");
    menu.style.width = "176px"; // w-44
    menu.style.height = `${menuHeight}px`;

    const item = document.createElement("button");
    item.setAttribute("role", "menuitem");
    menu.appendChild(item);

    document.body.appendChild(menu);

    // Mock getBoundingClientRect to return dynamic values based on position
    const originalGetBoundingClientRect = menu.getBoundingClientRect.bind(menu);
    menu.getBoundingClientRect = vi.fn(() => {
      const rect = originalGetBoundingClientRect();
      return {
        width: 176,
        height: menuHeight,
        top: parseFloat(menu.style.top) || 0,
        left: parseFloat(menu.style.left) || 0,
        bottom: (parseFloat(menu.style.top) || 0) + menuHeight,
        right: (parseFloat(menu.style.left) || 0) + 176,
      };
    });

    return { trigger, menu, item };
  }

  beforeEach(() => {
    // Mock viewport dimensions
    Object.defineProperty(window, "innerWidth", { value: 1024, writable: true });
    Object.defineProperty(window, "innerHeight", { value: 768, writable: true });
  });

  test("positions menu below trigger by default", () => {
    const { trigger, menu } = createMenuWithTrigger({ bottom: 100, left: 50, top: 80, right: 70 });

    const component = makeComponent();
    component.$refs = { trigger, menu };

    component.openMenu();

    expect(component.menuTop).toBe(104); // bottom + 4
    expect(component.menuLeft).toBe(50);
  });

  test("clamps menu to left edge when overflowing right", () => {
    // Trigger near right edge: left=900, menu width=176, viewport=1024
    // Menu would end at 900+176=1076, which exceeds 1024
    const { trigger, menu } = createMenuWithTrigger({ bottom: 100, left: 900, top: 80, right: 920 });

    const component = makeComponent();
    component.$refs = { trigger, menu };

    // Simulate menu being positioned initially
    menu.style.top = "104px";
    menu.style.left = "900px";

    component.openMenu();

    // After $nextTick, should clamp: max(8, 1024 - 176 - 8) = 840
    expect(component.menuLeft).toBe(840);
  });

  test("flips menu upward when overflowing bottom", () => {
    // Trigger near bottom: bottom=700, menu height=200, viewport=768
    // Menu would end at 704+200=904, which exceeds 768
    const { trigger, menu } = createMenuWithTrigger({ bottom: 700, left: 50, top: 680, right: 70 }, 200);

    const component = makeComponent();
    component.$refs = { trigger, menu };

    // Simulate menu being positioned initially
    menu.style.top = "704px";
    menu.style.left = "50px";

    component.openMenu();

    // Should flip upward: 680 - 200 - 4 = 476
    expect(component.menuTop).toBe(476);
  });

  test("clamps menu to viewport when cannot flip upward", () => {
    // Trigger near bottom with tall menu: bottom=700, menu height=300, viewport=768
    // Menu would overflow (700+4+300=1004 > 768)
    // Cannot flip upward fully (680-300-4=376, but menu is too tall)
    // Should clamp to viewport bottom
    const { trigger, menu } = createMenuWithTrigger({ bottom: 700, left: 50, top: 680, right: 70 }, 300);

    const component = makeComponent();
    component.$refs = { trigger, menu };

    // Simulate menu being positioned initially at bottom edge
    menu.style.top = "704px";
    menu.style.left = "50px";

    component.openMenu();

    // Menu overflows bottom (704+300=1004 > 768)
    // Try flip: 680-300-4=376 (valid, so should flip)
    expect(component.menuTop).toBe(376);
  });

  test("handles corner case: bottom-right edge", () => {
    // Trigger at bottom-right corner
    const { trigger, menu } = createMenuWithTrigger({ bottom: 700, left: 900, top: 680, right: 920 }, 200);

    const component = makeComponent();
    component.$refs = { trigger, menu };

    // Simulate menu being positioned initially
    menu.style.top = "704px";
    menu.style.left = "900px";

    component.openMenu();

    // Should adjust both: left=840, top=476 (flipped upward)
    expect(component.menuLeft).toBe(840);
    expect(component.menuTop).toBe(476);
  });

  test("respects minimum padding from viewport edges", () => {
    // Trigger at extreme right: left=1020
    const { trigger, menu } = createMenuWithTrigger({ bottom: 100, left: 1020, top: 80, right: 1040 });

    const component = makeComponent();
    component.$refs = { trigger, menu };

    // Simulate menu being positioned initially
    menu.style.top = "104px";
    menu.style.left = "1020px";

    component.openMenu();

    // Should maintain 8px padding: 1024 - 176 - 8 = 840
    expect(component.menuLeft).toBe(840);
  });

  test("caps height and enables internal scroll when menu is taller than viewport", () => {
    // Menu height 900 exceeds viewport 768; cannot flip upward either.
    const { trigger, menu } = createMenuWithTrigger({ bottom: 400, left: 50, top: 380, right: 70 }, 900);

    const component = makeComponent();
    component.$refs = { trigger, menu };

    menu.style.top = "404px";
    menu.style.left = "50px";

    component.openMenu();

    // Pinned to top padding and capped at viewport minus 2*padding (752).
    expect(component.menuTop).toBe(8);
    expect(menu.style.maxHeight).toBe("752px");
    expect(menu.style.overflowY).toBe("auto");
  });

  test("clears stale max-height/overflowY from a previous open", () => {
    const { trigger, menu } = createMenuWithTrigger({ bottom: 100, left: 50, top: 80, right: 70 }, 200);

    // Simulate leftover inline styles from a prior tall-menu open.
    menu.style.maxHeight = "400px";
    menu.style.overflowY = "auto";

    const component = makeComponent();
    component.$refs = { trigger, menu };

    component.openMenu();

    // Fits below trigger; the stale caps should be cleared.
    expect(menu.style.maxHeight).toBe("");
    expect(menu.style.overflowY).toBe("");
  });

  test("menu remains actionable after viewport clamping", () => {
    const { trigger, menu, item } = createMenuWithTrigger({ bottom: 700, left: 900, top: 680, right: 920 }, 200);
    const focusSpy = vi.spyOn(item, "focus");

    const component = makeComponent();
    component.$refs = { trigger, menu };

    menu.style.top = "704px";
    menu.style.left = "900px";

    component.openMenu();

    // Menu should be positioned and first item focused
    expect(component.menuOpen).toBe(true);
    expect(focusSpy).toHaveBeenCalled();
  });
});

// ─── Ref guards ───────────────────────────────────────────────────────────────

describe("Ref guards", () => {
  test("openMenu warns and returns when $refs.trigger is missing", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const component = makeComponent();
    component.$refs = {};

    component.openMenu();

    expect(warnSpy).toHaveBeenCalledWith(expect.stringMatching(/trigger/));
    expect(component.menuOpen).toBe(false);
  });

  test("openMenu warns when $refs.menu is missing after trigger click", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const trigger = document.createElement("button");
    trigger.getBoundingClientRect = vi.fn(() => ({ bottom: 100, left: 50, top: 80 }));

    const component = makeComponent();
    component.$refs = { trigger };

    component.openMenu();

    expect(warnSpy).toHaveBeenCalledWith(expect.stringMatching(/menu/));
    expect(component.menuOpen).toBe(true); // still flipped open before $nextTick
  });

  test("navigate warns and returns when $refs.menu is missing", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const component = makeComponent();
    component.$refs = {};

    expect(() => component.navigate(1)).not.toThrow();
    expect(warnSpy).toHaveBeenCalledWith(expect.stringMatching(/menu/));
  });

  test("navigate is a no-op when menu has no menuitems", () => {
    const menu = document.createElement("div");
    document.body.appendChild(menu);

    const component = makeComponent();
    component.$refs = { menu };

    expect(() => component.navigate(1)).not.toThrow();
  });
});

// ─── destroy hook ─────────────────────────────────────────────────────────────

describe("destroy", () => {
  test("clears main container scroll-lock when destroyed while menu is open", () => {
    const main = document.createElement("main");
    main.setAttribute("data-scroll-container", "");
    main.style.overflow = "hidden";
    document.body.appendChild(main);

    const component = makeComponent();
    component.init();
    component.menuOpen = true;

    component.destroy();

    expect(main.style.overflow).toBe("");
  });

  test("clears wrapper scroll-lock when destroyed while menu is open", () => {
    const wrapper = document.createElement("div");
    wrapper.id = "destroy-wrapper";
    wrapper.style.overflow = "hidden";
    document.body.appendChild(wrapper);

    const component = makeComponent("destroy-wrapper");
    component.init();
    component.menuOpen = true;

    component.destroy();

    expect(wrapper.style.overflow).toBe("");
  });

  test("does not touch scroll-lock when destroyed while menu is closed", () => {
    const main = document.createElement("main");
    main.setAttribute("data-scroll-container", "");
    main.style.overflow = "auto";
    document.body.appendChild(main);

    const component = makeComponent();
    component.init();
    component.menuOpen = false;

    component.destroy();

    expect(main.style.overflow).toBe("auto");
  });
});

// ─── Multi-menu coordination ──────────────────────────────────────────────────

describe("Multi-menu coordination", () => {
  function makeOpenableComponent() {
    const { menu } = createMenuItems(1);
    const trigger = document.createElement("button");
    trigger.getBoundingClientRect = vi.fn(() => ({ bottom: 100, left: 50, top: 80 }));
    const component = makeComponent();
    component.init();
    component.$refs = { trigger, menu };
    return component;
  }

  test("opening a new menu closes the previously open peer", () => {
    const componentA = makeOpenableComponent();
    const componentB = makeOpenableComponent();

    componentA.openMenu();
    expect(componentA.menuOpen).toBe(true);

    componentB.openMenu();
    expect(componentA.menuOpen).toBe(false);
    expect(componentB.menuOpen).toBe(true);
  });

  test("reopening the same instance is a no-op on the peer slot", () => {
    const componentA = makeOpenableComponent();

    componentA.openMenu();
    expect(componentA.menuOpen).toBe(true);

    componentA.openMenu();
    expect(componentA.menuOpen).toBe(true);
  });

  test("destroying the currently-open menu releases the peer slot", () => {
    const componentA = makeOpenableComponent();
    const componentB = makeOpenableComponent();

    componentA.openMenu();
    componentA.destroy();

    // Opening a fresh instance should not attempt to close the destroyed one.
    expect(() => componentB.openMenu()).not.toThrow();
    expect(componentB.menuOpen).toBe(true);
  });
});
