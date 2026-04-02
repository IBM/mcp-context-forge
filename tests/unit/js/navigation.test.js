/**
 * Unit tests for navigation.js module
 * Tests: navigateAdmin
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { navigateAdmin } from "../../../mcpgateway/admin_ui/navigation.js";

describe("navigateAdmin", () => {
  let originalLocation;
  let originalRootPath;

  beforeEach(() => {
    originalLocation = window.location;
    originalRootPath = window.ROOT_PATH;
    delete window.location;
    window.location = {
      href: "",
      origin: "http://localhost:3000",
      pathname: "/admin",
      search: "",
      hash: "",
      reload: vi.fn(),
    };
  });

  afterEach(() => {
    window.location = originalLocation;
    window.ROOT_PATH = originalRootPath;
  });

  test("navigates to admin fragment with no proxy", () => {
    window.ROOT_PATH = "";
    window.location.pathname = "/admin";

    navigateAdmin("tools");

    expect(window.location.href).toBe("http://localhost:3000/admin#tools");
  });

  test("navigates with proxy prefix preserved", () => {
    window.ROOT_PATH = "";
    window.location.pathname = "/api/proxy/mcp/admin";

    navigateAdmin("servers");

    expect(window.location.href).toBe("http://localhost:3000/api/proxy/mcp/admin#servers");
  });

  test("includes search params in navigation", () => {
    window.ROOT_PATH = "";
    window.location.pathname = "/admin";
    const params = new URLSearchParams();
    params.set("team_id", "team-123");

    navigateAdmin("gateways", params);

    expect(window.location.href).toBe("http://localhost:3000/admin?team_id=team-123#gateways");
  });

  test("includes include_inactive param", () => {
    window.ROOT_PATH = "";
    window.location.pathname = "/admin";
    const params = new URLSearchParams();
    params.set("include_inactive", "true");

    navigateAdmin("tools", params);

    expect(window.location.href).toBe("http://localhost:3000/admin?include_inactive=true#tools");
  });

  test("preserves pagination params from current URL", () => {
    window.ROOT_PATH = "";
    window.location.pathname = "/admin";
    window.location.search = "?tools_page=3&tools_size=50";

    navigateAdmin("tools");

    expect(window.location.href).toContain("tools_page=3");
    expect(window.location.href).toContain("tools_size=50");
  });

  test("preserves namespaced inactive params", () => {
    window.ROOT_PATH = "";
    window.location.pathname = "/admin";
    window.location.search = "?servers_inactive=true";

    navigateAdmin("servers");

    expect(window.location.href).toContain("servers_inactive=true");
  });

  test("preserves search query params", () => {
    window.ROOT_PATH = "";
    window.location.pathname = "/admin";
    window.location.search = "?tools_q=search-term";

    navigateAdmin("tools");

    expect(window.location.href).toContain("tools_q=search-term");
  });

  test("preserves tags filter params", () => {
    window.ROOT_PATH = "";
    window.location.pathname = "/admin";
    window.location.search = "?tools_tags=tag1,tag2";

    navigateAdmin("tools");

    expect(window.location.href).toContain("tools_tags=tag1%2Ctag2");
  });

  test("does not override provided search params with current URL params", () => {
    window.ROOT_PATH = "";
    window.location.pathname = "/admin";
    window.location.search = "?tools_page=5";
    const params = new URLSearchParams();
    params.set("tools_page", "1");

    navigateAdmin("tools", params);

    expect(window.location.href).toContain("tools_page=1");
    expect(window.location.href).not.toContain("tools_page=5");
  });

  test("reloads page when target URL is identical to current URL", () => {
    window.ROOT_PATH = "";
    window.location.pathname = "/admin";
    window.location.search = "";
    window.location.hash = "#tools";
    window.location.href = "http://localhost:3000/admin#tools";

    navigateAdmin("tools");

    expect(window.location.reload).toHaveBeenCalled();
  });

  test("does not reload when URL is different", () => {
    window.ROOT_PATH = "";
    window.location.pathname = "/admin";
    window.location.search = "";
    window.location.hash = "#servers";
    window.location.href = "http://localhost:3000/admin#servers";

    navigateAdmin("tools");

    expect(window.location.reload).not.toHaveBeenCalled();
    expect(window.location.href).toBe("http://localhost:3000/admin#tools");
  });

  test("handles deep proxy paths", () => {
    window.ROOT_PATH = "";
    window.location.pathname = "/api/v1/proxy/mcp/admin";

    navigateAdmin("catalog");

    expect(window.location.href).toBe("http://localhost:3000/api/v1/proxy/mcp/admin#catalog");
  });

  test("uses ROOT_PATH when /admin not found in pathname", () => {
    window.ROOT_PATH = "http://localhost:3000/custom";
    window.location.pathname = "/some/other/path";

    navigateAdmin("tools");

    expect(window.location.href).toBe("http://localhost:3000/custom/admin#tools");
  });

  test("uses origin when ROOT_PATH empty and /admin not found", () => {
    window.ROOT_PATH = "";
    window.location.pathname = "/other";

    navigateAdmin("servers");

    expect(window.location.href).toBe("http://localhost:3000/admin#servers");
  });

  test("handles multiple query params", () => {
    window.ROOT_PATH = "";
    window.location.pathname = "/admin";
    const params = new URLSearchParams();
    params.set("team_id", "team-1");
    params.set("include_inactive", "true");
    params.set("custom", "value");

    navigateAdmin("resources", params);

    expect(window.location.href).toContain("team_id=team-1");
    expect(window.location.href).toContain("include_inactive=true");
    expect(window.location.href).toContain("custom=value");
  });

  test("handles administrator path segment correctly", () => {
    window.ROOT_PATH = "";
    window.location.pathname = "/administrator/admin";

    navigateAdmin("tools");

    expect(window.location.href).toBe("http://localhost:3000/administrator/admin#tools");
  });
});
