import { test, expect } from "./fixtures/api-mock";
import { APP } from "./utils/paths";
import type { ResourceRead } from "../src/generated/types";

const MOCK_RESOURCE: NonNullable<ResourceRead> = {
  id: "res-123abc456def789", // pragma: allowlist secret
  uri: "resource://test/document.txt",
  name: "Test Document",
  description: "A test resource for E2E testing",
  mimeType: "text/plain",
  size: 1024,
  tags: ["test", "document"],
  enabled: true,
  createdAt: "2026-04-28T15:41:31.233166",
  updatedAt: "2026-04-28T15:41:31.233168",
  createdBy: "admin@example.com",
  teamId: "0a9b06bd22974fe386dcacb18548ed61", // pragma: allowlist secret
  team: "Platform Administrator's Team",
  ownerEmail: "admin@example.com",
  visibility: "public",
  gatewayId: "gw-123",
};

const MOCK_RESOURCE_JSON: NonNullable<ResourceRead> = {
  id: "res-json-789xyz", // pragma: allowlist secret
  uri: "resource://api/config.json",
  name: "API Configuration",
  description: "JSON configuration for API endpoints",
  mimeType: "application/json",
  size: 2048,
  tags: ["config", "api"],
  enabled: true,
  createdAt: "2026-04-28T16:00:00.000000",
  updatedAt: "2026-04-28T16:00:00.000000",
  createdBy: "admin@example.com",
  teamId: "0a9b06bd22974fe386dcacb18548ed61", // pragma: allowlist secret
  team: "Platform Administrator's Team",
  ownerEmail: "admin@example.com",
  visibility: "team",
  gatewayId: "gw-456",
};

