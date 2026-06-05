/**
 * Unit tests for components/team-selector.js
 * Tests: teamSelector factory, init URL parsing, toggleOpen, selectAllTeams,
 *        loadTeams, updateTeamContext
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { teamSelector } from "../../../mcpgateway/admin_ui/components/team-selector.js";

// ─── Setup / teardown ─────────────────────────────────────────────────────────

beforeEach(() => {
  delete window.USER_TEAMS;
  delete window.USER_TEAMS_DATA;
  delete window.Admin;
  delete window.updateTeamContext;

  delete window.location;
  window.location = {
    href: "http://localhost/admin",
    search: "",
  };
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ─── Factory ──────────────────────────────────────────────────────────────────

describe("teamSelector factory", () => {
  test("returns open as false", () => {
    expect(teamSelector().open).toBe(false);
  });

  test("returns selectedTeam as empty string", () => {
    expect(teamSelector().selectedTeam).toBe("");
  });

  test("returns selectedTeamName as 'All Teams'", () => {
    expect(teamSelector().selectedTeamName).toBe("All Teams");
  });

  test("exposes init, toggleOpen, selectAllTeams, loadTeams, updateTeamContext", () => {
    const component = teamSelector();
    expect(typeof component.init).toBe("function");
    expect(typeof component.toggleOpen).toBe("function");
    expect(typeof component.selectAllTeams).toBe("function");
    expect(typeof component.loadTeams).toBe("function");
    expect(typeof component.updateTeamContext).toBe("function");
  });

  test("does not throw on construction", () => {
    expect(() => teamSelector()).not.toThrow();
  });
});

// ─── init ─────────────────────────────────────────────────────────────────────

describe("init — no team_id in URL", () => {
  test("keeps selectedTeam as empty string", () => {
    const component = teamSelector();
    component.init();
    expect(component.selectedTeam).toBe("");
  });

  test("keeps selectedTeamName as 'All Teams'", () => {
    const component = teamSelector();
    component.init();
    expect(component.selectedTeamName).toBe("All Teams");
  });
});

describe("init — team_id present in URL", () => {
  test("selects team from USER_TEAMS_DATA when matching id found", () => {
    window.location.search = "?team_id=t1";
    window.USER_TEAMS_DATA = [{ id: "t1", name: "Alpha", is_personal: false }];

    const component = teamSelector();
    component.init();

    expect(component.selectedTeam).toBe("t1");
    expect(component.selectedTeamName).toBe("🏢 Alpha");
  });

  test("prefixes personal team name with person emoji", () => {
    window.location.search = "?team_id=t2";
    window.USER_TEAMS_DATA = [{ id: "t2", name: "My Team", is_personal: true }];

    const component = teamSelector();
    component.init();

    expect(component.selectedTeamName).toBe("👤 My Team");
  });

  test("prefixes non-personal team name with building emoji", () => {
    window.location.search = "?team_id=t3";
    window.USER_TEAMS_DATA = [{ id: "t3", name: "Corp", is_personal: false }];

    const component = teamSelector();
    component.init();

    expect(component.selectedTeamName).toBe("🏢 Corp");
  });

  test("falls back to USER_TEAMS when USER_TEAMS_DATA is empty", () => {
    window.location.search = "?team_id=t3";
    window.USER_TEAMS_DATA = [];
    window.USER_TEAMS = [{ id: "t3", name: "Beta", is_personal: false }];

    const component = teamSelector();
    component.init();

    expect(component.selectedTeam).toBe("t3");
    expect(component.selectedTeamName).toBe("🏢 Beta");
  });

  test("falls back to USER_TEAMS when USER_TEAMS_DATA is not an array", () => {
    window.location.search = "?team_id=t4";
    window.USER_TEAMS_DATA = null;
    window.USER_TEAMS = [{ id: "t4", name: "Gamma", is_personal: false }];

    const component = teamSelector();
    component.init();

    expect(component.selectedTeam).toBe("t4");
  });

  test("calls Admin.safeReplaceState removing team_id when id not found in non-empty teams", () => {
    window.location = {
      href: "http://localhost/admin?team_id=unknown",
      search: "?team_id=unknown",
    };
    window.USER_TEAMS_DATA = [{ id: "t1", name: "Alpha", is_personal: false }];
    const safeReplaceState = vi.fn();
    window.Admin = { safeReplaceState };

    const component = teamSelector();
    component.init();

    expect(safeReplaceState).toHaveBeenCalledOnce();
    const cleanUrl = safeReplaceState.mock.calls[0][2];
    expect(cleanUrl.searchParams.has("team_id")).toBe(false);
  });

  test("does not call safeReplaceState when teams array is empty", () => {
    window.location.search = "?team_id=t1";
    window.USER_TEAMS_DATA = [];
    window.USER_TEAMS = [];
    const safeReplaceState = vi.fn();
    window.Admin = { safeReplaceState };

    const component = teamSelector();
    component.init();

    expect(safeReplaceState).not.toHaveBeenCalled();
    expect(component.selectedTeam).toBe("");
  });

  test("does not throw when team not found and Admin is absent", () => {
    window.location = {
      href: "http://localhost/admin?team_id=missing",
      search: "?team_id=missing",
    };
    window.USER_TEAMS_DATA = [{ id: "t1", name: "Alpha", is_personal: false }];
    delete window.Admin;

    const component = teamSelector();
    expect(() => component.init()).not.toThrow();
  });
});

// ─── toggleOpen ───────────────────────────────────────────────────────────────

describe("toggleOpen", () => {
  test("sets open to true when currently false", () => {
    const component = teamSelector();
    component.toggleOpen();
    expect(component.open).toBe(true);
  });

  test("sets open to false when currently true", () => {
    const component = teamSelector();
    component.open = true;
    component.toggleOpen();
    expect(component.open).toBe(false);
  });

  test("calls loadTeams after toggling", () => {
    const component = teamSelector();
    const loadSpy = vi.spyOn(component, "loadTeams");
    component.toggleOpen();
    expect(loadSpy).toHaveBeenCalledOnce();
  });
});

// ─── selectAllTeams ───────────────────────────────────────────────────────────

describe("selectAllTeams", () => {
  test("resets selectedTeam to empty string", () => {
    const component = teamSelector();
    component.selectedTeam = "t1";
    component.selectAllTeams();
    expect(component.selectedTeam).toBe("");
  });

  test("resets selectedTeamName to 'All Teams'", () => {
    const component = teamSelector();
    component.selectedTeamName = "🏢 Alpha";
    component.selectAllTeams();
    expect(component.selectedTeamName).toBe("All Teams");
  });

  test("closes the dropdown", () => {
    const component = teamSelector();
    component.open = true;
    component.selectAllTeams();
    expect(component.open).toBe(false);
  });

  test("calls updateTeamContext with empty string", () => {
    window.updateTeamContext = vi.fn();
    const component = teamSelector();
    component.selectAllTeams();
    expect(window.updateTeamContext).toHaveBeenCalledWith("");
  });
});

// ─── loadTeams ────────────────────────────────────────────────────────────────

describe("loadTeams", () => {
  test("calls Admin.loadTeamSelectorDropdown when open is true", () => {
    const loadTeamSelectorDropdown = vi.fn();
    window.Admin = { loadTeamSelectorDropdown };
    const component = teamSelector();
    component.open = true;
    component.loadTeams();
    expect(loadTeamSelectorDropdown).toHaveBeenCalledOnce();
  });

  test("does not call loadTeamSelectorDropdown when open is false", () => {
    const loadTeamSelectorDropdown = vi.fn();
    window.Admin = { loadTeamSelectorDropdown };
    const component = teamSelector();
    component.open = false;
    component.loadTeams();
    expect(loadTeamSelectorDropdown).not.toHaveBeenCalled();
  });

  test("does not throw when Admin is absent and open is true", () => {
    const component = teamSelector();
    component.open = true;
    expect(() => component.loadTeams()).not.toThrow();
  });
});

// ─── updateTeamContext ────────────────────────────────────────────────────────

describe("updateTeamContext", () => {
  test("calls window.updateTeamContext with the given teamId", () => {
    window.updateTeamContext = vi.fn();
    const component = teamSelector();
    component.updateTeamContext("t1");
    expect(window.updateTeamContext).toHaveBeenCalledWith("t1");
  });

  test("calls window.updateTeamContext with empty string", () => {
    window.updateTeamContext = vi.fn();
    const component = teamSelector();
    component.updateTeamContext("");
    expect(window.updateTeamContext).toHaveBeenCalledWith("");
  });

  test("does not throw when window.updateTeamContext is not defined", () => {
    delete window.updateTeamContext;
    const component = teamSelector();
    expect(() => component.updateTeamContext("t1")).not.toThrow();
  });

  test("does not throw when window.updateTeamContext is not a function", () => {
    window.updateTeamContext = "not-a-function";
    const component = teamSelector();
    expect(() => component.updateTeamContext("t1")).not.toThrow();
  });
});
