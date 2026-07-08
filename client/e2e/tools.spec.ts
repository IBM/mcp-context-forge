import { test, expect } from "./fixtures/api-mock";
import { APP } from "./utils/paths";
import type { Tool } from "../src/types/tool";

function makeTool(id: string, gatewaySlug: string, overrides: Partial<Tool> = {}): Tool {
  return {
    id,
    name: id,
    originalName: id,
    description: `Description for ${id}`,
    originalDescription: `Original description for ${id}`,
    title: `${id} Title`,
    gatewayId: `gw-${gatewaySlug}`,
    gatewaySlug,
    customName: id,
    customNameSlug: id.toLowerCase(),
    enabled: true,
    reachable: true,
    executionCount: 0,
    tags: [],
    integrationType: "mcp",
    requestType: "http",
    url: `https://example.com/${id}`,
    createdAt: "2026-04-10T10:00:00Z",
    updatedAt: "2026-04-10T10:00:00Z",
    ...overrides,
  };
}

const TOOL_A1 = makeTool("get_issues", "github-server");
const TOOL_A2 = makeTool("create_issue", "github-server");
const TOOL_B1 = makeTool("send_message", "slack-server");

test.describe("Tools page", () => {
  test.beforeEach(async ({ page, apiMock }) => {
    await apiMock.mockMe();

    await page.addInitScript(() => {
      sessionStorage.setItem("mcpgateway_token", "mock-token-12345");
    });
  });

  test("shows Add tools card when no tools exist", async ({ page }) => {
    await page.route("**/tools?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Add tools")).toBeVisible();
    await expect(
      page.getByText(/Tools will appear automatically when you connect a MCP server/i),
    ).toBeVisible();
  });

  test("Add tools card opens the tool form", async ({ page }) => {
    await page.route("**/tools?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    // Click the Add tools card
    await page.getByText("Add tools").click();

    await expect(page.getByRole("heading", { name: "Add tool" })).toBeVisible();
  });

  test("shows tools grouped by gateway slug", async ({ page }) => {
    await page.route("**/tools?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([TOOL_A1, TOOL_A2, TOOL_B1]),
      });
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("heading", { name: "Tools" })).toBeVisible();

    await expect(page.getByText("github-server")).toBeVisible();
    await expect(page.getByText("slack-server")).toBeVisible();

    await expect(page.getByText("get_issues")).toBeVisible();
    await expect(page.getByText("create_issue")).toBeVisible();
    await expect(page.getByText("send_message")).toBeVisible();

    await expect(page.getByText("2 tools")).toBeVisible();
    await expect(page.getByText("1 tool")).toBeVisible();
  });

  test("shows error alert when tools API fails", async ({ page }) => {
    await page.route("**/tools?*", async (route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Internal server error" }),
      });
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByText("Error loading tools")).toBeVisible();
  });

  test("caps badge display at 8 and shows +N overflow tag", async ({ page }) => {
    const manyTools: Tool[] = Array.from({ length: 10 }, (_, i) =>
      makeTool(`tool_${i + 1}`, "big-gateway"),
    );

    await page.route("**/tools?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(manyTools),
      });
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("big-gateway")).toBeVisible();
    await expect(page.getByText("10 tools")).toBeVisible();

    await expect(page.getByText("tool_1")).toBeVisible();
    await expect(page.getByText("tool_8")).toBeVisible();

    await expect(page.getByText("tool_9")).not.toBeVisible();
    await expect(page.getByText("tool_10")).not.toBeVisible();
    await expect(page.getByText("+2")).toBeVisible();
  });

  test("opens more options dropdown and shows View Details item", async ({ page }) => {
    await page.route("**/tools?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([TOOL_A1]),
      });
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "More options for github-server" }).click();

    await expect(page.getByRole("menuitem", { name: "View Details" })).toBeVisible();
  });

  test("opens details panel when View Details is clicked", async ({ page }) => {
    await page.route("**/tools?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([TOOL_A1, TOOL_A2]),
      });
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "More options for github-server" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();

    const panel = page.getByRole("region", { name: /Tools for github-server/i });
    await expect(panel).toBeVisible();

    await expect(panel.getByText("get_issues").first()).toBeVisible();
    await expect(panel.getByText("create_issue").first()).toBeVisible();
  });

  test("closes details panel via close button", async ({ page }) => {
    await page.route("**/tools?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([TOOL_A1]),
      });
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "More options for github-server" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();

    const panel = page.getByRole("region", { name: /Tools for github-server/i });
    await expect(panel).toBeVisible();

    await page.getByLabel("Close tool details").click();

    await expect(panel).not.toBeVisible();
  });

  test("optimistically removes tool on delete confirmation and shows success toast", async ({
    page,
  }) => {
    let deleteRequestCount = 0;

    await page.route("**/tools?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([TOOL_A1, TOOL_A2]),
      });
    });
    await page.route(`**/tools/${TOOL_A1.id}`, async (route) => {
      if (route.request().method() === "DELETE") {
        deleteRequestCount += 1;
        await route.fulfill({ status: 204 });
      } else {
        await route.fallback();
      }
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "More options for github-server" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();

    const panel = page.getByRole("region", { name: /Tools for github-server/i });
    await expect(panel).toBeVisible();

    await expect(panel.getByText("get_issues").first()).toBeVisible();

    await panel.getByRole("button", { name: "More options" }).first().click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("dialog", { name: "Delete tool" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText(/Are you sure you want to delete "get_issues"/i)).toBeVisible();

    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect.poll(() => deleteRequestCount).toBe(1);
    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: /Tool.*get_issues.*deleted/i }),
    ).toBeVisible();
  });

  test("rolls back optimistic delete and shows error toast when delete API fails", async ({
    page,
  }) => {
    let deleteRequestCount = 0;

    await page.route("**/tools?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([TOOL_A1, TOOL_A2]),
      });
    });
    await page.route(`**/tools/${TOOL_A1.id}`, async (route) => {
      if (route.request().method() === "DELETE") {
        deleteRequestCount += 1;
        await route.fulfill({
          status: 403,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Forbidden" }),
        });
      } else {
        await route.fallback();
      }
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "More options for github-server" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();

    const panel = page.getByRole("region", { name: /Tools for github-server/i });
    await expect(panel).toBeVisible();

    await panel.getByRole("button", { name: "More options" }).first().click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("dialog", { name: "Delete tool" });
    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect.poll(() => deleteRequestCount).toBe(1);

    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: /Forbidden/i }),
    ).toBeVisible();

    await expect(panel.getByText("get_issues").first()).toBeVisible();
  });

  test("cancels delete dialog and keeps tool in details panel", async ({ page }) => {
    await page.route("**/tools?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([TOOL_A1, TOOL_A2]),
      });
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "More options for github-server" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();

    const panel = page.getByRole("region", { name: /Tools for github-server/i });
    await panel.getByRole("button", { name: "More options" }).first().click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("dialog", { name: "Delete tool" });
    await expect(dialog).toBeVisible();

    await dialog.getByRole("button", { name: "Cancel" }).click();

    await expect(dialog).not.toBeVisible();
    await expect(panel.getByText("get_issues").first()).toBeVisible();
  });

  test("details panel closes immediately when the only tool in a group is deleted", async ({
    page,
  }) => {
    const SOLO = makeTool("solo_tool", "solo-gateway");

    await page.route("**/tools?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([SOLO]),
      });
    });
    await page.route(`**/tools/${SOLO.id}`, async (route) => {
      if (route.request().method() === "DELETE") {
        await route.fulfill({ status: 204 });
      } else {
        await route.fallback();
      }
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "More options for solo-gateway" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();

    const panel = page.getByRole("region", { name: /Tools for solo-gateway/i });
    await expect(panel).toBeVisible();

    await panel.getByRole("button", { name: "More options" }).first().click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    await page
      .getByRole("dialog", { name: "Delete tool" })
      .getByRole("button", { name: "Delete" })
      .click();

    await expect(panel).not.toBeVisible();
  });

  test("details panel stays open and deleted row is gone while remaining tool stays visible", async ({
    page,
  }) => {
    const TOOL_1 = makeTool("alpha_tool", "multi-gw");
    const TOOL_2 = makeTool("beta_tool", "multi-gw");

    let resolveDelete!: () => void;
    const deleteHeld = new Promise<void>((res) => {
      resolveDelete = res;
    });

    await page.route("**/tools?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([TOOL_1, TOOL_2]),
      });
    });
    await page.route(`**/tools/${TOOL_1.id}`, async (route) => {
      if (route.request().method() === "DELETE") {
        await deleteHeld;
        await route.fulfill({ status: 204 });
      } else {
        await route.fallback();
      }
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "More options for multi-gw" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();

    const panel = page.getByRole("region", { name: /Tools for multi-gw/i });
    await expect(panel).toBeVisible();
    await expect(panel.getByText("alpha_tool").first()).toBeVisible();
    await expect(panel.getByText("beta_tool").first()).toBeVisible();

    await panel.getByRole("button", { name: "More options" }).first().click();
    await page.getByRole("menuitem", { name: "Delete" }).click();
    await page
      .getByRole("dialog", { name: "Delete tool" })
      .getByRole("button", { name: "Delete" })
      .click();

    await expect(panel.getByText("alpha_tool")).not.toBeVisible();
    await expect(panel.getByText("beta_tool").first()).toBeVisible();

    resolveDelete();
    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: /alpha_tool/i }),
    ).toBeVisible();
  });

  test("details panel re-opens with all tools restored after rollback", async ({ page }) => {
    const TOOL_1 = makeTool("rollback_tool_1", "rb-gateway");
    const TOOL_2 = makeTool("rollback_tool_2", "rb-gateway");

    await page.route("**/tools?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([TOOL_1, TOOL_2]),
      });
    });
    await page.route(`**/tools/${TOOL_1.id}`, async (route) => {
      if (route.request().method() === "DELETE") {
        await route.fulfill({
          status: 403,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Forbidden" }),
        });
      } else {
        await route.fallback();
      }
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "More options for rb-gateway" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();

    const panel = page.getByRole("region", { name: /Tools for rb-gateway/i });
    await expect(panel).toBeVisible();

    await panel.getByRole("button", { name: "More options" }).first().click();
    await page.getByRole("menuitem", { name: "Delete" }).click();
    await page
      .getByRole("dialog", { name: "Delete tool" })
      .getByRole("button", { name: "Delete" })
      .click();

    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: /Forbidden/i }),
    ).toBeVisible();

    await expect(panel).toBeVisible();
    await expect(panel.getByText("rollback_tool_1").first()).toBeVisible();
    await expect(panel.getByText("rollback_tool_2").first()).toBeVisible();
  });

  test("card group disappears from grid when its only tool is deleted", async ({ page }) => {
    const SOLO = makeTool("lone_tool", "lone-gateway");
    let toolDeleted = false;

    await page.route("**/tools?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(toolDeleted ? [TOOL_A1] : [SOLO, TOOL_A1]),
      });
    });
    await page.route(`**/tools/${SOLO.id}`, async (route) => {
      if (route.request().method() === "DELETE") {
        toolDeleted = true;
        await route.fulfill({ status: 204 });
      } else {
        await route.fallback();
      }
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("lone-gateway")).toBeVisible();
    await expect(page.getByText("github-server")).toBeVisible();

    await page.getByRole("button", { name: "More options for lone-gateway" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();

    const panel = page.getByRole("region", { name: /Tools for lone-gateway/i });
    await expect(panel).toBeVisible();

    await panel.getByRole("button", { name: "More options" }).first().click();
    await page.getByRole("menuitem", { name: "Delete" }).click();
    await page
      .getByRole("dialog", { name: "Delete tool" })
      .getByRole("button", { name: "Delete" })
      .click();

    await expect(page.getByText("lone-gateway")).not.toBeVisible();

    await expect(page.getByText("github-server")).toBeVisible();
  });

  test("Add tools card is keyboard accessible via Enter", async ({ page }) => {
    await page.route("**/tools?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    const addToolsCard = page.getByRole("button").filter({ hasText: "Add tools" });
    await addToolsCard.focus();
    await page.keyboard.press("Enter");

    await expect(page.getByRole("heading", { name: "Add tool" })).toBeVisible();
  });
});
