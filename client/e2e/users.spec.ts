import { test, expect } from "./fixtures/api-mock";
import { APP } from "./utils/paths";
import type { User } from "../src/types/user";

// Logged-in admin (from apiMock.mockMe) uses DEFAULT_TEST_USER: email = "test@example.com".
// MOCK_USER uses a different email so tests can delete/edit without self-conflict.
const MOCK_USER: User = {
  email: "john@example.com",
  full_name: "John Doe",
  is_admin: false,
  is_active: true,
  auth_provider: "None",
  created_at: "2026-06-16T13:01:12",
  updated_at: "2026-06-16T13:05:34",
  last_login: "2026-06-17T14:09:56",
  email_verified: true,
  password_change_required: false,
  failed_login_attempts: 0,
  is_locked: false,
};

const MOCK_USER_2: User = {
  email: "jane@example.com",
  full_name: "Jane Smith",
  is_admin: false,
  is_active: true,
  auth_provider: "None",
  created_at: "2026-06-16T14:00:00",
  updated_at: "2026-06-16T14:00:00",
  last_login: "2026-06-17T10:00:00",
  email_verified: true,
  password_change_required: false,
  failed_login_attempts: 0,
  is_locked: false,
};

// encodeURIComponent("john@example.com") = "john%40example.com"
const MOCK_USER_ROUTE = `**/auth/email/admin/users/${encodeURIComponent(MOCK_USER.email)}`;

