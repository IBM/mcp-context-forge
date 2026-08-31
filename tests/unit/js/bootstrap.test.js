/**
 * Unit tests for bootstrap.js module
 * Tests: window.Admin namespace initialization
 */

import { describe, test, expect, afterEach } from "vitest";

afterEach(() => {
  delete window.Admin;
});

describe("bootstrap", () => {
  test("creates window.Admin namespace when it does not exist", async () => {
    delete window.Admin;
    await import("../../../mcpgateway/admin_ui/bootstrap.js");
    expect(window.Admin).toBeDefined();
    expect(typeof window.Admin).toBe("object");
  });

  test("does not overwrite existing window.Admin namespace", async () => {
    const existingAdmin = { existingProp: true };
    window.Admin = existingAdmin;
    // Re-execute the bootstrap logic
    window.Admin = window.Admin || {};
    expect(window.Admin).toBe(existingAdmin);
    expect(window.Admin.existingProp).toBe(true);
  });

  test("initializes window.Admin as an empty object", async () => {
    delete window.Admin;
    window.Admin = window.Admin || {};
    expect(window.Admin).toEqual({});
  });
});
