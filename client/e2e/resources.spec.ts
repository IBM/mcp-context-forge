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
        body: JSON.stringify({ data: [] }),
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

  test("shows resource group cards when resources exist", async ({ page }) => {
    // Mock resources response with data
    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [MOCK_RESOURCE],
        }),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    // Check for resources heading
    await expect(page.getByRole("heading", { name: "Resources" })).toBeVisible();

    // Check for "Add resources" card
    await expect(page.getByText("Add resources")).toBeVisible();

    // Check for resource group card - gateway slug and count
    await expect(page.getByText("test-gateway")).toBeVisible();
    await expect(page.getByText("1 resource")).toBeVisible();
  });

  test("displays resource group card with badges", async ({ page }) => {
    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [MOCK_RESOURCE],
        }),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    // Check for gateway slug
    await expect(page.getByText("test-gateway")).toBeVisible();

    // Check for resource name badge
    await expect(page.getByText("Test Document")).toBeVisible();
  });

  test("clicking add resources card opens form", async ({ page }) => {
    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [],
        }),
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

  test.skip("opens resource group details panel", async ({ page }) => {
    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [MOCK_RESOURCE],
        }),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    // Click the three-dot menu on the resource group card
    await page.getByRole("button", { name: /More options for test-gateway/i }).click();

    // Click "View Details"
    await page.getByRole("menuitem", { name: "View Details" }).click();

    // Check details panel is visible
    await expect(page.getByText("test-gateway")).toBeVisible();
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
          body: JSON.stringify({
            data: resources,
          }),
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

    // Verify new resource group appears
    await expect(page.getByText("api-gateway")).toBeVisible();
  });

  test.skip("validates required fields in create form", async ({ page }) => {
    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [MOCK_RESOURCE],
        }),
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
        body: JSON.stringify({
          data: isDeleted ? [] : [MOCK_RESOURCE],
        }),
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

    await expect(page.getByText("test-gateway")).toBeVisible();

    // Open details panel
    await page.getByRole("button", { name: /More options for test-gateway/i }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();

    // Delete from panel
    await page.getByRole("button", { name: "Delete" }).click();

    const dialog = page.getByRole("dialog", { name: "Delete resource" });
    await expect(dialog).toBeVisible();

    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect.poll(() => deleteRequestCount).toBe(1);
    await expect.poll(() => listRequestCount).toBeGreaterThan(1);
    await expect(page.getByText("test-gateway")).toHaveCount(0);
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

  test("displays multiple resource groups correctly", async ({ page }) => {
    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [MOCK_RESOURCE, MOCK_RESOURCE_JSON],
        }),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    // Check for both gateway groups
    await expect(page.getByText("test-gateway")).toBeVisible();
    await expect(page.getByText("api-gateway")).toBeVisible();

    // Check resource counts - should have two "1 resource" texts
    const resourceCountTexts = page.getByText("1 resource");
    await expect(resourceCountTexts).toHaveCount(2);
  });

  test("groups resources by gateway automatically", async ({ page }) => {
    const resource1 = { ...MOCK_RESOURCE, gatewaySlug: "gateway-a" };
    const resource2 = { ...MOCK_RESOURCE_JSON, gatewaySlug: "gateway-b" };

    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [resource1, resource2],
        }),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    // Check for gateway group cards
    await expect(page.getByText("gateway-a")).toBeVisible();
    await expect(page.getByText("gateway-b")).toBeVisible();
  });

  test("shows resource count in group card", async ({ page }) => {
    const resource1 = { ...MOCK_RESOURCE, id: "res-1", name: "Resource 1" };
    const resource2 = { ...MOCK_RESOURCE, id: "res-2", name: "Resource 2" };

    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: [resource1, resource2],
        }),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    // Check for resource count
    await expect(page.getByText("2 resources")).toBeVisible();
  });
});
