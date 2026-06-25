import { test, expect } from "./fixtures/api-mock";
import { APP } from "./utils/paths";
import type { MCPServer } from "../src/types/server";

const MOCK_SERVER: MCPServer = {
  id: "srv-abc123",
  name: "GitHub MCP Server",
  url: "http://localhost:9000/sse",
  transport: "SSE",
  enabled: true,
  reachable: true,
  visibility: "public",
  team: "Platform Admins",
  owner_email: "admin@example.com",
  toolCount: 5,
  promptCount: 2,
  resourceCount: 3,
  createdAt: "2026-04-10T10:00:00Z",
  updatedAt: "2026-04-10T10:00:00Z",
};

const MOCK_SERVER_2: MCPServer = {
  id: "srv-def456",
  name: "Slack MCP Server",
  url: "http://localhost:9001/sse",
  transport: "SSE",
  enabled: false,
  reachable: false,
  visibility: "team",
  team: "Engineering",
  owner_email: "dev@example.com",
  toolCount: 3,
  promptCount: 0,
  resourceCount: 1,
  createdAt: "2026-04-11T11:00:00Z",
  updatedAt: "2026-04-11T11:00:00Z",
};

test.describe("MCP Servers page", () => {
  test.beforeEach(async ({ page, apiMock }) => {
    await apiMock.mockMe();

    await page.addInitScript(() => {
      sessionStorage.setItem("mcpgateway_token", "mock-token-12345");
    });
  });

  test("shows empty state panel when no servers exist", async ({ page }) => {
    await page.route("**/gateways?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ gateways: [], nextCursor: null }),
      });
    });

    await page.goto(APP.SERVERS);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Connect MCP server")).toBeVisible();
    await expect(
      page.getByText(/Register a MCP server to federate its tools, resources, and prompts/i),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: /Connect/i })).toBeVisible();
  });

  test("shows servers list with title and Connect button when servers exist", async ({ page }) => {
    await page.route("**/gateways?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ gateways: [MOCK_SERVER], nextCursor: null }),
      });
    });

    await page.goto(APP.SERVERS);
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("heading", { name: "MCP Servers" })).toBeVisible();
    await expect(page.getByRole("row").filter({ hasText: "GitHub MCP Server" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Connect/i })).toBeVisible();
  });

  test("shows error alert when API fails", async ({ page }) => {
    await page.route("**/gateways?*", async (route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Internal server error" }),
      });
    });

    await page.goto(APP.SERVERS);
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByText("Error loading servers")).toBeVisible();
  });

  test("shows both servers when multiple exist", async ({ page }) => {
    await page.route("**/gateways?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ gateways: [MOCK_SERVER, MOCK_SERVER_2], nextCursor: null }),
      });
    });

    await page.goto(APP.SERVERS);
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("row").filter({ hasText: "GitHub MCP Server" })).toBeVisible();
    await expect(page.getByRole("row").filter({ hasText: "Slack MCP Server" })).toBeVisible();
  });

  test("shows Load More button when nextCursor is present", async ({ page }) => {
    await page.route("**/gateways?*", async (route) => {
      const url = new URL(route.request().url());
      const hasCursor = url.searchParams.has("cursor");

      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          hasCursor
            ? { gateways: [MOCK_SERVER_2], nextCursor: null }
            : { gateways: [MOCK_SERVER], nextCursor: "cursor-1" },
        ),
      });
    });

    await page.goto(APP.SERVERS);
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("row").filter({ hasText: "GitHub MCP Server" })).toBeVisible();
    await expect(page.getByRole("row").filter({ hasText: "Slack MCP Server" })).not.toBeVisible();

    const loadMoreButton = page.getByRole("button", { name: /Load More/i });
    await expect(loadMoreButton).toBeVisible();
    await loadMoreButton.click();

    await expect(page.getByRole("row").filter({ hasText: "Slack MCP Server" })).toBeVisible();
    await expect(page.getByRole("row").filter({ hasText: "GitHub MCP Server" })).toBeVisible();
    await expect(loadMoreButton).not.toBeVisible();
  });

  test("hides Load More button when there is no nextCursor", async ({ page }) => {
    await page.route("**/gateways?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ gateways: [MOCK_SERVER], nextCursor: null }),
      });
    });

    await page.goto(APP.SERVERS);
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("button", { name: /Load More/i })).not.toBeVisible();
  });

  test("opens server actions dropdown menu", async ({ page }) => {
    await page.route("**/gateways?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ gateways: [MOCK_SERVER], nextCursor: null }),
      });
    });

    await page.goto(APP.SERVERS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for GitHub MCP Server" }).click();

    await expect(page.getByRole("menuitem", { name: "View Details" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Edit" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Test Connection" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Deactivate" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Delete" })).toBeVisible();
  });

  test("optimistically removes server on delete confirmation and shows success toast", async ({
    page,
  }) => {
    let deleteRequestCount = 0;

    await page.route("**/gateways?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ gateways: [MOCK_SERVER, MOCK_SERVER_2], nextCursor: null }),
      });
    });
    await page.route(`**/gateways/${MOCK_SERVER.id}`, async (route) => {
      expect(route.request().method()).toBe("DELETE");
      deleteRequestCount += 1;
      await route.fulfill({ status: 204 });
    });

    await page.goto(APP.SERVERS);
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("row").filter({ hasText: "GitHub MCP Server" })).toBeVisible();
    await expect(page.getByRole("row").filter({ hasText: "Slack MCP Server" })).toBeVisible();

    await page.getByRole("button", { name: "Actions for GitHub MCP Server" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("dialog", { name: "Delete MCP Server" });
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByText(
        "Are you sure you want to delete this MCP server? This action cannot be undone.",
      ),
    ).toBeVisible();

    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect(page.getByRole("row").filter({ hasText: "GitHub MCP Server" })).not.toBeVisible();
    await expect(page.getByRole("row").filter({ hasText: "Slack MCP Server" })).toBeVisible();

    await expect.poll(() => deleteRequestCount).toBe(1);
    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: /GitHub MCP Server deleted/ }),
    ).toBeVisible();
  });

  test("cancels delete and keeps server in list", async ({ page }) => {
    await page.route("**/gateways?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ gateways: [MOCK_SERVER], nextCursor: null }),
      });
    });

    await page.goto(APP.SERVERS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for GitHub MCP Server" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("dialog", { name: "Delete MCP Server" });
    await expect(dialog).toBeVisible();

    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).not.toBeVisible();

    await expect(page.getByRole("row").filter({ hasText: "GitHub MCP Server" })).toBeVisible();
  });

  test("rolls back optimistic delete and shows error toast when delete fails", async ({ page }) => {
    let deleteRequestCount = 0;

    await page.route("**/gateways?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ gateways: [MOCK_SERVER, MOCK_SERVER_2], nextCursor: null }),
      });
    });
    await page.route(`**/gateways/${MOCK_SERVER.id}`, async (route) => {
      expect(route.request().method()).toBe("DELETE");
      deleteRequestCount += 1;
      await route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Forbidden" }),
      });
    });

    await page.goto(APP.SERVERS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for GitHub MCP Server" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("dialog", { name: "Delete MCP Server" });
    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect.poll(() => deleteRequestCount).toBe(1);

    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: "Error deleting mcp server" }),
    ).toBeVisible();

    await expect(page.getByRole("row").filter({ hasText: "GitHub MCP Server" })).toBeVisible();
  });

  test("closes details drawer optimistically when the viewed server is deleted", async ({
    page,
  }) => {
    await page.route("**/gateways?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ gateways: [MOCK_SERVER, MOCK_SERVER_2], nextCursor: null }),
      });
    });
    await page.route(`**/gateways/${MOCK_SERVER.id}`, async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_SERVER),
        });
        return;
      }
      await route.fulfill({ status: 204 });
    });
    await page.route(`**/gateways/${MOCK_SERVER.id}/tools*`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ tools: [] }),
      }),
    );
    await page.route(`**/gateways/${MOCK_SERVER.id}/resources*`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ resources: [] }),
      }),
    );
    await page.route(`**/gateways/${MOCK_SERVER.id}/prompts*`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ prompts: [] }),
      }),
    );

    await page.goto(APP.SERVERS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for GitHub MCP Server" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();
    await expect(page.getByRole("heading", { name: "GitHub MCP Server" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("button", { name: /close mcp server details/i })).not.toBeVisible();

    await page.getByRole("button", { name: "Actions for GitHub MCP Server" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();
    await page
      .getByRole("dialog", { name: "Delete MCP Server" })
      .getByRole("button", { name: "Delete" })
      .click();

    await expect(page.getByRole("row").filter({ hasText: "GitHub MCP Server" })).not.toBeVisible();
    await expect(page.getByRole("button", { name: /close mcp server details/i })).not.toBeVisible();
  });

  test("restores details drawer when delete is rolled back after API failure", async ({ page }) => {
    await page.route("**/gateways?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ gateways: [MOCK_SERVER, MOCK_SERVER_2], nextCursor: null }),
      });
    });
    await page.route(`**/gateways/${MOCK_SERVER.id}`, async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_SERVER),
        });
        return;
      }

      await route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Forbidden" }),
      });
    });
    await page.route(`**/gateways/${MOCK_SERVER.id}/tools*`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ tools: [] }),
      }),
    );
    await page.route(`**/gateways/${MOCK_SERVER.id}/resources*`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ resources: [] }),
      }),
    );
    await page.route(`**/gateways/${MOCK_SERVER.id}/prompts*`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ prompts: [] }),
      }),
    );

    await page.goto(APP.SERVERS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for GitHub MCP Server" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();
    await expect(page.getByRole("heading", { name: "GitHub MCP Server" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("button", { name: /close mcp server details/i })).not.toBeVisible();

    await page.getByRole("button", { name: "Actions for GitHub MCP Server" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();
    await page
      .getByRole("dialog", { name: "Delete MCP Server" })
      .getByRole("button", { name: "Delete" })
      .click();

    await expect(page.getByRole("row").filter({ hasText: "GitHub MCP Server" })).toBeVisible();
    await expect(page.getByRole("button", { name: /close mcp server details/i })).not.toBeVisible();

    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: "Error deleting mcp server" }),
    ).toBeVisible();
  });

  test("does not close details drawer when a different server is deleted", async ({ page }) => {
    await page.route("**/gateways?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ gateways: [MOCK_SERVER, MOCK_SERVER_2], nextCursor: null }),
      });
    });
    await page.route(`**/gateways/${MOCK_SERVER.id}`, async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_SERVER),
        });
      }
    });
    await page.route(`**/gateways/${MOCK_SERVER_2.id}`, async (route) => {
      await route.fulfill({ status: 204 });
    });
    await page.route(`**/gateways/${MOCK_SERVER.id}/tools*`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ tools: [] }),
      }),
    );
    await page.route(`**/gateways/${MOCK_SERVER.id}/resources*`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ resources: [] }),
      }),
    );
    await page.route(`**/gateways/${MOCK_SERVER.id}/prompts*`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ prompts: [] }),
      }),
    );

    await page.goto(APP.SERVERS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for GitHub MCP Server" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();
    await expect(page.getByRole("heading", { name: "GitHub MCP Server" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("button", { name: /close mcp server details/i })).not.toBeVisible();

    await page.getByRole("button", { name: "Actions for Slack MCP Server" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();
    await page
      .getByRole("dialog", { name: "Delete MCP Server" })
      .getByRole("button", { name: "Delete" })
      .click();

    await expect(page.getByRole("row").filter({ hasText: "Slack MCP Server" })).not.toBeVisible();

    await page.getByRole("button", { name: "Actions for GitHub MCP Server" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();
    await expect(page.getByRole("heading", { name: "GitHub MCP Server" })).toBeVisible();
  });

  test("opens server details panel from actions menu", async ({ page }) => {
    await page.route("**/gateways?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ gateways: [MOCK_SERVER], nextCursor: null }),
      });
    });
    await page.route(`**/gateways/${MOCK_SERVER.id}`, async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_SERVER),
        });
      }
    });
    await page.route(`**/gateways/${MOCK_SERVER.id}/tools*`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ tools: [] }),
      });
    });
    await page.route(`**/gateways/${MOCK_SERVER.id}/resources*`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ resources: [] }),
      });
    });
    await page.route(`**/gateways/${MOCK_SERVER.id}/prompts*`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ prompts: [] }),
      });
    });

    await page.goto(APP.SERVERS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Actions for GitHub MCP Server" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();

    // Wait for the details panel to open (heading "GitHub MCP Server" appears in the panel header)
    await expect(page.getByRole("heading", { name: "GitHub MCP Server" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Components" })).toBeVisible();
  });

  test("shows per-page selector in the servers footer", async ({ page }) => {
    await page.route("**/gateways?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ gateways: [MOCK_SERVER], nextCursor: null }),
      });
    });

    await page.goto(APP.SERVERS);
    await page.waitForLoadState("networkidle");

    await expect(page.locator("#limit-select")).toBeVisible();
    await expect(page.getByText(/Per page:/i)).toBeVisible();
  });
});