test.describe("Resources page", () => {
  test.beforeEach(async ({ page, apiMock }) => {
    // Mock authentication
    await apiMock.mockMe();

    // Set auth token in sessionStorage
    await page.addInitScript(() => {
      sessionStorage.setItem("mcpgateway_token", "mock-token-12345");
    });
  });

  test("shows add resources card when no resources exist", async ({ page }) => {
    // Mock empty resources response
    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    // Check for "Add resources" card (first card in grid)
    await expect(page.getByText("Add resources")).toBeVisible();
    await expect(
      page.getByText(/Resources will appear automatically when you connect a MCP server/),
    ).toBeVisible();
  });

  test("shows individual resource cards when resources exist", async ({ page }) => {
    // Mock resources response with data
    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([MOCK_RESOURCE]),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    // Check for resources heading
    await expect(page.getByRole("heading", { name: "Resources" })).toBeVisible();

    // Check for "Add resources" card
    await expect(page.getByText("Add resources")).toBeVisible();

    // Check for individual resource card with resource name
    await expect(page.getByText("Test Document")).toBeVisible();
  });

  test("displays resource card with metadata badges", async ({ page }) => {
    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([MOCK_RESOURCE]),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    // Check for resource name in card header
    await expect(page.getByText("Test Document")).toBeVisible();

    // Check for MIME type badge
    await expect(page.getByText("text/plain")).toBeVisible();
  });

  test("clicking add resources card opens form", async ({ page }) => {
    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    // Click the "Add resources" card
    await page.getByText("Add resources").click();

    // Check form is visible
    await expect(page.getByLabel("URI")).toBeVisible();
    await expect(page.getByLabel("Name")).toBeVisible();
  });

  test("shows error state when API fails", async ({ page }) => {
    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Internal server error" }),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByText("Error loading resources")).toBeVisible();
  });

  test("displays multiple individual resource cards correctly", async ({ page }) => {
    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([MOCK_RESOURCE, MOCK_RESOURCE_JSON]),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    // Check for both individual resource cards
    await expect(page.getByText("Test Document")).toBeVisible();
    await expect(page.getByText("API Configuration")).toBeVisible();

    // Should have 3 cards total (2 resources + 1 add card)
    const cards = page.locator('[data-slot="card"]');
    await expect(cards).toHaveCount(3);
  });

  test("displays resources from different gateways as individual cards", async ({ page }) => {
    const resource1 = { ...MOCK_RESOURCE, gatewayId: "gateway-a", name: "Resource A" };
    const resource2 = { ...MOCK_RESOURCE_JSON, gatewayId: "gateway-b", name: "Resource B" };

    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([resource1, resource2]),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    // Check for individual resource cards (not grouped by gateway)
    await expect(page.getByText("Resource A")).toBeVisible();
    await expect(page.getByText("Resource B")).toBeVisible();
  });

  test("shows all resources as individual cards", async ({ page }) => {
    const resource1 = { ...MOCK_RESOURCE, id: "res-1", name: "Resource 1" };
    const resource2 = { ...MOCK_RESOURCE, id: "res-2", name: "Resource 2" };

    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([resource1, resource2]),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    // Check for individual resource cards
    await expect(page.getByText("Resource 1")).toBeVisible();
    await expect(page.getByText("Resource 2")).toBeVisible();

    // Should have 3 cards total (2 resources + 1 add card)
    const cards = page.locator('[data-slot="card"]');
    await expect(cards).toHaveCount(3);
  });

  test.describe("Delete resource", () => {
    test("cancel in confirm dialog keeps resource visible", async ({ page }) => {
      await page.route("**/resources?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([MOCK_RESOURCE]),
        });
      });

      await page.goto(APP.RESOURCES);
      await page.waitForLoadState("networkidle");

      await expect(page.getByText("Test Document", { exact: true })).toBeVisible();

      // Open card dropdown
      await page.getByLabel("More options for Test Document").click();
      await page.getByText("Delete").click();

      // Confirm dialog should appear
      await expect(page.getByText("Delete resource")).toBeVisible();
      await expect(page.getByText(/Are you sure you want to delete "Test Document"/)).toBeVisible();

      // Cancel
      await page.getByRole("button", { name: "Cancel" }).click();

      // Resource should still be visible
      await expect(page.getByText("Test Document", { exact: true })).toBeVisible();
    });

    test("confirming delete removes resource from grid", async ({ page }) => {
      await page.route("**/resources?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([MOCK_RESOURCE]),
        });
      });

      await page.route("**/resources/res-123abc456def789", async (route) => {
        await route.fulfill({ status: 204 });
      });

      await page.goto(APP.RESOURCES);
      await page.waitForLoadState("networkidle");

      await expect(page.getByText("Test Document", { exact: true })).toBeVisible();

      await page.getByLabel("More options for Test Document").click();
      await page.getByText("Delete").click();

      await expect(page.getByText("Delete resource")).toBeVisible();
      await page.getByRole("button", { name: /^delete$/i }).click();

      // Resource should disappear from grid
      await expect(page.getByText("Test Document", { exact: true })).not.toBeVisible();
    });

    test("resource disappears immediately before DELETE responds (optimistic)", async ({
      page,
    }) => {
      let resolveDelete!: () => void;

      await page.route("**/resources?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([MOCK_RESOURCE]),
        });
      });

      await page.route("**/resources/res-123abc456def789", async (route) => {
        await new Promise<void>((res) => {
          resolveDelete = res;
        });
        await route.fulfill({ status: 204 });
      });

      await page.goto(APP.RESOURCES);
      await page.waitForLoadState("networkidle");

      await expect(page.getByText("Test Document", { exact: true })).toBeVisible();

      await page.getByLabel("More options for Test Document").click();
      await page.getByText("Delete").click();
      await expect(page.getByText("Delete resource")).toBeVisible();
      await page.getByRole("button", { name: /^delete$/i }).click();

      // Should disappear immediately (optimistic), before API resolves
      await expect(page.getByText("Test Document", { exact: true })).not.toBeVisible();

      resolveDelete();
    });

    test("resource reappears when DELETE API returns error (rollback)", async ({ page }) => {
      await page.route("**/resources?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([MOCK_RESOURCE]),
        });
      });

      await page.route("**/resources/res-123abc456def789", async (route) => {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Cannot delete: resource in use" }),
        });
      });

      await page.goto(APP.RESOURCES);
      await page.waitForLoadState("networkidle");

      await expect(page.getByText("Test Document", { exact: true })).toBeVisible();

      await page.getByLabel("More options for Test Document").click();
      await page.getByText("Delete").click();
      await expect(page.getByText("Delete resource")).toBeVisible();
      await page.getByRole("button", { name: /^delete$/i }).click();

      // After rollback resource should reappear
      await expect(page.getByText("Test Document", { exact: true })).toBeVisible();
    });
  });
});
