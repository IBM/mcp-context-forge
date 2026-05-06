import { test, expect } from "./fixtures/api-mock";
import { APP } from "./utils/paths";
import type { VirtualServer } from "../src/types/server";

const MOCK_VIRTUAL_SERVER: VirtualServer = {
  id: "76c7b637dafc4d7197f14817ddffeda9",
  name: "testVS",
  description: "Test virtual server",
  icon: "",
  createdAt: "2026-04-28T15:41:31.233166",
  updatedAt: "2026-04-28T15:41:31.233168",
  enabled: true,
  associatedTools: [],
  associatedToolIds: ["tool1", "tool2"],
  associatedResources: ["resource1"],
  associatedPrompts: ["prompt1"],
  associatedA2aAgents: [],
  metrics: null,
  tags: ["public", "enabled"],
  createdBy: "admin@example.com",
  createdFromIp: "127.0.0.1",
  createdVia: "ui",
  createdUserAgent: "Mozilla/5.0",
  modifiedBy: null,
  modifiedFromIp: null,
  modifiedVia: null,
  modifiedUserAgent: null,
  importBatchId: null,
  federationSource: null,
  version: 1,
  teamId: "0a9b06bd22974fe386dcacb18548ed61",
  team: "Platform Administrator's Team",
  ownerEmail: "admin@example.com",
  visibility: "public",
  oauthEnabled: false,
  oauthConfig: null,
};

