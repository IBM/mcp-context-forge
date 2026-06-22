import { test, expect } from "./fixtures/api-mock";
import { APP } from "./utils/paths";
import type { Resource } from "../src/types/resource";

const MOCK_RESOURCE: Resource = {
  id: "res-123abc456def789", // pragma: allowlist secret
  uri: "resource://test/document.txt",
  name: "Test Document",
  description: "A test resource for E2E testing",
  mimeType: "text/plain",
  size: 1024,
  tags: ["test", "document"],
  enabled: true,
  content: null,
  createdAt: "2026-04-28T15:41:31.233166",
  updatedAt: "2026-04-28T15:41:31.233168",
  createdBy: "admin@example.com",
  teamId: "0a9b06bd22974fe386dcacb18548ed61", // pragma: allowlist secret
  team: "Platform Administrator's Team",
  ownerEmail: "admin@example.com",
  visibility: "public",
  gatewaySlug: "test-gateway",
  gatewayId: "gw-123",
};

const MOCK_RESOURCE_JSON: Resource = {
  id: "res-json-789xyz", // pragma: allowlist secret
  uri: "resource://api/config.json",
  name: "API Configuration",
  description: "JSON configuration for API endpoints",
  mimeType: "application/json",
  size: 2048,
  tags: ["config", "api"],
  enabled: true,
  content: null,
  createdAt: "2026-04-28T16:00:00.000000",
  updatedAt: "2026-04-28T16:00:00.000000",
  createdBy: "admin@example.com",
  teamId: "0a9b06bd22974fe386dcacb18548ed61", // pragma: allowlist secret
  team: "Platform Administrator's Team",
  ownerEmail: "admin@example.com",
  visibility: "team",
  gatewaySlug: "api-gateway",
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

  test.skip("shows loading state while fetching resources", async () => {
    // Skip: Loading state is too fast to reliably test in E2E
    // This is better tested in unit tests with controlled timing
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

  test.skip("opens resource details panel", async ({ page }) => {
    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([MOCK_RESOURCE]),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    // Click the three-dot menu on the resource card
    await page.getByRole("button", { name: /More options for Test Document/i }).click();

    // Click "View Details"
    await page.getByRole("menuitem", { name: "View Details" }).click();

    // Check details panel is visible
    await expect(page.getByText("Test Document Details")).toBeVisible();
  });

  test.skip("creates a new resource", async ({ page }) => {
    let createRequestCount = 0;
    let listRequestCount = 0;

    await page.route("**/resources?*", async (route) => {
      if (route.request().method() === "GET") {
        listRequestCount += 1;
        const resources =
          createRequestCount > 0 ? [MOCK_RESOURCE, MOCK_RESOURCE_JSON] : [MOCK_RESOURCE];
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(resources),
        });
      }
    });

    await page.route("**/resources", async (route) => {
      if (route.request().method() === "POST") {
        createRequestCount += 1;
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify(MOCK_RESOURCE_JSON),
        });
      }
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    // Click "Add resources" card
    await page.getByText("Add resources").click();

    // Fill form
    await page.getByLabel("URI").fill("resource://api/config.json");
    await page.getByLabel("Name").fill("API Configuration");
    await page.getByLabel("MIME Type").fill("application/json");
    await page.getByLabel("Description").fill("JSON configuration for API endpoints");

    // Submit form
    await page.getByRole("button", { name: "Create" }).click();

    // Verify request was made
    await expect.poll(() => createRequestCount).toBe(1);
    await expect.poll(() => listRequestCount).toBeGreaterThan(1);

    // Verify new resource card appears
    await expect(page.getByText("API Configuration")).toBeVisible();
  });

  test.skip("validates required fields in create form", async ({ page }) => {
    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([MOCK_RESOURCE]),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    await page.getByText("Add resources").click();

    // Try to submit without filling required fields
    await page.getByRole("button", { name: "Create" }).click();

    // Form should show validation errors
    await expect(page.getByText("URI is required")).toBeVisible();
    await expect(page.getByText("Name is required")).toBeVisible();
  });

  test.skip("confirms and deletes a resource from details panel", async ({ page }) => {
    let isDeleted = false;
    let listRequestCount = 0;
    let deleteRequestCount = 0;

    await page.route("**/resources?*", async (route) => {
      listRequestCount += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(isDeleted ? [] : [MOCK_RESOURCE]),
      });
    });

    await page.route(`**/resources/${MOCK_RESOURCE.id}`, async (route) => {
      if (route.request().method() === "DELETE") {
        deleteRequestCount += 1;
        isDeleted = true;
        await route.fulfill({ status: 204 });
      }
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Test Document")).toBeVisible();

    // Open details panel
    await page.getByRole("button", { name: /More options for Test Document/i }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();

    // Delete from panel
    await page.getByRole("button", { name: "Delete" }).click();

    const dialog = page.getByRole("dialog", { name: "Delete resource" });
    await expect(dialog).toBeVisible();

    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect.poll(() => deleteRequestCount).toBe(1);
    await expect.poll(() => listRequestCount).toBeGreaterThan(1);
    await expect(page.getByText("Test Document")).toHaveCount(0);
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
    const resource1 = { ...MOCK_RESOURCE, gatewaySlug: "gateway-a", name: "Resource A" };
    const resource2 = { ...MOCK_RESOURCE_JSON, gatewaySlug: "gateway-b", name: "Resource B" };

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
});
