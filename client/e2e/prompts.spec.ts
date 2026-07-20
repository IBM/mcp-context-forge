import { test, expect } from "./fixtures/api-mock";
import { APP } from "./utils/paths";
import type { PromptRead } from "../src/generated/types";

type Prompt = NonNullable<PromptRead>;

/** Body the create form POSTs to `/prompts` (see usePromptForm.getFormData). */
interface CreatePromptPayload {
  prompt: { name: string; template: string; description?: string | null; [key: string]: unknown };
  team_id?: string | null;
  visibility?: string;
}

/** Flat body the edit form PUTs to `/prompts/{id}` (see usePromptForm.getUpdateData). */
interface UpdatePromptPayload {
  name?: string;
  template?: string | null;
  description?: string | null;
  [key: string]: unknown;
}

function makePrompt(id: string, gatewaySlug: string, overrides: Partial<Prompt> = {}): Prompt {
  return {
    id,
    name: id,
    originalName: id,
    customName: id,
    customNameSlug: id.toLowerCase(),
    displayName: id,
    gatewayId: `gw-${gatewaySlug}`,
    gatewaySlug,
    description: `Description for ${id}`,
    template: "Summarize: {{topic}}",
    arguments: [{ name: "topic", required: true }],
    tags: [],
    enabled: true,
    visibility: "public",
    createdAt: "2026-04-10T10:00:00Z",
    updatedAt: "2026-04-10T10:00:00Z",
    ...overrides,
  };
}

