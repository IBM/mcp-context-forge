/**
 * Unit tests for config/state lookup functions.
 * Tests pure functions - no DOM required.
 */

import { describe, test, expect, beforeEach } from "vitest";
import { isAdminUser, getRootPath } from "../../mcpgateway/admin_ui/utils.js";
import {
  getPerformanceAggregationConfig,
  getPerformanceAggregationLabel,
  getPerformanceAggregationQuery,
} from "../../mcpgateway/admin_ui/logging.js";

// ---------------------------------------------------------------------------
// isAdminUser
// ---------------------------------------------------------------------------
describe("isAdminUser", () => {
  beforeEach(() => {
    delete window.IS_ADMIN;
  });

  test("returns true when IS_ADMIN is true", () => {
    window.IS_ADMIN = true;
    expect(isAdminUser()).toBe(true);
  });

  test("returns true when IS_ADMIN is truthy string", () => {
    window.IS_ADMIN = "yes";
    expect(isAdminUser()).toBe(true);
  });

  test("returns false when IS_ADMIN is false", () => {
    window.IS_ADMIN = false;
    expect(isAdminUser()).toBe(false);
  });

  test("returns false when IS_ADMIN is undefined", () => {
    window.IS_ADMIN = undefined;
    expect(isAdminUser()).toBe(false);
  });

  test("returns false when IS_ADMIN is null", () => {
    window.IS_ADMIN = null;
    expect(isAdminUser()).toBe(false);
  });

  test("returns false when IS_ADMIN is 0", () => {
    window.IS_ADMIN = 0;
    expect(isAdminUser()).toBe(false);
  });

  test("returns false when IS_ADMIN is empty string", () => {
    window.IS_ADMIN = "";
    expect(isAdminUser()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// getRootPath
// ---------------------------------------------------------------------------
describe("getRootPath", () => {
  beforeEach(() => {
    delete window.ROOT_PATH;
  });

  test("returns ROOT_PATH when set", () => {
    window.ROOT_PATH = "/gateway";
    expect(getRootPath()).toBe("/gateway");
  });

  test("returns empty string when ROOT_PATH is undefined", () => {
    window.ROOT_PATH = undefined;
    expect(getRootPath()).toBe("");
  });

  test("returns empty string when ROOT_PATH is null", () => {
    window.ROOT_PATH = null;
    expect(getRootPath()).toBe("");
  });

  test("returns empty string when ROOT_PATH is empty", () => {
    window.ROOT_PATH = "";
    expect(getRootPath()).toBe("");
  });
});

// ---------------------------------------------------------------------------
// getAuthenticatedUserId (local implementation for testing)
// ---------------------------------------------------------------------------
describe("getAuthenticatedUserId", () => {
  // Local implementation since it's not exported from llmChat.js
  const getAuthenticatedUserId = () => {
    const currentUser = window.CURRENT_USER;
    if (!currentUser) {
      return "";
    }
    if (typeof currentUser === "string") {
      return currentUser;
    }
    if (typeof currentUser === "object") {
      return (
        currentUser.id ||
        currentUser.user_id ||
        currentUser.sub ||
        currentUser.email ||
        ""
      );
    }
    return "";
  };

  beforeEach(() => {
    delete window.CURRENT_USER;
  });

  test("returns empty string when CURRENT_USER is undefined", () => {
    window.CURRENT_USER = undefined;
    expect(getAuthenticatedUserId()).toBe("");
  });

  test("returns empty string when CURRENT_USER is null", () => {
    window.CURRENT_USER = null;
    expect(getAuthenticatedUserId()).toBe("");
  });

  test("returns string when CURRENT_USER is a string", () => {
    window.CURRENT_USER = "admin@example.com";
    expect(getAuthenticatedUserId()).toBe("admin@example.com");
  });

  test("extracts id from object", () => {
    window.CURRENT_USER = { id: "user-123" };
    expect(getAuthenticatedUserId()).toBe("user-123");
  });

  test("extracts user_id from object", () => {
    window.CURRENT_USER = { user_id: "u456" };
    expect(getAuthenticatedUserId()).toBe("u456");
  });

  test("extracts sub from object", () => {
    window.CURRENT_USER = { sub: "subject-789" };
    expect(getAuthenticatedUserId()).toBe("subject-789");
  });

  test("extracts email from object", () => {
    window.CURRENT_USER = { email: "user@test.com" };
    expect(getAuthenticatedUserId()).toBe("user@test.com");
  });

  test("prefers id over user_id over sub over email", () => {
    window.CURRENT_USER = {
      id: "id-1",
      user_id: "uid-2",
      sub: "sub-3",
      email: "e@x.com",
    };
    expect(getAuthenticatedUserId()).toBe("id-1");
  });

  test("returns empty string for empty object", () => {
    window.CURRENT_USER = {};
    expect(getAuthenticatedUserId()).toBe("");
  });
});

// ---------------------------------------------------------------------------
// getPerformanceAggregationConfig / Label / Query
// ---------------------------------------------------------------------------
describe("getPerformanceAggregationConfig", () => {
  test("returns 5m config by default", () => {
    const result = getPerformanceAggregationConfig("5m");
    expect(result).toEqual({
      label: "5-minute aggregation",
      query: "5m",
    });
  });

  test("returns 24h config", () => {
    const result = getPerformanceAggregationConfig("24h");
    expect(result).toEqual({
      label: "24-hour aggregation",
      query: "24h",
    });
  });

  test("falls back to 5m for unknown key", () => {
    const result = getPerformanceAggregationConfig("unknown");
    expect(result).toEqual({
      label: "5-minute aggregation",
      query: "5m",
    });
  });

  test("getPerformanceAggregationLabel returns label for 5m", () => {
    expect(getPerformanceAggregationLabel("5m")).toBe("5-minute aggregation");
  });

  test("getPerformanceAggregationLabel returns label for 24h", () => {
    expect(getPerformanceAggregationLabel("24h")).toBe("24-hour aggregation");
  });

  test("getPerformanceAggregationQuery returns query for 5m", () => {
    expect(getPerformanceAggregationQuery("5m")).toBe("5m");
  });

  test("getPerformanceAggregationQuery returns query for 24h", () => {
    expect(getPerformanceAggregationQuery("24h")).toBe("24h");
  });
});
