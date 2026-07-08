import { test, expect } from "./fixtures/api-mock";
import { APP } from "./utils/paths";
import type { ResourceRead } from "../src/generated/types";

type Resource = NonNullable<ResourceRead>;

function makeResource(id: string, gatewayId: string, overrides: Partial<Resource> = {}): Resource {
  return {
    id,
    uri: `resource://test/${id}`,
    name: id,
    description: `Description for ${id}`,
    mimeType: "text/plain",
    size: 1024,
    tags: [],
    enabled: true,
    createdAt: "2026-04-28T15:41:31.233166",
    updatedAt: "2026-04-28T15:41:31.233168",
    createdBy: "admin@example.com",
    visibility: "public",
    gatewayId,
    ...overrides,
  };
}

const RESOURCE_A1 = makeResource("document-txt", "github-server");
const RESOURCE_A2 = makeResource("config-json", "github-server", { mimeType: "application/json" });
const RESOURCE_B1 = makeResource("readme-md", "slack-server");

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
    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Add resources")).toBeVisible();
    await expect(
      page.getByText(/Resources will appear automatically when you connect a MCP server/),
    ).toBeVisible();
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

    await page.getByText("Add resources").click();

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

  test("shows resources grouped by gateway slug", async ({ page }) => {
    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([RESOURCE_A1, RESOURCE_A2, RESOURCE_B1]),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("heading", { name: "Resources" })).toBeVisible();

    await expect(page.getByText("github-server")).toBeVisible();
    await expect(page.getByText("slack-server")).toBeVisible();

    await expect(page.getByText("document-txt")).toBeVisible();
    await expect(page.getByText("config-json")).toBeVisible();
    await expect(page.getByText("readme-md")).toBeVisible();

    await expect(page.getByText("2 resources")).toBeVisible();
    await expect(page.getByText("1 resource")).toBeVisible();
  });

  test("caps badge display at 8 and shows +N overflow tag", async ({ page }) => {
    const manyResources: Resource[] = Array.from({ length: 10 }, (_, i) =>
      makeResource(`resource_${i + 1}`, "big-gateway"),
    );

    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(manyResources),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("big-gateway")).toBeVisible();
    await expect(page.getByText("10 resources")).toBeVisible();

    await expect(page.getByText("resource_1")).toBeVisible();
    await expect(page.getByText("resource_8")).toBeVisible();

    await expect(page.getByText("resource_9")).not.toBeVisible();
    await expect(page.getByText("resource_10")).not.toBeVisible();
    await expect(page.getByText("+2")).toBeVisible();
  });

  test("opens more options dropdown and shows View Details item", async ({ page }) => {
    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([RESOURCE_A1]),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "More options for github-server" }).click();

    await expect(page.getByRole("menuitem", { name: "View Details" })).toBeVisible();
  });

  test("opens details panel when View Details is clicked", async ({ page }) => {
    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([RESOURCE_A1, RESOURCE_A2]),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "More options for github-server" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();

    const panel = page.getByRole("region", { name: /Resources for github-server/i });
    await expect(panel).toBeVisible();

    await expect(panel.getByText("document-txt").first()).toBeVisible();
    await expect(panel.getByText("config-json").first()).toBeVisible();
  });

  test("closes details panel via close button", async ({ page }) => {
    await page.route("**/resources?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([RESOURCE_A1]),
      });
    });

    await page.goto(APP.RESOURCES);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "More options for github-server" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();

    const panel = page.getByRole("region", { name: /Resources for github-server/i });
    await expect(panel).toBeVisible();

    await page.getByLabel("Close resource details").click();

    await expect(panel).not.toBeVisible();
  });

  test.describe("Delete resource", () => {
    test("cancel in confirm dialog keeps resource visible", async ({ page }) => {
      await page.route("**/resources?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([RESOURCE_A1]),
        });
      });

      await page.goto(APP.RESOURCES);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "More options for github-server" }).click();
      await page.getByRole("menuitem", { name: "View Details" }).click();

      const panel = page.getByRole("region", { name: /Resources for github-server/i });
      await panel.getByRole("button", { name: "More options" }).first().click();
      await page.getByRole("menuitem", { name: "Delete" }).click();

      const dialog = page.getByRole("dialog", { name: "Delete resource" });
      await expect(dialog).toBeVisible();
      await expect(
        dialog.getByText(/Are you sure you want to delete "document-txt"/i),
      ).toBeVisible();

      await dialog.getByRole("button", { name: "Cancel" }).click();

      await expect(dialog).not.toBeVisible();
      await expect(panel.getByText("document-txt").first()).toBeVisible();
    });

    test("optimistically removes resource on delete confirmation and shows success toast", async ({
      page,
    }) => {
      let deleteRequestCount = 0;

      await page.route("**/resources?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([RESOURCE_A1, RESOURCE_A2]),
        });
      });
      await page.route(`**/resources/${RESOURCE_A1.id}`, async (route) => {
        if (route.request().method() === "DELETE") {
          deleteRequestCount += 1;
          await route.fulfill({ status: 204 });
        } else {
          await route.fallback();
        }
      });

      await page.goto(APP.RESOURCES);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "More options for github-server" }).click();
      await page.getByRole("menuitem", { name: "View Details" }).click();

      const panel = page.getByRole("region", { name: /Resources for github-server/i });
      await expect(panel).toBeVisible();
      await expect(panel.getByText("document-txt").first()).toBeVisible();

      await panel.getByRole("button", { name: "More options" }).first().click();
      await page.getByRole("menuitem", { name: "Delete" }).click();

      const dialog = page.getByRole("dialog", { name: "Delete resource" });
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Delete" }).click();

      await expect.poll(() => deleteRequestCount).toBe(1);
      await expect(
        page.locator("[data-sonner-toast]").filter({ hasText: /document-txt.*deleted/i }),
      ).toBeVisible();
    });

    test("rolls back optimistic delete and shows error toast when delete API fails", async ({
      page,
    }) => {
      let deleteRequestCount = 0;

      await page.route("**/resources?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([RESOURCE_A1, RESOURCE_A2]),
        });
      });
      await page.route(`**/resources/${RESOURCE_A1.id}`, async (route) => {
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

      await page.goto(APP.RESOURCES);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "More options for github-server" }).click();
      await page.getByRole("menuitem", { name: "View Details" }).click();

      const panel = page.getByRole("region", { name: /Resources for github-server/i });
      await expect(panel).toBeVisible();

      await panel.getByRole("button", { name: "More options" }).first().click();
      await page.getByRole("menuitem", { name: "Delete" }).click();

      const dialog = page.getByRole("dialog", { name: "Delete resource" });
      await dialog.getByRole("button", { name: "Delete" }).click();

      await expect.poll(() => deleteRequestCount).toBe(1);

      await expect(
        page.locator("[data-sonner-toast]").filter({ hasText: /Forbidden/i }),
      ).toBeVisible();

      await expect(panel.getByText("document-txt").first()).toBeVisible();
    });

    test("details panel closes immediately when the only resource in a group is deleted", async ({
      page,
    }) => {
      const SOLO = makeResource("solo_resource", "solo-gateway");

      await page.route("**/resources?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([SOLO]),
        });
      });
      await page.route(`**/resources/${SOLO.id}`, async (route) => {
        if (route.request().method() === "DELETE") {
          await route.fulfill({ status: 204 });
        } else {
          await route.fallback();
        }
      });

      await page.goto(APP.RESOURCES);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "More options for solo-gateway" }).click();
      await page.getByRole("menuitem", { name: "View Details" }).click();

      const panel = page.getByRole("region", { name: /Resources for solo-gateway/i });
      await expect(panel).toBeVisible();

      await panel.getByRole("button", { name: "More options" }).first().click();
      await page.getByRole("menuitem", { name: "Delete" }).click();

      await page
        .getByRole("dialog", { name: "Delete resource" })
        .getByRole("button", { name: "Delete" })
        .click();

      await expect(panel).not.toBeVisible();
    });

    test("details panel stays open and deleted row is gone while remaining resource stays visible", async ({
      page,
    }) => {
      const RESOURCE_1 = makeResource("alpha_resource", "multi-gw");
      const RESOURCE_2 = makeResource("beta_resource", "multi-gw");

      let resolveDelete!: () => void;
      const deleteHeld = new Promise<void>((res) => {
        resolveDelete = res;
      });

      await page.route("**/resources?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([RESOURCE_1, RESOURCE_2]),
        });
      });
      await page.route(`**/resources/${RESOURCE_1.id}`, async (route) => {
        if (route.request().method() === "DELETE") {
          await deleteHeld;
          await route.fulfill({ status: 204 });
        } else {
          await route.fallback();
        }
      });

      await page.goto(APP.RESOURCES);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "More options for multi-gw" }).click();
      await page.getByRole("menuitem", { name: "View Details" }).click();

      const panel = page.getByRole("region", { name: /Resources for multi-gw/i });
      await expect(panel).toBeVisible();
      await expect(panel.getByText("alpha_resource").first()).toBeVisible();
      await expect(panel.getByText("beta_resource").first()).toBeVisible();

      await panel.getByRole("button", { name: "More options" }).first().click();
      await page.getByRole("menuitem", { name: "Delete" }).click();
      await page
        .getByRole("dialog", { name: "Delete resource" })
        .getByRole("button", { name: "Delete" })
        .click();

      await expect(panel.getByText("alpha_resource")).not.toBeVisible();
      await expect(panel.getByText("beta_resource").first()).toBeVisible();

      resolveDelete();
      await expect(
        page.locator("[data-sonner-toast]").filter({ hasText: /alpha_resource/i }),
      ).toBeVisible();
    });

    test("card group disappears from grid when its only resource is deleted", async ({ page }) => {
      const SOLO = makeResource("lone_resource", "lone-gateway");

      await page.route("**/resources?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([SOLO, RESOURCE_A1]),
        });
      });
      await page.route(`**/resources/${SOLO.id}`, async (route) => {
        if (route.request().method() === "DELETE") {
          await route.fulfill({ status: 204 });
        } else {
          await route.fallback();
        }
      });

      await page.goto(APP.RESOURCES);
      await page.waitForLoadState("networkidle");

      await expect(page.getByText("lone-gateway")).toBeVisible();
      await expect(page.getByText("github-server")).toBeVisible();

      await page.getByRole("button", { name: "More options for lone-gateway" }).click();
      await page.getByRole("menuitem", { name: "View Details" }).click();

      const panel = page.getByRole("region", { name: /Resources for lone-gateway/i });
      await expect(panel).toBeVisible();

      await panel.getByRole("button", { name: "More options" }).first().click();
      await page.getByRole("menuitem", { name: "Delete" }).click();
      await page
        .getByRole("dialog", { name: "Delete resource" })
        .getByRole("button", { name: "Delete" })
        .click();

      await expect(page.getByText("lone-gateway")).not.toBeVisible();
      await expect(page.getByText("github-server")).toBeVisible();
    });
  });
});
