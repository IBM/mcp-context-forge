import { test, expect } from "./fixtures/api-mock";
import { APP } from "./utils/paths";
import type { VirtualServer } from "../src/types/server";

const MOCK_VIRTUAL_SERVER: VirtualServer = {
  id: "76c7b637dafc4d7197f14817ddffeda9", // pragma: allowlist secret
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
  teamId: "0a9b06bd22974fe386dcacb18548ed61", // pragma: allowlist secret
  team: "Platform Administrator's Team",
  ownerEmail: "admin@example.com",
  visibility: "public",
  oauthEnabled: false,
  oauthConfig: null,
};

const MOCK_VIRTUAL_SERVER_DETAILS: VirtualServer = {
  ...MOCK_VIRTUAL_SERVER,
  description: "Virtual server endpoint: developer tooling server exposing repository workflows.",
  associatedTools: ["Get Repo Issues", "Create New Issue"],
  associatedToolIds: ["GITHUB_GET_REPO_ISSUES", "GITHUB_CREATE_ISSUE"],
  associatedResources: ["github://repo/{owner}/{repo}"],
  associatedPrompts: ["summarize_pull_request"],
  tags: [{ id: "tag-development", label: "development" }],
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

  test("navigates to create server UI when MCP server card is clicked", async ({ page }) => {
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

    // Should navigate to create server UI
    await expect(page).toHaveURL(/\/app\/gateways\/create-server/);
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

    // Check for create server card
    await expect(
      page.getByRole("button", { name: /Create server Make external sources/i }),
    ).toBeVisible();

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

    await expect(page.getByText("testVS")).toBeVisible();

    const card = page.getByTestId("virtual-server-card").filter({ hasText: "testVS" });
    await expect(card.getByTestId("enabled-indicator")).toBeVisible();

    await expect(card.getByTestId("tool-count")).toHaveText("2");
    await expect(card.getByTestId("resource-count")).toHaveText("1");
    await expect(card.getByTestId("prompt-count")).toHaveText("1");

    await expect(card.getByText("public")).toBeVisible();
    await expect(card.getByText("enabled")).toBeVisible();

    await expect(card.getByTestId("last-updated")).toBeVisible();
  });

  test("opens server actions dropdown menu and shows disabled placeholder items", async ({
    page,
  }) => {
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for testVS" }).click();

    const viewDetails = page.getByRole("menuitem", { name: "View details" });
    await expect(viewDetails).toBeVisible();
    await expect(viewDetails).not.toHaveAttribute("data-disabled", "");

    for (const label of ["Test connection", "Edit server", "Delete"]) {
      const item = page.getByRole("menuitem", { name: label });
      await expect(item).toBeVisible();
      await expect(item).toHaveAttribute("data-disabled", "");
    }
  });

  test("opens virtual server details drawer from row actions", async ({ page }) => {
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });
    await page.route(`**/servers/${MOCK_VIRTUAL_SERVER.id}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_VIRTUAL_SERVER_DETAILS),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for testVS" }).click();
    await page.getByRole("menuitem", { name: "View details" }).click();

    const drawer = page.getByRole("dialog", { name: "testVS details" });
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole("heading", { name: "Virtual server details" })).toBeVisible();
    await expect(
      drawer.getByText(
        "Virtual server endpoint: developer tooling server exposing repository workflows.",
      ),
    ).toBeVisible();
    await expect(drawer.getByText("Status")).toBeVisible();
    await expect(drawer.getByText("Active")).toBeVisible();
    await expect(drawer.getByText("Visibility")).toBeVisible();
    await expect(drawer.getByText("Public")).toBeVisible();
    await expect(drawer.getByText("development")).toBeVisible();
    await expect(drawer.getByText("Get Repo Issues")).toBeVisible();
    await expect(drawer.getByText("GITHUB_GET_REPO_ISSUES")).toBeVisible();
    await expect(drawer.getByText("github://repo/{owner}/{repo}").first()).toBeVisible();
    await expect(drawer.getByText("summarize_pull_request").first()).toBeVisible();

    const addSourcesButton = drawer.getByRole("button", { name: "Add sources" });
    await expect(addSourcesButton).toBeVisible();

    await drawer.getByRole("button", { name: "Tools" }).click();
    await expect(drawer.getByText("Create New Issue")).toBeVisible();
    await expect(drawer.getByText("github://repo/{owner}/{repo}")).toHaveCount(0);
    await expect(drawer.getByText("summarize_pull_request")).toHaveCount(0);
  });

  test("drawer add sources button navigates to the create server UI", async ({ page }) => {
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });
    await page.route(`**/servers/${MOCK_VIRTUAL_SERVER.id}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_VIRTUAL_SERVER_DETAILS),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for testVS" }).click();
    await page.getByRole("menuitem", { name: "View details" }).click();
    await page
      .getByRole("dialog", { name: "testVS details" })
      .getByRole("button", {
        name: "Add sources",
      })
      .click();

    await expect(page).toHaveURL(/\/app\/gateways\/create-server/);
  });

  test("disables the Upload action button on virtual server cards", async ({ page }) => {
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("button", { name: /Open testVS \(coming soon\)/ })).toBeDisabled();
  });

  test("navigates to create server UI from the create server card", async ({ page }) => {
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("button", { name: "Virtual server actions" })).toHaveCount(0);
    await page.getByRole("button", { name: /Create server Make external sources/i }).click();

    await expect(page).toHaveURL(/\/app\/gateways\/create-server/);
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

    const card = page.getByTestId("virtual-server-card").filter({ hasText: "testVS" });

    await expect(card.getByTestId("enabled-indicator")).toHaveCount(0);

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

    await expect(page.getByText("testVS")).toBeVisible();
    await expect(page.getByText("Production Server")).toBeVisible();

    const card1 = page.getByTestId("virtual-server-card").filter({ hasText: "testVS" });
    const card2 = page.getByTestId("virtual-server-card").filter({ hasText: "Production Server" });

    await expect(card1.getByText("public")).toBeVisible();
    await expect(card2.getByText("private")).toBeVisible();
  });

  test("places empty virtual servers after servers with components", async ({ page }) => {
    const emptyServer = {
      ...MOCK_VIRTUAL_SERVER,
      id: "empty-server-id",
      name: "peach-thistle-shark",
      enabled: false,
      associatedTools: [],
      associatedToolIds: [],
      associatedResources: [],
      associatedPrompts: [],
      tags: [],
    };

    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [emptyServer, MOCK_VIRTUAL_SERVER] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    const cards = page.getByTestId("virtual-server-card");
    await expect(cards).toHaveCount(2);
    await expect(cards.nth(0)).toHaveAttribute("data-server-name", "testVS");
    await expect(cards.nth(1)).toHaveAttribute("data-server-name", "peach-thistle-shark");
    await expect(cards.nth(1)).toHaveClass(/col-span-full/);
    await expect(
      cards.nth(1).getByRole("button", { name: "Add sources and components" }),
    ).toBeVisible();
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

    // Focus the create server card
    const connectCard = page.getByRole("button", {
      name: /Create server Make external sources/i,
    });
    await connectCard.focus();

    // Press Enter
    await page.keyboard.press("Enter");

    // Should navigate to the create server UI
    await expect(page).toHaveURL(/\/app\/gateways\/create-server/);
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

    const card = page.getByTestId("virtual-server-card").filter({ hasText: "testVS" });
    await expect(card.getByTestId("last-updated")).toBeVisible();
    await expect(card.getByTestId("last-updated")).not.toHaveText("");
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

    const card = page.getByTestId("virtual-server-card").filter({ hasText: "testVS" });

    await expect(card).toHaveClass(/col-span-full/);
    await expect(card.getByRole("button", { name: "Add sources and components" })).toBeVisible();
    await expect(card.getByTestId("tool-count")).toHaveCount(0);
    await expect(card.getByTestId("resource-count")).toHaveCount(0);
    await expect(card.getByTestId("prompt-count")).toHaveCount(0);
  });

  test("disables not-yet-implemented source types in the empty-state selector", async ({
    page,
  }) => {
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    const restCard = page.getByTestId("action-card-REST API");
    const grpcCard = page.getByTestId("action-card-gRPC");

    await expect(restCard).toHaveAttribute("aria-disabled", "true");
    await expect(grpcCard).toHaveAttribute("aria-disabled", "true");

    await expect(restCard.getByRole("button", { name: /\+ Connect/ })).toBeDisabled();
    await expect(grpcCard.getByRole("button", { name: /\+ Connect/ })).toBeDisabled();
  });
});
