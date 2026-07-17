import type { Page } from "@playwright/test";
import { test, expect } from "./fixtures/api-mock";
import { APP } from "./utils/paths";
import type { Tool } from "../src/types/tool";

/** Payload the create form POSTs to `/tools` (see useToolForm.getFormData). */
interface CreateToolPayload {
  tool: Record<string, unknown>;
  team_id?: string;
}

/** Flat payload the edit form PUTs to `/tools/{id}` (see useToolForm.handleSubmit). */
interface UpdateToolPayload {
  name?: string;
  url?: string;
  customName?: string;
  [key: string]: unknown;
}

/** Stub the tools list endpoint (`/tools?limit=0&include_inactive=true`). */
async function routeToolsList(page: Page, tools: Tool[]) {
  await page.route("**/tools?*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(tools),
    });
  });
}

async function openAddToolForm(page: Page) {
  await page.getByText("Add tools").click();
  await expect(page.getByRole("heading", { name: "Add tool" })).toBeVisible();
}

async function fillToolBasics(page: Page, name: string, url: string) {
  await page.locator("#tool-name").fill(name);
  await page.locator("#tool-url").fill(url);
}

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
    deprecated: false,
    executionCount: 0,
    tags: [],
    integrationType: "mcp",
    requestType: "http",
    url: `https://example.com/${id}`,
    headers: {},
    inputSchema: { type: "object", properties: {} },
    annotations: {},
    jsonpathFilter: null,
    auth: null,
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

  test("truncates a long gateway name and keeps the overflow menu visible", async ({ page }) => {
    // A gateway slug long enough to overflow the card at the default viewport.
    const longSlug =
      "openzeppelin-stylus-contracts-enterprise-edition-extended-long-server-name-instance";
    const tools: Tool[] = [makeTool("stylus_erc20", longSlug), makeTool("stylus_erc721", longSlug)];

    await page.route("**/tools?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(tools),
      });
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    // The kebab menu for the long-named group must stay visible.
    const kebab = page.getByRole("button", { name: `More options for ${longSlug}` });
    await expect(kebab).toBeVisible();

    const card = page.locator('[data-slot="card"]').filter({ has: kebab });
    const title = card.locator('[data-slot="card-header"] span.truncate').first();

    // The title is actually clipped (its content is wider than the box) and
    // carries a native tooltip so the full name stays discoverable on hover.
    const isTruncated = await title.evaluate((el) => el.scrollWidth > el.clientWidth);
    expect(isTruncated).toBe(true);
    await expect(title).toHaveAttribute("title", longSlug);

    // The kebab is not pushed past the card's right edge (it was clipped before).
    const cardBox = await card.boundingBox();
    const kebabBox = await kebab.boundingBox();
    expect(cardBox).not.toBeNull();
    expect(kebabBox).not.toBeNull();
    expect(kebabBox!.x + kebabBox!.width).toBeLessThanOrEqual(cardBox!.x + cardBox!.width + 1);

    // And it remains functional.
    await kebab.click();
    await expect(page.getByRole("menuitem", { name: "View Details" })).toBeVisible();
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

  // ---------------------------------------------------------------------------
  // Create
  // ---------------------------------------------------------------------------

  test("creates a REST tool and POSTs the expected payload", async ({ page }) => {
    let createBody: CreateToolPayload | null = null;

    await routeToolsList(page, []);
    await page.route("**/tools", async (route) => {
      if (route.request().method() === "POST") {
        createBody = route.request().postDataJSON() as CreateToolPayload;
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({ id: "list_users" }),
        });
      } else {
        await route.fallback();
      }
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await openAddToolForm(page);
    await fillToolBasics(page, "list_users", "https://api.example.com/users");

    await page.getByRole("button", { name: "Add tool" }).click();

    await expect.poll(() => createBody).not.toBeNull();
    const tool = createBody!.tool;
    expect(tool.name).toBe("list_users");
    expect(tool.url).toBe("https://api.example.com/users");
    expect(tool.integration_type).toBe("REST");
    expect(tool.request_type).toBe("POST");
    expect(tool.auth_type).toBeUndefined();

    // Form closes and returns to the grid on success.
    await expect(page.getByRole("heading", { name: "Tools" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Add tool" })).not.toBeVisible();
  });

  test("chosen request type is sent in the create payload", async ({ page }) => {
    let createBody: CreateToolPayload | null = null;

    await routeToolsList(page, []);
    await page.route("**/tools", async (route) => {
      if (route.request().method() === "POST") {
        createBody = route.request().postDataJSON() as CreateToolPayload;
        await route.fulfill({ status: 201, contentType: "application/json", body: "{}" });
      } else {
        await route.fallback();
      }
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await openAddToolForm(page);
    await fillToolBasics(page, "get_user", "https://api.example.com/users/1");

    // The request-type segmented control is a radiogroup of GET/POST/PUT/PATCH/DELETE.
    await page.locator('label[for="request-GET"]').click();
    await page.getByRole("button", { name: "Add tool" }).click();

    await expect.poll(() => createBody).not.toBeNull();
    expect(createBody!.tool.request_type).toBe("GET");
  });

  test("shows a submit error when the create API fails", async ({ page }) => {
    await routeToolsList(page, []);
    await page.route("**/tools", async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 403,
          contentType: "application/json",
          body: JSON.stringify({ message: "You do not have permission to create tools" }),
        });
      } else {
        await route.fallback();
      }
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await openAddToolForm(page);
    await fillToolBasics(page, "denied_tool", "https://api.example.com/denied");
    await page.getByRole("button", { name: "Add tool" }).click();

    await expect(page.getByText(/You do not have permission to create tools/i)).toBeVisible();
    // Stays on the form so the user can correct/retry.
    await expect(page.getByRole("heading", { name: "Add tool" })).toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // Create — authentication types
  // ---------------------------------------------------------------------------

  const authScenarios: Array<{
    label: string;
    authLabelFor: string | null;
    fillCreds: (page: Page) => Promise<void>;
    expectAuth: (tool: Record<string, unknown>) => void;
  }> = [
    {
      label: "no authentication",
      authLabelFor: null,
      fillCreds: async () => {},
      expectAuth: (tool) => {
        expect(tool.auth_type).toBeUndefined();
      },
    },
    {
      label: "basic authentication",
      authLabelFor: "auth-basic",
      fillCreds: async (page) => {
        await page.locator("#basic-auth-username").fill("api_user");
        await page.locator("#basic-auth-password").fill("s3cret_pass");
      },
      expectAuth: (tool) => {
        expect(tool.auth_type).toBe("basic");
        expect(tool.auth_username).toBe("api_user");
        expect(tool.auth_password).toBe("s3cret_pass");
      },
    },
    {
      label: "bearer token authentication",
      authLabelFor: "auth-bearer",
      fillCreds: async (page) => {
        await page.locator("#bearer-token").fill("tok_abc123");
      },
      expectAuth: (tool) => {
        expect(tool.auth_type).toBe("bearer");
        expect(tool.auth_token).toBe("tok_abc123");
      },
    },
    {
      label: "custom header authentication",
      authLabelFor: "auth-custom",
      fillCreds: async (page) => {
        await page.getByRole("button", { name: "Add header" }).click();
        await page.locator("#header-key-0").fill("X-API-Key");
        await page.locator("#header-value-0").fill("key_value_123");
      },
      expectAuth: (tool) => {
        expect(tool.auth_type).toBe("authheaders");
        expect(tool.auth_header_key).toBe("X-API-Key");
        expect(tool.auth_header_value).toBe("key_value_123");
      },
    },
  ];

  for (const scenario of authScenarios) {
    test(`creates a tool with ${scenario.label}`, async ({ page }) => {
      let createBody: CreateToolPayload | null = null;

      await routeToolsList(page, []);
      await page.route("**/tools", async (route) => {
        if (route.request().method() === "POST") {
          createBody = route.request().postDataJSON() as CreateToolPayload;
          await route.fulfill({ status: 201, contentType: "application/json", body: "{}" });
        } else {
          await route.fallback();
        }
      });

      await page.goto(APP.TOOLS);
      await page.waitForLoadState("networkidle");

      await openAddToolForm(page);
      await fillToolBasics(page, "auth_tool", "https://api.example.com/secure");

      if (scenario.authLabelFor) {
        await page.getByRole("button", { name: "Advanced settings" }).click();
        await page.locator(`label[for="${scenario.authLabelFor}"]`).click();
        await scenario.fillCreds(page);
      }

      await page.getByRole("button", { name: "Add tool" }).click();

      await expect.poll(() => createBody).not.toBeNull();
      scenario.expectAuth(createBody!.tool);
    });
  }

  // ---------------------------------------------------------------------------
  // Edit
  // ---------------------------------------------------------------------------

  test("edits a tool and PUTs the updated fields", async ({ page }) => {
    const TOOL = makeTool("editable_tool", "edit-gw", {
      integrationType: "REST",
      requestType: "POST",
      inputSchema: { type: "object", properties: {} },
    });
    let putBody: UpdateToolPayload | null = null;

    await routeToolsList(page, [TOOL]);
    await page.route(`**/tools/${TOOL.id}`, async (route) => {
      const method = route.request().method();
      if (method === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(TOOL),
        });
      } else if (method === "PUT") {
        putBody = route.request().postDataJSON() as UpdateToolPayload;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...TOOL, customName: putBody.customName }),
        });
      } else {
        await route.fallback();
      }
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "More options for edit-gw" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();

    const panel = page.getByRole("region", { name: /Tools for edit-gw/i });
    await expect(panel).toBeVisible();

    await panel.getByRole("button", { name: "More options" }).first().click();
    await page.getByRole("menuitem", { name: "Edit" }).click();

    await expect(page.getByRole("heading", { name: "Edit tool" })).toBeVisible();

    const nameInput = page.locator("#tool-name");
    await expect(nameInput).toHaveValue("editable_tool");
    await nameInput.fill("editable_tool_renamed");

    await page.getByRole("button", { name: "Update tool" }).click();

    await expect.poll(() => putBody).not.toBeNull();
    expect(putBody!.name).toBe("editable_tool_renamed");
    expect(putBody!.customName).toBe("editable_tool_renamed");

    // Form closes back to the grid on success.
    await expect(page.getByRole("heading", { name: "Tools" })).toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // View schema
  // ---------------------------------------------------------------------------

  test("view schema dialog shows input and output schemas", async ({ page }) => {
    const TOOL = makeTool("schema_tool", "schema-gw", {
      inputSchema: { type: "object", properties: { query: { type: "string" } } },
      outputSchema: { type: "object", properties: { result: { type: "string" } } },
    });

    await routeToolsList(page, [TOOL]);

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "More options for schema-gw" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();

    const panel = page.getByRole("region", { name: /Tools for schema-gw/i });
    await expect(panel).toBeVisible();

    await panel.getByRole("button", { name: "View schema" }).first().click();

    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Tool schema")).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "Input" })).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "Output" })).toBeVisible();
    await expect(dialog.locator("pre").first()).toContainText("query");
    await expect(dialog.locator("pre").nth(1)).toContainText("result");

    await dialog.getByRole("button", { name: "Close" }).first().click();
    await expect(dialog).not.toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // Activate / Deactivate
  // ---------------------------------------------------------------------------

  test("deactivates an active tool and reflects the inactive status", async ({ page }) => {
    const TOOL = makeTool("toggle_tool", "toggle-gw", { enabled: true, reachable: true });
    let activateParam: string | null = null;

    await routeToolsList(page, [TOOL]);
    await page.route(`**/tools/${TOOL.id}/state*`, async (route) => {
      if (route.request().method() === "POST") {
        activateParam = new URL(route.request().url()).searchParams.get("activate");
        await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
      } else {
        await route.fallback();
      }
    });
    await page.route(`**/tools/${TOOL.id}`, async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...TOOL, enabled: false, reachable: false }),
        });
      } else {
        await route.fallback();
      }
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "More options for toggle-gw" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();

    const panel = page.getByRole("region", { name: /Tools for toggle-gw/i });
    await expect(panel).toBeVisible();
    await expect(panel.getByText("Active", { exact: true })).toBeVisible();

    await panel.getByRole("button", { name: "More options" }).first().click();
    await page.getByRole("menuitem", { name: "Deactivate" }).click();

    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: /toggle_tool.*deactivated/i }),
    ).toBeVisible();
    await expect.poll(() => activateParam).toBe("false");
    await expect(panel.getByText("Inactive", { exact: true })).toBeVisible();

    // The menu now offers re-activation.
    await panel.getByRole("button", { name: "More options" }).first().click();
    await expect(page.getByRole("menuitem", { name: "Activate" })).toBeVisible();
  });

  test("activates an inactive tool and reflects the active status", async ({ page }) => {
    const TOOL = makeTool("inactive_tool", "activate-gw", { enabled: false, reachable: false });
    let activateParam: string | null = null;

    await routeToolsList(page, [TOOL]);
    await page.route(`**/tools/${TOOL.id}/state*`, async (route) => {
      if (route.request().method() === "POST") {
        activateParam = new URL(route.request().url()).searchParams.get("activate");
        await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
      } else {
        await route.fallback();
      }
    });
    await page.route(`**/tools/${TOOL.id}`, async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...TOOL, enabled: true, reachable: true }),
        });
      } else {
        await route.fallback();
      }
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "More options for activate-gw" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();

    const panel = page.getByRole("region", { name: /Tools for activate-gw/i });
    await expect(panel).toBeVisible();
    await expect(panel.getByText("Inactive", { exact: true })).toBeVisible();

    await panel.getByRole("button", { name: "More options" }).first().click();
    await page.getByRole("menuitem", { name: "Activate" }).click();

    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: /inactive_tool.*activated/i }),
    ).toBeVisible();
    await expect.poll(() => activateParam).toBe("true");
    await expect(panel.getByText("Active", { exact: true })).toBeVisible();
  });

  test("shows an error toast and keeps status when activation fails", async ({ page }) => {
    const TOOL = makeTool("toggle_fail_tool", "fail-gw", { enabled: true, reachable: true });
    let getCount = 0;

    await routeToolsList(page, [TOOL]);
    await page.route(`**/tools/${TOOL.id}/state*`, async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 403,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Forbidden" }),
        });
      } else {
        await route.fallback();
      }
    });
    await page.route(`**/tools/${TOOL.id}`, async (route) => {
      if (route.request().method() === "GET") {
        getCount += 1;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(TOOL),
        });
      } else {
        await route.fallback();
      }
    });

    await page.goto(APP.TOOLS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "More options for fail-gw" }).click();
    await page.getByRole("menuitem", { name: "View Details" }).click();

    const panel = page.getByRole("region", { name: /Tools for fail-gw/i });
    await expect(panel).toBeVisible();

    await panel.getByRole("button", { name: "More options" }).first().click();
    await page.getByRole("menuitem", { name: "Deactivate" }).click();

    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: /Forbidden/i }),
    ).toBeVisible();

    // A failed toggle never re-fetches the tool and leaves the status untouched.
    await expect(panel.getByText("Active", { exact: true })).toBeVisible();
    expect(getCount).toBe(0);
  });
});