test.describe("Prompts page", () => {
  test.beforeEach(async ({ page, apiMock }) => {
    await apiMock.mockMe();
    await page.addInitScript(() => {
      sessionStorage.setItem("mcpgateway_token", "mock-token-12345");
    });
  });

  test("truncates a long gateway name and keeps the overflow menu visible", async ({ page }) => {
    const longSlug =
      "openzeppelin-stylus-contracts-enterprise-edition-extended-long-server-name-instance";
    const prompts: Prompt[] = [
      makePrompt("summarize", longSlug),
      makePrompt("translate", longSlug),
    ];

    await page.route("**/prompts?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(prompts),
      });
    });

    await page.goto(APP.PROMPTS);
    await page.waitForLoadState("networkidle");

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

    await kebab.click();
    await expect(page.getByRole("menuitem", { name: "View details" })).toBeVisible();
  });

  test("creates a new prompt and shows it in the list", async ({ page }) => {
    const promptsList: Prompt[] = [];
    let createBody: CreatePromptPayload | null = null;

    await page.route("**/prompts?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(promptsList),
      });
    });
    await page.route("**/prompts", async (route) => {
      if (route.request().method() === "POST") {
        createBody = route.request().postDataJSON() as CreatePromptPayload;
        const created = makePrompt(createBody.prompt.name, "", {
          id: "prompt-created",
          gatewayId: null,
          gatewaySlug: null,
          displayName: createBody.prompt.name,
          template: createBody.prompt.template,
          description: createBody.prompt.description ?? null,
          arguments: [],
        });
        // Persist so the post-submit refetch surfaces the new prompt.
        promptsList.push(created);
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify(created),
        });
      } else {
        await route.fallback();
      }
    });

    await page.goto(APP.PROMPTS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Add prompts" }).click();
    await expect(page.getByRole("heading", { name: "Add prompt" })).toBeVisible();

    await page.locator("#name").fill("weekly_report");
    await page.locator("#template").fill("Generate a weekly report for {{ team }}");
    await page.getByRole("button", { name: "Add prompt" }).click();

    // The POST carried the entered fields.
    await expect.poll(() => createBody).not.toBeNull();
    expect(createBody!.prompt.name).toBe("weekly_report");
    expect(createBody!.prompt.template).toBe("Generate a weekly report for {{ team }}");

    // Form closes and the new prompt appears under the REST prompts group.
    await expect(page.getByRole("heading", { name: "Prompts" })).toBeVisible();
    await expect(page.getByText("REST prompts")).toBeVisible();
    await expect(page.getByText("weekly_report")).toBeVisible();
  });

  test("edits an existing prompt and shows the update", async ({ page }) => {
    const PROMPT = makePrompt("summarize", "", {
      id: "prompt-1",
      gatewayId: null,
      gatewaySlug: null,
      displayName: "summarize",
      description: "Original description",
      arguments: [],
    });
    const promptsList: Prompt[] = [PROMPT];
    let putBody: UpdatePromptPayload | null = null;

    await page.route("**/prompts?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(promptsList),
      });
    });
    await page.route(`**/prompts/${PROMPT.id}`, async (route) => {
      if (route.request().method() === "PUT") {
        putBody = route.request().postDataJSON() as UpdatePromptPayload;
        promptsList[0] = { ...promptsList[0], description: putBody.description ?? null };
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(promptsList[0]),
        });
      } else {
        await route.fallback();
      }
    });

    await page.goto(APP.PROMPTS);
    await page.waitForLoadState("networkidle");

    // Open the details panel for the REST prompts group.
    await page.getByRole("button", { name: "More options for REST prompts" }).click();
    await page.getByRole("menuitem", { name: "View details" }).click();

    const panel = page.getByRole("region", { name: /Prompt details:/ });
    await expect(panel).toBeVisible();

    // Definition tab -> row overflow -> Edit.
    await panel.getByRole("tab", { name: "Definition" }).click();
    await panel.getByRole("button", { name: "More options for summarize" }).click();
    await page.getByRole("menuitem", { name: "Edit" }).click();

    await expect(page.getByRole("heading", { name: "Edit prompt" })).toBeVisible();
    await expect(page.locator("#name")).toHaveValue("summarize");
    await expect(page.locator("#description")).toHaveValue("Original description");

    await page.locator("#description").fill("Updated description via e2e");
    await page.getByRole("button", { name: "Save changes" }).click();

    // The PUT carried the new description and a success toast is shown.
    await expect.poll(() => putBody).not.toBeNull();
    expect(putBody!.description).toBe("Updated description via e2e");
    await expect(page.locator("[data-sonner-toast]").filter({ hasText: /updated/i })).toBeVisible();

    // Reopen the panel and confirm the updated description is reflected.
    await page.getByRole("button", { name: "More options for REST prompts" }).click();
    await page.getByRole("menuitem", { name: "View details" }).click();
    await expect(page.getByText("Updated description via e2e")).toBeVisible();
  });

  test("restricts the edit form to name/visibility/tags for a federated prompt", async ({
    page,
  }) => {
    const PROMPT = makePrompt("summarize", "hugging-face", {
      id: "prompt-1",
      displayName: "summarize",
      description: "Upstream description",
      template: "Upstream template",
      arguments: [],
    });
    const promptsList: Prompt[] = [PROMPT];
    let putBody: UpdatePromptPayload | null = null;

    await page.route("**/prompts?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(promptsList),
      });
    });
    await page.route(`**/prompts/${PROMPT.id}`, async (route) => {
      if (route.request().method() === "PUT") {
        putBody = route.request().postDataJSON() as UpdatePromptPayload;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...PROMPT, name: putBody.name ?? PROMPT.name }),
        });
      } else {
        await route.fallback();
      }
    });

    await page.goto(APP.PROMPTS);
    await page.waitForLoadState("networkidle");

    // Open the federated group's panel and launch the edit form.
    await page.getByRole("button", { name: "More options for hugging-face" }).click();
    await page.getByRole("menuitem", { name: "View details" }).click();

    const panel = page.getByRole("region", { name: /Prompt details:/ });
    await panel.getByRole("tab", { name: "Definition" }).click();
    await panel.getByRole("button", { name: "More options for summarize" }).click();
    await page.getByRole("menuitem", { name: "Edit" }).click();

    await expect(page.getByRole("heading", { name: "Edit prompt" })).toBeVisible();

    // Upstream-managed fields are disabled; a notice explains why.
    await expect(page.getByRole("note")).toBeVisible();
    await expect(page.getByLabel(/template/i)).toBeDisabled();
    await expect(page.getByLabel(/arguments/i)).toBeDisabled();
    await expect(page.getByLabel("Description")).toBeDisabled();

    // Name / visibility / tags stay editable and a rename is persisted.
    await expect(page.locator("#name")).toBeEnabled();
    await page.locator("#name").fill("renamed_summarize");
    await page.getByRole("button", { name: "Save changes" }).click();

    await expect.poll(() => putBody).not.toBeNull();
    expect(putBody!.name).toBe("renamed_summarize");
  });

  test("renders a preview in the details panel Try it tab", async ({ page }) => {
    const PROMPT = makePrompt("summarize", "", {
      id: "prompt-1",
      gatewayId: null,
      gatewaySlug: null,
      displayName: "summarize",
      template: "Summarize: {{ topic }}",
      arguments: [{ name: "topic", required: true }],
    });

    await page.route("**/prompts?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([PROMPT]),
      });
    });

    // The render-only preview POSTs to `/prompts/{name}` (addressed by name).
    let renderBody: Record<string, string> | null = null;
    await page.route("**/prompts/summarize", async (route) => {
      if (route.request().method() === "POST") {
        renderBody = route.request().postDataJSON() as Record<string, string>;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            messages: [{ role: "user", content: { type: "text", text: "Summarize: Cats" } }],
            description: null,
          }),
        });
      } else {
        await route.fallback();
      }
    });

    await page.goto(APP.PROMPTS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "More options for REST prompts" }).click();
    await page.getByRole("menuitem", { name: "View details" }).click();

    const panel = page.getByRole("region", { name: /Prompt details:/ });
    await expect(panel).toBeVisible();

    // Fill the argument and run the render-only preview (Try it tab is default).
    await panel.getByLabel(/topic/).fill("Cats");
    await panel.getByRole("button", { name: "Preview" }).click();

    // The render request carried the argument value.
    await expect.poll(() => renderBody).not.toBeNull();
    expect(renderBody!.topic).toBe("Cats");

    // A success status row and the rendered message body are shown.
    await expect(panel).toContainText("200 OK");
    await expect(panel).toContainText("Summarize: Cats");
  });

  test("adds a tag to a prompt from the details panel", async ({ page }) => {
    const PROMPT = makePrompt("summarize", "", {
      id: "prompt-1",
      gatewayId: null,
      gatewaySlug: null,
      displayName: "summarize",
      tags: [],
      arguments: [],
    });
    let putBody: { tags?: string[] } | null = null;

    await page.route("**/prompts?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([PROMPT]),
      });
    });
    await page.route(`**/prompts/${PROMPT.id}`, async (route) => {
      if (route.request().method() === "PUT") {
        putBody = route.request().postDataJSON() as { tags?: string[] };
        // updateTags returns the prompt with the normalized tag list.
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...PROMPT, tags: putBody.tags ?? [] }),
        });
      } else {
        await route.fallback();
      }
    });

    await page.goto(APP.PROMPTS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "More options for REST prompts" }).click();
    await page.getByRole("menuitem", { name: "View details" }).click();

    const panel = page.getByRole("region", { name: /Prompt details:/ });
    await expect(panel).toBeVisible();

    // Expand the inline tag editor, enter a tag, and confirm.
    await panel.getByRole("button", { name: "Add tags" }).click();
    await panel.getByRole("textbox", { name: "Add tags" }).fill("urgent");
    await panel.getByRole("button", { name: "Add", exact: true }).click();

    // The PUT carried the full tag list and the new chip is rendered.
    await expect.poll(() => putBody).not.toBeNull();
    expect(putBody!.tags).toEqual(["urgent"]);
    await expect(panel.getByText("urgent")).toBeVisible();
  });
});