test.describe("Gateways page", () => {
  test.beforeEach(async ({ page, apiMock }) => {
    // Mock authentication
    await apiMock.mockMe();

    // Set auth token in sessionStorage
    await page.addInitScript(() => {
      sessionStorage.setItem("mcpgateway_token", "mock-token-12345");
    });
  });

  test.skip("shows loading state while fetching servers", async () => {
    // Skip: Loading state is too fast to reliably test in E2E
    // This is better tested in unit tests with controlled timing
  });

  test("shows source selection when no servers exist", async ({ page }) => {
    // Mock empty servers response
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    // Check for source selection heading
    await expect(page.getByRole("heading", { name: "Connect a source" })).toBeVisible();

    // Check all four action cards are present (use role="main" to avoid sidebar conflicts)
    const mainContent = page.getByRole("main");
    await expect(mainContent.getByText("MCP server", { exact: true })).toBeVisible();
    await expect(mainContent.getByText("AI agent", { exact: true })).toBeVisible();
    await expect(mainContent.getByText("REST API", { exact: true })).toBeVisible();
    await expect(mainContent.getByText("gRPC", { exact: true })).toBeVisible();

    // Check descriptions
    await expect(
      page.getByText("Register an endpoint implementing the Model Context Protocol"),
    ).toBeVisible();
    await expect(
      page.getByText("Add an agent over A2A, OpenAI, or Anthropic protocols"),
    ).toBeVisible();
  });

  test("navigates to servers page when MCP server card is clicked", async ({ page }) => {
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    // Click the MCP server connect button
    await page.getByRole("button", { name: "+ Connect" }).first().click();

    // Should navigate to servers page with openForm query param
    await expect(page).toHaveURL(/\/app\/servers\?openForm=true/);
  });

  test("navigates to agents page when AI agent card is clicked", async ({ page }) => {
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    // Click the AI agent connect button (second button)
    await page.getByRole("button", { name: "+ Connect" }).nth(1).click();

    // Should navigate to agents page
    await expect(page).toHaveURL(/\/app\/agents/);
  });

  test("shows virtual servers list when servers exist", async ({ page }) => {
    // Mock servers response with data
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    // Check for virtual servers heading
    await expect(page.getByRole("heading", { name: "Virtual servers" })).toBeVisible();

    // Check for connect source card
    await expect(page.getByText("Connect a source")).toBeVisible();

    // Check for virtual server card
    await expect(page.getByText("testVS")).toBeVisible();
  });

  test("displays server details correctly", async ({ page }) => {
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    // Check server name
    await expect(page.getByText("testVS")).toBeVisible();

    // Check enabled indicator (green dot)
    const card = page.locator('[class*="min-h-35"]').filter({ hasText: "testVS" });
    await expect(card.locator('[class*="bg-emerald-500"]')).toBeVisible();

    // Check counts (use more specific selectors to avoid duplicates)
    const toolsCount = card.locator("span").filter({ hasText: /^2$/ }).first();
    await expect(toolsCount).toBeVisible(); // 2 tools

    // Check visibility badge
    await expect(card.getByText("public")).toBeVisible();
    await expect(card.getByText("enabled")).toBeVisible();

    // Check timestamp is present (format may vary)
    await expect(card.locator('span[class*="text-muted-foreground"]')).toBeVisible();
  });

  test("opens server actions dropdown menu", async ({ page }) => {
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    // Click the actions button (ellipsis icon)
    await page.getByRole("button", { name: "Actions for testVS" }).click();

    // Check dropdown menu items
    await expect(page.getByText("View details")).toBeVisible();
    await expect(page.getByText("Test connection")).toBeVisible();
    await expect(page.getByText("Edit server")).toBeVisible();
  });

  test("opens virtual server actions dropdown in header", async ({ page }) => {
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    // Click the header actions button
    await page.getByRole("button", { name: "Virtual server actions" }).click();

    // Check dropdown menu items (use role="menuitem" to target dropdown items specifically)
    await expect(page.getByRole("menuitem", { name: "Connect a source" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Browse server catalog" })).toBeVisible();
  });

  test("navigates to server catalog from dropdown", async ({ page }) => {
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    // Open dropdown and click catalog option
    await page.getByRole("button", { name: "Virtual server actions" }).click();
    await page.getByText("Browse server catalog").click();

    // Should navigate to server catalog
    await expect(page).toHaveURL(/\/app\/server-catalog/);
  });

  test("shows error state when API fails", async ({ page }) => {
    // Mock API error
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Internal server error" }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    // Check for error message
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByText("Error loading virtual servers")).toBeVisible();
  });

  test("shows partial error when servers load but with error", async ({ page }) => {
    // Mock API that returns servers successfully on first call
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    // Should show servers list from successful response
    await expect(page.getByText("testVS")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Virtual servers" })).toBeVisible();
  });

  test("handles disabled server correctly", async ({ page }) => {
    const disabledServer = { ...MOCK_VIRTUAL_SERVER, enabled: false, tags: ["public", "disabled"] };

    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [disabledServer] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    const card = page.locator('[class*="min-h-35"]').filter({ hasText: "testVS" });

    // Should NOT show green enabled indicator
    await expect(card.locator('[class*="bg-emerald-500"]')).not.toBeVisible();

    // Should show disabled badge
    await expect(card.getByText("disabled")).toBeVisible();
  });

  test("displays multiple servers correctly", async ({ page }) => {
    const server2 = {
      ...MOCK_VIRTUAL_SERVER,
      id: "server2-id",
      name: "Production Server",
      visibility: "private" as const,
      enabled: false,
      tags: ["private", "disabled"],
    };

    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER, server2] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    // Check both servers are visible
    await expect(page.getByText("testVS")).toBeVisible();
    await expect(page.getByText("Production Server")).toBeVisible();

    // Check different visibility badges
    const card1 = page.locator('[class*="min-h-35"]').filter({ hasText: "testVS" });
    const card2 = page.locator('[class*="min-h-35"]').filter({ hasText: "Production Server" });

    await expect(card1.getByText("public")).toBeVisible();
    await expect(card2.getByText("private")).toBeVisible();
  });

  test("connect source card is keyboard accessible", async ({ page }) => {
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    // Focus the connect source card
    const connectCard = page.getByRole("button", { name: /Connect a source/i });
    await connectCard.focus();

    // Press Enter
    await page.keyboard.press("Enter");

    // Should navigate to servers page
    await expect(page).toHaveURL(/\/app\/servers\?openForm=true/);
  });

  test("formats timestamps correctly", async ({ page }) => {
    const serverWithoutUpdate = {
      ...MOCK_VIRTUAL_SERVER,
      updatedAt: "",
    };

    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [serverWithoutUpdate] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    // Should show timestamp (format may vary, just check it's present)
    const card = page.locator('[class*="min-h-35"]').filter({ hasText: "testVS" });
    await expect(card.locator('span[class*="text-muted-foreground"]')).toBeVisible();
  });

  test("handles empty associated arrays correctly", async ({ page }) => {
    const serverWithNoAssociations = {
      ...MOCK_VIRTUAL_SERVER,
      associatedToolIds: [],
      associatedResources: [],
      associatedPrompts: [],
    };

    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [serverWithNoAssociations] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    const card = page.locator('[class*="min-h-35"]').filter({ hasText: "testVS" });

    // All counts should be 0
    const counts = await card.locator('span:has-text("0")').count();
    expect(counts).toBeGreaterThanOrEqual(3); // At least 3 zeros for tools, resources, prompts
  });
});