test.describe("Users page", () => {
  test.beforeEach(async ({ page, apiMock }) => {
    await apiMock.mockMe();

    await page.addInitScript(() => {
      sessionStorage.setItem("mcpgateway_token", "mock-token-12345");
    });
  });

  test("shows users list", async ({ page }) => {
    await page.route("**/auth/email/admin/users?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ users: [MOCK_USER] }),
      });
    });

    await page.goto(APP.USERS);
    await page.waitForLoadState("networkidle");

    const main = page.getByRole("main");
    await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();
    await expect(main.getByText("John Doe")).toBeVisible();
    await expect(main.getByText("john@example.com")).toBeVisible();
    await expect(page.getByRole("cell", { name: "User" })).toBeVisible();
    await expect(main.getByText("Active")).toBeVisible();
  });

  test("loads more users when pagination cursor is present", async ({ page }) => {
    await page.route("**/auth/email/admin/users?*", async (route) => {
      const url = new URL(route.request().url());
      const hasCursor = url.searchParams.has("cursor");

      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          hasCursor ? { users: [MOCK_USER_2] } : { users: [MOCK_USER], nextCursor: "cursor-1" },
        ),
      });
    });

    await page.goto(APP.USERS);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("John Doe")).toBeVisible();
    await expect(page.getByText("Jane Smith")).not.toBeVisible();

    const loadMoreButton = page.getByRole("button", { name: "Load more users" });
    await expect(loadMoreButton).toBeVisible();
    await loadMoreButton.click();

    await expect(page.getByText("Jane Smith")).toBeVisible();
    await expect(page.getByText("John Doe")).toBeVisible();
    await expect(loadMoreButton).not.toBeVisible();
  });

  test("creates a user", async ({ page }) => {
    let createCount = 0;

    await page.route("**/auth/email/admin/users?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ users: [] }),
      });
    });
    await page.route("**/auth/email/admin/users", async (route) => {
      expect(route.request().method()).toBe("POST");
      createCount++;
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          email: "newuser@example.com",
          full_name: "New User",
          is_admin: false,
          is_active: true,
          auth_provider: "email",
          created_at: new Date().toISOString(),
          email_verified: false,
          password_change_required: false,
          failed_login_attempts: 0,
          is_locked: false,
        } satisfies User),
      });
    });

    await page.goto(APP.USERS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Create User" }).click();

    await expect(page.getByRole("heading", { name: "Create User" })).toBeVisible();

    await page.locator("#user-email").fill("newuser@example.com");
    await page.locator("#user-password").fill("securepassword");
    await page.locator("#user-confirm-password").fill("securepassword");

    await page.getByRole("button", { name: "Create User" }).click();

    await expect.poll(() => createCount).toBe(1);
    await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();
    await expect(page.getByText("newuser@example.com")).toBeVisible();
  });

  test.describe("create user form validation", () => {
    test.beforeEach(async ({ page }) => {
      await page.route("**/auth/email/admin/users?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ users: [] }),
        });
      });

      await page.goto(APP.USERS);
      await page.waitForLoadState("networkidle");
      await page.getByRole("button", { name: "Create User" }).click();
      await expect(page.getByRole("heading", { name: "Create User" })).toBeVisible();
    });

    test("email is required", async ({ page }) => {
      await page.locator("#user-password").fill("securepassword");
      await page.locator("#user-confirm-password").fill("securepassword");

      await page.getByRole("button", { name: "Create User" }).click();

      await expect(page.getByText("Invalid email address")).toBeVisible();
    });

    test("password is required", async ({ page }) => {
      await page.locator("#user-email").fill("user@example.com");

      await page.getByRole("button", { name: "Create User" }).click();

      await expect(page.getByText("Password must be at least 8 characters")).toBeVisible();
    });

    test("passwords must match", async ({ page }) => {
      await page.locator("#user-email").fill("user@example.com");
      await page.locator("#user-password").fill("securepassword");
      await page.locator("#user-confirm-password").fill("differentpassword");

      await page.getByRole("button", { name: "Create User" }).click();

      await expect(page.getByText("Passwords do not match")).toBeVisible();
    });

    test("all other fields are optional", async ({ page }) => {
      let createCalled = false;
      await page.route("**/auth/email/admin/users", async (route) => {
        createCalled = true;
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            email: "minimal@example.com",
            is_admin: false,
            is_active: true,
            auth_provider: "email",
            created_at: new Date().toISOString(),
            email_verified: false,
            password_change_required: false,
            failed_login_attempts: 0,
            is_locked: false,
          } satisfies User),
        });
      });

      await page.locator("#user-email").fill("minimal@example.com");
      await page.locator("#user-password").fill("securepassword");
      await page.locator("#user-confirm-password").fill("securepassword");

      await page.getByRole("button", { name: "Create User" }).click();

      await expect.poll(() => createCalled).toBe(true);
    });
  });

  test("edits a user", async ({ page }) => {
    const updatedUser: User = { ...MOCK_USER, full_name: "John Updated" };
    let patchCount = 0;

    await page.route("**/auth/email/admin/users?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ users: [MOCK_USER] }),
      });
    });
    await page.route(MOCK_USER_ROUTE, async (route) => {
      expect(route.request().method()).toBe("PATCH");
      patchCount++;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(updatedUser),
      });
    });

    await page.goto(APP.USERS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for John Doe" }).click();
    await page.getByRole("menuitem", { name: "Edit" }).click();

    await expect(page.getByRole("heading", { name: "Edit User" })).toBeVisible();

    await page.locator("#user-full-name").clear();
    await page.locator("#user-full-name").fill("John Updated");

    await page.getByRole("button", { name: "Save Changes" }).click();

    await expect.poll(() => patchCount).toBe(1);
    await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();
    await expect(page.getByText("John Updated")).toBeVisible();
    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: /updated successfully/ }),
    ).toBeVisible();
  });

  test.describe("edit user form validation", () => {
    test.beforeEach(async ({ page }) => {
      await page.route("**/auth/email/admin/users?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ users: [MOCK_USER] }),
        });
      });

      await page.goto(APP.USERS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Actions for John Doe" }).click();
      await page.getByRole("menuitem", { name: "Edit" }).click();
      await expect(page.getByRole("heading", { name: "Edit User" })).toBeVisible();
    });

    test("password is not required", async ({ page }) => {
      let patchCalled = false;
      await page.route(MOCK_USER_ROUTE, async (route) => {
        patchCalled = true;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_USER),
        });
      });

      await page.getByRole("button", { name: "Save Changes" }).click();

      await expect.poll(() => patchCalled).toBe(true);
      await expect(page.getByText("Password must be at least 8 characters")).not.toBeVisible();
    });

    test("passwords must match if password is filled", async ({ page }) => {
      await page.locator("#user-password").fill("newpassword123");
      await page.locator("#user-confirm-password").fill("differentpassword");

      await page.getByRole("button", { name: "Save Changes" }).click();

      await expect(page.getByText("Passwords do not match")).toBeVisible();
    });

    test("all other fields are optional", async ({ page }) => {
      let patchCalled = false;
      await page.route(MOCK_USER_ROUTE, async (route) => {
        patchCalled = true;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_USER),
        });
      });

      await page.getByRole("button", { name: "Save Changes" }).click();

      await expect.poll(() => patchCalled).toBe(true);
    });
  });

  test("optimistically removes user on delete confirmation and shows success toast", async ({
    page,
  }) => {
    let deleteRequestCount = 0;

    await page.route("**/auth/email/admin/users?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ users: [MOCK_USER, MOCK_USER_2] }),
      });
    });
    await page.route(MOCK_USER_ROUTE, async (route) => {
      expect(route.request().method()).toBe("DELETE");
      deleteRequestCount++;
      await route.fulfill({ status: 204 });
    });

    await page.goto(APP.USERS);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("John Doe")).toBeVisible();
    await expect(page.getByText("Jane Smith")).toBeVisible();

    await page.getByRole("button", { name: "Actions for John Doe" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByText(
        "Are you sure you want to delete John Doe (john@example.com)? This action cannot be undone.",
      ),
    ).toBeVisible();

    await dialog.getByRole("button", { name: "Delete User" }).click();

    // Optimistic: dialog closes and user disappears immediately before API resolves
    await expect(dialog).not.toBeVisible();
    await expect(page.getByText("John Doe")).not.toBeVisible();
    await expect(page.getByText("Jane Smith")).toBeVisible();

    await expect.poll(() => deleteRequestCount).toBe(1);
    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: /deleted successfully/ }),
    ).toBeVisible();
  });

  test("cancels delete dialog and keeps user in list", async ({ page }) => {
    await page.route("**/auth/email/admin/users?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ users: [MOCK_USER] }),
      });
    });

    await page.goto(APP.USERS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for John Doe" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toBeVisible();

    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).not.toBeVisible();

    await expect(page.getByText("John Doe")).toBeVisible();
  });

  test("rolls back optimistic delete and shows error toast when delete API fails", async ({
    page,
  }) => {
    let deleteRequestCount = 0;

    await page.route("**/auth/email/admin/users?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ users: [MOCK_USER, MOCK_USER_2] }),
      });
    });
    await page.route(MOCK_USER_ROUTE, async (route) => {
      expect(route.request().method()).toBe("DELETE");
      deleteRequestCount++;
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Internal Server Error" }),
      });
    });

    await page.goto(APP.USERS);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("John Doe")).toBeVisible();

    await page.getByRole("button", { name: "Actions for John Doe" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("alertdialog");
    await dialog.getByRole("button", { name: "Delete User" }).click();

    // Optimistic: dialog closes and user is removed immediately
    await expect(dialog).not.toBeVisible();

    // API fails → user is rolled back into the table
    await expect.poll(() => deleteRequestCount).toBe(1);
    await expect(page.getByText("John Doe")).toBeVisible();
    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: /Failed to delete user/ }),
    ).toBeVisible();
  });

  test("blocks self-delete client-side: no API call fires, dialog closes, error toast shown", async ({
    page,
  }) => {
    // DEFAULT_TEST_USER (logged-in user) has email "test@example.com"
    const selfUser: User = { ...MOCK_USER, email: "test@example.com", full_name: "Test User" };

    await page.route("**/auth/email/admin/users?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ users: [selfUser] }),
      });
    });

    // Track whether the DELETE endpoint is ever called — it must NOT be
    let deleteCallCount = 0;
    await page.route("**/auth/email/admin/users/test%40example.com", async (route) => {
      if (route.request().method() === "DELETE") {
        deleteCallCount++;
      }
      // Fulfill just in case, but we assert it's never reached
      await route.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Cannot delete your own account" }),
      });
    });

    await page.goto(APP.USERS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for Test User" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Delete User" }).click();

    // Client-side guard fires: dialog closes immediately with no round-trip
    await expect(dialog).not.toBeVisible();
    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: "You cannot delete your own account" }),
    ).toBeVisible();

    // User stays in the table (no optimistic removal happened)
    await expect(page.getByText("test@example.com")).toBeVisible();

    // The DELETE API was never called
    expect(deleteCallCount).toBe(0);
  });
});
