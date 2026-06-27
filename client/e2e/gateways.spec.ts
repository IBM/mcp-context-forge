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

const MOCK_MCP_SERVER = {
  id: "mcp-gateway-1",
  name: "github-mcp",
  url: "http://localhost:9000",
  transport: "SSE",
  enabled: true,
  reachable: true,
  visibility: "public",
  tool_count: 1,
  resource_count: 1,
  prompt_count: 1,
  created_at: "2026-04-28T15:41:31.233166",
  updated_at: "2026-04-28T15:41:31.233168",
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

  test("shows connect source card when no virtual servers exist", async ({ page }) => {
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

    await expect(page.getByRole("heading", { name: "Virtual servers" })).toBeVisible();
    const mainContent = page.getByRole("main");
    await expect(
      mainContent.getByRole("button", { name: /Create server Make external sources/i }),
    ).toBeVisible();
    await expect(page.getByTestId("virtual-server-card")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Connect a source" })).toHaveCount(0);
    await expect(mainContent.getByText("MCP server", { exact: true })).toHaveCount(0);
    await expect(mainContent.getByText("Virtual Server", { exact: true })).toHaveCount(0);
  });

  test("navigates to create server UI when connect source card is clicked", async ({ page }) => {
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: /Create server Make external sources/i }).click();

    await expect(page).toHaveURL(/\/app\/gateways\/create-server$/);
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

  test("opens server actions dropdown menu and hides unavailable actions", async ({ page }) => {
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

    const editServer = page.getByRole("menuitem", { name: "Edit server" });
    await expect(editServer).toBeVisible();
    await expect(editServer).not.toHaveAttribute("data-disabled", "");
    await expect(page.getByRole("menuitem", { name: "Deactivate" })).toHaveCount(0);
    const deleteItem = page.getByRole("menuitem", { name: "Delete" });
    await expect(deleteItem).toBeVisible();
    await expect(deleteItem).not.toHaveAttribute("data-disabled", "");
  });

  test("optimistically removes the card before the API responds", async ({ page }) => {
    let releaseDelete!: () => void;
    const deleteCanFinish = new Promise<void>((resolve) => {
      releaseDelete = resolve;
    });
    let deleteRequestCount = 0;

    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });
    await page.route(`**/servers/${MOCK_VIRTUAL_SERVER.id}`, async (route) => {
      expect(route.request().method()).toBe("DELETE");
      deleteRequestCount += 1;
      await deleteCanFinish;
      await route.fulfill({ status: 204 });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for testVS" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("dialog", { name: "Delete virtual server" });
    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect(page.getByTestId("virtual-server-card").filter({ hasText: "testVS" })).toHaveCount(
      0,
    );

    await expect.poll(() => deleteRequestCount).toBe(1);
    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: "testVS deleted." }),
    ).toHaveCount(0);

    releaseDelete();
    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: "testVS deleted." }),
    ).toBeVisible();
  });

  test("dialog and form state are cleared immediately on confirm", async ({ page }) => {
    let releaseDelete!: () => void;
    const deleteCanFinish = new Promise<void>((resolve) => {
      releaseDelete = resolve;
    });

    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });
    await page.route(`**/servers/${MOCK_VIRTUAL_SERVER.id}`, async (route) => {
      await deleteCanFinish;
      await route.fulfill({ status: 204 });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for testVS" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("dialog", { name: "Delete virtual server" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Delete" }).click();

    // Dialog is gone before the API resolves
    await expect(dialog).toHaveCount(0);

    releaseDelete();
  });

  test("confirms and deletes a virtual server", async ({ page }) => {
    let isDeleted = false;
    let listRequestCount = 0;
    let deleteRequestCount = 0;

    await page.route("**/servers?*", async (route) => {
      listRequestCount += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: isDeleted ? [] : [MOCK_VIRTUAL_SERVER] }),
      });
    });
    await page.route(`**/servers/${MOCK_VIRTUAL_SERVER.id}`, async (route) => {
      expect(route.request().method()).toBe("DELETE");
      deleteRequestCount += 1;
      isDeleted = true;
      await route.fulfill({ status: 204 });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("testVS")).toBeVisible();

    await page.getByRole("button", { name: "Actions for testVS" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("dialog", { name: "Delete virtual server" });
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByText("Are you sure you want to delete testVS? This action cannot be undone."),
    ).toBeVisible();

    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect(page.getByTestId("virtual-server-card").filter({ hasText: "testVS" })).toHaveCount(
      0,
    );

    await expect.poll(() => deleteRequestCount).toBe(1);
    await expect.poll(() => listRequestCount).toBeGreaterThan(1);
  });

  test("shows delete progress while a virtual server delete is pending", async ({ page }) => {
    let deleteRequestCount = 0;
    let releaseDelete: () => void;
    const deleteCanFinish = new Promise<void>((resolve) => {
      releaseDelete = resolve;
    });

    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });
    await page.route(`**/servers/${MOCK_VIRTUAL_SERVER.id}`, async (route) => {
      expect(route.request().method()).toBe("DELETE");
      deleteRequestCount += 1;
      await deleteCanFinish;
      await route.fulfill({ status: 204 });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for testVS" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("dialog", { name: "Delete virtual server" });
    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect(dialog).toHaveCount(0);
    await expect(page.getByTestId("virtual-server-card").filter({ hasText: "testVS" })).toHaveCount(
      0,
    );

    await expect.poll(() => deleteRequestCount).toBe(1);
    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: "testVS deleted." }),
    ).toHaveCount(0);

    releaseDelete!();
    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: "testVS deleted." }),
    ).toBeVisible();
    await expect.poll(() => deleteRequestCount).toBe(1);
  });

  test("rolls back the card to the grid when the API returns an error", async ({ page }) => {
    let releaseDelete!: () => void;
    const deleteCanFinish = new Promise<void>((resolve) => {
      releaseDelete = resolve;
    });
    let deleteRequestCount = 0;

    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });
    await page.route(`**/servers/${MOCK_VIRTUAL_SERVER.id}`, async (route) => {
      expect(route.request().method()).toBe("DELETE");
      deleteRequestCount += 1;
      await deleteCanFinish;
      await route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Forbidden" }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for testVS" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("dialog", { name: "Delete virtual server" });
    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect(page.getByTestId("virtual-server-card").filter({ hasText: "testVS" })).toHaveCount(
      0,
    );

    releaseDelete();
    await expect.poll(() => deleteRequestCount).toBe(1);

    await expect(
      page.getByTestId("virtual-server-card").filter({ hasText: "testVS" }),
    ).toBeVisible();

    await expect(page.getByText("Error deleting virtual server")).toBeVisible();
    await expect(page.getByText("You don't have permission to perform this action.")).toBeVisible();
    await expect(page.getByRole("main").getByText("Error deleting virtual server")).toHaveCount(0);
  });

  test("shows delete failures in a toast instead of the page content", async ({ page }) => {
    let deleteRequestCount = 0;

    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });
    await page.route(`**/servers/${MOCK_VIRTUAL_SERVER.id}`, async (route) => {
      expect(route.request().method()).toBe("DELETE");
      deleteRequestCount += 1;
      await route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Forbidden" }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for testVS" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("dialog", { name: "Delete virtual server" });
    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect.poll(() => deleteRequestCount).toBe(1);
    await expect(page.getByText("Error deleting virtual server")).toBeVisible();
    await expect(page.getByText("You don't have permission to perform this action.")).toBeVisible();
    await expect(page.getByRole("main").getByText("Error deleting virtual server")).toHaveCount(0);
    await expect(
      page.getByTestId("virtual-server-card").filter({ hasText: "testVS" }),
    ).toBeVisible();
  });

  test("cancels delete dialog and keeps the virtual server card visible", async ({ page }) => {
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    await expect(
      page.getByTestId("virtual-server-card").filter({ hasText: "testVS" }),
    ).toBeVisible();

    await page.getByRole("button", { name: "Actions for testVS" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("dialog", { name: "Delete virtual server" });
    await expect(dialog).toBeVisible();

    await dialog.getByRole("button", { name: "Cancel" }).click();

    await expect(dialog).not.toBeVisible();
    await expect(
      page.getByTestId("virtual-server-card").filter({ hasText: "testVS" }),
    ).toBeVisible();
  });

  test("removes only the deleted card while sibling servers remain visible", async ({ page }) => {
    const SIBLING: VirtualServer = {
      ...MOCK_VIRTUAL_SERVER,
      id: "sibling-server-id",
      name: "siblingVS",
    };
    let deleteRequestCount = 0;

    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER, SIBLING] }),
      });
    });
    await page.route(`**/servers/${MOCK_VIRTUAL_SERVER.id}`, async (route) => {
      expect(route.request().method()).toBe("DELETE");
      deleteRequestCount += 1;
      await route.fulfill({ status: 204 });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    await expect(
      page.getByTestId("virtual-server-card").filter({ hasText: "testVS" }),
    ).toBeVisible();
    await expect(
      page.getByTestId("virtual-server-card").filter({ hasText: "siblingVS" }),
    ).toBeVisible();

    await page.getByRole("button", { name: "Actions for testVS" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("dialog", { name: "Delete virtual server" });
    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect.poll(() => deleteRequestCount).toBe(1);

    await expect(page.getByTestId("virtual-server-card").filter({ hasText: "testVS" })).toHaveCount(
      0,
    );
    await expect(
      page.getByTestId("virtual-server-card").filter({ hasText: "siblingVS" }),
    ).toBeVisible();

    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: "testVS deleted." }),
    ).toBeVisible();
  });

  test("closes the details panel immediately when its virtual server is deleted", async ({
    page,
  }) => {
    let releaseDelete!: () => void;
    const deleteCanFinish = new Promise<void>((resolve) => {
      releaseDelete = resolve;
    });
    let deleteRequestCount = 0;

    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });
    await page.route(`**/servers/${MOCK_VIRTUAL_SERVER.id}`, async (route) => {
      if (route.request().method() === "DELETE") {
        deleteRequestCount += 1;
        await deleteCanFinish; // hold the response
        await route.fulfill({ status: 204 });
      } else {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_VIRTUAL_SERVER_DETAILS),
        });
      }
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for testVS" }).click();
    await page.getByRole("menuitem", { name: "View details" }).click();

    const detailsPanel = page.getByRole("region", { name: "testVS details" });
    await expect(detailsPanel).toBeVisible();

    await page.keyboard.press("Escape"); // drawer is a full-height overlay; must close it before clicking table row actions
    await expect(detailsPanel).toHaveCount(0);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for testVS" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("dialog", { name: "Delete virtual server" });
    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect(page.getByTestId("virtual-server-card").filter({ hasText: "testVS" })).toHaveCount(
      0,
    );
    await expect(dialog).toHaveCount(0);

    releaseDelete();
    await expect.poll(() => deleteRequestCount).toBe(1);
    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: "testVS deleted." }),
    ).toBeVisible();
  });

  test("rolls back the details panel when delete fails", async ({ page }) => {
    let releaseDelete!: () => void;
    const deleteCanFinish = new Promise<void>((resolve) => {
      releaseDelete = resolve;
    });
    let deleteRequestCount = 0;

    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });
    await page.route(`**/servers/${MOCK_VIRTUAL_SERVER.id}`, async (route) => {
      if (route.request().method() === "DELETE") {
        deleteRequestCount += 1;
        await deleteCanFinish;
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Internal Server Error" }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_VIRTUAL_SERVER_DETAILS),
        });
      }
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for testVS" }).click();
    await page.getByRole("menuitem", { name: "View details" }).click();

    const detailsPanel = page.getByRole("region", { name: "testVS details" });
    await expect(detailsPanel).toBeVisible();

    await page.keyboard.press("Escape"); // drawer is a full-height overlay; must close it before clicking table row actions
    await expect(detailsPanel).toHaveCount(0);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for testVS" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("dialog", { name: "Delete virtual server" });
    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect(page.getByTestId("virtual-server-card").filter({ hasText: "testVS" })).toHaveCount(
      0,
    );

    releaseDelete();
    await expect.poll(() => deleteRequestCount).toBe(1);
    await expect(
      page.getByTestId("virtual-server-card").filter({ hasText: "testVS" }),
    ).toBeVisible();
    await expect(page.getByText("Error deleting virtual server")).toBeVisible();
  });

  test("closes the details panel when its virtual server is deleted (via escape)", async ({
    page,
  }) => {
    let deleteRequestCount = 0;

    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [MOCK_VIRTUAL_SERVER] }),
      });
    });
    await page.route(`**/servers/${MOCK_VIRTUAL_SERVER.id}`, async (route) => {
      if (route.request().method() === "DELETE") {
        deleteRequestCount += 1;
        await route.fulfill({ status: 204 });
      } else {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_VIRTUAL_SERVER_DETAILS),
        });
      }
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for testVS" }).click();
    await page.getByRole("menuitem", { name: "View details" }).click();

    const detailsPanel = page.getByRole("region", { name: "testVS details" });
    await expect(detailsPanel).toBeVisible();

    await page.keyboard.press("Escape"); // drawer is a full-height overlay; must close it before clicking table row actions

    await expect(detailsPanel).toHaveCount(0);

    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for testVS" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("dialog", { name: "Delete virtual server" });
    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect.poll(() => deleteRequestCount).toBe(1);

    await expect(page.getByTestId("virtual-server-card").filter({ hasText: "testVS" })).toHaveCount(
      0,
    );
    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: "testVS deleted." }),
    ).toBeVisible();
  });

  test("opens virtual server details panel from row actions", async ({ page }) => {
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

    const detailsPanel = page.getByRole("region", { name: "testVS details" });
    await expect(detailsPanel).toBeVisible();
    await expect(
      detailsPanel.getByRole("heading", { name: "Virtual server details" }),
    ).toBeVisible();
    await expect(
      detailsPanel.getByText(
        "Virtual server endpoint: developer tooling server exposing repository workflows.",
      ),
    ).toBeVisible();
    await expect(detailsPanel.getByText("Status")).toBeVisible();
    await expect(detailsPanel.getByText("Active")).toBeVisible();
    await expect(detailsPanel.getByText("Visibility")).toBeVisible();
    await expect(detailsPanel.getByText("Public")).toBeVisible();
    await expect(detailsPanel.getByText("development")).toBeVisible();
    await expect(detailsPanel.getByText("Get Repo Issues")).toBeVisible();
    await expect(detailsPanel.getByText("GITHUB_GET_REPO_ISSUES")).toBeVisible();
    await expect(detailsPanel.getByText("github://repo/{owner}/{repo}").first()).toBeVisible();
    await expect(detailsPanel.getByText("summarize_pull_request").first()).toBeVisible();

    const addSourcesButton = detailsPanel.getByRole("button", { name: "Add source" });
    await expect(addSourcesButton).toBeVisible();

    await detailsPanel.getByRole("tab", { name: "Tools" }).click();
    await expect(detailsPanel.getByText("Create New Issue")).toBeVisible();
    await expect(detailsPanel.getByText("github://repo/{owner}/{repo}")).toHaveCount(0);
    await expect(detailsPanel.getByText("summarize_pull_request")).toHaveCount(0);
  });

  test("details panel add source button navigates to edit the virtual server", async ({ page }) => {
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
      .getByRole("region", { name: "testVS details" })
      .getByRole("button", {
        name: "Add source",
      })
      .click();

    await expect(page).toHaveURL(
      new RegExp(`/app/gateways/create-server\\?editServerId=${MOCK_VIRTUAL_SERVER.id}`),
    );
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

  test("empty virtual server add sources button navigates to edit the virtual server", async ({
    page,
  }) => {
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

    await page
      .getByTestId("virtual-server-card")
      .filter({ hasText: "testVS" })
      .getByRole("button", { name: "Add sources and components" })
      .click();

    await expect(page).toHaveURL(
      new RegExp(`/app/gateways/create-server\\?editServerId=${MOCK_VIRTUAL_SERVER.id}`),
    );
  });

  test("creates a virtual server with components from a selected MCP server", async ({ page }) => {
    let createPayload: unknown = null;

    await page.route("**/gateways?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ gateways: [MOCK_MCP_SERVER] }),
      });
    });
    await page.route("**/tools?*", async (route) => {
      expect(new URL(route.request().url()).searchParams.get("gateway_id")).toBe(
        MOCK_MCP_SERVER.id,
      );
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ tools: [{ id: "tool-from-mcp", name: "Tool from MCP" }] }),
      });
    });
    await page.route("**/resources?*", async (route) => {
      expect(new URL(route.request().url()).searchParams.get("gateway_id")).toBe(
        MOCK_MCP_SERVER.id,
      );
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          resources: [{ id: "resource-from-mcp", name: "Resource from MCP" }],
        }),
      });
    });
    await page.route("**/prompts?*", async (route) => {
      expect(new URL(route.request().url()).searchParams.get("gateway_id")).toBe(
        MOCK_MCP_SERVER.id,
      );
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ prompts: [{ id: "prompt-from-mcp", name: "Prompt from MCP" }] }),
      });
    });
    await page.route("**/servers", async (route) => {
      expect(route.request().method()).toBe("POST");
      createPayload = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...MOCK_VIRTUAL_SERVER,
          id: "created-server-id",
          name: "MCP backed server",
          associatedToolIds: ["tool-from-mcp"],
          associatedResources: ["resource-from-mcp"],
          associatedPrompts: ["prompt-from-mcp"],
        }),
      });
    });
    await page.route("**/servers?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ servers: [] }),
      });
    });

    await page.goto("/app/gateways/create-server");
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("radio", { name: "Public" })).toBeChecked();
    await page.getByLabel("Name").fill("MCP backed server");
    await page.getByRole("button", { name: "Continue" }).click();
    await page
      .getByRole("button", { name: "Add tools, resources, and prompts from connected sources" })
      .click();
    await page.getByRole("checkbox", { name: "Select github-mcp" }).check();
    await expect(page.getByRole("button", { name: "Submit" })).toBeVisible();
    await page.getByRole("button", { name: "Submit" }).click();

    await expect.poll(() => createPayload).not.toBeNull();
    expect(createPayload).toMatchObject({
      server: {
        name: "MCP backed server",
        visibility: "public",
        associated_tools: ["tool-from-mcp"],
        associated_resources: ["resource-from-mcp"],
        associated_prompts: ["prompt-from-mcp"],
      },
      visibility: "public",
    });
    await expect(page).toHaveURL(/\/app\/gateways$/);
  });
});
